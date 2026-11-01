from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.status import ProductStatus
from app.models import Product, ProductAsset


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.flush()
        return product

    async def get(self, product_id: UUID) -> Product | None:
        return await self.session.get(Product, product_id)

    async def list_all(
        self, *, limit: int, offset: int, include_archived: bool = False
    ) -> Sequence[Product]:
        stmt = select(Product).order_by(Product.created_at.desc()).limit(limit).offset(offset)
        if not include_archived:
            stmt = stmt.where(Product.status == ProductStatus.ACTIVE)
        return (await self.session.scalars(stmt)).all()

    async def get_many(self, product_ids: Sequence[UUID]) -> Sequence[Product]:
        return (await self.session.scalars(select(Product).where(Product.id.in_(product_ids)))).all()

    async def add_image(self, image: ProductAsset) -> ProductAsset:
        self.session.add(image)
        await self.session.flush()
        return image

    async def get_image(self, image_id: UUID) -> ProductAsset | None:
        return await self.session.get(ProductAsset, image_id)

    async def list_images(self, product_id: UUID) -> Sequence[ProductAsset]:
        stmt = (
            select(ProductAsset)
            .where(ProductAsset.product_id == product_id)
            .order_by(ProductAsset.created_at)
        )
        return (await self.session.scalars(stmt)).all()
