"""Runs one queued job against the LangGraph thread of its task.

PostgreSQL business writes and checkpoint writes cannot share a transaction, so
the runner treats the checkpoint as the source of truth for graph progress and
reconciles the business task from it after every run. Any crash point therefore
converges on a correct state when the job is retried:

* Crash before the resume was consumed: the interrupt is still pending with the
  job's review key, so the decision is applied.
* Crash after it was consumed: the key no longer matches, so the decision is not
  applied twice. The graph just continues from its checkpoint.
* Crash after the graph paused but before the status update: nothing is run, and
  reconciliation sets the AWAITING status.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.runtime import WorkflowDeps
from app.core.exceptions import AppError, WorkflowError, is_transient_error
from app.core.logging import bind_log_context
from app.core.status import (
    REVIEW_STATUS_BY_TYPE,
    JobStatus,
    ReviewType,
    TaskStatus,
    is_legal_transition,
)
from app.models import ContentTask, GenerationJob, TaskEvent
from app.repositories.job_repository import JobRepository
from app.repositories.task_repository import TaskRepository
from app.services.task_service import transition_task
from app.workers.job_queue import JobQueue

logger = logging.getLogger(__name__)

THREAD_BUSY_RETRY_SECONDS = 5


def plan_graph_input(job_payload: dict[str, Any], task_id: str, snapshot: StateSnapshot) -> Any:
    """Decide what to send to the graph. Returns ``SKIP_RUN`` if there is nothing to run."""
    if snapshot.interrupts:
        paused_key = snapshot.interrupts[0].value["review_key"]
        if job_payload.get("review_key") == paused_key:
            return Command(resume=job_payload["decision"])
        return SKIP_RUN
    if snapshot.created_at is None:
        if job_payload.get("review_key"):
            raise WorkflowError("A decision was submitted for a workflow with no checkpoint.", code="CHECKPOINT_MISSING")
        return {"task_id": task_id}
    if not snapshot.next:
        return SKIP_RUN
    # Checkpoint exists mid-graph (crash or failed node): None continues from it.
    return None


SKIP_RUN = object()


class _LeaseLost(Exception):
    pass


class JobRunner:
    def __init__(
        self, *, graph: CompiledStateGraph, deps: WorkflowDeps, queue: JobQueue, engine: AsyncEngine
    ) -> None:
        self.graph = graph
        self.deps = deps
        self.queue = queue
        self.engine = engine

    async def run(self, job: GenerationJob) -> None:
        async with self.deps.session_factory() as session:
            task = await TaskRepository(session).get(job.task_id)
        if task is None:
            logger.error("Job refers to a missing task", extra={"job_id": str(job.id)})
            return
        with bind_log_context(job_id=str(job.id), task_id=str(task.id), thread_id=task.thread_id):
            logger.info("Job started", extra={"job_type": job.job_type.value, "attempt": job.attempts})
            try:
                async with self._thread_lock(task.thread_id) as acquired:
                    if not acquired:
                        logger.info("Thread is busy on another worker; rescheduling job")
                        await self.queue.reschedule(
                            job.id, delay_seconds=THREAD_BUSY_RETRY_SECONDS, refund_attempt=True
                        )
                        return
                    await self._run_with_heartbeat(job, task)
            except _LeaseLost:
                logger.warning("Lease lost; another worker now owns this job")
            except asyncio.CancelledError:
                # Worker shutdown is not the job's fault, so it does not use up an attempt.
                await asyncio.shield(self.queue.reschedule(job.id, delay_seconds=0, refund_attempt=True))
                raise
            except Exception as error:
                await self._handle_failure(job, task, error)

    async def _run_with_heartbeat(self, job: GenerationJob, task: ContentTask) -> None:
        execution = asyncio.current_task()
        lost = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self.queue.lease_seconds / 3)
                try:
                    renewed = await self.queue.renew_lease(job.id)
                except Exception:
                    # A brief database outage should not abort work; the lease may yet recover.
                    logger.warning("Lease renewal failed; will try again", exc_info=True)
                    continue
                if not renewed:
                    lost.set()
                    execution.cancel()
                    return

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            await self._execute(job, task)
        except asyncio.CancelledError:
            if lost.is_set():
                execution.uncancel()
                raise _LeaseLost() from None
            raise
        finally:
            heartbeat_task.cancel()

    async def _execute(self, job: GenerationJob, task: ContentTask) -> None:
        config = {"configurable": {"thread_id": task.thread_id}}
        snapshot = await self.graph.aget_state(config)
        graph_input = plan_graph_input(job.payload, str(task.id), snapshot)
        if graph_input is not SKIP_RUN:
            # durability="sync" guarantees each step's checkpoint is stored before the next starts.
            await self.graph.ainvoke(graph_input, config, context=self.deps, durability="sync")
            snapshot = await self.graph.aget_state(config)
        await self._reconcile(job, task, snapshot)

    async def _reconcile(self, job: GenerationJob, task: ContentTask, snapshot: StateSnapshot) -> None:
        """Bring the business task in line with the checkpoint, and finish the job, atomically."""
        async with self.deps.session_factory() as session:
            current = await TaskRepository(session).get(task.id)
            if snapshot.interrupts:
                pause = snapshot.interrupts[0].value
                target = REVIEW_STATUS_BY_TYPE[ReviewType(pause["review_type"])]
                if current.status != target or current.current_review_key != pause["review_key"]:
                    await transition_task(
                        session, current, target, node_name="review", current_review_key=pause["review_key"]
                    )
            elif current.status not in (TaskStatus.READY, TaskStatus.CANCELLED):
                raise WorkflowError(
                    "The workflow stopped without reaching a review or a final status.",
                    code="WORKFLOW_STOPPED_UNEXPECTEDLY",
                    details={"status": current.status.value, "next_nodes": list(snapshot.next)},
                )
            if not await JobRepository(session).complete(job.id, self.queue.worker_id):
                await session.rollback()
                raise _LeaseLost()
            await session.commit()
        logger.info("Job finished", extra={"task_status": current.status.value})

    async def _handle_failure(self, job: GenerationJob, task: ContentTask, error: Exception) -> None:
        """Infrastructure hiccups retry the job. Everything else fails the task, recoverably."""
        logger.error(
            "Job failed",
            extra={"error_type": type(error).__name__, "attempt": job.attempts},
            exc_info=not isinstance(error, AppError),
        )
        retryable = is_transient_error(error) and not _is_provider_error(error)
        if retryable and job.attempts < job.max_attempts:
            await self.queue.reschedule(
                job.id, delay_seconds=min(2**job.attempts, 60), error=_error_summary(error)["message"]
            )
            return
        async with self.deps.session_factory() as session:
            await mark_job_and_task_failed(session, job.id, self.queue.worker_id, _error_summary(error))
            await session.commit()

    @asynccontextmanager
    async def _thread_lock(self, thread_id: str) -> AsyncIterator[bool]:
        """Hold a session-level PostgreSQL lock on the thread while it runs.

        The lock belongs to the connection, so it disappears the moment a worker's
        process dies. This protects a thread even if a stalled worker outlives its lease.
        """
        async with self.engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": thread_id}
            )
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    await asyncio.shield(
                        connection.execute(
                            text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": thread_id}
                        )
                    )


async def mark_job_and_task_failed(session, job_id, worker_id: str, summary: dict[str, Any]) -> None:
    jobs = JobRepository(session)
    if not await jobs.fail(job_id, worker_id, summary["message"]):
        return
    job = await jobs.get(job_id)
    await _fail_task(session, job, summary)


async def fail_exhausted_jobs(session) -> int:
    """Stop retrying jobs whose workers kept dying, and surface the failure on their tasks."""
    jobs = JobRepository(session)
    exhausted = await jobs.claim_exhausted()
    summary = {
        "code": "WORKER_CRASHED",
        "message": "The worker stopped responding during every attempt of this job.",
    }
    for job in exhausted:
        job.status = JobStatus.FAILED
        job.last_error = summary["message"]
        job.lease_owner = None
        job.lease_expires_at = None
        await session.flush()
        await _fail_task(session, job, summary)
    return len(exhausted)


async def _fail_task(session, job: GenerationJob, summary: dict[str, Any]) -> None:
    repository = TaskRepository(session)
    task = await repository.get(job.task_id)
    if is_legal_transition(task.status, TaskStatus.FAILED):
        await transition_task(session, task, TaskStatus.FAILED, message=summary["message"], last_error=summary)
    else:
        await repository.add_event(
            TaskEvent(task_id=task.id, event_type="JOB_FAILED", message=summary["message"], data=summary)
        )


def _is_provider_error(error: Exception) -> bool:
    # Node-level retries already used the provider's retry budget. Retrying the whole
    # job on top would multiply API calls, so the task fails and can be retried by hand.
    return isinstance(error, AppError)


def _error_summary(error: Exception) -> dict[str, Any]:
    if isinstance(error, AppError):
        return {"code": error.code, "message": error.message, "details": error.details}
    # Unknown exception text may contain internals, so it stays in the logs only.
    return {
        "code": "WORKFLOW_ERROR",
        "message": "An unexpected error occurred while running the workflow.",
        "error_type": type(error).__name__,
    }
