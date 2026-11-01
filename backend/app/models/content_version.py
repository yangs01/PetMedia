from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.status import GenerationSource, VersionApproval
from app.db.base import Base, created_at_column, enum_column, uuid_pk


class ContentVersion(Base):
    """An immutable draft. ``content`` is never updated; changes create a new row."""

    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("task_id", "version_number", name="uq_content_version_number"),
        UniqueConstraint("task_id", "idempotency_key", name="uq_content_version_idempotency"),
    )

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int]
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    generation_source: Mapped[GenerationSource] = mapped_column(enum_column(GenerationSource))
    parent_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("content_versions.id", ondelete="SET NULL"))
    revision_feedback: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[VersionApproval] = mapped_column(
        enum_column(VersionApproval), default=VersionApproval.PENDING
    )
    # Retrying a generation step finds the row it already wrote instead of adding a duplicate.
    idempotency_key: Mapped[str] = mapped_column(String(255))
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_column()
