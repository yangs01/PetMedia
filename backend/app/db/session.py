"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(database_url: str, *, pool_size: int = 10) -> AsyncEngine:
    return create_async_engine(database_url, pool_size=pool_size, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    # expire_on_commit=False lets callers read an object after the transaction that wrote it.
    return async_sessionmaker(engine, expire_on_commit=False)
