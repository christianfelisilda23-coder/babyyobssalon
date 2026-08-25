"""
Appointment booking + lifecycle logic.

Booking:
  1. Validate that client/walk-in/staff/service(s)/package belong to the
     caller's organization_id (taken from the JWT, never the request body).
  2. BEGIN TRANSACTION.
  3. Lock the staff member's schedule (`SELECT ... FOR UPDATE`) so two
     concurrent booking requests for the same staff member can't both pass
     the overlap check at once.
  4. Check for an overlapping, still-active appointment for that staff
     member. If one exists -> ROLLBACK, raise 409 SCHEDULE_CONFLICT.
  5. Otherwise INSERT the appointment (status='requested') + one
     `appointment_services` row per rendered service (packages are expanded
     here) and COMMIT.

Completion pipeline (status -> completed):
  - deduct product stock (blocked if insufficient)
  - generate commission records from specialist rates
  - append rows to the client's service history

Defense in depth: the DB-level EXCLUDE constraint (0001) makes an
overlapping booking impossible at the database level even if application
logic is bypassed.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    LEGAL_TRANSITIONS,
    Appointment,
    AppointmentService,
    AppointmentStatus,
    Client,
    Commission,
    Product,
    ProductUsage,
    Service,
    ServiceHistory,
    ServicePackage,
    ServicePackageItem,
    Specialist,
    Staff,
    WalkInCustomer,
)
from app.schemas.schemas import AppointmentCreate

ACTIVE_STATUSES = (
    AppointmentStatus.requested,
    AppointmentStatus.confirmed,
    AppointmentStatus.in_progress,
)


def _round_cents(value: Decimal) -> int:
    return int(value.to_integral_value(rounding="ROUND_HALF_UP"))


async def _get_owned_or_404(db: AsyncSession, model, obj_id: UUID, organization_id: UUID, label: str):
    stmt = select(model).where(
        model.id == obj_id,
        model.organization_id == organization_id,
        model.deleted_at.is_(None),
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
    return obj


async def resolve_staff_from_user(db: AsyncSession, organization_id: UUID, user_id: UUID) -> Staff | None:
    """The active staff record owned by a given platform user (if any)."""
    stmt = select(Staff).where(
        Staff.organization_id == organization_id,
        Staff.user_id == user_id,
        Staff.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalars().first()


async def _resolve_lines(
    db: AsyncSession,
    organization_id: UUID,
    payload: AppointmentCreate,
) -> tuple[list[dict], int, int]:
    """
    Resolves the requested services (legacy service_id, service_ids,
    services list, or package) into normalized lines + totals.

    Returns (lines, total_duration_minutes, total_cents). Package bookings
    return the package's fixed price as the total.
    """
    lines: list[dict] = []
    total_cents = 0
    total_duration = 0

    if payload.package_id is not None:
        package = await _get_owned_or_404(
            db, ServicePackage, payload.package_id, organization_id, "Package"
        )
        if not package.active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package is not active")
        items_stmt = (
            select(ServicePackage)
            .options(selectinload(ServicePackage.items).selectinload(ServicePackageItem.service))
            .where(ServicePackage.id == package.id)
        )
        package = (await db.execute(items_stmt)).scalar_one()
        for item in package.items:
            svc = item.service
            lines.append(
                {
                    "service_id": svc.id,
                    "service_name": svc.name,
                    "duration_minutes": svc.duration_minutes,
                    "price_cents": svc.price_cents,
                    "quantity": item.quantity,
                    "commission_rate_pct": None,
                }
            )
            total_duration += svc.duration_minutes * item.quantity
        total_cents = package.price_cents

    else:
        raw_lines: list[tuple[UUID, int, Decimal | None]] = []
        if payload.service_id is not None:
            raw_lines.append((payload.service_id, 1, None))
        if payload.service_ids:
            raw_lines.extend((sid, 1, None) for sid in payload.service_ids)
        if payload.services:
            raw_lines.extend(
                (line.service_id, line.quantity, line.commission_rate_pct) for line in payload.services
            )

        for service_id, quantity, commission_rate_pct in raw_lines:
            svc = await _get_owned_or_404(db, Service, service_id, organization_id, "Service")
            if not svc.active:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Service '{svc.name}' is not active")
            lines.append(
                {
                    "service_id": svc.id,
                    "service_name": svc.name,
                    "duration_minutes": svc.duration_minutes,
                    "price_cents": svc.price_cents,
                    "quantity": quantity,
                    "commission_rate_pct": commission_rate_pct,
                }
            )
            total_duration += svc.duration_minutes * quantity
            total_cents += svc.price_cents * quantity

    if not lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a service_id, service_ids, services, or package_id",
        )
    return lines, total_duration, total_cents


async def create_appointment(
    db: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    payload: AppointmentCreate,
) -> Appointment:
    # --- 1. Validate request: everything must belong to caller's org ---
    staff = await _get_owned_or_404(db, Staff, payload.staff_id, organization_id, "Staff member")
    if not staff.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Staff member is not active")

    if payload.client_id is not None:
        await _get_owned_or_404(db, Client, payload.client_id, organization_id, "Client")
    elif payload.walk_in_id is not None:
        await _get_owned_or_404(db, WalkInCustomer, payload.walk_in_id, organization_id, "Walk-in customer")

    lines, total_duration, total_cents = await _resolve_lines(db, organization_id, payload)
    end_time = payload.start_time + timedelta(minutes=total_duration)
    primary_service_id = lines[0]["service_id"]

    try:
        # --- 2/3. Lock this staff member's schedule for the duration of
        # the transaction so a concurrent request for the same staff_id
        # can't interleave between our check and our insert. ---
        await db.execute(select(Staff.id).where(Staff.id == staff.id).with_for_update())

        # --- 4. Overlap check among this staff member's active bookings ---
        overlap_stmt = select(Appointment.id).where(
            Appointment.organization_id == organization_id,
            Appointment.staff_id == staff.id,
            Appointment.deleted_at.is_(None),
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.start_time < end_time,
            Appointment.end_time > payload.start_time,
        ).with_for_update()
        conflict = (await db.execute(overlap_stmt)).first()

        if conflict is not None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SCHEDULE_CONFLICT",
                    "message": "This staff member already has an appointment in that time window.",
                },
            )

        # --- 5. Insert + commit ---
        appointment = Appointment(
            organization_id=organization_id,
            client_id=payload.client_id,
            walk_in_id=payload.walk_in_id,
            staff_id=staff.id,
            service_id=primary_service_id,
            package_id=payload.package_id,
            package_price_cents=payload.package_id and total_cents or None,
            total_cents=total_cents,
            discount_cents=payload.discount_cents,
            start_time=payload.start_time,
            end_time=end_time,
            status=AppointmentStatus.requested,
            notes=payload.notes,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(appointment)
        await db.flush()

        for line in lines:
            db.add(
                AppointmentService(
                    organization_id=organization_id,
                    appointment_id=appointment.id,
                    service_id=line["service_id"],
                    service_name=line["service_name"],
                    duration_minutes=line["duration_minutes"],
                    price_cents=line["price_cents"],
                    quantity=line["quantity"],
                    commission_rate_pct=line["commission_rate_pct"],
                    created_by=user_id,
                    updated_by=user_id,
                )
            )

        await db.commit()
        await db.refresh(appointment)
        await db.refresh(appointment, ["appointment_services"])
        return appointment

    except IntegrityError as exc:
        # Safety net: the DB-level EXCLUDE constraint caught a race that
        # somehow slipped past the application-level check above.
        await db.rollback()
        if "appointments_no_overlap" in str(exc.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SCHEDULE_CONFLICT",
                    "message": "This staff member already has an appointment in that time window.",
                },
            ) from exc
        raise


# ---------------------------------------------------------- completion -----


async def _deduct_stock(db: AsyncSession, appointment: Appointment) -> None:
    """Deduct product stock for a completing appointment. Blocks (400) if
    any product's stock would go negative."""
    usage_stmt = select(ProductUsage).where(
        ProductUsage.organization_id == appointment.organization_id,
        ProductUsage.appointment_id == appointment.id,
        ProductUsage.deleted_at.is_(None),
    )
    usage_rows = (await db.execute(usage_stmt)).scalars().all()
    if not usage_rows:
        return

    product_ids = [u.product_id for u in usage_rows if u.product_id is not None]
    products: dict[UUID, Product] = {}
    if product_ids:
        result = await db.execute(
            select(Product).where(
                Product.organization_id == appointment.organization_id,
                Product.id.in_(product_ids),
                Product.deleted_at.is_(None),
            )
        )
        products = {p.id: p for p in result.scalars()}

    shortages = []
    for usage in usage_rows:
        product = products.get(usage.product_id) if usage.product_id else None
        if product is None:
            continue  # product was hard-deleted; nothing to deduct
        remaining = product.stock_quantity - usage.quantity
        if remaining < 0:
            shortages.append(
                f"{product.name} (needs {usage.quantity}, has {product.stock_quantity})"
            )
    if shortages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INSUFFICIENT_STOCK",
                "message": "Cannot complete: insufficient stock. " + ", ".join(shortages),
                "items": shortages,
            },
        )

    for usage in usage_rows:
        product = products.get(usage.product_id) if usage.product_id else None
        if product is None:
            continue
        product.stock_quantity = product.stock_quantity - usage.quantity
        product.updated_by = appointment.updated_by


async def _generate_commissions(db: AsyncSession, appointment: Appointment, user_id: UUID) -> None:
    """One commission row per rendered service line, using the per-service
    override or the specialist's default rate. Staff without a specialist
    record earn no commission."""
    specialist_stmt = select(Specialist).where(
        Specialist.organization_id == appointment.organization_id,
        Specialist.staff_id == appointment.staff_id,
        Specialist.deleted_at.is_(None),
    )
    specialist = (await db.execute(specialist_stmt)).scalar_one_or_none()
    if specialist is None:
        return

    existing_stmt = select(Commission.id).where(
        Commission.appointment_id == appointment.id,
        Commission.organization_id == appointment.organization_id,
    )
    if (await db.execute(existing_stmt)).first() is not None:
        return  # already processed

    lines_stmt = select(AppointmentService).where(
        AppointmentService.appointment_id == appointment.id,
        AppointmentService.deleted_at.is_(None),
    )
    lines = (await db.execute(lines_stmt)).scalars().all()

    for line in lines:
        rate = line.commission_rate_pct if line.commission_rate_pct is not None else specialist.default_commission_rate_pct
        amount = _round_cents(
            Decimal(line.price_cents) * line.quantity * Decimal(rate) / Decimal(100)
        )
        db.add(
            Commission(
                organization_id=appointment.organization_id,
                appointment_id=appointment.id,
                specialist_id=specialist.id,
                service_name=line.service_name,
                rate_pct=rate,
                amount_cents=amount,
                created_by=user_id,
                updated_by=user_id,
            )
        )


async def _write_service_history(db: AsyncSession, appointment: Appointment, user_id: UUID) -> None:
    """Append completed services to the client's history log. Walk-in
    appointments have no client_id, so nothing is logged here (it appears
    in history only after the walk-in is converted to a client)."""
    if appointment.client_id is None:
        return

    specialist_stmt = select(Specialist).where(
        Specialist.organization_id == appointment.organization_id,
        Specialist.staff_id == appointment.staff_id,
        Specialist.deleted_at.is_(None),
    )
    specialist = (await db.execute(specialist_stmt)).scalar_one_or_none()

    lines_stmt = select(AppointmentService).where(
        AppointmentService.appointment_id == appointment.id,
        AppointmentService.deleted_at.is_(None),
    )
    lines = (await db.execute(lines_stmt)).scalars().all()

    for line in lines:
        db.add(
            ServiceHistory(
                organization_id=appointment.organization_id,
                client_id=appointment.client_id,
                appointment_id=appointment.id,
                service_id=line.service_id,
                specialist_id=specialist.id if specialist else None,
                service_name=line.service_name,
                price_cents=line.price_cents * line.quantity,
                completed_at=datetime.now(timezone.utc),
                created_by=user_id,
                updated_by=user_id,
            )
        )


async def transition_status(
    db: AsyncSession,
    appointment: Appointment,
    new_status: AppointmentStatus,
    user_id: UUID,
    cancellation_reason: str | None = None,
) -> Appointment:
    allowed = LEGAL_TRANSITIONS.get(appointment.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot transition appointment from '{appointment.status.value}' "
                f"to '{new_status.value}'. Allowed: "
                f"{sorted(s.value for s in allowed) or 'none (terminal state)'}"
            ),
        )
    if new_status == AppointmentStatus.cancelled and not cancellation_reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cancellation_reason is required when cancelling an appointment",
        )

    appointment.status = new_status
    appointment.updated_by = user_id
    if new_status == AppointmentStatus.cancelled:
        appointment.cancellation_reason = cancellation_reason

    if new_status == AppointmentStatus.completed:
        # Completion pipeline: stock -> commissions -> history. Raises 400
        # (and rolls back everything) if any product is understocked.
        await _deduct_stock(db, appointment)
        await _generate_commissions(db, appointment, user_id)
        await _write_service_history(db, appointment, user_id)

    await db.commit()
    await db.refresh(appointment)
    await db.refresh(appointment, ["appointment_services"])
    return appointment


# ------------------------------------------------------------ availability -


async def booked_ranges_for_staff(
    db: AsyncSession,
    organization_id: UUID,
    staff_id: UUID,
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """Occupied, still-active time ranges for a specialist on a date
    (used by GET /specialists/{id}/availability)."""
    stmt = select(Appointment).where(
        Appointment.organization_id == organization_id,
        Appointment.staff_id == staff_id,
        Appointment.deleted_at.is_(None),
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_time < date_to,
        Appointment.end_time > date_from,
    ).order_by(Appointment.start_time)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "start_time": a.start_time.isoformat(),
            "end_time": a.end_time.isoformat(),
            "status": a.status.value,
            "appointment_id": str(a.id),
        }
        for a in rows
    ]
