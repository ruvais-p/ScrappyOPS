"""TA / DA requests (a person's "field day"): starting and ending the day, bills, the approval chain, the automatic
calculation of travel allowance and the fraud flags, flagging by Head Office, and the monthly payment."""
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from psycopg.types.json import Jsonb

from core.services.common import ApiError, fetch, fetch_one
from kwd import storage
from kwd.rules.base import Rules
from kwd.rules.util import haversine_m, ist_date, ist_today, now, photo_ok, trim
from kwd.scope import HO, TSO, ZM

OWN_VEHICLE = ("two_wheeler", "car")


def policy():
    return fetch_one("select * from kwd_expense_policy where id = 1")


def D(x):
    return Decimal(str(x))


def r2(x, places=2):
    return D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def event(day_id, actor, ev, amount=None, note=None, meta=None):
    fetch_one("insert into kwd_claim_events (day_id, actor, event, amount, note, meta) values (%(d)s, %(a)s, %(e)s, %(m)s, %(n)s, %(x)s) returning id",
              {"d": day_id, "a": actor, "e": ev, "m": amount, "n": note, "x": Jsonb(meta) if meta is not None else None})


# ---------------------------------------------------------------------------------------------- the automatic calculation
def recalc_field_day(day_id):
    """Work out kilometres, TA, DA and every system flag for a request, from the visits, the readings and the bills.
    The browser never sends these numbers. Runs after any change to the day, its bills or that day's visits (until approval)."""
    d = fetch_one("select * from kwd_field_days where id = %(i)s", {"i": day_id})
    if not d or d["status"] not in ("open", "submitted"):
        return
    p = policy()
    v = fetch_one("select count(*) filter (where zm_status <> 'rejected') as ok, count(*) filter (where zm_status = 'rejected') as rej, "
                  "min(check_in_at) as first_in from kwd_visits where tso_id = %(t)s and (check_in_at at time zone 'Asia/Kolkata')::date = %(d)s",
                  {"t": d["tso_id"], "d": d["day"]})
    v_ok, v_rej, first_in = v["ok"], v["rej"], v["first_in"]

    pts = []
    if d["start_lat"] is not None and d["start_lng"] is not None:
        pts.append((d["start_lat"], d["start_lng"]))
    for r in fetch("select check_in_lat as lat, check_in_lng as lng from kwd_visits where tso_id = %(t)s and zm_status <> 'rejected' "
                   "and (check_in_at at time zone 'Asia/Kolkata')::date = %(d)s and check_in_lat is not null and check_in_lng is not null order by check_in_at",
                   {"t": d["tso_id"], "d": d["day"]}):
        pts.append((r["lat"], r["lng"]))
    if d["end_lat"] is not None and d["end_lng"] is not None:
        pts.append((d["end_lat"], d["end_lng"]))
    km = sum(haversine_m(a[0], a[1], b[0], b[1]) / 1000 for a, b in zip(pts, pts[1:]))
    gps_km = r2(D(km) * p["road_factor"], 1) if len(pts) >= 2 else None
    odo_km = d["end_odo"] - d["start_odo"] if d["start_odo"] is not None and d["end_odo"] is not None else None

    f, rate, tkm = [], Decimal(0), Decimal(0)
    if d["travel_mode"] in OWN_VEHICLE:
        rate = p["rate_two_wheeler"] if d["travel_mode"] == "two_wheeler" else p["rate_car"]
        tkm = D(max(odo_km or 0, 0))
        if d["end_at"] is not None and (d["start_odo"] is None or d["end_odo"] is None):
            f.append("odometer_missing")
        if odo_km is not None and odo_km > p["max_km_day"]:
            f.append("km_over_daily_limit")
        if odo_km is not None and gps_km is not None and D(odo_km) > gps_km * (1 + D(p["km_tolerance_pct"]) / 100) + 5:
            f.append("km_above_gps")
        if odo_km is not None and odo_km > 0 and gps_km is None:
            f.append("no_gps_route")
        prev = fetch_one("select end_odo from kwd_field_days where tso_id = %(t)s and day < %(d)s and end_odo is not null and "
                         "upper(replace(coalesce(vehicle_no, ''), ' ', '')) = upper(replace(coalesce(%(v)s::text, ''), ' ', '')) order by day desc limit 1",
                         {"t": d["tso_id"], "d": d["day"], "v": d["vehicle_no"]})
        if prev and d["start_odo"] is not None and d["start_odo"] < prev["end_odo"]:
            f.append("odometer_overlap")

    s = fetch_one("select coalesce(sum(amount) filter (where category in ('bus_train','auto_taxi','parking_toll')), 0) as travel, "
                  "coalesce(sum(amount) filter (where category = 'lodging'), 0) as lodging, "
                  "coalesce(sum(amount) filter (where category in ('phone_internet','printing_courier','other')), 0) as other, "
                  "coalesce(sum(amount) filter (where category = 'auto_taxi'), 0) as autotaxi from kwd_expense_items where day_id = %(i)s", {"i": d["id"]})
    travel, lodging, other, autotaxi = s["travel"], s["lodging"], s["other"], s["autotaxi"]
    allowance = d["da_requested"]
    ta_amount = r2(tkm * rate, 2) + travel

    if v_ok == 0:
        f.append("no_field_work")
    if v_rej > 0:
        f.append("visits_rejected")
    if d["start_lat"] is None:
        f.append("no_gps_start")
    if d["end_at"] is not None and d["end_lat"] is None:
        f.append("no_gps_end")
    if (d["start_acc"] is not None and d["start_acc"] > 100) or (d["end_acc"] is not None and d["end_acc"] > 100):
        f.append("weak_gps")
    if d["end_at"] is None and d["day"] < ist_today():
        f.append("day_not_ended")
    if first_in is not None and d["start_at"] > first_in:
        f.append("late_start")
    if d["end_at"] is not None and ist_date(d["end_at"]) > d["day"]:
        f.append("late_end")
    if lodging > p["lodging_cap"]:
        f.append("lodging_over_cap")
    if lodging > 0 and not d["night_halt"]:
        f.append("lodging_without_halt")
    if autotaxi > p["auto_taxi_cap_day"]:
        f.append("auto_taxi_over_cap")
    if allowance > (p["da_outstation"] if d["night_halt"] else p["da_local"]):
        f.append("da_over_cap")
    has_da_bill = fetch_one("select exists (select 1 from kwd_expense_items where day_id = %(i)s and category = 'da_bill') as x", {"i": d["id"]})["x"]
    if allowance > p["bill_required_above"] and not has_da_bill:
        f.append("da_no_bill")
    if fetch_one("select exists (select 1 from kwd_expense_items where day_id = %(i)s and 'missing_bill' = any(flags)) as x", {"i": d["id"]})["x"]:
        f.append("missing_bill")
    if fetch_one("select exists (select 1 from kwd_expense_items where day_id = %(i)s and 'duplicate_bill' = any(flags)) as x", {"i": d["id"]})["x"]:
        f.append("duplicate_bill")
    if d["submitted_at"] is not None and ist_date(d["submitted_at"]) > d["day"] + timedelta(days=p["claim_window_days"]):
        f.append("late_claim")
    if d["day"].weekday() == 6:
        f.append("sunday")

    # a plain update: this is the system writing, so it is not logged as a person's change
    fetch("update kwd_field_days set visits_count = %(vc)s, gps_km = %(gk)s, odo_km = %(ok)s, ta_km = %(tk)s, ta_amount = %(ta)s, "
          "da_amount = %(da)s, lodging_amount = %(lo)s, other_amount = %(ot)s, flags = %(f)s where id = %(i)s returning 1",
          {"vc": v_ok, "gk": gps_km, "ok": odo_km, "tk": tkm, "ta": ta_amount, "da": allowance, "lo": lodging, "ot": other, "f": f, "i": d["id"]})


# ---------------------------------------------------------------------------------------------- the day itself
class FieldDays(Rules):
    api = "field_days"
    audit = ("INSERT", "UPDATE")
    defaults = {"tso_id": lambda c: c.uid, "day": lambda c: ist_today(), "travel_mode": "two_wheeler", "start_at": lambda c: now(),
                "night_halt": False, "visits_count": 0, "ta_km": 0, "ta_amount": 0, "da_amount": 0, "lodging_amount": 0,
                "other_amount": 0, "flags": [], "status": "open", "created_at": lambda c: now(), "ho_flag": False, "da_requested": 0}

    def insert_check(self, ctx, S, P, new):
        return new["tso_id"] == ctx.uid

    def update_using(self, ctx, S, a):
        return f"({a}.tso_id = {S.me} or {S.is_ho()} or ({S.is_zm()} and {S.is_my_tso(a + '.tso_id')}))"

    def update_check(self, ctx, S, P, new):
        return True

    def before_insert(self, ctx, new):
        if ctx.role is None:
            raise ApiError("Account inactive")
        t = now()
        new.update(tso_id=ctx.uid, day=ist_today(), start_at=t, created_at=t, end_at=None, end_lat=None, end_lng=None, end_acc=None,
                   end_odo=None, end_photo=None, visits_count=0, gps_km=None, odo_km=None, ta_km=0, ta_amount=0, da_amount=0,
                   da_requested=0, lodging_amount=0, other_amount=0, flags=[], status="open", submitted_at=None, approved_amount=None,
                   zm_by=None, zm_at=None, zm_remark=None, ho_by=None, ho_at=None, ho_remark=None, paid_by=None, paid_at=None,
                   paid_ref=None, payment_id=None, ho_flag=False, ho_flag_by=None, ho_flag_at=None)
        veh = trim(new.get("vehicle_no")).upper()
        new["vehicle_no"] = veh or None
        if new.get("travel_mode") in OWN_VEHICLE:
            if new["vehicle_no"] is None:
                raise ApiError("Enter the vehicle number.")
            if new.get("start_odo") is None:
                raise ApiError("Enter the odometer reading.")
            if not photo_ok(ctx, new.get("start_photo")):
                raise ApiError("Take a photo of the odometer.")
        else:
            new["start_odo"] = None
            if new.get("start_photo") is not None and not photo_ok(ctx, new["start_photo"]):
                raise ApiError("Invalid photo.")
        return new

    def after_insert(self, ctx, row):
        recalc_field_day(row["id"])
        event(row["id"], ctx.uid, "started", meta={"mode": row["travel_mode"], "odo": row["start_odo"]})

    def before_update(self, ctx, old, new, keys):
        r = ctx.role
        own_vehicle = old["travel_mode"] in OWN_VEHICLE
        for c in ("id", "tso_id", "day", "created_at", "travel_mode", "vehicle_no", "start_at", "start_lat", "start_lng", "start_acc",
                  "start_odo", "start_photo", "visits_count", "gps_km", "odo_km", "ta_km", "ta_amount", "da_amount", "lodging_amount",
                  "other_amount", "flags", "ho_flag", "ho_flag_by", "ho_flag_at"):
            new[c] = old[c]
        if r is None:
            raise ApiError("Account inactive")
        t = now()

        if old["tso_id"] == ctx.uid:                                              # the person's own request
            if old["status"] != "open":
                raise ApiError("This request is submitted and locked.")
            for c in ("approved_amount", "zm_by", "zm_at", "zm_remark", "ho_by", "ho_at", "ho_remark", "paid_by", "paid_at", "paid_ref"):
                new[c] = old[c]
            ends = ("end_at", "end_lat", "end_lng", "end_acc", "end_odo", "end_photo")
            if old["end_at"] is not None:
                for c in ends:
                    new[c] = old[c]
            elif new.get("end_at") is not None:
                new["end_at"] = t
                if own_vehicle:
                    if new.get("end_odo") is None:
                        raise ApiError("Enter the odometer reading.")
                    if old["start_odo"] is not None and new["end_odo"] < old["start_odo"]:
                        raise ApiError(f"The reading is lower than this morning's ({old['start_odo']}).")
                    if not photo_ok(ctx, new.get("end_photo")):
                        raise ApiError("Take a photo of the odometer.")
                else:
                    new["end_odo"] = None
                    if new.get("end_photo") is not None and not photo_ok(ctx, new["end_photo"]):
                        raise ApiError("Invalid photo.")
            else:
                for c in ("end_lat", "end_lng", "end_acc", "end_odo", "end_photo"):
                    new[c] = None
            # the allowance is typed by the person, never above the maximum Head Office set
            p = policy()
            new["da_requested"] = r2(new.get("da_requested") or 0, 2)
            cap = p["da_outstation"] if new["night_halt"] else p["da_local"]
            if new["da_requested"] < 0:
                raise ApiError("The allowance cannot be negative.")
            if new["da_requested"] > cap:
                raise ApiError(f"The allowance for one day is at most Rs {cap} (the maximum set by Head Office).")
            if new["status"] == "submitted":
                if new.get("end_at") is None:
                    raise ApiError("End your day before submitting the request.")
                has_bill = fetch_one("select exists (select 1 from kwd_expense_items where day_id = %(i)s and category = 'da_bill') as x", {"i": old["id"]})["x"]
                if new["da_requested"] > p["bill_required_above"] and not has_bill:
                    raise ApiError("Upload the bill(s) for your allowance before submitting.")
                new["submitted_at"] = t
            elif new["status"] == "open":
                new["submitted_at"] = old["submitted_at"]
            else:
                raise ApiError("You can only submit your own request.")
            return self._guard_payment(old, new)

        if r == TSO:
            raise ApiError("Not allowed.")
        if r == ZM and not fetch_one("select exists (select 1 from kwd_profiles where id = %(u)s and manager_id = %(m)s) as x", {"u": old["tso_id"], "m": ctx.uid})["x"]:
            raise ApiError("Not your team.")
        for c in ("end_at", "end_lat", "end_lng", "end_acc", "end_odo", "end_photo", "night_halt", "halt_place", "tso_note", "submitted_at", "da_requested"):
            new[c] = old[c]

        if new["status"] == old["status"]:
            raise ApiError("Nothing to change.")
        if old["status"] == "submitted" and new["status"] in ("zm_approved", "rejected", "open"):
            if new["status"] == "zm_approved":
                new["approved_amount"] = new["approved_amount"] if new.get("approved_amount") is not None else old["total_claimed"]
                if new["approved_amount"] < 0 or new["approved_amount"] > old["total_claimed"]:
                    raise ApiError(f"The verified amount must be between 0 and the requested {old['total_claimed']}.")
                if new["approved_amount"] < old["total_claimed"] and not trim(new.get("zm_remark")):
                    raise ApiError("Write why the amount was cut.")
            else:
                if not trim(new.get("zm_remark")):
                    raise ApiError("Write the reason.")
                new["approved_amount"] = None
            new["zm_by"], new["zm_at"] = ctx.uid, t
            for c in ("ho_by", "ho_at", "ho_remark", "paid_by", "paid_at", "paid_ref"):
                new[c] = old[c]
        elif r == HO and old["status"] in ("submitted", "zm_approved") and new["status"] in ("ho_approved", "rejected", "open"):
            if new["status"] == "ho_approved":
                base = new["approved_amount"] if new.get("approved_amount") is not None else (
                    old["approved_amount"] if old["approved_amount"] is not None else old["total_claimed"])
                new["approved_amount"] = base
                if base < 0 or base > old["total_claimed"]:
                    raise ApiError(f"The approved amount must be between 0 and the requested {old['total_claimed']}.")
                before = old["approved_amount"] if old["approved_amount"] is not None else old["total_claimed"]
                if base < before and not trim(new.get("ho_remark")):
                    raise ApiError("Write why the amount was cut.")
            else:
                if not trim(new.get("ho_remark")):
                    raise ApiError("Write the reason.")
                new["approved_amount"] = None
            new["ho_by"], new["ho_at"] = ctx.uid, t
            for c in ("zm_by", "zm_at", "zm_remark", "paid_by", "paid_at", "paid_ref"):
                new[c] = old[c]
        elif r == HO and old["status"] == "ho_approved" and new["status"] == "paid":
            if not trim(new.get("paid_ref")):
                raise ApiError("Enter the payment reference (UTR / voucher no).")
            new["paid_by"], new["paid_at"] = ctx.uid, t
            new["approved_amount"] = old["approved_amount"]
            for c in ("zm_by", "zm_at", "zm_remark", "ho_by", "ho_at", "ho_remark"):
                new[c] = old[c]
        else:
            raise ApiError(f"This step is not allowed ({old['status']} to {new['status']}).")
        return self._guard_payment(old, new)

    def _guard_payment(self, old, new):
        """A day is paid only by the monthly settlement, never one by one."""
        new["payment_id"] = old["payment_id"]
        if new["status"] == "paid" and old["status"] != "paid":
            raise ApiError("TA/DA is paid monthly. Use the monthly settlement.")
        return new

    def after_update(self, ctx, old, row, keys):
        recalc_field_day(row["id"])
        r = ctx.role
        if row["da_requested"] != old["da_requested"]:
            event(row["id"], ctx.uid, "da_set", row["da_requested"],
                  f"Changed from Rs {old['da_requested']}" if old["da_requested"] > 0 else None)
        if old["end_at"] is None and row["end_at"] is not None:
            event(row["id"], ctx.uid, "ended", meta={"odo": row["end_odo"]})
        if row["status"] != old["status"]:
            ev = {"submitted": "submitted", "zm_approved": "zm_verified", "ho_approved": "ho_approved", "paid": "paid", "rejected": "rejected"}.get(row["status"], "sent_back")
            if row["status"] == "submitted":
                amt = fetch_one("select total_claimed from kwd_field_days where id = %(i)s", {"i": row["id"]})["total_claimed"]
                note = row["tso_note"]
            elif row["status"] == "paid":
                amt, note = row["approved_amount"], row["paid_ref"]
            else:
                amt, note = row["approved_amount"], row["ho_remark"] if r == HO else row["zm_remark"]
            event(row["id"], ctx.uid, ev, amt, note)


# ---------------------------------------------------------------------------------------------- bills
class ExpenseItems(Rules):
    api = "expense_items"
    audit = ("INSERT", "DELETE")
    defaults = {"tso_id": lambda c: c.uid, "created_at": lambda c: now(), "flags": []}

    def insert_check(self, ctx, S, P, new):
        return new["tso_id"] == ctx.uid

    def delete_using(self, ctx, S, a):
        return f"{a}.tso_id = {S.me}"

    def before_insert(self, ctx, new):
        d = fetch_one("select * from kwd_field_days where id = %(i)s", {"i": new.get("day_id")})
        if not d or d["tso_id"] != ctx.uid:
            raise ApiError("Not your request.")
        if d["status"] != "open":
            raise ApiError("This request is submitted and locked.")
        p = policy()
        new["tso_id"], new["created_at"], new["flags"], new["bill_hash"] = ctx.uid, now(), [], None
        new["bill_no"] = trim(new.get("bill_no")) or None
        cat = new.get("category")
        if cat in ("meals", "da_other"):
            raise ApiError("Type your allowance amount, then upload the bills.")
        if cat == "da_bill":
            new["amount"] = Decimal(0)                      # the allowance is typed on the request; bills are the evidence
            if new.get("bill_path") is None:
                raise ApiError("Upload the bill photo.")
        elif new.get("amount") is None or new["amount"] <= 0:
            raise ApiError("Enter the amount.")
        if new.get("bill_path") is not None:
            if not photo_ok(ctx, new["bill_path"]):
                raise ApiError("Upload the bill photo again.")
            new["bill_hash"] = storage.etag(new["bill_path"])
        if new["amount"] > p["bill_required_above"] and new.get("bill_path") is None:
            new["flags"].append("missing_bill")
        dup = False
        if new["bill_hash"] is not None:
            dup = fetch_one("select exists (select 1 from kwd_expense_items where bill_hash = %(h)s) as x", {"h": new["bill_hash"]})["x"]
        if not dup and new["bill_no"] is not None:
            dup = fetch_one("select exists (select 1 from kwd_expense_items where lower(bill_no) = lower(%(b)s) and category = %(c)s and amount = %(a)s) as x",
                            {"b": new["bill_no"], "c": cat, "a": new["amount"]})["x"]
        if dup:
            new["flags"].append("duplicate_bill")
        return new

    def after_insert(self, ctx, row):
        recalc_field_day(row["day_id"])
        event(row["day_id"], ctx.uid, "bill_added", row["amount"], row["description"],
              {"category": row["category"], "bill": row["bill_path"] is not None, "flags": row["flags"]})

    def before_update(self, ctx, old, new, keys):
        raise ApiError("Expenses cannot be edited. Delete it and add it again.")

    def before_delete(self, ctx, old):
        open_day = fetch_one("select exists (select 1 from kwd_field_days where id = %(i)s and status = 'open') as x", {"i": old["day_id"]})["x"]
        if old["tso_id"] != ctx.uid or not open_day:
            raise ApiError("This claim is submitted and locked.")

    def after_delete(self, ctx, old):
        recalc_field_day(old["day_id"])
        event(old["day_id"], ctx.uid, "bill_removed", old["amount"], old["description"], {"category": old["category"]})


# ---------------------------------------------------------------------------------------------- Head Office actions
def flag_day(ctx, p_day, p_flag, p_reason):
    if ctx.role != HO:
        raise ApiError("Only Head Office can flag.")
    if not trim(p_reason):
        raise ApiError("Write the reason.")
    d = fetch_one("select * from kwd_field_days where id = %(i)s for update", {"i": p_day})
    if not d:
        raise ApiError("Request not found.")
    if d["ho_flag"] == bool(p_flag):
        raise ApiError(f"It is already {'flagged' if p_flag else 'clear'}.")
    fetch("update kwd_field_days set ho_flag = %(f)s, ho_flag_by = %(u)s, ho_flag_at = now() where id = %(i)s returning 1",
          {"f": bool(p_flag), "u": ctx.uid, "i": p_day})
    event(p_day, ctx.uid, "ho_flagged" if p_flag else "ho_unflagged", None, trim(p_reason))
    return None


def pay_month(ctx, p_tso, p_month, p_ref, p_note=None):
    """Pay one person's approved days for a finished month in a single payment."""
    if ctx.role != HO:
        raise ApiError("Only Head Office can pay.")
    if not trim(p_ref):
        raise ApiError("Enter the payment reference (UTR / voucher no).")
    m = date.fromisoformat(str(p_month)[:10]).replace(day=1)
    nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    if nxt > ist_today():
        raise ApiError(f"This month is not over yet. Pay from {nxt.strftime('%d %b %Y')}.")
    s = fetch_one("select count(*) as n, coalesce(sum(approved_amount), 0) as total from kwd_field_days where tso_id = %(t)s and day >= %(a)s and day < %(b)s "
                  "and status = 'ho_approved' and not ho_flag", {"t": p_tso, "a": m, "b": nxt})
    if s["n"] == 0:
        raise ApiError("Nothing approved to pay for this month (flagged days are on hold).")
    pay = fetch_one("insert into kwd_expense_payments (tso_id, month, days, amount, paid_ref, note, paid_by) values (%(t)s, %(m)s, %(n)s, %(a)s, %(r)s, %(no)s, %(u)s) returning *",
                    {"t": p_tso, "m": m, "n": s["n"], "a": s["total"], "r": trim(p_ref), "no": trim(p_note) or None, "u": ctx.uid})
    fetch("update kwd_field_days set status = 'paid', paid_ref = %(r)s, payment_id = %(p)s where tso_id = %(t)s and day >= %(a)s and day < %(b)s "
          "and status = 'ho_approved' and not ho_flag returning 1", {"r": trim(p_ref), "p": pay["id"], "t": p_tso, "a": m, "b": nxt})
    from kwd.rules.util import to_json
    fetch_one("insert into kwd_audit_log (table_name, row_id, action, new_data, actor) values ('expense_payments', %(i)s, 'PAY_MONTH', %(n)s, %(u)s) returning id",
              {"i": pay["id"], "n": Jsonb(to_json(pay)), "u": ctx.uid})
    return pay
