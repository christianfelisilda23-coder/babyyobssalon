from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import (
    Appointment,
    AppointmentService,
    Client,
    Commission,
    Payment,
    PaymentStatus,
    Product,
    ProductUsage,
    ServicePackage,
    Specialist,
    Staff,
)
from app.services import appointments as appointment_service

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_ROLES = ("admin", "front_desk")


async def _resolve_specialist_id(
    db: AsyncSession, principal: Principal, specialist_id: UUID | None
) -> UUID | None:
    """Staff ID used to scope performance/commission reports. Admins + front
    desk can pick any specialist; specialists are locked to their own record."""
    if specialist_id is not None and principal.role not in REPORT_ROLES:
        raise PermissionError("Specialists can only view their own report")
    if specialist_id is not None:
        return specialist_id
    if principal.role == "specialist":
        staff = await appointment_service.resolve_staff_from_user(
            db, principal.organization_id, principal.user_id
        )
        if staff is None:
            return None
        return staff.id
    return None


@router.get("/dashboard")
async def dashboard(
    date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*REPORT_ROLES)),
):
    """Home-screen KPIs for a single day (defaults to today, UTC)."""
    day = date or datetime.now(timezone.utc)
    day_start = datetime.combine(day.date(), time.min, tzinfo=timezone.utc)
    day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

    org = principal.organization_id

    # Appointment counts by status for the day.
    status_counts = (
        await db.execute(
            select(Appointment.status, func.count(Appointment.id))
            .where(
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.start_time >= day_start,
                Appointment.start_time <= day_end,
            )
            .group_by(Appointment.status)
        )
    ).all()

    # Revenue recognized today (paid payments whose appointment started today).
    revenue = (
        await db.execute(
            select(
                func.coalesce(func.sum(Payment.amount_cents), 0),
                func.coalesce(func.sum(Payment.tip_cents), 0),
                func.count(Payment.id),
            )
            .join(Appointment, Appointment.id == Payment.appointment_id)
            .where(
                Payment.organization_id == org,
                Payment.status == PaymentStatus.paid,
                Payment.deleted_at.is_(None),
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.start_time >= day_start,
                Appointment.start_time <= day_end,
            )
        )
    ).one()

    # Upcoming (scheduled, not yet started).
    now = datetime.now(timezone.utc)
    upcoming = (
        await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.status.in_(["requested", "confirmed"]),
                Appointment.start_time >= now,
            )
        )
    ).scalar_one()

    # New registered clients this week (from Monday, UTC).
    week_start = now - timedelta(days=_days_since_monday(now))
    new_clients = (
        await db.execute(
            select(func.count(Client.id)).where(
                Client.organization_id == org,
                Client.deleted_at.is_(None),
                Client.created_at >= week_start,
            )
        )
    ).scalar_one()

    low_stock = (
        await db.execute(
            select(func.count(Product.id)).where(
                Product.organization_id == org,
                Product.deleted_at.is_(None),
                Product.active.is_(True),
                Product.stock_quantity <= Product.reorder_level,
            )
        )
    ).scalar_one()

    return {
        "date": day.date().isoformat(),
        "appointments": {status.value: count for status, count in status_counts},
        "appointments_total": sum(count for _, count in status_counts),
        "revenue_cents": int(revenue[0]),
        "tips_cents": int(revenue[1]),
        "transactions": int(revenue[2]),
        "upcoming_appointments": int(upcoming),
        "new_clients_this_week": int(new_clients),
        "low_stock_products": int(low_stock),
    }


@router.get("/revenue")
async def revenue_report(
    date_from: datetime,
    date_to: datetime,
    group_by: str = Query(default="day", pattern="^(day|week|month|service|staff)$"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*REPORT_ROLES)),
):
    """
    Recognized revenue (paid payments) between two timestamps.
    `group_by` buckets by calendar period, service line, or staff member.
    """
    org = principal.organization_id
    if group_by in ("day", "week", "month"):
        bucket = func.date_trunc(group_by, Payment.created_at)
        stmt = (
            select(
                bucket.label("bucket"),
                func.coalesce(func.sum(Payment.amount_cents), 0),
                func.coalesce(func.sum(Payment.tip_cents), 0),
                func.count(Payment.id),
            )
            .join(Appointment, Appointment.id == Payment.appointment_id)
            .where(
                Payment.organization_id == org,
                Payment.status == PaymentStatus.paid,
                Payment.deleted_at.is_(None),
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.start_time >= date_from,
                Appointment.start_time <= date_to,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "group_by": group_by,
            "rows": [
                {
                    "bucket": bucket.isoformat(),
                    "revenue_cents": int(revenue),
                    "tips_cents": int(tips),
                    "transactions": int(transactions),
                }
                for bucket, revenue, tips, transactions in rows
            ],
        }

    if group_by == "service":
        stmt = (
            select(
                AppointmentService.service_name,
                func.coalesce(func.sum(AppointmentService.price_cents * AppointmentService.quantity), 0),
                func.count(func.distinct(AppointmentService.appointment_id)),
                func.sum(AppointmentService.quantity),
            )
            .join(Appointment, Appointment.id == AppointmentService.appointment_id)
            .where(
                AppointmentService.organization_id == org,
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.status == "completed",
                Appointment.start_time >= date_from,
                Appointment.start_time <= date_to,
            )
            .group_by(AppointmentService.service_name)
            .order_by(func.sum(AppointmentService.price_cents * AppointmentService.quantity).desc())
        )
        rows = (await db.execute(stmt)).all()
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "group_by": group_by,
            "rows": [
                {
                    "service_name": service_name,
                    "revenue_cents": int(revenue),
                    "appointments": int(appointments),
                    "units": int(units),
                }
                for service_name, revenue, appointments, units in rows
            ],
        }

    # group_by == "staff"
    stmt = (
        select(
            Appointment.staff_id,
            Staff.display_name,
            func.coalesce(func.sum(AppointmentService.price_cents * AppointmentService.quantity), 0),
            func.count(func.distinct(Appointment.id)),
        )
        .join(AppointmentService, AppointmentService.appointment_id == Appointment.id)
        .join(Staff, Staff.id == Appointment.staff_id)
        .where(
            AppointmentService.organization_id == org,
            Appointment.organization_id == org,
            Appointment.deleted_at.is_(None),
            Appointment.status == "completed",
            Appointment.start_time >= date_from,
            Appointment.start_time <= date_to,
        )
        .group_by(Appointment.staff_id, Staff.display_name)
        .order_by(func.sum(AppointmentService.price_cents * AppointmentService.quantity).desc())
    )
    rows = (await db.execute(stmt)).all()
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "group_by": group_by,
        "rows": [
            {
                "staff_id": staff_id,
                "staff_name": staff_name,
                "revenue_cents": int(revenue),
                "appointments": int(appointments),
            }
            for staff_id, staff_name, revenue, appointments in rows
        ],
    }


@router.get("/commissions")
async def commissions_report(
    date_from: datetime,
    date_to: datetime,
    specialist_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Earned commissions per specialist for completed appointments in range."""
    if principal.role not in REPORT_ROLES and principal.role != "specialist":
        raise PermissionError("Requires one of roles: admin, front_desk, specialist")

    scope_staff_id = await _resolve_specialist_id(db, principal, specialist_id)
    org = principal.organization_id

    stmt = (
        select(
            Commission.specialist_id,
            Specialist.default_commission_rate_pct,
            func.count(func.distinct(Commission.appointment_id)),
            func.count(Commission.id),
            func.coalesce(func.sum(Commission.amount_cents), 0),
        )
        .outerjoin(Specialist, Specialist.id == Commission.specialist_id)
        .where(
            Commission.organization_id == org,
            Commission.created_at >= date_from,
            Commission.created_at <= date_to,
        )
        .group_by(Commission.specialist_id, Specialist.default_commission_rate_pct)
        .order_by(func.sum(Commission.amount_cents).desc())
    )
    if scope_staff_id is not None:
        stmt = stmt.where(Commission.specialist_id == scope_staff_id)
    rows = (await db.execute(stmt)).all()

    specialist_names = {}
    if rows:
        specialist_ids = [r[0] for r in rows if r[0] is not None]
        if specialist_ids:
            names = (
                await db.execute(
                    select(Staff.id, Staff.display_name).where(Staff.id.in_(specialist_ids))
                )
            ).all()
            specialist_names = {staff_id: display_name for staff_id, display_name in names}

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rows": [
            {
                "specialist_id": specialist_id,
                "specialist_name": specialist_names.get(specialist_id),
                "default_rate_pct": default_rate,
                "appointments": int(appointments),
                "commission_lines": int(lines),
                "amount_cents": int(amount),
            }
            for specialist_id, default_rate, appointments, lines, amount in rows
        ],
        "total_cents": int(sum(r[4] or 0 for r in rows)),
    }


@router.get("/performance")
async def performance_report(
    date_from: datetime,
    date_to: datetime,
    staff_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Per-staff workload + revenue: bookings, completed, no-shows, and
    service revenue for completed appointments."""
    if principal.role not in REPORT_ROLES and principal.role != "specialist":
        raise PermissionError("Requires one of roles: admin, front_desk, specialist")

    scope_staff_id = await _resolve_specialist_id(db, principal, staff_id)
    org = principal.organization_id

    base = (
        select(Appointment.staff_id, Staff.display_name)
        .join(Staff, Staff.id == Appointment.staff_id)
        .where(
            Appointment.organization_id == org,
            Appointment.deleted_at.is_(None),
            Appointment.start_time >= date_from,
            Appointment.start_time <= date_to,
        )
        .group_by(Appointment.staff_id, Staff.display_name)
    )
    if scope_staff_id is not None:
        base = base.where(Appointment.staff_id == scope_staff_id)

    bookings = (
        await db.execute(
            select(
                Appointment.staff_id,
                func.count(Appointment.id),
                func.count(case((Appointment.status == "completed", 1))),
                func.count(case((Appointment.status == "no_show", 1))),
                func.count(case((Appointment.status == "cancelled", 1))),
            )
            .where(
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.start_time >= date_from,
                Appointment.start_time <= date_to,
            )
            .group_by(Appointment.staff_id)
        )
    ).all()

    revenue = (
        await db.execute(
            select(
                Appointment.staff_id,
                func.coalesce(func.sum(AppointmentService.price_cents * AppointmentService.quantity), 0),
            )
            .join(Appointment, Appointment.id == AppointmentService.appointment_id)
            .where(
                AppointmentService.organization_id == org,
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.status == "completed",
                Appointment.start_time >= date_from,
                Appointment.start_time <= date_to,
            )
            .group_by(Appointment.staff_id)
        )
    ).all()

    stats: dict[UUID, dict] = {}
    for staff_id, name in (await db.execute(base)).all():
        stats.setdefault(staff_id, {"staff_id": staff_id, "staff_name": name})
    for staff_id, total, completed, no_show, cancelled in bookings:
        row = stats.setdefault(staff_id, {"staff_id": staff_id, "staff_name": None})
        row.update(
            {
                "bookings": int(total),
                "completed": int(completed or 0),
                "no_shows": int(no_show or 0),
                "cancelled": int(cancelled or 0),
            }
        )
    for staff_id, rev in revenue:
        stats.setdefault(staff_id, {"staff_id": staff_id, "staff_name": None}).update(
            {"service_revenue_cents": int(rev)}
        )

    for row in stats.values():
        row.setdefault("bookings", 0)
        row.setdefault("completed", 0)
        row.setdefault("no_shows", 0)
        row.setdefault("cancelled", 0)
        row.setdefault("service_revenue_cents", 0)

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rows": sorted(stats.values(), key=lambda r: r["service_revenue_cents"], reverse=True),
    }


@router.get("/product-usage")
async def product_usage_report(
    date_from: datetime,
    date_to: datetime,
    product_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*REPORT_ROLES)),
):
    """Consumed product quantities + cost by product over the range."""
    org = principal.organization_id
    stmt = (
        select(
            ProductUsage.product_id,
            ProductUsage.product_name,
            func.sum(ProductUsage.quantity),
            func.coalesce(func.sum(ProductUsage.quantity * ProductUsage.unit_cost_cents), 0),
            func.count(func.distinct(ProductUsage.appointment_id)),
        )
        .join(Appointment, Appointment.id == ProductUsage.appointment_id)
        .where(
            ProductUsage.organization_id == org,
            ProductUsage.deleted_at.is_(None),
            Appointment.organization_id == org,
            Appointment.deleted_at.is_(None),
            Appointment.start_time >= date_from,
            Appointment.start_time <= date_to,
        )
        .group_by(ProductUsage.product_id, ProductUsage.product_name)
        .order_by(func.sum(ProductUsage.quantity).desc())
    )
    if product_id is not None:
        stmt = stmt.where(ProductUsage.product_id == product_id)
    rows = (await db.execute(stmt)).all()
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rows": [
            {
                "product_id": product_id,
                "product_name": product_name,
                "quantity": float(quantity or 0),
                "cost_cents": int(cost),
                "appointments": int(appointments),
            }
            for product_id, product_name, quantity, cost, appointments in rows
        ],
        "total_cost_cents": int(sum(r[3] or 0 for r in rows)),
    }


@router.get("/customers")
async def customers_report(
    date_from: datetime,
    date_to: datetime,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*REPORT_ROLES)),
):
    """New client sign-ups plus the top clients by visit count in the range."""
    org = principal.organization_id

    new_clients = (
        await db.execute(
            select(
                Client.id,
                Client.full_name,
                Client.email,
                Client.phone,
                Client.created_at,
            )
            .where(
                Client.organization_id == org,
                Client.deleted_at.is_(None),
                Client.created_at >= date_from,
                Client.created_at <= date_to,
            )
            .order_by(Client.created_at.desc())
        )
    ).all()

    top = (
        await db.execute(
            select(
                Client.id,
                Client.full_name,
                func.count(Appointment.id),
                func.count(case((Appointment.status == "completed", 1))),
            )
            .join(Appointment, Appointment.client_id == Client.id)
            .where(
                Client.organization_id == org,
                Client.deleted_at.is_(None),
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.start_time >= date_from,
                Appointment.start_time <= date_to,
            )
            .group_by(Client.id, Client.full_name)
            .order_by(func.count(Appointment.id).desc())
            .limit(20)
        )
    ).all()

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "new_clients_count": len(new_clients),
        "new_clients": [
            {"id": client_id, "full_name": full_name, "email": email, "phone": phone, "created_at": created_at}
            for client_id, full_name, email, phone, created_at in new_clients
        ],
        "top_clients": [
            {
                "client_id": client_id,
                "client_name": full_name,
                "visits": int(visits),
                "completed": int(completed or 0),
            }
            for client_id, full_name, visits, completed in top
        ],
    }


@router.get("/packages")
async def packages_report(
    date_from: datetime,
    date_to: datetime,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*REPORT_ROLES)),
):
    """Package usage: how often each package was booked and its revenue."""
    org = principal.organization_id
    rows = (
        await db.execute(
            select(
                ServicePackage.id,
                ServicePackage.name,
                func.count(Appointment.id),
                func.coalesce(func.sum(Appointment.package_price_cents), 0),
            )
            .join(Appointment, Appointment.package_id == ServicePackage.id)
            .where(
                ServicePackage.organization_id == org,
                ServicePackage.deleted_at.is_(None),
                Appointment.organization_id == org,
                Appointment.deleted_at.is_(None),
                Appointment.package_id.is_not(None),
                Appointment.start_time >= date_from,
                Appointment.start_time <= date_to,
            )
            .group_by(ServicePackage.id, ServicePackage.name)
            .order_by(func.count(Appointment.id).desc())
        )
    ).all()
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rows": [
            {
                "package_id": package_id,
                "package_name": package_name,
                "bookings": int(bookings),
                "revenue_cents": int(revenue),
            }
            for package_id, package_name, bookings, revenue in rows
        ],
    }


def _days_since_monday(dt: datetime) -> int:
    # Python weekday(): Monday == 0.
    return dt.weekday()
