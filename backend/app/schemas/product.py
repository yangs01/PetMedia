from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.core.status import ProductStatus

ShortList = Annotated[list[Annotated[str, Field(min_length=1, max_length=500)]], Field(max_length=50)]


class ProductFields(BaseModel):
    sku: str | None = Field(default=None, max_length=100)
    key_features: ShortList = Field(default_factory=list)
    materials: ShortList = Field(default_factory=list)
    suitable_pets: ShortList = Field(default_factory=list)
    usage_instructions: str | None = None
    safety_notes: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    product_url: HttpUrl | None = None


class ProductCreate(ProductFields):
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)


class ProductUpdate(ProductFields):
    """Partial update: only fields present in the request body are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1)
    status: ProductStatus | None = None

    @field_validator("key_features", "materials", "suitable_pets", mode="before")
    @classmethod
    def _null_means_empty(cls, value: object) -> object:
        return [] if value is None else value


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str | None
    name: str
    category: str
    description: str
    key_features: list[str]
    materials: list[str]
    suitable_pets: list[str]
    usage_instructions: str | None
    safety_notes: str | None
    price: Decimal | None
    currency: str | None
    product_url: str | None
    status: ProductStatus
    created_at: datetime
    updated_at: datetime


class ProductImageRead(BaseModel):
    id: UUID
    product_id: UUID
    url: str
    mime_type: str
    width: int
    height: int
    created_at: datetime
