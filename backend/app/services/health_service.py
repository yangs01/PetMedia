"""Readiness checks for the dependencies the system cannot work without."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.media.storage import Storage


async def readiness_checks(session: AsyncSession, settings: Settings, storage: Storage) -> dict[str, bool]:
    checks = {"database": False, "migrations": False, "checkpoints": False, "storage": False}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = True
        checks["migrations"] = bool(await session.scalar(text("SELECT to_regclass('public.alembic_version')")))
        checks["checkpoints"] = bool(
            await session.scalar(
                text("SELECT to_regclass(:name)"), {"name": f"{settings.langgraph_schema}.checkpoints"}
            )
        )
    except SQLAlchemyError:
        await session.rollback()

    probe = f"exports/.ready-{uuid4().hex}"
    try:
        storage.save_bytes(probe, b"")
        storage.path_for(probe).unlink()
        checks["storage"] = True
    except OSError:
        pass
    return checks
