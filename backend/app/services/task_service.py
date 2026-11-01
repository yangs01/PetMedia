"""Task lifecycle: creation, legal status changes, retry/cancel and read models."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    InvalidTaskStateError,
    NotFoundError,
    RequestValidationFailure,
)
from app.core.status import (
    AVAILABLE_ACTIONS,
    REVIEW_TYPE_BY_STATUS,
    JobType,
    ProductStatus,
    TaskStatus,
    is_legal_transition,
)
from app.models import ContentTask, TaskEvent
from app.publishing import supported_platforms
from app.repositories.asset_repository import AssetRepository
from app.repositories.brand_repository import BrandRepository
from app.repositories.content_repository import ContentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    ChannelContentRead,
    ContentVersionRead,
    TaskCreate,
    TaskDetail,
    TopicRead,
)
from app.services.asset_service import to_asset_read


async def transition_task(
    session: AsyncSession,
    task: ContentTask,
    target: TaskStatus,
    *,
    node_name: str | None = None,
    message: str | None = None,
    **values: Any,
) -> None:
    """Apply a legal status change using compare-and-set, and log it. Does not commit."""
    if not is_legal_transition(task.status, target):
        raise InvalidTaskStateError(
            f"A task cannot move from {task.status.value} to {target.value}.",
            details={"current_status": task.status.value, "requested_status": target.value},
        )
    repository = TaskRepository(session)
    previous = task.status
    if not await repository.compare_and_set_status(task, target, values):
        raise ConflictError(
            "The task was changed by another request. Reload it and try again.",
            code="CONCURRENT_UPDATE",
            details={"current_status": previous.value},
        )
    await session.refresh(task)
    await repository.add_event(
        TaskEvent(
            task_id=task.id,
            event_type="STATUS_CHANGED",
            from_status=previous.value,
            to_status=target.value,
            node_name=node_name,
            message=message,
        )
    )


async def get_task_or_404(session: AsyncSession, task_id: UUID) -> ContentTask:
    task = await TaskRepository(session).get(task_id)
    if task is None:
        raise NotFoundError("Task not found.", details={"task_id": str(task_id)})
    return task


class TaskService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tasks = TaskRepository(session)
        self.jobs = JobRepository(session)

    async def create_task(self, request: TaskCreate) -> ContentTask:
        if await BrandRepository(self.session).get(request.brand_id) is None:
            raise RequestValidationFailure("The brand does not exist.", details={"brand_id": str(request.brand_id)})
        await self._validate_products(request.product_ids)
        channels = list(dict.fromkeys(channel.lower() for channel in request.channels))
        unsupported = set(channels) - set(supported_platforms())
        if unsupported:
            raise RequestValidationFailure(
                "Unsupported channel.",
                details={"unsupported": sorted(unsupported), "supported": supported_platforms()},
            )
        task_id = uuid4()
        task = ContentTask(
            id=task_id,
            thread_id=f"content-task-{task_id}",
            brand_id=request.brand_id,
            status=TaskStatus.CREATED,
            lock_version=0,
            target_market=request.target_market or self.settings.default_target_market,
            target_audience=request.target_audience,
            marketing_goal=request.marketing_goal,
            operator_instructions=request.operator_instructions,
            channels=channels,
            image_count=request.image_count or self.settings.default_image_count,
            target_word_count=request.target_word_count or self.settings.default_target_word_count,
        )
        await self.tasks.add(task, list(dict.fromkeys(request.product_ids)))
        await transition_task(self.session, task, TaskStatus.QUEUED, message="Task created.")
        await self.jobs.enqueue(
            task_id=task.id,
            job_type=JobType.START_CONTENT_WORKFLOW,
            idempotency_key=f"start:{task.id}",
            max_attempts=self.settings.job_max_attempts,
        )
        await self.session.commit()
        return task

    async def _validate_products(self, product_ids: list[UUID]) -> None:
        products = await ProductRepository(self.session).get_many(product_ids)
        active = {product.id for product in products if product.status == ProductStatus.ACTIVE}
        missing = [str(product_id) for product_id in product_ids if product_id not in active]
        if missing:
            raise RequestValidationFailure(
                "Some products do not exist or are archived.", details={"product_ids": missing}
            )

    async def retry_task(self, task_id: UUID) -> ContentTask:
        """Requeue a failed task. The graph continues from its last checkpoint."""
        task = await get_task_or_404(self.session, task_id)
        if task.status != TaskStatus.FAILED:
            raise InvalidTaskStateError(
                "Only failed tasks can be retried.", details={"current_status": task.status.value}
            )
        # If the failed job carried an unconsumed human decision, it must travel with the
        # retry; otherwise the decision would be lost and the graph would stay interrupted.
        failed_job = await self.jobs.latest_for_task(task_id)
        payload = dict(failed_job.payload) if failed_job else {}
        await transition_task(self.session, task, TaskStatus.QUEUED, message="Retry requested.", last_error=None)
        await self.jobs.enqueue(
            task_id=task.id,
            job_type=JobType.RETRY_WORKFLOW,
            idempotency_key=f"retry:{task.id}:{task.lock_version}",
            max_attempts=self.settings.job_max_attempts,
            payload=payload,
        )
        await self.session.commit()
        return task

    async def cancel_task(self, task_id: UUID) -> ContentTask:
        """Cancel a task that is not paused at a review. Reviews cancel through their decision."""
        task = await get_task_or_404(self.session, task_id)
        if task.status == TaskStatus.QUEUED:
            if not await self.jobs.cancel_pending(task_id):
                raise InvalidTaskStateError(
                    "A worker has already started this task.", details={"current_status": task.status.value}
                )
        elif task.status != TaskStatus.FAILED:
            raise InvalidTaskStateError(
                "This task cannot be cancelled now. Use the review decision endpoint at a review stage.",
                details={"current_status": task.status.value},
            )
        await transition_task(self.session, task, TaskStatus.CANCELLED, message="Cancelled by operator.")
        await self.session.commit()
        return task

    async def list_tasks(self, *, status: TaskStatus | None, limit: int, offset: int):
        return await self.tasks.list_all(status=status, limit=limit, offset=offset)

    async def list_events(self, task_id: UUID, *, after_id: int, limit: int):
        await get_task_or_404(self.session, task_id)
        return await self.tasks.list_events(task_id, after_id=after_id, limit=limit)

    async def list_topics(self, task_id: UUID):
        await get_task_or_404(self.session, task_id)
        return await self.tasks.list_topics(task_id)

    async def list_versions(self, task_id: UUID):
        await get_task_or_404(self.session, task_id)
        return await ContentRepository(self.session).list_versions(task_id)

    async def list_channels(self, task_id: UUID):
        await get_task_or_404(self.session, task_id)
        return await ContentRepository(self.session).list_channels(task_id)

    async def get_detail(self, task_id: UUID) -> TaskDetail:
        task = await get_task_or_404(self.session, task_id)
        content = ContentRepository(self.session)
        assets = AssetRepository(self.session)

        topic = await self.tasks.get_topic(task.selected_topic_id) if task.selected_topic_id else None
        version = (
            await content.get_version(task.current_content_version_id)
            if task.current_content_version_id
            else None
        )
        plan = await assets.latest_plan(task.id)
        channels = await content.list_channels(task.id)
        decision_in_progress = await self.jobs.has_active_job(task.id)
        return TaskDetail(
            id=task.id,
            thread_id=task.thread_id,
            brand_id=task.brand_id,
            product_ids=await self.tasks.product_ids(task.id),
            status=task.status,
            version=task.lock_version,
            review_stage=REVIEW_TYPE_BY_STATUS.get(task.status),
            review_key=task.current_review_key,
            available_actions=list(AVAILABLE_ACTIONS.get(task.status, ())),
            decision_in_progress=decision_in_progress,
            target_market=task.target_market,
            target_audience=task.target_audience,
            marketing_goal=task.marketing_goal,
            channels=task.channels,
            image_count=task.image_count,
            selected_topic=TopicRead.model_validate(topic) if topic else None,
            current_version=ContentVersionRead.model_validate(version) if version else None,
            approved_version_id=task.approved_content_version_id,
            carousel_plan=plan.slides if plan else None,
            assets=[to_asset_read(asset) for asset in await assets.list_for_task(task.id)],
            channel_contents=[ChannelContentRead.model_validate(channel) for channel in channels],
            error=task.last_error,
            created_at=task.created_at,
            updated_at=task.updated_at,
            completed_at=task.completed_at,
        )
