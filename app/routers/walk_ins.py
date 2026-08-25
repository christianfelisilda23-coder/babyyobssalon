import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import (
    Appointment,
    AppointmentStatus,
    AppointmentService,
    Client,
    ServiceHistory,
    WalkInCustomer,
)
from app.schemas.schemas import ClientOut, WalkInConvertRequest, WalkInCreate, WalkInOut, WalkInUpdate

router = APIRouter(prefix="/walk-ins", tags=["walk-ins"])

STAFF_ROLES = ("admin", "front_desk")


async def _get_walkin_or_404(db: AsyncSession, walk_in_id: UUID, organization_id: UUID) -> WalkInCustomer:
    stmt = select(WalkInCustomer).where(
        WalkInCustomer.id == walk_in_id,
        WalkInCustomer.organization_id == organization_id,
        WalkInCustomer.deleted_at.is_(None),
    )
    walk_in = (await db.execute(stmt)).scalar_one_or_none()
    if walk_in is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Walk-in customer not found")
    return walk_in


@router.post("", response_model=WalkInOut, status_code=status.HTTP_201_CREATED)
async def create_walk_in(
    payload: WalkInCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    walk_in = WalkInCustomer(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        updated_by=principal.user_id,
        **payload.model_dump(),
    )
    db.add(walk_in)
    await db.commit()
    await db.refresh(walk_in)
    return walk_in


@router.get("", response_model=list[WalkInOut])
async def list_walk_ins(
    search: str | None = Query(default=None),
    converted: bool | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(WalkInCustomer).where(
        WalkInCustomer.organization_id == principal.organization_id,
        WalkInCustomer.deleted_at.is_(None),
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (WalkInCustomer.full_name.ilike(like)) | (WalkInCustomer.phone.ilike(like))
        )
    if converted is True:
        stmt = stmt.where(WalkInCustomer.converted_client_id.is_not(None))
    elif converted is False:
        stmt = stmt.where(WalkInCustomer.converted_client_id.is_(None))
    stmt = stmt.order_by(WalkInCustomer.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{walk_in_id}", response_model=WalkInOut)
async def get_walk_in(
    walk_in_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_walkin_or_404(db, walk_in_id, principal.organization_id)


@router.patch("/{walk_in_id}", response_model=WalkInOut)
async def update_walk_in(
    walk_in_id: UUID,
    payload: WalkInUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    walk_in = await _get_walkin_or_404(db, walk_in_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(walk_in, field, value)
    walk_in.updated_by = principal.user_id
    await db.commit()
    await db.refresh(walk_in)
    return walk_in


@router.delete("/{walk_in_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_walk_in(
    walk_in_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    walk_in = await _get_walkin_or_404(db, walk_in_id, principal.organization_id)
    walk_in.deleted_at = datetime.now(timezone.utc)
    walk_in.updated_by = principal.user_id
    await db.commit()


@router.post("/{walk_in_id}/convert-to-client", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def convert_to_client(
    walk_in_id: UUID,
    payload: WalkInConvertRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    """
    Registers the walk-in as a full client, links the two records, and
    backfills `service_history` for any completed appointments the walk-in
    already had (history is preserved across the conversion).
    """
    walk_in = await _get_walkin_or_404(db, walk_in_id, principal.organization_id)
    if walk_in.converted_client_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Walk-in already converted to a client")

    client = Client(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        full_name=payload.full_name or walk_in.full_name,
        phone=payload.phone if payload.phone is not None else walk_in.phone,
        email=payload.email if payload.email is not None else walk_in.email,
        notes=payload.notes if payload.notes is not None else walk_in.notes,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(client)
    await db.flush()

    walk_in.converted_client_id = client.id
    walk_in.updated_by = principal.user_id

    # Preserve service history: copy completed walk-in services to the new client.
    completed = (
        await db.execute(
            select(Appointment).where(
                Appointment.organization_id == principal.organization_id,
                Appointment.walk_in_id == walk_in.id,
                Appointment.status == AppointmentStatus.completed,
                Appointment.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    existing_history = (
        await db.execute(
            select(ServiceHistory.appointment_id, ServiceHistory.service_name).where(
                ServiceHistory.organization_id == principal.organization_id,
                ServiceHistory.appointment_id.in_([a.id for a in completed]) if completed else False,
            )
        )
    ).all() if completed else []
    seen = {(h.appointment_id, h.service_name) for h in existing_history}

    for appointment in completed:
        lines = (
            await db.execute(
                select(AppointmentService).where(
                    AppointmentService.appointment_id == appointment.id,
                    AppointmentService.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for line in lines:
            if (appointment.id, line.service_name) in seen:
                continue
            db.add(
                ServiceHistory(
                    organization_id=principal.organization_id,
                    client_id=client.id,
                    appointment_id=appointment.id,
                    service_id=line.service_id,
                    service_name=line.service_name,
                    price_cents=line.price_cents * line.quantity,
                    completed_at=appointment.updated_at,
                    created_by=principal.user_id,
                    updated_by=principal.user_id,
                )
            )

    await db.commit()
    await db.refresh(client)
    return client
