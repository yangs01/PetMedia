from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.status import ProductStatus
from app.media.storage import Storage, validate_upload_image
from app.models import CustomerReview, Product, ProductAsset
from app.repositories.product_repository import ProductRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.product import ProductCreate, ProductImageRead, ProductUpdate
from app.schemas.review import ReviewCreate
from app.services.asset_service import asset_url


def to_image_read(image: ProductAsset) -> ProductImageRead:
    return ProductImageRead(
        id=image.id,
        product_id=image.product_id,
        url=asset_url(image.id),
        mime_type=image.mime_type,
        width=image.width,
        height=image.height,
        created_at=image.created_at,
    )


class ProductService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.products = ProductRepository(session)

    async def create(self, request: ProductCreate) -> Product:
        values = request.model_dump(mode="json", exclude={"price"})
        product = Product(**values, price=request.price)
        self.session.add(product)
        await self._commit_unique_sku()
        return product

    async def list(self, *, limit: int, offset: int, include_archived: bool):
        return await self.products.list_all(limit=limit, offset=offset, include_archived=include_archived)

    async def get(self, product_id: UUID) -> Product:
        product = await self.products.get(product_id)
        if product is None:
            raise NotFoundError("Product not found.", details={"product_id": str(product_id)})
        return product

    async def update(self, product_id: UUID, request: ProductUpdate) -> Product:
        product = await self.get(product_id)
        changes = request.model_dump(mode="json", exclude_unset=True, exclude={"price"})
        if "price" in request.model_fields_set:
            changes["price"] = request.price
        for field, value in changes.items():
            setattr(product, field, value)
        await self._commit_unique_sku()
        await self.session.refresh(product)
        return product

    async def archive(self, product_id: UUID) -> None:
        """Soft delete: existing tasks and their provenance keep referring to the product."""
        product = await self.get(product_id)
        product.status = ProductStatus.ARCHIVED
        await self.session.commit()

    async def add_image(self, product_id: UUID, data: bytes) -> ProductAsset:
        await self.get(product_id)
        image = validate_upload_image(
            data, max_bytes=self.settings.max_upload_bytes, max_pixels=self.settings.max_image_pixels
        )
        # A generated name means the client's filename can never influence the path.
        key = f"products/{product_id}/{uuid4().hex}.{image.extension}"
        self.storage.save_bytes(key, data)
        record = ProductAsset(
            product_id=product_id,
            file_path=key,
            mime_type=image.mime_type,
            width=image.width,
            height=image.height,
        )
        await self.products.add_image(record)
        await self.session.commit()
        return record

    async def list_images(self, product_id: UUID):
        await self.get(product_id)
        return await self.products.list_images(product_id)

    async def add_review(self, product_id: UUID, request: ReviewCreate) -> CustomerReview:
        await self.get(product_id)
        review = await ReviewRepository(self.session).add(
            CustomerReview(product_id=product_id, **request.model_dump())
        )
        await self.session.commit()
        return review

    async def list_reviews(self, product_id: UUID):
        await self.get(product_id)
        return await ReviewRepository(self.session).list_for_product(product_id)

    async def _commit_unique_sku(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError("A product with this SKU already exists.", code="DUPLICATE_SKU") from error
