import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models.activity_log import ActivityLog

router = APIRouter(prefix="/activity-logs", tags=["activity-logs"])

ADMIN_ROLES = ("admin", "owner", "front_desk", "superadmin")


class ActivityLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    actor_id: uuid.UUID
    actor_name: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str | None
    description: str
    created_at: datetime


class ActivityLogListOut(BaseModel):
    items: list[ActivityLogOut]
    total: int


@router.get("", response_model=ActivityLogListOut)
async def list_activity_logs(
    action: str | None = None,
    entity_type: str | None = None,
    search: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ROLES)),
):
    stmt = select(ActivityLog).where(
        ActivityLog.organization_id == principal.organization_id
    )
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (ActivityLog.description.ilike(like))
            | (ActivityLog.actor_name.ilike(like))
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = stmt.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit)
    items = (await db.execute(stmt)).scalars().all()
    return {"items": list(items), "total": total}


@router.get("/summary")
async def activity_summary(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ROLES)),
):
    """Per-action counts used to build filter chips."""
    stmt = (
        select(ActivityLog.action, func.count(ActivityLog.id))
        .where(ActivityLog.organization_id == principal.organization_id)
        .group_by(ActivityLog.action)
        .order_by(func.count(ActivityLog.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    return {"actions": {action: count for action, count in rows}}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_activity_logs(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "superadmin")),
):
    """Delete all activity logs for this organization (admin only)."""
    logs = (
        await db.execute(
            select(ActivityLog).where(ActivityLog.organization_id == principal.organization_id)
        )
    ).scalars().all()
    for log in logs:
        await db.delete(log)
    await db.commit()
    return None


async def log_activity(
    db: AsyncSession,
    organization_id: uuid.UUID,
    action: str,
    entity_type: str,
    description: str,
    actor_id: uuid.UUID | None = None,
    actor_name: str = "system",
    actor_role: str = "",
    entity_id: uuid.UUID | str | None = None,
):
    """Create an activity log row. Called at the end of mutating endpoints
    (reusing the caller's already-open transaction/session)."""
    log = ActivityLog(
        organization_id=organization_id,
        actor_id=actor_id or uuid.uuid4(),
        actor_name=str(actor_name),
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        description=description,
    )
    db.add(log)
