"""The franchise module: leads handed out by Head Office, presentations, sales with delivery and installation, stock that moves
automatically with every sale, and monthly targets. Stock can never go below zero; a sale cannot be edited once cancelled."""
import re
from datetime import timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

from core.services.common import ApiError, fetch, fetch_one
from kwd.rules.base import Rules
from kwd.rules.util import ist_today, now, photo_ok, trim
from kwd.scope import FR, HO


def uu(P, v):
    return f"{P.add(v)}::uuid" if v is not None else "null::uuid"


def lock_stock(franchise_id, product_id):
    fetch_one("select pg_advisory_xact_lock(hashtext(%(k)s)) as x", {"k": f"{franchise_id}{product_id}"})


def on_hand(franchise_id, product_id):
    return fetch_one("select coalesce(sum(qty), 0) as q from kwd_fr_stock_moves where franchise_id = %(f)s and product_id = %(p)s",
                     {"f": franchise_id, "p": product_id})["q"]


def add_stock_move(actor, franchise_id, product_id, qty, kind, sale_id=None, note=None, ref_no=None):
    """Write one stock movement (the system side: sales and cancellations). Refuses to take stock below zero."""
    lock_stock(franchise_id, product_id)
    cur = on_hand(franchise_id, product_id)
    if cur + qty < 0:
        raise ApiError(f"Stock cannot go below zero (on hand: {cur})")
    return fetch_one("insert into kwd_fr_stock_moves (franchise_id, product_id, qty, kind, sale_id, note, ref_no, created_by) "
                     "values (%(f)s, %(p)s, %(q)s, %(k)s, %(s)s, %(n)s, %(r)s, %(a)s) returning *",
                     {"f": franchise_id, "p": product_id, "q": qty, "k": kind, "s": sale_id, "n": note, "r": ref_no, "a": actor})


# ---------------------------------------------------------------------------------------------- simple HO-only tables
class FrFranchises(Rules):
    api = "fr_franchises"
    audit = ("INSERT", "UPDATE")
    defaults = {"is_active": True, "created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return ctx.role == HO

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO


class FrProductCategories(FrFranchises):
    """The kinds of product (Digester, Inoculum ...). Head Office can add more; a product points at one of them."""
    api = "fr_product_categories"
    defaults = {"sort": 0}

    def before_insert(self, ctx, new):
        if ctx.role != HO:
            return new                                   # refused by the permission check
        name = re.sub(r"\s+", " ", trim(new.get("name")))
        if not 2 <= len(name) <= 40:
            raise ApiError("Enter a category name of 2 to 40 characters")
        key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
        if not key:
            raise ApiError("Enter a category name with letters or numbers")
        if fetch_one("select 1 as x from kwd_fr_product_categories where key = %(k)s or lower(name) = lower(%(n)s)", {"k": key, "n": name}):
            raise ApiError(f"The category {name} already exists")
        new["name"], new["key"] = name, key
        new["sort"] = fetch_one("select coalesce(max(sort), 0) + 1 as s from kwd_fr_product_categories")["s"]
        return new


class FrProducts(FrFranchises):
    api = "fr_products"
    defaults = {"is_active": True, "unit": "unit", "needs_install": False, "sort": 0}

    def before_insert(self, ctx, new):
        """Head Office adds a product: it needs a name, a unique code, a category and an HSN/SAC, so the bill form can fill the HSN in."""
        if ctx.role != HO:
            return new                                   # anyone else is refused by the permission check, not by these messages
        new["name"], new["code"] = trim(new.get("name")), trim(new.get("code")).upper()
        if len(new["name"]) < 2:
            raise ApiError("Enter the product name")
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,29}", new["code"]):
            raise ApiError("Enter a product code of letters, numbers and dashes, for example KWD-480")
        if not fetch_one("select 1 as x from kwd_fr_product_categories where key = %(k)s", {"k": new.get("category")}):
            raise ApiError("Choose the product category")
        hsn = trim(new.get("hsn_sac"))
        if not re.fullmatch(r"\d{4,8}", hsn):
            raise ApiError("Enter the HSN/SAC code: 4 to 8 digits")
        new["hsn_sac"] = hsn
        try:
            gst = Decimal(str(new.get("gst_percent") if new.get("gst_percent") not in (None, "") else 0))
        except Exception:
            raise ApiError("Enter a GST rate from 0 to 100")
        if not gst.is_finite() or gst < 0 or gst > 100:
            raise ApiError("Enter a GST rate from 0 to 100")
        new["gst_percent"] = gst
        if fetch_one("select 1 as x from kwd_fr_products where code = %(c)s", {"c": new["code"]}):
            raise ApiError(f"A product with the code {new['code']} already exists")
        new["unit"] = trim(new.get("unit")) or "unit"
        new["spec"] = trim(new.get("spec")) or None
        if fetch_one("select 1 as x from kwd_fr_products where lower(name) = lower(%(n)s)", {"n": new["name"]}):
            raise ApiError(f"A product named {new['name']} already exists")
        if not new.get("sort"):
            new["sort"] = fetch_one("select coalesce(max(sort), 0) + 1 as s from kwd_fr_products")["s"]
        return new


class FrCompanySettings(Rules):
    api = "fr_company_settings"
    audit = ("INSERT", "UPDATE")
    defaults = {"id": 1}

    def insert_check(self, ctx, S, P, new):
        return ctx.role == HO and new.get("id") == 1

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO and new.get("id") == 1

    def before_insert(self, ctx, new):
        new["id"], new["updated_by"], new["updated_at"] = 1, ctx.uid, now()
        return new

    def before_update(self, ctx, old, new, keys):
        new["id"], new["updated_by"], new["updated_at"] = 1, ctx.uid, now()
        return new


class FrMeetings(Rules):
    api = "fr_meetings"
    audit = ("INSERT", "UPDATE")
    defaults = {"status": "scheduled", "created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return ctx.role == HO

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO

    def before_insert(self, ctx, new):
        if new.get("meeting_type") not in ("B2B", "B2C", "B2G"):
            raise ApiError("Choose B2B, B2C or B2G as the meeting type")
        if len(trim(new.get("description"))) < 2:
            raise ApiError("Enter a meeting description")
        new.update(status="scheduled", created_by=ctx.uid, completed_by=None, completed_at=None)
        return new

    def before_update(self, ctx, old, new, keys):
        if old["status"] != "scheduled":
            raise ApiError("This meeting is already complete")
        if new.get("status") != "completed":
            raise ApiError("Use the Complete action to finish this meeting")
        new.update(scheduled_at=old["scheduled_at"], meeting_type=old["meeting_type"], description=old["description"],
                   created_by=old["created_by"], created_at=old["created_at"], status="completed", completed_by=ctx.uid, completed_at=now())
        return new


class FrTargets(Rules):
    api = "fr_targets"
    audit = ("INSERT", "UPDATE", "DELETE")
    defaults = {"updated_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return ctx.role == HO

    def update_using(self, ctx, S, a):
        return S.is_ho()

    def update_check(self, ctx, S, P, new):
        return ctx.role == HO

    def delete_using(self, ctx, S, a):
        return S.is_ho()

    def before_insert(self, ctx, new):
        new["set_by"], new["updated_at"] = ctx.uid, now()
        return new

    def before_update(self, ctx, old, new, keys):
        new["set_by"], new["updated_at"] = ctx.uid, now()
        return new


# ---------------------------------------------------------------------------------------------- leads
class FrLeads(Rules):
    api = "fr_leads"
    audit = ("INSERT", "UPDATE")
    defaults = {"status": "new", "assigned_at": lambda c: now(), "created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        if ctx.role == HO:
            return True
        fid = ctx.franchise_id
        return f"({S.role_in(FR)} and {uu(P, new['franchise_id'])} = {S.P.add(fid)}::uuid)" if ctx.role == FR and fid else "false"

    def update_using(self, ctx, S, a):
        return S.fr_can_see(a + ".franchise_id")

    def update_check(self, ctx, S, P, new):
        return S.fr_can_see(uu(P, new["franchise_id"]))

    def before_insert(self, ctx, new):
        new.update(status="new", lost_reason=None, fr_note=None, next_followup_on=None, last_update_at=None, assigned_by=ctx.uid, assigned_at=now())
        # a franchisee's own lead: marked as theirs, no Head Office note, and the sheet cannot be filed under someone else
        new["source"] = "own" if ctx.role == FR else "ho"
        if ctx.role == FR:
            new["hq_note"] = None
            if len(trim(new.get("customer_name"))) < 2:
                raise ApiError("Enter the customer name")
        return new

    def before_update(self, ctx, old, new, keys):
        r = ctx.role
        if r == FR:
            # the details of a lead Head Office gave are fixed; a franchisee can correct the details of their own
            locked = ["id", "franchise_id", "hq_note", "assigned_by", "assigned_at", "created_at", "source"]
            if old["source"] != "own":
                locked += ["customer_name", "customer_type", "contact_person", "phone", "district_id", "place", "address", "product_id", "qty"]
            elif old["status"] == "won" and any(new[c] != old[c] for c in ("customer_name", "customer_type", "product_id", "qty")):
                raise ApiError("A closed sale cannot be edited")
            for c in locked:
                new[c] = old[c]
            if old["source"] == "own" and len(trim(new.get("customer_name"))) < 2:
                raise ApiError("Enter the customer name")
            if new["status"] != old["status"]:
                if old["status"] == "won":
                    raise ApiError("A closed sale cannot be reopened")
                if new["status"] == "won":
                    raise ApiError("Record the sale to close this lead")
                if new["status"] == "new":
                    raise ApiError("A lead cannot go back to New")
                if new["status"] == "lost" and len(trim(new.get("lost_reason"))) < 5:
                    raise ApiError("Say why this lead was lost")
                if new["status"] != "lost":
                    new["lost_reason"] = None
            elif old["status"] == "won":
                new["fr_note"], new["next_followup_on"], new["lost_reason"] = old["fr_note"], old["next_followup_on"], old["lost_reason"]
            new["last_update_at"] = now()
        elif r == HO:
            for c in ("status", "lost_reason", "fr_note", "next_followup_on", "last_update_at", "assigned_by", "source"):
                new[c] = old[c]
            if new["franchise_id"] != old["franchise_id"]:
                if old["source"] == "own":
                    raise ApiError("A lead the franchisee found stays with them")
                if old["status"] in ("won", "presentation_set", "negotiating"):
                    raise ApiError("Only a lead that is new, contacted or lost can be moved to another franchisee")
                new["assigned_by"], new["assigned_at"] = ctx.uid, now()
        else:
            raise ApiError("Not allowed")
        return new

    def after_update(self, ctx, old, row, keys):
        if row["status"] != old["status"]:
            fetch_one("insert into kwd_fr_lead_events (lead_id, franchise_id, actor, from_status, to_status, note) values (%(l)s, %(f)s, %(a)s, %(o)s, %(n)s, %(t)s) returning id",
                      {"l": row["id"], "f": row["franchise_id"], "a": ctx.uid, "o": old["status"], "n": row["status"],
                       "t": row["lost_reason"] if row["lost_reason"] is not None else row["fr_note"]})


# ---------------------------------------------------------------------------------------------- presentations
class FrPresentations(Rules):
    api = "fr_presentations"
    audit = ("INSERT", "UPDATE")
    defaults = {"status": "scheduled", "reschedule_count": 0, "product_ids": [], "created_at": lambda c: now()}

    def _own(self, ctx, S, expr):
        fid = ctx.franchise_id
        return f"({S.role_in(FR)} and {expr} = {S.P.add(fid)}::uuid)" if fid else "false"

    def insert_check(self, ctx, S, P, new):
        return self._own(ctx, S, uu(P, new["franchise_id"]))

    def update_using(self, ctx, S, a):
        return self._own(ctx, S, a + ".franchise_id")

    def update_check(self, ctx, S, P, new):
        return self._own(ctx, S, uu(P, new["franchise_id"]))

    def before_insert(self, ctx, new):
        f = ctx.franchise_id
        new.update(franchise_id=f, status="scheduled", reschedule_count=0, created_by=ctx.uid, cancel_reason=None, done_at=None,
                   actual_attendees=None, outcome=None, notes=None, done_lat=None, done_lng=None, done_photo=None)
        if new.get("lead_id") is not None and not fetch_one("select exists (select 1 from kwd_fr_leads where id = %(i)s and franchise_id = %(f)s) as x",
                                                           {"i": new["lead_id"], "f": f})["x"]:
            raise ApiError("That lead is not yours")
        if len(trim(new.get("venue_name"))) < 2:
            raise ApiError("Enter the place or organisation")
        return new

    def after_insert(self, ctx, row):
        if row.get("lead_id"):
            fetch("update kwd_fr_leads set status = 'presentation_set', last_update_at = now() where id = %(i)s and status in ('new','contacted') returning 1", {"i": row["lead_id"]})

    def before_update(self, ctx, old, patched, keys):
        v, new = patched, dict(old)
        if old["status"] == "cancelled":
            raise ApiError("A cancelled appointment cannot be changed")
        if old["status"] == "done":
            if now() > old["done_at"] + timedelta(days=3):
                raise ApiError("This presentation is closed for changes")
            new["outcome"], new["actual_attendees"], new["notes"] = v["outcome"], v["actual_attendees"], v["notes"]
            return new
        for c in ("venue_type", "venue_name", "lsgd_name", "district_id", "address", "contact_person", "phone", "expected_attendees",
                  "product_ids", "purpose", "notes"):
            new[c] = v[c]
        if v["scheduled_at"] != old["scheduled_at"]:
            new["scheduled_at"], new["reschedule_count"] = v["scheduled_at"], old["reschedule_count"] + 1
        if v["status"] == "cancelled":
            if len(trim(v.get("cancel_reason"))) < 5:
                raise ApiError("Say why it was cancelled")
            new["status"], new["cancel_reason"] = "cancelled", trim(v["cancel_reason"])
        elif v["status"] == "done":
            if now() < old["scheduled_at"] - timedelta(hours=3):
                raise ApiError("You can mark it done only on the day of the presentation")
            if v.get("outcome") is None:
                raise ApiError("Choose how it went")
            if v.get("actual_attendees") is None:
                raise ApiError("Enter how many people attended")
            if v.get("done_photo") is not None and not photo_ok(ctx, v["done_photo"]):
                raise ApiError("Photo is not valid")
            new.update(status="done", done_at=now(), outcome=v["outcome"], actual_attendees=v["actual_attendees"],
                       done_lat=v.get("done_lat"), done_lng=v.get("done_lng"), done_photo=v.get("done_photo"))
        return new

    def after_update(self, ctx, old, row, keys):
        if row["status"] == "done" and old["status"] == "scheduled" and row.get("lead_id") and row.get("outcome") in ("interested", "follow_up"):
            fetch("update kwd_fr_leads set status = 'negotiating', last_update_at = now() where id = %(i)s and status in ('new','contacted','presentation_set') returning 1",
                  {"i": row["lead_id"]})


# ---------------------------------------------------------------------------------------------- sales
RK = ["pending", "dispatched", "delivered"]
IK = ["pending", "scheduled", "installed"]


class FrSales(Rules):
    api = "fr_sales"
    audit = ("INSERT", "UPDATE")

    def update_using(self, ctx, S, a):
        return S.fr_can_see(a + ".franchise_id")

    def update_check(self, ctx, S, P, new):
        return S.fr_can_see(uu(P, new["franchise_id"]))

    def before_update(self, ctx, old, patched, keys):
        r, today = ctx.role, ist_today()
        v = patched
        if r == FR:
            if old["status"] == "cancelled":
                raise ApiError("This sale was cancelled by Head Office")
            new = dict(old)
            amount = v["amount_received"]
            if amount < old["amount_received"]:
                raise ApiError("Money received cannot be reduced")
            if amount > old["total"]:
                raise ApiError(f"Money received cannot be more than the sale total ({old['total']})")
            new["amount_received"], new["invoice_no"] = amount, old["invoice_no"]
            ds = v["delivery_status"]
            if RK.index(ds) < RK.index(old["delivery_status"]):
                raise ApiError("Delivery cannot go backwards")
            if old["delivery_status"] == "delivered":
                new["delivery_note"] = v["delivery_note"]
            else:
                new["delivery_status"], new["delivery_note"] = ds, v["delivery_note"]
                if ds in ("dispatched", "delivered"):
                    new["dispatched_on"] = v["dispatched_on"] or today
                    if new["dispatched_on"] < old["sale_date"] or new["dispatched_on"] > today:
                        raise ApiError("Dispatch date must be between the sale date and today")
                if ds == "delivered":
                    if v["delivered_on"] is None:
                        raise ApiError("Enter the delivery date")
                    if v["delivered_on"] < old["sale_date"] or v["delivered_on"] > today:
                        raise ApiError("Delivery date must be between the sale date and today")
                    new["delivered_on"], new["delivered_at"] = v["delivered_on"], now()
            if old["needs_install"]:
                inst_status = v["installation_status"]
                if old["installation_status"] == "installed":
                    new["install_note"] = v["install_note"]
                else:
                    if IK.index(inst_status) < IK.index(old["installation_status"]):
                        raise ApiError("Installation cannot go backwards")
                    if inst_status != "pending" and new["delivery_status"] != "delivered":
                        raise ApiError("Mark the sale delivered before scheduling the installation")
                    new["installation_status"], new["install_note"] = inst_status, v["install_note"]
                    if inst_status in ("scheduled", "installed"):
                        if v["install_planned_on"] is None and inst_status == "scheduled":
                            raise ApiError("Enter the installation date")
                        new["install_planned_on"] = v["install_planned_on"] or v["installed_on"]
                    if inst_status == "installed":
                        if v["installed_on"] is None:
                            raise ApiError("Enter the date it was installed")
                        if (new["delivered_on"] is not None and v["installed_on"] < new["delivered_on"]) or v["installed_on"] > today:
                            raise ApiError("Installation date must be between delivery and today")
                        if not photo_ok(ctx, v["install_photo"]):
                            raise ApiError("Add a photo of the installed unit")
                        new["installed_on"], new["installed_at"], new["install_photo"] = v["installed_on"], now(), v["install_photo"]
            return new
        if r == HO:
            new = dict(old)
            new["ho_flag"], new["ho_flag_reason"] = bool(v["ho_flag"]), v["ho_flag_reason"]
            if new["ho_flag"] and len(trim(v["ho_flag_reason"])) < 5:
                raise ApiError("Say why you are flagging this sale")
            if not new["ho_flag"]:
                new["ho_flag_reason"] = None
            return new
        raise ApiError("Not allowed")


# ---------------------------------------------------------------------------------------------- stock
class FrStockMoves(Rules):
    api = "fr_stock_moves"
    defaults = {"created_at": lambda c: now()}

    def insert_check(self, ctx, S, P, new):
        return ctx.role in (HO, FR) and new.get("kind") in ("opening", "received", "damaged", "returned", "count_adjust")

    def before_insert(self, ctx, new):
        r, kind = ctx.role, new.get("kind")
        if kind in ("sale", "sale_cancel"):
            raise ApiError("Sales move stock automatically")
        if r == FR:
            new["franchise_id"] = ctx.franchise_id
            if new["franchise_id"] is None:
                raise ApiError("Franchise not active")
        elif r != HO:
            raise ApiError("Not allowed")
        new["sale_id"] = None
        if kind in ("damaged", "returned", "count_adjust") and len(trim(new.get("note"))) < 5:
            raise ApiError("Add a short note (at least 5 characters) for this stock change")
        new["created_by"] = ctx.uid
        if kind in ("opening", "received", "sale_cancel"):
            new["qty"] = abs(new["qty"])
        elif kind in ("damaged", "returned", "sale"):
            new["qty"] = -abs(new["qty"])
        lock_stock(new["franchise_id"], new["product_id"])
        cur = on_hand(new["franchise_id"], new["product_id"])
        if cur + new["qty"] < 0:
            raise ApiError(f"Stock cannot go below zero (on hand: {cur})")
        return new


# ---------------------------------------------------------------------------------------------- actions
def record_sale(ctx, p_lead=None, p_customer_name=None, p_customer_type=None, p_phone=None, p_district=None, p_place=None,
                p_sale_date=None, p_invoice_no=None, p_amount_received=None, p_items=None, p_franchise=None):
    """A franchisee records a sale, or Head Office records one for a franchisee."""
    from datetime import date
    from uuid import UUID
    if ctx.role == FR:
        f = ctx.franchise_id
        if f is None:
            raise ApiError("Franchise not found")
    elif ctx.role == HO and p_franchise:
        try:
            f = str(UUID(str(p_franchise)))
        except (ValueError, TypeError):
            raise ApiError("Choose an active franchisee")
        if not fetch_one("select id from kwd_fr_franchises where id = %(f)s and is_active", {"f": f}):
            raise ApiError("Choose an active franchisee")
    else:
        raise ApiError("Choose a franchisee to record this bill")
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
    fl = ["backdated"] if sale_date < today else []
    if p_lead:
        ld = fetch_one("select * from kwd_fr_leads where id = %(i)s and franchise_id = %(f)s for update", {"i": p_lead, "f": f})
        if not ld:
            raise ApiError("Lead not found")
        if ld["status"] == "won":
            raise ApiError("This lead already has a sale")
    s = fetch_one("insert into kwd_fr_sales (franchise_id, lead_id, customer_name, customer_type, phone, district_id, place, sale_date, invoice_no, created_by) "
                  "values (%(f)s, %(l)s, %(n)s, %(t)s, %(p)s, %(d)s, %(pl)s, %(sd)s, %(inv)s, %(u)s) returning *",
                  {"f": f, "l": p_lead, "n": trim(p_customer_name), "t": p_customer_type, "p": trim(p_phone) or None, "d": p_district,
                   "pl": trim(p_place) or None, "sd": sale_date, "inv": trim(p_invoice_no) or None, "u": ctx.uid})
    total, install = Decimal(0), False
    for it in p_items:
        try:
            pid, q = UUID(str(it["product_id"])), int(it["qty"])
            gst = Decimal(str(it.get("gst_percent") or 0))
            hsn = trim(it.get("hsn_sac"))
            # The price can be entered without GST (unit_price) or with GST (unit_price_incl). With GST, the price before tax is worked out here.
            incl = Decimal(str(it["unit_price_incl"])) if it.get("unit_price_incl") not in (None, "") else None
            if incl is not None:
                if not incl.is_finite() or incl <= 0 or gst < 0 or gst > 100:
                    raise ValueError
                pr = (incl / (Decimal(1) + gst / Decimal(100))).quantize(Decimal("0.000001"))
            else:
                pr = Decimal(str(it["unit_price"]))
        except Exception:
            raise ApiError("Enter valid product, quantity, price and GST details")
        if q <= 0:
            raise ApiError("Quantity must be at least 1")
        if pr <= 0:
            raise ApiError("Enter the selling price")
        if gst < 0 or gst > 100:
            raise ApiError("GST must be between 0 and 100 percent")
        if ctx.role == HO and not hsn:
            raise ApiError("Enter HSN/SAC for each product")
        prod = fetch_one("select * from kwd_fr_products where id = %(i)s and is_active", {"i": pid})
        if not prod:
            raise ApiError("Unknown product")
        lock_stock(f, pid)
        have = on_hand(f, pid)
        if have < q:
            raise ApiError(f"Only {have} of {prod['name']} in stock")
        fetch_one("insert into kwd_fr_sale_items (sale_id, product_id, hsn_sac, qty, unit_price, gst_percent) "
                  "values (%(s)s, %(p)s, %(h)s, %(q)s, %(u)s, %(g)s) returning id",
                  {"s": s["id"], "p": pid, "h": hsn or None, "q": q, "u": pr, "g": gst})
        add_stock_move(ctx.uid, f, pid, -q, "sale", s["id"])
        total += q * incl if incl is not None else q * pr * (Decimal(1) + gst / Decimal(100))
        install = install or prod["needs_install"]
        if prod["list_price"] is not None and pr < prod["list_price"] * Decimal("0.9"):
            fl.append("below_list_price")
    received = Decimal(str(p_amount_received or 0))
    if received > total:
        raise ApiError("Money received cannot be more than the sale total")
    business_start = sale_date.year if sale_date.month >= 4 else sale_date.year - 1
    business_year = f"{business_start % 100:02d}{(business_start + 1) % 100:02d}"
    counter = fetch_one(
        "insert into kwd_fr_invoice_counters (business_year, last_number) values (%(fy)s, 1) "
        "on conflict (business_year) do update set last_number = kwd_fr_invoice_counters.last_number + 1 returning last_number",
        {"fy": business_year},
    )["last_number"]
    invoice_no = f"{p_customer_type}/{business_year}/{sale_date:%m%d}/{counter:03d}"
    row = fetch_one("update kwd_fr_sales set invoice_no = %(inv)s, total = %(t)s, amount_received = %(r)s, needs_install = %(i)s, installation_status = %(is)s, flags = %(fl)s where id = %(id)s returning *",
                    {"inv": invoice_no, "t": total, "r": received, "i": install, "is": "pending" if install else "not_needed", "fl": sorted(set(fl)), "id": s["id"]})
    if p_lead:
        fetch("update kwd_fr_leads set status = 'won', last_update_at = now() where id = %(i)s returning 1", {"i": p_lead})
    from kwd.rules import RULES
    RULES["fr_sales"]._audit(ctx, "INSERT", None, row, row["id"])
    return s["id"]


def cancel_sale(ctx, p_sale, p_reason):
    if ctx.role != HO:
        raise ApiError("Only Head Office can cancel a sale")
    if len(trim(p_reason)) < 5:
        raise ApiError("Say why this sale is cancelled")
    sl = fetch_one("select * from kwd_fr_sales where id = %(i)s for update", {"i": p_sale})
    if not sl:
        raise ApiError("Sale not found")
    if sl["status"] == "cancelled":
        raise ApiError("Already cancelled")
    row = fetch_one("update kwd_fr_sales set status = 'cancelled', cancel_reason = %(r)s, cancelled_by = %(u)s, cancelled_at = now() where id = %(i)s returning *",
                    {"r": trim(p_reason), "u": ctx.uid, "i": p_sale})
    for i in fetch("select product_id, qty from kwd_fr_sale_items where sale_id = %(i)s", {"i": p_sale}):
        add_stock_move(ctx.uid, sl["franchise_id"], i["product_id"], i["qty"], "sale_cancel", p_sale, "Sale cancelled: " + trim(p_reason))
    if sl["lead_id"]:
        fetch("update kwd_fr_leads set status = 'negotiating' where id = %(i)s and status = 'won' returning 1", {"i": sl["lead_id"]})
    from kwd.rules import RULES
    RULES["fr_sales"]._audit(ctx, "UPDATE", sl, row, row["id"])
    return None


def receive_payment(ctx, p_sale, p_amount, p_method, p_reference=None):
    """Record an additional customer payment against an active franchise invoice (Head Office only)."""
    from decimal import InvalidOperation

    if ctx.role != HO:
        raise ApiError("Only Head Office can record invoice payments")
    try:
        amount = Decimal(str(p_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ApiError("Enter a valid payment amount")
    if amount <= 0:
        raise ApiError("Payment amount must be greater than zero")
    if p_method not in ("cash", "upi", "bank_transfer", "cheque", "card", "other"):
        raise ApiError("Choose a payment method")
    sale = fetch_one("select * from kwd_fr_sales where id = %(i)s for update", {"i": p_sale})
    if not sale or sale["status"] != "active":
        raise ApiError("Active invoice not found")
    due = Decimal(str(sale["total"])) - Decimal(str(sale["amount_received"]))
    if due <= 0:
        raise ApiError("This invoice has no balance due")
    if amount > due:
        raise ApiError(f"Payment cannot exceed the balance due ({due})")
    receipt = fetch_one(
        "insert into kwd_fr_payment_receipts (sale_id, amount, method, reference, received_by) "
        "values (%(s)s, %(a)s, %(m)s, %(r)s, %(u)s) returning *",
        {"s": sale["id"], "a": amount, "m": p_method, "r": trim(p_reference) or None, "u": ctx.uid},
    )
    row = fetch_one("update kwd_fr_sales set amount_received = amount_received + %(a)s where id = %(i)s returning *",
                    {"a": amount, "i": sale["id"]})
    from kwd.rules import RULES
    RULES["fr_sales"]._audit(ctx, "UPDATE", sale, row, row["id"])
    return receipt["id"]
