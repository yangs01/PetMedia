from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BrandCreate(BaseModel):
    brand_name: str = Field(min_length=1, max_length=255)
    brand_description: str | None = None
    brand_voice: list[str] = Field(default_factory=list, max_length=20)
    target_audience: str | None = None
    default_locale: str = Field(default="en-US", pattern=r"^en(-[A-Z]{2})?$")
    target_markets: list[str] = Field(default_factory=list, max_length=20)
    marketing_goals: list[str] = Field(default_factory=list, max_length=20)
    preferred_cta: str | None = Field(default=None, max_length=255)
    prohibited_claims: list[str] = Field(default_factory=list, max_length=100)
    style_guidelines: str | None = None


class BrandUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    brand_name: str | None = Field(default=None, min_length=1, max_length=255)
    brand_description: str | None = None
    brand_voice: list[str] | None = Field(default=None, max_length=20)
    target_audience: str | None = None
    default_locale: str | None = Field(default=None, pattern=r"^en(-[A-Z]{2})?$")
    target_markets: list[str] | None = Field(default=None, max_length=20)
    marketing_goals: list[str] | None = Field(default=None, max_length=20)
    preferred_cta: str | None = Field(default=None, max_length=255)
    prohibited_claims: list[str] | None = Field(default=None, max_length=100)
    style_guidelines: str | None = None


class BrandRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    brand_name: str
    brand_description: str | None
    brand_voice: list[str]
    target_audience: str | None
    default_locale: str
    target_markets: list[str]
    marketing_goals: list[str]
    preferred_cta: str | None
    prohibited_claims: list[str]
    style_guidelines: str | None
    has_logo: bool = False
    created_at: datetime
    updated_at: datetime
