from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.status import TaskStatus
from app.db.base import Base, created_at_column, enum_column, updated_at_column, uuid_pk


class ContentTask(Base):
    __tablename__ = "content_tasks"
    __table_args__ = (CheckConstraint("image_count BETWEEN 3 AND 5", name="image_count_range"),)

    id: Mapped[UUID] = uuid_pk()
    thread_id: Mapped[str] = mapped_column(String(255), unique=True)
    brand_id: Mapped[UUID] = mapped_column(ForeignKey("brand_profiles.id", ondelete="RESTRICT"), index=True)
    status: Mapped[TaskStatus] = mapped_column(enum_column(TaskStatus), default=TaskStatus.CREATED, index=True)
    # Incremented on every status change; the basis of optimistic concurrency checks.
    lock_version: Mapped[int] = mapped_column(Integer, default=0)

    target_market: Mapped[str] = mapped_column(String(50))
    target_audience: Mapped[str | None] = mapped_column(Text)
    marketing_goal: Mapped[str | None] = mapped_column(Text)
    operator_instructions: Mapped[str | None] = mapped_column(Text)
    channels: Mapped[list[str]] = mapped_column(JSONB)
    image_count: Mapped[int]
    target_word_count: Mapped[int]

    # Facts frozen at the start of the workflow, so every generation step and the
    # export provenance refer to the same product data even if a product is edited later.
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # use_alter breaks the table cycle: these tables also reference content_tasks.
    selected_topic_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("topic_suggestions.id", use_alter=True, ondelete="SET NULL")
    )
    current_content_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content_versions.id", use_alter=True, ondelete="SET NULL")
    )
    approved_content_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content_versions.id", use_alter=True, ondelete="SET NULL")
    )
    # Identifies the review the workflow is paused on. Decisions are tied to it.
    current_review_key: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentTaskProduct(Base):
    __tablename__ = "content_task_products"

    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
