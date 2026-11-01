"""Builds the grounded generation context and reads it back for workflow nodes."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import WorkflowError
from app.models import ContentTask
from app.repositories.brand_repository import BrandRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.review_repository import ReviewRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.content import BrandFacts, GenerationContext, ProductFacts, ReviewFacts


async def build_generation_context(session: AsyncSession, task: ContentTask) -> GenerationContext:
    brand = await BrandRepository(session).get(task.brand_id)
    if brand is None:
        raise WorkflowError("The task's brand no longer exists.", code="BRAND_MISSING")

    tasks = TaskRepository(session)
    products_repo = ProductRepository(session)
    product_ids = await tasks.product_ids(task.id)
    by_id = {product.id: product for product in await products_repo.get_many(product_ids)}

    products: list[ProductFacts] = []
    for product_id in product_ids:
        product = by_id[product_id]
        images = await products_repo.list_images(product_id)
        products.append(
            ProductFacts(
                id=str(product.id),
                sku=product.sku,
                name=product.name,
                category=product.category,
                description=product.description,
                key_features=product.key_features,
                materials=product.materials,
                suitable_pets=product.suitable_pets,
                usage_instructions=product.usage_instructions,
                safety_notes=product.safety_notes,
                price=str(product.price) if product.price is not None else None,
                currency=product.currency,
                product_url=product.product_url,
                image_paths=[image.file_path for image in images],
            )
        )

    reviews = await ReviewRepository(session).list_usable(product_ids)
    return GenerationContext(
        brand=BrandFacts(
            brand_name=brand.brand_name,
            brand_description=brand.brand_description,
            brand_voice=brand.brand_voice,
            target_audience=brand.target_audience,
            preferred_cta=brand.preferred_cta,
            prohibited_claims=brand.prohibited_claims,
            style_guidelines=brand.style_guidelines,
            logo_path=brand.logo_path,
        ),
        products=products,
        reviews=[
            ReviewFacts(
                id=str(review.id),
                product_id=str(review.product_id),
                rating=review.rating,
                review_text=review.review_text,
            )
            for review in reviews
        ],
        target_market=task.target_market,
        target_audience=task.target_audience,
        marketing_goal=task.marketing_goal,
        operator_instructions=task.operator_instructions,
        locale=brand.default_locale,
        channels=task.channels,
        image_count=task.image_count,
        target_word_count=task.target_word_count,
        recent_topics=await tasks.recent_selected_topics(brand.id),
    )


def read_generation_context(task: ContentTask) -> GenerationContext:
    if task.context_snapshot is None:
        raise WorkflowError("The task's generation context has not been loaded.", code="CONTEXT_MISSING")
    return GenerationContext.model_validate(task.context_snapshot)
