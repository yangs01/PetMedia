from langgraph.runtime import Runtime

from app.ai.nodes.common import ensure_status, load_task
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.ai.validators.product_validator import ensure_context_is_usable
from app.core.status import TaskStatus
from app.services.content_service import build_generation_context, read_generation_context


async def load_context(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Freeze the product, brand and review facts this task will be grounded in."""
    async with runtime.context.session_factory() as session:
        task = await load_task(session, state["task_id"])
        if task.context_snapshot is None:
            context = await build_generation_context(session, task)
            ensure_context_is_usable(context)
            task.context_snapshot = context.model_dump(mode="json")
        else:
            context = read_generation_context(task)
        await ensure_status(session, task, TaskStatus.GENERATING_TOPICS, "load_context")
        await session.commit()
    return {
        "brand_id": str(task.brand_id),
        "product_ids": [product.id for product in context.products],
        "channels": task.channels,
        "image_count": task.image_count,
        "workflow_status": TaskStatus.GENERATING_TOPICS.value,
    }
