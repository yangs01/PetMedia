from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.media.storage import Storage, validate_upload_image
from app.models import BrandProfile
from app.repositories.brand_repository import BrandRepository
from app.schemas.brand import BrandCreate, BrandRead, BrandUpdate


def to_brand_read(brand: BrandProfile) -> BrandRead:
    fields = {name: getattr(brand, name) for name in BrandRead.model_fields if name != "has_logo"}
    return BrandRead(**fields, has_logo=brand.logo_path is not None)


class BrandService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.brands = BrandRepository(session)

    async def create(self, request: BrandCreate) -> BrandProfile:
        brand = BrandProfile(**request.model_dump())
        self.session.add(brand)
        await self._commit_unique_name()
        return brand

    async def list(self, *, limit: int, offset: int):
        return await self.brands.list_all(limit=limit, offset=offset)

    async def get(self, brand_id: UUID) -> BrandProfile:
        brand = await self.brands.get(brand_id)
        if brand is None:
            raise NotFoundError("Brand not found.", details={"brand_id": str(brand_id)})
        return brand

    async def update(self, brand_id: UUID, request: BrandUpdate) -> BrandProfile:
        brand = await self.get(brand_id)
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(brand, field, value)
        await self._commit_unique_name()
        await self.session.refresh(brand)
        return brand

    async def set_logo(self, brand_id: UUID, data: bytes) -> BrandProfile:
        brand = await self.get(brand_id)
        image = validate_upload_image(
            data, max_bytes=self.settings.max_upload_bytes, max_pixels=self.settings.max_image_pixels
        )
        brand.logo_path = self.storage.save_bytes(f"brands/{brand_id}/{uuid4().hex}.{image.extension}", data)
        await self.session.commit()
        await self.session.refresh(brand)
        return brand

    async def _commit_unique_name(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError("A brand with this name already exists.", code="DUPLICATE_BRAND") from error
