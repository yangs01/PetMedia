"""Read access to stored media. API responses expose URLs, never server file paths."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import MediaFileMissingError, NotFoundError
from app.media.storage import Storage
from app.models import GeneratedAsset
from app.repositories.asset_repository import AssetRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.asset import AssetRead


def asset_url(asset_id: UUID) -> str:
    return f"/api/v1/assets/{asset_id}"


def to_asset_read(asset: GeneratedAsset) -> AssetRead:
    return AssetRead(
        id=asset.id,
        slide_number=asset.slide_number,
        asset_version=asset.asset_version,
        status=asset.status,
        url=asset_url(asset.id),
        width=asset.width,
        height=asset.height,
        file_size=asset.file_size,
        sha256=asset.sha256,
        provider=asset.provider,
        is_mock=asset.is_mock,
        visual_feedback=asset.visual_feedback,
        source_content_version_id=asset.source_content_version_id,
        carousel_plan_id=asset.carousel_plan_id,
        created_at=asset.created_at,
    )


class AssetService:
    def __init__(self, session: AsyncSession, storage: Storage) -> None:
        self.session = session
        self.storage = storage

    async def list_for_task(self, task_id: UUID, *, include_history: bool) -> list[AssetRead]:
        assets = await AssetRepository(self.session).list_for_task(task_id, include_history=include_history)
        return [to_asset_read(asset) for asset in assets]

    async def resolve_file(self, asset_id: UUID) -> tuple[Path, str]:
        """Find a generated or product image by id and return its path and MIME type."""
        record = await AssetRepository(self.session).get(asset_id)
        if record is None:
            record = await ProductRepository(self.session).get_image(asset_id)
        if record is None:
            raise NotFoundError("Asset not found.", details={"asset_id": str(asset_id)})
        path = self.storage.path_for(record.file_path)
        if not path.is_file():
            raise MediaFileMissingError("The asset's file is missing from storage.", details={"asset_id": str(asset_id)})
        return path, record.mime_type
