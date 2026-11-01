from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.status import TaskStatus
from app.models import ApprovalRecord, ContentTask, ContentTaskProduct, TaskEvent, TopicSuggestion


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, task: ContentTask, product_ids: Sequence[UUID]) -> ContentTask:
        self.session.add(task)
        await self.session.flush()
        self.session.add_all(
            ContentTaskProduct(task_id=task.id, product_id=product_id, position=position)
            for position, product_id in enumerate(product_ids)
        )
        await self.session.flush()
        return task

    async def get(self, task_id: UUID) -> ContentTask | None:
        return await self.session.get(ContentTask, task_id, populate_existing=True)

    async def list_all(
        self, *, status: TaskStatus | None, limit: int, offset: int
    ) -> Sequence[ContentTask]:
        stmt = select(ContentTask).order_by(ContentTask.created_at.desc()).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(ContentTask.status == status)
        return (await self.session.scalars(stmt)).all()

    async def product_ids(self, task_id: UUID) -> list[UUID]:
        stmt = (
            select(ContentTaskProduct.product_id)
            .where(ContentTaskProduct.task_id == task_id)
            .order_by(ContentTaskProduct.position)
        )
        return list((await self.session.scalars(stmt)).all())

    async def compare_and_set_status(
        self, task: ContentTask, target: TaskStatus, values: dict[str, Any]
    ) -> bool:
        """Change status only if nobody changed the task since it was read."""
        result = await self.session.execute(
            update(ContentTask)
            .where(
                ContentTask.id == task.id,
                ContentTask.status == task.status,
                ContentTask.lock_version == task.lock_version,
            )
            .values(status=target, lock_version=ContentTask.lock_version + 1, **values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    async def add_event(self, event: TaskEvent) -> None:
        self.session.add(event)
        await self.session.flush()

    async def list_events(self, task_id: UUID, *, after_id: int, limit: int) -> Sequence[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
            .order_by(TaskEvent.id)
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()

    async def add_approval(self, record: ApprovalRecord) -> ApprovalRecord:
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_topics(self, task_id: UUID) -> Sequence[TopicSuggestion]:
        stmt = (
            select(TopicSuggestion)
            .where(TopicSuggestion.task_id == task_id)
            .order_by(TopicSuggestion.batch_number, TopicSuggestion.position)
        )
        return (await self.session.scalars(stmt)).all()

    async def list_topic_batch(self, task_id: UUID, batch_number: int) -> Sequence[TopicSuggestion]:
        stmt = (
            select(TopicSuggestion)
            .where(TopicSuggestion.task_id == task_id, TopicSuggestion.batch_number == batch_number)
            .order_by(TopicSuggestion.position)
        )
        return (await self.session.scalars(stmt)).all()

    async def latest_topic_batch_number(self, task_id: UUID) -> int | None:
        stmt = (
            select(TopicSuggestion.batch_number)
            .where(TopicSuggestion.task_id == task_id)
            .order_by(TopicSuggestion.batch_number.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def get_topic(self, topic_id: UUID) -> TopicSuggestion | None:
        return await self.session.get(TopicSuggestion, topic_id)

    async def recent_selected_topics(self, brand_id: UUID, limit: int = 20) -> list[str]:
        stmt = (
            select(TopicSuggestion.title)
            .join(ContentTask, ContentTask.id == TopicSuggestion.task_id)
            .where(ContentTask.brand_id == brand_id, TopicSuggestion.is_selected.is_(True))
            .order_by(TopicSuggestion.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())
