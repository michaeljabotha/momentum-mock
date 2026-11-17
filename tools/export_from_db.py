#!/usr/bin/env python3
"""Build prod_data.sql - every mock table replaced with real Momentum data - straight from the bid_corp database.

Runs the same queries as the real partner API (forcelink DEV12431, BidCorpPartnerApi) against a read-only login,
limited to the Momentum sites, and writes a SQL script that empties every mock table and inserts the result.
The mock loads it on start-up when it is present (see app/seed.py), or by hand:

    sqlite3 momentum.db < prod_data.sql

Usage (the defaults file holds host, user, password and database under [client]; keep it private):

    python3 tools/export_from_db.py --defaults-file ~/.config/forcelink/bid_corp.cnf

Needs the mysql command-line client; otherwise only the Python standard library.
The output holds real names and comments: it is git-ignored, keep it out of commits.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SITE_TYPE = "STE"
LOCATION_ASSET_TYPE = "LCT"
FEEDBACK_TYPE, PROBLEM_TYPE = "RYET", "RYEP"
ROLE_BY_TYPE = {"CL": "CLEANER", "SUP": "SUPERVISOR", "CMG": "SITE_MANAGER"}
RATING_BY_ANSWER = {"HAPPY": 5, "NEUTRAL": 3, "SAD": 1, "PROBLEM": 1}
CREATED_STATES = "5,17,18"
RESOLVED_STATES = "4,24,3,16"
LATE_GRACE_MINUTES = 15
TABLES = ["cleaner_check_in", "escalation", "customer_feedback", "stock_movement", "stock_on_hand",
          "work_order", "shift_attendance", "material", "location", "employee", "store", "org_unit"]


class Db:
    def __init__(self, defaults_file: Path):
        self.defaults = str(defaults_file.expanduser())

    def rows(self, sql: str) -> list[list[str | None]]:
        out = subprocess.run(["mysql", f"--defaults-file={self.defaults}", "-N", "-B", "-e", sql],
                             capture_output=True, text=True)
        if out.returncode:
            sys.exit(f"mysql failed: {out.stderr.strip()}\n{sql[:400]}")
        return [[None if v == "NULL" else unescape(v) for v in line.split("\t")]
                for line in out.stdout.splitlines()]


def unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\t", "\t").replace("\\0", "\0").replace("\\\\", "\\")


def ids(values) -> str:
    values = [str(int(v)) for v in values]
    return ",".join(values) if values else "-1"


def num(value) -> int | None:
    return None if value is None else int(value)


class Exporter:
    def __init__(self, db: Db, sites: list[int], date_from: str, date_to: str, zone: ZoneInfo):
        self.db, self.sites, self.zone = db, sites, zone
        self.date_from, self.date_to_excl = date_from, (date.fromisoformat(date_to).toordinal() + 1)
        self.date_to_excl = date.fromordinal(self.date_to_excl).isoformat()
        self.orgs = {int(r[0]): (num(r[1]), r[2], r[3], r[4] == "1") for r in db.rows(
            "select o.id, o.parent_org_id, t.code, o.description, o.active from org_structure o"
            " left join reference_list t on t.id = o.org_unit_type_id")}
        self.scope = [o for o in self.orgs if self.site_of(o) in sites]
        self.any_site = [o for o in self.orgs if self.site_of(o) is not None]

    def site_of(self, org_id) -> int | None:
        seen = set()
        while org_id is not None and org_id in self.orgs and org_id not in seen:
            seen.add(org_id)
            parent, typ, _name, active = self.orgs[org_id]
            if active and typ == SITE_TYPE:
                return org_id
            org_id = parent
        return None

    def utc(self, local: str | None) -> str | None:
        """The database holds the subscriber's local time; the mock stores UTC with a Z."""
        if not local:
            return None
        dt = datetime.strptime(local[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.zone)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def rng(self, column: str) -> str:
        return f"{column} >= '{self.date_from}' and {column} < '{self.date_to_excl}'"

    # ------------------------------------------------------------------ queries (as BidCorpPartnerApi)

    def resources(self):
        types = ",".join(f"'{t}'" for t in ROLE_BY_TYPE)
        return self.db.rows(
            "select x.id, x.code, x.description, x.type_code, x.org_id,"
            " coalesce((select min(m.id) from resource m where m.user_id = x.manager_id and m.active = 1),"
            "  (select min(s.id) from resource s join resource_type st on st.id = s.resource_sub_type_id"
            "   join resource_orgunit so on so.resource_id = s.id"
            "   join resource_orgunit xo on xo.orgstructure_id = so.orgstructure_id and xo.resource_id = x.id"
            "   where s.active = 1 and s.id <> x.id and st.code = case x.type_code"
            "    when 'CL' then 'SUP' when 'SUP' then 'CMG' end)) supervisor_id, x.active"
            " from (select r.id, r.code, r.description, t.code type_code, r.active, r.manager_id,"
            "  (select min(ro.orgstructure_id) from resource_orgunit ro"
            f"   where ro.resource_id = r.id and ro.orgstructure_id in ({ids(self.scope)})) org_id"
            "  from resource r join resource_type t on t.id = r.resource_sub_type_id"
            f"  where t.code in ({types})) x where x.org_id is not null order by x.id")

    def attendance(self):
        scope, any_site = ids(self.scope), ids(self.any_site)
        inner = ("select 0 kind, s.id row_id, s.resource_id, date(s.shift_start_date) shift_day,"
                 " s.shift_start_date clock_in, s.shift_end_date clock_out, c.start_date_time rostered, c.id cal_id,"
                 f" case when s.orgunit_id in ({any_site}) then s.orgunit_id"
                 f"  when c.org_structure_id in ({any_site}) then c.org_structure_id"
                 "  else (select min(ro.orgstructure_id) from resource_orgunit ro"
                 f"   where ro.resource_id = s.resource_id and ro.orgstructure_id in ({scope})) end org_id"
                 " from resource_shift_record s left join availability_calendar c on c.id = s.availability_calendar_id"
                 f" where {self.rng('s.shift_start_date')}"
                 " union all"
                 " select 1, c.id, c.resource_id, date(c.start_date_time), null, null, c.start_date_time, c.id,"
                 f" case when c.org_structure_id in ({any_site}) then c.org_structure_id"
                 "  else (select min(ro.orgstructure_id) from resource_orgunit ro"
                 f"   where ro.resource_id = c.resource_id and ro.orgstructure_id in ({scope})) end"
                 " from availability_calendar c"
                 f" where {self.rng('c.start_date_time')} and c.start_date_time < now() and c.resource_id is not null"
                 " and not exists (select 1 from resource_shift_record s where s.resource_id = c.resource_id"
                 "  and (s.availability_calendar_id = c.id or date(s.shift_start_date) = date(c.start_date_time)))")
        return self.db.rows(
            "select x.kind, x.resource_id, r.code, x.org_id, x.shift_day, x.clock_in, x.clock_out, x.rostered,"
            " exists (select 1 from leave_xref lx where lx.avail_cal_id = x.cal_id) on_leave"
            f" from ({inner}) x join resource r on r.id = x.resource_id where x.org_id in ({scope})"
            " order by x.shift_day, x.resource_id, x.kind, x.row_id")

    def work_orders(self):
        return self.db.rows(
            "select w.id, w.code, w.org_structure_id, t.description, w.description, w.created_date_time,"
            " w.actual_finish, coalesce(w.resource_id, (select min(x.resource_id) from workorder_resources x"
            "  where x.workorder_id = w.id)), la.id, la.description, la.code"
            " from work_order w left join reference_list t on t.id = w.workorder_type_id"
            " left join asset la on la.id = coalesce(w.asset_id, (select min(x.asset_id) from work_order_asset x"
            "  where x.work_order_id = w.id))"
            f" where {self.rng('w.actual_finish')} and w.org_structure_id in ({ids(self.scope)})"
            " order by w.actual_finish, w.id")

    def site_by_location(self) -> dict[int, int]:
        by_name = {" ".join(n.split()).lower(): o for o, (_p, t, n, a) in self.orgs.items()
                   if a and t == SITE_TYPE and n}
        result = {}
        for asset_id, name in self.db.rows("select a.id, a.description from asset a join asset_type t"
                                           f" on t.id = a.asset_type_id where t.code = '{LOCATION_ASSET_TYPE}'"):
            site = by_name.get(" ".join((name or "").split()).lower())
            if site:
                result[int(asset_id)] = site
        return result

    def requests(self, site_by_location: dict[int, int]):
        any_location = ids(site_by_location)
        locations = ids(k for k, v in site_by_location.items() if v in self.sites)
        status = (f"(case when cs.system_status_id in ({RESOLVED_STATES}) then 'RESOLVED'"
                  f" when cs.system_status_id is null or cs.system_status_id in ({CREATED_STATES}) then 'OPEN'"
                  " else 'ACKNOWLEDGED' end)")
        return self.db.rows(
            "select wr.id, rt.code, wr.org_structure_id, lct.parent_id, a.id, a.code, a.description, wr.date_created,"
            f" wr.inspection_list_group_id, wr.code, {status},"
            " coalesce(wr.work_order_id, (select min(w.id) from work_order w where w.createdFromWorkRequest_id = wr.id)),"
            " coalesce((select min(x.resource_id) from workorderrequest_resources x where x.workorderrequest_id = wr.id),"
            "  (select min(r.id) from resource r where r.user_id = wr.assignedToUser_id and r.active = 1)),"
            " (select min(h.time_stamp) from workrequeststatushistory h join status_reference n on n.id = h.new_id"
            f"  where h.workrequest_id = wr.id and n.system_status_id not in ({CREATED_STATES})),"
            " (select max(h.time_stamp) from workrequeststatushistory h join status_reference n on n.id = h.new_id"
            f"  where h.workrequest_id = wr.id and n.system_status_id in ({RESOLVED_STATES})),"
            " (select p.description from reference_list p where p.id = wr.priority_id)"
            " from work_order_request wr"
            f" join reference_list rt on rt.id = wr.work_request_type_id and rt.code in ('{FEEDBACK_TYPE}','{PROBLEM_TYPE}')"
            " left join asset a on a.id = (select min(x.asset_id) from work_order_request_asset x"
            "  where x.work_order_request_id = wr.id)"
            f" left join asset_hierarchy lct on lct.id = a.id and lct.parent_id in ({any_location})"
            " left join status_reference cs on cs.id = wr.work_request_status_id"
            f" where {self.rng('wr.date_created')}"
            f" and (lct.parent_id in ({locations}) or (lct.parent_id is null and wr.org_structure_id in ({ids(self.scope)})))"
            " order by wr.date_created, wr.id")

    def answers(self, groups: list[int]) -> dict[int, list]:
        result: dict[int, list] = {}
        if not groups:
            return result
        root_of = {g: g for g in groups}
        for child, parent in self.db.rows("select h.id, h.parent_id from inspection_group_hierarchy h"
                                          f" where h.parent_id in ({ids(groups)})"):
            root_of.setdefault(int(child), int(parent))
        for group, code, value, question in self.db.rows(
                "select i.inspection_list_group_id, o.code, i.value_string, i.description"
                " from inspection_list_item i left join custom_reference_list o on o.id = i.value_id"
                f" where i.inspection_list_group_id in ({ids(root_of)}) order by i.sort_order, i.id"):
            answer = result.setdefault(root_of[int(group)], [None, None])
            if answer[0] is None and code in RATING_BY_ANSWER:
                answer[0] = code
            elif (answer[1] is None and question and question.strip().lower().startswith("comment")
                  and value and value.strip()):
                answer[1] = value.strip()
        return result


def level(created: datetime, until: datetime) -> int:
    hours = (until - created).total_seconds() // 3600
    return 1 if hours < 4 else 2 if hours < 24 else 3


def priority(description: str | None) -> str:
    text = (description or "").upper()
    if "CRITICAL" in text or "URGENT" in text:
        return "CRITICAL"
    if "HIGH" in text:
        return "HIGH"
    return "LOW" if "LOW" in text else "MEDIUM"


def sql(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def insert(table: str, columns: list[str], rows: list[tuple]) -> list[str]:
    head = f"INSERT INTO {table} ({', '.join(columns)}) VALUES"
    return [f"{head} ({', '.join(sql(v) for v in row)});" for row in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--defaults-file", required=True, type=Path, help="mysql client options file ([client] section)")
    ap.add_argument("--sites", default="542,543,544", help="site org unit ids (Momentum Cape Town, Centurion, Sandton)")
    ap.add_argument("--from", dest="date_from", default="2025-07-01")
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat())
    ap.add_argument("--time-zone", default="Africa/Johannesburg", help="the subscriber's time zone")
    ap.add_argument("--split-supervisors", default="542",
                    help="sites whose cleaners are spread evenly over the site's supervisors (mock only; '' for none)."
                         " Default: Momentum Cape Town")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "prod_data.sql")
    args = ap.parse_args()

    zone = ZoneInfo(args.time_zone)
    sites = [int(s) for s in args.sites.split(",") if s.strip()]
    ex = Exporter(Db(args.defaults_file), sites, args.date_from, args.date_to, zone)
    now = datetime.now(timezone.utc)

    def site(org_id) -> int | None:
        return ex.site_of(num(org_id))

    org_units = {s: ex.orgs[s][2] for s in sites if s in ex.orgs}

    # Inactive resources are left out of the mock altogether, with their shifts.
    employees: dict[int, tuple] = {}
    inactive: set[int] = set()
    for rid, code, name, typ, org, sup, active in ex.resources():
        if active != "1":
            inactive.add(int(rid))
            continue
        employees[int(rid)] = (int(rid), code or "", name or "", site(org), ROLE_BY_TYPE[typ], num(sup), True)

    attendance, placeholders = [], 0
    for kind, rid, code, org, day, clock_in, clock_out, rostered, on_leave in ex.attendance():
        absent, leave = kind == "1", on_leave == "1"
        if leave:
            status = "ON_LEAVE"
        elif absent:
            status = "ABSENT"
        elif clock_in and rostered and (datetime.fromisoformat(clock_in) - datetime.fromisoformat(rostered))\
                .total_seconds() > LATE_GRACE_MINUTES * 60:
            status = "LATE"
        else:
            status = "ON_TIME"
        rid = int(rid)
        if rid in inactive:
            continue
        if rid not in employees:
            employees[rid] = (rid, code or "", code or "", site(org), "CLEANER", None, True)
            placeholders += 1
        attendance.append((rid, site(org), day, ex.utc(clock_in), ex.utc(clock_out), status,
                           "APPROVED" if leave else "NONE"))
    employees = {k: v[:5] + ((v[5] if v[5] in employees else None),) + v[6:] for k, v in employees.items()}

    # Mock only: the real rule gives every cleaner at a site with several supervisors the lowest-id one. Spread the
    # cleaners at each listed site evenly over the site's supervisors instead, by cleaner id.
    for split_site in [int(s) for s in args.split_supervisors.split(",") if s.strip()]:
        sups = sorted(k for k, v in employees.items() if v[3] == split_site and v[4] == "SUPERVISOR")
        cleaners = sorted(k for k, v in employees.items() if v[3] == split_site and v[4] == "CLEANER")
        if not sups:
            continue
        for i, k in enumerate(cleaners):
            employees[k] = employees[k][:5] + (sups[i % len(sups)],) + employees[k][6:]

    locations: dict[int, tuple] = {}
    work_orders = []
    for wid, code, org, typ, desc, created, finished, rid, loc_id, loc_name, loc_code in ex.work_orders():
        if loc_id:
            locations.setdefault(int(loc_id), (int(loc_id), site(org), loc_name or "", loc_code or "", loc_code or "",
                                               "NFC"))
        work_orders.append((int(wid), code, site(org), "COMPLETED", typ or "", desc or "", ex.utc(created),
                            ex.utc(finished), num(rid), num(loc_id)))

    site_by_location = ex.site_by_location()
    requests = ex.requests(site_by_location)
    answers = ex.answers([int(r[8]) for r in requests if r[8]])
    feedback, escalations = [], []
    for (wid, typ, org, lct, asset_id, asset_code, asset_name, created, group, wr_code, esc_status, wo_id, assignee,
         acknowledged, resolved, prio) in requests:
        wid = int(wid)
        req_site = site_by_location.get(num(lct)) if lct else site(org)
        answer = answers.get(num(group), [None, None]) if group else [None, None]
        problem = typ == PROBLEM_TYPE
        if asset_id:
            locations[int(asset_id)] = (int(asset_id), req_site, asset_name or "", asset_code or "", asset_code or "",
                                        "NFC")
        category = "CLEANLINESS" if problem or answer[0] == "PROBLEM" else "GENERAL"
        feedback.append((wid, req_site, num(asset_id), asset_code or "", RATING_BY_ANSWER.get(answer[0], 0),
                         answer[0], category, answer[1], ex.utc(created), wid if problem else None))
        if problem:
            created_dt = datetime.fromisoformat(created).replace(tzinfo=zone)
            resolved_at = resolved if esc_status == "RESOLVED" else None
            until = datetime.fromisoformat(resolved_at).replace(tzinfo=zone) if resolved_at else now
            escalations.append((wid, wr_code or str(wid), req_site, num(asset_id), "QR_FEEDBACK", wid, num(wo_id),
                                "CLEANLINESS", priority(prio), level(created_dt, until), esc_status, None,
                                num(assignee), ex.utc(created),
                                None if esc_status == "OPEN" else ex.utc(acknowledged), ex.utc(resolved_at),
                                answer[1]))

    out = ["-- Replaces every mock table with real Momentum data from the bid_corp database.",
           f"-- Sites {args.sites}, {args.date_from}..{args.date_to}, generated {now.strftime('%Y-%m-%dT%H:%M:%SZ')}.",
           "-- Holds real names and comments: do not commit.",
           "BEGIN TRANSACTION;"]
    out += [f"DELETE FROM {t};" for t in TABLES]
    out.append("DELETE FROM sqlite_sequence;")
    out += insert("org_unit", ["id", "type", "name"], [(i, "SITE", n) for i, n in sorted(org_units.items())])
    out += insert("employee", ["id", "employee_code", "name", "org_unit_id", "role", "supervisor_id", "active"],
                  [employees[k] for k in sorted(employees)])
    out += insert("location", ["id", "org_unit_id", "name", "qr_code_id", "tag_id", "tag_type"],
                  [locations[k] for k in sorted(locations)])
    out += insert("shift_attendance", ["employee_id", "org_unit_id", "shift_date", "clock_in_timestamp",
                                       "clock_out_timestamp", "status", "leave_status"], attendance)
    out += insert("work_order", ["id", "work_order_code", "org_unit_id", "status", "work_order_type", "description",
                                 "created_date", "completed_date", "resource_id", "location_id"], work_orders)
    out += insert("customer_feedback", ["id", "org_unit_id", "location_id", "qr_code_id", "rating", "sentiment",
                                        "category", "comment", "submitted_timestamp", "escalation_id"], feedback)
    out += insert("escalation", ["id", "escalation_code", "org_unit_id", "location_id", "source", "feedback_id",
                                 "work_order_id", "category", "priority", "level", "status", "raised_by_resource_id",
                                 "assigned_to_resource_id", "created_date", "acknowledged_date", "resolved_date",
                                 "comment"], escalations)
    out.append("COMMIT;")
    args.out.write_text("\n".join(out) + "\n")
    print(f"wrote {args.out}: {len(org_units)} sites, {len(employees)} employees ({placeholders} placeholder),"
          f" {len(locations)} locations, {len(attendance)} shifts, {len(work_orders)} work orders,"
          f" {len(feedback)} feedback, {len(escalations)} escalations. Stock and check-ins: empty.", file=sys.stderr)


if __name__ == "__main__":
    main()
