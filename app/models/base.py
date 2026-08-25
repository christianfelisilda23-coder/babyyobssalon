"""Shared enums and mixins for all ORM models."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = ["Base", "AppointmentStatus", "PaymentMethod", "PaymentStatus", "LEGAL_TRANSITIONS", "TimestampMixin"]


class AppointmentStatus(str, enum.Enum):
    requested = "requested"
    confirmed = "confirmed"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    card = "card"
    ewallet = "ewallet"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    refunded = "refunded"


# Legal status transitions, enforced in app/services/appointments.py.
LEGAL_TRANSITIONS: dict[AppointmentStatus, set[AppointmentStatus]] = {
    AppointmentStatus.requested: {AppointmentStatus.confirmed, AppointmentStatus.cancelled},
    AppointmentStatus.confirmed: {
        AppointmentStatus.in_progress,
        AppointmentStatus.cancelled,
        AppointmentStatus.no_show,
    },
    AppointmentStatus.in_progress: {AppointmentStatus.completed, AppointmentStatus.cancelled},
    AppointmentStatus.completed: set(),
    AppointmentStatus.cancelled: set(),
    AppointmentStatus.no_show: set(),
}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
