"""Read-only cross-domain business intelligence for explicitly granted HQ accounts."""
from datetime import date
from uuid import UUID

from core.models import Profile
from core.services.common import ApiError, fetch, fetch_one
from core.services.registry import rpc
from core.services.warehouse import _d


def _need_super_admin(ctx):
    if ctx.role != "super_admin" or not Profile.objects.filter(pk=ctx.uid, active=True, is_super_admin=True).exists():
        raise ApiError("Super Admin access is required.", status=403, code="42501")


@rpc()
def super_admin_business_intelligence(ctx, p_from, p_to, p_stream="all", p_franchise=None):
    """Return separately attributed scrap, KWD franchise, pipeline, and TA/DA reports."""
    _need_super_admin(ctx)
    if p_stream not in ("all", "scrap", "digester"):
        raise ApiError("Choose a valid business stream.")
    a, b = _d(p_from), _d(p_to)
    if b < a:
        raise ApiError("The end date must be on or after the start date.")
    try:
        from_date, to_date = date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        raise ApiError("Choose valid report dates.")
    fy_from = from_date.year if from_date.month >= 4 else from_date.year - 1
    fy_to = to_date.year if to_date.month >= 4 else to_date.year - 1
    if p_franchise in (None, ""):
        scrap_franchise = digester_franchise = None
    elif p_stream == "scrap":
        try:
            scrap_franchise = int(p_franchise)
        except (TypeError, ValueError):
            raise ApiError("Choose a valid scrap franchise.")
        digester_franchise = None
    elif p_stream == "digester":
        try:
            digester_franchise = UUID(str(p_franchise))
        except (TypeError, ValueError, AttributeError):
            raise ApiError("Choose a valid digester franchise.")
        scrap_franchise = None
    else:
        raise ApiError("Choose a business stream before filtering by franchise.")

    result = {"period": {"from": a, "to": b, "timezone": "Asia/Kolkata"}, "stream": p_stream,
              "franchises": {"scrap": [], "digester": []}}
    if p_stream in ("all", "scrap"):
        result["franchises"]["scrap"] = fetch("select id, code, name, active from franchises order by code")
        prm = {"a": a, "b": b, "f": scrap_franchise}
        summary = fetch_one("""
          select count(*) as bill_count, coalesce(sum(total_kg),0) as kg, coalesce(sum(total_amount),0) as amount
          from hq_paid_bills where paid_day between %(a)s::date and %(b)s::date
            and (%(f)s::integer is null or franchise_id=%(f)s::integer)
        """, prm)
        summary["weighted_avg_rate"] = (summary["amount"] / summary["kg"]) if summary["kg"] else None
        summary["weighing"] = fetch_one("""
          select coalesce(sum(w.billed_kg),0) as billed_kg,coalesce(sum(w.warehouse_kg),0) as warehouse_kg
          from load_weighings w where w.superseded_at is null
            and (w.weighed_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
            and (%(f)s::integer is null or w.franchise_id=%(f)s::integer)
        """, prm)
        daily = fetch("""
          select d.month, coalesce(x.bill_count,0) as bill_count, coalesce(x.kg,0) as kg, coalesce(x.amount,0) as amount
          from generate_series(date_trunc('month', %(a)s::date), date_trunc('month', %(b)s::date), interval '1 month') d(month)
          left join (select date_trunc('month',paid_day)::date as month, count(*) as bill_count, sum(total_kg) as kg, sum(total_amount) as amount
                     from hq_paid_bills where paid_day between %(a)s::date and %(b)s::date
                       and (%(f)s::integer is null or franchise_id=%(f)s::integer)
                     group by 1) x on x.month=d.month::date order by d.month
        """, prm)
        items = fetch("""
          select i.id as item_id, i.name as item_name, coalesce(sum(bi.qty_kg),0) as kg, coalesce(sum(bi.amount),0) as amount,
                 count(distinct bi.bill_id) as bills,
                 case when sum(bi.qty_kg)>0 then sum(bi.amount)/sum(bi.qty_kg) else null end as avg_rate
          from scrap_items i left join hq_paid_bills pb on pb.paid_day between %(a)s::date and %(b)s::date
            and (%(f)s::integer is null or pb.franchise_id=%(f)s::integer)
            left join bill_items bi on bi.bill_id=pb.bill_id and bi.item_id=i.id
          where i.active group by i.id,i.name order by i.name
        """, prm)
        stock = fetch("""
          select f.id as franchise_id,f.code as franchise_code,f.name as franchise_name,cr.item_id,cr.item_name,cr.rate_per_kg,
            coalesce((select sum(w.warehouse_kg) from load_weighings w join loads l on l.id=w.load_id
              where w.item_id=cr.item_id and w.franchise_id=f.id and w.superseded_at is null and l.status in ('reconciled','flagged')),0)
            - coalesce((select sum(r.kg) from hq_releases r where r.item_id=cr.item_id and r.franchise_id=f.id),0) as stock_kg
          from franchises f cross join current_rates cr where (%(f)s::integer is null or f.id=%(f)s::integer)
          order by f.code,cr.item_name
        """, {"f": scrap_franchise})
        leads = fetch("""
          select status,count(*) as count from leads where (slot at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
            and (%(f)s::integer is null or franchise_id=%(f)s::integer) group by status order by status
        """, prm)
        result["scrap"] = {"summary": summary, "monthly": daily, "items": items, "stock": stock, "leads": leads}

    if p_stream in ("all", "digester"):
        result["franchises"]["digester"] = fetch("select id,business_name,district_id,is_active from kwd_fr_franchises order by business_name")
        prm = {"a": a, "b": b, "f": str(digester_franchise) if digester_franchise else None}
        sales = fetch_one("""
          select count(*) as invoice_count, coalesce(sum(s.total),0) as invoiced,
                 coalesce(sum(s.total-s.amount_received),0) as outstanding
          from kwd_fr_sales s where s.status='active' and s.sale_date between %(a)s::date and %(b)s::date
            and (%(f)s::uuid is null or s.franchise_id=%(f)s::uuid)
        """, prm)
        receipts = fetch_one("""
          select coalesce(sum(r.amount),0) as received from kwd_fr_payment_receipts r join kwd_fr_sales s on s.id=r.sale_id
          where s.status='active' and (r.received_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date
            and (%(f)s::uuid is null or s.franchise_id=%(f)s::uuid)
        """, prm)
        monthly = fetch("""
          select d.month,coalesce(x.qty,0) as qty,coalesce(x.sales,0) as sales
          from generate_series(date_trunc('month',%(a)s::date),date_trunc('month',%(b)s::date),interval '1 month') d(month)
          left join (select date_trunc('month',s.sale_date)::date as month,sum(i.qty) as qty,sum(i.line_total) as sales
            from kwd_fr_sales s join kwd_fr_sale_items i on i.sale_id=s.id
            where s.status='active' and s.sale_date between %(a)s::date and %(b)s::date
              and (%(f)s::uuid is null or s.franchise_id=%(f)s::uuid) group by 1) x on x.month=d.month::date order by d.month
        """, prm)
        products = fetch("""
          select p.id as product_id,p.code,p.name,p.unit,p.list_price,
                 coalesce(sum(i.qty) filter(where s.id is not null),0) as qty,
                 coalesce(sum(i.line_total) filter(where s.id is not null),0) as sales,
                 case when sum(i.qty) filter(where s.id is not null)>0
                      then sum(i.line_total) filter(where s.id is not null)/sum(i.qty) filter(where s.id is not null) else null end as realized_price
          from kwd_fr_products p left join kwd_fr_sale_items i on i.product_id=p.id
            left join kwd_fr_sales s on s.id=i.sale_id and s.status='active' and s.sale_date between %(a)s::date and %(b)s::date
              and (%(f)s::uuid is null or s.franchise_id=%(f)s::uuid)
          where p.is_active group by p.id,p.code,p.name,p.unit,p.list_price order by p.sort,p.name
        """, prm)
        product_stock = fetch("""
          select f.id as franchise_id,f.business_name as franchise_name,p.id as product_id,p.name as product_name,p.unit,
                 coalesce(st.on_hand,0) as on_hand
          from kwd_fr_franchises f cross join kwd_fr_products p
          left join kwd_v_fr_stock st on st.franchise_id=f.id and st.product_id=p.id
          where f.is_active and p.is_active and (%(f)s::uuid is null or f.id=%(f)s::uuid)
          order by f.business_name,p.sort,p.name
        """, {"f": prm["f"]})
        targets = fetch("""
          select f.id as franchise_id,f.business_name,p.id as product_id,p.name as product_name,sum(t.target_units) as target_units,
                 sum(t.target_amount) as target_amount,coalesce(sum(si.qty),0) as sold_units,coalesce(sum(si.line_total),0) as sales_value
          from kwd_fr_targets t join kwd_fr_franchises f on f.id=t.franchise_id join kwd_fr_products p on p.id=t.product_id
          left join kwd_fr_sales s on s.franchise_id=f.id and s.status='active'
            and s.sale_date between greatest(%(a)s::date,t.month)
              and least(%(b)s::date,(t.month+interval '1 month - 1 day')::date)
          left join kwd_fr_sale_items si on si.sale_id=s.id and si.product_id=p.id
          where t.month between date_trunc('month',%(a)s::date)::date and date_trunc('month',%(b)s::date)::date
            and (%(f)s::uuid is null or f.id=%(f)s::uuid) group by f.id,f.business_name,p.id,p.name order by f.business_name,p.name
        """, prm)
        franchise_sales = fetch("""
          select f.id as franchise_id,f.business_name,count(s.id) as invoices,coalesce(sum(s.total),0) as sales,
                 coalesce((select sum(r.amount) from kwd_fr_payment_receipts r join kwd_fr_sales sr on sr.id=r.sale_id
                   where sr.franchise_id=f.id and sr.status='active'
                     and (r.received_at at time zone 'Asia/Kolkata')::date between %(a)s::date and %(b)s::date),0) as received,
                 coalesce(sum(s.total-s.amount_received),0) as outstanding,
                 count(s.id) filter (where s.delivery_status <> 'delivered') as to_deliver
          from kwd_fr_franchises f left join kwd_fr_sales s on s.franchise_id=f.id and s.status='active'
            and s.sale_date between %(a)s::date and %(b)s::date
          where f.is_active and (%(f)s::uuid is null or f.id=%(f)s::uuid)
          group by f.id,f.business_name order by f.business_name
        """, prm)
        franchise_leads = fetch("""
          select l.franchise_id,f.business_name,l.status,count(*) as count,coalesce(sum(l.qty),0) as units
          from kwd_fr_leads l join kwd_fr_franchises f on f.id=l.franchise_id
          where l.created_at >= %(a)s::date and l.created_at < %(b)s::date + interval '1 day'
            and (%(f)s::uuid is null or l.franchise_id=%(f)s::uuid)
          group by l.franchise_id,f.business_name,l.status order by f.business_name,l.status
        """, prm)
        opportunities = fetch("""
          select o.stage,count(*) as count,coalesce(sum(o.expected_value),0) as pipeline,
                 coalesce(sum(o.expected_value*o.probability/100.0),0) as weighted_pipeline
          from kwd_opportunities o join kwd_lsgds l on l.id=o.lsgd_id
          where split_part(o.financial_year,'-',1)::integer between %(fy_from)s and %(fy_to)s
          group by o.stage order by o.stage
        """, {**prm, "fy_from": fy_from, "fy_to": fy_to})
        expenses = fetch("""
          select p.id as tso_id,p.full_name,
            coalesce((select string_agg(d.name,', ' order by d.name) from kwd_user_districts ud join kwd_districts d on d.id=ud.district_id where ud.user_id=p.id),'') as districts,
            count(fd.id) as claim_days,string_agg(distinct fd.status,', ' order by fd.status) as claim_statuses,
            coalesce(sum(fd.total_claimed),0) as requested,
            coalesce(sum(fd.approved_amount) filter(where fd.status in ('ho_approved','paid')),0) as approved,
            coalesce(sum(fd.approved_amount) filter(where fd.status='paid'),0) as paid
          from kwd_field_days fd join kwd_profiles p on p.id=fd.tso_id
          where fd.day between %(a)s::date and %(b)s::date group by p.id,p.full_name order by p.full_name
        """, {"a": a, "b": b})
        yearly_products = fetch("""
          select case when extract(month from s.sale_date)>=4 then extract(year from s.sale_date)::integer
                      else (extract(year from s.sale_date)-1)::integer end as fy_start,
                 p.id as product_id,p.code,p.name,p.unit,sum(i.qty) as qty,sum(i.line_total) as sales,
                 case when sum(i.qty)>0 then sum(i.line_total)/sum(i.qty) else null end as realized_price
          from kwd_fr_sales s join kwd_fr_sale_items i on i.sale_id=s.id join kwd_fr_products p on p.id=i.product_id
          where s.status='active' and s.sale_date between %(a)s::date and %(b)s::date
            and (%(f)s::uuid is null or s.franchise_id=%(f)s::uuid)
          group by 1,p.id,p.code,p.name,p.unit order by 1 desc,p.name
        """, prm)
        result["digester"] = {"summary": {**sales, **receipts}, "monthly": monthly, "products": products,
                              "yearly_products": yearly_products,
                              "stock": product_stock, "targets": targets, "franchises": franchise_sales,
                              "leads": franchise_leads, "opportunities": opportunities}
        result["expenses"] = {"by_staff": expenses}
    return result
