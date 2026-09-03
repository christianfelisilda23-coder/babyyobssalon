import uuid
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import Appointment, Product, ProductUsage
from app.schemas.schemas import ProductCreate, ProductOut, ProductUpdate, ProductUsageCreate, ProductUsageOut, StockAdjust

router = APIRouter(prefix="/products", tags=["products"])

STAFF_ROLES = ("admin", "front_desk", "superadmin")


async def _get_product_or_404(db: AsyncSession, product_id: UUID, organization_id: UUID) -> Product:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.organization_id == organization_id,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


async def _get_appointment_or_404(db: AsyncSession, appointment_id: UUID, organization_id: UUID) -> Appointment:
    appointment = (
        await db.execute(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.organization_id == organization_id,
                Appointment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appointment


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    product = Product(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        created_by=principal.user_id,
        updated_by=principal.user_id,
        **payload.model_dump(),
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.get("", response_model=list[ProductOut])
async def list_products(
    active_only: bool = True,
    search: str | None = Query(default=None),
    low_stock: bool = False,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(Product).where(
        Product.organization_id == principal.organization_id,
        Product.deleted_at.is_(None),
    )
    if active_only:
        stmt = stmt.where(Product.active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where((Product.name.ilike(like)) | (Product.sku.ilike(like)))
    if low_stock:
        stmt = stmt.where(Product.stock_quantity <= Product.reorder_level)
    result = await db.execute(stmt.order_by(Product.name))
    return result.scalars().all()


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    return await _get_product_or_404(db, product_id, principal.organization_id)


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    product = await _get_product_or_404(db, product_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    product.updated_by = principal.user_id
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    product = await _get_product_or_404(db, product_id, principal.organization_id)
    product.deleted_at = datetime.now(timezone.utc)
    product.updated_by = principal.user_id
    await db.commit()


@router.post("/{product_id}/stock", response_model=ProductOut)
async def adjust_stock(
    product_id: UUID,
    payload: StockAdjust,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    """Adjusts stock by a signed delta (e.g. +10 for a delivery, -2 for
    damage). New quantity must not go negative."""
    product = await _get_product_or_404(db, product_id, principal.organization_id)
    new_qty = product.stock_quantity + payload.delta
    if new_qty < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Stock cannot go negative")
    product.stock_quantity = new_qty
    product.updated_by = principal.user_id
    await db.commit()
    await db.refresh(product)
    return product


# ----------------------------------------------------- product usage --------


@router.post("/usage", response_model=ProductUsageOut, status_code=status.HTTP_201_CREATED)
async def record_product_usage(
    payload: ProductUsageCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    """
    Records a product consumed on an appointment. Stock is NOT deducted here
    — it is deducted when the appointment is marked completed (and blocks
    completion if insufficient).
    """
    appointment = await _get_appointment_or_404(db, payload.appointment_id, principal.organization_id)
    product = await _get_product_or_404(db, payload.product_id, principal.organization_id)

    usage = ProductUsage(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        appointment_id=appointment.id,
        product_id=product.id,
        product_name=product.name,
        quantity=payload.quantity,
        unit_cost_cents=product.price_cents,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(usage)
    await db.commit()
    await db.refresh(usage)
    return usage


@router.get("/appointments/{appointment_id}/usage", response_model=list[ProductUsageOut])
async def list_appointment_usage(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    await _get_appointment_or_404(db, appointment_id, principal.organization_id)
    result = await db.execute(
        select(ProductUsage).where(
            ProductUsage.organization_id == principal.organization_id,
            ProductUsage.appointment_id == appointment_id,
            ProductUsage.deleted_at.is_(None),
        )
    )
    return result.scalars().all()


@router.delete("/usage/{usage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_usage(
    usage_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*STAFF_ROLES)),
):
    usage = (
        await db.execute(
            select(ProductUsage).where(
                ProductUsage.id == usage_id,
                ProductUsage.organization_id == principal.organization_id,
                ProductUsage.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if usage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product usage record not found")
    usage.deleted_at = datetime.now(timezone.utc)
    usage.updated_by = principal.user_id
    await db.commit()
