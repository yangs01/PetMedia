from uuid import UUID

from langgraph.runtime import Runtime

from app.ai.nodes.common import ensure_status, generate_with_validation, load_task
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.status import TaskStatus
from app.models import ChannelContent
from app.publishing import get_adapter
from app.repositories.content_repository import ContentRepository
from app.schemas.content import MasterCopy
from app.services.content_service import read_generation_context


async def adapt_channels(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Adapt the approved draft for each channel. Already saved channels are skipped."""
    deps = runtime.context
    task_id = UUID(state["task_id"])
    # Always the approved version, never whichever draft happens to be latest.
    version_id = UUID(state["approved_content_version_id"])

    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        await ensure_status(session, task, TaskStatus.GENERATING_ASSETS, "adapt_channels")
        await session.commit()
        context = read_generation_context(task)
        version = await ContentRepository(session).get_version(version_id)
        master = MasterCopy.model_validate(version.content)

    channel_ids: list[str] = []
    for platform in state["channels"]:
        adapter = get_adapter(platform)
        async with deps.session_factory() as session:
            channel = await ContentRepository(session).get_channel(task_id, version_id, platform)
        if channel is None:
            llm = deps.models.for_role(adapter.model_role)

            # Default arguments bind the loop variables for this iteration's closure.
            async def generate(feedback, adapter=adapter, llm=llm):
                return await adapter.adapt(llm, context, master, feedback=feedback)

            output, report = await generate_with_validation(
                generate, context, max_fixes=deps.settings.max_copy_auto_fixes
            )
            async with deps.session_factory() as session:
                channel = await ContentRepository(session).add_channel(
                    ChannelContent(
                        task_id=task_id,
                        content_version_id=version_id,
                        platform=platform,
                        payload={"platform": platform, **output.model_dump(mode="json")},
                        validation=report.to_record(),
                        provider=llm.name,
                        prompt_version=adapter.prompt.version_label,
                    )
                )
                await session.commit()
        channel_ids.append(str(channel.id))
    return {"channel_content_ids": channel_ids}
