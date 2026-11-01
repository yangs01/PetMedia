from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.runtime import Runtime

from app.ai.nodes.common import ensure_status, load_task
from app.ai.prompts import load_prompt
from app.ai.providers.model_config import ModelRole
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.exceptions import StructuredOutputError
from app.core.status import TaskStatus
from app.models import TopicSuggestion
from app.repositories.task_repository import TaskRepository
from app.services.content_service import read_generation_context


async def generate_topics(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Create the next batch of topics. Earlier batches stay as history.

    The batch number comes from checkpointed state, so a retry targets the same
    batch: if that batch was already saved, it is reused instead of paying for
    another model call or adding duplicates.
    """
    deps = runtime.context
    task_id = UUID(state["task_id"])
    batch_number = state.get("topic_batch_number", 0) + 1
    feedback = state.get("topic_feedback")

    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        await ensure_status(session, task, TaskStatus.GENERATING_TOPICS, "generate_topics")
        await session.commit()
        repository = TaskRepository(session)
        existing = await repository.list_topic_batch(task_id, batch_number)
        previous_titles = [topic.title for topic in await repository.list_topics(task_id)]
        context = read_generation_context(task)

    if not existing:
        count = deps.settings.default_topic_count
        llm = deps.models.for_role(ModelRole.TOPIC_GENERATION)
        batch = await llm.generate_topics(
            context, count=count, feedback=feedback, previous_titles=previous_titles
        )
        if len(batch.topics) != count:
            raise StructuredOutputError(f"Expected {count} topics, got {len(batch.topics)}.")
        batch_id = uuid5(NAMESPACE_URL, f"{task_id}:topics:{batch_number}")
        existing = [
            TopicSuggestion(
                task_id=task_id,
                batch_id=batch_id,
                batch_number=batch_number,
                position=position,
                operator_feedback=feedback,
                provider=llm.name,
                prompt_version=load_prompt("topic_generation").version_label,
                **topic.model_dump(),
            )
            for position, topic in enumerate(batch.topics, start=1)
        ]
        async with deps.session_factory() as session:
            session.add_all(existing)
            await session.commit()

    return {
        "topic_batch_number": batch_number,
        "topic_candidate_ids": [str(topic.id) for topic in existing],
        "topic_feedback": None,
        "last_decision": None,
    }
