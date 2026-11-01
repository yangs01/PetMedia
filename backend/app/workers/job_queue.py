"""Short transactions around the job repository, one per queue operation."""

from uuid import UUID

from app.db.session import SessionFactory
from app.models import GenerationJob
from app.repositories.job_repository import JobRepository


class JobQueue:
    def __init__(self, session_factory: SessionFactory, *, worker_id: str, lease_seconds: int) -> None:
        self._session_factory = session_factory
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    async def claim(self) -> GenerationJob | None:
        async with self._session_factory() as session:
            job = await JobRepository(session).claim_next(self.worker_id, self.lease_seconds)
            await session.commit()
            return job

    async def renew_lease(self, job_id: UUID) -> bool:
        async with self._session_factory() as session:
            renewed = await JobRepository(session).renew_lease(job_id, self.worker_id, self.lease_seconds)
            await session.commit()
            return renewed

    async def reschedule(
        self, job_id: UUID, *, delay_seconds: float, error: str | None = None, refund_attempt: bool = False
    ) -> bool:
        async with self._session_factory() as session:
            done = await JobRepository(session).reschedule(
                job_id, self.worker_id, delay_seconds=delay_seconds, error=error, refund_attempt=refund_attempt
            )
            await session.commit()
            return done
