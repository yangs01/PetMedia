from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.dependencies import SessionDep, SettingsDep, StorageDep
from app.services.health_service import readiness_checks

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: SettingsDep) -> dict[str, str]:
    """Liveness: the API process is running."""
    return {"status": "ok", "app": settings.app_name, "environment": settings.app_env}


@router.get("/health/ready")
async def ready(session: SessionDep, settings: SettingsDep, storage: StorageDep) -> JSONResponse:
    """Readiness: returns 503 if a required dependency is unavailable."""
    checks = await readiness_checks(session, settings, storage)
    is_ready = all(checks.values())
    return JSONResponse(
        {
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
            "providers": {"llm": settings.llm_provider, "image": settings.image_provider},
        },
        status_code=200 if is_ready else 503,
    )
