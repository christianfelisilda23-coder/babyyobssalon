import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models import Service, Staff, StaffService
from app.schemas.schemas import StaffCreate, StaffOut, StaffServiceOut, StaffUpdate

router = APIRouter(prefix="/staff", tags=["staff"])


async def _get_staff_or_404(db: AsyncSession, staff_id: UUID, organization_id: UUID) -> Staff:
    stmt = select(Staff).where(
        Staff.id == staff_id, Staff.organization_id == organization_id, Staff.deleted_at.is_(None)
    )
    staff = (await db.execute(stmt)).scalar_one_or_none()
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff member not found")
    return staff


@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    payload: StaffCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    existing = (
        await db.execute(
            select(Staff).where(
                Staff.organization_id == principal.organization_id, Staff.user_id == payload.user_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This user is already staff in this organization")

    staff = Staff(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        updated_by=principal.user_id,
        **payload.model_dump(),
    )
    db.add(staff)
    await db.commit()
    await db.refresh(staff)
    return staff


@router.get("", response_model=list[StaffOut])
async def list_staff(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(Staff).where(Staff.organization_id == principal.organization_id, Staff.deleted_at.is_(None))
    if active_only:
        stmt = stmt.where(Staff.active.is_(True))
    result = await db.execute(stmt.order_by(Staff.display_name))
    return result.scalars().all()


@router.get("/{staff_id}", response_model=StaffOut)
async def get_staff(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_staff_or_404(db, staff_id, principal.organization_id)


@router.patch("/{staff_id}", response_model=StaffOut)
async def update_staff(
    staff_id: UUID,
    payload: StaffUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    staff = await _get_staff_or_404(db, staff_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(staff, field, value)
    staff.updated_by = principal.user_id
    await db.commit()
    await db.refresh(staff)
    return staff


@router.delete("/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    staff = await _get_staff_or_404(db, staff_id, principal.organization_id)
    staff.deleted_at = datetime.now(timezone.utc)
    staff.updated_by = principal.user_id
    await db.commit()


# ---------------------------------------------- Staff <-> Service links ---
@router.post("/{staff_id}/services/{service_id}", response_model=StaffServiceOut, status_code=status.HTTP_201_CREATED)
async def qualify_staff_for_service(
    staff_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await _get_staff_or_404(db, staff_id, principal.organization_id)
    service = (
        await db.execute(
            select(Service).where(
                Service.id == service_id,
                Service.organization_id == principal.organization_id,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    existing = (
        await db.execute(
            select(StaffService).where(StaffService.staff_id == staff_id, StaffService.service_id == service_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    link = StaffService(staff_id=staff_id, service_id=service_id, organization_id=principal.organization_id)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


@router.delete("/{staff_id}/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_staff_service_qualification(
    staff_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    link = (
        await db.execute(
            select(StaffService).where(
                StaffService.staff_id == staff_id,
                StaffService.service_id == service_id,
                StaffService.organization_id == principal.organization_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Qualification link not found")
    await db.delete(link)
    await db.commit()


@router.get("/{staff_id}/services", response_model=list[StaffServiceOut])
async def list_staff_qualifications(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await _get_staff_or_404(db, staff_id, principal.organization_id)
    result = await db.execute(
        select(StaffService).where(
            StaffService.staff_id == staff_id, StaffService.organization_id == principal.organization_id
        )
    )
    return result.scalars().all()
