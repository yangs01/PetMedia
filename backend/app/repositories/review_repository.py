from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.status import ReviewVerification
from app.models import CustomerReview


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, review: CustomerReview) -> CustomerReview:
        self.session.add(review)
        await self.session.flush()
        return review

    async def list_for_product(self, product_id: UUID) -> Sequence[CustomerReview]:
        stmt = (
            select(CustomerReview)
            .where(CustomerReview.product_id == product_id)
            .order_by(CustomerReview.created_at.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def list_usable(self, product_ids: Sequence[UUID], limit: int = 20) -> Sequence[CustomerReview]:
        """Reviews the AI may see: verified and with permission to use."""
        stmt = (
            select(CustomerReview)
            .where(
                CustomerReview.product_id.in_(product_ids),
                CustomerReview.permission_to_use.is_(True),
                CustomerReview.verified_status == ReviewVerification.VERIFIED,
            )
            .order_by(CustomerReview.created_at.desc())
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()
