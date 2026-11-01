from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.status import ProductStatus
from app.db.base import Base, created_at_column, enum_column, updated_at_column, uuid_pk


class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = uuid_pk()
    sku: Mapped[str | None] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text)
    key_features: Mapped[list[str]] = mapped_column(JSONB, default=list)
    materials: Mapped[list[str]] = mapped_column(JSONB, default=list)
    suitable_pets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    usage_instructions: Mapped[str | None] = mapped_column(Text)
    safety_notes: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    product_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[ProductStatus] = mapped_column(
        enum_column(ProductStatus), default=ProductStatus.ACTIVE, index=True
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    images: Mapped[list["ProductAsset"]] = relationship(
        back_populates="product", order_by="ProductAsset.created_at", cascade="all, delete-orphan"
    )


class ProductAsset(Base):
    __tablename__ = "product_assets"

    id: Mapped[UUID] = uuid_pk()
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    # Path relative to the storage root; never an absolute server path.
    file_path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int]
    height: Mapped[int]
    created_at: Mapped[datetime] = created_at_column()

    product: Mapped[Product] = relationship(back_populates="images")
