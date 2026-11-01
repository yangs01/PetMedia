from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import SessionDep, SettingsDep, StorageDep
from app.schemas.review import ReviewCreate, ReviewRead
from app.services.product_service import ProductService

router = APIRouter(prefix="/products/{product_id}/reviews", tags=["reviews"])


@router.post("", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_review(
    product_id: UUID, request: ReviewCreate, session: SessionDep, settings: SettingsDep, storage: StorageDep
):
    return await ProductService(session, settings, storage).add_review(product_id, request)


@router.get("", response_model=list[ReviewRead])
async def list_reviews(product_id: UUID, session: SessionDep, settings: SettingsDep, storage: StorageDep):
    return await ProductService(session, settings, storage).list_reviews(product_id)
