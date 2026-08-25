# Build Prompt: Salon Management System (SMS)

Use this prompt as-is to brief an AI coding assistant (or a dev team) on building the system.

---

## 1. Project Overview

Build a **Salon Management System (SMS)** — a full-stack web application for managing a salon's day-to-day operations: clients, services, staff, appointments, walk-ins, packages, product usage, commissions, payments, customer preferences, and service history.

**Tech stack (required):**
- **Backend:** Python 3.11, FastAPI
- **Database:** PostgreSQL 14
- **ORM:** SQLAlchemy 2.0 (async) with Alembic for migrations
- **Validation:** Pydantic v2 schemas, separate from ORM models
- **Auth:** JWT (access + refresh tokens), role-based access control
- **Password hashing:** passlib (bcrypt)
- **Server:** Uvicorn
- **Testing:** Pytest + httpx AsyncClient

---

## 2. Core Modules & Entities

Design the schema and endpoints around these entities:

1. **Clients** — registered customers with contact info and preferences
2. **Walk-in Customers** — unregistered or unscheduled visitors, optionally convertible to a full client record
3. **Employees** — all staff (may include non-service roles like front desk/admin)
4. **Specialists** — employees who perform services (subtype of employee, with specialties/skills)
5. **Salon Services** — individual services offered (haircut, coloring, manicure, massage, etc.), with base price and duration
6. **Service Packages** — bundles of multiple services sold at a combined price
7. **Appointments** — scheduled bookings linking a client (or walk-in), specialist, service(s)/package, date/time, and status
8. **Products** — retail/consumable products (shampoo, dye, wax, etc.)
9. **Product Usage** — products consumed per appointment/service (for inventory deduction and cost tracking)
10. **Commissions** — specialist earnings computed per completed service/appointment
11. **Payments** — transactions tied to appointments (cash, card, e-wallet), including tips and discounts
12. **Customer Preferences** — preferred specialist, allergies, product sensitivities, notes
13. **Service History** — historical log of completed services per client, auto-populated from completed appointments

---

## 3. Database Schema (PostgreSQL 14)

Design normalized tables with the following conventions:
- All primary keys are `UUID` (use `gen_random_uuid()` via `pgcrypto` extension)
- All tables include `created_at`, `updated_at` (timestamptz, default `now()`), and `is_active`/`is_deleted` for soft deletes where relevant
- Foreign keys use `ON DELETE RESTRICT` by default, except audit/log-style tables which may use `ON DELETE SET NULL`
- Use `ENUM` types (or CHECK constraints) for status fields (e.g., appointment status, payment method)
- Add indexes on all foreign keys and frequently filtered columns (e.g., `appointment_date`, `client_id`, `specialist_id`)

### Suggested table list

| Table | Purpose |
|---|---|
| `clients` | Registered customers |
| `walk_in_customers` | Unscheduled/unregistered visitors |
| `customer_preferences` | Preferences/allergies linked to a client |
| `employees` | All staff records |
| `specialists` | Extends `employees`; skill/specialty data |
| `specialist_specialties` | Many-to-many: specialist ↔ service categories |
| `service_categories` | Grouping for services (Hair, Nails, Spa, etc.) |
| `salon_services` | Individual services, price, duration |
| `service_packages` | Bundled offerings |
| `service_package_items` | Many-to-many: package ↔ services |
| `appointments` | Scheduled bookings |
| `appointment_services` | Many-to-many: appointment ↔ services/package rendered |
| `products` | Retail/consumable inventory |
| `product_usage` | Products consumed per appointment |
| `commissions` | Specialist earnings per appointment/service |
| `payments` | Transactions per appointment |
| `service_history` | Denormalized/log table of completed services per client |
| `users` | Login accounts (admin, front desk, specialist) mapped to `employees` |

### Key relationships
- `clients` 1—N `appointments`, 1—1 `customer_preferences`, 1—N `service_history`
- `walk_in_customers` 1—N `appointments` (appointment references either `client_id` or `walk_in_id`, never both — enforce via CHECK constraint)
- `specialists` 1—N `appointments`, 1—N `commissions`
- `appointments` 1—N `appointment_services`, 1—N `product_usage`, 1—1 `payments`, 1—N `commissions`
- `service_packages` N—N `salon_services` via `service_package_items`

---

## 4. Business Logic Requirements

- **Appointment scheduling:** prevent double-booking a specialist for overlapping time slots; validate against specialist working hours/availability.
- **Walk-ins:** allow creating an appointment directly from a walk-in record without requiring full client registration; support converting a walk-in to a registered client later while preserving service history.
- **Service packages:** when booked, expand into individual `appointment_services` rows so reporting and commissions work at the service level.
- **Product usage:** deduct quantity from `products` stock on appointment completion; block/flag completion if stock is insufficient.
- **Commission calculation:** configurable commission rate per specialist (flat % or per-service override); auto-generate commission records when an appointment is marked `completed`.
- **Payments:** support partial/split payments, discounts, tips; payment total must reconcile with services/packages rendered.
- **Service history:** auto-insert a `service_history` record whenever an appointment status changes to `completed`.
- **Status lifecycle for appointments:** `pending` → `confirmed` → `in_progress` → `completed` / `cancelled` / `no_show`.

---

## 5. API Structure (FastAPI)

Organize routers by module, e.g.:

```
app/
├── main.py
├── core/
│   ├── config.py
│   ├── security.py
│   └── database.py
├── models/          # SQLAlchemy ORM models
├── schemas/         # Pydantic schemas (Create/Update/Read per entity)
├── crud/            # DB access layer per entity
├── routers/
│   ├── auth.py
│   ├── clients.py
│   ├── walk_ins.py
│   ├── employees.py
│   ├── specialists.py
│   ├── services.py
│   ├── packages.py
│   ├── appointments.py
│   ├── products.py
│   ├── commissions.py
│   ├── payments.py
│   └── reports.py
├── services/        # business logic (scheduling checks, commission calc, etc.)
└── tests/
```

Each entity router should expose standard REST endpoints (`GET` list w/ pagination & filters, `GET` by id, `POST`, `PUT/PATCH`, `DELETE` soft-delete) plus module-specific actions, e.g.:
- `POST /appointments/{id}/complete` — mark complete, trigger commission + service history
- `POST /walk-ins/{id}/convert-to-client`
- `GET /specialists/{id}/availability?date=`
- `GET /reports/commissions?specialist_id=&from=&to=`
- `GET /reports/revenue?from=&to=`

---

## 6. Roles & Access Control

- **Admin/Owner:** full access, reports, staff management, pricing
- **Front Desk/Receptionist:** manage appointments, walk-ins, payments, clients
- **Specialist:** view own schedule, own commissions, mark own appointments in-progress/complete
- Enforce via JWT-embedded role claims and FastAPI dependency-based permission checks.

---

## 7. Non-Functional Requirements

- Use Pydantic settings (`.env`) for DB URL, JWT secret, token expiry.
- Alembic migrations for every schema change (no manual DDL).
- Consistent error responses (custom exception handlers → structured JSON with status code, message, field errors).
- Input validation on all write endpoints (e.g., no negative prices/durations, appointment times must be in the future for new bookings).
- Async DB sessions throughout (asyncpg driver).
- Seed script for demo data (sample services, specialists, clients).
- API documented via FastAPI's built-in OpenAPI/Swagger UI.

---

## 8. Deliverables Expected

1. PostgreSQL 14 schema + Alembic migration scripts
2. FastAPI backend implementing all modules above
3. Seed/demo data script
4. Postman collection or `requests.http` file covering all endpoints
5. README with setup instructions (venv, `pip install`, `alembic upgrade head`, `uvicorn` run command)

---

### Notes for the assistant building this
- Ask before assuming a specific frontend framework — this prompt covers backend only unless a frontend is explicitly requested.
- Confirm commission rules (flat vs. per-service, tiered) and package pricing rules (fixed bundle price vs. sum-with-discount) before finalizing those tables, since these vary by salon and affect the schema.
