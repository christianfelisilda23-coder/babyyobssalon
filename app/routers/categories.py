import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import ServiceCategory
from app.schemas.schemas import CategoryCreate, CategoryOut

router = APIRouter(prefix="/categories", tags=["categories"])

ADMIN_ONLY = ("admin",)


async def _get_category_or_404(db: AsyncSession, category_id: UUID, organization_id: UUID) -> ServiceCategory:
    stmt = select(ServiceCategory).where(
        ServiceCategory.id == category_id,
        ServiceCategory.organization_id == organization_id,
        ServiceCategory.deleted_at.is_(None),
    )
    category = (await db.execute(stmt)).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    existing = (
        await db.execute(
            select(ServiceCategory).where(
                ServiceCategory.organization_id == principal.organization_id,
                ServiceCategory.name == payload.name,
                ServiceCategory.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category name already exists")

    category = ServiceCategory(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        name=payload.name,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    result = await db.execute(
        select(ServiceCategory)
        .where(
            ServiceCategory.organization_id == principal.organization_id,
            ServiceCategory.deleted_at.is_(None),
        )
        .order_by(ServiceCategory.name)
    )
    return result.scalars().all()


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_category_or_404(db, category_id, principal.organization_id)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: UUID,
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    category = await _get_category_or_404(db, category_id, principal.organization_id)
    category.name = payload.name
    category.updated_by = principal.user_id
    await db.commit()
    await db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    category = await _get_category_or_404(db, category_id, principal.organization_id)
    category.deleted_at = datetime.now(timezone.utc)
    category.updated_by = principal.user_id
    await db.commit()
