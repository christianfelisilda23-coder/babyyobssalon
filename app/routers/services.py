import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models import Service
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


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    service = Service(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        updated_by=principal.user_id,
        **payload.model_dump(),
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


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
    return result.scalars().all()


@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_service_or_404(db, service_id, principal.organization_id)


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: UUID,
    payload: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    service = await _get_service_or_404(db, service_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, field, value)
    service.updated_by = principal.user_id
    await db.commit()
    await db.refresh(service)
    return service


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
