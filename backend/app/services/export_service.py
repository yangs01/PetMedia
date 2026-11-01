"""Builds downloadable ZIP packages from approved content only."""

import asyncio
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExportNotReadyError, NotFoundError, WorkflowError
from app.core.status import AssetStatus, TaskStatus
from app.media.storage import Storage
from app.models import ChannelContent, ContentTask, GeneratedAsset
from app.publishing import get_adapter
from app.publishing.base import SlideExport
from app.repositories.asset_repository import AssetRepository
from app.repositories.content_repository import ContentRepository
from app.schemas.asset import ExportList, ExportOption
from app.services.task_service import get_task_or_404


@dataclass(frozen=True)
class ExportFile:
    path: Path
    filename: str


class ExportService:
    def __init__(self, session: AsyncSession, storage: Storage) -> None:
        self.session = session
        self.storage = storage

    async def list_exports(self, task_id: UUID) -> ExportList:
        task = await get_task_or_404(self.session, task_id)
        ready = task.status == TaskStatus.READY
        names = [*task.channels, "all"]
        return ExportList(
            task_id=task.id,
            ready=ready,
            exports=[
                ExportOption(name=name, url=f"/api/v1/tasks/{task.id}/exports/{name}", available=ready)
                for name in names
            ],
        )

    async def build(self, task_id: UUID, name: str) -> ExportFile:
        """Return the ZIP for one platform or ``all``. Packages are immutable once READY."""
        task = await get_task_or_404(self.session, task_id)
        if task.status != TaskStatus.READY:
            raise ExportNotReadyError(
                "Exports are available once the task is READY.",
                details={"current_status": task.status.value},
            )
        if name != "all" and name not in task.channels:
            raise NotFoundError(f"This task has no '{name}' export.", details={"channels": task.channels})

        filename = f"content_task_{task.id}.zip" if name == "all" else f"content_task_{task.id}_{name}.zip"
        key = f"exports/{task.id}/{filename}"
        if not self.storage.exists(key):
            archive = await self._assemble(task, name)
            await asyncio.to_thread(self.storage.save_bytes, key, archive)
        return ExportFile(path=self.storage.path_for(key), filename=filename)

    async def _assemble(self, task: ContentTask, name: str) -> bytes:
        approved_id = task.approved_content_version_id
        assets = [
            asset
            for asset in await AssetRepository(self.session).list_for_task(task.id)
            if asset.status == AssetStatus.APPROVED and asset.source_content_version_id == approved_id
        ]
        if len(assets) != task.image_count:
            raise WorkflowError(
                "The approved images do not match the requested slide count.",
                code="EXPORT_INCONSISTENT",
                details={"approved_assets": len(assets), "image_count": task.image_count},
            )
        channels = {
            channel.platform: channel
            for channel in await ContentRepository(self.session).list_channels(task.id)
            if channel.content_version_id == approved_id
        }
        plan = await AssetRepository(self.session).get_plan(assets[0].carousel_plan_id)
        alt_text = {slide["slide_number"]: slide["alt_text"] for slide in plan.slides}

        def load_slides() -> list[SlideExport]:
            return [
                SlideExport(
                    asset_id=str(asset.id),
                    slide_number=asset.slide_number,
                    alt_text=alt_text.get(asset.slide_number, ""),
                    data=self.storage.read_bytes(asset.file_path),
                )
                for asset in assets
            ]

        slides = await asyncio.to_thread(load_slides)
        metadata = await self._metadata(task, assets, channels, slides)
        return await asyncio.to_thread(_zip_package, task, name, channels, slides, metadata)

    async def _metadata(
        self,
        task: ContentTask,
        assets: list[GeneratedAsset],
        channels: dict[str, ChannelContent],
        slides: list[SlideExport],
    ) -> dict[str, Any]:
        version = await ContentRepository(self.session).get_version(task.approved_content_version_id)
        by_id = {slide.asset_id: slide for slide in slides}
        return {
            "task_id": str(task.id),
            "thread_id": task.thread_id,
            "target_market": task.target_market,
            "selected_topic_id": str(task.selected_topic_id),
            "approved_content_version": {
                "id": str(version.id),
                "version_number": version.version_number,
                "generation_source": version.generation_source.value,
                "provider": version.provider,
                "prompt_version": version.prompt_version,
                "source_review_ids": version.content.get("source_review_ids", []),
            },
            "channels": {
                platform: {"id": str(channel.id), "provider": channel.provider, "prompt_version": channel.prompt_version}
                for platform, channel in channels.items()
            },
            "images": [
                {
                    "asset_id": str(asset.id),
                    "slide_number": asset.slide_number,
                    "asset_version": asset.asset_version,
                    "provider": asset.provider,
                    "is_mock": asset.is_mock,
                    "sha256": hashlib.sha256(by_id[str(asset.id)].data).hexdigest(),
                }
                for asset in assets
            ],
            "contains_mock_content": any(asset.is_mock for asset in assets)
            or version.provider == "mock"
            or any(channel.provider == "mock" for channel in channels.values()),
        }


def _zip_package(
    task: ContentTask,
    name: str,
    channels: dict[str, ChannelContent],
    slides: list[SlideExport],
    metadata: dict[str, Any],
) -> bytes:
    combined = name == "all"
    platforms = task.channels if combined else [name]
    buffer = io.BytesIO()
    # JPEGs are already compressed, so storing them saves CPU with no size penalty.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for platform in platforms:
            channel = channels.get(platform)
            if channel is None:
                raise WorkflowError(f"No {platform} content exists for the approved version.", code="EXPORT_INCONSISTENT")
            files = get_adapter(platform).package_files(channel.payload, slides, combined=combined)
            for path, data in files.items():
                compress = zipfile.ZIP_STORED if path.endswith(".jpg") else zipfile.ZIP_DEFLATED
                archive.writestr(f"{platform}/{path}", data, compress_type=compress)
            if not combined:
                platform_metadata = {**metadata, "platform": platform, "content": channel.payload}
                archive.writestr(f"{platform}/metadata.json", json.dumps(platform_metadata, indent=2))
        if combined:
            archive.writestr("metadata.json", json.dumps(metadata, indent=2))
            archive.writestr("README.md", _package_readme(task, metadata))
    return buffer.getvalue()


def _package_readme(task: ContentTask, metadata: dict[str, Any]) -> str:
    version = metadata["approved_content_version"]
    warning = (
        "\n**Warning: this package contains mock content and must not be published.**\n"
        if metadata["contains_mock_content"]
        else ""
    )
    return (
        f"# Content package for task {task.id}\n{warning}\n"
        f"Approved draft: version {version['version_number']} ({version['generation_source']}).\n\n"
        "- `instagram/`: caption, hashtags, alt text and carousel slides in posting order.\n"
        "- `facebook/`: post text and images.\n"
        "- `metadata.json`: provenance and versions.\n\n"
        "Publish manually. Review claims and images one last time before posting.\n"
    )
