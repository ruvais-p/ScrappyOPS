"""Billing. Two kinds of tax invoice:
  purchase  a franchise sells stock to HQ. The supervisor makes it from a load for HQ that has been finalized: the kg and the price per
            kg are already fixed on the load, and GST is added on top.
  sale      HQ sells stock to a buyer. HQ can only sell what it holds: everything released to it, minus what it has already sold.
Invoices are numbered per series and financial year (KKD/2627/0001, HQ/2627/0001). Once issued, an invoice changes only by being
marked paid (HQ) or cancelled with a reason; cancelling puts the stock and the load back so they can be invoiced again."""
import re
from datetime import date as date_cls, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.models import (Buyer, Counter, Franchise, HqDispatch, Invoice, InvoiceLine, ScrapItem, next_number)
from core.services.common import (ApiError, advisory_lock, btrim, fetch, fetch_one, fixed_decimal, hq_log, nullify, round_half_up, scalar,
                                  show_num)
from core.services.registry import rpc

IST = ZoneInfo("Asia/Kolkata")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
HSN_RE = re.compile(r"^\d{4,8}$")
HQ_COMPANY = {"company_name": "SCRAPPY INNOVATIONS PVT LTD.", "address": "HO. WP 18/108 - H,J,K\n1st FLOOR SAJ BUILDING\nMANJERI ROAD WANDOOR\nPIN 679328",
              "phone": "+918592964750", "gstin": "32ABFCS0169R1ZX", "email": "info@scrappyinnovations.com", "state": "Kerala"}
EPS = Decimal("0.0001")
MAX_INVOICE_LINES = 100


def _id(value, label):
    boolean = isinstance(value, bool)
    value = str(value)
    if boolean or len(value) > 18 or not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise ApiError(f"Choose a valid {label}.")
    return int(value)


def _text(value, label, limit):
    value = btrim(value)
    if len(value) > limit:
        raise ApiError(f"The {label} is too long.")
    return value or None


def _franchise_scope(ctx, requested):
    value = ctx.fr_scope(requested)
    return _id(value, "franchise") if value is not None else None


def _limit(value, default, maximum):
    if value in (None, ""):
        return default
    return min(_id(value, "limit"), maximum)


def today():
    return datetime.now(IST).date()


def financial_year(d):
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def next_code(series, d):
    """KKD/2627/0001: the next number of that series in that financial year."""
    key = f"inv:{series}:{financial_year(d)}"
    Counter.objects.get_or_create(name=key)
    return f"{series}/{financial_year(d)}/{next_number(key):04d}"


def company():
    """HQ's own details (the company settings the franchise billing already uses), with the defaults when none were saved."""
    row = fetch_one("select * from kwd_fr_company_settings where id = 1") or {}
    return {k: (row.get(k) or HQ_COMPANY[k]) for k in HQ_COMPANY}


def party_details(party=None):
    """Capture the printed identity at issue time, independently of future edits."""
    if party is None:
        details = company()
        details["name"] = details.pop("company_name")
        return details
    return {key: getattr(party, key) for key in ("name", "address", "phone", "email", "gstin", "state")}


def pick_date(value, floor=None):
    if value in (None, ""):
        return today()
    try:
        d = date_cls.fromisoformat(str(value)[:10])
    except ValueError:
        raise ApiError("Enter a valid invoice date.")
    if d > today():
        raise ApiError("The invoice date cannot be in the future.")
    if floor and d < floor:
        raise ApiError("The invoice date cannot be before the load was finalized.")
    return d


def line_values(kg, rate, gst):
    taxable = round_half_up(kg * rate, 2)
    gst_amount = round_half_up(taxable * gst / 100, 2)
    return taxable, gst_amount, taxable + gst_amount


def hq_in_hand(item_id):
    """Kg HQ holds of a material: everything released to it, minus what it has sold on issued invoices."""
    return scalar("""
      select coalesce((select sum(kg) from hq_releases where item_id = %(i)s), 0)
           - coalesce((select sum(l.kg) from invoice_lines l join invoices v on v.id = l.invoice_id
                       where l.item_id = %(i)s and v.kind = 'sale' and v.status = 'issued'), 0)""", {"i": item_id})


def _gstin(value):
    g = btrim(value).upper().replace(" ", "")
    if g and not GSTIN_RE.match(g):
        raise ApiError("Enter a valid 15-character GSTIN, or leave it empty.")
    return g or None


def _need(ctx, *roles, message="Not allowed."):
    if ctx.role not in roles:
        raise ApiError(message)


# ---------------------------------------------------------------------------------------------- materials, details, buyers
@rpc()
def bill_items(ctx):
    """The materials with the HSN code and GST rate used on invoices."""
    _need(ctx, "hq", "supervisor", message="Only the supervisor or HQ can see this.")
    return fetch("select id, name, active, hsn_code, gst_percent from scrap_items where active order by name")


@rpc()
def hq_set_item_tax(ctx, p_item_id, p_hsn=None, p_gst=0):
    _need(ctx, "hq", message="Only HQ can set the HSN code and GST rate.")
    item = ScrapItem.objects.filter(pk=_id(p_item_id, "material"), active=True).first()
    if item is None:
        raise ApiError("Unknown material.")
    hsn = btrim(p_hsn)
    if hsn and not HSN_RE.match(hsn):
        raise ApiError("The HSN code is 4 to 8 digits.")
    gst = fixed_decimal(p_gst, "GST rate", 2, 5)
    if gst < 0 or gst > 100:
        raise ApiError("Enter a GST rate from 0 to 100.")
    old = {"hsn": item.hsn_code, "gst": float(item.gst_percent)}
    item.hsn_code, item.gst_percent = hsn or None, gst
    item.save(update_fields=["hsn_code", "gst_percent"])
    hq_log(ctx, "item_tax_set", item.name, {"old": old, "new": {"hsn": item.hsn_code, "gst": float(gst)}})
    return item.name


@rpc()
def bill_details(ctx, p_franchise=None):
    """HQ's company details and a franchise's billing details (a supervisor sees their own franchise)."""
    _need(ctx, "hq", "supervisor", message="Only the supervisor or HQ can see this.")
    f = _franchise_scope(ctx, p_franchise)
    fr = fetch_one("select id, code, name, gstin, address, phone, email, state from franchises where id = %(f)s", {"f": f}) if f else None
    return {"company": company(), "franchise": fr}


@rpc()
def set_billing_details(ctx, p_franchise=None, p_gstin=None, p_address=None, p_phone=None, p_email=None, p_state=None):
    """What a franchise's own invoices to HQ show as the seller."""
    _need(ctx, "hq", "supervisor", message="Only the supervisor or HQ can change the billing details.")
    f = _franchise_scope(ctx, p_franchise)
    fr = Franchise.objects.select_for_update().filter(pk=f).first() if f else None
    if fr is None:
        raise ApiError("Choose the franchise.")
    fr.gstin = _gstin(p_gstin)
    fr.address = _text(p_address, "address", 2000)
    fr.phone = _text(p_phone, "phone", 40)
    fr.email = _text(p_email, "email", 254)
    fr.state = _text(p_state, "state", 100)
    fr.save(update_fields=["gstin", "address", "phone", "email", "state"])
    hq_log(ctx, "billing_details_saved", fr.code, None, fr.pk)
    return fr.code


@rpc()
def hq_buyers(ctx):
    _need(ctx, "hq", message="Only HQ can see the buyers.")
    return fetch("""select b.id, b.name, b.gstin, b.address, b.phone, b.email, b.state, b.active,
                           (select count(*) from invoices v where v.buyer_id = b.id and v.status = 'issued') as invoices
                    from buyers b order by lower(b.name)""")


@rpc()
def hq_save_buyer(ctx, p_name, p_gstin=None, p_address=None, p_phone=None, p_email=None, p_state=None, p_active=True, p_buyer_id=None):
    _need(ctx, "hq", message="Only HQ can add buyers.")
    name = re.sub(r"\s+", " ", btrim(p_name))
    if not 2 <= len(name) <= 200:
        raise ApiError("Enter the buyer's name.")
    if not isinstance(p_active, bool):
        raise ApiError("Choose whether the buyer is active.")
    if p_buyer_id is not None:
        p_buyer_id = _id(p_buyer_id, "buyer")
    if Buyer.objects.filter(name__iexact=name).exclude(pk=p_buyer_id or 0).exists():
        raise ApiError(f"A buyer named {name} already exists.")
    values = dict(name=name, gstin=_gstin(p_gstin), address=_text(p_address, "address", 2000),
                  phone=_text(p_phone, "phone", 40), email=_text(p_email, "email", 254),
                  state=_text(p_state, "state", 100), active=p_active)
    if p_buyer_id:
        b = Buyer.objects.select_for_update().filter(pk=p_buyer_id).first()
        if b is None:
            raise ApiError("Buyer not found.")
        for k, v in values.items():
            setattr(b, k, v)
        b.save()
    else:
        b = Buyer.objects.create(created_by_id=ctx.uid, **values)
    hq_log(ctx, "buyer_saved", b.name, {"id": b.pk})
    return b.pk


# ---------------------------------------------------------------------------------------------- the franchise invoices HQ
@rpc()
def bill_pending_invoices(ctx, p_franchise=None):
    """Finalized loads for HQ that the franchise has not invoiced yet, with what the invoice will say."""
    _need(ctx, "hq", "supervisor", message="Only the supervisor or HQ can see this.")
    f = _franchise_scope(ctx, p_franchise)
    loads = fetch("""
      select d.id, d.code, d.franchise_id, fr.code as franchise_code, fr.name as franchise_name, d.vehicle_no, d.reviewed_at as finalized_at
      from hq_dispatches d join franchises fr on fr.id = d.franchise_id
      where d.status = 'finalized' and (%(f)s::integer is null or d.franchise_id = %(f)s::integer)
        and not exists (select 1 from invoices v where v.dispatch_id = d.id and v.status = 'issued')
      order by d.id desc""", {"f": f})
    if not loads:
        return []
    lines = fetch("""
      select l.dispatch_id, i.name as item_name, i.hsn_code, i.gst_percent, l.kg, l.price_per_kg as rate, l.amount as taxable
      from hq_dispatch_lines l join scrap_items i on i.id = l.item_id where l.dispatch_id = any(%(ids)s) order by l.id""", {"ids": [x["id"] for x in loads]})
    by = {}
    for ln in lines:
        ln["gst_amount"] = round_half_up(ln["taxable"] * ln["gst_percent"] / 100, 2)
        ln["total"] = ln["taxable"] + ln["gst_amount"]
        by.setdefault(ln["dispatch_id"], []).append(ln)
    for x in loads:
        x["lines"] = by.get(x["id"], [])
        x["taxable"] = sum((l["taxable"] for l in x["lines"]), Decimal(0))
        x["gst_amount"] = sum((l["gst_amount"] for l in x["lines"]), Decimal(0))
        x["total"] = x["taxable"] + x["gst_amount"]
    return loads


@rpc()
def bill_create_purchase_invoice(ctx, p_dispatch_id, p_invoice_date=None, p_note=None):
    """The franchise's invoice to HQ for a finalized load: the same kg and price per kg as the load, GST added from the material's rate."""
    _need(ctx, "hq", "supervisor", message="Only the supervisor can make the franchise's invoice.")
    d = HqDispatch.objects.select_for_update().filter(pk=_id(p_dispatch_id, "load")).first()
    if d is None or not ctx.fr_ok(d.franchise_id):
        raise ApiError("Load not found.")
    if d.status != "finalized":
        raise ApiError("Only a finalized load can be invoiced.")
    if Invoice.objects.filter(dispatch_id=d.pk, status="issued").exists():
        raise ApiError("This load already has an invoice.")
    when = pick_date(p_invoice_date, floor=d.reviewed_at.astimezone(IST).date() if d.reviewed_at else None)
    fr = Franchise.objects.get(pk=d.franchise_id)
    rows, sub, gst = [], Decimal(0), Decimal(0)
    for ln in d.lines.select_related("item").order_by("id"):
        if ln.price_per_kg is None or ln.amount is None:
            raise ApiError("This load has no price. Ask HQ to set the price and finalize it again.")
        g = ln.item.gst_percent
        gst_amount = round_half_up(ln.amount * g / 100, 2)
        rows.append(dict(item_id=ln.item_id, item_name=ln.item.name, hsn_code=ln.item.hsn_code, kg=ln.kg, rate=ln.price_per_kg, gst_percent=g, taxable=ln.amount,
                         gst_amount=gst_amount, total=ln.amount + gst_amount))
        sub, gst = sub + ln.amount, gst + gst_amount
    if not rows:
        raise ApiError("A load with no materials cannot be invoiced.")
    fixed_decimal(sub + gst, "invoice total", 2, 14)
    inv = Invoice.objects.create(code=next_code(fr.code, when), kind="purchase", franchise_id=fr.pk, dispatch_id=d.pk, invoice_date=when, vehicle_no=d.vehicle_no,
                                 seller_details=party_details(fr), buyer_details=party_details(),
                                 note=nullify(p_note), subtotal=sub, gst_total=gst, total=sub + gst, created_by_id=ctx.uid)
    InvoiceLine.objects.bulk_create([InvoiceLine(invoice_id=inv.pk, **r) for r in rows])
    hq_log(ctx, "invoice_issued", inv.code, {"load": d.code, "total": float(inv.total)}, fr.pk)
    return {"id": inv.pk, "code": inv.code, "total": inv.total}


# ---------------------------------------------------------------------------------------------- HQ sells to a buyer
@rpc()
def hq_stock_summary(ctx):
    """What HQ holds of each material: released to it by the franchises, sold to buyers, and still in hand."""
    _need(ctx, "hq", message="Only HQ can see its stock.")
    return fetch("""
      select i.id as item_id, i.name as item_name, i.hsn_code, i.gst_percent,
             coalesce((select sum(kg) from hq_releases r where r.item_id = i.id), 0) as received_kg,
             coalesce((select sum(l.kg) from invoice_lines l join invoices v on v.id = l.invoice_id
                       where l.item_id = i.id and v.kind = 'sale' and v.status = 'issued'), 0) as sold_kg
      from scrap_items i where i.active order by i.name""")


@rpc()
def bill_create_sale_invoice(ctx, p_buyer_id, p_lines, p_invoice_date=None, p_vehicle_no=None, p_note=None):
    """p_lines = [{"item_id": 1, "kg": 40, "rate": 21.5, "gst_percent": 18}, ...]. HQ cannot sell more than it holds."""
    _need(ctx, "hq", message="Only HQ can sell its stock.")
    buyer = Buyer.objects.filter(pk=_id(p_buyer_id, "buyer"), active=True).first()
    if buyer is None:
        raise ApiError("Choose the buyer.")
    if not isinstance(p_lines, list) or not p_lines:
        raise ApiError("Add at least one material.")
    if len(p_lines) > MAX_INVOICE_LINES:
        raise ApiError(f"An invoice can have at most {MAX_INVOICE_LINES} lines.")
    when = pick_date(p_invoice_date)
    wanted, per_item = [], {}
    for ln in p_lines:
        if not isinstance(ln, dict):
            raise ApiError("Every invoice line must be an object.")
        item = ScrapItem.objects.filter(pk=_id(ln.get("item_id"), "material"), active=True).first()
        if item is None:
            raise ApiError("Choose the material on every line.")
        kg = fixed_decimal(ln.get("kg"), "kg", 3, 14)
        rate = fixed_decimal(ln.get("rate"), "rate", 2, 12)
        gst = fixed_decimal(ln["gst_percent"], "GST rate", 2, 5) if ln.get("gst_percent") not in (None, "") else item.gst_percent
        if kg <= 0 or rate <= 0:
            raise ApiError(f"Enter the kg and the rate for {item.name}.")
        if gst < 0 or gst > 100:
            raise ApiError("Enter a GST rate from 0 to 100.")
        wanted.append((item, kg, rate, gst))
        per_item[item.pk] = per_item.get(item.pk, Decimal(0)) + kg
    for item_id in sorted(per_item):
        advisory_lock(item_id, 0)                              # one sale at a time per material, so two invoices cannot sell the same stock
    for item_id, kg in per_item.items():
        have = hq_in_hand(item_id)
        if kg > have + EPS:
            raise ApiError(f"Not enough {ScrapItem.objects.get(pk=item_id).name} in HQ stock. In hand: {show_num(have, 1)} kg.")
    rows, sub, gst_sum = [], Decimal(0), Decimal(0)
    for item, kg, rate, gst in wanted:
        taxable, gst_amount, total = line_values(kg, rate, gst)
        rows.append(dict(item_id=item.pk, item_name=item.name, hsn_code=item.hsn_code, kg=kg, rate=rate, gst_percent=gst, taxable=taxable, gst_amount=gst_amount, total=total))
        sub, gst_sum = sub + taxable, gst_sum + gst_amount
    fixed_decimal(sub + gst_sum, "invoice total", 2, 14)
    inv = Invoice.objects.create(code=next_code("HQ", when), kind="sale", buyer_id=buyer.pk, invoice_date=when, vehicle_no=nullify(p_vehicle_no),
                                 seller_details=party_details(), buyer_details=party_details(buyer),
                                 note=nullify(p_note), subtotal=sub, gst_total=gst_sum, total=sub + gst_sum, created_by_id=ctx.uid)
    InvoiceLine.objects.bulk_create([InvoiceLine(invoice_id=inv.pk, **r) for r in rows])
    hq_log(ctx, "invoice_issued", inv.code, {"buyer": buyer.name, "total": float(inv.total)})
    return {"id": inv.pk, "code": inv.code, "total": inv.total}


# ---------------------------------------------------------------------------------------------- the list, payment, cancelling
@rpc()
def bill_invoices(ctx, p_kind=None, p_from=None, p_to=None, p_franchise=None, p_limit=300):
    """Invoices, newest first, with their lines. HQ sees all of them; a supervisor sees their own franchise's invoices to HQ."""
    _need(ctx, "hq", "supervisor", message="Only the supervisor or HQ can see invoices.")
    f = _franchise_scope(ctx, p_franchise)
    kind = p_kind if p_kind in ("purchase", "sale") else None
    if ctx.role != "hq":
        kind = "purchase"
    heads = fetch("""
      select v.id, v.code, v.kind, v.invoice_date, v.status, v.payment_status, v.paid_on, v.payment_ref, v.vehicle_no, v.note, v.subtotal, v.gst_total, v.total,
             v.cancel_reason, v.created_at, v.franchise_id, fr.code as franchise_code,
             case when v.kind = 'purchase' then v.seller_details->>'name' end as franchise_name, v.dispatch_id, d.code as load_code,
             v.buyer_id, case when v.kind = 'sale' then v.buyer_details->>'name' end as buyer_name, p.full_name as created_by_name
      from invoices v left join franchises fr on fr.id = v.franchise_id left join buyers b on b.id = v.buyer_id
           left join hq_dispatches d on d.id = v.dispatch_id join profiles p on p.id = v.created_by
      where (%(k)s::text is null or v.kind = %(k)s::text) and (%(f)s::integer is null or v.franchise_id = %(f)s::integer)
        and (%(a)s::date is null or v.invoice_date >= %(a)s::date) and (%(z)s::date is null or v.invoice_date <= %(z)s::date)
      order by v.invoice_date desc, v.id desc limit %(n)s""",
                  {"k": kind, "f": f, "a": p_from or None, "z": p_to or None, "n": _limit(p_limit, 300, 1000)})
    if not heads:
        return []
    lines = fetch("""select l.invoice_id, l.item_id, l.item_name, l.hsn_code, l.kg, l.rate, l.gst_percent, l.taxable, l.gst_amount, l.total
                     from invoice_lines l join scrap_items i on i.id = l.item_id where l.invoice_id = any(%(ids)s) order by l.id""", {"ids": [h["id"] for h in heads]})
    by = {}
    for ln in lines:
        by.setdefault(ln.pop("invoice_id"), []).append(ln)
    for h in heads:
        h["lines"] = by.get(h["id"], [])
        h["total_kg"] = sum((x["kg"] for x in h["lines"]), Decimal(0))
    return heads


def _invoice_for(ctx, invoice_id, lock=False):
    inv = (Invoice.objects.select_for_update() if lock else Invoice.objects).filter(pk=_id(invoice_id, "invoice")).first()
    if inv is None:
        raise ApiError("Invoice not found.")
    if ctx.role == "hq":
        return inv
    if ctx.role == "supervisor" and inv.kind == "purchase" and ctx.fr_ok(inv.franchise_id):
        return inv
    raise ApiError("Invoice not found.")


@rpc()
def bill_mark_paid(ctx, p_invoice_id, p_paid_on=None, p_reference=None):
    """HQ records that a purchase invoice was paid to the franchise, or that a buyer paid HQ's sale invoice."""
    _need(ctx, "hq", message="Only HQ can record a payment.")
    inv = _invoice_for(ctx, p_invoice_id, lock=True)
    if inv.status != "issued":
        raise ApiError("This invoice was cancelled.")
    if inv.payment_status == "paid":
        raise ApiError("This invoice is already marked paid.")
    inv.payment_status, inv.paid_on, inv.payment_ref = "paid", pick_date(p_paid_on), nullify(p_reference)
    inv.save(update_fields=["payment_status", "paid_on", "payment_ref"])
    hq_log(ctx, "invoice_paid", inv.code, {"on": str(inv.paid_on), "ref": inv.payment_ref}, inv.franchise_id)
    return inv.code


@rpc()
def bill_cancel_invoice(ctx, p_invoice_id, p_reason):
    """Cancel an invoice that is not paid. The stock comes back to HQ (a sale) or the load can be invoiced again (a purchase)."""
    _need(ctx, "hq", "supervisor", message="Not allowed.")
    inv = _invoice_for(ctx, p_invoice_id, lock=True)
    if inv.status != "issued":
        raise ApiError("This invoice was already cancelled.")
    if inv.payment_status == "paid":
        raise ApiError("A paid invoice cannot be cancelled.")
    if len(btrim(p_reason)) < 3:
        raise ApiError("Say why this invoice is cancelled.")
    from django.utils import timezone
    inv.status, inv.cancel_reason, inv.cancelled_at = "cancelled", btrim(p_reason), timezone.now()
    inv.save(update_fields=["status", "cancel_reason", "cancelled_at"])
    hq_log(ctx, "invoice_cancelled", inv.code, {"reason": inv.cancel_reason}, inv.franchise_id)
    return inv.code
