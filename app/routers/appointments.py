from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models import Appointment, AppointmentStatus, Staff
from app.schemas.schemas import AppointmentCreate, AppointmentOut, AppointmentStatusUpdate
from app.services import appointments as appointment_service

router = APIRouter(prefix="/appointments", tags=["appointments"])

FRONT_DESK_ROLES = ("admin", "front_desk")


def _owned_appointment_stmt(organization_id: UUID, appointment_id: UUID):
    return (
        select(Appointment)
        .options(selectinload(Appointment.appointment_services))
        .where(
            Appointment.id == appointment_id,
            Appointment.organization_id == organization_id,
            Appointment.deleted_at.is_(None),
        )
    )


async def _get_appointment_or_404(db: AsyncSession, appointment_id: UUID, organization_id: UUID) -> Appointment:
    appt = (await db.execute(_owned_appointment_stmt(organization_id, appointment_id))).scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appt


async def _ensure_can_transition(db: AsyncSession, principal: Principal, appointment: Appointment) -> None:
    """Admins + front desk can transition any appointment; specialists can
    only touch appointments assigned to their own staff record."""
    if principal.role in FRONT_DESK_ROLES:
        return
    if principal.role == "specialist":
        staff = await appointment_service.resolve_staff_from_user(
            db, principal.organization_id, principal.user_id
        )
        if staff is None or staff.id != appointment.staff_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Specialists can only update their own appointments",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient role to update appointments",
    )


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Books a client or walk-in into a slot with one or more services (or a
    package, which is expanded to service lines). Returns 409
    SCHEDULE_CONFLICT if the staff member is already booked.
    """
    return await appointment_service.create_appointment(
        db=db,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        payload=payload,
    )


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    staff_id: UUID | None = None,
    client_id: UUID | None = None,
    walk_in_id: UUID | None = None,
    status_filter: AppointmentStatus | None = Query(default=None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Calendar/list view — powers the (organization_id, staff_id, start_time) index."""
    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.appointment_services))
        .where(
            Appointment.organization_id == principal.organization_id,
            Appointment.deleted_at.is_(None),
        )
    )
    if staff_id:
        stmt = stmt.where(Appointment.staff_id == staff_id)
    if client_id:
        stmt = stmt.where(Appointment.client_id == client_id)
    if walk_in_id:
        stmt = stmt.where(Appointment.walk_in_id == walk_in_id)
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    if date_from:
        stmt = stmt.where(Appointment.start_time >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.start_time <= date_to)

    stmt = stmt.order_by(Appointment.start_time).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_appointment_or_404(db, appointment_id, principal.organization_id)


@router.post("/{appointment_id}/status", response_model=AppointmentOut)
async def update_appointment_status(
    appointment_id: UUID,
    payload: AppointmentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Transitions an appointment through its state machine:
    requested -> confirmed -> in_progress -> completed
                       \\-> cancelled          \\-> cancelled
                       \\-> no_show (from confirmed)
    """
    appointment = await _get_appointment_or_404(db, appointment_id, principal.organization_id)
    await _ensure_can_transition(db, principal, appointment)
    return await appointment_service.transition_status(
        db=db,
        appointment=appointment,
        new_status=payload.status,
        user_id=principal.user_id,
        cancellation_reason=payload.cancellation_reason,
    )


@router.post("/{appointment_id}/complete", response_model=AppointmentOut)
async def complete_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """
    Shorthand for marking an in_progress appointment complete. Triggers the
    completion pipeline: stock deduction, commission generation, and service
    history. 400 INSUFFICIENT_STOCK if any consumed product is understocked.
    """
    appointment = await _get_appointment_or_404(db, appointment_id, principal.organization_id)
    await _ensure_can_transition(db, principal, appointment)
    return await appointment_service.transition_status(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.completed,
        user_id=principal.user_id,
    )
