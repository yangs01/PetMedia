"""Structured logging on top of the standard library.

Each line is a JSON object. ``bind_log_context`` attaches identifiers such as
task_id and job_id to every line logged in the current asyncio task, so call
sites do not have to pass them around.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)

# Attributes every LogRecord has; anything else came from the ``extra`` argument.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **(_log_context.get() or {}),
        }
        entry.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # httpx logs full request URLs at INFO; they add noise without adding diagnostics.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@contextmanager
def bind_log_context(**values: Any) -> Iterator[None]:
    token = _log_context.set({**(_log_context.get() or {}), **values})
    try:
        yield
    finally:
        _log_context.reset(token)
