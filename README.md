# Salon Management Module — Backend

A working implementation of the database design submitted in
`database-design-submission.zip` (`SCHEMA.md`, `database-schema.dbml`,
`erd.png`, `database-flow.png`), built with:

- **PostgreSQL 14**
- **Python 3.11**
- **FastAPI** (async, SQLAlchemy 2.0 + asyncpg, Alembic migrations)

It has been run and tested end-to-end (register → book → double-booking
conflict → status transitions → tenant isolation) — see "What's been
verified" at the bottom.

## What's implemented

- Every table from `SCHEMA.md`: `organizations`, `clients`, `staff`,
  `services`, `staff_services`, `appointments`, with the same columns,
  constraints, indexes, and the `appointment_status` enum.
- The exact booking transaction from `database-flow.png`: validate
  ownership → `BEGIN` → lock the staff member's schedule (`SELECT ...
  FOR UPDATE`) → overlap check → insert or roll back with
  `409 SCHEDULE_CONFLICT`.
- **Defense in depth**: on top of the app-level lock, the migration adds
  a Postgres `EXCLUDE` constraint (via `btree_gist`) so a double-booking
  is physically impossible at the database level too, even if the API
  layer is bypassed.
- Multi-tenant isolation: `organization_id` is read only from the JWT,
  never from the request body, and every query filters by it.
- Full CRUD for clients, staff, services, plus staff↔service
  qualification links.
- The appointment status state machine (`requested → confirmed →
  in_progress → completed`, with `cancelled`/`no_show` branches),
  enforced server-side.
- Soft deletes (`deleted_at`) instead of hard deletes on business tables.

### One thing worth knowing: auth

In the real ARGO platform, `organizations` and the `user_id` behind
`staff.user_id` are owned by the platform, not this module — this module
just references them. So this module can't run **standalone** without
*some* identity system. `app/routers/auth.py` and the `platform_users`
table are a minimal stand-in for that (register/login/JWT), clearly
marked in the code. When wiring into the real platform, swap that piece
out; every other router only depends on `get_current_principal()`, which
just reads `organization_id`/`user_id`/`role` off whatever JWT it's given.

## Project layout

```
salon-backend/
├── app/
│   ├── core/            # config, DB session, auth/JWT
│   ├── models/           # SQLAlchemy models (mirrors SCHEMA.md)
│   ├── schemas/           # Pydantic request/response models
│   ├── routers/          # auth, clients, staff, services, appointments
│   ├── services/         # booking transaction + status state machine
│   └── main.py
├── alembic/               # migrations (0001_initial_schema.py has the full schema)
├── docker-compose.yml     # Postgres 14 + the API
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Setup — Option A: Docker (recommended, fastest)

Requires Docker + Docker Compose.

```bash
cd salon-backend
docker compose up --build
```

That's it. This:
1. Starts Postgres 14 in a container and waits until it's healthy.
2. Builds the API image (Python 3.11 + dependencies).
3. Runs `alembic upgrade head` to create the schema.
4. Starts the API on **http://localhost:8000**.

Interactive API docs: **http://localhost:8000/docs**

To stop: `Ctrl+C`, then `docker compose down` (add `-v` to also wipe the
database volume).

## Setup — Option B: Run locally without Docker

Requires Python 3.11 and a local PostgreSQL 14 server.

**1. Create the database**
```bash
psql -U postgres -c "CREATE DATABASE salon_db;"
```

**2. Set up the app**
```bash
cd salon-backend
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # edit .env if your Postgres creds differ
```

**3. Run the migration** (creates all tables, constraints, indexes, and
the overlap-prevention constraint)
```bash
alembic upgrade head
```

**4. Start the API**
```bash
uvicorn app.main:app --reload --port 8000
```

Visit **http://localhost:8000/docs** for interactive Swagger docs.

## Walkthrough: exercising the API

You can do all of this from `/docs`, or with curl:

**1. Register an organization + admin user** (demo stand-in for the
platform's real signup — see note above)
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "organization_name": "Glow Salon",
    "email": "owner@glowsalon.example.com",
    "password": "supersecret123",
    "display_name": "Jamie Owner"
  }'
```
Save the `access_token` from the response — every other call needs it as
`Authorization: Bearer <token>`.

**2. Create a service**
```bash
curl -X POST http://localhost:8000/services \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Haircut & Style", "category": "Hair", "duration_minutes": 45, "price_cents": 5500}'
```

**3. Create a client**
```bash
curl -X POST http://localhost:8000/clients \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"full_name": "Alex Rivera", "phone": "+15551234567"}'
```

**4. Qualify a staff member for the service** (registering created you
as staff automatically — `GET /staff` to get your `staff_id`)
```bash
curl -X POST http://localhost:8000/staff/$STAFF_ID/services/$SERVICE_ID \
  -H "Authorization: Bearer $TOKEN"
```

**5. Book an appointment**
```bash
curl -X POST http://localhost:8000/appointments \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"client_id\": \"$CLIENT_ID\", \"staff_id\": \"$STAFF_ID\", \"service_id\": \"$SERVICE_ID\", \"start_time\": \"2026-08-15T10:00:00Z\"}"
```
`end_time` is computed automatically from the service's duration.

**6. Try to double-book the same staff member for an overlapping time** —
you'll get `409 SCHEDULE_CONFLICT`.

**7. Move it through its lifecycle**
```bash
curl -X POST http://localhost:8000/appointments/$APPOINTMENT_ID/status \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"status": "confirmed"}'
```
Legal transitions: `requested → confirmed | cancelled`,
`confirmed → in_progress | cancelled | no_show`,
`in_progress → completed | cancelled`. Anything else returns `400`.

## What's been verified

Built and tested against a real Postgres instance (not just written from
memory) — the migration was applied, the server was run, and each of
these was exercised live over HTTP:

- ✅ Register → org, admin user, and matching staff row created; JWT issued
- ✅ Login → same JWT contract
- ✅ Service / client / staff CRUD, tenant-scoped
- ✅ Staff↔service qualification linking
- ✅ Booking an appointment computes `end_time` correctly from the service duration
- ✅ Booking an **overlapping** slot for the same staff member → `409 SCHEDULE_CONFLICT`
- ✅ Booking a **back-to-back, non-overlapping** slot → succeeds (boundary-correct)
- ✅ Status transitions follow the state machine; illegal jumps (e.g.
  `confirmed → completed`, skipping `in_progress`) are rejected with `400`
- ✅ Cancelling an appointment frees the slot — it can be rebooked
- ✅ A second organization cannot see or fetch-by-ID the first
  organization's clients (tenant isolation, including on direct ID access)

## Extending this

- Swap `app/routers/auth.py` for a call into the real ARGO identity
  service and drop the `platform_users` table once integrated.
- Add pagination cursors if client/appointment lists grow large (the
  current `limit`/`offset` works fine at moderate scale, given the
  indexes already in place).
- If you want appointment reminders/notifications, that's a natural
  next module — it would read from `appointments` but shouldn't need
  schema changes.
