from uuid import UUID

from fastapi import APIRouter, Query, UploadFile, status

from app.api.dependencies import SessionDep, SettingsDep, StorageDep, read_upload_limited
from app.schemas.product import ProductCreate, ProductImageRead, ProductRead, ProductUpdate
from app.services.product_service import ProductService, to_image_read

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(request: ProductCreate, session: SessionDep, settings: SettingsDep, storage: StorageDep):
    return await ProductService(session, settings, storage).create(request)


@router.get("", response_model=list[ProductRead])
async def list_products(
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_archived: bool = False,
):
    return await ProductService(session, settings, storage).list(
        limit=limit, offset=offset, include_archived=include_archived
    )


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(product_id: UUID, session: SessionDep, settings: SettingsDep, storage: StorageDep):
    return await ProductService(session, settings, storage).get(product_id)


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID, request: ProductUpdate, session: SessionDep, settings: SettingsDep, storage: StorageDep
):
    return await ProductService(session, settings, storage).update(product_id, request)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: UUID, session: SessionDep, settings: SettingsDep, storage: StorageDep) -> None:
    """Archives the product, so existing tasks keep their history."""
    await ProductService(session, settings, storage).archive(product_id)


@router.post("/{product_id}/images", response_model=ProductImageRead, status_code=status.HTTP_201_CREATED)
async def upload_product_image(
    product_id: UUID, file: UploadFile, session: SessionDep, settings: SettingsDep, storage: StorageDep
):
    data = await read_upload_limited(file, settings)
    image = await ProductService(session, settings, storage).add_image(product_id, data)
    return to_image_read(image)


@router.get("/{product_id}/images", response_model=list[ProductImageRead])
async def list_product_images(product_id: UUID, session: SessionDep, settings: SettingsDep, storage: StorageDep):
    images = await ProductService(session, settings, storage).list_images(product_id)
    return [to_image_read(image) for image in images]
