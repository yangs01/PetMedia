from uuid import UUID

from langgraph.runtime import Runtime

from app.ai.nodes.common import load_task
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.ai.validators.content_validator import validate_master_copy
from app.repositories.content_repository import ContentRepository
from app.schemas.content import MasterCopy
from app.services.content_service import read_generation_context


async def validate_copy(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Check the draft and store the report on the version.

    Errors trigger a bounded automatic revision. If errors remain, the draft still
    goes to the human with its report visible, since a person makes the final call.
    """
    deps = runtime.context
    version_id = state["current_content_version_id"]
    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        context = read_generation_context(task)
        version = await ContentRepository(session).get_version(UUID(version_id))
        report = validate_master_copy(MasterCopy.model_validate(version.content), context)
        # Validation metadata may change; the draft content itself never does.
        version.validation = report.to_record()
        await session.commit()

    fixes_used = state.get("copy_auto_fix_count", 0)
    if report.has_errors and fixes_used < deps.settings.max_copy_auto_fixes:
        return {
            "copy_auto_fix_count": fixes_used + 1,
            "pending_revision": {
                "key": f"autofix:{version_id}",
                "feedback": report.as_revision_feedback(),
            },
        }
    return {"copy_auto_fix_count": 0}


def route_after_validation(state: ContentState) -> str:
    return "generate_copy" if state.get("pending_revision") else "review_copy"
