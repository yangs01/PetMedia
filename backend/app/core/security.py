"""Optional single-operator API key check (Phase 1 has no user accounts)."""

import secrets

from fastapi import Header

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured = get_settings().api_key
    if configured is None or not configured.get_secret_value():
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, configured.get_secret_value()):
        raise AuthenticationError("A valid X-API-Key header is required.")
