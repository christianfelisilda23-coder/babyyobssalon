import uuid
from datetime import datetime, time, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import Specialist, SpecialistSpecialty, Staff, ServiceCategory
from app.schemas.schemas import SpecialtyLink, SpecialistCreate, SpecialistOut, SpecialistUpdate
from app.services import appointments as appointment_service

router = APIRouter(prefix="/specialists", tags=["specialists"])

ADMIN_ONLY = ("admin",)


async def _get_specialist_or_404(db: AsyncSession, specialist_id: UUID, organization_id: UUID) -> Specialist:
    stmt = select(Specialist).where(
        Specialist.id == specialist_id,
        Specialist.organization_id == organization_id,
        Specialist.deleted_at.is_(None),
    )
    specialist = (await db.execute(stmt)).scalar_one_or_none()
    if specialist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specialist not found")
    return specialist


async def _out(db: AsyncSession, specialist: Specialist) -> dict:
    staff = (
        await db.execute(
            select(Staff).where(
                Staff.id == specialist.staff_id,
                Staff.organization_id == specialist.organization_id,
                Staff.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    return {
        "id": specialist.id,
        "organization_id": specialist.organization_id,
        "staff_id": specialist.staff_id,
        "default_commission_rate_pct": specialist.default_commission_rate_pct,
        "staff_display_name": staff.display_name if staff else None,
        "staff_title": staff.title if staff else None,
        "staff_active": staff.active if staff else None,
        "created_at": specialist.created_at,
        "updated_at": specialist.updated_at,
    }


@router.post("", response_model=SpecialistOut, status_code=status.HTTP_201_CREATED)
async def create_specialist(
    payload: SpecialistCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    staff = (
        await db.execute(
            select(Staff).where(
                Staff.id == payload.staff_id,
                Staff.organization_id == principal.organization_id,
                Staff.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")

    existing = (
        await db.execute(
            select(Specialist).where(
                Specialist.organization_id == principal.organization_id,
                Specialist.staff_id == payload.staff_id,
                Specialist.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This staff member is already a specialist")

    specialist = Specialist(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        staff_id=staff.id,
        default_commission_rate_pct=payload.default_commission_rate_pct,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(specialist)
    await db.commit()
    await db.refresh(specialist)
    return await _out(db, specialist)


@router.get("", response_model=list[SpecialistOut])
async def list_specialists(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    result = await db.execute(
        select(Specialist)
        .join(Staff, Staff.id == Specialist.staff_id)
        .where(
            Specialist.organization_id == principal.organization_id,
            Specialist.deleted_at.is_(None),
            Staff.deleted_at.is_(None),
        )
        .order_by(Staff.display_name)
    )
    specialists = result.scalars().all()
    return [await _out(db, s) for s in specialists]


@router.get("/{specialist_id}", response_model=SpecialistOut)
async def get_specialist(
    specialist_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    specialist = await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    return await _out(db, specialist)


@router.patch("/{specialist_id}", response_model=SpecialistOut)
async def update_specialist(
    specialist_id: UUID,
    payload: SpecialistUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    specialist = await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(specialist, field, value)
    specialist.updated_by = principal.user_id
    await db.commit()
    await db.refresh(specialist)
    return await _out(db, specialist)


@router.delete("/{specialist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_specialist(
    specialist_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    specialist = await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    specialist.deleted_at = datetime.now(timezone.utc)
    specialist.updated_by = principal.user_id
    await db.commit()


# ---------------------------------------------- specialties (category links) ---


@router.post("/{specialist_id}/specialties", status_code=status.HTTP_201_CREATED)
async def add_specialty(
    specialist_id: UUID,
    payload: SpecialtyLink,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    category = (
        await db.execute(
            select(ServiceCategory).where(
                ServiceCategory.id == payload.category_id,
                ServiceCategory.organization_id == principal.organization_id,
                ServiceCategory.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    existing = (
        await db.execute(
            select(SpecialistSpecialty).where(
                SpecialistSpecialty.specialist_id == specialist_id,
                SpecialistSpecialty.category_id == payload.category_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            SpecialistSpecialty(
                specialist_id=specialist_id,
                category_id=payload.category_id,
                organization_id=principal.organization_id,
            )
        )
        await db.commit()
    return {"specialist_id": specialist_id, "category_id": payload.category_id}


@router.delete("/{specialist_id}/specialties/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_specialty(
    specialist_id: UUID,
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    link = (
        await db.execute(
            select(SpecialistSpecialty).where(
                SpecialistSpecialty.specialist_id == specialist_id,
                SpecialistSpecialty.category_id == category_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Specialty link not found")
    await db.delete(link)
    await db.commit()


@router.get("/{specialist_id}/specialties")
async def list_specialties(
    specialist_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    result = await db.execute(
        select(ServiceCategory)
        .join(SpecialistSpecialty, SpecialistSpecialty.category_id == ServiceCategory.id)
        .where(
            SpecialistSpecialty.specialist_id == specialist_id,
            ServiceCategory.organization_id == principal.organization_id,
        )
        .order_by(ServiceCategory.name)
    )
    categories = result.scalars().all()
    return [
        {"id": c.id, "organization_id": c.organization_id, "name": c.name}
        for c in categories
    ]


@router.get("/{specialist_id}/availability")
async def specialist_availability(
    specialist_id: UUID,
    date: str | None = Query(default=None, description="ISO date (YYYY-MM-DD)"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Occupied time ranges for a specialist. Free slots are everything not
    covered by these ranges within working hours."""
    specialist = await _get_specialist_or_404(db, specialist_id, principal.organization_id)
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date must be YYYY-MM-DD") from exc
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
    elif date_from and date_to:
        start, end = date_from, date_to
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either `date` or `date_from` + `date_to`",
        )

    ranges = await appointment_service.booked_ranges_for_staff(
        db, principal.organization_id, specialist.staff_id, start, end
    )
    return {"specialist_id": specialist.id, "staff_id": specialist.staff_id, "booked_ranges": ranges}
