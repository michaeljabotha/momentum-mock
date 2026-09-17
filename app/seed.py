"""Generate a realistic mock dataset into SQLite.

Run with:  python -m app.seed  [--reset]
"""
import argparse
import random
from datetime import date, datetime, time, timedelta, timezone

from .config import DB_PATH, SCOPED_ORG_UNIT_IDS, SCOPED_STORE_IDS
from .db import connect, init_schema

RNG = random.Random(20260917)

# Data spans roughly a year back from "today" in the POC timeline.
TODAY = date(2026, 9, 17)
HISTORY_DAYS = 365

SITES = [
    (4021, "Depot - Bellville"),
    (4022, "Depot - Montague Gardens"),
    (4023, "Depot - Epping"),
    (4024, "Regional Hub - Paarl"),
    (4025, "Regional Hub - Somerset West"),
]
# One out-of-scope site, so FORBIDDEN/scoping behaviour is exercisable.
UNSCOPED_SITES = [(4099, "Depot - Port Elizabeth (out of partner scope)")]

STORES = [
    (12, "Main Store - Bellville", 4021),
    (13, "Main Store - Montague Gardens", 4022),
    (14, "Main Store - Epping", 4023),
    (15, "Regional Store - Paarl", 4024),
    (99, "Main Store - Port Elizabeth (out of partner scope)", 4099),
]

FIRST_NAMES = ["Thabo", "Ayesha", "Johan", "Nomsa", "Pieter", "Lerato", "Riaan", "Zanele",
               "Sipho", "Marieke", "Dumisani", "Chantal", "Kagiso", "Andre", "Nandi",
               "Willem", "Refilwe", "Shaun", "Palesa", "Gerhard", "Bongani", "Elsabe"]
LAST_NAMES = ["Nkosi", "Petersen", "van Wyk", "Dlamini", "Botha", "Mahlangu", "Adams",
              "Khumalo", "du Plessis", "Jacobs", "Mokoena", "Steyn", "Ndlovu", "Fourie",
              "Tshabalala", "Isaacs", "Naidoo", "Coetzee", "Mbeki", "Erasmus"]

WORK_ORDER_TYPES = [
    "Corrective Maintenance", "Preventative Maintenance", "Installation",
    "Inspection", "Meter Replacement", "Emergency Callout", "Site Survey",
]
WO_DESCRIPTIONS = [
    "Replaced faulty isolator on distribution board",
    "Quarterly preventative service on pump station",
    "Installed replacement water meter and commissioned",
    "Repaired burst 25mm supply line",
    "Cleared blocked drainage sump",
    "Routine inspection of standby generator",
    "Replaced corroded valve assembly",
    "Recalibrated flow meter after fault report",
    "Emergency repair to ruptured main after third-party damage",
    "Reinstated service following planned shutdown",
    "Replaced damaged manhole cover and surround",
    "Serviced compressor and replaced filters",
]

MATERIALS = [
    ("MAT-00231", "Coupling, 25mm PVC", "EA"),
    ("MAT-00232", "Coupling, 50mm PVC", "EA"),
    ("MAT-00310", "Pipe, 25mm HDPE", "M"),
    ("MAT-00311", "Pipe, 50mm HDPE", "M"),
    ("MAT-00415", "Ball Valve, 25mm Brass", "EA"),
    ("MAT-00416", "Gate Valve, 50mm", "EA"),
    ("MAT-00502", "Water Meter, 15mm Class B", "EA"),
    ("MAT-00503", "Water Meter, 20mm Class B", "EA"),
    ("MAT-00610", "Cable, 2.5mm2 Twin & Earth", "M"),
    ("MAT-00611", "Cable, 4mm2 Twin & Earth", "M"),
    ("MAT-00705", "Circuit Breaker, 20A Single Pole", "EA"),
    ("MAT-00706", "Circuit Breaker, 60A Triple Pole", "EA"),
    ("MAT-00812", "Isolator, 30A Weatherproof", "EA"),
    ("MAT-00901", "Thread Sealant Tape, 12mm", "ROLL"),
    ("MAT-00902", "Silicone Sealant, Clear 300ml", "TUBE"),
    ("MAT-01005", "Manhole Cover, Light Duty", "EA"),
    ("MAT-01110", "Bolt Set, M12 Galvanised", "SET"),
    ("MAT-01201", "Air Filter, Compressor Type B", "EA"),
    ("MAT-01202", "Oil, Hydraulic ISO 46", "L"),
    ("MAT-01305", "Gasket, 50mm Rubber", "EA"),
    ("MAT-01402", "Pressure Gauge, 0-16 bar", "EA"),
    ("MAT-01501", "Safety Gloves, Nitrile Coated", "PAIR"),
    ("MAT-01502", "Hard Hat, White", "EA"),
    ("MAT-01601", "Warning Tape, 100m Roll", "ROLL"),
]

MOVEMENT_TYPES = ["RECEIPT", "ISSUE", "TRANSFER_IN", "TRANSFER_OUT", "ADJUSTMENT"]
MOVEMENT_WEIGHTS = [18, 55, 8, 8, 11]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=timezone.utc)


def seed(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = connect()
    init_schema(conn)
    cur = conn.cursor()

    if cur.execute("SELECT COUNT(*) FROM shift_attendance").fetchone()[0]:
        print(f"{DB_PATH} already seeded - pass --reset to rebuild.")
        conn.close()
        return

    all_sites = SITES + UNSCOPED_SITES
    cur.executemany("INSERT OR REPLACE INTO org_unit (id, type, name) VALUES (?, 'SITE', ?)",
                    all_sites)
    cur.executemany("INSERT OR REPLACE INTO store (id, name, org_unit_id) VALUES (?, ?, ?)",
                    STORES)

    # ---- Employees: ~22 per site -----------------------------------------
    employees: list[tuple[int, str, str, int]] = []
    emp_id = 88201
    for site_id, _ in all_sites:
        for _ in range(RNG.randint(20, 24)):
            name = f"{RNG.choice(FIRST_NAMES)} {RNG.choice(LAST_NAMES)}"
            employees.append((emp_id, f"EMP{emp_id}", name, site_id))
            emp_id += 1
    cur.executemany(
        "INSERT OR REPLACE INTO employee (id, employee_code, name, org_unit_id) "
        "VALUES (?, ?, ?, ?)", employees)

    # ---- Materials --------------------------------------------------------
    materials = [(9000 + i, code, desc, uom)
                 for i, (code, desc, uom) in enumerate(MATERIALS, start=1)]
    cur.executemany(
        "INSERT OR REPLACE INTO material "
        "(id, material_code, material_description, unit_of_measure) VALUES (?, ?, ?, ?)",
        materials)

    # ---- Attendance: one row per employee per working day -----------------
    attendance = []
    start_day = TODAY - timedelta(days=HISTORY_DAYS)
    for offset in range(HISTORY_DAYS + 1):
        day = start_day + timedelta(days=offset)
        if day.weekday() >= 5:            # weekdays only
            continue
        for e_id, _code, _name, site_id in employees:
            roll = RNG.random()
            if roll < 0.04:               # on approved/pending leave
                status, leave = "ON_LEAVE", RNG.choices(
                    ["APPROVED", "PENDING"], weights=[85, 15])[0]
                cin = cout = None
            elif roll < 0.07:             # no-show
                status, leave = "ABSENT", RNG.choices(
                    ["NONE", "REJECTED"], weights=[80, 20])[0]
                cin = cout = None
            else:
                late_by = RNG.choices([0, RNG.randint(6, 45)], weights=[82, 18])[0]
                status = "LATE" if late_by > 5 else "ON_TIME"
                leave = "NONE"
                shift_start = at(day, 7, 0) + timedelta(minutes=late_by)
                cin = iso(shift_start - timedelta(minutes=RNG.randint(0, 12)))
                cout = iso(at(day, 16, 0) + timedelta(minutes=RNG.randint(-20, 70)))
            attendance.append((e_id, site_id, day.isoformat(), cin, cout, status, leave))
    cur.executemany(
        "INSERT INTO shift_attendance (employee_id, org_unit_id, shift_date, "
        "clock_in_timestamp, clock_out_timestamp, status, leave_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", attendance)

    # ---- Work orders ------------------------------------------------------
    work_orders = []
    wo_id = 104001
    emps_by_site: dict[int, list[int]] = {}
    for e_id, _c, _n, site_id in employees:
        emps_by_site.setdefault(site_id, []).append(e_id)

    for offset in range(HISTORY_DAYS + 1):
        day = start_day + timedelta(days=offset)
        weekday = day.weekday() < 5
        for site_id, _ in all_sites:
            count = RNG.randint(4, 12) if weekday else RNG.randint(0, 3)
            for _ in range(count):
                completed = at(day, RNG.randint(7, 17), RNG.choice([0, 15, 30, 45]))
                resource = RNG.choice(emps_by_site[site_id])
                work_orders.append((
                    wo_id, f"WO-{day.year}-{wo_id}", site_id, "COMPLETED",
                    RNG.choice(WORK_ORDER_TYPES), RNG.choice(WO_DESCRIPTIONS),
                    iso(completed),
                    resource if RNG.random() > 0.05 else None,
                ))
                wo_id += 1
        # A few still-open orders, so the COMPLETED filter is doing real work.
        if weekday and RNG.random() < 0.5:
            site_id = RNG.choice(all_sites)[0]
            work_orders.append((
                wo_id, f"WO-{day.year}-{wo_id}", site_id, "IN_PROGRESS",
                RNG.choice(WORK_ORDER_TYPES), RNG.choice(WO_DESCRIPTIONS), None, None))
            wo_id += 1
    cur.executemany(
        "INSERT OR REPLACE INTO work_order (id, work_order_code, org_unit_id, status, "
        "work_order_type, description, completed_date, resource_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", work_orders)

    wo_codes_by_site: dict[int, list[str]] = {}
    for w in work_orders:
        wo_codes_by_site.setdefault(w[2], []).append(w[1])

    # ---- Stock movements, then on-hand derived from them ------------------
    movements = []
    mv_id = 500001
    store_ids = [s[0] for s in STORES]
    store_site = {s[0]: s[2] for s in STORES}
    for offset in range(HISTORY_DAYS + 1):
        day = start_day + timedelta(days=offset)
        if day.weekday() >= 5 and RNG.random() < 0.7:
            continue
        for store_id in store_ids:
            for _ in range(RNG.randint(3, 14)):
                m_id, m_code, _desc, _uom = RNG.choice(materials)
                ttype = RNG.choices(MOVEMENT_TYPES, weights=MOVEMENT_WEIGHTS)[0]
                # Quantity ranges are tuned so inflows roughly offset outflows over
                # the full history - otherwise derived on-hand drifts to zero.
                if ttype == "RECEIPT":
                    qty = float(RNG.randint(10, 70))
                elif ttype == "TRANSFER_IN":
                    qty = float(RNG.randint(2, 22))
                elif ttype in ("ISSUE", "TRANSFER_OUT"):
                    qty = -float(RNG.randint(1, 25))
                else:  # ADJUSTMENT - small stock-take correction either way
                    qty = float(RNG.randint(-8, 8)) or 1.0
                if ttype == "ISSUE":
                    ref = RNG.choice(wo_codes_by_site[store_site[store_id]])
                elif ttype == "RECEIPT":
                    ref = f"GRN-{day.year}-{RNG.randint(10000, 99999)}"
                elif ttype in ("TRANSFER_IN", "TRANSFER_OUT"):
                    ref = f"TRF-{day.year}-{RNG.randint(1000, 9999)}"
                else:
                    ref = None
                ts = at(day, RNG.randint(6, 18), RNG.choice([5, 20, 35, 50]))
                movements.append((mv_id, store_id, m_id, ttype, qty, iso(ts), ref))
                mv_id += 1
    cur.executemany(
        "INSERT OR REPLACE INTO stock_movement (id, store_id, material_id, "
        "transaction_type, quantity, transaction_timestamp, reference_document) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", movements)

    # On-hand = opening balance + net movements, floored at 0.
    as_of = iso(at(TODAY, 6, 0))
    on_hand = []
    net: dict[tuple[int, int], float] = {}
    for _id, store_id, m_id, _t, qty, _ts, _r in movements:
        net[(store_id, m_id)] = net.get((store_id, m_id), 0.0) + qty
    for store_id in store_ids:
        for m_id, _code, _desc, _uom in materials:
            opening = float(RNG.randint(150, 900))
            qty = max(0.0, round(opening + net.get((store_id, m_id), 0.0), 2))
            on_hand.append((store_id, m_id, qty, as_of))
    cur.executemany(
        "INSERT OR REPLACE INTO stock_on_hand (store_id, material_id, quantity_on_hand, "
        "as_of_timestamp) VALUES (?, ?, ?, ?)", on_hand)

    conn.commit()

    print(f"Seeded {DB_PATH}")
    for table in ("org_unit", "store", "employee", "material", "shift_attendance",
                  "work_order", "stock_on_hand", "stock_movement"):
        n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<18} {n:>7,}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed the mock Forcelink partner database.")
    ap.add_argument("--reset", action="store_true", help="Delete and rebuild the database.")
    seed(**vars(ap.parse_args()))
