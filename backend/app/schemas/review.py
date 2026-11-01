from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.status import ReviewVerification


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    review_text: str = Field(min_length=1, max_length=10000)
    source: str = Field(min_length=1, max_length=100, examples=["order_review"])
    source_reference: str = Field(
        min_length=1,
        max_length=255,
        description="Traceable reference, such as an order id or testimonial record.",
    )
    permission_to_use: bool = False
    verified_status: ReviewVerification = ReviewVerification.UNVERIFIED


class ReviewRead(ReviewCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    created_at: datetime
