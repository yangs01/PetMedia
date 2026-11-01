from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, uuid_pk


class TopicSuggestion(Base):
    __tablename__ = "topic_suggestions"
    __table_args__ = (UniqueConstraint("task_id", "batch_number", "position", name="uq_topic_batch_position"),)

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[UUID] = mapped_column(index=True)
    batch_number: Mapped[int]
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(500))
    angle: Mapped[str] = mapped_column(Text)
    target_audience: Mapped[str] = mapped_column(Text)
    hook: Mapped[str] = mapped_column(Text)
    product_relevance: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(50))
    rationale: Mapped[str] = mapped_column(Text)
    operator_feedback: Mapped[str | None] = mapped_column(Text)
    is_selected: Mapped[bool] = mapped_column(default=False)
    provider: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_column()
