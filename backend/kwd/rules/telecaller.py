"""Telecalling: Head Office hands a telecaller a batch of sales leads or franchise-partner leads to call. Each call logs a
status and a hot/warm/cold temperature so the follow-up list can show the hottest leads first. A telecaller can also bill a
customer directly: the same tax-invoice shape as the franchise module, picked from the shared product catalogue, but with
no stock to track and no products to add."""
from datetime import timedelta
from decimal import Decimal

from core.services.common import ApiError, fetch_one
from kwd.rules.base import Rules
from kwd.rules.util import ist_today, now, trim
from kwd.scope import HO, TC


def uu(P, v):
    return f"{P.add(v)}::uuid" if v is not None else "null::uuid"


class TcLeads(Rules):
    api = "tc_leads"
    audit = ("INSERT", "UPDATE")
    defaults = {"status": "new", "created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return ctx.role in (HO, TC)

    def update_using(self, ctx, S, a):
        return S.tc_can_see(a + ".assigned_to")

    def update_check(self, ctx, S, P, new):
        return S.tc_can_see(uu(P, new.get("assigned_to")))

    def before_insert(self, ctx, new):
        if ctx.role not in (HO, TC):
            raise ApiError("Only Head Office or a telecaller can add a telecalling lead")
        if new.get("kind") not in ("sales", "franchise"):
            raise ApiError("Choose sales or franchise")
        if len(trim(new.get("customer_name"))) < 2:
            raise ApiError("Enter the name")
        if ctx.role == TC:
            new["assigned_to"] = ctx.uid
        elif not new.get("assigned_to"):
            raise ApiError("Choose a telecaller to assign this lead to")
        new.update(status="new", temperature=None, lost_reason=None, next_followup_on=None, tc_note=None,
                    last_call_at=None, last_update_at=None, created_by=ctx.uid, created_at=now())
        return new

    def before_update(self, ctx, old, new, keys):
        r = ctx.role
        if r == HO:
            # Head Office can fix the lead's own details and reassign it; the call outcome is the telecaller's to write
            for c in ("status", "temperature", "lost_reason", "next_followup_on", "tc_note", "last_call_at", "last_update_at", "created_by"):
                new[c] = old[c]
            if len(trim(new.get("customer_name"))) < 2:
                raise ApiError("Enter the name")
        elif r == TC:
            # the lead's own details are fixed for a telecaller; only the call outcome can be written
            locked = ["id", "kind", "customer_name", "contact_person", "phone", "district_id", "place", "address",
                      "assigned_to", "created_by", "created_at"]
            for c in locked:
                new[c] = old[c]
            if old["status"] in ("converted", "lost"):
                raise ApiError("This lead is closed")
            if new["status"] not in ("new", "contacted", "interested", "not_interested", "converted", "lost"):
                raise ApiError("Choose a valid status")
            if new["status"] == "new" and old["status"] != "new":
                raise ApiError("A lead cannot go back to New")
            if new["status"] == "lost" and len(trim(new.get("lost_reason"))) < 5:
                raise ApiError("Say why this lead was lost")
            if new["status"] != "lost":
                new["lost_reason"] = None
            if new.get("temperature") not in (None, "hot", "warm", "cold"):
                raise ApiError("Choose hot, warm or cold")
            new["last_call_at"] = now()
            new["last_update_at"] = now()
        else:
            raise ApiError("Not allowed")
        return new

    def after_update(self, ctx, old, row, keys):
        if row["status"] != old["status"] or row["temperature"] != old["temperature"]:
            from core.services.common import fetch_one
            fetch_one("insert into kwd_tc_lead_events (lead_id, actor, from_status, to_status, from_temperature, to_temperature, note) "
                      "values (%(l)s, %(a)s, %(fs)s, %(ts)s, %(ft)s, %(tt)s, %(n)s) returning id",
                      {"l": row["id"], "a": ctx.uid, "fs": old["status"], "ts": row["status"],
                       "ft": old["temperature"], "tt": row["temperature"],
                       "n": row["lost_reason"] if row["lost_reason"] is not None else row["tc_note"]})


# ---------------------------------------------------------------------------------------------- billing
def record_sale(ctx, p_customer_name=None, p_customer_type=None, p_phone=None, p_district=None, p_place=None,
                p_sale_date=None, p_amount_received=None, p_items=None):
    """A telecaller bills a customer directly: picks products from the shared catalogue, prices them, and gets a tax
    invoice. No stock is tracked and no product can be added here - that stays with Head Office."""
    from datetime import date
    from uuid import UUID
    if ctx.role != TC:
        raise ApiError("Only a telecaller can create this bill")
    if not isinstance(p_items, list) or not p_items:
        raise ApiError("Add at least one product")
    if len(trim(p_customer_name)) < 2:
        raise ApiError("Enter the customer name")
    if p_customer_type not in ("B2B", "B2C", "B2G"):
        raise ApiError("Choose the customer type")
    today = ist_today()
    sale_date = date.fromisoformat(str(p_sale_date)[:10]) if p_sale_date else today
    if sale_date > today or sale_date < today - timedelta(days=7):
        raise ApiError("Sale date must be within the last 7 days")
    s = fetch_one("insert into kwd_tc_sales (telecaller_id, customer_name, customer_type, phone, district_id, place, sale_date, created_by) "
                  "values (%(f)s, %(n)s, %(t)s, %(p)s, %(d)s, %(pl)s, %(sd)s, %(u)s) returning *",
                  {"f": ctx.uid, "n": trim(p_customer_name), "t": p_customer_type, "p": trim(p_phone) or None, "d": p_district,
                   "pl": trim(p_place) or None, "sd": sale_date, "u": ctx.uid})
    total = Decimal(0)
    for it in p_items:
        try:
            pid, quantity = UUID(str(it["product_id"])), Decimal(str(it["qty"]))
            if not quantity.is_finite() or quantity != quantity.to_integral_value():
                raise ValueError
            q = int(quantity)
            gst = Decimal(str(it.get("gst_percent") or 0))
            if not gst.is_finite():
                raise ValueError
            hsn = trim(it.get("hsn_sac"))
            incl = Decimal(str(it["unit_price_incl"])) if it.get("unit_price_incl") not in (None, "") else None
            if incl is not None:
                if not incl.is_finite() or incl <= 0 or gst < 0 or gst > 100:
                    raise ValueError
                pr = incl / (Decimal(1) + gst / Decimal(100))
            else:
                pr = Decimal(str(it["unit_price"]))
            if not pr.is_finite():
                raise ValueError
        except Exception:
            raise ApiError("Enter valid product, quantity, price and GST details")
        if q <= 0:
            raise ApiError("Quantity must be at least 1")
        if pr <= 0:
            raise ApiError("Enter the selling price")
        if gst < 0 or gst > 100:
            raise ApiError("GST must be between 0 and 100 percent")
        prod = fetch_one("select * from kwd_fr_products where id = %(i)s and is_active", {"i": pid})
        if not prod:
            raise ApiError("Unknown product")
        fetch_one("insert into kwd_tc_sale_items (sale_id, product_id, hsn_sac, qty, unit_price, gst_percent) "
                  "values (%(s)s, %(p)s, %(h)s, %(q)s, %(u)s, %(g)s) returning id",
                  {"s": s["id"], "p": pid, "h": hsn or prod["hsn_sac"] or None, "q": q, "u": pr, "g": gst})
        total += q * incl if incl is not None else q * pr * (Decimal(1) + gst / Decimal(100))
    try:
        received = Decimal(str(p_amount_received or 0))
        if not received.is_finite() or received < 0:
            raise ValueError
    except Exception:
        raise ApiError("Enter a valid non-negative payment amount")
    if received > total:
        raise ApiError("Money received cannot be more than the sale total")
    business_start = sale_date.year if sale_date.month >= 4 else sale_date.year - 1
    business_year = f"{business_start % 100:02d}{(business_start + 1) % 100:02d}"
    counter = fetch_one(
        "insert into kwd_tc_invoice_counters (business_year, last_number) values (%(fy)s, 1) "
        "on conflict (business_year) do update set last_number = kwd_tc_invoice_counters.last_number + 1 returning last_number",
        {"fy": business_year},
    )["last_number"]
    invoice_no = f"TC-{p_customer_type}/{business_year}/{sale_date:%m%d}/{counter:03d}"
    row = fetch_one("update kwd_tc_sales set invoice_no = %(inv)s, total = %(t)s, amount_received = %(r)s where id = %(id)s returning *",
                    {"inv": invoice_no, "t": total, "r": received, "id": s["id"]})
    return row["id"]


def cancel_sale(ctx, p_sale, p_reason):
    if ctx.role != HO:
        raise ApiError("Only Head Office can cancel a bill")
    if len(trim(p_reason)) < 5:
        raise ApiError("Say why this bill is cancelled")
    sl = fetch_one("select * from kwd_tc_sales where id = %(i)s for update", {"i": p_sale})
    if not sl:
        raise ApiError("Bill not found")
    if sl["status"] == "cancelled":
        raise ApiError("Already cancelled")
    fetch_one("update kwd_tc_sales set status = 'cancelled', cancel_reason = %(r)s, cancelled_by = %(u)s, cancelled_at = now() where id = %(i)s returning *",
              {"r": trim(p_reason), "u": ctx.uid, "i": p_sale})
    return None


def receive_payment(ctx, p_sale, p_amount, p_method, p_reference=None):
    """Record an additional customer payment against an active telecalling bill: the telecaller who raised it, or Head Office."""
    from decimal import InvalidOperation

    sale = fetch_one("select * from kwd_tc_sales where id = %(i)s for update", {"i": p_sale})
    if not sale:
        raise ApiError("Bill not found")
    if ctx.role == TC and sale["telecaller_id"] != ctx.uid:
        raise ApiError("Bill not found")
    elif ctx.role not in (HO, TC):
        raise ApiError("Not allowed")
    if sale["status"] != "active":
        raise ApiError("Active invoice not found")
    try:
        amount = Decimal(str(p_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ApiError("Enter a valid payment amount")
    if amount <= 0:
        raise ApiError("Payment amount must be greater than zero")
    if p_method not in ("cash", "upi", "bank_transfer", "cheque", "card", "other"):
        raise ApiError("Choose a payment method")
    due = Decimal(str(sale["total"])) - Decimal(str(sale["amount_received"]))
    if due <= 0:
        raise ApiError("This invoice has no balance due")
    if amount > due:
        raise ApiError(f"Payment cannot exceed the balance due ({due})")
    receipt = fetch_one(
        "insert into kwd_tc_payment_receipts (sale_id, amount, method, reference, received_by) "
        "values (%(s)s, %(a)s, %(m)s, %(r)s, %(u)s) returning *",
        {"s": sale["id"], "a": amount, "m": p_method, "r": trim(p_reference) or None, "u": ctx.uid},
    )
    fetch_one("update kwd_tc_sales set amount_received = amount_received + %(a)s where id = %(i)s returning *",
              {"a": amount, "i": sale["id"]})
    return receipt["id"]
