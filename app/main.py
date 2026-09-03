from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from sqlalchemy import text
from app.models.parties import Organization, PlatformUser
from app.models.staff import Staff
from app.routers import (
    activity_logs,
    appointments,
    auth,
    categories,
    clients,
    notifications,
    packages,
    payments,
    products,
    reports,
    services,
    specialists,
    staff,
    walk_ins,
)

import uuid

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Appointment & booking backend for the Salon Management Module.",
    version="1.0.0",
)

# Dev-friendly CORS so a browser-based frontend (e.g. served from a
# different origin/port, or from the Claude artifacts sandbox) can call
# this API directly. Tighten `allow_origins` to your real frontend's
# origin before deploying to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(staff.router)
app.include_router(services.router)
app.include_router(specialists.router)
app.include_router(categories.router)
app.include_router(packages.router)
app.include_router(appointments.router)
app.include_router(walk_ins.router)
app.include_router(products.router)
app.include_router(payments.router)
app.include_router(reports.router)
app.include_router(notifications.router)
app.include_router(activity_logs.router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": settings.app_name}


@app.on_event("startup")
async def ensure_notifications_table():
    """Create notifications table if it doesn't exist (Render doesn't run alembic)."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                user_id UUID NOT NULL,
                appointment_id UUID REFERENCES appointments(id),
                type VARCHAR(32) NOT NULL,
                title VARCHAR(200) NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_org_user ON notifications(organization_id, user_id)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_notifications_org_user_read ON notifications(organization_id, user_id, is_read)"))
        await db.commit()


@app.on_event("startup")
async def ensure_activity_logs_table():
    """Create activity_logs table if it doesn't exist (Render doesn't run alembic)."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL REFERENCES organizations(id),
                actor_id UUID NOT NULL,
                actor_name VARCHAR(200) NOT NULL,
                actor_role VARCHAR(32) NOT NULL DEFAULT '',
                action VARCHAR(50) NOT NULL,
                entity_type VARCHAR(50) NOT NULL,
                entity_id VARCHAR(64),
                description TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_activity_logs_org ON activity_logs(organization_id)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_activity_logs_org_created ON activity_logs(organization_id, created_at)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_activity_logs_org_entity ON activity_logs(organization_id, entity_type, entity_id)"))
        await db.commit()


@app.on_event("startup")
async def seed_accounts():
    """Create default admin and staff accounts if they don't exist."""
    async with AsyncSessionLocal() as db:
        # Seed admin
        admin_exists = (
            await db.execute(select(PlatformUser).where(PlatformUser.email == "admin@salon.com"))
        ).scalar_one_or_none()

        org = None
        admin_user = None

        if not admin_exists:
            org = Organization(id=uuid.uuid4(), name="Bloom Studio")
            db.add(org)
            await db.flush()

            admin_user = PlatformUser(
                id=uuid.uuid4(),
                organization_id=org.id,
                email="admin@salon.com",
                hashed_password=hash_password("admin123"),
                role="admin",
            )
            db.add(admin_user)
            await db.flush()

            admin_staff = Staff(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=admin_user.id,
                display_name="Admin User",
                title="Owner",
                active=True,
                created_by=admin_user.id,
                updated_by=admin_user.id,
            )
            db.add(admin_staff)
        else:
            admin_user = admin_exists
            org = (await db.execute(
                select(Organization).where(Organization.id == admin_user.organization_id)
            )).scalar_one_or_none()

        # Seed staff
        staff_exists = (
            await db.execute(select(PlatformUser).where(PlatformUser.email == "staff@salon.com"))
        ).scalar_one_or_none()

        if not staff_exists and org and admin_user:
            staff_user = PlatformUser(
                id=uuid.uuid4(),
                organization_id=org.id,
                email="staff@salon.com",
                hashed_password=hash_password("staff123"),
                role="staff",
            )
            db.add(staff_user)
            await db.flush()

            staff_member = Staff(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=staff_user.id,
                display_name="Staff Member",
                title="Stylist",
                active=True,
                created_by=admin_user.id,
                updated_by=admin_user.id,
            )
            db.add(staff_member)

        # Ensure org is resolved (in case admin already existed).
        if org is None and admin_user:
            org = (await db.execute(
                select(Organization).where(Organization.id == admin_user.organization_id)
            )).scalar_one_or_none()

        # Seed a separate Super Admin (superadmin) account with full rights.
        superadmin_exists = (
            await db.execute(select(PlatformUser).where(PlatformUser.email == "superadmin@salon.com"))
        ).scalar_one_or_none()

        if not superadmin_exists and org:
            superadmin_user = PlatformUser(
                id=uuid.uuid4(),
                organization_id=org.id,
                email="superadmin@salon.com",
                hashed_password=hash_password("superadmin123"),
                role="superadmin",
            )
            db.add(superadmin_user)
            await db.flush()

            superadmin_staff = Staff(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=superadmin_user.id,
                display_name="Super Admin",
                title="Super Admin",
                active=True,
                created_by=superadmin_user.id,
                updated_by=superadmin_user.id,
            )
            db.add(superadmin_staff)

        # Seed the Owner account (separate top-tier role).
        owner_exists = (
            await db.execute(select(PlatformUser).where(PlatformUser.email == "owner@salon.com"))
        ).scalar_one_or_none()

        if not owner_exists and org:
            owner_user = PlatformUser(
                id=uuid.uuid4(),
                organization_id=org.id,
                email="owner@salon.com",
                hashed_password=hash_password("owner123"),
                role="owner",
            )
            db.add(owner_user)
            await db.flush()

            owner_staff = Staff(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=owner_user.id,
                display_name="Owner",
                title="Owner",
                active=True,
                created_by=owner_user.id,
                updated_by=owner_user.id,
            )
            db.add(owner_staff)

        await db.commit()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    # Normalizes error shape whether `detail` is a string or a dict
    # (appointment conflicts return a structured {code, message} detail).
    detail = exc.detail
    if isinstance(detail, dict):
        body = detail
    else:
        body = {"code": "ERROR", "message": detail}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "Invalid request", "errors": exc.errors()},
    )
