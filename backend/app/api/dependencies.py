"""Request-scoped dependencies shared by the API routes."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import MediaError
from app.media.storage import Storage


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
StorageDep = Annotated[Storage, Depends(get_storage)]


async def read_upload_limited(upload: UploadFile, settings: Settings) -> bytes:
    """Read at most the allowed size, so an oversized upload cannot exhaust memory."""
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise MediaError(
            f"The uploaded file exceeds the {settings.max_upload_bytes}-byte limit.",
            code="UPLOAD_TOO_LARGE",
            details={"max_bytes": settings.max_upload_bytes},
        )
    return data
