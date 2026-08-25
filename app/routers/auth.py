import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    Principal,
    create_access_token,
    create_refresh_token,
    get_current_principal,
    get_refresh_principal,
    hash_password,
    verify_password,
)
from app.models import Organization, PlatformUser, Staff
from app.schemas.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(user: PlatformUser) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(
            organization_id=user.organization_id, user_id=user.id, role=user.role
        ),
        refresh_token=create_refresh_token(
            organization_id=user.organization_id, user_id=user.id, role=user.role
        ),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    DEMO ONLY. Creates a new organization + an admin user + a matching
    staff record, and returns a JWT pair. In production, organizations and
    users are provisioned by the ARGO platform, not by this module.
    """
    existing = (
        await db.execute(select(PlatformUser).where(PlatformUser.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    org = Organization(id=uuid.uuid4(), name=payload.organization_name)
    db.add(org)
    await db.flush()

    user = PlatformUser(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role="admin",
    )
    db.add(user)
    await db.flush()

    staff = Staff(
        id=uuid.uuid4(),
        organization_id=org.id,
        user_id=user.id,
        display_name=payload.display_name,
        title="Admin",
        active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(staff)
    await db.commit()

    return _token_pair(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.email == payload.email))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    return _token_pair(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_refresh_principal),
):
    """
    Rotates a refresh token into a fresh access + refresh pair. The token
    must be a `type=refresh` JWT (see app/core/security.py) issued to the
    same user that still exists.
    """
    user = (
        await db.execute(
            select(PlatformUser).where(
                PlatformUser.id == principal.user_id,
                PlatformUser.organization_id == principal.organization_id,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The user account behind this refresh token no longer exists",
        )

    # Re-issue with the user's current role (handles role changes).
    return _token_pair(user)
