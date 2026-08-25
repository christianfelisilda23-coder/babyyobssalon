"""Catalog: categories, services, packages, products."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

__all__ = ["ServiceCategory", "Service", "ServicePackage", "ServicePackageItem", "Product"]


class ServiceCategory(TimestampMixin, Base):
    """Grouping for services (Hair, Nails, Spa, ...)."""

    __tablename__ = "service_categories"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_service_categories_org_name"),
        Index("ix_service_categories_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        CheckConstraint("price_cents >= 0", name="ck_services_price_nonnegative"),
        Index("ix_services_organization_id", "organization_id"),
        Index("ix_services_organization_id_active", "organization_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_categories.id"), nullable=True
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization: Mapped["Organization"] = relationship(back_populates="services")
    staff_services: Mapped[list["StaffService"]] = relationship(back_populates="service")


class ServicePackage(TimestampMixin, Base):
    """Bundle of services sold at a fixed price (see service_package_items)."""

    __tablename__ = "service_packages"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="ck_packages_price_nonnegative"),
        Index("ix_packages_organization_id", "organization_id"),
        Index("ix_packages_org_active", "organization_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    items: Mapped[list["ServicePackageItem"]] = relationship(back_populates="package")


class ServicePackageItem(Base):
    """Many-to-many: which services (and how many) make up a package."""

    __tablename__ = "service_package_items"
    __table_args__ = (Index("ix_package_items_organization_id", "organization_id"),)

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_packages.id"), primary_key=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("services.id"), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    package: Mapped["ServicePackage"] = relationship(back_populates="items")
    service: Mapped["Service"] = relationship()


class Product(TimestampMixin, Base):
    """Retail / consumable inventory item."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_products_stock_nonnegative"),
        CheckConstraint("price_cents >= 0", name="ck_products_price_nonnegative"),
        Index("ix_products_organization_id", "organization_id"),
        Index("ix_products_org_active", "organization_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="unit")
    stock_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
