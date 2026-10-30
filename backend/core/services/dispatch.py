"""Stock going to HQ on a vehicle, in two hands: the warehouse manager enters the quantity of each material loaded and sends it
to the supervisor; the supervisor finalizes it (the releases and the price are recorded then) or sends it back with a reason.
HQ sets the price it pays per kg for each material (the sale price of a franchise's stock). The warehouse manager never sees prices."""
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core.models import Franchise, HqBuyRate, HqDispatch, HqDispatchLine, HqRelease, HqRequirement, ScrapItem
from core.services.common import (ApiError, advisory_lock, blank, btrim, dec, fetch, fetch_one, fixed_decimal, hq_log, round_half_up, scalar,
                                  show_num)
from core.services.registry import rpc
from core.services.warehouse import stock_kg

EPS = Decimal("0.0001")
MAX_BUY_RATE = 100000
MAX_DISPATCH_LINES = 100


def _need(ctx, *roles, message):
    if ctx.role not in roles:
        raise ApiError(message)


def _released(requirement_id):
    return HqRelease.objects.filter(requirement_id=requirement_id).aggregate(s=Sum("kg"))["s"] or Decimal(0)


def _waiting(*, requirement_id=None, item_id=None, franchise_id=None, skip=None):
    """Kg already promised to other dispatches that are waiting for the supervisor, so two people cannot load the same stock."""
    q = HqDispatchLine.objects.filter(dispatch__status="pending")
    if skip is not None:
        q = q.exclude(dispatch_id=skip)
    if requirement_id is not None:
        q = q.filter(requirement_id=requirement_id)
    if item_id is not None:
        q = q.filter(item_id=item_id, dispatch__franchise_id=franchise_id)
    return q.aggregate(s=Sum("kg"))["s"] or Decimal(0)


def _buy_rate(item_id):
    row = fetch_one("select rate_per_kg from current_hq_buy_rates where item_id = %(i)s", {"i": item_id})
    return row["rate_per_kg"] if row else None


# ---------------------------------------------------------------------------------------------- HQ sets what it pays
@rpc()
def hq_set_buy_rate(ctx, p_item_id, p_rate):
    _need(ctx, "hq", message="Only HQ can set the price it pays.")
    rate = dec(p_rate, "price") if p_rate is not None else None
    if rate is None or rate <= 0 or rate > MAX_BUY_RATE:
        raise ApiError(f"Enter a price between 0 and {MAX_BUY_RATE} per kg.")
    item = ScrapItem.objects.filter(pk=p_item_id, active=True).first()
    if item is None:
        raise ApiError("Unknown material.")
    old = _buy_rate(item.pk)
    if old is not None and old == round_half_up(rate):
        raise ApiError(f"{item.name} is already ₹{format(old, 'f')} per kg.")
    HqBuyRate.objects.create(item_id=item.pk, rate_per_kg=rate, set_by_id=ctx.uid)
    hq_log(ctx, "buy_rate_set", item.name, {"old": float(old) if old is not None else None, "new": float(rate)})
    return item.name


@rpc()
def hq_buy_rates(ctx):
    """Every active material with the price HQ pays now (null = not set yet)."""
    _need(ctx, "hq", message="Only HQ can see all the prices.")
    return fetch("""select i.id as item_id, i.name as item_name, b.rate_per_kg, b.effective_from
                    from scrap_items i left join current_hq_buy_rates b on b.item_id = i.id
                    where i.active order by i.name""")


# ---------------------------------------------------------------------------------------------- the warehouse manager prepares a load
@rpc()
def wh_submit_dispatch(ctx, p_lines, p_vehicle_no, p_note=None, p_dispatch_id=None, p_franchise_id=None):
    """p_lines = [{"requirement_id": 3, "kg": 41.5}, {"item_id": 2, "kg": 10}, ...]: a line is either for an HQ request, or for a
    material loaded without a request ("item_id"). A load with no request lines needs the franchise (only HQ has to say which).
    Sends the load to the supervisor. With p_dispatch_id it corrects a load the supervisor sent back (or one still waiting)."""
    _need(ctx, "warehouse", "hq", message="Only the warehouse manager can prepare a load for HQ.")
    vehicle = btrim(p_vehicle_no)
    if not vehicle:
        raise ApiError("Enter the vehicle number.")
    if not isinstance(p_lines, list) or not p_lines:
        raise ApiError("Enter the quantity of at least one material.")
    if len(p_lines) > MAX_DISPATCH_LINES:
        raise ApiError(f"A load can have at most {MAX_DISPATCH_LINES} lines.")
    wanted, extra = {}, {}                        # kg by request, and kg by material for what is loaded without a request
    for ln in p_lines:
        if not isinstance(ln, dict):
            raise ApiError("Every load line must be an object.")
        rid, iid = ln.get("requirement_id"), ln.get("item_id")
        kg = fixed_decimal(ln.get("kg"), "kg", 3, 14)
        if (rid is None) == (iid is None) or kg <= 0:
            raise ApiError("Every line needs a request or a material, and a quantity above zero.")
        raw_id = rid if rid is not None else iid
        if isinstance(raw_id, bool) or not str(raw_id).isdigit():
            raise ApiError("Choose a valid request or material.")
        book, key = (wanted, int(rid)) if rid is not None else (extra, int(iid))
        if key in book:
            raise ApiError("The same request is listed twice." if rid is not None else "The same material is listed twice.")
        book[key] = kg
    reqs = {r.pk: r for r in HqRequirement.objects.filter(pk__in=wanted)}
    if len(reqs) != len(wanted):
        raise ApiError("Requirement not found.")
    franchises = {r.franchise_id for r in reqs.values()}
    if len(franchises) > 1:
        raise ApiError("One vehicle load can only carry stock of one franchise.")
    if franchises:
        franchise_id = franchises.pop()
        if not ctx.fr_ok(franchise_id):
            raise ApiError("This request belongs to another franchise.")
    else:                                         # nothing here names a franchise: staff use their own, HQ must say
        franchise_id = ctx.fr_scope(p_franchise_id)
        if franchise_id is None:
            raise ApiError("Choose the franchise this load is from.")
        # Canonicalize HQ's JSON input before comparing it with an existing load's integer FK.
        fr = Franchise.objects.filter(pk=franchise_id, active=True).first()
        if fr is None:
            raise ApiError("Choose an active franchise.")
        franchise_id = fr.pk
    items = {i.pk: i for i in ScrapItem.objects.filter(pk__in=extra, active=True)}
    if len(items) != len(extra):
        raise ApiError("Unknown material.")

    dispatch = None
    if p_dispatch_id is not None:
        dispatch = HqDispatch.objects.select_for_update().filter(pk=p_dispatch_id).first()
        if dispatch is None or not ctx.fr_ok(dispatch.franchise_id):
            raise ApiError("Load not found.")
        if dispatch.status not in ("pending", "rejected"):
            raise ApiError("This load has already been finalized or withdrawn.")
        if dispatch.franchise_id != franchise_id:
            raise ApiError("One vehicle load can only carry stock of one franchise.")

    for item_id in sorted({r.item_id for r in reqs.values()} | set(extra)):          # one at a time per material, in a fixed order
        advisory_lock(item_id, franchise_id)
    skip = dispatch.pk if dispatch else None
    need_by_item = {}
    for rid, kg in wanted.items():
        r = HqRequirement.objects.select_for_update().get(pk=rid)
        if r.status != "open":
            raise ApiError(f"{r.code} has been cancelled.")
        room = r.required_kg - _released(rid) - _waiting(requirement_id=rid, skip=skip)
        if kg > room + EPS:
            raise ApiError(f"HQ only needs {show_num(max(room, Decimal(0)), 1)} kg more for {r.code}.")
        need_by_item[r.item_id] = need_by_item.get(r.item_id, Decimal(0)) + kg
    for item_id, kg in extra.items():
        need_by_item[item_id] = need_by_item.get(item_id, Decimal(0)) + kg
    for item_id, kg in need_by_item.items():
        have = stock_kg(item_id, franchise_id) - _waiting(item_id=item_id, franchise_id=franchise_id, skip=skip)
        if kg > have + EPS:
            name = ScrapItem.objects.get(pk=item_id).name
            raise ApiError(f"Not enough {name} in stock. Available: {show_num(max(have, Decimal(0)), 1)} kg.")

    if dispatch is None:
        dispatch = HqDispatch.objects.create(franchise_id=franchise_id, vehicle_no=vehicle, note=p_note, prepared_by_id=ctx.uid)
    else:
        dispatch.vehicle_no, dispatch.note, dispatch.status = vehicle, p_note, "pending"
        dispatch.prepared_by_id, dispatch.reviewed_by_id, dispatch.reviewed_at, dispatch.review_note = ctx.uid, None, None, None
        dispatch.save()
        dispatch.lines.all().delete()
    for rid, kg in wanted.items():
        HqDispatchLine.objects.create(dispatch_id=dispatch.pk, requirement_id=rid, item_id=reqs[rid].item_id, kg=kg)
    for iid, kg in extra.items():
        HqDispatchLine.objects.create(dispatch_id=dispatch.pk, requirement=None, item_id=iid, kg=kg)
    hq_log(ctx, "dispatch_submitted", dispatch.code, {"vehicle": vehicle, "lines": len(wanted) + len(extra), "without_request": len(extra)}, franchise_id)
    return dispatch.code


@rpc()
def wh_withdraw_dispatch(ctx, p_dispatch_id, p_note=None):
    """Take back a load the supervisor has not finalized yet."""
    _need(ctx, "warehouse", "hq", message="Only the warehouse manager can withdraw a load.")
    d = HqDispatch.objects.select_for_update().filter(pk=p_dispatch_id).first()
    if d is None or not ctx.fr_ok(d.franchise_id):
        raise ApiError("Load not found.")
    if d.status not in ("pending", "rejected"):
        raise ApiError("This load has already been finalized or withdrawn.")
    d.status, d.review_note = "withdrawn", p_note or d.review_note
    d.save()
    hq_log(ctx, "dispatch_withdrawn", d.code, None, d.franchise_id)
    return d.code


# ---------------------------------------------------------------------------------------------- the supervisor decides
@rpc()
def sup_review_dispatch(ctx, p_dispatch_id, p_decision, p_note=None):
    """p_decision: 'finalize' (records the releases at the price HQ pays now) or 'reject' (a reason is required).
    A different person from the one who prepared the load must decide."""
    _need(ctx, "supervisor", "hq", message="Only the supervisor can finalize a load.")
    if p_decision not in ("finalize", "reject"):
        raise ApiError("Choose finalize or reject.")
    d = HqDispatch.objects.select_for_update().filter(pk=p_dispatch_id).first()
    if d is None or not ctx.fr_ok(d.franchise_id):
        raise ApiError("Load not found.")
    if d.status != "pending":
        raise ApiError("This load is not waiting for approval.")
    if d.prepared_by_id == ctx.uid:
        raise ApiError("A different person must approve a load you prepared.")
    if p_decision == "reject":
        if blank(p_note):
            raise ApiError("Add a reason so the warehouse manager knows what to correct.")
        d.status, d.reviewed_by_id, d.reviewed_at, d.review_note = "rejected", ctx.uid, timezone.now(), btrim(p_note)
        d.save()
        hq_log(ctx, "dispatch_rejected", d.code, {"note": btrim(p_note)}, d.franchise_id)
        return {"status": "rejected", "code": d.code}

    lines = list(d.lines.select_related("item", "requirement").order_by("item_id", "id"))
    for item_id in sorted({ln.item_id for ln in lines}):
        advisory_lock(item_id, d.franchise_id)
    rates = {}
    for ln in lines:
        req = HqRequirement.objects.select_for_update().get(pk=ln.requirement_id) if ln.requirement_id else None
        if req is not None and req.status != "open":
            raise ApiError(f"{req.code} has been cancelled. Send this load back to the warehouse manager.")
        if req is not None and ln.kg > (req.required_kg - _released(req.pk)) + EPS:
            raise ApiError(f"HQ no longer needs {show_num(ln.kg, 1)} kg for {req.code}. Send this load back.")
        rate = rates.get(ln.item_id) or _buy_rate(ln.item_id)
        if rate is None:
            raise ApiError(f"HQ has not set the price it pays for {ln.item.name}. Ask HQ to set it, then finalize.")
        rates[ln.item_id] = rate
    for item_id in {ln.item_id for ln in lines}:
        need = sum((ln.kg for ln in lines if ln.item_id == item_id), Decimal(0))
        have = stock_kg(item_id, d.franchise_id)
        if need > have + EPS:
            raise ApiError(f"Not enough {ScrapItem.objects.get(pk=item_id).name} in stock. In the yard: {show_num(have, 1)} kg.")

    total = Decimal(0)
    for ln in lines:
        rel = HqRelease.objects.create(requirement_id=ln.requirement_id, item_id=ln.item_id, kg=ln.kg, vehicle_no=d.vehicle_no,
                                       note=f"{d.code}" + (f" · {d.note}" if d.note else ""), released_by_id=ctx.uid,
                                       franchise_id=d.franchise_id)
        ln.price_per_kg = rates[ln.item_id]
        ln.amount = round_half_up(ln.kg * ln.price_per_kg)
        ln.release_id = rel.pk
        ln.save(update_fields=["price_per_kg", "amount", "release"])
        total += ln.amount
    d.status, d.reviewed_by_id, d.reviewed_at, d.review_note = "finalized", ctx.uid, timezone.now(), nullable(p_note)
    d.save()
    hq_log(ctx, "dispatch_finalized", d.code, {"amount": float(total), "lines": len(lines)}, d.franchise_id)
    return {"status": "finalized", "code": d.code, "amount": total}


def nullable(s):
    return btrim(s) or None


# ---------------------------------------------------------------------------------------------- reading
@rpc()
def wh_dispatches(ctx, p_status=None, p_limit=200, p_franchise=None):
    """The loads prepared for HQ, newest first, with their lines. Prices are included for the supervisor and HQ only."""
    _need(ctx, "warehouse", "supervisor", "hq", message="Not allowed.")
    f = ctx.fr_scope(p_franchise)
    limit = max(1, min(int(p_limit or 200), 500))
    heads = fetch("""
      select d.id, d.code, d.franchise_id, d.vehicle_no, d.status, d.note, d.prepared_by, pp.full_name as prepared_by_name, d.prepared_at,
             d.reviewed_by, rp.full_name as reviewed_by_name, d.reviewed_at, d.review_note
      from hq_dispatches d join profiles pp on pp.id = d.prepared_by left join profiles rp on rp.id = d.reviewed_by
      where (%(f)s::integer is null or d.franchise_id = %(f)s::integer) and (%(s)s::text is null or d.status = %(s)s::text)
      order by d.id desc limit %(n)s""", {"f": f, "s": p_status, "n": limit})
    if not heads:
        return []
    lines = fetch("""
      select l.id, l.dispatch_id, l.requirement_id, q.code as requirement_code, l.item_id, i.name as item_name, l.kg,
             l.price_per_kg, l.amount, l.release_id
      from hq_dispatch_lines l left join hq_requirements q on q.id = l.requirement_id join scrap_items i on i.id = l.item_id
      where l.dispatch_id = any(%(ids)s) order by l.id""", {"ids": [h["id"] for h in heads]})
    show_price = ctx.role in ("supervisor", "hq")
    now_rates = {}
    by = {}
    for ln in lines:
        if show_price:
            if ln["price_per_kg"] is None:                      # not finalized yet: show what it would be at today's price
                rate = now_rates.setdefault(ln["item_id"], _buy_rate(ln["item_id"]))
                ln["expected_price_per_kg"] = rate
                ln["expected_amount"] = round_half_up(ln["kg"] * rate) if rate is not None else None
        else:
            for k in ("price_per_kg", "amount"):
                ln.pop(k, None)
        by.setdefault(ln["dispatch_id"], []).append(ln)
    for h in heads:
        h["lines"] = by.get(h["id"], [])
        h["total_kg"] = sum((x["kg"] for x in h["lines"]), Decimal(0))
        if show_price:
            fin = h["status"] == "finalized"
            key = "amount" if fin else "expected_amount"
            vals = [x.get(key) for x in h["lines"]]
            h["total_amount"] = sum(vals, Decimal(0)) if all(v is not None for v in vals) else None
    return heads


@rpc()
def sup_stock_value(ctx, p_franchise=None):
    """The supervisor's price section: for each material the stock in the yard, the price HQ pays per kg, and what the stock
    is worth at that price; plus what has been sold to HQ and what is waiting for approval."""
    _need(ctx, "supervisor", "hq", message="Only the supervisor can see the sale prices.")
    f = ctx.fr_scope(p_franchise)
    items = fetch("select i.id as item_id, i.name as item_name, b.rate_per_kg, b.effective_from from scrap_items i "
                  "left join current_hq_buy_rates b on b.item_id = i.id where i.active order by i.name")
    rows, total, unpriced = [], Decimal(0), 0
    for it in items:
        kg = stock_kg(it["item_id"], f)
        waiting = _waiting(item_id=it["item_id"], franchise_id=f) if f is not None else (
            HqDispatchLine.objects.filter(dispatch__status="pending", item_id=it["item_id"]).aggregate(s=Sum("kg"))["s"] or Decimal(0))
        rate = it["rate_per_kg"]
        value = round_half_up(kg * rate) if rate is not None else None
        if value is not None:
            total += value
        elif kg > 0:
            unpriced += 1
        rows.append({"item_id": it["item_id"], "item_name": it["item_name"], "stock_kg": kg, "waiting_kg": waiting,
                     "price_per_kg": rate, "price_since": it["effective_from"], "value": value})
    sold = fetch_one("""select coalesce(sum(l.amount), 0) as amount, coalesce(sum(l.kg), 0) as kg, count(distinct d.id) as loads
                        from hq_dispatch_lines l join hq_dispatches d on d.id = l.dispatch_id
                        where d.status = 'finalized' and (%(f)s::integer is null or d.franchise_id = %(f)s::integer)""", {"f": f})
    pending = scalar("select count(*) from hq_dispatches where status = 'pending' and (%(f)s::integer is null or franchise_id = %(f)s::integer)", {"f": f})
    return {"items": rows, "total_value": total, "unpriced_items": unpriced, "sold_amount": sold["amount"], "sold_kg": sold["kg"],
            "sold_loads": sold["loads"], "pending_loads": pending}
