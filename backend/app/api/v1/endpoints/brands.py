from uuid import UUID

from fastapi import APIRouter, Query, UploadFile, status

from app.api.dependencies import SessionDep, SettingsDep, StorageDep, read_upload_limited
from app.schemas.brand import BrandCreate, BrandRead, BrandUpdate
from app.services.brand_service import BrandService, to_brand_read

router = APIRouter(prefix="/brands", tags=["brands"])


@router.post("", response_model=BrandRead, status_code=status.HTTP_201_CREATED)
async def create_brand(request: BrandCreate, session: SessionDep, settings: SettingsDep, storage: StorageDep):
    return to_brand_read(await BrandService(session, settings, storage).create(request))


@router.get("", response_model=list[BrandRead])
async def list_brands(
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    brands = await BrandService(session, settings, storage).list(limit=limit, offset=offset)
    return [to_brand_read(brand) for brand in brands]


@router.get("/{brand_id}", response_model=BrandRead)
async def get_brand(brand_id: UUID, session: SessionDep, settings: SettingsDep, storage: StorageDep):
    return to_brand_read(await BrandService(session, settings, storage).get(brand_id))


@router.patch("/{brand_id}", response_model=BrandRead)
async def update_brand(
    brand_id: UUID, request: BrandUpdate, session: SessionDep, settings: SettingsDep, storage: StorageDep
):
    return to_brand_read(await BrandService(session, settings, storage).update(brand_id, request))


@router.post("/{brand_id}/logo", response_model=BrandRead)
async def upload_brand_logo(
    brand_id: UUID, file: UploadFile, session: SessionDep, settings: SettingsDep, storage: StorageDep
):
    data = await read_upload_limited(file, settings)
    return to_brand_read(await BrandService(session, settings, storage).set_logo(brand_id, data))
