from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class ChannelContent(Base):
    """Platform output. ``platform`` is a plain string so new platforms need no migration."""

    __tablename__ = "channel_contents"
    __table_args__ = (UniqueConstraint("task_id", "content_version_id", "platform", name="uq_channel_task_version_platform"),)

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    content_version_id: Mapped[UUID] = mapped_column(ForeignKey("content_versions.id", ondelete="RESTRICT"))
    platform: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
