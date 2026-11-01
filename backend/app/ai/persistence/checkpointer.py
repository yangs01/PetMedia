"""Official PostgreSQL checkpointer setup.

The saver's SQL uses unqualified table names, so setting ``search_path`` on its
connections places LangGraph's tables in their own schema without touching them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings

# Arbitrary fixed key: concurrent worker startups take turns running migrations.
_SETUP_LOCK_KEY = 7306115


def checkpoint_conninfo(settings: Settings) -> str:
    return make_conninfo(
        settings.langgraph_database_url, options=f"-c search_path={settings.langgraph_schema}"
    )


@asynccontextmanager
async def open_checkpointer(settings: Settings, *, max_size: int = 10) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a saver backed by a connection pool and close it reliably on exit."""
    pool = AsyncConnectionPool(
        conninfo=checkpoint_conninfo(settings),
        min_size=1,
        max_size=max_size,
        open=False,
        # Connection settings the saver requires (see AsyncPostgresSaver.from_conn_string).
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    try:
        yield AsyncPostgresSaver(pool)
    finally:
        await pool.close()


async def setup_checkpointer(settings: Settings) -> None:
    """Create the schema and run the saver's own migrations. Safe to run repeatedly."""
    schema = settings.langgraph_schema  # Restricted to a safe identifier by Settings.
    async with await psycopg.AsyncConnection.connect(
        settings.langgraph_database_url, autocommit=True
    ) as connection:
        await connection.execute("SELECT pg_advisory_lock(%s)", (_SETUP_LOCK_KEY,))
        try:
            await connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            async with open_checkpointer(settings, max_size=2) as saver:
                await saver.setup()
        finally:
            await connection.execute("SELECT pg_advisory_unlock(%s)", (_SETUP_LOCK_KEY,))
