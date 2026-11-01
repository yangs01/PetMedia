"""API process: ``uv run python -m app.serve``. See ``core/event_loop.py`` for why."""

import uvicorn

from app.core.config import get_settings
from app.core.event_loop import run_async
from app.main import create_app


def main() -> None:
    settings = get_settings()
    config = uvicorn.Config(create_app(settings), host=settings.api_host, port=settings.api_port, log_config=None)
    run_async(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
