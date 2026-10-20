"""Visits: the evidence of a field visit. The server (not the phone) decides the time, the distance to the office, and every
fraud flag; evidence cannot be edited afterwards; and who may review or sign off is fixed here."""
from datetime import timedelta

from core.services.common import ApiError, fetch, fetch_one
from kwd.rules.base import Rules
from kwd.rules.util import haversine_m, ist_date, ist_today, now, trim
from kwd.scope import HO, TSO, ZM


class Visits(Rules):
    api = "visits"
    audit = ("INSERT", "UPDATE", "DELETE")
    defaults = {"tso_id": lambda c: c.uid, "check_in_at": lambda c: now(), "created_at": lambda c: now(), "fraud_flags": [],
                "zm_status": "pending"}

    # ---- who may create / change ----
    def insert_check(self, ctx, S, P, new):
        from kwd.rules.simple import uu
        return f"({S.role_in(TSO, ZM)} and {S.can_see_lsgd(uu(P, new['lsgd_id']))})"

    def update_using(self, ctx, S, a):
        return f"({a}.tso_id = {S.me} or ({S.role_in(ZM, HO)} and {S.can_see_lsgd(a + '.lsgd_id')}))"

    # ---- BEFORE INSERT: server time, distance, flags ----
    def before_insert(self, ctx, new):
        if ctx.role != HO:
            new["tso_id"] = ctx.uid
        t = now()
        new.update(check_in_at=t, created_at=t, check_out_at=None, fraud_flags=[], distance_from_office_m=None, zm_status="pending",
                   zm_reviewed_by=None, zm_reviewed_at=None, zm_remark=None, ho_signed_by=None, ho_signed_at=None, ho_remark=None)
        flags = []
        # the planned task this visit belongs to
        task_id = None
        if new.get("task_id"):
            r = fetch_one("select id from kwd_tasks where id = %(i)s and assigned_to = %(t)s and lsgd_id = %(l)s",
                          {"i": new["task_id"], "t": new["tso_id"], "l": new["lsgd_id"]})
            task_id = r["id"] if r else None
        if task_id is None:
            r = fetch_one("select id from kwd_tasks where assigned_to = %(t)s and lsgd_id = %(l)s and planned_date = %(d)s and status = 'planned' limit 1",
                          {"t": new["tso_id"], "l": new["lsgd_id"], "d": ist_today()})
            task_id = r["id"] if r else None
        new["task_id"] = task_id
        if task_id is None:
            flags.append("unplanned")

        office = fetch_one("select office_lat, office_lng from kwd_lsgds where id = %(l)s", {"l": new["lsgd_id"]}) or {}
        lat, lng = new.get("check_in_lat"), new.get("check_in_lng")
        if lat is None or lng is None:
            flags.append("no_gps")
        elif office.get("office_lat") is None:
            flags.append("lsgd_location_missing")
        else:
            dist = haversine_m(lat, lng, office["office_lat"], office["office_lng"])
            new["distance_from_office_m"] = dist
            if dist > 300:
                flags.append("outside_geofence")
        if new.get("gps_accuracy_m") is not None and new["gps_accuracy_m"] > 100:
            flags.append("weak_gps")

        prev = fetch_one("select check_in_at, check_in_lat, check_in_lng from kwd_visits where tso_id = %(t)s and check_in_lat is not null "
                         "order by check_in_at desc limit 1", {"t": new["tso_id"]})
        if prev and lat is not None:
            km = haversine_m(prev["check_in_lat"], prev["check_in_lng"], lat, lng) / 1000
            hrs = max((t - prev["check_in_at"]).total_seconds() / 3600, 0.01)
            if km / hrs > 80:
                flags.append("impossible_travel")
        n = fetch_one("select count(*) as n from kwd_visits where tso_id = %(t)s and (check_in_at at time zone 'Asia/Kolkata')::date = %(d)s",
                      {"t": new["tso_id"], "d": ist_today()})["n"]
        if n >= 8:
            flags.append("high_volume_day")
        new["fraud_flags"] = flags
        # details are "filled in" when the discussion is long enough
        new["details_at"] = t if len(trim(new.get("discussion"))) >= 20 else None
        return new

    # ---- AFTER INSERT: tick the planned task, refresh the day's claim ----
    def after_insert(self, ctx, row):
        if row.get("task_id"):
            fetch("update kwd_tasks set status = 'done' where id = %(i)s returning 1", {"i": row["task_id"]})
        self._recalc(row)

    def _recalc(self, row):
        from kwd.rules.days import recalc_field_day
        for d in fetch("select id from kwd_field_days where tso_id = %(t)s and day = %(d)s and status in ('open','submitted')",
                       {"t": row["tso_id"], "d": ist_date(row["check_in_at"])}):
            recalc_field_day(d["id"])

    # ---- BEFORE UPDATE: owner completes details; ZM reviews; HO signs off ----
    def before_update(self, ctx, old, new, keys):
        r = ctx.role
        owner = old["tso_id"] == ctx.uid
        for c in ("tso_id", "lsgd_id", "check_in_at", "check_in_lat", "check_in_lng", "gps_accuracy_m", "distance_from_office_m",
                  "photo_path", "fraud_flags", "created_at", "task_id", "details_at"):
            new[c] = old[c]
        if r is None:
            raise ApiError("Account inactive")
        t = now()
        if owner and r in (TSO, ZM):
            if old["zm_status"] != "pending":
                raise ApiError("Visit already reviewed; it is locked")
            lim = timedelta(days=3) if old["details_at"] is None else timedelta(hours=12)
            if t - old["check_in_at"] > lim:
                raise ApiError("The 3 days to add details are over. Ask your manager." if old["details_at"] is None
                               else "Visit locked 12 hours after check-in")
            new["check_out_at"] = t if (old["check_out_at"] is None and new.get("check_out_at") is not None
                                        and t - old["check_in_at"] <= timedelta(hours=12)) else old["check_out_at"]
            for c in ("zm_status", "zm_remark", "zm_reviewed_by", "zm_reviewed_at", "ho_remark", "ho_signed_by", "ho_signed_at"):
                new[c] = old[c]
            if new.get("discussion") != old.get("discussion") or old["details_at"] is not None:
                if len(trim(new.get("discussion"))) < 20:
                    raise ApiError("Write at least 20 characters about the discussion.")
                if old["details_at"] is None:
                    new["details_at"] = t
        elif r == ZM:
            for c in ("discussion", "outcome", "interest_level", "next_followup_on", "check_out_at", "ho_remark", "ho_signed_by", "ho_signed_at"):
                new[c] = old[c]
            if new["zm_status"] != old["zm_status"]:
                if new["zm_status"] == "verified" and old["details_at"] is None:
                    raise ApiError("The details of this visit are not filled in yet. Ask the visitor to complete them.")
                new["zm_reviewed_by"], new["zm_reviewed_at"] = ctx.uid, t
            else:
                new["zm_reviewed_by"], new["zm_reviewed_at"] = old["zm_reviewed_by"], old["zm_reviewed_at"]
        elif r == HO:
            for c in ("discussion", "outcome", "interest_level", "next_followup_on", "check_out_at"):
                new[c] = old[c]
            if new["zm_status"] != old["zm_status"]:
                if new["zm_status"] == "verified" and old["details_at"] is None:
                    raise ApiError("The details of this visit are not filled in yet.")
                new["zm_reviewed_by"], new["zm_reviewed_at"] = ctx.uid, t
            if new.get("ho_signed_at") is not None and old["ho_signed_at"] is None:
                if old["details_at"] is None:
                    raise ApiError("The details of this visit are not filled in yet.")
                new["ho_signed_by"], new["ho_signed_at"] = ctx.uid, t
        else:
            raise ApiError("Account inactive")
        return new

    def after_update(self, ctx, old, row, keys):
        if "zm_status" in keys:                           # a review (or a rejection) changes the day's visit count and flags
            self._recalc(row)


class VisitContacts(Rules):
    """Who was met on a visit. Only the visit's owner adds people."""
    api = "visit_contacts"

    def insert_check(self, ctx, S, P, new):
        from kwd.rules.simple import uu
        return f"exists (select 1 from kwd_visits v where v.id = {uu(P, new['visit_id'])} and v.tso_id = {S.me})"
