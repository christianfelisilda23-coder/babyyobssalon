import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal
from app.models.notifications import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID | None
    type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationPatch(BaseModel):
    is_read: bool


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(Notification).where(
        Notification.organization_id == principal.organization_id,
        Notification.user_id == principal.user_id,
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/count")
async def notification_count(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.organization_id == principal.organization_id,
            Notification.user_id == principal.user_id,
            Notification.is_read == False,
        )
    )
    return {"unread": result.scalar() or 0}


@router.patch("/{notification_id}", response_model=NotificationOut)
async def update_notification(
    notification_id: uuid.UUID,
    payload: NotificationPatch,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    notif = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.organization_id == principal.organization_id,
                Notification.user_id == principal.user_id,
            )
        )
    ).scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = payload.is_read
    await db.commit()
    await db.refresh(notif)
    return notif


class NotificationCreate(BaseModel):
    user_id: uuid.UUID
    type: str
    title: str
    message: str


@router.post("", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
async def create_notification_endpoint(
    payload: NotificationCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Send a notification to a specific user in the organization. Admin only."""
    notif = Notification(
        organization_id=principal.organization_id,
        user_id=payload.user_id,
        type=payload.type,
        title=payload.title,
        message=payload.message,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return notif


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await db.execute(
        update(Notification)
        .where(
            Notification.organization_id == principal.organization_id,
            Notification.user_id == principal.user_id,
            Notification.is_read == False,
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


async def create_notification(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    notif_type: str,
    title: str,
    message: str,
    appointment_id: uuid.UUID | None = None,
):
    notif = Notification(
        organization_id=organization_id,
        user_id=user_id,
        appointment_id=appointment_id,
        type=notif_type,
        title=title,
        message=message,
    )
    db.add(notif)
