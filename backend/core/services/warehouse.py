"""The warehouse: weigh each load against its bills, keep stock per franchise, serve HQ's requirements, count and verify
collector cash, and hand leads to collectors. Rules are the same as the database functions they replace."""
from datetime import date as date_cls
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from core.models import (Bill, BillItem, CashLedger, CashSettlement, Franchise, HqRelease, HqRequirement, Lead, Load,
                         LoadWeighing, Profile, ScrapItem)
from core.services.common import (ApiError, advisory_lock, blank, btrim, dec, fetch, hq_log, round_half_up, scalar,
                                  show_num)
from core.services.registry import rpc


def tolerance_pct():
    return Decimal(str(getattr(settings, "WEIGHING_TOLERANCE_PCT", 2)))


@rpc()
def wh_tolerance_pct(ctx):
    ctx.need_session()
    return tolerance_pct()


def stock_kg(item_id, franchise_id=None):
    """Kg of a material in the yard: weighed in (reconciled or flagged loads) minus released to HQ. franchise None = all."""
    return scalar("""
      select coalesce((select sum(w.warehouse_kg) from load_weighings w join loads l on l.id = w.load_id
                       where w.item_id = %(i)s and w.superseded_at is null and l.status in ('reconciled','flagged')
                         and (%(f)s::integer is null or w.franchise_id = %(f)s::integer)), 0)
           - coalesce((select sum(kg) from hq_releases where item_id = %(i)s and (%(f)s::integer is null or franchise_id = %(f)s::integer)), 0)
    """, {"i": item_id, "f": franchise_id})


# ---------------------------------------------------------------------------------------------- weighing
@rpc()
def record_load_weighing(ctx, p_load_id, p_weights, p_note=None):
    """Weigh a load material by material. p_weights: [{"item_id": 1, "kg": 41.5}, ...].
    A material is fine when the warehouse weight is within the tolerance of what the collector billed."""
    if ctx.role not in ("warehouse", "hq"):
        raise ApiError("Only warehouse staff can record weighing.")
    if not isinstance(p_weights, list) or len(p_weights) == 0:
        raise ApiError("Send the weight of each material as a list.")
    load = Load.objects.select_for_update().filter(pk=p_load_id).first()
    if load is None:
        raise ApiError("Load not found.")
    if not ctx.fr_ok(load.franchise_id):
        raise ApiError("This load belongs to another franchise.")
    if load.status != "submitted":
        raise ApiError(f"This load is not waiting for weighing (status: {load.status}).")

    entries = []
    for w in p_weights:
        try:
            entries.append((int(w["item_id"]), w.get("kg")))
        except Exception:
            raise ApiError("Unknown material in the list.")
    ids = [e[0] for e in entries]
    items = {i.pk: i for i in ScrapItem.objects.filter(pk__in=ids)}
    if any(i not in items for i in ids):
        raise ApiError("Unknown material in the list.")
    if len(set(ids)) != len(ids):
        raise ApiError("Each material can be entered only once.")

    billed = {r["item_id"]: r["kg"] for r in
              BillItem.objects.filter(bill__load_id=load.pk, bill__status="paid").values("item_id").annotate(kg=Sum("qty_kg"))}
    missing = [ScrapItem.objects.get(pk=i).name for i in sorted(billed) if i not in items]
    if missing:
        raise ApiError(f"Enter the weight for: {', '.join(missing)}.")

    now = timezone.now()
    LoadWeighing.objects.filter(load_id=load.pk, superseded_at__isnull=True).update(superseded_at=now)

    tol = tolerance_pct()
    all_ok, tb, tw, out = True, Decimal(0), Decimal(0), []
    for item_id, raw in sorted(entries, key=lambda e: e[0]):
        item = items[item_id]
        try:
            w = None if raw is None else Decimal(str(raw))
        except Exception:
            w = None
        if w is None or not w.is_finite() or w < 0 or w > 100000:
            raise ApiError(f"The weight of {item.name} must be between 0 and 100000 kg.")
        b = billed.get(item_id, Decimal(0)) or Decimal(0)
        ok = (abs(w - b) / b <= tol / 100) if b > 0 else (w == 0)
        all_ok = all_ok and ok
        LoadWeighing.objects.create(load_id=load.pk, item_id=item_id, billed_kg=b, warehouse_kg=w, within_tolerance=ok,
                                    weighed_by_id=ctx.uid, franchise_id=load.franchise_id)
        tb += b
        tw += w
        out.append({"item": item.name, "billed_kg": b, "warehouse_kg": w,
                    "diff_pct": round_half_up((w - b) / b * 100, 2) if b > 0 else None, "ok": ok})
    status = "reconciled" if all_ok else "flagged"
    load.warehouse_kg = tw
    load.status = status
    load.checked_by_id = ctx.uid
    load.weighed_at = now
    load.weighing_note = p_note
    load.save(update_fields=["warehouse_kg", "status", "checked_by", "weighed_at", "weighing_note"])
    return {"status": status, "billed_kg": tb, "warehouse_kg": tw, "tolerance_pct": tol, "items": out}


@rpc()
def record_weighing(ctx, p_load_id=None, p_warehouse_kg=None):
    """The old single-total version stays switched off so it cannot skip the per-material check."""
    raise ApiError("Use record_load_weighing, which checks every material.")


@rpc()
def resolve_flagged_load(ctx, p_load_id, p_action, p_note):
    """HQ decides about a flagged load: accept the difference, or send it back for re-weighing."""
    if ctx.role != "hq":
        raise ApiError("Only HQ can resolve a flagged load.")
    if p_action not in ("accept", "reweigh"):
        raise ApiError("Action must be accept or reweigh.")
    if blank(p_note):
        raise ApiError("Add a note explaining the decision.")
    load = Load.objects.select_for_update().filter(pk=p_load_id).first()
    if load is None or load.status != "flagged":
        raise ApiError("This load is not flagged.")
    now = timezone.now()
    if p_action == "accept":
        load.status = "reconciled"
        load.resolved_by_id = ctx.uid
        load.resolved_at = now
        load.resolution_note = p_note
        load.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note"])
        return "reconciled"
    # re-weigh: only possible while the stock from this load has not already left the yard
    for w in LoadWeighing.objects.filter(load_id=load.pk, superseded_at__isnull=True):
        advisory_lock(w.item_id, load.franchise_id)
        if stock_kg(w.item_id, load.franchise_id) - w.warehouse_kg < 0:
            raise ApiError("Cannot re-weigh: stock from this load has already been released to HQ.")
    LoadWeighing.objects.filter(load_id=load.pk, superseded_at__isnull=True).update(superseded_at=now)
    load.status = "submitted"
    load.warehouse_kg = None
    load.checked_by = None
    load.weighed_at = None
    load.resolved_by_id = ctx.uid
    load.resolved_at = now
    load.resolution_note = p_note
    load.save(update_fields=["status", "warehouse_kg", "checked_by", "weighed_at", "resolved_by", "resolved_at", "resolution_note"])
    return "submitted"


# ---------------------------------------------------------------------------------------------- HQ requirements and releases
@rpc()
def raise_requirement(ctx, p_item_id, p_required_kg, p_due_date=None, p_note=None, p_franchise=None):
    if ctx.role != "hq":
        raise ApiError("Only HQ can raise a requirement.")
    if p_franchise is None:
        raise ApiError("Choose the franchise this request is for.")
    if not Franchise.objects.filter(pk=p_franchise, active=True).exists():
        raise ApiError("That franchise is not active.")
    kg = dec(p_required_kg, "kg HQ needs") if p_required_kg is not None else None
    if kg is None or kg <= 0:
        raise ApiError("Enter the kg HQ needs.")
    if not ScrapItem.objects.filter(pk=p_item_id).exists():
        raise ApiError("Unknown material.")
    due = None
    if p_due_date not in (None, ""):
        try:
            due = date_cls.fromisoformat(str(p_due_date)[:10])
        except ValueError:
            raise ApiError("Enter a valid due date.")
    req = HqRequirement.objects.create(item_id=p_item_id, required_kg=kg, due_date=due, note=p_note,
                                       raised_by_id=ctx.uid, franchise_id=p_franchise)
    return req.code


@rpc()
def cancel_requirement(ctx, p_requirement_id, p_note):
    if ctx.role != "hq":
        raise ApiError("Only HQ can cancel a requirement.")
    if blank(p_note):
        raise ApiError("Add a reason for cancelling.")
    n = HqRequirement.objects.filter(pk=p_requirement_id, status="open").update(
        status="cancelled", cancelled_at=timezone.now(), cancel_note=p_note)
    if not n:
        raise ApiError("Requirement not found or already cancelled.")
    return None


@rpc()
def release_to_hq(ctx, p_requirement_id, p_kg, p_vehicle_no=None, p_note=None):
    """Release stock to HQ against one of its requests. A supervisor (or HQ) does this. Never more than HQ still needs,
    and never more than is in the yard of that franchise."""
    if ctx.role not in ("supervisor", "hq"):
        raise ApiError("Only warehouse staff can release stock.")
    req = HqRequirement.objects.filter(pk=p_requirement_id).first()
    if req is None:
        raise ApiError("Requirement not found.")
    if not ctx.fr_ok(req.franchise_id):
        raise ApiError("This request belongs to another franchise.")
    kg = dec(p_kg, "kg to release")
    if kg <= 0:
        raise ApiError("Enter the kg to release.")
    vehicle = btrim(p_vehicle_no)
    if not vehicle:
        raise ApiError("Enter the vehicle number.")
    # one release at a time for this material in this franchise
    advisory_lock(req.item_id, req.franchise_id)
    req = HqRequirement.objects.select_for_update().get(pk=req.pk)
    if req.status != "open":
        raise ApiError("This request has been cancelled.")
    done = HqRelease.objects.filter(requirement_id=req.pk).aggregate(s=Sum("kg"))["s"] or Decimal(0)
    if kg > (req.required_kg - done) + Decimal("0.0001"):
        raise ApiError(f"HQ only needs {show_num(req.required_kg - done, 1)} kg more for this request.")
    have = stock_kg(req.item_id, req.franchise_id)
    if kg > have + Decimal("0.0001"):
        raise ApiError(f"Not enough stock. In the yard: {show_num(have, 1)} kg.")
    rel = HqRelease.objects.create(requirement_id=req.pk, item_id=req.item_id, kg=kg, vehicle_no=vehicle, note=p_note,
                                   released_by_id=ctx.uid, franchise_id=req.franchise_id)
    return rel.code


# ---------------------------------------------------------------------------------------------- cash
@rpc()
def issue_float(ctx, p_driver_id, p_amount, p_note=None):
    if ctx.role not in ("warehouse", "hq"):
        raise ApiError("Only warehouse staff can issue float.")
    amount = dec(p_amount, "amount") if p_amount is not None else None
    if amount is None or amount <= 0 or amount > 500000:
        raise ApiError("Enter an amount between 1 and 500000.")
    drv = Profile.objects.select_for_update().filter(pk=p_driver_id, role="driver", active=True).first() if p_driver_id else None
    if drv is None or drv.franchise_id is None:
        raise ApiError("That is not an active driver.")
    if not ctx.fr_ok(drv.franchise_id):
        raise ApiError("This driver belongs to another franchise.")
    CashLedger.objects.create(driver_id=drv.pk, entry_type="float_issued", amount=amount,
                              note=p_note if p_note is not None else "Float issued at warehouse",
                              created_by_id=ctx.uid, franchise_id=drv.franchise_id)
    return CashLedger.objects.filter(driver_id=drv.pk).aggregate(s=Sum("amount"))["s"] or Decimal(0)


def uncounted_loads(driver_id, upto):
    """Ended routes of a driver, up to and including `upto`, that no cash count has covered yet."""
    return [r["lid"] for r in fetch("""
      select l.id as lid from loads l
      where l.driver_id = %(d)s and l.status <> 'open' and l.id <= %(u)s
        and not exists (select 1 from cash_settlements s where s.load_id = l.id or s.covered_load_ids @> array[l.id])
      order by l.id""", {"d": driver_id, "u": upto})]


@rpc()
def count_route_cash(ctx, p_load_id, p_counted, p_note=None):
    """Count the cash a collector hands back. One count is made on the collector's latest route and covers all earlier
    routes that were not counted. Expected cash = the collector's full cash in hand."""
    if ctx.role not in ("warehouse", "hq"):
        raise ApiError("Only warehouse staff can count cash.")
    counted = dec(p_counted, "cash you counted") if p_counted is not None else None
    if counted is None or counted < 0 or counted > 1000000:
        raise ApiError("Enter the cash you counted.")
    load = Load.objects.filter(pk=p_load_id).first()
    if load is None:
        raise ApiError("Load not found.")
    if not ctx.fr_ok(load.franchise_id):
        raise ApiError("This route belongs to another franchise.")
    # take this collector's turn: nobody else counts or spends against this collector at the same moment
    Profile.objects.select_for_update().filter(pk=load.driver_id).first()
    list(Load.objects.select_for_update().filter(driver_id=load.driver_id).values_list("id", flat=True))
    load = Load.objects.get(pk=p_load_id)

    if load.status == "open":
        raise ApiError("The driver has not ended this route yet.")
    if any(True for _ in fetch("select 1 from cash_settlements s where s.load_id = %(l)s or %(l)s = any(s.covered_load_ids)", {"l": load.pk})):
        raise ApiError("Cash for this route was already counted.")
    if Load.objects.filter(driver_id=load.driver_id, status="open").exists():
        raise ApiError("This driver still has a route on the road. Count the cash when the driver is back.")
    last = Load.objects.filter(driver_id=load.driver_id).exclude(status="open").order_by("-id").first()
    if last.pk != load.pk:
        raise ApiError(f"Count from the driver's latest route ({last.code}). One count covers all of this driver's routes.")
    cov = [i for i in uncounted_loads(load.driver_id, load.pk) if i != load.pk]

    bal = CashLedger.objects.filter(driver_id=load.driver_id).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    expected = max(bal, Decimal(0))
    if counted != expected and blank(p_note):
        raise ApiError(f"The count differs from the expected ₹{format(expected, 'f')}. Add a note.")

    paid = BillItem.objects.filter(bill__status="paid", bill__load_id__in=[load.pk] + cov)
    cash_paid = paid.filter(bill__payment_method="cash").aggregate(s=Sum("amount"))["s"] or Decimal(0)
    upi_paid = paid.filter(bill__payment_method="upi").aggregate(s=Sum("amount"))["s"] or Decimal(0)

    s = CashSettlement.objects.create(load_id=load.pk, driver_id=load.driver_id, expected_cash=expected, counted_cash=counted,
                                      cash_paid=cash_paid, upi_paid=upi_paid, counted_by_id=ctx.uid, count_note=p_note,
                                      covered_load_ids=cov, franchise_id=load.franchise_id)
    codes = ", ".join(Load.objects.filter(pk__in=[load.pk] + cov).order_by("id").values_list("code", flat=True))
    if expected > 0:
        CashLedger.objects.create(driver_id=load.driver_id, entry_type="handover", amount=-expected,
                                  note=f"Routes {codes}: counted ₹{format(counted, 'f')}, expected ₹{format(expected, 'f')}",
                                  created_by_id=ctx.uid, franchise_id=load.franchise_id)
    return {"settlement_id": s.pk, "expected": expected, "counted": counted, "difference": counted - expected,
            "status": "counted", "routes": codes}


@rpc()
def verify_settlement(ctx, p_settlement_id, p_decision, p_note=None):
    """A different person (a supervisor, or HQ) verifies or disputes the count."""
    if ctx.role not in ("supervisor", "hq"):
        raise ApiError("Only a supervisor can verify cash.")
    if p_decision not in ("verify", "dispute"):
        raise ApiError("Decision must be verify or dispute.")
    s = CashSettlement.objects.select_for_update().filter(pk=p_settlement_id).first()
    if s is None:
        raise ApiError("Settlement not found.")
    if not ctx.fr_ok(s.franchise_id):
        raise ApiError("This settlement belongs to another franchise.")
    if s.status != "counted":
        raise ApiError(f"This settlement is already {s.status}.")
    if s.counted_by_id == ctx.uid:
        raise ApiError("The person who counted the cash cannot verify it.")
    if (s.difference != 0 or p_decision == "dispute") and blank(p_note):
        raise ApiError("Add a note explaining the difference or the dispute.")
    s.status = "verified" if p_decision == "verify" else "disputed"
    s.verified_by_id = ctx.uid
    s.verified_at = timezone.now()
    s.verify_note = p_note
    s.save(update_fields=["status", "verified_by", "verified_at", "verify_note"])
    return s.status


@rpc()
def receive_cash(ctx, p_driver_id=None, p_amount=None):
    """Switched off: cash must go through the cash count on the Finance screen."""
    raise ApiError("Use the cash count on the Finance screen. It records the count and needs a supervisor to verify it.")


# ---------------------------------------------------------------------------------------------- reports
def _d(v):
    """A date coming from the page ('2026-10-09'). Left as text; the database casts it."""
    if v is None:
        raise ApiError("Choose the dates.")
    return str(v)[:10]


@rpc()
def wh_stock_report(ctx, p_from, p_to, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch("""
      select cr.item_id, cr.item_name, cr.rate_per_kg,
             coalesce(sum(case when m.day < %(a)s::date then (case m.kind when 'received' then m.kg else -m.kg end) end), 0) as opening_kg,
             coalesce(sum(case when m.day between %(a)s::date and %(b)s::date and m.kind = 'received' then m.kg end), 0) as received_kg,
             coalesce(sum(case when m.day between %(a)s::date and %(b)s::date and m.kind = 'released' then m.kg end), 0) as released_kg,
             coalesce(sum(case when m.day <= %(b)s::date then (case m.kind when 'received' then m.kg else -m.kg end) end), 0) as closing_kg,
             coalesce(sum(case when m.day <= %(b)s::date then (case m.kind when 'received' then m.kg else -m.kg end) end), 0) * cr.rate_per_kg as closing_value,
             (select coalesce(sum(q.remaining_kg), 0) from hq_requirement_progress q
               where q.item_id = cr.item_id and q.status in ('open','partial') and (%(f)s::integer is null or q.franchise_id = %(f)s::integer)) as hq_open_need_kg,
             (coalesce((select sum(w.warehouse_kg) from load_weighings w join loads l2 on l2.id = w.load_id
                         where w.item_id = cr.item_id and w.superseded_at is null and l2.status in ('reconciled','flagged')
                           and (%(f)s::integer is null or w.franchise_id = %(f)s::integer)), 0)
              - coalesce((select sum(r.kg) from hq_releases r where r.item_id = cr.item_id
                           and (%(f)s::integer is null or r.franchise_id = %(f)s::integer)), 0)) as stock_now_kg
      from current_rates cr
      left join wh_stock_movements m on m.item_id = cr.item_id and (%(f)s::integer is null or m.franchise_id = %(f)s::integer)
      group by cr.item_id, cr.item_name, cr.rate_per_kg
      order by cr.item_id
    """, {"a": _d(p_from), "b": _d(p_to), "f": f})


@rpc()
def wh_pickups(ctx, p_from, p_to, p_load_id=None, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch("""
      select b.id as bill_id, b.bill_no, ld.code as lead_code, cu.area, b.load_id, lo.code as load_code, pr.full_name as driver_name,
             b.paid_at, b.payment_method, bt.total_kg, bt.total_amount, fr.code as franchise_code,
             cu.name as customer_name, cu.phone, ld.latitude, ld.longitude
      from bills b
      join bill_totals bt on bt.bill_id = b.id
      join leads ld on ld.id = b.lead_id
      join customers cu on cu.id = ld.customer_id
      join loads lo on lo.id = b.load_id
      join profiles pr on pr.id = lo.driver_id
      join franchises fr on fr.id = lo.franchise_id
      where b.status = 'paid'
        and (b.paid_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
        and (%(load)s::integer is null or b.load_id = %(load)s::integer)
        and (%(f)s::integer is null or lo.franchise_id = %(f)s::integer)
      order by b.paid_at desc
    """, {"a": _d(p_from), "b": _d(p_to), "load": p_load_id, "f": f})


@rpc()
def wh_transactions(ctx, p_from, p_to, p_driver=None, p_limit=200, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch("""
      select * from (
        select c.created_at as txn_at, c.driver_id, pr.full_name as driver_name, c.entry_type as kind, c.amount as cash_effect, abs(c.amount) as amount,
               b.bill_no, ld.code as lead_code, cu.area, c.note as ref, fr.code as franchise_code
        from cash_ledger c
        join profiles pr on pr.id = c.driver_id
        join franchises fr on fr.id = c.franchise_id
        left join bills b on b.id = c.bill_id
        left join leads ld on ld.id = b.lead_id
        left join customers cu on cu.id = ld.customer_id
        where (c.created_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
          and (%(f)s::integer is null or c.franchise_id = %(f)s::integer)
        union all
        select b.paid_at, lo.driver_id, pr.full_name, 'upi_payout', 0::numeric, bt.total_amount,
               b.bill_no, ld.code, cu.area, b.upi_ref, fr.code
        from bills b
        join bill_totals bt on bt.bill_id = b.id
        join loads lo on lo.id = b.load_id
        join profiles pr on pr.id = lo.driver_id
        join franchises fr on fr.id = lo.franchise_id
        join leads ld on ld.id = b.lead_id
        join customers cu on cu.id = ld.customer_id
        where b.status = 'paid' and b.payment_method = 'upi'
          and (b.paid_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
          and (%(f)s::integer is null or lo.franchise_id = %(f)s::integer)
      ) t
      where (%(drv)s::uuid is null or t.driver_id = %(drv)s::uuid)
      order by t.txn_at desc
      limit greatest(least(%(lim)s::integer, 1000), 1)
    """, {"a": _d(p_from), "b": _d(p_to), "drv": p_driver or None, "lim": 200 if p_limit is None else int(p_limit), "f": f})


ROUTE_CASH_SQL = """
  select l.id as load_id, l.code as load_code, l.driver_id, p.full_name as driver_name,
         (l.started_at at time zone 'Asia/Kolkata')::date as route_date, z.st as route_status,
         coalesce(fl.amt, 0) as float_issued, coalesce(s.cash_paid, pay.cash) as cash_paid, coalesce(s.upi_paid, pay.upi) as upi_paid,
         coalesce(s.expected_cash, case when z.st = 'awaiting_count' then (select greatest(coalesce(sum(c.amount), 0), 0) from cash_ledger c where c.driver_id = l.driver_id) end) as expected_cash,
         s.counted_cash, s.difference, coalesce(s.id, cv.id) as settlement_id, cb.full_name as counted_by_name, s.counted_at, s.count_note,
         vb.full_name as verified_by_name, s.verified_at, s.verify_note, l.franchise_id, fr.code as franchise_code
  from loads l
  join profiles p on p.id = l.driver_id
  join franchises fr on fr.id = l.franchise_id
  left join cash_settlements s on s.load_id = l.id
  left join lateral (select cs.id from cash_settlements cs where cs.covered_load_ids @> array[l.id] limit 1) cv on true
  left join profiles cb on cb.id = s.counted_by
  left join profiles vb on vb.id = s.verified_by
  cross join lateral (select case
      when s.id is not null then s.status
      when cv.id is not null then 'included'
      when l.status = 'open' then 'on_route'
      when exists (select 1 from loads o where o.driver_id = l.driver_id and o.status = 'open') then 'driver_out'
      when l.id = (select max(x.id) from loads x where x.driver_id = l.driver_id and x.status <> 'open') then 'awaiting_count'
      else 'with_last' end as st) z
  left join lateral (select sum(c.amount) as amt from cash_ledger c
      where c.driver_id = l.driver_id and c.entry_type = 'float_issued'
        and c.created_at >= ((l.started_at at time zone 'Asia/Kolkata')::date)::timestamp at time zone 'Asia/Kolkata'
        and c.created_at < ((l.started_at at time zone 'Asia/Kolkata')::date + 1)::timestamp at time zone 'Asia/Kolkata') fl on true
  cross join lateral (select coalesce(sum(bi.amount) filter (where b.payment_method = 'cash'), 0) as cash,
                             coalesce(sum(bi.amount) filter (where b.payment_method = 'upi'), 0) as upi
      from bills b join bill_items bi on bi.bill_id = b.id
      where b.status = 'paid'
        and b.load_id = any (case when z.st = 'awaiting_count'
              then array(select l2.id from loads l2 where l2.driver_id = l.driver_id and l2.status <> 'open' and l2.id <= l.id
                         and not exists (select 1 from cash_settlements s2 where s2.load_id = l2.id or s2.covered_load_ids @> array[l2.id]))
              else array[l.id] end)) pay
  where l.started_at >= (%(a)s::date)::timestamp at time zone 'Asia/Kolkata'
    and l.started_at < ((%(b)s::date + 1))::timestamp at time zone 'Asia/Kolkata'
    and (%(drv)s::uuid is null or l.driver_id = %(drv)s::uuid)
    and (%(f)s::integer is null or l.franchise_id = %(f)s::integer)
  order by l.started_at desc
"""


@rpc()
def wh_route_cash(ctx, p_from, p_to, p_driver=None, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch(ROUTE_CASH_SQL, {"a": _d(p_from), "b": _d(p_to), "drv": p_driver or None, "f": f})


# ---------------------------------------------------------------------------------------------- leads for the supervisor
SEARCH_SQL = """(%(q)s::text is null or btrim(%(q)s::text) = '' or cu.name ilike '%%' || btrim(%(q)s::text) || '%%'
                 or cu.phone ilike '%%' || btrim(%(q)s::text) || '%%' or l.code ilike '%%' || btrim(%(q)s::text) || '%%'
                 or coalesce(cu.area, '') ilike '%%' || btrim(%(q)s::text) || '%%')"""


@rpc()
def wh_leads(ctx, p_from, p_to, p_status=None, p_driver=None, p_search=None, p_limit=500, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch(f"""
      select l.id as lead_id, l.code, cu.name as customer_name, cu.phone, cu.address, cu.area, l.latitude, l.longitude,
             l.slot, l.status, l.items_said, l.driver_id, pr.full_name as driver_name, l.fail_reason, l.fail_note,
             l.failed_at, b.bill_no, bt.total_amount, fr.code as franchise_code
      from leads l
      join customers cu on cu.id = l.customer_id
      join franchises fr on fr.id = l.franchise_id
      left join profiles pr on pr.id = l.driver_id
      left join bills b on b.lead_id = l.id
      left join lateral (select sum(bi.amount) as total_amount from bill_items bi where bi.bill_id = b.id) bt on b.id is not null
      where (%(f)s::integer is null or l.franchise_id = %(f)s::integer)
        and ((l.slot at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
             or l.status = 'unassigned'
             or (l.status = 'failed' and l.failed_at >= now() - interval '7 days'))
        and (%(st)s::text is null or l.status = %(st)s::text)
        and (%(drv)s::uuid is null or l.driver_id = %(drv)s::uuid)
        and {SEARCH_SQL}
      order by (l.status = 'unassigned') desc, l.slot nulls last, l.id
      limit greatest(least(%(lim)s::integer, 1000), 1)
    """, {"a": _d(p_from), "b": _d(p_to), "st": p_status, "drv": p_driver or None, "q": p_search,
          "lim": 500 if p_limit is None else int(p_limit), "f": f})


@rpc()
def wh_lead_counts(ctx, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch("""
      select
        (select count(*) from leads l where l.status = 'unassigned' and (%(f)s::integer is null or l.franchise_id = %(f)s::integer)) as unassigned,
        (select count(*) from leads l where l.status = 'failed' and l.failed_at >= now() - interval '3 days' and (%(f)s::integer is null or l.franchise_id = %(f)s::integer)) as failed_recent,
        (select count(*) from leads l where l.status in ('scheduled','in_progress')
           and (l.slot at time zone 'Asia/Kolkata')::date = (now() at time zone 'Asia/Kolkata')::date
           and (%(f)s::integer is null or l.franchise_id = %(f)s::integer)) as open_today
    """, {"f": f})


@rpc()
def wh_driver_workload(ctx, p_date, p_franchise=None):
    f = ctx.fr_scope(p_franchise)
    return fetch("""
      select p.id as driver_id, p.full_name, p.vehicle_no, p.territory,
             (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress','closed')
                and (l.slot at time zone 'Asia/Kolkata')::date = %(d)s::date) as leads_day,
             (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress')) as open_now
      from profiles p
      where p.role = 'driver' and p.active and (%(f)s::integer is null or p.franchise_id = %(f)s::integer)
      order by p.full_name
    """, {"d": _d(p_date), "f": f})


@rpc()
def wh_assign_leads(ctx, p_lead_ids, p_driver=None):
    """Give leads to a collector (or take them back, p_driver = null). A supervisor can only use their own franchise."""
    role = ctx.role
    if role not in ("supervisor", "hq"):
        raise ApiError("Only the supervisor can assign leads.")
    ids = sorted({int(x) for x in (p_lead_ids or [])})
    if not ids:
        raise ApiError("Select at least one lead.")
    if len(ids) > 200:
        raise ApiError("Assign at most 200 leads at a time.")
    drv = None
    if p_driver:
        drv = Profile.objects.filter(pk=p_driver, role="driver", active=True).first()
        if drv is None:
            raise ApiError("Choose an active driver.")
    my_f = None
    if role == "supervisor":
        my_f = ctx.franchise_id
        if my_f is None:
            raise ApiError("Your login is not assigned to a franchise.")
        if drv is not None and drv.franchise_id != my_f:
            raise ApiError("That driver is not in your franchise.")
    n, codes = 0, []
    for lead in Lead.objects.select_for_update().filter(pk__in=ids).order_by("id"):
        if role == "supervisor" and lead.franchise_id != my_f:
            raise ApiError(f"Lead {lead.code} is not in your franchise.")
        if drv is not None and drv.franchise_id != lead.franchise_id:
            raise ApiError(f"Lead {lead.code} belongs to a different franchise than this driver.")
        if lead.status not in ("unassigned", "scheduled", "failed"):
            raise ApiError(f"Lead {lead.code} is {lead.status} and cannot be assigned.")
        if drv is None and lead.status != "scheduled":
            raise ApiError(f"Lead {lead.code} is already unassigned or not completed.")
        lead.driver_id = drv.pk if drv else None
        lead.status = "scheduled" if drv else "unassigned"
        lead.fail_reason = lead.fail_note = lead.failed_at = None
        lead.save(update_fields=["driver", "status", "fail_reason", "fail_note", "failed_at"])
        n += 1
        codes.append(lead.code)
    if n != len(ids):
        raise ApiError("Some of the selected leads were not found.")
    hq_log(ctx, "leads_assigned" if drv else "leads_unassigned", f"{n} lead{'' if n == 1 else 's'}",
           {"driver": str(drv.pk) if drv else None, "driver_name": drv.full_name if drv else None, "codes": codes},
           my_f if my_f is not None else (drv.franchise_id if drv else None))
    return n


@rpc()
def wh_split_leads(ctx, p_lead_ids, p_driver_ids):
    """Share leads evenly between several collectors. Leads are put in order of area, then time, and handed out in blocks,
    so each collector gets neighbouring areas."""
    if ctx.role not in ("supervisor", "hq"):
        raise ApiError("Only the supervisor can assign leads.")
    drivers = sorted({str(x) for x in (p_driver_ids or [])})
    if not drivers:
        raise ApiError("Choose at least one driver.")
    k = len(drivers)
    rows = fetch("""
      select l.id from leads l join customers cu on cu.id = l.customer_id
      where l.id = any(%(ids)s::integer[])
      order by coalesce(cu.area, ''), l.slot, l.id
    """, {"ids": [int(x) for x in (p_lead_ids or [])]})
    ids = [r["id"] for r in rows]
    if not ids:
        raise ApiError("Select at least one lead.")
    n = len(ids)
    base, extra = divmod(n, k)
    out = []
    for d in range(1, k + 1):
        grp = []
        for i in range(n):
            if base == 0:
                if i == d - 1:
                    grp.append(ids[i])
            elif i < extra * (base + 1):
                if i // (base + 1) == d - 1:
                    grp.append(ids[i])
            elif extra + (i - extra * (base + 1)) // base == d - 1:
                grp.append(ids[i])
        if grp:
            count = wh_assign_leads(ctx, grp, drivers[d - 1])
            name = Profile.objects.filter(pk=drivers[d - 1]).values_list("full_name", flat=True).first()
            out.append({"driver_id": drivers[d - 1], "name": name, "count": count})
    return out
