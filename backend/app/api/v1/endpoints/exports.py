from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.dependencies import SessionDep, StorageDep
from app.schemas.asset import ExportList
from app.services.export_service import ExportService

router = APIRouter(prefix="/tasks/{task_id}/exports", tags=["exports"])


@router.get("", response_model=ExportList)
async def list_exports(task_id: UUID, session: SessionDep, storage: StorageDep):
    return await ExportService(session, storage).list_exports(task_id)


async def _download(task_id: UUID, name: str, session, storage) -> FileResponse:
    export = await ExportService(session, storage).build(task_id, name)
    return FileResponse(export.path, media_type="application/zip", filename=export.filename)


@router.get("/instagram", response_class=FileResponse)
async def export_instagram(task_id: UUID, session: SessionDep, storage: StorageDep) -> FileResponse:
    return await _download(task_id, "instagram", session, storage)


@router.get("/facebook", response_class=FileResponse)
async def export_facebook(task_id: UUID, session: SessionDep, storage: StorageDep) -> FileResponse:
    return await _download(task_id, "facebook", session, storage)


@router.get("/all", response_class=FileResponse)
async def export_all(task_id: UUID, session: SessionDep, storage: StorageDep) -> FileResponse:
    return await _download(task_id, "all", session, storage)
