import asyncio
import hashlib
from uuid import UUID

from langgraph.runtime import Runtime

from app.ai.nodes.common import ensure_status, load_task
from app.ai.runtime import WorkflowDeps
from app.ai.states.content_state import ContentState
from app.core.status import AssetStatus, TaskStatus
from app.media.renderer import SlideRenderInput, render_slide
from app.media.specs import CAROUSEL_SPEC
from app.models import GeneratedAsset
from app.repositories.asset_repository import AssetRepository
from app.schemas.content import CarouselSlide, GenerationContext
from app.services.content_service import read_generation_context

# Added by code, not left to the plan: the model must never draw products or text.
IMAGE_CONSTRAINTS = (
    "Background or lifestyle illustration only. No text, letters, logos, watermarks or "
    "packaging. Do not depict any specific commercial product."
)


def compose_image_prompt(
    slide: CarouselSlide, context: GenerationContext, feedback: str | None, asset_version: int
) -> str:
    parts = [slide.image_prompt]
    if context.brand.style_guidelines:
        parts.append(f"Style: {context.brand.style_guidelines}")
    if feedback:
        parts.append(f"Art direction: {feedback}")
    parts.append(IMAGE_CONSTRAINTS)
    if asset_version > 1:
        parts.append(f"Create a fresh variation (version {asset_version}).")
    return " ".join(parts)


async def generate_images(state: ContentState, runtime: Runtime[WorkflowDeps]) -> dict:
    """Create images for the requested slides; other slides are not touched.

    Each slide is saved as soon as it is ready. After a failure, the retry skips
    finished slides by looking up (task, slide, request key).
    """
    deps = runtime.context
    task_id = UUID(state["task_id"])
    plan_id = UUID(state["carousel_plan_id"])
    version_id = UUID(state["approved_content_version_id"])
    request_key = state.get("image_request_key") or "initial"
    feedback = state.get("image_feedback")

    async with deps.session_factory() as session:
        task = await load_task(session, state["task_id"])
        await ensure_status(session, task, TaskStatus.GENERATING_ASSETS, "generate_images")
        await session.commit()
        context = read_generation_context(task)
        plan = await AssetRepository(session).get_plan(plan_id)

    slides = [CarouselSlide.model_validate(slide) for slide in plan.slides]
    requested = set(state.get("pending_slide_numbers") or [s.slide_number for s in slides])

    for slide in slides:
        if slide.slide_number not in requested:
            continue
        async with deps.session_factory() as session:
            repository = AssetRepository(session)
            if await repository.get_by_request(task_id, slide.slide_number, request_key):
                continue
            asset_version = await repository.next_asset_version(task_id, slide.slide_number)
        await _produce_slide(deps, context, slide, task_id, plan_id, version_id, request_key, feedback, asset_version)

    async with deps.session_factory() as session:
        current = await AssetRepository(session).list_for_task(task_id)
    return {
        "generated_asset_ids": [str(asset.id) for asset in current],
        "pending_slide_numbers": [],
        "image_request_key": None,
        "image_feedback": None,
        "last_decision": None,
    }


async def _produce_slide(
    deps: WorkflowDeps,
    context: GenerationContext,
    slide: CarouselSlide,
    task_id: UUID,
    plan_id: UUID,
    version_id: UUID,
    request_key: str,
    feedback: str | None,
    asset_version: int,
) -> None:
    spec = CAROUSEL_SPEC
    prompt = compose_image_prompt(slide, context, feedback, asset_version)
    generated = await deps.image.generate_background(prompt, width=spec.width, height=spec.height)

    def read_optional(key: str | None) -> bytes | None:
        return deps.storage.read_bytes(key) if key else None

    product_key = _product_image_key(slide, context)
    product_image = await asyncio.to_thread(read_optional, product_key)
    logo = await asyncio.to_thread(read_optional, context.brand.logo_path)
    jpeg = await asyncio.to_thread(
        render_slide,
        SlideRenderInput(
            headline=slide.headline,
            supporting_text=slide.supporting_text,
            layout=slide.layout_template,
            brand_name=context.brand.brand_name,
            background=generated.data,
            product_image=product_image,
            logo=logo,
        ),
        spec=spec,
        font_path=deps.settings.font_path,
        max_bytes=deps.settings.max_output_jpeg_bytes,
    )
    key = f"generated/{task_id}/slide_{slide.slide_number:02d}_v{asset_version}.jpg"
    await asyncio.to_thread(deps.storage.save_bytes, key, jpeg)

    async with deps.session_factory() as session:
        await AssetRepository(session).replace_current(
            GeneratedAsset(
                task_id=task_id,
                carousel_plan_id=plan_id,
                source_content_version_id=version_id,
                slide_number=slide.slide_number,
                asset_version=asset_version,
                request_key=request_key,
                file_path=key,
                mime_type="image/jpeg",
                width=spec.width,
                height=spec.height,
                file_size=len(jpeg),
                sha256=hashlib.sha256(jpeg).hexdigest(),
                generation_prompt=prompt,
                visual_feedback=feedback,
                provider=generated.provider,
                is_mock=generated.is_mock,
                status=AssetStatus.ACTIVE,
            )
        )
        await session.commit()


def _product_image_key(slide: CarouselSlide, context: GenerationContext) -> str | None:
    """Use the operator's real photo. No photo means the slide simply shows no product."""
    products = {product.id: product for product in context.products}
    for product_id in slide.product_ids:
        product = products.get(product_id)
        if product and product.image_paths:
            return product.image_paths[0]
    return None
