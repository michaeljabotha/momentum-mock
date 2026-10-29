"""SQLite access helpers."""
import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS org_unit (
    id          INTEGER PRIMARY KEY,
    type        TEXT NOT NULL DEFAULT 'SITE',
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS store (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    org_unit_id INTEGER REFERENCES org_unit(id)
);

CREATE TABLE IF NOT EXISTS employee (
    id            INTEGER PRIMARY KEY,
    employee_code TEXT NOT NULL,
    name          TEXT NOT NULL,
    org_unit_id   INTEGER NOT NULL REFERENCES org_unit(id),
    role          TEXT NOT NULL DEFAULT 'CLEANER',
    supervisor_id INTEGER REFERENCES employee(id),
    active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS location (
    id          INTEGER PRIMARY KEY,
    org_unit_id INTEGER NOT NULL REFERENCES org_unit(id),
    name        TEXT NOT NULL,
    qr_code_id  TEXT NOT NULL,
    tag_id      TEXT NOT NULL,
    tag_type    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS material (
    id                   INTEGER PRIMARY KEY,
    material_code        TEXT NOT NULL,
    material_description TEXT NOT NULL,
    unit_of_measure      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shift_attendance (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id         INTEGER NOT NULL REFERENCES employee(id),
    org_unit_id         INTEGER NOT NULL REFERENCES org_unit(id),
    shift_date          TEXT NOT NULL,
    clock_in_timestamp  TEXT,
    clock_out_timestamp TEXT,
    status              TEXT NOT NULL,
    leave_status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_order (
    id             INTEGER PRIMARY KEY,
    work_order_code TEXT NOT NULL,
    org_unit_id    INTEGER NOT NULL REFERENCES org_unit(id),
    status         TEXT NOT NULL,
    work_order_type TEXT NOT NULL,
    description    TEXT NOT NULL,
    created_date   TEXT NOT NULL,
    completed_date TEXT,
    resource_id    INTEGER
);

CREATE TABLE IF NOT EXISTS stock_on_hand (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id         INTEGER NOT NULL REFERENCES store(id),
    material_id      INTEGER NOT NULL REFERENCES material(id),
    quantity_on_hand REAL NOT NULL,
    as_of_timestamp  TEXT NOT NULL,
    UNIQUE (store_id, material_id)
);

CREATE TABLE IF NOT EXISTS stock_movement (
    id                    INTEGER PRIMARY KEY,
    store_id              INTEGER NOT NULL REFERENCES store(id),
    material_id           INTEGER NOT NULL REFERENCES material(id),
    transaction_type      TEXT NOT NULL,
    quantity              REAL NOT NULL,
    transaction_timestamp TEXT NOT NULL,
    reference_document    TEXT
);

CREATE TABLE IF NOT EXISTS customer_feedback (
    id                  INTEGER PRIMARY KEY,
    org_unit_id         INTEGER NOT NULL REFERENCES org_unit(id),
    location_id         INTEGER NOT NULL REFERENCES location(id),
    qr_code_id          TEXT NOT NULL,
    rating              INTEGER NOT NULL,
    category            TEXT NOT NULL,
    comment             TEXT,
    submitted_timestamp TEXT NOT NULL,
    escalation_id       INTEGER REFERENCES escalation(id)
);

CREATE TABLE IF NOT EXISTS escalation (
    id                      INTEGER PRIMARY KEY,
    escalation_code         TEXT NOT NULL,
    org_unit_id             INTEGER NOT NULL REFERENCES org_unit(id),
    location_id             INTEGER REFERENCES location(id),
    source                  TEXT NOT NULL,
    feedback_id             INTEGER REFERENCES customer_feedback(id),
    work_order_id           INTEGER REFERENCES work_order(id),
    category                TEXT NOT NULL,
    priority                TEXT NOT NULL,
    level                   INTEGER NOT NULL,
    status                  TEXT NOT NULL,
    raised_by_resource_id   INTEGER REFERENCES employee(id),
    assigned_to_resource_id INTEGER REFERENCES employee(id),
    created_date            TEXT NOT NULL,
    acknowledged_date       TEXT,
    resolved_date           TEXT
);

CREATE TABLE IF NOT EXISTS cleaner_check_in (
    id                  INTEGER PRIMARY KEY,
    resource_id         INTEGER NOT NULL REFERENCES employee(id),
    org_unit_id         INTEGER NOT NULL REFERENCES org_unit(id),
    location_id         INTEGER NOT NULL REFERENCES location(id),
    tag_id              TEXT NOT NULL,
    method              TEXT NOT NULL,
    check_in_timestamp  TEXT NOT NULL,
    check_out_timestamp TEXT
);

CREATE INDEX IF NOT EXISTS ix_att_date ON shift_attendance (shift_date);
CREATE INDEX IF NOT EXISTS ix_att_org  ON shift_attendance (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_att_emp  ON shift_attendance (employee_id);
CREATE INDEX IF NOT EXISTS ix_wo_done  ON work_order (completed_date);
CREATE INDEX IF NOT EXISTS ix_wo_org   ON work_order (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_mv_ts    ON stock_movement (transaction_timestamp);
CREATE INDEX IF NOT EXISTS ix_mv_store ON stock_movement (store_id);
CREATE INDEX IF NOT EXISTS ix_emp_org  ON employee (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_fb_ts    ON customer_feedback (submitted_timestamp);
CREATE INDEX IF NOT EXISTS ix_fb_org   ON customer_feedback (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_esc_ts   ON escalation (created_date);
CREATE INDEX IF NOT EXISTS ix_esc_org  ON escalation (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_ci_ts    ON cleaner_check_in (check_in_timestamp);
CREATE INDEX IF NOT EXISTS ix_ci_org   ON cleaner_check_in (org_unit_id);
CREATE INDEX IF NOT EXISTS ix_ci_res   ON cleaner_check_in (resource_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_conn():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
