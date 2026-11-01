"""Initialize both database areas: ``uv run python -m app.db.init_db``.

Business tables are managed by Alembic. LangGraph tables are managed by the
official saver's ``setup()``, in their own schema.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.ai.persistence.checkpointer import setup_checkpointer
from app.core.config import Settings, get_settings
from app.core.event_loop import run_async
from app.media.storage import LocalStorage

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    # ConfigParser treats "%" as interpolation, so percent-encoded passwords must be doubled.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run_migrations(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def init_database(settings: Settings) -> None:
    run_migrations(settings.database_url)
    run_async(setup_checkpointer(settings))
    LocalStorage(settings.resolved_storage_root).ensure_layout()


if __name__ == "__main__":
    init_database(get_settings())
    print("Database and storage initialized.")
