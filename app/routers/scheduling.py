import uuid
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models import Staff, StaffSchedule, StaffTimeOff
from app.routers.activity_logs import log_activity
from app.schemas.schemas import (
    ScheduleDayOut,
    ScheduleOut,
    ScheduleSetIn,
    TimeOffIn,
    TimeOffOut,
    TimeOffUpdate,
)

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


async def _get_staff_or_404(db: AsyncSession, staff_id: UUID, organization_id: UUID) -> Staff:
    stmt = select(Staff).where(
        Staff.id == staff_id, Staff.organization_id == organization_id, Staff.deleted_at.is_(None)
    )
    staff = (await db.execute(stmt)).scalar_one_or_none()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")
    return staff


# ---------------------------------------------------------------- Schedule ----
@router.get("/staff/{staff_id}/schedule", response_model=ScheduleOut)
async def get_schedule(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    staff = await _get_staff_or_404(db, staff_id, principal.organization_id)
    rows = (
        await db.execute(
            select(StaffSchedule)
            .where(
                StaffSchedule.organization_id == principal.organization_id,
                StaffSchedule.staff_id == staff_id,
            )
            .order_by(StaffSchedule.day_of_week)
        )
    ).scalars().all()
    return ScheduleOut(staff_id=staff.id, display_name=staff.display_name, days=rows)


@router.put("/staff/{staff_id}/schedule", response_model=ScheduleOut)
async def set_schedule(
    staff_id: UUID,
    payload: ScheduleSetIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    staff = await _get_staff_or_404(db, staff_id, principal.organization_id)
    await db.execute(
        delete(StaffSchedule).where(
            StaffSchedule.organization_id == principal.organization_id,
            StaffSchedule.staff_id == staff_id,
        )
    )
    for day in payload.days:
        db.add(
            StaffSchedule(
                id=uuid.uuid4(),
                organization_id=principal.organization_id,
                staff_id=staff_id,
                day_of_week=day.day_of_week,
                is_working=day.is_working,
                start_time=day.start_time,
                end_time=day.end_time,
                lunch_start=day.lunch_start,
                lunch_end=day.lunch_end,
            )
        )
    await db.commit()
    await log_activity(
        db, principal.organization_id,
        action="schedule.updated", entity_type="staff",
        description=f"Updated weekly schedule for '{staff.display_name}'.",
        actor_id=principal.user_id, actor_name=principal.email,
        entity_id=staff_id,
    )
    await db.commit()
    rows = (
        await db.execute(
            select(StaffSchedule)
            .where(
                StaffSchedule.organization_id == principal.organization_id,
                StaffSchedule.staff_id == staff_id,
            )
            .order_by(StaffSchedule.day_of_week)
        )
    ).scalars().all()
    return ScheduleOut(staff_id=staff.id, display_name=staff.display_name, days=rows)


# ---------------------------------------------------------------- Time off ----
@router.get("/staff/{staff_id}/timeoffs", response_model=list[TimeOffOut])
async def list_time_offs(
    staff_id: UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await _get_staff_or_404(db, staff_id, principal.organization_id)
    stmt = select(StaffTimeOff).where(
        StaffTimeOff.organization_id == principal.organization_id,
        StaffTimeOff.staff_id == staff_id,
    )
    if from_date:
        stmt = stmt.where(StaffTimeOff.date >= from_date)
    if to_date:
        stmt = stmt.where(StaffTimeOff.date <= to_date)
    result = await db.execute(stmt.order_by(StaffTimeOff.date))
    return result.scalars().all()


@router.post("/staff/{staff_id}/timeoffs", response_model=TimeOffOut, status_code=status.HTTP_201_CREATED)
async def create_time_off(
    staff_id: UUID,
    payload: TimeOffIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    staff = await _get_staff_or_404(db, staff_id, principal.organization_id)
    row = StaffTimeOff(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        staff_id=staff_id,
        **payload.model_dump(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await log_activity(
        db, principal.organization_id,
        action="timeoff.created", entity_type="staff",
        description=f"Added {payload.type.replace('_', ' ')} for '{staff.display_name}' on {payload.date}.",
        actor_id=principal.user_id, actor_name=principal.email,
        entity_id=staff_id,
    )
    await db.commit()
    return row


@router.patch("/timeoffs/{timeoff_id}", response_model=TimeOffOut)
async def update_time_off(
    timeoff_id: UUID,
    payload: TimeOffUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    row = (
        await db.execute(
            select(StaffTimeOff).where(
                StaffTimeOff.id == timeoff_id,
                StaffTimeOff.organization_id == principal.organization_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time off entry not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    await log_activity(
        db, principal.organization_id,
        action="timeoff.updated", entity_type="staff",
        description=f"Updated a time off entry for a staff member.",
        actor_id=principal.user_id, actor_name=principal.email,
        entity_id=row.staff_id,
    )
    await db.commit()
    return row


@router.delete("/timeoffs/{timeoff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_off(
    timeoff_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    row = (
        await db.execute(
            select(StaffTimeOff).where(
                StaffTimeOff.id == timeoff_id,
                StaffTimeOff.organization_id == principal.organization_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time off entry not found")
    await db.execute(
        delete(StaffTimeOff).where(StaffTimeOff.id == timeoff_id)
    )
    await db.commit()
    await log_activity(
        db, principal.organization_id,
        action="timeoff.deleted", entity_type="staff",
        description=f"Removed a time off entry.",
        actor_id=principal.user_id, actor_name=principal.email,
        entity_id=row.staff_id,
    )
    await db.commit()
