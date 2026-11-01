from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[UUID] = uuid_pk()
    brand_name: Mapped[str] = mapped_column(String(255), unique=True)
    brand_description: Mapped[str | None] = mapped_column(Text)
    brand_voice: Mapped[list[str]] = mapped_column(JSONB, default=list)
    target_audience: Mapped[str | None] = mapped_column(Text)
    default_locale: Mapped[str] = mapped_column(String(20), default="en-US")
    target_markets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    marketing_goals: Mapped[list[str]] = mapped_column(JSONB, default=list)
    preferred_cta: Mapped[str | None] = mapped_column(String(255))
    prohibited_claims: Mapped[list[str]] = mapped_column(JSONB, default=list)
    style_guidelines: Mapped[str | None] = mapped_column(Text)
    logo_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
