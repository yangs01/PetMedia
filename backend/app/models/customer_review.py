from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.status import ReviewVerification
from app.db.base import Base, created_at_column, enum_column, uuid_pk


class CustomerReview(Base):
    """A genuine customer review. Never created or changed by AI."""

    __tablename__ = "customer_reviews"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)

    id: Mapped[UUID] = uuid_pk()
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int]
    review_text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    source_reference: Mapped[str] = mapped_column(String(255))
    permission_to_use: Mapped[bool] = mapped_column(default=False)
    verified_status: Mapped[ReviewVerification] = mapped_column(
        enum_column(ReviewVerification), default=ReviewVerification.UNVERIFIED
    )
    created_at: Mapped[datetime] = created_at_column()
