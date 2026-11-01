from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.status import JobStatus, JobType
from app.db.base import Base, created_at_column, enum_column, updated_at_column, uuid_pk


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        # A task's LangGraph thread must never have two jobs in flight. This index makes
        # that a database guarantee, and it is what rejects concurrent resume commands.
        Index(
            "uq_job_one_active_per_task",
            "task_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        Index("ix_job_claim", "status", "available_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType))
    status: Mapped[JobStatus] = mapped_column(enum_column(JobStatus), default=JobStatus.PENDING)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int]
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
