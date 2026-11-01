"""Shared fixtures. Integration tests run against a real PostgreSQL test database.

Override the database with TEST_DATABASE_URL and TEST_LANGGRAPH_DATABASE_URL. The
test database's contents are destroyed, so never point these at real data.
"""

import asyncio
import io
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import psycopg
import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import text

from app.ai.graphs.content_graph import build_content_graph
from app.ai.persistence.checkpointer import open_checkpointer, setup_checkpointer
from app.ai.providers.mock_provider import MockImageProvider, MockLLMProvider
from app.ai.providers.model_router import ModelRouter
from app.ai.runtime import WorkflowDeps
from app.core.config import Settings
from app.db.init_db import run_migrations
from app.db.session import create_engine, create_session_factory
from app.main import create_app
from app.media.storage import LocalStorage
from app.workers.job_queue import JobQueue
from app.workers.job_runner import JobRunner

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://petmedia:petmedia@127.0.0.1:5432/petmedia_test"
)
TEST_LANGGRAPH_URL = os.environ.get(
    "TEST_LANGGRAPH_DATABASE_URL", "postgresql://petmedia:petmedia@127.0.0.1:5432/petmedia_test"
)
BUSINESS_TABLES = (
    "products, brand_profiles, content_tasks, generation_jobs, task_events, approval_records, "
    "topic_suggestions, content_versions, carousel_plans, generated_assets, channel_contents, "
    "customer_reviews, product_assets, content_task_products"
)


def pytest_asyncio_loop_factories(config, item):
    # psycopg's async mode cannot use the Windows default (see app/core/event_loop.py).
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


@pytest.fixture(scope="session")
def storage_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("storage")


@pytest.fixture(scope="session")
def settings(storage_root: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        langgraph_database_url=TEST_LANGGRAPH_URL,
        storage_root=storage_root,
        llm_provider="mock",
        image_provider="mock",
        job_lease_seconds=30,
        log_level="WARNING",
    )


@pytest_asyncio.fixture(scope="session")
async def prepared_database(settings: Settings) -> None:
    """Rebuild both schemas through the real migration paths, once per test session."""
    with psycopg.connect(TEST_LANGGRAPH_URL, autocommit=True) as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {settings.langgraph_schema} CASCADE")
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    run_migrations(settings.database_url)
    await setup_checkpointer(settings)
    LocalStorage(settings.resolved_storage_root).ensure_layout()


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings, prepared_database) -> AsyncIterator:
    engine = create_engine(settings.database_url, pool_size=20)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def clean_db(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {BUSINESS_TABLES} CASCADE"))


@pytest.fixture
def storage(settings: Settings) -> LocalStorage:
    return LocalStorage(settings.resolved_storage_root)


@pytest_asyncio.fixture
async def client(settings, session_factory, storage, clean_db) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    # httpx's ASGI transport does not run lifespan events, so state is set directly.
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.storage = storage
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        yield client


@pytest_asyncio.fixture
async def saver(settings) -> AsyncIterator:
    async with open_checkpointer(settings) as saver:
        yield saver


@pytest.fixture
def make_runner(settings, session_factory, storage, engine, saver):
    """Build a runner that executes real queue jobs in-process."""

    def build(*, llm=None, models=None, image=None, worker_id: str = "test-worker", max_node_attempts: int = 3):
        deps = WorkflowDeps(
            session_factory=session_factory,
            models=models or ModelRouter.uniform(llm or MockLLMProvider()),
            image=image or MockImageProvider(),
            storage=storage,
            settings=settings,
        )
        queue = JobQueue(session_factory, worker_id=worker_id, lease_seconds=settings.job_lease_seconds)
        graph = build_content_graph(saver, max_node_attempts=max_node_attempts, retry_initial_interval=0.01)
        return JobRunner(graph=graph, deps=deps, queue=queue, engine=engine)

    return build


@pytest.fixture
def drain():
    """Run queued jobs until the queue has nothing due, as a worker's loop would."""

    async def run(runner: JobRunner) -> int:
        count = 0
        while (job := await runner.queue.claim()) is not None:
            await runner.run(job)
            count += 1
        return count

    return run


def png_bytes(size=(200, 200), color=(200, 120, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


BRAND_BODY = {
    "brand_name": "Paws & Play",
    "brand_description": "Friendly pet products for curious companions.",
    "brand_voice": ["Friendly", "Trustworthy", "Playful"],
    "target_markets": ["US"],
    "default_locale": "en-US",
    "preferred_cta": "Explore the collection.",
    "prohibited_claims": ["best in the world"],
}
PRODUCT_BODY = {
    "name": "Interactive Cat Ball Toy",
    "category": "Cat Toys",
    "description": "An interactive toy designed to encourage playtime and exploration.",
    "key_features": ["Lightweight design", "Rolling ball mechanism", "Suitable for supervised indoor play"],
}


@pytest_asyncio.fixture
async def task_inputs(client: httpx.AsyncClient) -> dict:
    """A brand and a product with a real photo, created through the API."""
    brand = (await client.post("/brands", json=BRAND_BODY)).json()
    product = (await client.post("/products", json=PRODUCT_BODY)).json()
    response = await client.post(
        f"/products/{product['id']}/images", files={"file": ("cat.png", png_bytes(), "image/png")}
    )
    assert response.status_code == 201
    return {"brand_id": brand["id"], "product_ids": [product["id"]], "image_count": 4}
