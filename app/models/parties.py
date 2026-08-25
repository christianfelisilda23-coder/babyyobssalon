"""Organizations, clients, walk-ins, preferences, and the demo login user."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

__all__ = ["Organization", "Client", "WalkInCustomer", "CustomerPreference", "PlatformUser"]


class Organization(Base):
    """
    Owned by the ARGO platform in production - this module only references
    it. Kept as a real table here so the schema is runnable standalone.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    clients: Mapped[list["Client"]] = relationship(back_populates="organization")
    staff: Mapped[list["Staff"]] = relationship(back_populates="organization")
    services: Mapped[list["Service"]] = relationship(back_populates="organization")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="organization")


class Client(TimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        Index("ix_clients_organization_id", "organization_id"),
        Index("ix_clients_organization_id_phone", "organization_id", "phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="clients")
    preferences: Mapped["CustomerPreference | None"] = relationship(
        back_populates="client", uselist=False, cascade="all, delete-orphan"
    )
    history: Mapped[list["ServiceHistory"]] = relationship(back_populates="client")


class WalkInCustomer(TimestampMixin, Base):
    """
    Unregistered / unscheduled visitor. Can be converted into a full
    `Client` later via POST /walk-ins/{id}/convert-to-client, which keeps
    any service history accumulated while still a walk-in.
    """

    __tablename__ = "walk_in_customers"
    __table_args__ = (
        Index("ix_walk_ins_organization_id", "organization_id"),
        Index("ix_walk_ins_org_phone", "organization_id", "phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    converted_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True
    )

    converted_client: Mapped["Client | None"] = relationship()


class CustomerPreference(TimestampMixin, Base):
    """1-1 preferences attached to a registered client."""

    __tablename__ = "customer_preferences"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_id", name="uq_customer_preferences_client"),
        Index("ix_customer_preferences_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    preferred_specialist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=True
    )
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_sensitivities: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="preferences")


class PlatformUser(Base):
    """
    DEMO-ONLY stand-in for the ARGO platform's real identity provider.
    Not part of the official schema - exists purely so this module can
    register/login users and issue JWTs when run standalone. Delete this
    model (and app/routers/auth.py's register/login) once wired into the
    real platform's auth.
    """

    __tablename__ = "platform_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
