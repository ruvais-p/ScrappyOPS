"""HQ: reports across franchises (or one), and the actions only HQ may take. Every action checks the caller is HQ.
Decisions are written to the activity log, which cannot be edited."""
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Q

from core.models import (AuthSession, Bill, CashLedger, CashSettlement, Franchise, HqRequirement, Lead, Load, Profile,
                         Rate, ScrapItem, SettlementResolution, User)
from core.services.common import (ApiError, blank, btrim, dec, fetch, fetch_one, hq_log, nullify, round_half_up,
                                  show_num)
from core.services.registry import rpc
from core.services.warehouse import SEARCH_SQL, _d, stock_kg, wh_stock_report


def _need_hq(ctx):
    if ctx.role != "hq":
        raise ApiError("HQ only.")


# ---------------------------------------------------------------------------------------------- overview and reports
@rpc()
def hq_overview(ctx, p_from, p_to, p_franchise=None):
    _need_hq(ctx)
    a, b, f = _d(p_from), _d(p_to), p_franchise
    prm = {"a": a, "b": b, "f": f}
    F = "(%(f)s::integer is null or {c} = %(f)s::integer)"

    def fr(col="franchise_id"):
        return F.format(c=col)

    row = fetch_one(f"""
      select jsonb_build_object(
        'franchises_active', (select count(*) from franchises where active),
        'drivers_active',    (select count(*) from profiles where role = 'driver' and active and {fr()}),
        'leads_scheduled',   (select count(*) from leads where status = 'scheduled' and {fr()}),
        'leads_unassigned',  (select count(*) from leads where status = 'unassigned' and {fr()}),
        'leads_failed',      (select count(*) from leads where status = 'failed' and (failed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date and {fr()}),
        'leads_today',       (select count(*) from leads where status in ('scheduled','in_progress') and (slot at time zone 'Asia/Kolkata')::date = (now() at time zone 'Asia/Kolkata')::date and {fr()}),
        'leads_in_progress', (select count(*) from leads where status = 'in_progress' and {fr()}),
        'leads_late',        (select count(*) from leads where status = 'scheduled' and slot < now() - interval '3 hours' and {fr()}),
        'leads_closed',      (select count(*) from leads where status = 'closed' and (closed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date and {fr()}),
        'leads_cancelled',   (select count(*) from leads where status = 'cancelled' and (created_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date and {fr()}),
        'paid_bills',        (select count(*) from hq_paid_bills where paid_day between %(a)s::date and %(b)s::date and {fr()}),
        'kg',                (select coalesce(sum(total_kg), 0) from hq_paid_bills where paid_day between %(a)s::date and %(b)s::date and {fr()}),
        'amount',            (select coalesce(sum(total_amount), 0) from hq_paid_bills where paid_day between %(a)s::date and %(b)s::date and {fr()}),
        'cash_amount',       (select coalesce(sum(total_amount), 0) from hq_paid_bills where payment_method = 'cash' and paid_day between %(a)s::date and %(b)s::date and {fr()}),
        'upi_amount',        (select coalesce(sum(total_amount), 0) from hq_paid_bills where payment_method = 'upi' and paid_day between %(a)s::date and %(b)s::date and {fr()}),
        'loads_open',        (select count(*) from loads where status = 'open' and {fr()}),
        'loads_waiting',     (select count(*) from loads where status = 'submitted' and {fr()}),
        'loads_flagged',     (select count(*) from loads where status = 'flagged' and {fr()}),
        'billed_kg_weighed', (select coalesce(sum(billed_kg), 0) from load_weighings where superseded_at is null and (weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date and {fr()}),
        'weighed_kg',        (select coalesce(sum(warehouse_kg), 0) from load_weighings where superseded_at is null and (weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date and {fr()}),
        'cash_in_field',     (select coalesce(sum(amount), 0) from cash_ledger where {fr()}),
        'counts_waiting',    (select count(*) from (select p.id, (select l.id from loads l where l.driver_id = p.id and l.status <> 'open' order by l.id desc limit 1) as last_id
                                                    from profiles p where p.role = 'driver' and {fr('p.franchise_id')}) d
                              where d.last_id is not null
                                and not exists (select 1 from loads o where o.driver_id = d.id and o.status = 'open')
                                and not exists (select 1 from cash_settlements s where s.load_id = d.last_id or s.covered_load_ids @> array[d.last_id])),
        'counts_unverified', (select count(*) from cash_settlements where status = 'counted' and {fr()}),
        'disputes_open',     (select count(*) from cash_settlements s where s.status = 'disputed' and {fr('s.franchise_id')} and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)),
        'shortage_total',    (select coalesce(sum(-difference), 0) from cash_settlements where difference < 0 and (counted_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date and {fr()}),
        'req_open',          (select count(*) from hq_requirement_progress where status in ('open','partial') and {fr()}),
        'req_remaining_kg',  (select coalesce(sum(remaining_kg), 0) from hq_requirement_progress where status in ('open','partial') and {fr()}),
        'req_overdue',       (select count(*) from hq_requirement_progress where is_overdue and {fr()})
      ) as r
    """, prm)
    r = row["r"]
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    stock = wh_stock_report(ctx, today.isoformat(), today.isoformat(), f)
    r["stock_kg"] = sum((x["stock_now_kg"] for x in stock), Decimal(0))
    r["stock_value"] = sum((x["stock_now_kg"] * x["rate_per_kg"] for x in stock), Decimal(0))
    return r


@rpc()
def hq_daily(ctx, p_from, p_to, p_franchise=None):
    _need_hq(ctx)
    return fetch("""
      select d.dd::date as day, count(pb.bill_id) as pickups, coalesce(sum(pb.total_kg), 0) as kg, coalesce(sum(pb.total_amount), 0) as amount,
             coalesce(sum(pb.total_amount) filter (where pb.payment_method = 'cash'), 0) as cash_amount,
             coalesce(sum(pb.total_amount) filter (where pb.payment_method = 'upi'), 0) as upi_amount
      from generate_series(%(a)s::date, least(%(b)s::date, %(a)s::date + 400), interval '1 day') d(dd)
      left join hq_paid_bills pb on pb.paid_day = d.dd::date and (%(f)s::integer is null or pb.franchise_id = %(f)s::integer)
      group by d.dd order by d.dd
    """, {"a": _d(p_from), "b": _d(p_to), "f": p_franchise})


@rpc()
def hq_item_summary(ctx, p_from, p_to, p_franchise=None):
    _need_hq(ctx)
    return fetch("""
      select i.id as item_id, i.name as item_name, coalesce(sum(bi.qty_kg), 0) as kg, coalesce(sum(bi.amount), 0) as amount,
             count(distinct bi.bill_id) as pickups,
             case when sum(bi.qty_kg) > 0 then round(sum(bi.amount) / sum(bi.qty_kg), 2) else 0 end as avg_rate
      from scrap_items i
      left join hq_paid_bills pb on pb.paid_day between %(a)s::date and %(b)s::date and (%(f)s::integer is null or pb.franchise_id = %(f)s::integer)
      left join bill_items bi on bi.bill_id = pb.bill_id and bi.item_id = i.id
      where i.active
      group by i.id, i.name
      order by i.id
    """, {"a": _d(p_from), "b": _d(p_to), "f": p_franchise})


@rpc()
def hq_driver_scorecard(ctx, p_from, p_to, p_franchise=None):
    _need_hq(ctx)
    return fetch("""
      select p.id as driver_id, p.full_name, p.active, p.vehicle_no, p.territory,
        (select count(*) from leads l where l.driver_id = p.id and l.status <> 'cancelled' and (l.slot at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as leads_assigned,
        (select count(*) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between %(a)s::date and %(b)s::date) as pickups,
        (select coalesce(sum(pb.total_kg), 0) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between %(a)s::date and %(b)s::date) as kg,
        (select coalesce(sum(pb.total_amount), 0) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between %(a)s::date and %(b)s::date) as amount,
        (select round((avg(extract(epoch from (pb.paid_at - pb.created_at)) / 60))::numeric, 1) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between %(a)s::date and %(b)s::date) as avg_minutes,
        (select coalesce(sum(w.billed_kg), 0) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as weighed_billed_kg,
        (select coalesce(sum(w.warehouse_kg), 0) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as weighed_kg,
        (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as variance_pct,
        (select count(distinct w.load_id) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and not w.within_tolerance and (w.weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as loads_off_tolerance,
        (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id) as cash_in_hand,
        (select coalesce(sum(-s.difference), 0) from cash_settlements s where s.driver_id = p.id and s.difference < 0 and (s.counted_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as cash_short,
        (select count(*) from cash_settlements s where s.driver_id = p.id and s.status = 'disputed' and (s.counted_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as disputes,
        fr.code as franchise_code
      from profiles p join franchises fr on fr.id = p.franchise_id
      where p.role = 'driver' and (%(f)s::integer is null or p.franchise_id = %(f)s::integer)
      order by p.active desc, fr.code, p.full_name
    """, {"a": _d(p_from), "b": _d(p_to), "f": p_franchise})


@rpc()
def hq_bills(ctx, p_from, p_to, p_status=None, p_driver=None, p_search=None, p_limit=200, p_franchise=None):
    _need_hq(ctx)
    search = """(%(q)s::text is null or btrim(%(q)s::text) = '' or cu.name ilike '%%' || btrim(%(q)s::text) || '%%' or cu.phone ilike '%%' || btrim(%(q)s::text) || '%%'
                 or b.bill_no ilike '%%' || btrim(%(q)s::text) || '%%' or ld.code ilike '%%' || btrim(%(q)s::text) || '%%' or coalesce(cu.area, '') ilike '%%' || btrim(%(q)s::text) || '%%')"""
    return fetch(f"""
      select b.id as bill_id, b.bill_no, ld.code as lead_code, cu.name as customer_name, cu.phone, cu.area, lo.driver_id, pr.full_name as driver_name,
             lo.code as load_code, b.status, b.payment_method, b.upi_ref, bt.total_kg, bt.total_amount,
             b.created_at, b.sent_at, b.whatsapp_opened_at, b.confirmed_at, b.paid_at, b.confirm_proof_url, fr.code as franchise_code
      from bills b
      join bill_totals bt on bt.bill_id = b.id
      join leads ld on ld.id = b.lead_id
      join customers cu on cu.id = ld.customer_id
      join loads lo on lo.id = b.load_id
      join profiles pr on pr.id = lo.driver_id
      join franchises fr on fr.id = lo.franchise_id
      where (b.created_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
        and (%(f)s::integer is null or lo.franchise_id = %(f)s::integer)
        and (%(st)s::text is null or b.status = %(st)s::text)
        and (%(drv)s::uuid is null or lo.driver_id = %(drv)s::uuid)
        and {search}
      order by b.created_at desc
      limit greatest(least(%(lim)s::integer, 500), 1)
    """, {"a": _d(p_from), "b": _d(p_to), "st": p_status, "drv": p_driver or None, "q": p_search,
          "lim": 200 if p_limit is None else int(p_limit), "f": p_franchise})


@rpc()
def hq_leads(ctx, p_from, p_to, p_status=None, p_driver=None, p_search=None, p_limit=300, p_franchise=None):
    _need_hq(ctx)
    return fetch(f"""
      select l.id as lead_id, l.code, cu.name as customer_name, cu.phone, cu.address, cu.area, l.driver_id, pr.full_name as driver_name,
             l.slot, l.status, l.items_said, b.bill_no, b.status as bill_status, l.created_at, l.closed_at, fr.code as franchise_code,
             l.fail_reason, l.fail_note, l.failed_at, l.latitude, l.longitude
      from leads l
      join customers cu on cu.id = l.customer_id
      join franchises fr on fr.id = l.franchise_id
      left join profiles pr on pr.id = l.driver_id
      left join bills b on b.lead_id = l.id
      where ((l.slot at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
             or (l.status in ('unassigned','scheduled','in_progress','failed') and %(st)s::text is not null))
        and (%(f)s::integer is null or l.franchise_id = %(f)s::integer)
        and (%(st)s::text is null or l.status = %(st)s::text)
        and (%(drv)s::uuid is null or l.driver_id = %(drv)s::uuid)
        and {SEARCH_SQL}
      order by l.slot desc nulls last, l.id desc
      limit greatest(least(%(lim)s::integer, 500), 1)
    """, {"a": _d(p_from), "b": _d(p_to), "st": p_status, "drv": p_driver or None, "q": p_search,
          "lim": 300 if p_limit is None else int(p_limit), "f": p_franchise})


@rpc()
def hq_loads(ctx, p_from, p_to, p_franchise=None):
    _need_hq(ctx)
    return fetch("""
      select l.id as load_id, l.code, l.driver_id, p.full_name as driver_name, l.vehicle_no, l.status, l.started_at, l.submitted_at,
             (select count(*) from bills b where b.load_id = l.id and b.status = 'paid') as pickups,
             (select coalesce(sum(bt.total_kg), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.load_id = l.id and b.status = 'paid') as billed_kg,
             (select coalesce(sum(bt.total_amount), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.load_id = l.id and b.status = 'paid') as billed_amount,
             (select sum(w.warehouse_kg) from load_weighings w where w.load_id = l.id and w.superseded_at is null) as weighed_kg,
             (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w where w.load_id = l.id and w.superseded_at is null) as variance_pct,
             (select count(*) from load_weighings w where w.load_id = l.id and w.superseded_at is null and not w.within_tolerance) as items_off,
             l.resolution_note, fr.code as franchise_code
      from loads l join profiles p on p.id = l.driver_id join franchises fr on fr.id = l.franchise_id
      where ((l.started_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date or l.status in ('submitted','flagged'))
        and (%(f)s::integer is null or l.franchise_id = %(f)s::integer)
      order by l.id desc
    """, {"a": _d(p_from), "b": _d(p_to), "f": p_franchise})


@rpc()
def hq_team(ctx, p_franchise=None):
    _need_hq(ctx)
    return fetch("""
      select p.id, p.full_name, u.email::text as email, p.role, p.phone, p.territory, p.vehicle_no, p.active,
             (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id) as cash_in_hand,
             (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress')) as open_leads,
             p.franchise_id, fr.code as franchise_code, fr.name as franchise_name
      from profiles p left join users u on u.id = p.id left join franchises fr on fr.id = p.franchise_id
      where %(f)s::integer is null or p.franchise_id = %(f)s::integer or p.role = 'hq'
      order by case p.role when 'hq' then 0 when 'supervisor' then 1 when 'warehouse' then 2 else 3 end, fr.code, p.full_name
    """, {"f": p_franchise})


@rpc()
def hq_inventory(ctx, p_franchise=None):
    """Current stock by material and franchise warehouse, including the warehouse staff assigned there."""
    _need_hq(ctx)
    return fetch("""
      select f.id as franchise_id, f.code as franchise_code, f.name as franchise_name,
             coalesce(w.warehouse_names, '') as warehouse_names,
             cr.item_id, cr.item_name, cr.rate_per_kg,
             coalesce((select sum(lw.warehouse_kg)
                       from load_weighings lw join loads l on l.id = lw.load_id
                       where lw.item_id = cr.item_id and lw.franchise_id = f.id
                         and lw.superseded_at is null and l.status in ('reconciled','flagged')), 0)
             - coalesce((select sum(r.kg) from hq_releases r
                         where r.item_id = cr.item_id and r.franchise_id = f.id), 0) as stock_now_kg
      from franchises f
      cross join current_rates cr
      left join lateral (
        select string_agg(p.full_name, ', ' order by p.full_name) as warehouse_names
        from profiles p where p.franchise_id = f.id and p.role = 'warehouse' and p.active
      ) w on true
      where (%(f)s::integer is null or f.id = %(f)s::integer)
      order by f.code, cr.item_name
    """, {"f": p_franchise})


@rpc()
def hq_franchises(ctx, p_from, p_to):
    _need_hq(ctx)
    return fetch("""
      select f.id as franchise_id, f.code, f.name, f.district, f.constituency, f.active,
        (select count(*) from profiles p where p.franchise_id = f.id and p.role = 'driver' and p.active) as drivers,
        (select count(*) from profiles p where p.franchise_id = f.id and p.role <> 'driver' and p.active) as staff,
        (select count(*) from leads l where l.franchise_id = f.id and l.status in ('scheduled','in_progress') and (l.slot at time zone 'Asia/Kolkata')::date = (now() at time zone 'Asia/Kolkata')::date) as leads_today,
        (select count(*) from leads l where l.franchise_id = f.id and l.status = 'scheduled' and l.slot < now() - interval '3 hours') as leads_late,
        (select count(*) from hq_paid_bills pb where pb.franchise_id = f.id and pb.paid_day between %(a)s::date and %(b)s::date) as pickups,
        (select coalesce(sum(pb.total_kg), 0) from hq_paid_bills pb where pb.franchise_id = f.id and pb.paid_day between %(a)s::date and %(b)s::date) as kg,
        (select coalesce(sum(pb.total_amount), 0) from hq_paid_bills pb where pb.franchise_id = f.id and pb.paid_day between %(a)s::date and %(b)s::date) as amount,
        (select coalesce(sum(
            coalesce((select sum(w.warehouse_kg) from load_weighings w join loads l3 on l3.id = w.load_id
                       where w.item_id = i.id and w.superseded_at is null and l3.status in ('reconciled','flagged') and w.franchise_id = f.id), 0)
          - coalesce((select sum(r.kg) from hq_releases r where r.item_id = i.id and r.franchise_id = f.id), 0)), 0)
           from scrap_items i where i.active) as stock_kg,
        (select coalesce(sum(c.amount), 0) from cash_ledger c where c.franchise_id = f.id) as cash_in_hand,
        (select count(*) from loads l where l.franchise_id = f.id and l.status = 'open') as loads_open,
        (select count(*) from loads l where l.franchise_id = f.id and l.status = 'submitted') as loads_waiting,
        (select count(*) from loads l where l.franchise_id = f.id and l.status = 'flagged') as loads_flagged,
        (select count(*) from cash_settlements s where s.franchise_id = f.id and s.status = 'disputed' and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)) as disputes_open,
        (select count(*) from cash_settlements s where s.franchise_id = f.id and s.status = 'counted') as counts_unverified,
        (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w where w.franchise_id = f.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date) as variance_pct,
        greatest((select max(l.started_at) from loads l where l.franchise_id = f.id), (select max(pb.paid_at) from hq_paid_bills pb where pb.franchise_id = f.id)) as last_activity
      from franchises f
      order by f.code
    """, {"a": _d(p_from), "b": _d(p_to)})


@rpc()
def hq_open_disputes(ctx, p_franchise=None):
    _need_hq(ctx)
    return fetch("""
      select s.id as settlement_id, l.code as load_code, d.full_name as driver_name, f.code as franchise_code, s.expected_cash, s.counted_cash,
             s.difference, cb.full_name as counted_by_name, vb.full_name as verified_by_name, s.verify_note, s.verified_at
      from cash_settlements s
      join loads l on l.id = s.load_id
      join profiles d on d.id = s.driver_id
      join franchises f on f.id = s.franchise_id
      left join profiles cb on cb.id = s.counted_by
      left join profiles vb on vb.id = s.verified_by
      where s.status = 'disputed' and (%(f)s::integer is null or s.franchise_id = %(f)s::integer)
        and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)
      order by s.verified_at desc
    """, {"f": p_franchise})


# ---------------------------------------------------------------------------------------------- franchises
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,11}$")
CODE_MSG = "The code must be 2 to 12 letters, numbers or dashes (for example KKD)."


@rpc()
def hq_add_franchise(ctx, p_code, p_name, p_district=None, p_constituency=None):
    _need_hq(ctx)
    code = btrim(p_code).upper()
    if not CODE_RE.match(code):
        raise ApiError(CODE_MSG)
    if blank(p_name):
        raise ApiError("Enter the franchise name.")
    if Franchise.objects.filter(code=code).exists():
        raise ApiError(f"The code {code} is already used by another franchise.")
    fr = Franchise.objects.create(code=code, name=btrim(p_name), district=nullify(p_district), constituency=nullify(p_constituency))
    hq_log(ctx, "franchise_added", code, {"name": btrim(p_name)}, fr.pk)
    return fr.pk


@rpc()
def hq_update_franchise(ctx, p_id, p_code, p_name, p_district=None, p_constituency=None, p_active=True):
    _need_hq(ctx)
    old = Franchise.objects.select_for_update().filter(pk=p_id).first()
    if old is None:
        raise ApiError("Franchise not found.")
    code = btrim(p_code).upper()
    if not CODE_RE.match(code):
        raise ApiError(CODE_MSG)
    if blank(p_name):
        raise ApiError("Enter the franchise name.")
    if Franchise.objects.filter(code=code).exclude(pk=p_id).exists():
        raise ApiError(f"The code {code} is already used by another franchise.")
    if old.active and not p_active:
        if Load.objects.filter(franchise_id=p_id, status="open").exists():
            raise ApiError("A driver of this franchise is on the road. Switch it off after the route ends.")
        if Lead.objects.filter(franchise_id=p_id, status__in=("scheduled", "in_progress")).exists():
            raise ApiError("This franchise still has open leads. Cancel or reassign them first.")
    old_code, was_active = old.code, old.active
    old.code, old.name = code, btrim(p_name)
    old.district, old.constituency, old.active = nullify(p_district), nullify(p_constituency), bool(p_active)
    old.save()
    hq_log(ctx, "franchise_updated", code, {"was_active": was_active, "now_active": bool(p_active), "old_code": old_code}, p_id)
    return code


# ---------------------------------------------------------------------------------------------- people
@rpc()
def hq_add_person(ctx, p_email, p_full_name, p_role, p_franchise, p_phone=None, p_territory=None, p_vehicle_no=None):
    """Set up a person who already has a login: their name, role and franchise."""
    _need_hq(ctx)
    if p_role not in ("driver", "warehouse", "supervisor"):
        raise ApiError("Role must be driver, warehouse or supervisor.")
    if blank(p_full_name):
        raise ApiError("Enter the name.")
    if not Franchise.objects.filter(pk=p_franchise, active=True).exists():
        raise ApiError("Choose an active franchise.")
    user = User.objects.filter(email__iexact=btrim(p_email)).first()
    if user is None:
        raise ApiError("No login with this email yet. Create it first with Create logins.")
    if Profile.objects.filter(pk=user.pk).exists():
        raise ApiError("This login is already set up.")
    if fetch_one("select id from kwd_profiles where id = %(u)s", {"u": user.pk}):
        raise ApiError("This login belongs to the field app and cannot be assigned here.")
    Profile.objects.create(user=user, full_name=btrim(p_full_name), role=p_role, franchise_id=p_franchise, phone=nullify(p_phone),
                           territory=nullify(p_territory), vehicle_no=nullify(p_vehicle_no), active=True)
    hq_log(ctx, "person_added", btrim(p_full_name), {"role": p_role, "email": btrim(p_email).lower()}, p_franchise)
    return btrim(p_full_name)


@rpc()
def hq_update_profile(ctx, p_id, p_full_name, p_phone=None, p_territory=None, p_vehicle_no=None, p_active=True, p_franchise=None):
    _need_hq(ctx)
    old = Profile.objects.select_for_update().filter(pk=p_id).first()
    if old is None:
        raise ApiError("Person not found.")
    if old.role == "super_admin" or old.is_super_admin:
        raise ApiError("Super Admin accounts cannot be edited here.", status=403)
    if blank(p_full_name):
        raise ApiError("Enter a name.")
    if str(p_id) == str(ctx.uid) and not p_active:
        raise ApiError("You cannot deactivate your own login.")
    new_f = None if old.role == "hq" else (p_franchise if p_franchise is not None else old.franchise_id)
    if old.role != "hq":
        # the new franchise must be active (staying where they already are is always fine)
        if new_f is None or not Franchise.objects.filter(Q(active=True) | Q(pk=old.franchise_id), pk=new_f).exists():
            raise ApiError("Choose an active franchise.")
    if old.role == "driver" and ((old.active and not p_active) or new_f != old.franchise_id):
        if Load.objects.filter(driver_id=p_id, status="open").exists():
            raise ApiError("This driver has a route on the road. Do this after the route ends.")
        if Lead.objects.filter(driver_id=p_id, status__in=("scheduled", "in_progress")).exists():
            raise ApiError("Reassign this driver's open leads first.")
    if old.role == "driver" and new_f != old.franchise_id:
        bal = fetch_one("select coalesce(sum(amount), 0) as s from cash_ledger where driver_id = %(d)s", {"d": p_id})["s"]
        if bal != 0:
            raise ApiError("This driver still holds cash. Count it before moving the driver to another franchise.")
    was_active, old_name, old_f = old.active, old.full_name, old.franchise_id
    old.full_name, old.phone, old.territory = btrim(p_full_name), nullify(p_phone), nullify(p_territory)
    old.vehicle_no, old.active, old.franchise_id = nullify(p_vehicle_no), bool(p_active), new_f
    old.save()
    hq_log(ctx, "profile_updated", old_name, {"id": str(p_id), "was_active": was_active, "now_active": bool(p_active),
                                              "from_franchise": old_f, "to_franchise": new_f}, new_f)
    return btrim(p_full_name)


def end_sessions(user_id):
    """Sign a person out on every device (used after a password reset)."""
    AuthSession.objects.filter(user_id=user_id).delete()


# ---------------------------------------------------------------------------------------------- leads
@rpc()
def hq_reassign_lead(ctx, p_lead_id, p_driver_id):
    _need_hq(ctx)
    lead = Lead.objects.select_for_update().filter(pk=p_lead_id).first()
    if lead is None:
        raise ApiError("Lead not found.")
    if lead.status not in ("unassigned", "scheduled", "failed"):
        raise ApiError(f"Only a lead that has not been started can be assigned (this one is {lead.status}).")
    drv = Profile.objects.filter(pk=p_driver_id, role="driver", active=True).first() if p_driver_id else None
    if drv is None:
        raise ApiError("Choose an active driver.")
    if lead.driver_id == drv.pk and lead.status == "scheduled":
        raise ApiError(f"This lead is already with {drv.full_name}.")
    was, from_driver, from_f = lead.status, lead.driver_id, lead.franchise_id
    lead.driver_id, lead.franchise_id, lead.status = drv.pk, drv.franchise_id, "scheduled"
    lead.fail_reason = lead.fail_note = lead.failed_at = None
    lead.save(update_fields=["driver", "franchise", "status", "fail_reason", "fail_note", "failed_at"])
    hq_log(ctx, "lead_reassigned", lead.code,
           {"from": str(from_driver) if from_driver else None, "to": str(drv.pk), "from_franchise": from_f,
            "to_franchise": drv.franchise_id, "was": was}, drv.franchise_id)
    return drv.full_name


@rpc()
def hq_cancel_lead(ctx, p_lead_id, p_reason):
    _need_hq(ctx)
    if blank(p_reason):
        raise ApiError("Add a reason for cancelling.")
    lead = Lead.objects.select_for_update().filter(pk=p_lead_id).first()
    if lead is None:
        raise ApiError("Lead not found.")
    if lead.status not in ("unassigned", "scheduled", "failed"):
        raise ApiError(f"Only a lead that has not been started can be cancelled (this one is {lead.status}).")
    was = lead.status
    lead.status = "cancelled"
    lead.save(update_fields=["status"])
    hq_log(ctx, "lead_cancelled", lead.code, {"reason": btrim(p_reason), "was": was}, lead.franchise_id)
    return lead.code


@rpc()
def hq_resolve_dispute(ctx, p_settlement_id, p_decision, p_note):
    _need_hq(ctx)
    if p_decision not in ("recover_from_driver", "write_off", "no_action"):
        raise ApiError("Choose what happens to the shortage.")
    if blank(p_note):
        raise ApiError("Add a note explaining the decision.")
    s = CashSettlement.objects.select_for_update().filter(pk=p_settlement_id).first()
    if s is None or s.status != "disputed":
        raise ApiError("This settlement is not disputed.")
    if SettlementResolution.objects.filter(settlement_id=s.pk).exists():
        raise ApiError("This dispute has already been resolved.")
    SettlementResolution.objects.create(settlement_id=s.pk, decision=p_decision, note=btrim(p_note), resolved_by_id=ctx.uid)
    hq_log(ctx, "dispute_resolved", f"settlement {p_settlement_id}", {"decision": p_decision, "difference": float(s.difference)}, s.franchise_id)
    return p_decision


# ---------------------------------------------------------------------------------------------- rates and materials
@rpc()
def hq_set_rate(ctx, p_item_id, p_rate):
    _need_hq(ctx)
    rate = dec(p_rate, "rate") if p_rate is not None else None
    if rate is None or rate <= 0 or rate > 100000:
        raise ApiError("Enter a rate between 0 and 100000 per kg.")
    item = ScrapItem.objects.filter(pk=p_item_id, active=True).first()
    if item is None:
        raise ApiError("Unknown material.")
    row = fetch_one("select rate_per_kg from current_rates where item_id = %(i)s", {"i": item.pk})
    old = row["rate_per_kg"] if row else None
    if old is not None and old == rate:
        raise ApiError(f"{item.name} is already ₹{format(rate, 'f')} per kg.")
    Rate.objects.create(item_id=item.pk, rate_per_kg=rate, set_by_id=ctx.uid)
    hq_log(ctx, "rate_set", item.name, {"old": float(old) if old is not None else None, "new": float(rate)})
    return item.name


@rpc()
def hq_add_item(ctx, p_name, p_rate):
    _need_hq(ctx)
    name = re.sub(r"\s+", " ", btrim(p_name))
    if len(name) < 2 or len(name) > 30:
        raise ApiError("The name must be 2 to 30 characters.")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 &/().,+-]*$", name):
        raise ApiError("Use letters, numbers and spaces in the name.")
    rate = dec(p_rate, "rate") if p_rate is not None else None
    if rate is None or rate <= 0 or rate > 100000:
        raise ApiError("Enter a rate between 0 and 100000 per kg.")
    dup = ScrapItem.objects.filter(name__iexact=name).first()
    if dup is not None:
        if dup.active:
            raise ApiError(f"{dup.name} already exists.")
        raise ApiError(f"{dup.name} was removed earlier. Restore it instead of adding it again.")
    item = ScrapItem.objects.create(name=name, active=True)
    Rate.objects.create(item_id=item.pk, rate_per_kg=rate, set_by_id=ctx.uid)
    hq_log(ctx, "item_added", name, {"rate": float(rate)})
    return item.pk


@rpc()
def hq_set_item_active(ctx, p_item_id, p_active):
    """Remove (switch off) or restore a material. Nothing is deleted: past bills and stock history keep working."""
    _need_hq(ctx)
    item = ScrapItem.objects.select_for_update().filter(pk=p_item_id).first()
    if item is None:
        raise ApiError("Material not found.")
    if item.active == bool(p_active):
        raise ApiError(f"{item.name} is already {'active' if p_active else 'removed'}.")
    if not p_active:
        if ScrapItem.objects.filter(active=True).count() <= 1:
            raise ApiError("You cannot remove the last material.")
        have = stock_kg(item.pk, None)
        if have > Decimal("0.0001"):
            raise ApiError(f"There is still {show_num(have, 1)} kg of {item.name} in the yards. Release it to HQ first.")
        codes = fetch("select string_agg(code, ', ') as c from hq_requirement_progress where item_id = %(i)s and status in ('open','partial')", {"i": item.pk})[0]["c"]
        if codes:
            raise ApiError(f"HQ requirement {codes} still asks for {item.name}. Cancel it first.")
        codes = fetch("""select string_agg(distinct l.code, ', ') as c from bill_items bi join bills b on b.id = bi.bill_id join loads l on l.id = b.load_id
                         where bi.item_id = %(i)s and l.status in ('open','submitted','flagged')""", {"i": item.pk})[0]["c"]
        if codes:
            raise ApiError(f"{item.name} is in loads that are not finished yet ({codes}). Try again after they are weighed.")
    elif not Rate.objects.filter(item_id=item.pk).exists():
        raise ApiError("This material has no rate. Add it again with a rate.")
    item.active = bool(p_active)
    item.save(update_fields=["active"])
    hq_log(ctx, "item_restored" if p_active else "item_removed", item.name, {})
    return item.name
