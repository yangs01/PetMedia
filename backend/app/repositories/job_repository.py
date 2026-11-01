"""Database operations of the PostgreSQL job queue.

``claim_next`` uses ``FOR UPDATE SKIP LOCKED`` so any number of workers can poll
without blocking each other or picking the same row. Time comparisons use the
database clock, so workers with different clocks still agree on lease expiry.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.status import JobStatus, JobType
from app.models import GenerationJob


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        task_id: UUID,
        job_type: JobType,
        idempotency_key: str,
        max_attempts: int,
        payload: dict[str, Any] | None = None,
    ) -> GenerationJob:
        job = GenerationJob(
            task_id=task_id,
            job_type=job_type,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            payload=payload or {},
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: UUID) -> GenerationJob | None:
        return await self.session.get(GenerationJob, job_id, populate_existing=True)

    async def has_active_job(self, task_id: UUID) -> bool:
        stmt = select(GenerationJob.id).where(
            GenerationJob.task_id == task_id,
            GenerationJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)),
        )
        return await self.session.scalar(stmt.limit(1)) is not None

    async def latest_for_task(self, task_id: UUID) -> GenerationJob | None:
        stmt = (
            select(GenerationJob)
            .where(GenerationJob.task_id == task_id)
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def cancel_pending(self, task_id: UUID) -> bool:
        result = await self.session.execute(
            update(GenerationJob)
            .where(GenerationJob.task_id == task_id, GenerationJob.status == JobStatus.PENDING)
            .values(status=JobStatus.CANCELLED, finished_at=func.now())
        )
        return result.rowcount > 0

    async def claim_next(self, worker_id: str, lease_seconds: int) -> GenerationJob | None:
        """Claim a due job, or take over one whose worker stopped renewing its lease."""
        now = func.now()
        stmt = (
            select(GenerationJob)
            .where(
                or_(
                    and_(GenerationJob.status == JobStatus.PENDING, GenerationJob.available_at <= now),
                    and_(GenerationJob.status == JobStatus.RUNNING, GenerationJob.lease_expires_at < now),
                ),
                GenerationJob.attempts < GenerationJob.max_attempts,
            )
            .order_by(GenerationJob.available_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = await self.session.scalar(stmt)
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.lease_owner = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.flush()
        await self.session.refresh(job)
        return job

    async def claim_exhausted(self) -> Sequence[GenerationJob]:
        """Jobs whose worker crashed on the final attempt. Locked so one worker handles each."""
        stmt = (
            select(GenerationJob)
            .where(
                GenerationJob.status == JobStatus.RUNNING,
                GenerationJob.lease_expires_at < func.now(),
                GenerationJob.attempts >= GenerationJob.max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
        return (await self.session.scalars(stmt)).all()

    async def renew_lease(self, job_id: UUID, worker_id: str, lease_seconds: int) -> bool:
        return await self._update_owned(
            job_id, worker_id, lease_expires_at=func.now() + timedelta(seconds=lease_seconds)
        )

    async def complete(self, job_id: UUID, worker_id: str) -> bool:
        return await self._update_owned(
            job_id,
            worker_id,
            status=JobStatus.SUCCEEDED,
            finished_at=func.now(),
            lease_owner=None,
            lease_expires_at=None,
        )

    async def fail(self, job_id: UUID, worker_id: str, error: str) -> bool:
        return await self._update_owned(
            job_id,
            worker_id,
            status=JobStatus.FAILED,
            last_error=error[:2000],
            finished_at=func.now(),
            lease_owner=None,
            lease_expires_at=None,
        )

    async def reschedule(
        self, job_id: UUID, worker_id: str, *, delay_seconds: float, error: str | None = None,
        refund_attempt: bool = False,
    ) -> bool:
        values: dict[str, Any] = {
            "status": JobStatus.PENDING,
            "available_at": func.now() + timedelta(seconds=delay_seconds),
            "lease_owner": None,
            "lease_expires_at": None,
        }
        if error is not None:
            values["last_error"] = error[:2000]
        if refund_attempt:
            values["attempts"] = GenerationJob.attempts - 1
        return await self._update_owned(job_id, worker_id, **values)

    async def _update_owned(self, job_id: UUID, worker_id: str, **values: Any) -> bool:
        """Every worker write is fenced: it fails if the lease now belongs to someone else."""
        result = await self.session.execute(
            update(GenerationJob)
            .where(
                GenerationJob.id == job_id,
                GenerationJob.status == JobStatus.RUNNING,
                GenerationJob.lease_owner == worker_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1
