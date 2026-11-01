from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.status import AssetStatus


class AssetRead(BaseModel):
    id: UUID
    slide_number: int
    asset_version: int
    status: AssetStatus
    url: str
    width: int
    height: int
    file_size: int
    sha256: str
    provider: str
    is_mock: bool
    visual_feedback: str | None
    source_content_version_id: UUID
    carousel_plan_id: UUID
    created_at: datetime


class ExportOption(BaseModel):
    name: str
    url: str
    available: bool


class ExportList(BaseModel):
    task_id: UUID
    ready: bool
    exports: list[ExportOption]
