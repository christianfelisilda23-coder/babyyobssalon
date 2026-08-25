"""Operational entities: appointments, rendered services, payments,
commissions, product usage, and the service-history log."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AppointmentStatus, Base, PaymentMethod, PaymentStatus, TimestampMixin

__all__ = [
    "Appointment",
    "AppointmentService",
    "ProductUsage",
    "Payment",
    "Commission",
    "ServiceHistory",
]


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_appointments_end_after_start"),
        CheckConstraint("discount_cents >= 0", name="ck_appointments_discount_nonnegative"),
        CheckConstraint("total_cents >= 0", name="ck_appointments_total_nonnegative"),
        CheckConstraint(
            "(client_id IS NOT NULL AND walk_in_id IS NULL) OR (client_id IS NULL AND walk_in_id IS NOT NULL)",
            name="ck_appointments_client_or_walkin",
        ),
        Index("ix_appointments_organization_id", "organization_id"),
        Index("ix_appointments_org_staff_start", "organization_id", "staff_id", "start_time"),
        Index("ix_appointments_org_client", "organization_id", "client_id"),
        Index("ix_appointments_org_walkin", "organization_id", "walk_in_id"),
        Index("ix_appointments_org_status", "organization_id", "status"),
        Index("ix_appointments_org_start", "organization_id", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True
    )
    walk_in_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("walk_in_customers.id"), nullable=True
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False)
    # Legacy single-service reference; the authoritative set of rendered
    # services lives in `appointment_services`. Kept (nullable) so the
    # original single-service contract keeps working.
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=True
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_packages.id"), nullable=True
    )
    package_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status"),
        nullable=False,
        default=AppointmentStatus.requested,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="appointments")
    client: Mapped["Client | None"] = relationship()
    walk_in: Mapped["WalkInCustomer | None"] = relationship()
    staff: Mapped["Staff"] = relationship()
    service: Mapped["Service | None"] = relationship()
    package: Mapped["ServicePackage | None"] = relationship()
    appointment_services: Mapped[list["AppointmentService"]] = relationship(back_populates="appointment")
    product_usage: Mapped[list["ProductUsage"]] = relationship(back_populates="appointment")
    payments: Mapped[list["Payment"]] = relationship(back_populates="appointment")
    commissions: Mapped[list["Commission"]] = relationship(back_populates="appointment")


class AppointmentService(TimestampMixin, Base):
    """
    One line = one rendered service on an appointment (packages are
    expanded into these rows at booking time so reporting + commissions
    work at the service level). Name/price/duration are snapshotted at
    booking so later price changes don't rewrite history.
    """

    __tablename__ = "appointment_services"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="ck_appt_services_price_nonnegative"),
        CheckConstraint("quantity > 0", name="ck_appt_services_quantity_positive"),
        Index("ix_appointment_services_organization_id", "organization_id"),
        Index("ix_appointment_services_appointment_id", "appointment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=False
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=True
    )
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    commission_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    appointment: Mapped["Appointment"] = relationship(back_populates="appointment_services")


class ProductUsage(TimestampMixin, Base):
    """Products consumed during an appointment. Stock is deducted on
    appointment completion (blocked if insufficient)."""

    __tablename__ = "product_usage"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_product_usage_quantity_positive"),
        Index("ix_product_usage_organization_id", "organization_id"),
        Index("ix_product_usage_appointment_id", "appointment_id"),
        Index("ix_product_usage_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    appointment: Mapped["Appointment"] = relationship(back_populates="product_usage")
    product: Mapped["Product | None"] = relationship()


class Payment(TimestampMixin, Base):
    """One row per payment transaction against an appointment (split
    payments are allowed - a single appointment can have many rows)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_payments_amount_nonnegative"),
        CheckConstraint("tip_cents >= 0", name="ck_payments_tip_nonnegative"),
        CheckConstraint("discount_cents >= 0", name="ck_payments_discount_nonnegative"),
        Index("ix_payments_organization_id", "organization_id"),
        Index("ix_payments_appointment_id", "appointment_id"),
        Index("ix_payments_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method"), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), nullable=False, default=PaymentStatus.pending
    )
    tip_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    appointment: Mapped["Appointment"] = relationship(back_populates="payments")


class Commission(TimestampMixin, Base):
    """
    Specialist earnings. One row per rendered service line at completion.
    Rate comes from the per-service override (appointment_services) or the
    specialist's default rate.
    """

    __tablename__ = "commissions"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_commissions_amount_nonnegative"),
        CheckConstraint("rate_pct >= 0", name="ck_commissions_rate_nonnegative"),
        Index("ix_commissions_organization_id", "organization_id"),
        Index("ix_commissions_appointment_id", "appointment_id"),
        Index("ix_commissions_specialist_id", "specialist_id"),
        Index("ix_commissions_org_specialist_created", "organization_id", "specialist_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=False
    )
    specialist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("specialists.id"), nullable=True
    )
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    appointment: Mapped["Appointment"] = relationship(back_populates="commissions")
    specialist: Mapped["Specialist | None"] = relationship(back_populates="commissions")


class ServiceHistory(TimestampMixin, Base):
    """Denormalized log of completed services per client. Auto-populated
    when an appointment moves to `completed`."""

    __tablename__ = "service_history"
    __table_args__ = (
        Index("ix_service_history_organization_id", "organization_id"),
        Index("ix_service_history_client_id", "client_id"),
        Index("ix_service_history_client_completed", "client_id", "completed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=True
    )
    specialist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("specialists.id"), nullable=True
    )
    service_name: Mapped[str] = mapped_column(String(120), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    client: Mapped["Client"] = relationship(back_populates="history")
