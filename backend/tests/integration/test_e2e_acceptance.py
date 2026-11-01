"""The Phase 1 acceptance scenario, against real API and worker processes.

These tests start ``python -m app.serve`` and ``python -m app.workers.main`` as
separate operating system processes and talk to them over HTTP. Restart tests kill
those processes outright, with no chance to clean up, as a real crash would.
"""

import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import psycopg
import pytest
from PIL import Image

from tests.conftest import (
    BRAND_BODY,
    PRODUCT_BODY,
    TEST_DATABASE_URL,
    TEST_LANGGRAPH_URL,
    png_bytes,
)

pytestmark = [pytest.mark.integration, pytest.mark.e2e]

BACKEND_DIR = Path(__file__).resolve().parents[2]
JOB_LEASE_SECONDS = 4


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Processes:
    """Starts and kills the real backend processes."""

    def __init__(self, storage_root: Path, log_dir: Path) -> None:
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}/api/v1"
        self.log_dir = log_dir
        self.env = {
            **os.environ,
            "DATABASE_URL": TEST_DATABASE_URL,
            "LANGGRAPH_DATABASE_URL": TEST_LANGGRAPH_URL,
            "STORAGE_ROOT": str(storage_root),
            "API_PORT": str(self.port),
            "LLM_PROVIDER": "mock",
            "IMAGE_PROVIDER": "mock",
            "JOB_LEASE_SECONDS": str(JOB_LEASE_SECONDS),
            "WORKER_POLL_INTERVAL_SECONDS": "0.2",
            "API_KEY": "",
            "LOG_LEVEL": "INFO",
            "PYTHONUNBUFFERED": "1",
        }
        self.started: list[subprocess.Popen] = []
        self.count = 0

    def _spawn(self, module: str, **extra_env: str) -> subprocess.Popen:
        self.count += 1
        log = open(self.log_dir / f"{self.count}_{module}.log", "wb")  # noqa: SIM115
        process = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=BACKEND_DIR,
            env={**self.env, **extra_env},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        process.log_file = log
        self.started.append(process)
        return process

    async def start_api(self) -> subprocess.Popen:
        process = self._spawn("app.serve")
        async with httpx.AsyncClient() as client:
            for _ in range(150):
                try:
                    if (await client.get(f"{self.base_url}/health/ready")).status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                assert process.poll() is None, self.logs()
                await asyncio.sleep(0.2)
        raise AssertionError(f"The API did not become ready.\n{self.logs()}")

    def start_worker(self, **extra_env: str) -> subprocess.Popen:
        return self._spawn("app.workers.main", **extra_env)

    def kill(self, process: subprocess.Popen) -> None:
        process.kill()  # TerminateProcess on Windows, SIGKILL elsewhere.
        process.wait(timeout=20)
        process.log_file.close()
        self.started.remove(process)

    def stop_all(self) -> None:
        for process in list(self.started):
            self.kill(process)

    def logs(self) -> str:
        return "\n".join(f"--- {p.name}\n{p.read_text(errors='replace')[-3000:]}" for p in sorted(self.log_dir.iterdir()))


@pytest.fixture
def processes(tmp_path, prepared_database, clean_db):
    storage_root = tmp_path / "storage"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    running = Processes(storage_root, log_dir)
    yield running
    running.stop_all()


async def wait_for_status(client: httpx.AsyncClient, task_id: str, status: str, processes: Processes, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    task = {}
    while time.monotonic() < deadline:
        task = (await client.get(f"/tasks/{task_id}")).json()
        if task["status"] == status and not task["decision_in_progress"]:
            return task
        assert task["status"] != "FAILED", f"{task['error']}\n{processes.logs()}"
        await asyncio.sleep(0.15)
    raise AssertionError(f"Expected {status}, last saw {task.get('status')}.\n{processes.logs()}")


async def create_brand_and_product(client: httpx.AsyncClient) -> tuple[dict, dict]:
    brand = await client.post("/brands", json=BRAND_BODY)
    assert brand.status_code == 201
    product = await client.post("/products", json=PRODUCT_BODY)
    assert product.status_code == 201
    upload = await client.post(
        f"/products/{product.json()['id']}/images", files={"file": ("cat.png", png_bytes((600, 600)), "image/png")}
    )
    assert upload.status_code == 201
    return brand.json(), product.json()


async def test_full_acceptance_scenario(processes: Processes):
    await processes.start_api()
    processes.start_worker()
    async with httpx.AsyncClient(base_url=processes.base_url, timeout=30) as client:
        # Steps 1-2: brand and product.
        brand, product = await create_brand_and_product(client)

        # Step 3: content task for both platforms with four images.
        started = time.monotonic()
        response = await client.post(
            "/tasks",
            json={
                "brand_id": brand["id"],
                "product_ids": [product["id"]],
                "target_market": "US",
                "channels": ["instagram", "facebook"],
                "image_count": 4,
            },
        )
        assert response.status_code == 202
        assert time.monotonic() - started < 2, "Task creation must not wait for generation."
        task_id = response.json()["task_id"]

        # Step 4: five English topics.
        await wait_for_status(client, task_id, "AWAITING_TOPIC_REVIEW", processes)
        topics = (await client.get(f"/tasks/{task_id}/topics")).json()
        assert len(topics) == 5
        assert all(topic["title"].isascii() for topic in topics)

        # Step 5: select a topic.
        response = await client.post(
            f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[0]["id"]}
        )
        assert response.status_code == 202

        # Step 6: English draft.
        task = await wait_for_status(client, task_id, "AWAITING_COPY_REVIEW", processes)
        first_version = task["current_version"]
        assert first_version["version_number"] == 1
        assert task["selected_topic"]["id"] == topics[0]["id"]

        # Step 7: revision; the previous version stays accessible.
        feedback = "Make this more informative and less sales-oriented."
        response = await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "revise", "current_version_id": first_version["id"], "feedback": feedback},
        )
        assert response.status_code == 202
        await asyncio.sleep(0)
        task = await wait_for_status(client, task_id, "AWAITING_COPY_REVIEW", processes)
        versions = (await client.get(f"/tasks/{task_id}/versions")).json()
        assert [v["version_number"] for v in versions] == [1, 2]
        assert versions[0]["content"] == first_version["content"]
        assert task["current_version"]["id"] == versions[1]["id"]

        # Step 8: approve; the approved id is persisted.
        response = await client.post(
            f"/tasks/{task_id}/copy-decision", json={"action": "approve", "current_version_id": versions[1]["id"]}
        )
        assert response.status_code == 202

        # Steps 9-10: platform content, four-slide plan and four image files.
        task = await wait_for_status(client, task_id, "AWAITING_IMAGE_REVIEW", processes)
        assert task["approved_version_id"] == versions[1]["id"]
        channels = {c["platform"]: c["payload"] for c in task["channel_contents"]}
        assert channels["instagram"]["caption"] and channels["instagram"]["hashtags"]
        assert channels["facebook"]["post_text"]
        assert len(task["carousel_plan"]) == 4
        assert len(task["assets"]) == 4
        for asset in task["assets"]:
            image_response = await client.get(asset["url"].removeprefix("/api/v1"))
            image = Image.open(io.BytesIO(image_response.content))
            image.load()
            assert image.format == "JPEG" and image.size == (1080, 1350)
        before = {a["slide_number"]: a for a in task["assets"]}

        # Step 11: regenerate slide 2 only.
        response = await client.post(
            f"/tasks/{task_id}/image-decision",
            json={"action": "regenerate", "slide_numbers": [2], "feedback": "Make slide 2 more minimalistic."},
        )
        assert response.status_code == 202
        task = await wait_for_status(client, task_id, "AWAITING_IMAGE_REVIEW", processes)
        after = {a["slide_number"]: a for a in task["assets"]}
        for number in (1, 3, 4):
            assert after[number]["sha256"] == before[number]["sha256"]
        assert after[2]["sha256"] != before[2]["sha256"]

        # Step 12: approve; READY.
        response = await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})
        assert response.status_code == 202
        task = await wait_for_status(client, task_id, "READY", processes)

        # Step 13: combined ZIP.
        response = await client.get(f"/tasks/{task_id}/exports/all")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.testzip() is None
            names = set(archive.namelist())
            assert {"instagram/caption.txt", "facebook/post.txt", "metadata.json"} <= names
            assert {f"instagram/slide_0{n}.jpg" for n in range(1, 5)} <= names
            assert {f"facebook/images/image_0{n}.jpg" for n in range(1, 5)} <= names
            metadata = json.loads(archive.read("metadata.json"))
            assert {i["sha256"] for i in metadata["images"]} == {a["sha256"] for a in task["assets"]}

    # Step 15: verify PostgreSQL directly, bypassing the application.
    with psycopg.connect(TEST_LANGGRAPH_URL) as connection:
        count = lambda table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: E731
        assert count("products") == 1
        assert count("brand_profiles") == 1
        assert count("content_tasks") == 1
        assert count("topic_suggestions") == 5
        assert count("content_versions") == 2
        assert count("approval_records") == 5  # Select, revise, approve, regenerate, approve.
        assert count("generated_assets") == 5  # Four slides plus the superseded slide 2.
        assert count("channel_contents") == 2
        assert count("carousel_plans") == 1
        assert count("generation_jobs") == 6  # The start job plus one per decision.
        assert count("task_events") > 0
        assert count("langgraph.checkpoints") > 0
        unfinished = connection.execute("SELECT count(*) FROM generation_jobs WHERE status <> 'SUCCEEDED'").fetchone()[0]
        assert unfinished == 0


async def test_interrupted_task_survives_killing_both_processes(processes: Processes):
    """Step 14: a paused task resumes after the API and worker are both killed."""
    api = await processes.start_api()
    worker = processes.start_worker()
    async with httpx.AsyncClient(base_url=processes.base_url, timeout=30) as client:
        brand, product = await create_brand_and_product(client)
        response = await client.post(
            "/tasks", json={"brand_id": brand["id"], "product_ids": [product["id"]], "image_count": 3}
        )
        task_id = response.json()["task_id"]
        await wait_for_status(client, task_id, "AWAITING_TOPIC_REVIEW", processes)
        topics = (await client.get(f"/tasks/{task_id}/topics")).json()

    processes.kill(worker)
    processes.kill(api)

    # With the worker gone, decisions are accepted but wait durably in the queue.
    api = await processes.start_api()
    async with httpx.AsyncClient(base_url=processes.base_url, timeout=30) as client:
        task = (await client.get(f"/tasks/{task_id}")).json()
        assert task["status"] == "AWAITING_TOPIC_REVIEW"
        response = await client.post(
            f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[1]["id"]}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "GENERATING_COPY"
        repeat = await client.post(
            f"/tasks/{task_id}/topic-decision", json={"action": "select", "selected_topic_id": topics[1]["id"]}
        )
        assert repeat.status_code == 409

        worker = processes.start_worker()
        task = await wait_for_status(client, task_id, "AWAITING_COPY_REVIEW", processes)
        assert task["selected_topic"]["id"] == topics[1]["id"]
        # The earlier topics were reused, so the graph continued rather than restarted.
        assert [t["id"] for t in (await client.get(f"/tasks/{task_id}/topics")).json()] == [t["id"] for t in topics]

        # Restart once more while paused at copy review, then finish the whole workflow.
        processes.kill(worker)
        processes.start_worker()
        response = await client.post(
            f"/tasks/{task_id}/copy-decision",
            json={"action": "approve", "current_version_id": task["current_version"]["id"]},
        )
        assert response.status_code == 202
        task = await wait_for_status(client, task_id, "AWAITING_IMAGE_REVIEW", processes)
        assert len(task["assets"]) == 3
        await client.post(f"/tasks/{task_id}/image-decision", json={"action": "approve"})
        await wait_for_status(client, task_id, "READY", processes)
        assert (await client.get(f"/tasks/{task_id}/exports/all")).status_code == 200


async def test_worker_killed_mid_generation_is_recovered_by_another_worker(processes: Processes):
    """A hard crash in the middle of a slow node: the lease expires and the job is taken over."""
    await processes.start_api()
    slow_worker = processes.start_worker(MOCK_LLM_DELAY_SECONDS="60")
    async with httpx.AsyncClient(base_url=processes.base_url, timeout=30) as client:
        brand, product = await create_brand_and_product(client)
        response = await client.post("/tasks", json={"brand_id": brand["id"], "product_ids": [product["id"]]})
        task_id = response.json()["task_id"]

        deadline = time.monotonic() + 30
        while (await client.get(f"/tasks/{task_id}")).json()["status"] != "GENERATING_TOPICS":
            assert time.monotonic() < deadline, processes.logs()
            await asyncio.sleep(0.1)

        processes.kill(slow_worker)
        processes.start_worker()
        await wait_for_status(client, task_id, "AWAITING_TOPIC_REVIEW", processes, timeout=JOB_LEASE_SECONDS + 30)
        assert len((await client.get(f"/tasks/{task_id}/topics")).json()) == 5

    with psycopg.connect(TEST_LANGGRAPH_URL) as connection:
        status, attempts = connection.execute("SELECT status, attempts FROM generation_jobs").fetchone()
    assert (status, attempts) == ("SUCCEEDED", 2)
