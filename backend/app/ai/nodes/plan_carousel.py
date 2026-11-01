from uuid import UUID

from langgraph.runtime import Runtime

from app.ai.nodes.common import generate_with_validation, load_task
from app.ai.prompts import load_prompt
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.exceptions import StructuredOutputError
from app.models import CarouselPlan
from app.repositories.asset_repository import AssetRepository
from app.repositories.content_repository import ContentRepository
from app.schemas.content import CarouselPlanOutput, MasterCopy
from app.services.content_service import read_generation_context


async def plan_carousel(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Turn the approved draft into a slide plan. Produces data only, no images."""
    deps = runtime.context
    task_id = UUID(state["task_id"])
    version_id = UUID(state["approved_content_version_id"])
    image_count = state["image_count"]

    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        context = read_generation_context(task)
        plan = await AssetRepository(session).get_plan_for_version(task_id, version_id)
        version = await ContentRepository(session).get_version(version_id)
        master = MasterCopy.model_validate(version.content)

    if plan is None:

        async def generate(feedback: str | None) -> CarouselPlanOutput:
            output = await deps.llm.plan_carousel(
                context, master=master, image_count=image_count, feedback=feedback
            )
            _ensure_plan_matches(output, image_count, {product.id for product in context.products})
            return output

        output, report = await generate_with_validation(
            generate, context, max_fixes=deps.settings.max_copy_auto_fixes
        )
        async with deps.session_factory() as session:
            plan = await AssetRepository(session).add_plan(
                CarouselPlan(
                    task_id=task_id,
                    content_version_id=version_id,
                    slides=[slide.model_dump(mode="json") for slide in output.slides],
                    validation=report.to_record(),
                    provider=deps.llm.name,
                    prompt_version=load_prompt("carousel_planning").version_label,
                )
            )
            await session.commit()
    return {"carousel_plan_id": str(plan.id), "pending_slide_numbers": [], "image_request_key": None}


def _ensure_plan_matches(plan: CarouselPlanOutput, image_count: int, known_products: set[str]) -> None:
    if len(plan.slides) != image_count:
        raise StructuredOutputError(f"Expected {image_count} slides, got {len(plan.slides)}.")
    for slide in plan.slides:
        unknown = set(slide.product_ids) - known_products
        if unknown:
            raise StructuredOutputError(f"Slide {slide.slide_number} references an unknown product.")
