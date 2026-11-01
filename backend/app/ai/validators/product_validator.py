"""Checks that product data is sufficient before spending money on generation."""

from app.core.exceptions import WorkflowError
from app.schemas.content import GenerationContext


def ensure_context_is_usable(context: GenerationContext) -> None:
    if not context.products:
        raise WorkflowError("The task has no products to promote.", code="NO_PRODUCTS")
    for product in context.products:
        if not product.name.strip() or not product.description.strip():
            raise WorkflowError(
                f"Product {product.id} needs a name and a description before generating content.",
                code="INCOMPLETE_PRODUCT",
                details={"product_id": product.id},
            )
