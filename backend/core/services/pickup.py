"""The collector's day: start a pickup, weigh the scrap, lock and send the bill, get the customer's agreement,
pay, and end the route. Rules are the same as the database functions they replace."""
import re
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core.models import (Bill, BillItem, CashLedger, Customer, Lead, Load, LoadWeighing, Profile, ScrapItem,
                         CashSettlement)
from core.services.common import (ApiError, SESSION_MSG, blank, btrim, dec, fetch, fetch_one, hq_log, nullify,
                                  round_half_up, scalar, show_num)
from core.services.registry import rpc

FAIL_REASONS = ["Customer not at home", "Customer cancelled", "Phone not reachable", "Wrong address or location",
                "No scrap, or too little", "Customer did not agree to the rate", "Vehicle or other problem on my side", "Other"]


def _need_driver(ctx, msg="Only drivers can do this."):
    if ctx.role != "driver":
        raise ApiError(msg)


def _my_bill(ctx, bill_id):
    """The collector's own bill, locked for this request. Anyone else's bill is refused."""
    if not ctx.session_valid():
        raise ApiError(SESSION_MSG)
    b = (Bill.objects.select_for_update(of=("self",))
         .filter(pk=bill_id, load__driver_id=ctx.uid).first())
    if b is None:
        raise ApiError("This bill is not yours.")
    return b


def _bill_totals(bill_id):
    agg = BillItem.objects.filter(bill_id=bill_id).aggregate(kg=Sum("qty_kg"), amt=Sum("amount"))
    return agg["kg"], agg["amt"]


# ---------------------------------------------------------------------------------------------- my leads
@rpc()
def my_leads(ctx):
    """The collector's list: own leads that are not cancelled or still waiting for a driver."""
    return fetch("""
      select l.id as lead_id, l.code as lead_code, l.slot, l.status, l.items_said,
             c.name as customer_name, c.address, c.area,
             case when c.upi_id is null then null
                  else left(c.upi_id, 3) || '••••' || substring(c.upi_id from position('@' in c.upi_id)) end as upi_masked,
             b.id as bill_id, b.bill_no, b.status as bill_status, bt.total_kg, bt.total_amount, b.payment_method,
             l.latitude, l.longitude, c.phone, l.fail_reason, l.fail_note, l.failed_at
      from leads l
      join customers c on c.id = l.customer_id
      left join bills b on b.lead_id = l.id
      left join bill_totals bt on bt.bill_id = b.id
      where l.driver_id = %(uid)s and %(ok)s and l.status not in ('cancelled', 'unassigned')
      order by l.status in ('closed', 'failed'), l.slot nulls last, l.id
    """, {"uid": ctx.uid, "ok": ctx.session_valid()})


# ---------------------------------------------------------------------------------------------- start / weigh
@rpc()
def start_pickup(ctx, p_lead_id):
    _need_driver(ctx, "Only drivers can start pickups.")
    lead = Lead.objects.select_for_update().filter(pk=p_lead_id, driver_id=ctx.uid).first()
    if lead is None:
        raise ApiError("This lead is not assigned to you.")
    if lead.status not in ("scheduled", "in_progress"):
        raise ApiError(f"This lead is already {lead.status}.")
    existing = Bill.objects.filter(lead_id=lead.pk).values_list("pk", flat=True).first()
    if existing:
        return existing
    load = Load.objects.select_for_update().filter(driver_id=ctx.uid, status="open").first()
    if load is None:
        prof = ctx.profile
        if prof.franchise_id is None:
            raise ApiError("This person is not assigned to a franchise.")
        load = Load.objects.create(driver_id=ctx.uid, franchise_id=prof.franchise_id, vehicle_no=prof.vehicle_no)
    bill = Bill.objects.create(lead_id=lead.pk, load_id=load.pk)
    lead.status = "in_progress"
    lead.save(update_fields=["status"])
    return bill.pk


@rpc()
def set_bill_item(ctx, p_bill_id, p_item_id, p_qty_kg=None, p_photo_url=None, p_typed=False):
    """Set the kg of one material on a draft bill. The rate always comes from HQ. A weight of 0 (or empty) removes the line."""
    b = _my_bill(ctx, p_bill_id)
    if b.status != "draft":
        raise ApiError("Bill is locked after sending. Ask HQ to make changes.")
    qty = Decimal(0) if p_qty_kg in (None, "") else dec(p_qty_kg, "weight")
    if qty < 0 or qty > 100000:
        raise ApiError("Enter a weight between 0 and 100000 kg.")
    if qty == 0:
        BillItem.objects.filter(bill_id=b.pk, item_id=p_item_id).delete()
        return None
    item = ScrapItem.objects.filter(pk=p_item_id, active=True).first()
    if item is None:
        raise ApiError("Unknown material.")
    rate = scalar("select rate_per_kg from current_rates where item_id = %(i)s", {"i": item.pk})
    if rate is None:
        raise ApiError("No HQ rate set for this item.")
    qty = qty.quantize(Decimal("0.001"))
    if qty == 0:
        raise ApiError("Enter a weight between 0 and 100000 kg.")
    BillItem.objects.update_or_create(
        bill_id=b.pk, item_id=item.pk,
        defaults={"qty_kg": qty, "rate_per_kg": rate, "photo_url": p_photo_url, "typed_by_hand": bool(p_typed)})
    return None


# ---------------------------------------------------------------------------------------------- send / whatsapp
def _customer_of(bill):
    return fetch_one("select c.phone, c.name from leads l join customers c on c.id = l.customer_id where l.id = %(l)s",
                     {"l": bill.lead_id})


def _whatsapp_number(phone):
    n = re.sub(r"\D", "", phone or "")
    if len(n) == 10:
        n = "91" + n
    return n


@rpc()
def send_bill(ctx, p_bill_id):
    """Lock the bill (no more changes) and mark it sent. Returns the customer's number and a plain summary."""
    b = _my_bill(ctx, p_bill_id)
    if b.status != "draft":
        raise ApiError("This bill has already been sent.")
    items = list(BillItem.objects.filter(bill_id=b.pk).select_related("item").order_by("item__name"))
    if not items:
        raise ApiError("Add at least one item before sending.")
    b.status = "sent"
    b.sent_at = timezone.now()
    b.save(update_fields=["status", "sent_at"])
    cust = _customer_of(b)
    lines = "\n".join(f"{i.item.name}: {format(i.qty_kg, 'f')} kg x Rs {format(i.rate_per_kg, 'f')} = Rs {format(i.amount, 'f')}" for i in items)
    kg = sum((i.qty_kg for i in items), Decimal(0))
    total = sum((i.amount for i in items), Decimal(0))
    msg = (f"Scrappy bill {b.bill_no}\nHello {cust['name']},\n\n{lines}\n\nTotal: {format(kg, 'f')} kg, Rs {format(total, 'f')}"
           f"\n\nRates are fixed by Scrappy HQ. Questions? Reply to this message.")
    return [{"whatsapp_number": _whatsapp_number(cust["phone"]), "message": msg}]


def indian_amount(d):
    """1234567.5 -> '12,34,567.50'; whole rupees lose the '.00'."""
    d = round_half_up(d or 0, 2)
    neg = d < 0
    whole, frac = format(abs(d), "f").split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    s = f"{whole}.{frac}"
    s = re.sub(r"\.00$", "", s)
    return ("-" if neg else "") + (s or "0")


def trim_zeros(d):
    s = format(round_half_up(d or 0, 2), "f")
    s = re.sub(r"0+$", "", s)
    s = re.sub(r"\.$", "", s)
    return s or "0"


@rpc()
def bill_whatsapp(ctx, p_bill_id):
    """The WhatsApp message for a locked bill: the customer's number and a short, friendly summary."""
    b = _my_bill(ctx, p_bill_id)
    if b.status != "sent":
        raise ApiError("The bill must be locked before sending it.")
    cust = _customer_of(b)
    kg, total = _bill_totals(b.pk)
    first = (btrim(cust["name"]).split(" ")[0] if btrim(cust["name"]) else "") or "there"
    msg = (f"Hi {first}, thank you for choosing Scrappy! ♻️\n\n"
           f"Your scrap bill is ready.\n"
           f"Bill no: {b.bill_no}\n"
           f"Weight: {trim_zeros(kg)} kg\n"
           f"You will receive: *Rs {indian_amount(total)}*")
    return [{"whatsapp_number": _whatsapp_number(cust["phone"]), "message": msg}]


@rpc()
def mark_bill_shared(ctx, p_bill_id):
    """The collector opened WhatsApp to send the bill. The customer can be asked to agree only after this."""
    b = _my_bill(ctx, p_bill_id)
    if b.status == "draft":
        raise ApiError("Lock and send the bill first.")
    if b.whatsapp_opened_at is None:
        b.whatsapp_opened_at = timezone.now()
        b.save(update_fields=["whatsapp_opened_at"])
    return None


@rpc()
def confirm_bill(ctx, p_bill_id, p_proof_url=None):
    b = _my_bill(ctx, p_bill_id)
    if b.status != "sent":
        raise ApiError("Send the bill to the customer first.")
    if b.whatsapp_opened_at is None:
        raise ApiError("Send the bill to the customer on WhatsApp first.")
    b.status = "confirmed"
    b.confirmed_at = timezone.now()
    b.confirm_proof_url = p_proof_url
    b.save(update_fields=["status", "confirmed_at", "confirm_proof_url"])
    return None


# ---------------------------------------------------------------------------------------------- pay
@rpc()
def pay_bill(ctx, p_bill_id, p_method, p_upi_ref=None):
    """Pay the customer. UPI needs the transaction (UTR) number. Cash comes out of the collector's cash in hand, and
    can never take it below zero."""
    b = _my_bill(ctx, p_bill_id)
    if b.status != "confirmed":
        raise ApiError("The customer must confirm the bill before payment.")
    if p_method not in ("upi", "cash"):
        raise ApiError("Choose UPI or cash.")
    _kg, total = _bill_totals(b.pk)
    total = total or Decimal(0)
    if p_method == "upi":
        if len(btrim(p_upi_ref)) < 6:
            raise ApiError("Enter the UPI transaction (UTR) number.")
    else:
        # one cash movement at a time per collector, so two payments can never spend the same rupees
        prof = Profile.objects.select_for_update().get(pk=ctx.uid)
        bal = CashLedger.objects.filter(driver_id=ctx.uid).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        if bal - total < 0:
            raise ApiError(f"Not enough cash in hand (₹{format(bal, 'f')}). Use UPI.")
        CashLedger.objects.create(driver_id=ctx.uid, entry_type="cash_payout", amount=-total, bill_id=b.pk,
                                  note=f"Cash paid for {b.bill_no}", created_by_id=ctx.uid, franchise_id=prof.franchise_id)
    now = timezone.now()
    b.status = "paid"
    b.payment_method = p_method
    b.upi_ref = nullify(p_upi_ref)
    b.paid_at = now
    b.save(update_fields=["status", "payment_method", "upi_ref", "paid_at"])
    Lead.objects.filter(pk=b.lead_id).update(status="closed", closed_at=now)
    return None


# ---------------------------------------------------------------------------------------------- end route / could not complete
@rpc()
def end_route(ctx):
    ctx.need_session()
    load = Load.objects.select_for_update().filter(driver_id=ctx.uid, status="open").first()
    if load is None:
        raise ApiError("You have no open load.")
    if Bill.objects.filter(load_id=load.pk).exclude(status="paid").exists():
        raise ApiError("Finish or pay all started pickups before ending the route.")
    load.status = "submitted"
    load.submitted_at = timezone.now()
    load.save(update_fields=["status", "submitted_at"])
    return load.code


@rpc()
def fail_pickup(ctx, p_lead_id, p_reason, p_note=None):
    """The collector could not complete this pickup. A draft bill is thrown away; a bill already sent cannot be."""
    _need_driver(ctx)
    note = nullify(p_note)
    if p_reason is None or p_reason not in FAIL_REASONS:
        raise ApiError("Choose a reason.")
    if p_reason == "Other" and note is None:
        raise ApiError('Write a short note for "Other".')
    if note is not None and len(note) > 300:
        raise ApiError("Keep the note under 300 characters.")
    lead = Lead.objects.select_for_update().filter(pk=p_lead_id, driver_id=ctx.uid).first()
    if lead is None:
        raise ApiError("This lead is not assigned to you.")
    if lead.status not in ("scheduled", "in_progress"):
        raise ApiError(f"This lead is already {lead.status}.")
    kg, n = Decimal(0), 0
    bill = Bill.objects.select_for_update().filter(lead_id=lead.pk).first()
    if bill is not None:
        if bill.status != "draft":
            raise ApiError("The bill was already sent to the customer. Finish this pickup or ask HQ to cancel the bill.")
        agg = BillItem.objects.filter(bill_id=bill.pk).aggregate(kg=Sum("qty_kg"))
        kg = agg["kg"] or Decimal(0)
        n = BillItem.objects.filter(bill_id=bill.pk).count()
        load_id = bill.load_id
        BillItem.objects.filter(bill_id=bill.pk).delete()
        bill.delete()
        # an empty route that was only started for this pickup disappears with it
        if (not Bill.objects.filter(load_id=load_id).exists()
                and not LoadWeighing.objects.filter(load_id=load_id).exists()
                and not CashSettlement.objects.filter(load_id=load_id).exists()):
            Load.objects.filter(pk=load_id, status="open", driver_id=ctx.uid).delete()
    lead.status = "failed"
    lead.fail_reason = p_reason
    lead.fail_note = note
    lead.failed_at = timezone.now()
    lead.save(update_fields=["status", "fail_reason", "fail_note", "failed_at"])
    hq_log(ctx, "lead_failed", lead.code,
           {"reason": p_reason, "note": note, "driver": str(ctx.uid), "draft_kg_discarded": float(kg), "draft_items_discarded": n},
           lead.franchise_id)
    return lead.code
