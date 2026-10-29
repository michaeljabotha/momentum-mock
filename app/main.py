"""Forcelink Partner Integration API - Momentum Dashboard POC (mock implementation)."""
import sqlite3

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .auth import require_api_key
from .config import (API_VERSION, DEFAULT_PER_PAGE, MAX_PER_PAGE,
                     SCOPED_ORG_UNIT_IDS, SCOPED_STORE_IDS)
from .db import get_conn
from .envelope import ApiException, failure, new_request_id, success
from .params import (check_enum, check_org_unit_scope, check_store_scope,
                     pagination_block, validate_paging, validate_range)

app = FastAPI(
    title="Forcelink Partner Integration API - Momentum Dashboard POC",
    version=API_VERSION,
    description="Mock implementation of the scoped, read-only partner API surface: "
                "time & attendance, proof-of-service, stock management, resources, "
                "escalations, QR customer feedback, and cleaner tracking (NFC / beacon).",
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = new_request_id()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", new_request_id())


@app.exception_handler(ApiException)
async def api_exception_handler(request: Request, exc: ApiException):
    return JSONResponse(
        status_code=exc.status_code,
        content=failure(exc.code, exc.message, _rid(request), exc.details),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    """Map FastAPI's own 422s (e.g. a missing dateFrom) onto the spec envelope."""
    details = [{
        "field": str(e["loc"][-1]),
        "code": e.get("type", "invalid"),
        "message": e.get("msg", "Invalid value."),
    } for e in exc.errors()]
    message = details[0]["message"] if details else "Invalid request parameters."
    return JSONResponse(
        status_code=400,
        content=failure("VALIDATION_ERROR", message, _rid(request), details),
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=failure("INTERNAL_ERROR", "Unhandled server error.", _rid(request)),
    )


# No ge/le here on purpose: bounds are enforced in params.validate_paging so the
# rejection comes back in this API's error envelope rather than FastAPI's 422 shape.
PageQ = Query(1, description="1-indexed page number.")
PerPageQ = Query(DEFAULT_PER_PAGE, alias="per_page",
                 description="Items per page. Default 50, max 500.")


def _paged(conn: sqlite3.Connection, count_sql: str, rows_sql: str,
           args: list, page: int, per_page: int):
    total = conn.execute(count_sql, args).fetchone()[0]
    rows = conn.execute(rows_sql, args + [per_page, (page - 1) * per_page]).fetchall()
    return rows, pagination_block(page, per_page, total)


# --------------------------------------------------------------------------- #
# Attendance
# --------------------------------------------------------------------------- #
@app.get("/attendance/shift-records", tags=["Attendance"],
         summary="Per-shift attendance records for a date range.",
         dependencies=[Depends(require_api_key)])
def get_shift_records(
    request: Request,
    dateFrom: str = Query(..., example="2026-09-01"),
    dateTo: str = Query(..., example="2026-09-30"),
    orgUnitId: int | None = Query(None, example=4021),
    employeeId: int | None = Query(None, example=88213),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    start, end = validate_range(dateFrom, dateTo)
    page, per_page = validate_paging(page, per_page)
    check_org_unit_scope(orgUnitId)

    where = ["a.shift_date BETWEEN ? AND ?", f"a.org_unit_id IN ({_ph(SCOPED_ORG_UNIT_IDS)})"]
    args: list = [start.isoformat(), end.isoformat(), *SCOPED_ORG_UNIT_IDS]
    if orgUnitId is not None:
        where.append("a.org_unit_id = ?")
        args.append(orgUnitId)
    if employeeId is not None:
        where.append("a.employee_id = ?")
        args.append(employeeId)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM shift_attendance a WHERE {clause}",
        f"""SELECT a.*, e.employee_code, o.type AS org_type, o.name AS org_name
            FROM shift_attendance a
            JOIN employee e ON e.id = a.employee_id
            JOIN org_unit o ON o.id = a.org_unit_id
            WHERE {clause}
            ORDER BY a.shift_date, a.org_unit_id, a.employee_id
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "employeeId": r["employee_id"],
        "employeeCode": r["employee_code"],
        "orgUnit": {"id": r["org_unit_id"], "type": r["org_type"], "name": r["org_name"]},
        "shiftDate": r["shift_date"],
        "clockInTimestamp": r["clock_in_timestamp"],
        "clockOutTimestamp": r["clock_out_timestamp"],
        "status": r["status"],
        "leaveStatus": r["leave_status"],
    } for r in rows]
    return success(data, pagination, _rid(request))


# --------------------------------------------------------------------------- #
# Proof of service
# --------------------------------------------------------------------------- #
@app.get("/service-proof/completed-work-orders", tags=["ServiceProof"],
         summary="Completed work orders for a date range, by site.",
         dependencies=[Depends(require_api_key)])
def get_completed_work_orders(
    request: Request,
    dateFrom: str = Query(..., example="2026-09-01"),
    dateTo: str = Query(..., example="2026-09-30"),
    orgUnitId: int | None = Query(None, example=4021),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    start, end = validate_range(dateFrom, dateTo)
    page, per_page = validate_paging(page, per_page)
    check_org_unit_scope(orgUnitId)

    where = ["w.status = 'COMPLETED'",
             "date(w.completed_date) BETWEEN ? AND ?",
             f"w.org_unit_id IN ({_ph(SCOPED_ORG_UNIT_IDS)})"]
    args: list = [start.isoformat(), end.isoformat(), *SCOPED_ORG_UNIT_IDS]
    if orgUnitId is not None:
        where.append("w.org_unit_id = ?")
        args.append(orgUnitId)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM work_order w WHERE {clause}",
        f"""SELECT w.*, o.type AS org_type, o.name AS org_name
            FROM work_order w
            JOIN org_unit o ON o.id = w.org_unit_id
            WHERE {clause}
            ORDER BY w.org_unit_id, w.completed_date
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "workOrderId": r["id"],
        "workOrderCode": r["work_order_code"],
        "orgUnit": {"id": r["org_unit_id"], "type": r["org_type"], "name": r["org_name"]},
        "status": r["status"],
        "workOrderType": r["work_order_type"],
        "description": r["description"],
        "createdDate": r["created_date"],
        "completedDate": r["completed_date"],
        "resourceId": r["resource_id"],
    } for r in rows]
    return success(data, pagination, _rid(request))


# --------------------------------------------------------------------------- #
# Stock
# --------------------------------------------------------------------------- #
@app.get("/stock/on-hand", tags=["Stock"],
         summary="Current on-hand stock quantities, by store.",
         dependencies=[Depends(require_api_key)])
def get_stock_on_hand(
    request: Request,
    storeId: int | None = Query(None, example=12),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    page, per_page = validate_paging(page, per_page)
    check_store_scope(storeId)

    where = [f"s.store_id IN ({_ph(SCOPED_STORE_IDS)})"]
    args: list = [*SCOPED_STORE_IDS]
    if storeId is not None:
        where.append("s.store_id = ?")
        args.append(storeId)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM stock_on_hand s WHERE {clause}",
        f"""SELECT s.*, st.name AS store_name, m.material_code,
                   m.material_description, m.unit_of_measure
            FROM stock_on_hand s
            JOIN store st ON st.id = s.store_id
            JOIN material m ON m.id = s.material_id
            WHERE {clause}
            ORDER BY s.store_id, m.material_code
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "store": {"id": r["store_id"], "name": r["store_name"]},
        "materialId": r["material_id"],
        "materialCode": r["material_code"],
        "materialDescription": r["material_description"],
        "quantityOnHand": r["quantity_on_hand"],
        "unitOfMeasure": r["unit_of_measure"],
        "asOfTimestamp": r["as_of_timestamp"],
    } for r in rows]
    return success(data, pagination, _rid(request))


@app.get("/stock/movements", tags=["Stock"],
         summary="Stock movements/transactions for a date range, by store.",
         dependencies=[Depends(require_api_key)])
def get_stock_movements(
    request: Request,
    dateFrom: str = Query(..., example="2026-09-01"),
    dateTo: str = Query(..., example="2026-09-30"),
    storeId: int | None = Query(None, example=12),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    start, end = validate_range(dateFrom, dateTo)
    page, per_page = validate_paging(page, per_page)
    check_store_scope(storeId)

    where = ["date(mv.transaction_timestamp) BETWEEN ? AND ?",
             f"mv.store_id IN ({_ph(SCOPED_STORE_IDS)})"]
    args: list = [start.isoformat(), end.isoformat(), *SCOPED_STORE_IDS]
    if storeId is not None:
        where.append("mv.store_id = ?")
        args.append(storeId)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM stock_movement mv WHERE {clause}",
        f"""SELECT mv.*, st.name AS store_name, m.material_code, m.material_description
            FROM stock_movement mv
            JOIN store st ON st.id = mv.store_id
            JOIN material m ON m.id = mv.material_id
            WHERE {clause}
            ORDER BY mv.transaction_timestamp, mv.id
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "movementId": r["id"],
        "store": {"id": r["store_id"], "name": r["store_name"]},
        "materialId": r["material_id"],
        "materialCode": r["material_code"],
        "materialDescription": r["material_description"],
        "transactionType": r["transaction_type"],
        "quantity": r["quantity"],
        "transactionTimestamp": r["transaction_timestamp"],
        "referenceDocument": r["reference_document"],
    } for r in rows]
    return success(data, pagination, _rid(request))


# --------------------------------------------------------------------------- #
# Resources
# --------------------------------------------------------------------------- #
RESOURCE_ROLES = ["CLEANER", "SUPERVISOR", "SITE_MANAGER"]


@app.get("/resources", tags=["Resources"],
         summary="Resource (employee / user) lookup, including supervisor hierarchy.",
         dependencies=[Depends(require_api_key)])
def get_resources(
    request: Request,
    orgUnitId: int | None = Query(None, example=4021),
    resourceId: int | None = Query(None, example=88213),
    role: str | None = Query(None, example="SUPERVISOR",
                             description="CLEANER, SUPERVISOR or SITE_MANAGER."),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    page, per_page = validate_paging(page, per_page)
    check_org_unit_scope(orgUnitId)
    check_enum(role, "role", RESOURCE_ROLES)

    where = [f"e.org_unit_id IN ({_ph(SCOPED_ORG_UNIT_IDS)})"]
    args: list = [*SCOPED_ORG_UNIT_IDS]
    if orgUnitId is not None:
        where.append("e.org_unit_id = ?")
        args.append(orgUnitId)
    if resourceId is not None:
        where.append("e.id = ?")
        args.append(resourceId)
    if role is not None:
        where.append("e.role = ?")
        args.append(role)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM employee e WHERE {clause}",
        f"""SELECT e.*, o.type AS org_type, o.name AS org_name
            FROM employee e
            JOIN org_unit o ON o.id = e.org_unit_id
            WHERE {clause}
            ORDER BY e.org_unit_id, e.id
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "resourceId": r["id"],
        "resourceCode": r["employee_code"],
        "name": r["name"],
        "role": r["role"],
        "orgUnit": {"id": r["org_unit_id"], "type": r["org_type"], "name": r["org_name"]},
        "supervisorId": r["supervisor_id"],
        "active": bool(r["active"]),
    } for r in rows]
    return success(data, pagination, _rid(request))


# --------------------------------------------------------------------------- #
# Escalations
# --------------------------------------------------------------------------- #
ESCALATION_STATUSES = ["OPEN", "ACKNOWLEDGED", "RESOLVED"]


@app.get("/escalations", tags=["Escalations"],
         summary="Escalations raised in a date range, by site.",
         dependencies=[Depends(require_api_key)])
def get_escalations(
    request: Request,
    dateFrom: str = Query(..., example="2026-09-01"),
    dateTo: str = Query(..., example="2026-09-30"),
    orgUnitId: int | None = Query(None, example=4021),
    status: str | None = Query(None, example="OPEN",
                               description="OPEN, ACKNOWLEDGED or RESOLVED."),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    start, end = validate_range(dateFrom, dateTo)
    page, per_page = validate_paging(page, per_page)
    check_org_unit_scope(orgUnitId)
    check_enum(status, "status", ESCALATION_STATUSES)

    where = ["date(x.created_date) BETWEEN ? AND ?",
             f"x.org_unit_id IN ({_ph(SCOPED_ORG_UNIT_IDS)})"]
    args: list = [start.isoformat(), end.isoformat(), *SCOPED_ORG_UNIT_IDS]
    if orgUnitId is not None:
        where.append("x.org_unit_id = ?")
        args.append(orgUnitId)
    if status is not None:
        where.append("x.status = ?")
        args.append(status)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM escalation x WHERE {clause}",
        f"""SELECT x.*, o.type AS org_type, o.name AS org_name, l.name AS location_name
            FROM escalation x
            JOIN org_unit o ON o.id = x.org_unit_id
            LEFT JOIN location l ON l.id = x.location_id
            WHERE {clause}
            ORDER BY x.created_date, x.id
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "escalationId": r["id"],
        "escalationCode": r["escalation_code"],
        "orgUnit": {"id": r["org_unit_id"], "type": r["org_type"], "name": r["org_name"]},
        "location": _location(r),
        "source": r["source"],
        "feedbackId": r["feedback_id"],
        "workOrderId": r["work_order_id"],
        "category": r["category"],
        "priority": r["priority"],
        "level": r["level"],
        "status": r["status"],
        "raisedByResourceId": r["raised_by_resource_id"],
        "assignedToResourceId": r["assigned_to_resource_id"],
        "createdDate": r["created_date"],
        "acknowledgedDate": r["acknowledged_date"],
        "resolvedDate": r["resolved_date"],
    } for r in rows]
    return success(data, pagination, _rid(request))


# --------------------------------------------------------------------------- #
# Customer feedback (QR code)
# --------------------------------------------------------------------------- #
@app.get("/customer-feedback/qr-responses", tags=["CustomerFeedback"],
         summary="QR-code customer feedback submissions for a date range, by site.",
         dependencies=[Depends(require_api_key)])
def get_qr_responses(
    request: Request,
    dateFrom: str = Query(..., example="2026-09-01"),
    dateTo: str = Query(..., example="2026-09-30"),
    orgUnitId: int | None = Query(None, example=4021),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    start, end = validate_range(dateFrom, dateTo)
    page, per_page = validate_paging(page, per_page)
    check_org_unit_scope(orgUnitId)

    where = ["date(f.submitted_timestamp) BETWEEN ? AND ?",
             f"f.org_unit_id IN ({_ph(SCOPED_ORG_UNIT_IDS)})"]
    args: list = [start.isoformat(), end.isoformat(), *SCOPED_ORG_UNIT_IDS]
    if orgUnitId is not None:
        where.append("f.org_unit_id = ?")
        args.append(orgUnitId)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM customer_feedback f WHERE {clause}",
        f"""SELECT f.*, o.type AS org_type, o.name AS org_name, l.name AS location_name
            FROM customer_feedback f
            JOIN org_unit o ON o.id = f.org_unit_id
            JOIN location l ON l.id = f.location_id
            WHERE {clause}
            ORDER BY f.submitted_timestamp, f.id
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "feedbackId": r["id"],
        "orgUnit": {"id": r["org_unit_id"], "type": r["org_type"], "name": r["org_name"]},
        "location": _location(r),
        "qrCodeId": r["qr_code_id"],
        "rating": r["rating"],
        "category": r["category"],
        "comment": r["comment"],
        "submittedTimestamp": r["submitted_timestamp"],
        "escalationId": r["escalation_id"],
    } for r in rows]
    return success(data, pagination, _rid(request))


# --------------------------------------------------------------------------- #
# Cleaner tracking (NFC / beacon)
# --------------------------------------------------------------------------- #
@app.get("/cleaner-tracking/check-ins", tags=["CleanerTracking"],
         summary="Cleaner NFC tag scans and beacon check-ins for a date range, by site.",
         dependencies=[Depends(require_api_key)])
def get_cleaner_check_ins(
    request: Request,
    dateFrom: str = Query(..., example="2026-09-01"),
    dateTo: str = Query(..., example="2026-09-30"),
    orgUnitId: int | None = Query(None, example=4021),
    resourceId: int | None = Query(None, example=88213),
    page: int = PageQ,
    per_page: int = PerPageQ,
    conn: sqlite3.Connection = Depends(get_conn),
):
    start, end = validate_range(dateFrom, dateTo)
    page, per_page = validate_paging(page, per_page)
    check_org_unit_scope(orgUnitId)

    where = ["date(c.check_in_timestamp) BETWEEN ? AND ?",
             f"c.org_unit_id IN ({_ph(SCOPED_ORG_UNIT_IDS)})"]
    args: list = [start.isoformat(), end.isoformat(), *SCOPED_ORG_UNIT_IDS]
    if orgUnitId is not None:
        where.append("c.org_unit_id = ?")
        args.append(orgUnitId)
    if resourceId is not None:
        where.append("c.resource_id = ?")
        args.append(resourceId)
    clause = " AND ".join(where)

    rows, pagination = _paged(
        conn,
        f"SELECT COUNT(*) FROM cleaner_check_in c WHERE {clause}",
        f"""SELECT c.*, o.type AS org_type, o.name AS org_name, l.name AS location_name
            FROM cleaner_check_in c
            JOIN org_unit o ON o.id = c.org_unit_id
            JOIN location l ON l.id = c.location_id
            WHERE {clause}
            ORDER BY c.check_in_timestamp, c.id
            LIMIT ? OFFSET ?""",
        args, page, per_page)

    data = [{
        "checkInId": r["id"],
        "resourceId": r["resource_id"],
        "orgUnit": {"id": r["org_unit_id"], "type": r["org_type"], "name": r["org_name"]},
        "location": _location(r),
        "tagId": r["tag_id"],
        "method": r["method"],
        "checkInTimestamp": r["check_in_timestamp"],
        "checkOutTimestamp": r["check_out_timestamp"],
    } for r in rows]
    return success(data, pagination, _rid(request))


def _location(r: sqlite3.Row) -> dict | None:
    if r["location_id"] is None:
        return None
    return {"id": r["location_id"], "name": r["location_name"]}


def _ph(values: list) -> str:
    return ",".join("?" for _ in values)
