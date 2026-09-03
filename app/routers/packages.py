import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import Principal, get_current_principal, require_role
from app.models import Service, ServicePackage, ServicePackageItem
from app.schemas.schemas import PackageCreate, PackageItemIn, PackageOut, PackageUpdate

router = APIRouter(prefix="/packages", tags=["packages"])

ADMIN_ONLY = ("admin", "superadmin")


async def _get_package_or_404(db: AsyncSession, package_id: UUID, organization_id: UUID) -> ServicePackage:
    stmt = select(ServicePackage).where(
        ServicePackage.id == package_id,
        ServicePackage.organization_id == organization_id,
        ServicePackage.deleted_at.is_(None),
    )
    package = (await db.execute(stmt)).scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")
    return package


async def _get_service_or_404(db: AsyncSession, service_id: UUID, organization_id: UUID) -> Service:
    service = (
        await db.execute(
            select(Service).where(
                Service.id == service_id,
                Service.organization_id == organization_id,
                Service.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return service


async def _item_rows(db: AsyncSession, package: ServicePackage) -> list[dict]:
    result = await db.execute(
        select(ServicePackageItem, Service)
        .join(Service, Service.id == ServicePackageItem.service_id)
        .where(
            ServicePackageItem.package_id == package.id,
            ServicePackageItem.organization_id == package.organization_id,
        )
    )
    return [
        {
            "package_id": item.package_id,
            "service_id": item.service_id,
            "quantity": item.quantity,
            "service_name": service.name,
            "service_price_cents": service.price_cents,
        }
        for item, service in result.all()
    ]


async def _out(db: AsyncSession, package: ServicePackage) -> dict:
    return {
        "id": package.id,
        "organization_id": package.organization_id,
        "name": package.name,
        "description": package.description,
        "price_cents": package.price_cents,
        "active": package.active,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
        "items": await _item_rows(db, package),
    }


async def _replace_items(db: AsyncSession, package: ServicePackage, items: list[PackageItemIn], user_id: UUID) -> None:
    await db.execute(
        delete(ServicePackageItem).where(ServicePackageItem.package_id == package.id)
    )
    for item in items:
        await _get_service_or_404(db, item.service_id, package.organization_id)
        db.add(
            ServicePackageItem(
                package_id=package.id,
                service_id=item.service_id,
                organization_id=package.organization_id,
                quantity=item.quantity,
            )
        )


@router.post("", response_model=PackageOut, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: PackageCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    package = ServicePackage(
        id=uuid.uuid4(),
        organization_id=principal.organization_id,
        name=payload.name,
        description=payload.description,
        price_cents=payload.price_cents,
        active=payload.active,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(package)
    await db.flush()
    await _replace_items(db, package, payload.items, principal.user_id)
    await db.commit()
    await db.refresh(package)
    return await _out(db, package)


@router.get("", response_model=list[PackageOut])
async def list_packages(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    stmt = select(ServicePackage).where(
        ServicePackage.organization_id == principal.organization_id,
        ServicePackage.deleted_at.is_(None),
    )
    if active_only:
        stmt = stmt.where(ServicePackage.active.is_(True))
    result = await db.execute(stmt.order_by(ServicePackage.name))
    return [await _out(db, p) for p in result.scalars().all()]


@router.get("/{package_id}", response_model=PackageOut)
async def get_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    package = await _get_package_or_404(db, package_id, principal.organization_id)
    return await _out(db, package)


@router.patch("/{package_id}", response_model=PackageOut)
async def update_package(
    package_id: UUID,
    payload: PackageUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    package = await _get_package_or_404(db, package_id, principal.organization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "items":
            continue
        setattr(package, field, value)
    package.updated_by = principal.user_id
    if payload.items is not None:
        await _replace_items(db, package, payload.items, principal.user_id)
    await db.commit()
    await db.refresh(package)
    return await _out(db, package)


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(
    package_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    package = await _get_package_or_404(db, package_id, principal.organization_id)
    package.deleted_at = datetime.now(timezone.utc)
    package.updated_by = principal.user_id
    await db.commit()


@router.post("/{package_id}/items", response_model=PackageOut, status_code=status.HTTP_201_CREATED)
async def add_package_item(
    package_id: UUID,
    payload: PackageItemIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    package = await _get_package_or_404(db, package_id, principal.organization_id)
    await _get_service_or_404(db, payload.service_id, principal.organization_id)
    existing = (
        await db.execute(
            select(ServicePackageItem).where(
                ServicePackageItem.package_id == package.id,
                ServicePackageItem.service_id == payload.service_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.quantity = payload.quantity
    else:
        db.add(
            ServicePackageItem(
                package_id=package.id,
                service_id=payload.service_id,
                organization_id=principal.organization_id,
                quantity=payload.quantity,
            )
        )
    await db.commit()
    await db.refresh(package)
    return await _out(db, package)


@router.delete("/{package_id}/items/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_package_item(
    package_id: UUID,
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role(*ADMIN_ONLY)),
):
    package = await _get_package_or_404(db, package_id, principal.organization_id)
    item = (
        await db.execute(
            select(ServicePackageItem).where(
                ServicePackageItem.package_id == package.id,
                ServicePackageItem.service_id == service_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package item not found")
    await db.delete(item)
    await db.commit()
