from langgraph.types import interrupt

from app.ai.states.content_state import ContentState, CopyDecision, ReviewPayload
from app.core.status import TaskStatus


def copy_review_key(state: ContentState) -> str:
    return f"copy:{state['current_content_version_id']}"


async def review_copy(state: ContentState) -> dict:
    """Pause until a human decides. No side effects: this node re-runs on resume."""
    payload = ReviewPayload(
        review_type="COPY",
        review_key=copy_review_key(state),
        task_id=state["task_id"],
        candidate_ids=[state["current_content_version_id"]],
    )
    decision: CopyDecision = interrupt(payload.model_dump(), response_schema=CopyDecision)

    if decision.action == "approve":
        # For a direct human edit, version_id is the new version the API just created.
        return {
            "last_decision": "approve",
            "current_content_version_id": decision.version_id,
            "approved_content_version_id": decision.version_id,
        }
    if decision.action == "revise":
        return {
            "last_decision": "revise",
            "pending_revision": {"key": f"revision:{decision.decision_id}", "feedback": decision.feedback},
        }
    return {"last_decision": "cancel", "workflow_status": TaskStatus.CANCELLED.value}


def route_after_copy_review(state: ContentState) -> str:
    return {"approve": "adapt_channels", "revise": "generate_copy", "cancel": "__end__"}[state["last_decision"]]
