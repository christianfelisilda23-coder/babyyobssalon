from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.routers import (
    appointments,
    auth,
    categories,
    clients,
    packages,
    payments,
    products,
    reports,
    services,
    specialists,
    staff,
    walk_ins,
)

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


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "service": settings.app_name}


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
