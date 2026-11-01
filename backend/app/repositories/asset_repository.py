from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.status import AssetStatus
from app.models import CarouselPlan, ContentTask, GeneratedAsset

CURRENT_STATUSES = (AssetStatus.ACTIVE, AssetStatus.APPROVED)


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, asset_id: UUID) -> GeneratedAsset | None:
        return await self.session.get(GeneratedAsset, asset_id)

    async def get_plan(self, plan_id: UUID) -> CarouselPlan | None:
        return await self.session.get(CarouselPlan, plan_id)

    async def get_plan_for_version(self, task_id: UUID, content_version_id: UUID) -> CarouselPlan | None:
        stmt = select(CarouselPlan).where(
            CarouselPlan.task_id == task_id, CarouselPlan.content_version_id == content_version_id
        )
        return await self.session.scalar(stmt)

    async def latest_plan(self, task_id: UUID) -> CarouselPlan | None:
        stmt = (
            select(CarouselPlan)
            .where(CarouselPlan.task_id == task_id)
            .order_by(CarouselPlan.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def add_plan(self, plan: CarouselPlan) -> CarouselPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def list_for_task(
        self, task_id: UUID, *, include_history: bool = False
    ) -> Sequence[GeneratedAsset]:
        stmt = (
            select(GeneratedAsset)
            .where(GeneratedAsset.task_id == task_id)
            .order_by(GeneratedAsset.slide_number, GeneratedAsset.asset_version)
        )
        if not include_history:
            stmt = stmt.where(GeneratedAsset.status.in_(CURRENT_STATUSES))
        return (await self.session.scalars(stmt)).all()

    async def get_by_request(
        self, task_id: UUID, slide_number: int, request_key: str
    ) -> GeneratedAsset | None:
        stmt = select(GeneratedAsset).where(
            GeneratedAsset.task_id == task_id,
            GeneratedAsset.slide_number == slide_number,
            GeneratedAsset.request_key == request_key,
        )
        return await self.session.scalar(stmt)

    async def next_asset_version(self, task_id: UUID, slide_number: int) -> int:
        current_max = await self.session.scalar(
            select(func.max(GeneratedAsset.asset_version)).where(
                GeneratedAsset.task_id == task_id, GeneratedAsset.slide_number == slide_number
            )
        )
        return (current_max or 0) + 1

    async def replace_current(self, asset: GeneratedAsset) -> GeneratedAsset:
        """Make ``asset`` the slide's current image and keep the old one as history."""
        await self.session.execute(
            select(ContentTask.id).where(ContentTask.id == asset.task_id).with_for_update()
        )
        await self.session.execute(
            update(GeneratedAsset)
            .where(
                GeneratedAsset.task_id == asset.task_id,
                GeneratedAsset.slide_number == asset.slide_number,
                GeneratedAsset.status.in_(CURRENT_STATUSES),
            )
            .values(status=AssetStatus.SUPERSEDED)
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def approve_current(self, task_id: UUID) -> None:
        await self.session.execute(
            update(GeneratedAsset)
            .where(GeneratedAsset.task_id == task_id, GeneratedAsset.status == AssetStatus.ACTIVE)
            .values(status=AssetStatus.APPROVED)
        )
