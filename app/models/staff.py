"""Staff, specialists (extend staff), and specialist specialties."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

__all__ = ["Staff", "Specialist", "SpecialistSpecialty", "StaffService"]


class Staff(TimestampMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (
        Index("ix_staff_organization_id", "organization_id"),
        UniqueConstraint("organization_id", "user_id", name="uq_staff_org_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization: Mapped["Organization"] = relationship(back_populates="staff")
    staff_services: Mapped[list["StaffService"]] = relationship(back_populates="staff")
    specialist: Mapped["Specialist | None"] = relationship(
        back_populates="staff", uselist=False, cascade="all, delete-orphan"
    )


class Specialist(TimestampMixin, Base):
    """
    Extends `staff` with commission data: a default commission rate and the
    service categories this specialist is qualified for (via
    `specialist_specialties`).
    """

    __tablename__ = "specialists"
    __table_args__ = (
        CheckConstraint("default_commission_rate_pct >= 0", name="ck_specialists_rate_nonnegative"),
        UniqueConstraint("organization_id", "staff_id", name="uq_specialists_staff"),
        Index("ix_specialists_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False)
    default_commission_rate_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("15.00")
    )

    staff: Mapped["Staff"] = relationship(back_populates="specialist")
    specialties: Mapped[list["SpecialistSpecialty"]] = relationship(back_populates="specialist")
    commissions: Mapped[list["Commission"]] = relationship(back_populates="specialist")


class SpecialistSpecialty(Base):
    """Junction: which service categories a specialist is qualified for."""

    __tablename__ = "specialist_specialties"
    __table_args__ = (Index("ix_specialist_specialties_organization_id", "organization_id"),)

    specialist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("specialists.id"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_categories.id"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    specialist: Mapped["Specialist"] = relationship(back_populates="specialties")
    category: Mapped["ServiceCategory"] = relationship()


class StaffService(Base):
    """Junction table: which staff members are qualified for which services."""

    __tablename__ = "staff_services"
    __table_args__ = (Index("ix_staff_services_organization_id", "organization_id"),)

    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.id"), primary_key=True)
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("services.id"), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    staff: Mapped["Staff"] = relationship(back_populates="staff_services")
    service: Mapped["Service"] = relationship(back_populates="staff_services")
