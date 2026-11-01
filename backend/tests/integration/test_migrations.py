"""Migrations must match the models and must run in both directions."""

from uuid import uuid4

import psycopg
import pytest
from alembic import command

from app.db.init_db import alembic_config, run_migrations
from tests.conftest import TEST_LANGGRAPH_URL

pytestmark = pytest.mark.integration


def test_models_and_migrations_have_not_drifted(settings, prepared_database):
    # Raises if autogenerate would produce any operation, such as a missing foreign key.
    command.check(alembic_config(settings.database_url))


@pytest.mark.parametrize(
    "column", ["selected_topic_id", "current_content_version_id", "approved_content_version_id"]
)
async def test_task_references_are_enforced_by_foreign_keys(client, task_inputs, column):
    task_id = (await client.post("/tasks", json=task_inputs)).json()["task_id"]
    with psycopg.connect(TEST_LANGGRAPH_URL) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(f"UPDATE content_tasks SET {column} = %s WHERE id = %s", (uuid4(), task_id))


async def test_downgrade_and_upgrade_round_trip(settings, clean_db, engine):
    await engine.dispose()  # Pooled connections must not hold locks on the dropped tables.
    command.downgrade(alembic_config(settings.database_url), "base")
    with psycopg.connect(TEST_LANGGRAPH_URL) as connection:
        assert connection.execute("SELECT to_regclass('public.content_tasks')").fetchone()[0] is None
    run_migrations(settings.database_url)
    with psycopg.connect(TEST_LANGGRAPH_URL) as connection:
        assert connection.execute("SELECT to_regclass('public.content_tasks')").fetchone()[0] is not None
