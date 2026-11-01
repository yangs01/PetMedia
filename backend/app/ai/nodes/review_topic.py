from langgraph.types import interrupt

from app.ai.states.content_state import ContentState, ReviewPayload, TopicDecision
from app.core.status import TaskStatus


def topic_review_key(state: ContentState) -> str:
    return f"topic:batch:{state['topic_batch_number']}"


async def review_topic(state: ContentState) -> dict:
    """Pause until a human decides.

    LangGraph re-runs this node from the top on resume, so nothing before
    ``interrupt`` may have side effects. Business effects of the decision were
    already committed by ApprovalService before the job that resumes this graph.
    """
    payload = ReviewPayload(
        review_type="TOPIC",
        review_key=topic_review_key(state),
        task_id=state["task_id"],
        candidate_ids=state.get("topic_candidate_ids", []),
    )
    decision: TopicDecision = interrupt(payload.model_dump(), response_schema=TopicDecision)

    if decision.action == "select":
        return {"last_decision": "select", "selected_topic_id": decision.selected_topic_id}
    if decision.action == "regenerate":
        return {"last_decision": "regenerate", "topic_feedback": decision.feedback}
    return {"last_decision": "cancel", "workflow_status": TaskStatus.CANCELLED.value}


def route_after_topic_review(state: ContentState) -> str:
    return {"select": "generate_copy", "regenerate": "generate_topics", "cancel": "__end__"}[state["last_decision"]]
