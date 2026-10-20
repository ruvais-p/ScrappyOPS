"""Reporting views, the running numbers, and the database-level guards that make records tamper-proof.
(The guards repeat rules the Python code already follows, so even a direct database edit cannot break them.)"""
from django.db import migrations

VIEWS = r"""
create or replace view bill_totals as
  select b.id as bill_id, b.bill_no, b.lead_id, b.load_id, b.status, b.payment_method,
         coalesce(t.total_kg, 0::numeric) as total_kg, coalesce(t.total_amount, 0::numeric) as total_amount
  from bills b
  cross join lateral (select sum(bi.qty_kg) as total_kg, sum(bi.amount) as total_amount from bill_items bi where bi.bill_id = b.id) t;

create or replace view current_rates as
  select distinct on (r.item_id) r.item_id, i.name as item_name, r.rate_per_kg, r.effective_from
  from rates r join scrap_items i on i.id = r.item_id
  where i.active and r.effective_from <= clock_timestamp()
  order by r.item_id, r.effective_from desc;

create or replace view driver_cash_in_hand as
  select p.id as driver_id, p.full_name, coalesce(sum(c.amount), 0::numeric) as cash_in_hand
  from profiles p left join cash_ledger c on c.driver_id = p.id
  where p.role = 'driver'
  group by p.id, p.full_name;

create or replace view load_item_totals as
  select l.id as load_id, l.code as load_code, l.driver_id, i.name as item_name,
         sum(bi.qty_kg) as total_kg, sum(bi.amount) as total_value
  from loads l
  join bills b on b.load_id = l.id and b.status = 'paid'
  join bill_items bi on bi.bill_id = b.id
  join scrap_items i on i.id = bi.item_id
  group by l.id, l.code, l.driver_id, i.name;

create or replace view wh_stock_movements as
  select (w.weighed_at at time zone 'Asia/Kolkata')::date as day, 'received'::text as kind, w.item_id, i.name as item_name,
         w.warehouse_kg as kg, l.code as ref, w.weighed_at as happened_at, w.franchise_id
  from load_weighings w
  join loads l on l.id = w.load_id
  join scrap_items i on i.id = w.item_id
  where w.superseded_at is null and l.status in ('reconciled','flagged')
  union all
  select (r.released_at at time zone 'Asia/Kolkata')::date, 'released', r.item_id, i.name, r.kg, r.code, r.released_at, r.franchise_id
  from hq_releases r
  join scrap_items i on i.id = r.item_id;

create or replace view hq_requirement_progress as
  select q.id, q.code, q.item_id, i.name as item_name, q.required_kg,
         coalesce(r.kg, 0) as released_kg,
         greatest(q.required_kg - coalesce(r.kg, 0), 0) as remaining_kg,
         q.due_date,
         (q.created_at at time zone 'Asia/Kolkata')::date as raised_on,
         q.note,
         case when q.status = 'cancelled' then 'cancelled'
              when coalesce(r.kg, 0) >= q.required_kg then 'completed'
              when coalesce(r.kg, 0) > 0 then 'partial'
              else 'open' end as status,
         (q.status = 'open' and coalesce(r.kg, 0) < q.required_kg and q.due_date is not null
            and q.due_date < (now() at time zone 'Asia/Kolkata')::date) as is_overdue,
         q.franchise_id
  from hq_requirements q
  join scrap_items i on i.id = q.item_id
  left join (select requirement_id, sum(kg) as kg from hq_releases group by requirement_id) r on r.requirement_id = q.id;

create or replace view hq_paid_bills as
  select b.id as bill_id, lo.franchise_id, lo.driver_id, b.load_id, b.payment_method, b.paid_at,
         (b.paid_at at time zone 'Asia/Kolkata')::date as paid_day, b.created_at, bt.total_kg, bt.total_amount
  from bills b
  join loads lo on lo.id = b.load_id
  join bill_totals bt on bt.bill_id = b.id
  where b.status = 'paid';
"""

DROP_VIEWS = """
drop view if exists hq_paid_bills; drop view if exists hq_requirement_progress; drop view if exists wh_stock_movements;
drop view if exists load_item_totals; drop view if exists driver_cash_in_hand; drop view if exists current_rates; drop view if exists bill_totals;
"""

GUARDS = r"""
create or replace function guard_immutable() returns trigger language plpgsql as $$
begin raise exception 'This record cannot be changed or deleted.'; end $$;

create trigger hq_audit_immutable before update or delete on hq_audit for each row execute function guard_immutable();
create trigger hq_releases_immutable before update or delete on hq_releases for each row execute function guard_immutable();
create trigger settlement_resolutions_immutable before update or delete on settlement_resolutions for each row execute function guard_immutable();
create trigger cash_ledger_immutable before update or delete on cash_ledger for each row execute function guard_immutable();

create or replace function guard_weighings() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then raise exception 'Weighing records cannot be deleted.'; end if;
  if old.superseded_at is not null or new.superseded_at is null
     or (new.load_id, new.item_id, new.billed_kg, new.warehouse_kg, new.within_tolerance, new.weighed_by, new.weighed_at)
        is distinct from
        (old.load_id, old.item_id, old.billed_kg, old.warehouse_kg, old.within_tolerance, old.weighed_by, old.weighed_at)
  then raise exception 'Weighing records cannot be edited. Re-weigh the load instead.'; end if;
  return new;
end $$;
create trigger load_weighings_guard before update or delete on load_weighings for each row execute function guard_weighings();

create or replace function guard_settlements() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then raise exception 'Cash settlements cannot be deleted.'; end if;
  if old.status <> 'counted' then raise exception 'This settlement is final.'; end if;
  if (new.load_id, new.driver_id, new.expected_cash, new.counted_cash, new.cash_paid, new.upi_paid, new.counted_by, new.counted_at, new.count_note, new.covered_load_ids)
     is distinct from
     (old.load_id, old.driver_id, old.expected_cash, old.counted_cash, old.cash_paid, old.upi_paid, old.counted_by, old.counted_at, old.count_note, old.covered_load_ids)
  then raise exception 'Counted amounts cannot be changed.'; end if;
  return new;
end $$;
create trigger cash_settlements_guard before update or delete on cash_settlements for each row execute function guard_settlements();

create or replace function block_locked_bill_items() returns trigger language plpgsql as $$
declare s text;
begin
  select status into s from bills where id = coalesce(new.bill_id, old.bill_id);
  if s is not null and s <> 'draft' then raise exception 'Bill is locked after sending. Ask HQ to make changes.'; end if;
  return coalesce(new, old);
end $$;
create trigger bill_items_lock before insert or update or delete on bill_items for each row execute function block_locked_bill_items();

create or replace function block_cash_over_balance() returns trigger language plpgsql as $$
declare bal numeric;
begin
  if new.entry_type in ('cash_payout', 'handover') then
    select coalesce(sum(amount), 0) into bal from cash_ledger where driver_id = new.driver_id;
    if bal + new.amount < 0 then raise exception 'Not enough cash in hand (₹%). Use UPI.', bal; end if;
  end if;
  return new;
end $$;
create trigger cash_ledger_balance before insert on cash_ledger for each row execute function block_cash_over_balance();
"""

DROP_GUARDS = """
drop trigger if exists cash_ledger_balance on cash_ledger; drop trigger if exists bill_items_lock on bill_items;
drop trigger if exists cash_settlements_guard on cash_settlements; drop trigger if exists load_weighings_guard on load_weighings;
drop trigger if exists cash_ledger_immutable on cash_ledger; drop trigger if exists settlement_resolutions_immutable on settlement_resolutions;
drop trigger if exists hq_releases_immutable on hq_releases; drop trigger if exists hq_audit_immutable on hq_audit;
drop function if exists block_cash_over_balance(); drop function if exists block_locked_bill_items(); drop function if exists guard_settlements();
drop function if exists guard_weighings(); drop function if exists guard_immutable();
"""

COUNTERS = """
insert into counters (name, value) values ('lead_code', 1000), ('load_code', 0), ('bill_no', 0), ('requirement_code', 0), ('release_code', 300)
on conflict (name) do nothing;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [
        migrations.RunSQL(COUNTERS, reverse_sql="delete from counters;"),
        migrations.RunSQL(VIEWS, reverse_sql=DROP_VIEWS),
        migrations.RunSQL(GUARDS, reverse_sql=DROP_GUARDS),
    ]
