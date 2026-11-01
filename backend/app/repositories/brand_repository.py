from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BrandProfile


class BrandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, brand: BrandProfile) -> BrandProfile:
        self.session.add(brand)
        await self.session.flush()
        return brand

    async def get(self, brand_id: UUID) -> BrandProfile | None:
        return await self.session.get(BrandProfile, brand_id)

    async def list_all(self, *, limit: int, offset: int) -> Sequence[BrandProfile]:
        stmt = select(BrandProfile).order_by(BrandProfile.created_at.desc()).limit(limit).offset(offset)
        return (await self.session.scalars(stmt)).all()
