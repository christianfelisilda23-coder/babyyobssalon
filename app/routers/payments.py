import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import Appointment, Payment, PaymentStatus
from app.schemas.schemas import AppointmentBalanceOut, PaymentCreate, PaymentOut, PaymentUpdate

router = APIRouter(prefix="/payments", tags=["payments"])

STAFF_ROLES = ("admin", "front_desk")


async def _get_appointment_or_404(db: AsyncSession, appointment_id: UUID, organization_id: UUID) -> Appointment:
    appointment = (
        await db.execute(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.organization_id == organization_id,
                Appointment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appointment


async def _get_payment_or_404(db: AsyncSession, payment_id: UUID, organization_id: UUID) -> Payment:
    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.organization_id == organization_id,
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    """Records a (possibly partial) payment against an appointment. Split
    payments are allowed: call this once per transaction."""
    appointment = await _get_appointment_or_404(db, payload.appointment_id, principal.organization_id)

    payment = Payment(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        appointment_id=appointment.id,
        amount_cents=payload.amount_cents,
        method=payload.method,
        status=payload.status,
        tip_cents=payload.tip_cents,
        discount_cents=payload.discount_cents,
        reference=payload.reference,
        paid_at=payload.paid_at or (datetime.now(timezone.utc) if payload.status == PaymentStatus.paid else None),
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    appointment_id: UUID | None = None,
    status_filter: PaymentStatus | None = Query(default=None, alias="status"),
    method: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(Payment).where(
        Payment.organization_id == principal.organization_id,
        Payment.deleted_at.is_(None),
    )
    if appointment_id:
        stmt = stmt.where(Payment.appointment_id == appointment_id)
    if status_filter:
        stmt = stmt.where(Payment.status == status_filter)
    if method:
        stmt = stmt.where(Payment.method == method)
    if date_from:
        stmt = stmt.where(Payment.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Payment.created_at <= date_to)
    stmt = stmt.order_by(Payment.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_payment_or_404(db, payment_id, principal.organization_id)


@router.patch("/{payment_id}", response_model=PaymentOut)
async def update_payment(
    payment_id: UUID,
    payload: PaymentUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    payment = await _get_payment_or_404(db, payment_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(payment, field, value)
    payment.updated_by = principal.user_id
    await db.commit()
    await db.refresh(payment)
    return payment


@router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payment(
    payment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    payment = await _get_payment_or_404(db, payment_id, principal.organization_id)
    payment.deleted_at = datetime.now(timezone.utc)
    payment.updated_by = principal.user_id
    await db.commit()


@router.get("/appointments/{appointment_id}/payments", response_model=list[PaymentOut])
async def list_appointment_payments(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await _get_appointment_or_404(db, appointment_id, principal.organization_id)
    result = await db.execute(
        select(Payment)
        .where(
            Payment.organization_id == principal.organization_id,
            Payment.appointment_id == appointment_id,
            Payment.deleted_at.is_(None),
        )
        .order_by(Payment.created_at)
    )
    return result.scalars().all()


@router.get("/appointments/{appointment_id}/balance", response_model=AppointmentBalanceOut)
async def appointment_balance(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Reconciles what was rendered vs what's been paid for an appointment."""
    appointment = await _get_appointment_or_404(db, appointment_id, principal.organization_id)

    paid = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.organization_id == principal.organization_id,
                Payment.appointment_id == appointment.id,
                Payment.status == PaymentStatus.paid,
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    tip = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.tip_cents), 0)).where(
                Payment.organization_id == principal.organization_id,
                Payment.appointment_id == appointment.id,
                Payment.status == PaymentStatus.paid,
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    owed = appointment.total_cents - appointment.discount_cents
    return AppointmentBalanceOut(
        appointment_id=appointment.id,
        total_cents=appointment.total_cents,
        discount_cents=appointment.discount_cents,
        owed_cents=owed,
        paid_cents=int(paid),
        tip_cents=int(tip),
        outstanding_cents=max(0, owed - int(paid)),
        settled=int(paid) >= owed,
    )
