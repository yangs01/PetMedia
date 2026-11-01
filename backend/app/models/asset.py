from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.status import AssetStatus
from app.db.base import Base, created_at_column, enum_column, uuid_pk


class CarouselPlan(Base):
    __tablename__ = "carousel_plans"
    __table_args__ = (UniqueConstraint("task_id", "content_version_id", name="uq_carousel_plan_task_version"),)

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    content_version_id: Mapped[UUID] = mapped_column(ForeignKey("content_versions.id", ondelete="RESTRICT"))
    slides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_column()


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"
    __table_args__ = (
        UniqueConstraint("task_id", "slide_number", "asset_version", name="uq_asset_slide_version"),
        UniqueConstraint("task_id", "slide_number", "request_key", name="uq_asset_slide_request"),
        # At most one current image per slide; superseded versions stay as history.
        Index(
            "uq_asset_current_slide",
            "task_id",
            "slide_number",
            unique=True,
            postgresql_where=text("status IN ('ACTIVE', 'APPROVED')"),
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("content_tasks.id", ondelete="CASCADE"), index=True)
    carousel_plan_id: Mapped[UUID] = mapped_column(ForeignKey("carousel_plans.id", ondelete="CASCADE"))
    source_content_version_id: Mapped[UUID] = mapped_column(ForeignKey("content_versions.id", ondelete="RESTRICT"))
    slide_number: Mapped[int]
    asset_version: Mapped[int]
    # "initial" or the approval record that asked for this regeneration.
    request_key: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(50), default="image/jpeg")
    width: Mapped[int]
    height: Mapped[int]
    file_size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    generation_prompt: Mapped[str] = mapped_column(Text)
    visual_feedback: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(100))
    is_mock: Mapped[bool] = mapped_column(default=False)
    status: Mapped[AssetStatus] = mapped_column(enum_column(AssetStatus), default=AssetStatus.ACTIVE)
    created_at: Mapped[datetime] = created_at_column()
