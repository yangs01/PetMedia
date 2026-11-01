from uuid import UUID

from langgraph.runtime import Runtime
from sqlalchemy import func

from app.ai.nodes.common import ensure_status, load_task
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.exceptions import WorkflowError
from app.core.status import AssetStatus, TaskStatus
from app.publishing import get_adapter
from app.publishing.base import SlideExport
from app.repositories.asset_repository import AssetRepository
from app.repositories.content_repository import ContentRepository
from app.services.task_service import transition_task


async def finalize_content(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Link channel content to the approved images and mark the task READY.

    One transaction, and safe to re-run: a repeat finds the task already READY.
    """
    deps = runtime.context
    task_id = UUID(state["task_id"])
    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        if task.status == TaskStatus.READY:
            return {"workflow_status": TaskStatus.READY.value}
        await ensure_status(session, task, TaskStatus.FINALIZING, "finalize_content")

        plan = await AssetRepository(session).get_plan(UUID(state["carousel_plan_id"]))
        alt_text = {slide["slide_number"]: slide["alt_text"] for slide in plan.slides}
        assets = await AssetRepository(session).list_for_task(task_id)
        if len(assets) != task.image_count or any(a.status != AssetStatus.APPROVED for a in assets):
            raise WorkflowError(
                "Finalization requires one approved image per slide.",
                code="IMAGES_NOT_APPROVED",
                details={"assets": len(assets), "image_count": task.image_count},
            )
        slides = [
            SlideExport(
                asset_id=str(asset.id),
                slide_number=asset.slide_number,
                alt_text=alt_text.get(asset.slide_number, ""),
                data=b"",
            )
            for asset in assets
        ]
        approved_id = UUID(state["approved_content_version_id"])
        for channel in await ContentRepository(session).list_channels(task_id):
            if channel.content_version_id == approved_id:
                channel.payload = get_adapter(channel.platform).finalize_payload(channel.payload, slides)
        await session.flush()
        await transition_task(
            session, task, TaskStatus.READY, node_name="finalize_content", completed_at=func.now()
        )
        await session.commit()
    return {"workflow_status": TaskStatus.READY.value}
