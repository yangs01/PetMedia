"""Helpers shared by workflow nodes."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.validators.content_validator import ValidationReport, validate_text
from app.core.exceptions import NotFoundError
from app.core.status import TaskStatus
from app.models import ContentTask
from app.repositories.task_repository import TaskRepository
from app.schemas.content import GenerationContext
from app.services.task_service import transition_task


async def load_task(session: AsyncSession, task_id: str) -> ContentTask:
    task = await TaskRepository(session).get(UUID(task_id))
    if task is None:
        raise NotFoundError("Task not found.", details={"task_id": task_id})
    return task


async def ensure_status(session: AsyncSession, task: ContentTask, target: TaskStatus, node_name: str) -> None:
    """Move to ``target`` unless already there, so a re-executed node is harmless."""
    if task.status != target:
        await transition_task(session, task, target, node_name=node_name)


async def generate_with_validation[T: BaseModel](
    generate: Callable[[str | None], Awaitable[T]],
    context: GenerationContext,
    *,
    max_fixes: int,
) -> tuple[T, ValidationReport]:
    """Generate, validate, and ask for a bounded number of corrections.

    Output that still fails is returned with its report so a human can see it.
    It is never silently accepted or silently dropped.
    """
    feedback: str | None = None
    for _ in range(max_fixes):
        output = await generate(feedback)
        report = validate_text(output.full_text(), context)
        if not report.has_errors:
            return output, report
        feedback = report.as_revision_feedback()
    output = await generate(feedback)
    return output, validate_text(output.full_text(), context)
