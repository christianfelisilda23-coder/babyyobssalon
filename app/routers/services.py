import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models import Service, Staff, StaffService
from app.routers.activity_logs import log_activity
from app.schemas.schemas import ServiceCreate, ServiceOut, ServiceUpdate

router = APIRouter(prefix="/services", tags=["services"])


async def _get_service_or_404(db: AsyncSession, service_id: UUID, organization_id: UUID) -> Service:
    stmt = select(Service).where(
        Service.id == service_id, Service.organization_id == organization_id, Service.deleted_at.is_(None)
    )
    service = (await db.execute(stmt)).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return service


async def _replace_staff_assignments(db, organization_id, service_id, staff_ids):
    """Reset the staff_services junction for a service to the given staff ids."""
    await db.execute(
        StaffService.__table__.delete().where(
            StaffService.organization_id == organization_id, StaffService.service_id == service_id
        )
    )
    for staff_id in staff_ids or []:
        db.add(
            StaffService(
                staff_id=staff_id,
                service_id=service_id,
                organization_id=organization_id,
            )
        )


async def _assigned_staff(db, organization_id, service_id):
    rows = (
        await db.execute(
            select(Staff.id, Staff.display_name)
            .join(StaffService, Staff.id == StaffService.staff_id)
            .where(
                StaffService.organization_id == organization_id,
                StaffService.service_id == service_id,
            )
        )
    ).all()
    return [str(r[0]) for r in rows], [r[1] for r in rows]


async def _hydrate(db, org_id, service):
    ids, names = await _assigned_staff(db, org_id, service.id)
    return {
        "id": service.id,
        "organization_id": service.organization_id,
        "name": service.name,
        "category": service.category,
        "duration_minutes": service.duration_minutes,
        "price_cents": service.price_cents,
        "active": service.active,
        "created_at": service.created_at,
        "updated_at": service.updated_at,
        "assigned_staff_ids": ids,
        "assigned_staff_names": names,
    }


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    data = payload.model_dump(exclude={"assigned_staff_ids"})
    service = Service(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        updated_by=principal.user_id,
        **data,
    )
    db.add(service)
    await db.flush()
    await _replace_staff_assignments(db, principal.organization_id, service.id, payload.assigned_staff_ids)
    await db.commit()
    await log_activity(
        db, principal.organization_id,
        action="service.created", entity_type="service",
        description=f"Added service '{service.name}'.",
        actor_id=principal.user_id, actor_name=principal.email,
        entity_id=service.id,
    )
    await db.commit()
    return await _hydrate(db, principal.organization_id, service)


@router.get("", response_model=list[ServiceOut])
async def list_services(
    active_only: bool = True,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(Service).where(
        Service.organization_id == principal.organization_id, Service.deleted_at.is_(None)
    )
    if active_only:
        stmt = stmt.where(Service.active.is_(True))
    if category:
        stmt = stmt.where(Service.category == category)
    result = await db.execute(stmt.order_by(Service.name))
    services = result.scalars().all()
    return [await _hydrate(db, principal.organization_id, s) for s in services]


@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    service = await _get_service_or_404(db, service_id, principal.organization_id)
    return await _hydrate(db, principal.organization_id, service)


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: UUID,
    payload: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    service = await _get_service_or_404(db, service_id, principal.organization_id)
    data = payload.model_dump(exclude_unset=True, exclude={"assigned_staff_ids"})
    for field, value in data.items():
        setattr(service, field, value)
    service.updated_by = principal.user_id
    if payload.assigned_staff_ids is not None:
        await _replace_staff_assignments(db, principal.organization_id, service_id, payload.assigned_staff_ids)
    await db.commit()
    await log_activity(
        db, principal.organization_id,
        action="service.updated", entity_type="service",
        description=f"Updated service '{service.name}'.",
        actor_id=principal.user_id, actor_name=principal.email,
        entity_id=service.id,
    )
    await db.commit()
    return await _hydrate(db, principal.organization_id, service)


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    service = await _get_service_or_404(db, service_id, principal.organization_id)
    service.deleted_at = datetime.now(timezone.utc)
    service.updated_by = principal.user_id
    await db.commit()
