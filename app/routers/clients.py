import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models import Client, ServiceHistory
from app.schemas.schemas import ClientCreate, ClientOut, ClientUpdate, ServiceHistoryOut

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    client = Client(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        updated_by=principal.user_id,
        **payload.model_dump(),
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


@router.get("", response_model=list[ClientOut])
async def list_clients(
    search: str | None = Query(default=None, description="Filter by name/phone/email substring"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(Client).where(
        Client.organization_id == principal.organization_id,
        Client.deleted_at.is_(None),
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (Client.full_name.ilike(like)) | (Client.phone.ilike(like)) | (Client.email.ilike(like))
        )
    stmt = stmt.order_by(Client.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return result.scalars().all()


async def _get_client_or_404(db: AsyncSession, client_id: UUID, organization_id: UUID) -> Client:
    stmt = select(Client).where(
        Client.id == client_id,
        Client.organization_id == organization_id,
        Client.deleted_at.is_(None),
    )
    client = (await db.execute(stmt)).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_client_or_404(db, client_id, principal.organization_id)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: UUID,
    payload: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    client = await _get_client_or_404(db, client_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    client.updated_by = principal.user_id
    await db.commit()
    await db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    client = await _get_client_or_404(db, client_id, principal.organization_id)
    client.deleted_at = datetime.now(timezone.utc)
    client.updated_by = principal.user_id
    await db.commit()


@router.get("/{client_id}/history", response_model=list[ServiceHistoryOut])
async def client_service_history(
    client_id: UUID,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Client's service history, most recent first."""
    await _get_client_or_404(db, client_id, principal.organization_id)
    result = await db.execute(
        select(ServiceHistory)
        .where(
            ServiceHistory.organization_id == principal.organization_id,
            ServiceHistory.client_id == client_id,
            ServiceHistory.deleted_at.is_(None),
        )
        .order_by(ServiceHistory.completed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()
