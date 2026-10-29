"""Generate a realistic mock dataset into SQLite.

Run with:  python -m app.seed  [--reset]
"""
import argparse
import random
import sqlite3
from datetime import date, datetime, time, timedelta, timezone

from .config import DB_PATH
from .db import connect, init_schema

RNG = random.Random(20260917)

# Data spans roughly a year back from "today" in the POC timeline.
TODAY = date(2026, 9, 17)
HISTORY_DAYS = 365

SITES = [
    (4021, "Head Office - Centurion"),
    (4022, "Parktown Campus - Johannesburg"),
    (4023, "Durbanville Office - Cape Town"),
    (4024, "Umhlanga Ridge Office - Durban"),
    (4025, "Menlyn Office - Pretoria"),
]
# One out-of-scope site, so FORBIDDEN/scoping behaviour is exercisable.
UNSCOPED_SITES = [(4099, "Gqeberha Office (out of partner scope)")]

STORES = [
    (12, "Cleaning Store - Centurion", 4021),
    (13, "Cleaning Store - Parktown", 4022),
    (14, "Cleaning Store - Durbanville", 4023),
    (15, "Cleaning Store - Umhlanga", 4024),
    (99, "Cleaning Store - Gqeberha (out of partner scope)", 4099),
]

FIRST_NAMES = ["Thabo", "Ayesha", "Johan", "Nomsa", "Pieter", "Lerato", "Riaan", "Zanele",
               "Sipho", "Marieke", "Dumisani", "Chantal", "Kagiso", "Andre", "Nandi",
               "Willem", "Refilwe", "Shaun", "Palesa", "Gerhard", "Bongani", "Elsabe"]
LAST_NAMES = ["Nkosi", "Petersen", "van Wyk", "Dlamini", "Botha", "Mahlangu", "Adams",
              "Khumalo", "du Plessis", "Jacobs", "Mokoena", "Steyn", "Ndlovu", "Fourie",
              "Tshabalala", "Isaacs", "Naidoo", "Coetzee", "Mbeki", "Erasmus"]

# Reactive work is raised and closed within hours; scheduled work sits in the
# queue for longer. Drives created -> completed durations.
REACTIVE_WO_TYPES = ["Spill Response", "Washroom Replenishment", "Waste Removal"]
SCHEDULED_WO_TYPES = ["Scheduled Clean", "Deep Clean", "Window Cleaning",
                      "Carpet Shampoo", "Hygiene Service"]
WORK_ORDER_TYPES = REACTIVE_WO_TYPES + SCHEDULED_WO_TYPES
WO_DESCRIPTIONS = {
    "Spill Response": ["Cleaned coffee spill in open-plan office",
                       "Mopped water leak at lift lobby",
                       "Cleared broken glass and spill in canteen"],
    "Washroom Replenishment": ["Replenished toilet paper and hand towels",
                               "Refilled hand soap and sanitiser dispensers",
                               "Restocked sanitary bins and air fresheners"],
    "Waste Removal": ["Emptied overflowing bins and replaced liners",
                      "Removed recycling to central refuse area"],
    "Scheduled Clean": ["Daily clean of washrooms and touch points",
                        "Routine office clean - desks, floors and bins"],
    "Deep Clean": ["Quarterly deep clean of canteen and kitchenettes",
                   "Deep clean and descale of washroom fixtures"],
    "Window Cleaning": ["Cleaned internal glass partitions",
                        "Cleaned ground-floor façade windows"],
    "Carpet Shampoo": ["Shampooed boardroom carpets",
                       "Spot-treated and shampooed reception carpets"],
    "Hygiene Service": ["Serviced sanitary bins and hygiene units",
                        "Replaced urinal screens and sanitiser cartridges"],
}

MATERIALS = [
    ("MAT-00231", "Toilet Paper, 2-Ply 48-Roll Pack", "PACK"),
    ("MAT-00232", "Hand Towels, Z-Fold 20-Pack", "PACK"),
    ("MAT-00310", "Hand Soap Refill, 5L", "EA"),
    ("MAT-00311", "Hand Sanitiser Cartridge, 1L", "EA"),
    ("MAT-00415", "Bleach, Thick 5L", "EA"),
    ("MAT-00416", "Multi-Surface Cleaner, 5L", "EA"),
    ("MAT-00502", "Floor Cleaner Concentrate, 5L", "EA"),
    ("MAT-00503", "Glass Cleaner, 750ml Trigger", "EA"),
    ("MAT-00610", "Refuse Bags, Black 750x950", "ROLL"),
    ("MAT-00611", "Bin Liners, Clear Small", "ROLL"),
    ("MAT-00705", "Microfibre Cloths, 10-Pack", "PACK"),
    ("MAT-00706", "Mop Head, Cotton 400g", "EA"),
    ("MAT-00812", "Air Freshener Refill, Aerosol", "EA"),
    ("MAT-00901", "Urinal Screen, Deodorising", "EA"),
    ("MAT-00902", "Toilet Bowl Cleaner, 750ml", "EA"),
    ("MAT-01005", "Sanitary Bin Liners, 100-Pack", "PACK"),
    ("MAT-01110", "Dishwashing Liquid, 5L", "EA"),
    ("MAT-01201", "Scouring Pads, 10-Pack", "PACK"),
    ("MAT-01202", "Carpet Shampoo, 5L", "EA"),
    ("MAT-01305", "Furniture Polish, 400ml", "EA"),
    ("MAT-01402", "Disinfectant, Quaternary 5L", "EA"),
    ("MAT-01501", "Gloves, Nitrile Disposable 100", "BOX"),
    ("MAT-01502", "Wet Floor Sign", "EA"),
    ("MAT-01601", "Squeegee, 450mm", "EA"),
]

MOVEMENT_TYPES = ["RECEIPT", "ISSUE", "TRANSFER_IN", "TRANSFER_OUT", "ADJUSTMENT"]
MOVEMENT_WEIGHTS = [18, 55, 8, 8, 11]

# (name, feedback weight). Washrooms and canteens attract most QR scans.
LOCATION_POOL = [
    ("Ground Floor - Reception", 2), ("Ground Floor - Main Entrance", 1),
    ("Ground Floor - Ladies Restroom", 4), ("Ground Floor - Gents Restroom", 4),
    ("Ground Floor - Accessible Restroom", 2), ("Level 1 - Ladies Restroom", 4),
    ("Level 1 - Gents Restroom", 4), ("Level 1 - Open Plan Office", 1),
    ("Level 2 - Ladies Restroom", 3), ("Level 2 - Gents Restroom", 3),
    ("Level 2 - Boardroom", 1), ("Level 3 - Kitchenette", 2), ("Canteen", 4),
    ("Lift Lobby", 1), ("Basement Parking", 1), ("Gym Change Rooms", 2),
]

FEEDBACK_CATEGORIES = ["CLEANLINESS", "CONSUMABLES", "ODOUR", "SPILL",
                       "BROKEN_FIXTURE", "GENERAL"]
FEEDBACK_COMMENTS = {
    "good": ["Spotless, thank you!", "Always clean and well stocked.",
             "Great job by the cleaning team.", "Smells fresh."],
    "CLEANLINESS": ["Floor is dirty.", "Basins not cleaned.", "Toilets need attention."],
    "CONSUMABLES": ["No toilet paper.", "Soap dispenser empty.", "No hand towels."],
    "ODOUR": ["Bad smell in here.", "Needs air freshener urgently."],
    "SPILL": ["Water all over the floor.", "Something spilled near the entrance."],
    "BROKEN_FIXTURE": ["Tap is leaking.", "Hand dryer not working.", "Toilet won't flush."],
    "GENERAL": ["Bins are overflowing.", "Please check this area more often."],
}

ESCALATION_SOURCES_OTHER = ["SUPERVISOR", "CLIENT_REQUEST"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=timezone.utc)


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _schema_is_current() -> bool:
    """A database seeded before the schema grew new tables/columns can't be reused."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(work_order)")}
        return "created_date" in cols
    finally:
        conn.close()


def seed(reset: bool = False) -> None:
    if DB_PATH.exists() and not reset and not _schema_is_current():
        print(f"{DB_PATH} uses an older schema - rebuilding.")
        reset = True
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

    start_day = TODAY - timedelta(days=HISTORY_DAYS)

    # ---- Resources: 1 site manager, 2-3 supervisors, cleaners per site ----
    # Rows: (id, code, name, site, role, supervisor_id, active, left_on)
    employees: list[tuple] = []
    emp_id = 88201
    managers: dict[int, int] = {}
    supervisors: dict[int, list[int]] = {}
    cleaners: dict[int, list[int]] = {}
    left_on: dict[int, date] = {}
    for site_id, _ in all_sites:
        def new_emp(role: str, supervisor: int | None) -> int:
            nonlocal emp_id
            e = emp_id
            name = f"{RNG.choice(FIRST_NAMES)} {RNG.choice(LAST_NAMES)}"
            active = 1
            if role == "CLEANER" and RNG.random() < 0.06:
                active = 0
                left_on[e] = TODAY - timedelta(days=RNG.randint(10, 120))
            employees.append((e, f"EMP{e}", name, site_id, role, supervisor, active))
            emp_id += 1
            return e

        managers[site_id] = new_emp("SITE_MANAGER", None)
        supervisors[site_id] = [new_emp("SUPERVISOR", managers[site_id])
                                for _ in range(RNG.randint(2, 3))]
        cleaners[site_id] = [new_emp("CLEANER", RNG.choice(supervisors[site_id]))
                             for _ in range(RNG.randint(17, 21))]
    cur.executemany(
        "INSERT OR REPLACE INTO employee (id, employee_code, name, org_unit_id, role, "
        "supervisor_id, active) VALUES (?, ?, ?, ?, ?, ?, ?)", employees)

    # ---- Locations: QR code + NFC tag or BLE beacon per area -------------
    locations: dict[int, list[tuple[int, str, str, str, str, int]]] = {}
    loc_rows = []
    loc_id = 7001
    for site_id, _ in all_sites:
        picked = RNG.sample(LOCATION_POOL, RNG.randint(10, 14))
        for n, (loc_name, weight) in enumerate(picked, start=1):
            tag_type = RNG.choices(["NFC", "BEACON"], weights=[70, 30])[0]
            tag = f"{'NFC' if tag_type == 'NFC' else 'BCN'}-{site_id}-{n:03d}"
            qr = f"QR-{site_id}-{n:03d}"
            locations.setdefault(site_id, []).append((loc_id, loc_name, qr, tag, tag_type, weight))
            loc_rows.append((loc_id, site_id, loc_name, qr, tag, tag_type))
            loc_id += 1
    cur.executemany(
        "INSERT OR REPLACE INTO location (id, org_unit_id, name, qr_code_id, tag_id, tag_type) "
        "VALUES (?, ?, ?, ?, ?, ?)", loc_rows)

    # ---- Materials --------------------------------------------------------
    materials = [(9000 + i, code, desc, uom)
                 for i, (code, desc, uom) in enumerate(MATERIALS, start=1)]
    cur.executemany(
        "INSERT OR REPLACE INTO material "
        "(id, material_code, material_description, unit_of_measure) VALUES (?, ?, ?, ?)",
        materials)

    # ---- Attendance: one row per employee per working day -----------------
    attendance = []
    # Cleaners on shift, by (site, day) -> [(id, clock_in, clock_out)]; feeds
    # work-order assignment and NFC/beacon check-ins so they agree with T&A.
    on_shift: dict[tuple[int, date], list[tuple[int, datetime, datetime]]] = {}
    for offset in range(HISTORY_DAYS + 1):
        day = start_day + timedelta(days=offset)
        if day.weekday() >= 5:            # weekdays only
            continue
        for e_id, _code, _name, site_id, role, _sup, _active in employees:
            if e_id in left_on and day > left_on[e_id]:
                continue
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
                cin_dt = shift_start - timedelta(minutes=RNG.randint(0, 12))
                cout_dt = at(day, 16, 0) + timedelta(minutes=RNG.randint(-20, 70))
                cin, cout = iso(cin_dt), iso(cout_dt)
                if role == "CLEANER":
                    on_shift.setdefault((site_id, day), []).append((e_id, cin_dt, cout_dt))
            attendance.append((e_id, site_id, day.isoformat(), cin, cout, status, leave))
    cur.executemany(
        "INSERT INTO shift_attendance (employee_id, org_unit_id, shift_date, "
        "clock_in_timestamp, clock_out_timestamp, status, leave_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", attendance)

    # ---- Work orders ------------------------------------------------------
    work_orders = []
    wo_id = 104001

    def wo_resource(site_id: int, day: date) -> int:
        present = on_shift.get((site_id, day))
        return RNG.choice(present)[0] if present else RNG.choice(cleaners[site_id])

    def wo_duration(wo_type: str) -> timedelta:
        if RNG.random() < 0.04:           # long tail - stuck in the queue
            return timedelta(hours=RNG.randint(72, 150))
        if wo_type in REACTIVE_WO_TYPES:
            return timedelta(minutes=RNG.randint(15, 240))
        return timedelta(minutes=RNG.randint(120, 48 * 60))

    for offset in range(HISTORY_DAYS + 1):
        day = start_day + timedelta(days=offset)
        weekday = day.weekday() < 5
        for site_id, _ in all_sites:
            count = RNG.randint(4, 12) if weekday else RNG.randint(0, 3)
            for _ in range(count):
                completed = at(day, RNG.randint(7, 17), RNG.choice([0, 15, 30, 45]))
                wo_type = RNG.choice(WORK_ORDER_TYPES)
                work_orders.append((
                    wo_id, f"WO-{day.year}-{wo_id}", site_id, "COMPLETED",
                    wo_type, RNG.choice(WO_DESCRIPTIONS[wo_type]),
                    iso(completed - wo_duration(wo_type)), iso(completed),
                    wo_resource(site_id, day) if RNG.random() > 0.05 else None,
                ))
                wo_id += 1
        # A few still-open orders, so the COMPLETED filter is doing real work.
        if weekday and RNG.random() < 0.5:
            site_id = RNG.choice(all_sites)[0]
            wo_type = RNG.choice(WORK_ORDER_TYPES)
            work_orders.append((
                wo_id, f"WO-{day.year}-{wo_id}", site_id, "IN_PROGRESS",
                wo_type, RNG.choice(WO_DESCRIPTIONS[wo_type]),
                iso(at(day, RNG.randint(6, 17), RNG.choice([0, 15, 30, 45]))), None, None))
            wo_id += 1

    # ---- Cleaner tracking: NFC taps / beacon dwell during each shift ------
    check_ins = []
    ci_id = 900001
    for (site_id, _day), present in on_shift.items():
        site_locs = locations[site_id]
        for e_id, cin_dt, cout_dt in present:
            t = cin_dt + timedelta(minutes=RNG.randint(5, 20))
            while t < cout_dt - timedelta(minutes=10):
                l_id, _n, _qr, tag, tag_type, _w = RNG.choice(site_locs)
                step = timedelta(minutes=RNG.randint(30, 90))
                if tag_type == "BEACON":
                    dwell = timedelta(minutes=RNG.randint(5, 40))
                    out = min(t + dwell, t + step - timedelta(minutes=2), cout_dt)
                    out_iso = iso(out)
                else:
                    out_iso = None
                check_ins.append((ci_id, e_id, site_id, l_id, tag, tag_type, iso(t), out_iso))
                ci_id += 1
                t += step
    cur.executemany(
        "INSERT INTO cleaner_check_in (id, resource_id, org_unit_id, location_id, tag_id, "
        "method, check_in_timestamp, check_out_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        check_ins)

    # ---- QR customer feedback + escalations -------------------------------
    feedback = []
    escalations = []
    fb_id = 300001
    esc_id = 600001
    now = at(TODAY, 9, 0)             # "current time" for open/acknowledged state

    def new_escalation(site_id: int, loc_id: int | None, source: str, category: str,
                       priority: str, created: datetime, raised_by: int | None,
                       feedback_id: int | None) -> int:
        nonlocal esc_id, wo_id
        ack = created + timedelta(minutes=RNG.randint(3, 90))
        resolved = ack + timedelta(minutes=int(RNG.lognormvariate(4.6, 1.1)))
        hours_open = (resolved - created).total_seconds() / 3600
        level = 3 if hours_open > 24 else 2 if hours_open > 4 else 1
        assignee = managers[site_id] if level == 3 else RNG.choice(supervisors[site_id])
        # Recent escalations keep a backlog open so "open escalations" isn't empty.
        recent = now - created < timedelta(days=4)
        if resolved > now or (recent and RNG.random() < 0.45):
            resolved = None
        if ack > now or (recent and resolved is None and RNG.random() < 0.35):
            ack = None
        status = "RESOLVED" if resolved else "ACKNOWLEDGED" if ack else "OPEN"
        # Roughly half are actioned through a reactive work order.
        work_order_id = None
        if ack and RNG.random() < 0.5:
            wo_type = {"CONSUMABLES": "Washroom Replenishment", "SPILL": "Spill Response",
                       "GENERAL": "Waste Removal"}.get(category, "Scheduled Clean")
            work_orders.append((
                wo_id, f"WO-{ack.year}-{wo_id}", site_id,
                "COMPLETED" if resolved else "IN_PROGRESS", wo_type,
                RNG.choice(WO_DESCRIPTIONS[wo_type]), iso(ack),
                iso(resolved) if resolved else None,
                wo_resource(site_id, ack.date()) if resolved else None))
            work_order_id = wo_id
            wo_id += 1
        e = esc_id
        escalations.append((
            e, f"ESC-{created.year}-{e}", site_id, loc_id, source, feedback_id, work_order_id,
            category, priority, level, status, raised_by, assignee, iso(created),
            iso(ack) if ack else None, iso(resolved) if resolved else None))
        esc_id += 1
        return e

    for offset in range(HISTORY_DAYS + 1):
        day = start_day + timedelta(days=offset)
        weekday = day.weekday() < 5
        for site_id, _ in all_sites:
            site_locs = locations[site_id]
            weights = [loc[5] for loc in site_locs]
            for _ in range(RNG.randint(15, 50) if weekday else RNG.randint(2, 10)):
                l_id, _n, qr, _tag, _tt, _w = RNG.choices(site_locs, weights=weights)[0]
                rating = RNG.choices([5, 4, 3, 2, 1], weights=[55, 20, 10, 8, 7])[0]
                if rating >= 4:
                    category = RNG.choices(["GENERAL", "CLEANLINESS"], weights=[60, 40])[0]
                    comment = (RNG.choice(FEEDBACK_COMMENTS["good"])
                               if RNG.random() < 0.15 else None)
                else:
                    category = RNG.choice(FEEDBACK_CATEGORIES)
                    comment = (RNG.choice(FEEDBACK_COMMENTS[category])
                               if RNG.random() < (0.6 if rating <= 2 else 0.3) else None)
                submitted = at(day, RNG.randint(6, 18), RNG.randint(0, 59))
                if submitted > now:
                    continue
                escalation_id = None
                if rating <= 2 and RNG.random() < 0.6:
                    priority = (RNG.choice(["HIGH", "CRITICAL"]) if rating == 1
                                else RNG.choice(["MEDIUM", "HIGH"]))
                    escalation_id = new_escalation(
                        site_id, l_id, "QR_FEEDBACK", category, priority,
                        submitted + timedelta(minutes=RNG.randint(0, 5)), None, fb_id)
                feedback.append((fb_id, site_id, l_id, qr, rating, category, comment,
                                 iso(submitted), escalation_id))
                fb_id += 1
            # Supervisor-raised and client-requested escalations, a few a week.
            if weekday and RNG.random() < 0.6:
                source = RNG.choice(ESCALATION_SOURCES_OTHER)
                created = at(day, RNG.randint(7, 16), RNG.randint(0, 59))
                if created <= now:
                    new_escalation(
                        site_id, RNG.choice(site_locs)[0], source,
                        RNG.choice(FEEDBACK_CATEGORIES),
                        RNG.choices(["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                                    weights=[30, 40, 22, 8])[0],
                        created,
                        RNG.choice(supervisors[site_id]) if source == "SUPERVISOR" else None,
                        None)

    cur.executemany(
        "INSERT INTO escalation (id, escalation_code, org_unit_id, location_id, source, "
        "feedback_id, work_order_id, category, priority, level, status, "
        "raised_by_resource_id, assigned_to_resource_id, created_date, acknowledged_date, "
        "resolved_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", escalations)
    cur.executemany(
        "INSERT INTO customer_feedback (id, org_unit_id, location_id, qr_code_id, rating, "
        "category, comment, submitted_timestamp, escalation_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", feedback)

    cur.executemany(
        "INSERT OR REPLACE INTO work_order (id, work_order_code, org_unit_id, status, "
        "work_order_type, description, created_date, completed_date, resource_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", work_orders)

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
    for table in ("org_unit", "store", "employee", "location", "material",
                  "shift_attendance", "work_order", "cleaner_check_in",
                  "customer_feedback", "escalation", "stock_on_hand", "stock_movement"):
        n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<18} {n:>7,}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed the mock Forcelink partner database.")
    ap.add_argument("--reset", action="store_true", help="Delete and rebuild the database.")
    seed(**vars(ap.parse_args()))
