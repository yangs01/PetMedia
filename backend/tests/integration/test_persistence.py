"""Durability: checkpoints in PostgreSQL, restarts, crashes and concurrent access."""

import asyncio
from uuid import UUID

import psycopg
import pytest
from langgraph.types import Command
from sqlalchemy import select, text, update

from app.ai.graphs.content_graph import build_content_graph
from app.ai.persistence.checkpointer import open_checkpointer, setup_checkpointer
from app.ai.providers.mock_provider import MockLLMProvider
from app.core.status import JobStatus, TaskStatus
from app.models import ApprovalRecord, ContentTask, GenerationJob, TaskEvent
from app.repositories.job_repository import JobRepository
from app.workers.job_queue import JobQueue
from app.workers.job_runner import JobRunner, fail_exhausted_jobs
from tests.conftest import TEST_LANGGRAPH_URL
from tests.integration.test_workflow import (
    create_task,
    detail,
    select_first_topic,
    to_copy_review,
    to_topic_review,
)

pytestmark = pytest.mark.integration


async def latest_job(session_factory, task_id: str) -> GenerationJob:
    async with session_factory() as session:
        return await JobRepository(session).latest_for_task(UUID(task_id))


async def expire_lease(session_factory, job_id: UUID) -> None:
    async with session_factory() as session:
        await session.execute(
            update(GenerationJob).where(GenerationJob.id == job_id).values(lease_expires_at=text("now() - interval '1 second'"))
        )
        await session.commit()


class TestCheckpoints:
    async def test_checkpoints_live_in_their_own_schema(self, client, task_inputs, make_runner, drain, settings):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        thread_id = (await detail(client, task_id))["thread_id"]
        with psycopg.connect(TEST_LANGGRAPH_URL) as connection:
            count = connection.execute(
                f"SELECT count(*) FROM {settings.langgraph_schema}.checkpoints WHERE thread_id = %s", (thread_id,)
            ).fetchone()[0]
            public_table = connection.execute("SELECT to_regclass('public.checkpoints')").fetchone()[0]
        assert count > 0
        assert public_table is None

    async def test_setup_can_run_repeatedly(self, settings, prepared_database):
        await setup_checkpointer(settings)
        await setup_checkpointer(settings)

    async def test_thread_id_is_unique_stable_and_stored(self, client, task_inputs, make_runner, drain, session_factory):
        first = await create_task(client, task_inputs)
        second = await create_task(client, task_inputs)
        first_thread = (await detail(client, first))["thread_id"]
        assert first_thread != (await detail(client, second))["thread_id"]
        await drain(make_runner())
        assert (await detail(client, first))["thread_id"] == first_thread


class TestRestart:
    async def test_interrupted_task_resumes_on_a_brand_new_runtime(
        self, client, task_inputs, make_runner, drain, settings, session_factory, storage, engine
    ):
        """Everything in memory is thrown away; only PostgreSQL survives."""
        llm = MockLLMProvider()
        runner = make_runner(llm=llm)
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        thread_id = (await detail(client, task_id))["thread_id"]
        before = await runner.graph.aget_state({"configurable": {"thread_id": thread_id}})
        topics_before = (await client.get(f"/tasks/{task_id}/topics")).json()
        del runner

        await select_first_topic(client, task_id)

        async with open_checkpointer(settings) as fresh_saver:
            fresh_graph = build_content_graph(fresh_saver)
            config = {"configurable": {"thread_id": thread_id}}
            restored = await fresh_graph.aget_state(config)
            assert restored.next == ("review_topic",)
            assert restored.values == before.values
            assert restored.interrupts[0].value == before.interrupts[0].value

            from app.ai.providers.mock_provider import MockImageProvider
            from app.ai.providers.model_router import ModelRouter
            from app.ai.runtime import WorkflowDeps

            models = ModelRouter.uniform(MockLLMProvider())
            deps = WorkflowDeps(session_factory, models, MockImageProvider(), storage, settings)
            queue = JobQueue(session_factory, worker_id="restarted-worker", lease_seconds=30)
            await drain(JobRunner(graph=fresh_graph, deps=deps, queue=queue, engine=engine))

        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        # The workflow continued; it did not start over.
        topics_after = (await client.get(f"/tasks/{task_id}/topics")).json()
        assert [t["id"] for t in topics_after] == [t["id"] for t in topics_before]

    async def test_context_is_not_stored_in_the_checkpoint(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        state = await runner.graph.aget_state({"configurable": {"thread_id": (await detail(client, task_id))["thread_id"]}})
        assert set(state.values) >= {"task_id", "topic_candidate_ids"}
        assert "session_factory" not in str(state.values)
        for value in state.values.values():
            assert isinstance(value, str | int | list | dict | type(None))


class SlowTopicLLM(MockLLMProvider):
    calls = 0

    async def generate_topics(self, context, **kwargs):
        type(self).calls += 1
        return await super().generate_topics(context, **kwargs)


class TestCrashRecovery:
    async def test_crashed_workers_job_is_taken_over_after_its_lease_expires(
        self, client, task_inputs, make_runner, drain, session_factory
    ):
        task_id = await create_task(client, task_inputs)
        crashed = make_runner(worker_id="crashed-worker")
        job = await crashed.queue.claim()  # Claimed, then the process "dies" without a word.
        assert job.status == JobStatus.RUNNING

        survivor = make_runner(worker_id="survivor")
        assert await survivor.queue.claim() is None, "A live lease must block other workers."

        await expire_lease(session_factory, job.id)
        assert await drain(survivor) == 1
        assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"
        finished = await latest_job(session_factory, task_id)
        assert finished.status == JobStatus.SUCCEEDED and finished.attempts == 2

    async def test_resume_consumed_before_crash_is_not_applied_twice(
        self, client, task_inputs, make_runner, drain, session_factory
    ):
        """Crash after the decision reached the graph, before the job was marked done."""
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        current = (await detail(client, task_id))["current_version"]["id"]
        await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "revise", "current_version_id": current, "feedback": "Only once please"},
        )
        job = await runner.queue.claim()
        thread_id = (await detail(client, task_id))["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        await runner.graph.ainvoke(Command(resume=job.payload["decision"]), config, context=runner.deps, durability="sync")
        # The worker dies here, with the graph already paused on the *new* draft.
        await expire_lease(session_factory, job.id)

        await drain(make_runner(worker_id="survivor"))
        versions = (await client.get(f"/tasks/{task_id}/versions")).json()
        assert len(versions) == 2, "The revision must not run a second time."
        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        assert task["current_version"]["id"] == versions[1]["id"]
        assert task["review_key"] == f"copy:{versions[1]['id']}"

    async def test_crash_before_status_update_is_reconciled(
        self, client, task_inputs, make_runner, drain, session_factory
    ):
        """Crash after the interrupt checkpoint was written, before the business status update."""
        llm = SlowTopicLLM()
        SlowTopicLLM.calls = 0
        runner = make_runner(llm=llm)
        task_id = await create_task(client, task_inputs)
        job = await runner.queue.claim()
        thread_id = (await detail(client, task_id))["thread_id"]
        await runner.graph.ainvoke({"task_id": task_id}, {"configurable": {"thread_id": thread_id}}, context=runner.deps, durability="sync")
        assert (await detail(client, task_id))["status"] == "GENERATING_TOPICS"
        await expire_lease(session_factory, job.id)

        await drain(make_runner(llm=llm, worker_id="survivor"))
        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_TOPIC_REVIEW"
        assert task["review_key"] == "topic:batch:1"
        assert SlowTopicLLM.calls == 1, "Finished work must not be repeated."

    async def test_worker_shutdown_mid_node_requeues_and_continues_from_the_checkpoint(
        self, client, task_inputs, make_runner, drain, session_factory
    ):
        entered = asyncio.Event()

        class BlocksDuringCopy(MockLLMProvider):
            async def generate_master_copy(self, context, *, topic):
                entered.set()
                await asyncio.sleep(3600)

        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        await select_first_topic(client, task_id)
        stopping = make_runner(llm=BlocksDuringCopy(), worker_id="stopping")
        job = await stopping.queue.claim()
        running = asyncio.create_task(stopping.run(job))
        await asyncio.wait_for(entered.wait(), timeout=20)

        running.cancel()  # What the worker does to in-flight jobs on Ctrl+C.
        with pytest.raises(asyncio.CancelledError):
            await running
        requeued = await latest_job(session_factory, task_id)
        assert requeued.status == JobStatus.PENDING
        assert requeued.attempts == 0, "A shutdown must not use up one of the job's attempts."

        await drain(make_runner(worker_id="survivor"))
        task = await detail(client, task_id)
        assert task["status"] == "AWAITING_COPY_REVIEW"
        assert len((await client.get(f"/tasks/{task_id}/topics")).json()) == 5

    async def test_job_that_keeps_crashing_fails_the_task(self, client, task_inputs, make_runner, session_factory):
        task_id = await create_task(client, task_inputs)
        runner = make_runner(worker_id="doomed")
        for attempt in range(3):
            job = await runner.queue.claim()
            assert job is not None and job.attempts == attempt + 1
            await expire_lease(session_factory, job.id)
        assert await runner.queue.claim() is None

        async with session_factory() as session:
            assert await fail_exhausted_jobs(session) == 1
            await session.commit()
        task = await detail(client, task_id)
        assert task["status"] == "FAILED"
        assert task["error"]["code"] == "WORKER_CRASHED"
        assert (await latest_job(session_factory, task_id)).status == JobStatus.FAILED


class TestConcurrency:
    async def test_concurrent_decisions_accept_exactly_one(self, client, task_inputs, make_runner, drain, session_factory):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        topics = (await client.get(f"/tasks/{task_id}/topics")).json()
        responses = await asyncio.gather(
            *(
                client.post(f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": t["id"]})
                for t in topics
            )
        )
        codes = sorted(response.status_code for response in responses)
        assert codes == [202, 409, 409, 409, 409]
        async with session_factory() as session:
            records = (await session.scalars(select(ApprovalRecord).where(ApprovalRecord.task_id == UUID(task_id)))).all()
            jobs = (
                await session.scalars(
                    select(GenerationJob).where(GenerationJob.task_id == UUID(task_id), GenerationJob.status == JobStatus.PENDING)
                )
            ).all()
        assert len(records) == 1 and len(jobs) == 1
        accepted = next(r for r in responses if r.status_code == 202)
        assert (await detail(client, task_id))["selected_topic"]["id"] == str(records[0].target_reference_id)
        assert accepted.json()["decision_id"] == str(records[0].id)

    async def test_duplicate_submission_after_acceptance_is_rejected(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_copy_review(client, task_inputs, runner, drain)
        current = (await detail(client, task_id))["current_version"]["id"]
        body = {"action": "approve", "current_version_id": current}
        assert (await client.post(f"/tasks/{task_id}/copy-decision", json=body)).status_code == 202
        repeat = await client.post(f"/tasks/{task_id}/copy-decision", json=body)
        assert repeat.status_code == 409
        assert repeat.json()["error"]["code"] == "INVALID_TASK_STATE"
        assert repeat.json()["error"]["details"]["current_status"] == "GENERATING_ASSETS"

    async def test_database_refuses_two_active_jobs_for_one_task(self, client, task_inputs, session_factory):
        from sqlalchemy.exc import IntegrityError

        from app.core.status import JobType

        task_id = await create_task(client, task_inputs)
        async with session_factory() as session:
            with pytest.raises(IntegrityError):
                await JobRepository(session).enqueue(
                    task_id=UUID(task_id), job_type=JobType.RETRY_WORKFLOW, idempotency_key="other", max_attempts=3
                )

    async def test_workers_never_claim_the_same_job(self, client, task_inputs, make_runner):
        for _ in range(6):
            await create_task(client, task_inputs)
        queues = [make_runner(worker_id=f"worker-{n}").queue for n in range(10)]
        claimed = await asyncio.gather(*(queue.claim() for queue in queues))
        ids = [job.id for job in claimed if job]
        assert len(ids) == len(set(ids)) == 6

    async def test_thread_lock_blocks_a_second_worker(self, client, task_inputs, make_runner, session_factory):
        task_id = await create_task(client, task_inputs)
        thread_id = (await detail(client, task_id))["thread_id"]
        holder = make_runner(worker_id="holder")
        job = await holder.queue.claim()
        await expire_lease(session_factory, job.id)  # The holder has stalled but is still alive.

        second = make_runner(worker_id="second")
        async with holder._thread_lock(thread_id) as first_acquired:
            assert first_acquired
            reclaimed = await second.queue.claim()
            assert reclaimed.id == job.id
            await second.run(reclaimed)
            current = await latest_job(session_factory, task_id)
            assert current.status == JobStatus.PENDING, "The second worker must back off."
            assert (await detail(client, task_id))["status"] == "QUEUED"

        # Once released, the lock is available again.
        async with second._thread_lock(thread_id) as acquired:
            assert acquired

    async def test_expired_worker_cannot_finish_a_job_it_lost(self, client, task_inputs, make_runner, session_factory):
        task_id = await create_task(client, task_inputs)
        old = make_runner(worker_id="old")
        job = await old.queue.claim()
        await expire_lease(session_factory, job.id)
        new = make_runner(worker_id="new")
        assert (await new.queue.claim()).id == job.id
        async with session_factory() as session:
            repository = JobRepository(session)
            assert not await repository.complete(job.id, "old")
            assert not await repository.renew_lease(job.id, "old", 30)
            assert await repository.renew_lease(job.id, "new", 30)
            await session.commit()
        assert task_id

    async def test_concurrent_tasks_stay_isolated(self, client, task_inputs, make_runner, drain, session_factory):
        runner = make_runner()
        task_ids = [await create_task(client, task_inputs) for _ in range(4)]
        await asyncio.gather(*(runner.run(job) for job in [await runner.queue.claim() for _ in task_ids]))
        for task_id in task_ids:
            assert (await detail(client, task_id))["status"] == "AWAITING_TOPIC_REVIEW"
            assert len((await client.get(f"/tasks/{task_id}/topics")).json()) == 5

        await select_first_topic(client, task_ids[0])
        await drain(runner)
        statuses = [(await detail(client, task_id))["status"] for task_id in task_ids]
        assert statuses == ["AWAITING_COPY_REVIEW"] + ["AWAITING_TOPIC_REVIEW"] * 3
        topic_sets = [{t["id"] for t in (await client.get(f"/tasks/{i}/topics")).json()} for i in task_ids]
        assert len(set().union(*topic_sets)) == 20


class TestBusinessPersistence:
    async def test_status_changes_are_logged_as_events(self, client, task_inputs, make_runner, drain):
        runner = make_runner()
        task_id = await to_topic_review(client, task_inputs, runner, drain)
        events = (await client.get(f"/tasks/{task_id}/events")).json()
        path = [(event["from_status"], event["to_status"]) for event in events]
        assert path == [
            ("CREATED", "QUEUED"),
            ("QUEUED", "GENERATING_TOPICS"),
            ("GENERATING_TOPICS", "AWAITING_TOPIC_REVIEW"),
        ]
        later = (await client.get(f"/tasks/{task_id}/events", params={"after_id": events[1]["id"]})).json()
        assert len(later) == 1

    async def test_compare_and_set_rejects_a_stale_writer(self, client, task_inputs, session_factory):
        from app.core.exceptions import ConflictError
        from app.services.task_service import transition_task

        task_id = await create_task(client, task_inputs)
        async with session_factory() as first, session_factory() as second:
            stale = await first.get(ContentTask, UUID(task_id))
            fresh = await second.get(ContentTask, UUID(task_id))
            await transition_task(second, fresh, TaskStatus.GENERATING_TOPICS)
            await second.commit()
            with pytest.raises(ConflictError):
                await transition_task(first, stale, TaskStatus.CANCELLED)
            await first.rollback()

    async def test_every_change_of_status_increments_the_version(self, client, task_inputs, make_runner, drain, session_factory):
        task_id = await create_task(client, task_inputs)
        before = (await detail(client, task_id))["version"]
        await drain(make_runner())
        assert (await detail(client, task_id))["version"] == before + 2
        async with session_factory() as session:
            count = len((await session.scalars(select(TaskEvent).where(TaskEvent.task_id == UUID(task_id)))).all())
        assert count == 3
