from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChannelContent, ContentTask, ContentVersion


class ContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_version(self, version_id: UUID) -> ContentVersion | None:
        return await self.session.get(ContentVersion, version_id, populate_existing=True)

    async def get_version_by_key(self, task_id: UUID, idempotency_key: str) -> ContentVersion | None:
        stmt = select(ContentVersion).where(
            ContentVersion.task_id == task_id, ContentVersion.idempotency_key == idempotency_key
        )
        return await self.session.scalar(stmt)

    async def list_versions(self, task_id: UUID) -> Sequence[ContentVersion]:
        stmt = (
            select(ContentVersion)
            .where(ContentVersion.task_id == task_id)
            .order_by(ContentVersion.version_number)
        )
        return (await self.session.scalars(stmt)).all()

    async def add_version(self, version: ContentVersion) -> ContentVersion:
        """Insert a new draft with the next version number.

        The task row lock serializes numbering; the unique constraint backs it up.
        """
        await self.session.execute(
            select(ContentTask.id).where(ContentTask.id == version.task_id).with_for_update()
        )
        current_max = await self.session.scalar(
            select(func.max(ContentVersion.version_number)).where(
                ContentVersion.task_id == version.task_id
            )
        )
        version.version_number = (current_max or 0) + 1
        self.session.add(version)
        await self.session.flush()
        return version

    async def get_channel(
        self, task_id: UUID, content_version_id: UUID, platform: str
    ) -> ChannelContent | None:
        stmt = select(ChannelContent).where(
            ChannelContent.task_id == task_id,
            ChannelContent.content_version_id == content_version_id,
            ChannelContent.platform == platform,
        )
        return await self.session.scalar(stmt)

    async def add_channel(self, channel: ChannelContent) -> ChannelContent:
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def list_channels(self, task_id: UUID) -> Sequence[ChannelContent]:
        stmt = (
            select(ChannelContent)
            .where(ChannelContent.task_id == task_id)
            .order_by(ChannelContent.platform)
        )
        return (await self.session.scalars(stmt)).all()
