"""Event loop selection.

psycopg's async mode cannot run on Windows' default ProactorEventLoop, so every
process entry point (API server, worker) starts through ``run_async``. This is
also why the API is launched with ``python -m app.serve`` instead of the plain
``uvicorn`` command, which would choose the Proactor loop on Windows.
"""

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run_async[T](main: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        return asyncio.run(main, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(main)
