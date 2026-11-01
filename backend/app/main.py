"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.security import require_api_key
from app.db.session import create_engine, create_session_factory
from app.media.storage import LocalStorage

logger = logging.getLogger(__name__)


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError) -> JSONResponse:
        if error.status_code >= 500:
            logger.error("Request failed", extra={"error_type": error.code})
        return JSONResponse(_error_body(error.code, error.message, error.details), status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        errors = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse(
            _error_body("VALIDATION_ERROR", "The request is invalid.", {"errors": errors}), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_error_body(f"HTTP_{error.status_code}", str(error.detail)), status_code=error.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        # The traceback goes to the logs and never into the response.
        logger.exception("Unhandled error", exc_info=error)
        return JSONResponse(_error_body("INTERNAL_ERROR", "An unexpected error occurred."), status_code=500)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        storage = LocalStorage(settings.resolved_storage_root)
        storage.ensure_layout()
        app.state.settings = settings
        app.state.session_factory = create_session_factory(engine)
        app.state.storage = storage
        yield
        await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Backend for AI-assisted Instagram and Facebook content production.",
        lifespan=lifespan,
        dependencies=[Depends(require_api_key)],
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key"],
        )
    _register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app
