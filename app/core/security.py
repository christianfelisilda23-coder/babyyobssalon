"""
Authentication for the standalone demo.

IMPORTANT — read this before wiring into the real ARGO platform:
In production this module does NOT own identity. `organizations` and the
platform `user_id` referenced by `staff.user_id` are managed elsewhere, and
every request should arrive already carrying a platform-issued JWT.

Because this module needs to run standalone for development/testing, this
file also includes a minimal `platform_users` table + register/login flow
that stands in for the real identity provider. Swap `create_access_token`
callers / `app/routers/auth.py` for a call to the real platform's
auth service when integrating for real; nothing else in the codebase needs
to change, because every other router only depends on `get_current_principal`
below, which just reads organization_id/user_id/role off the JWT.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=True)


class Principal(BaseModel):
    """Identity extracted from the JWT for the current request."""
    organization_id: UUID
    user_id: UUID
    role: str = "staff"


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(organization_id: UUID, user_id: UUID, role: str = "staff", email: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "organization_id": str(organization_id),
        "user_id": str(user_id),
        "role": role,
        "email": email or "",
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(organization_id: UUID, user_id: UUID, role: str = "staff", email: str | None = None) -> str:
    """Stateless refresh token, distinct type claim + longer expiry. The
    caller is expected to rotate it (the refresh endpoint mints a new pair)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_refresh_expire_minutes)
    payload = {
        "organization_id": str(organization_id),
        "user_id": str(user_id),
        "role": role,
        "email": email or "",
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _principal_from_payload(payload: dict) -> Principal:
    organization_id = payload.get("organization_id")
    user_id = payload.get("user_id")
    role = payload.get("role", "staff")
    if organization_id is None or user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims",
        )
    return Principal(organization_id=UUID(organization_id), user_id=UUID(user_id), role=role)


def get_current_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Principal:
    """
    Decodes the bearer JWT and returns the caller's identity.

    Every router in this app pulls `organization_id` from here — NEVER from
    the request body or query params — so a client can never act on another
    tenant's data by passing a different organization_id in the payload.
    """
    return _principal_from_payload(_decode_token(credentials.credentials, "access"))


def get_refresh_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Principal:
    """Like `get_current_principal` but only accepts refresh tokens
    (used by POST /auth/refresh)."""
    return _principal_from_payload(_decode_token(credentials.credentials, "refresh"))


def require_role(*allowed_roles: str):
    """Dependency factory for simple role checks (e.g. require_role('admin'))."""

    def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return principal

    return _check
