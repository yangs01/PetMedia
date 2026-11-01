from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.dependencies import SessionDep, StorageDep
from app.services.asset_service import AssetService

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{asset_id}", response_class=FileResponse)
async def download_asset(asset_id: UUID, session: SessionDep, storage: StorageDep) -> FileResponse:
    path, mime_type = await AssetService(session, storage).resolve_file(asset_id)
    return FileResponse(path, media_type=mime_type)
