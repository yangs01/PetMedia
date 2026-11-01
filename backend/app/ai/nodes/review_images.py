import hashlib

from langgraph.types import interrupt

from app.ai.states.content_state import ContentState, ImageDecision, ReviewPayload
from app.core.status import TaskStatus


def image_review_key(state: ContentState) -> str:
    """Changes whenever any current image changes, which is what makes stale reviews detectable."""
    asset_ids = "|".join(sorted(state.get("generated_asset_ids", [])))
    return f"image:{hashlib.sha256(asset_ids.encode()).hexdigest()[:32]}"


async def review_images(state: ContentState) -> dict:
    """Pause until a human decides. No side effects: this node re-runs on resume."""
    payload = ReviewPayload(
        review_type="IMAGE",
        review_key=image_review_key(state),
        task_id=state["task_id"],
        candidate_ids=state.get("generated_asset_ids", []),
    )
    decision: ImageDecision = interrupt(payload.model_dump(), response_schema=ImageDecision)

    if decision.action == "approve":
        return {"last_decision": "approve"}
    if decision.action == "regenerate":
        return {
            "last_decision": "regenerate",
            "pending_slide_numbers": decision.slide_numbers,
            "image_request_key": f"regenerate:{decision.decision_id}",
            "image_feedback": decision.feedback,
        }
    return {"last_decision": "cancel", "workflow_status": TaskStatus.CANCELLED.value}


def route_after_image_review(state: ContentState) -> str:
    return {"approve": "finalize_content", "regenerate": "generate_images", "cancel": "__end__"}[state["last_decision"]]
