from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.status import ReviewType
from app.db.base import Base, created_at_column, enum_column, uuid_pk


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    # One decision per review: the database itself rejects a duplicate submission.
    __table_args__ = (UniqueConstraint("task_id", "review_key", name="uq_approval_task_review_key"),)

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    review_type: Mapped[ReviewType] = mapped_column(enum_column(ReviewType))
    decision: Mapped[str] = mapped_column(String(50))
    target_reference_id: Mapped[UUID | None]
    feedback: Mapped[str | None] = mapped_column(Text)
    review_key: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
