# Forcelink Partner Integration API — Momentum Dashboard POC (mock)

A runnable FastAPI mock of `acumensoftware-forcelink-partner-integration-api-1-unresolved.json`,
backed by SQLite and seeded with about a year of generated data so every endpoint
returns something worth querying.

## Run

```bash
./run.sh                 # venv + install + seed + serve on :8000
```

Or manually:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.seed --reset      # rebuild momentum.db
.venv/bin/uvicorn app.main:app --reload
```

Swagger UI: <http://127.0.0.1:8000/docs>

### Docker

```bash
docker build -t momentum-mock-api .
docker run --rm -p 8000:8000 momentum-mock-api
```

Or `docker compose up --build`.

The database is seeded during the build, so the container serves data as soon as it
starts. [docker-entrypoint.sh](docker-entrypoint.sh) re-seeds only when
`/app/momentum.db` is missing — which is what happens if you mount a volume over it.
To force a fresh dataset in a running container:

```bash
docker compose exec api python -m app.seed --reset
```

## Auth

Hardcoded in [app/config.py](app/config.py):

```
X-Api-Key: fl_uat_momentum_7f3c9a21d4e84b0c95e6
```

The same value is also accepted as `Authorization: Bearer <token>`, since the spec
lists `bearerAuth` for mock testing. Anything else returns `401 UNAUTHORIZED` in
the standard error envelope.

The key is scoped to sites `4021–4025` and stores `12–15`. The seed data also
includes site `4099` and store `99`, which are **out** of scope — request either
and you get `403 FORBIDDEN`, so partner scoping is exercisable end to end.

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/attendance/shift-records` | `dateFrom`, `dateTo` required; optional `orgUnitId`, `employeeId` |
| GET | `/service-proof/completed-work-orders` | `dateFrom`, `dateTo` required; optional `orgUnitId`; only `COMPLETED` rows |
| GET | `/stock/on-hand` | optional `storeId`; current snapshot |
| GET | `/stock/movements` | `dateFrom`, `dateTo` required; optional `storeId` |
| GET | `/resources` | optional `orgUnitId`, `resourceId`, `role` (`CLEANER` / `SUPERVISOR` / `SITE_MANAGER`); not date-ranged |
| GET | `/escalations` | `dateFrom`, `dateTo` required (on `createdDate`); optional `orgUnitId`, `status` (`OPEN` / `ACKNOWLEDGED` / `RESOLVED`) |
| GET | `/customer-feedback/qr-responses` | `dateFrom`, `dateTo` required; optional `orgUnitId`; Prestige Pulse QR submissions |
| GET | `/cleaner-tracking/check-ins` | `dateFrom`, `dateTo` required; optional `orgUnitId`, `resourceId`; NFC scans and beacon check-ins |

Completed work orders carry both `createdDate` and `completedDate`, so completion time
can be derived. Every resource id in the other payloads (`employeeId`, `resourceId`,
`raisedByResourceId`, `assignedToResourceId`) resolves through `/resources`, and
`supervisorId` there gives the cleaner → supervisor → site manager hierarchy.

All endpoints are paginated with `page` (default 1) and `per_page` (default 50, max 500),
return the `ApiEnvelopeBase` shell (`success` / `data` / `message` / `error` /
`pagination` / `meta`), and echo `meta.request_id` in the `X-Request-Id` header.

Date ranges are validated per the spec: ISO-8601 `YYYY-MM-DD`, `dateTo` not before
`dateFrom`, and a maximum span of 92 days. Failures come back as
`400 VALIDATION_ERROR` with a `details` array, in the envelope — including FastAPI's
own parameter errors, which are remapped so callers never see a raw 422. Unknown
`role` / `status` values are rejected the same way.

The Chi POC area exclusion (so QR / cleaner-tracking data isn't duplicated across
dashboards) is not modelled yet: every scoped site returns full data.

## Example

```bash
curl -H "X-Api-Key: fl_uat_momentum_7f3c9a21d4e84b0c95e6" \
  "http://127.0.0.1:8000/attendance/shift-records?dateFrom=2026-09-01&dateTo=2026-09-15&orgUnitId=4021&per_page=5"

curl -H "X-Api-Key: fl_uat_momentum_7f3c9a21d4e84b0c95e6" \
  "http://127.0.0.1:8000/customer-feedback/qr-responses?dateFrom=2026-09-01&dateTo=2026-09-17&orgUnitId=4021"

curl -H "X-Api-Key: fl_uat_momentum_7f3c9a21d4e84b0c95e6" \
  "http://127.0.0.1:8000/escalations?dateFrom=2026-09-01&dateTo=2026-09-17&status=OPEN"
```

A full usage guide (auth, conventions, every endpoint, dashboard recipes) is in
[docs/Forcelink-Partner-API-Guide.pdf](docs/Forcelink-Partner-API-Guide.pdf).

## Seed data

`python -m app.seed --reset` rebuilds `momentum.db` from a fixed random seed, so the
dataset is identical on every machine. It covers 2025-09-17 → 2026-09-17:

| Table | Rows |
| --- | --- |
| `org_unit` (sites) | 6 |
| `store` | 5 |
| `employee` (resources) | 134 |
| `location` (QR / NFC / beacon points) | 76 |
| `material` | 24 |
| `shift_attendance` | ~34,600 |
| `work_order` | ~16,900 |
| `cleaner_check_in` | ~257,000 |
| `customer_feedback` | ~55,600 |
| `escalation` | ~6,100 |
| `stock_on_hand` | 120 |
| `stock_movement` | ~12,600 |

Shape of the data: attendance is one row per employee per weekday with a realistic
mix of `ON_TIME` / `LATE` / `ABSENT` / `ON_LEAVE`; work orders are mostly `COMPLETED`
with a few open ones left in so the status filter has something to exclude; and
on-hand quantities are derived from the movement ledger rather than invented
independently, so receipts and issues reconcile against the balances.

The newer datasets are cross-consistent too: cleaner check-ins only fall inside that
cleaner's clock-in/clock-out on days they worked; about 60% of QR ratings of 1–2
raise a `QR_FEEDBACK` escalation (linked both ways); escalations open for more than
4h / 24h move to level 2 / 3, and level 3 goes to the site manager; and the last few
days keep a backlog of `OPEN` / `ACKNOWLEDGED` escalations.

A `momentum.db` built before these tables existed is detected and rebuilt
automatically the next time `python -m app.seed` runs.

## Layout

| File | Purpose |
| --- | --- |
| [app/main.py](app/main.py) | Routes, exception handlers, request-id middleware |
| [app/config.py](app/config.py) | API key, scoped site/store ids, limits |
| [app/db.py](app/db.py) | Schema and connection handling |
| [app/envelope.py](app/envelope.py) | Envelope builders, `ApiException` |
| [app/auth.py](app/auth.py) | `X-Api-Key` / bearer dependency |
| [app/params.py](app/params.py) | Date-range, paging and scope validation |
| [app/seed.py](app/seed.py) | Mock data generator |
