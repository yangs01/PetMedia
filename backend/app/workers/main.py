"""Worker process: ``uv run python -m app.workers.main``.

Polls the job queue and runs LangGraph workflows, independently of the API. Stop
it with Ctrl+C. After a crash, any worker takes over once the job's lease expires.
"""

import asyncio
import logging
import os
import signal
import socket
from uuid import uuid4

from app.ai.graphs.content_graph import build_content_graph
from app.ai.persistence.checkpointer import open_checkpointer, setup_checkpointer
from app.ai.providers import create_image_provider, create_llm_provider
from app.ai.runtime import WorkflowDeps
from app.core.config import Settings, get_settings
from app.core.event_loop import run_async
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.media.storage import LocalStorage
from app.workers.job_queue import JobQueue
from app.workers.job_runner import JobRunner, fail_exhausted_jobs

logger = logging.getLogger(__name__)


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    # Each running job holds one connection for its thread lock, one for its work,
    # and may need another for its lease heartbeat.
    engine = create_engine(settings.database_url, pool_size=settings.worker_concurrency * 3 + 2)
    session_factory = create_session_factory(engine)
    storage = LocalStorage(settings.resolved_storage_root)
    storage.ensure_layout()
    # Created up front so a missing API key stops the worker at startup with a clear message.
    deps = WorkflowDeps(
        session_factory=session_factory,
        llm=create_llm_provider(settings),
        image=create_image_provider(settings),
        storage=storage,
        settings=settings,
    )
    await setup_checkpointer(settings)
    queue = JobQueue(session_factory, worker_id=worker_id, lease_seconds=settings.job_lease_seconds)
    running: set[asyncio.Task] = set()

    async with open_checkpointer(settings, max_size=settings.worker_concurrency * 2 + 2) as saver:
        graph = build_content_graph(saver, max_node_attempts=settings.max_generation_retries)
        runner = JobRunner(graph=graph, deps=deps, queue=queue, engine=engine)
        logger.info("Worker started", extra={"worker_id": worker_id, "llm": deps.llm.name, "image": deps.image.name})
        try:
            while not stop.is_set():
                claimed = None
                try:
                    async with session_factory() as session:
                        await fail_exhausted_jobs(session)
                        await session.commit()
                    if len(running) < settings.worker_concurrency:
                        claimed = await queue.claim()
                except Exception:
                    logger.exception("Could not poll the job queue; will try again")
                if claimed is not None:
                    job_task = asyncio.create_task(runner.run(claimed))
                    running.add(job_task)
                    job_task.add_done_callback(running.discard)
                    continue  # There may be more work: skip the wait.
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_seconds)
                except TimeoutError:
                    pass
        finally:
            for job_task in running:
                job_task.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)
    for provider in (deps.llm, deps.image):
        close = getattr(provider, "aclose", None)
        if close:
            await close()
    await engine.dispose()
    logger.info("Worker stopped", extra={"worker_id": worker_id})


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    # signal.signal is used because Windows event loops lack add_signal_handler.
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)
    else:
        signal.signal(signal.SIGTERM, request_stop)
    await run_worker(settings, stop)


if __name__ == "__main__":
    run_async(_main())
