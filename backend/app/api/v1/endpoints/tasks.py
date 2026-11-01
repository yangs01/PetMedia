from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import SessionDep, SettingsDep, StorageDep
from app.core.status import TaskStatus
from app.schemas.asset import AssetRead
from app.schemas.task import (
    ChannelContentRead,
    ContentVersionRead,
    TaskCreate,
    TaskCreated,
    TaskDetail,
    TaskEventRead,
    TaskSummary,
    TopicRead,
)
from app.services.asset_service import AssetService
from app.services.task_service import TaskService, get_task_or_404

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_task(request: TaskCreate, session: SessionDep, settings: SettingsDep):
    """Creates the task and queues the workflow. The worker does the generation."""
    task = await TaskService(session, settings).create_task(request)
    return TaskCreated(task_id=task.id, thread_id=task.thread_id, status=task.status)


@router.get("", response_model=list[TaskSummary])
async def list_tasks(
    session: SessionDep,
    settings: SettingsDep,
    task_status: TaskStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return await TaskService(session, settings).list_tasks(status=task_status, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: UUID, session: SessionDep, settings: SettingsDep):
    return await TaskService(session, settings).get_detail(task_id)


@router.get("/{task_id}/events", response_model=list[TaskEventRead])
async def list_task_events(
    task_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    after_id: int = Query(default=0, ge=0, description="Return events after this event id (polling cursor)."),
    limit: int = Query(default=100, ge=1, le=500),
):
    return await TaskService(session, settings).list_events(task_id, after_id=after_id, limit=limit)


@router.get("/{task_id}/topics", response_model=list[TopicRead])
async def list_task_topics(task_id: UUID, session: SessionDep, settings: SettingsDep):
    return await TaskService(session, settings).list_topics(task_id)


@router.get("/{task_id}/versions", response_model=list[ContentVersionRead])
async def list_task_versions(task_id: UUID, session: SessionDep, settings: SettingsDep):
    return await TaskService(session, settings).list_versions(task_id)


@router.get("/{task_id}/assets", response_model=list[AssetRead])
async def list_task_assets(
    task_id: UUID,
    session: SessionDep,
    storage: StorageDep,
    include_history: bool = Query(default=False, description="Also return superseded image versions."),
):
    await get_task_or_404(session, task_id)
    return await AssetService(session, storage).list_for_task(task_id, include_history=include_history)


@router.get("/{task_id}/channels", response_model=list[ChannelContentRead])
async def list_task_channels(task_id: UUID, session: SessionDep, settings: SettingsDep):
    return await TaskService(session, settings).list_channels(task_id)


@router.post("/{task_id}/retry", response_model=TaskCreated, status_code=status.HTTP_202_ACCEPTED)
async def retry_task(task_id: UUID, session: SessionDep, settings: SettingsDep):
    """Requeues a FAILED task. Work already completed is not repeated."""
    task = await TaskService(session, settings).retry_task(task_id)
    return TaskCreated(task_id=task.id, thread_id=task.thread_id, status=task.status)


@router.post("/{task_id}/cancel", response_model=TaskCreated)
async def cancel_task(task_id: UUID, session: SessionDep, settings: SettingsDep):
    """Cancels a QUEUED or FAILED task. Paused tasks cancel through their review decision."""
    task = await TaskService(session, settings).cancel_task(task_id)
    return TaskCreated(task_id=task.id, thread_id=task.thread_id, status=task.status)
