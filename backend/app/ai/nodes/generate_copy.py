from uuid import UUID

from langgraph.runtime import Runtime

from app.ai.nodes.common import ensure_status, load_task
from app.ai.prompts import load_prompt
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.status import GenerationSource, TaskStatus
from app.models import ContentVersion
from app.repositories.content_repository import ContentRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.content import MasterCopy, TopicOutput
from app.services.content_service import read_generation_context


async def generate_copy(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Write the first draft, or a new version from a revision request. Never overwrites.

    Each draft has an idempotency key derived from what caused it, so a retry finds
    the version it already saved instead of creating another.
    """
    deps = runtime.context
    task_id = UUID(state["task_id"])
    revision = state.get("pending_revision")
    selected_topic_id = state["selected_topic_id"]
    idempotency_key = revision["key"] if revision else f"initial:{selected_topic_id}"

    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        await ensure_status(session, task, TaskStatus.GENERATING_COPY, "generate_copy")
        await session.commit()
        content = ContentRepository(session)
        saved = await content.get_version_by_key(task_id, idempotency_key)
        topic_record = await TaskRepository(session).get_topic(UUID(selected_topic_id))
        context = read_generation_context(task)
        parent = (
            await content.get_version(UUID(state["current_content_version_id"])) if revision else None
        )

    if saved is None:
        topic = TopicOutput.model_validate(topic_record, from_attributes=True)
        if revision:
            current = MasterCopy.model_validate(parent.content)
            draft = await deps.llm.revise_master_copy(
                context, topic=topic, current=current, feedback=revision["feedback"]
            )
        else:
            draft = await deps.llm.generate_master_copy(context, topic=topic)

        prompt_name = "copy_revision" if revision else "copy_generation"
        async with deps.session_factory() as session:
            saved = await ContentRepository(session).add_version(
                ContentVersion(
                    task_id=task_id,
                    content=draft.model_dump(mode="json"),
                    generation_source=GenerationSource.AI_REVISION if revision else GenerationSource.AI_INITIAL,
                    parent_version_id=parent.id if parent else None,
                    revision_feedback=revision["feedback"] if revision else None,
                    idempotency_key=idempotency_key,
                    provider=deps.llm.name,
                    prompt_version=load_prompt(prompt_name).version_label,
                )
            )
            task = await load_task(session, state["task_id"])
            task.current_content_version_id = saved.id
            await session.commit()
    else:
        # A previous attempt may have crashed between saving the draft and moving on.
        async with deps.session_factory() as session:
            task = await load_task(session, state["task_id"])
            task.current_content_version_id = saved.id
            await session.commit()

    updates: dict = {"current_content_version_id": str(saved.id), "pending_revision": None}
    if revision:
        updates["revision_count"] = state.get("revision_count", 0) + 1
    return updates
