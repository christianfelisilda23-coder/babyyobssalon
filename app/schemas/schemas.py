from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import AppointmentStatus, PaymentMethod, PaymentStatus

# ---------------------------------------------------------------- Auth ----
class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = Field(default="staff", max_length=32)
    display_name: str = Field(min_length=1, max_length=160)


class ClientRegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    password: str = Field(min_length=6)
    phone: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    email: str
    role: str
    created_at: datetime


# ------------------------------------------------------------- Clients ----
class ClientBase(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    notes: str | None = None


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    notes: str | None = None


class ClientOut(ClientBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------- Staff ----
class StaffBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    title: str | None = Field(default=None, max_length=80)
    active: bool = True


class StaffCreate(StaffBase):
    user_id: UUID


class StaffUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    title: str | None = Field(default=None, max_length=80)
    active: bool | None = None


class StaffOut(StaffBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------ Services ----
class ServiceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    duration_minutes: int = Field(gt=0)
    price_cents: int = Field(ge=0)
    active: bool = True


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    duration_minutes: int | None = Field(default=None, gt=0)
    price_cents: int | None = Field(default=None, ge=0)
    active: bool | None = None


class ServiceOut(ServiceBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------- Staff/Services ---
class StaffServiceLink(BaseModel):
    staff_id: UUID
    service_id: UUID


class StaffServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    staff_id: UUID
    service_id: UUID
    organization_id: UUID
    created_at: datetime


# --------------------------------------------------------- Appointments ---
class AppointmentServiceLine(BaseModel):
    """One service line to render at booking (package items / multi-service)."""
    service_id: UUID
    quantity: int = Field(default=1, gt=0)
    commission_rate_pct: Decimal | None = Field(default=None, ge=0)


class AppointmentCreate(BaseModel):
    client_id: UUID | None = None
    walk_in_id: UUID | None = None
    staff_id: UUID
    # Legacy single-service booking field (kept for the original contract).
    service_id: UUID | None = None
    # New booking styles: a list of services, or a package to expand.
    service_ids: list[UUID] | None = None
    services: list[AppointmentServiceLine] | None = None
    package_id: UUID | None = None
    start_time: datetime
    discount_cents: int = Field(default=0, ge=0)
    notes: str | None = None

    @field_validator("start_time")
    @classmethod
    def start_time_must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("start_time must include a timezone offset")
        return v

    @model_validator(mode="after")
    def validate_booking_shape(self) -> "AppointmentCreate":
        if (self.client_id is None) == (self.walk_in_id is None):
            raise ValueError("Exactly one of client_id or walk_in_id is required")
        has_service = any(
            [self.service_id is not None, self.service_ids, self.services, self.package_id is not None]
        )
        if not has_service:
            raise ValueError("Provide a service_id, service_ids, services, or package_id")
        if self.service_ids and self.services:
            raise ValueError("Provide either service_ids or services, not both")
        return self


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus
    cancellation_reason: str | None = None


class AppointmentServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    appointment_id: UUID
    service_id: UUID | None
    service_name: str
    duration_minutes: int
    price_cents: int
    quantity: int
    commission_rate_pct: Decimal | None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    client_id: UUID | None
    walk_in_id: UUID | None
    staff_id: UUID
    service_id: UUID | None
    package_id: UUID | None
    package_price_cents: int | None
    total_cents: int
    discount_cents: int
    start_time: datetime
    end_time: datetime
    status: AppointmentStatus
    notes: str | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    appointment_services: list[AppointmentServiceOut] = []


# ------------------------------------------------------- Walk-ins ----------
class WalkInCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    notes: str | None = None


class WalkInUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    notes: str | None = None


class WalkInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    full_name: str
    phone: str | None
    email: EmailStr | None
    notes: str | None
    converted_client_id: UUID | None
    created_at: datetime
    updated_at: datetime


class WalkInConvertRequest(BaseModel):
    """Details used to create the registered client record."""
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    notes: str | None = None


# --------------------------------------------------- Customer preferences ---
class PreferenceCreate(BaseModel):
    preferred_specialist_id: UUID | None = None
    allergies: str | None = None
    product_sensitivities: str | None = None
    notes: str | None = None


class PreferenceOut(PreferenceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    client_id: UUID
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------- Specialists -----
class SpecialistCreate(BaseModel):
    staff_id: UUID
    default_commission_rate_pct: Decimal = Field(default=Decimal("15.00"), ge=0)


class SpecialistUpdate(BaseModel):
    default_commission_rate_pct: Decimal | None = Field(default=None, ge=0)


class SpecialistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    staff_id: UUID
    default_commission_rate_pct: Decimal
    staff_display_name: str | None = None
    staff_title: str | None = None
    staff_active: bool | None = None
    created_at: datetime
    updated_at: datetime


class SpecialtyLink(BaseModel):
    category_id: UUID


# --------------------------------------------------- Service categories ----
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CategoryOut(CategoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------ Packages -----
class PackageItemIn(BaseModel):
    service_id: UUID
    quantity: int = Field(default=1, gt=0)


class PackageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    price_cents: int = Field(ge=0)
    active: bool = True
    items: list[PackageItemIn] = Field(min_length=1)


class PackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    active: bool | None = None
    items: list[PackageItemIn] | None = None


class PackageItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    package_id: UUID
    service_id: UUID
    quantity: int
    service_name: str | None = None
    service_price_cents: int | None = None


class PackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    price_cents: int
    active: bool
    created_at: datetime
    updated_at: datetime
    items: list[PackageItemOut] = []


# ------------------------------------------------------------- Products ----
class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    sku: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=60)
    unit: str = Field(default="unit", max_length=20)
    stock_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    price_cents: int = Field(default=0, ge=0)
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0)
    active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    sku: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=60)
    unit: str | None = Field(default=None, max_length=20)
    stock_quantity: Decimal | None = Field(default=None, ge=0)
    price_cents: int | None = Field(default=None, ge=0)
    reorder_level: Decimal | None = Field(default=None, ge=0)
    active: bool | None = None


class StockAdjust(BaseModel):
    delta: Decimal


class ProductOut(ProductCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------- Product usage ----
class ProductUsageCreate(BaseModel):
    appointment_id: UUID
    product_id: UUID
    quantity: Decimal = Field(gt=0)


class ProductUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    appointment_id: UUID
    product_id: UUID | None
    product_name: str
    quantity: Decimal
    unit_cost_cents: int
    created_at: datetime


# -------------------------------------------------------------- Payments ---
class PaymentCreate(BaseModel):
    appointment_id: UUID
    amount_cents: int = Field(gt=0)
    method: PaymentMethod
    status: PaymentStatus = PaymentStatus.pending
    tip_cents: int = Field(default=0, ge=0)
    discount_cents: int = Field(default=0, ge=0)
    reference: str | None = Field(default=None, max_length=120)
    paid_at: datetime | None = None


class PaymentUpdate(BaseModel):
    amount_cents: int | None = Field(default=None, gt=0)
    method: PaymentMethod | None = None
    status: PaymentStatus | None = None
    tip_cents: int | None = Field(default=None, ge=0)
    discount_cents: int | None = Field(default=None, ge=0)
    reference: str | None = Field(default=None, max_length=120)
    paid_at: datetime | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    appointment_id: UUID
    amount_cents: int
    method: PaymentMethod
    status: PaymentStatus
    tip_cents: int
    discount_cents: int
    reference: str | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AppointmentBalanceOut(BaseModel):
    appointment_id: UUID
    total_cents: int
    discount_cents: int
    owed_cents: int
    paid_cents: int
    tip_cents: int
    outstanding_cents: int
    settled: bool


# ----------------------------------------------------------- Commissions ---
class CommissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    appointment_id: UUID
    specialist_id: UUID | None
    service_name: str
    rate_pct: Decimal
    amount_cents: int
    created_at: datetime


class CommissionSummaryItem(BaseModel):
    specialist_id: UUID
    specialist_name: str | None = None
    appointments: int
    services: int
    amount_cents: int


# --------------------------------------------------------- Service history -
class ServiceHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    client_id: UUID
    appointment_id: UUID | None
    service_id: UUID | None
    specialist_id: UUID | None
    service_name: str
    price_cents: int
    completed_at: datetime
    created_at: datetime
