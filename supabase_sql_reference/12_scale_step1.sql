/* =====================================================================
   SCALE STEP 1 · remove the two slow spots found in the load test
   Needs step 11. Same answers as before, computed in a way that stays fast.
     1. bill_totals no longer re-adds every bill's items for every route
     2. the cash-route report (wh_route_cash) no longer scans all bills per route
     3. "cash counts waiting" on the HQ overview is counted directly
   Nothing here drops or deletes anything.
   ===================================================================== */

create index if not exists cash_ledger_driver_created_idx on public.cash_ledger (driver_id, created_at);
create index if not exists loads_started_idx on public.loads (started_at);
create index if not exists cash_settlements_covered_gin on public.cash_settlements using gin (covered_load_ids);

/* totals per bill, computed only for the bills a query actually needs */
create or replace view public.bill_totals with (security_invoker = true) as
  select b.id as bill_id, b.bill_no, b.lead_id, b.load_id, b.status, b.payment_method,
         coalesce(t.total_kg, 0::numeric) as total_kg, coalesce(t.total_amount, 0::numeric) as total_amount
  from public.bills b
  cross join lateral (select sum(bi.qty_kg) as total_kg, sum(bi.amount) as total_amount from public.bill_items bi where bi.bill_id = b.id) t;

create or replace function public.wh_uncounted_loads(p_driver uuid, p_upto integer)
returns table (lid integer)
language sql stable security definer set search_path to 'public'
as $$
  select l.id from public.loads l
  where l.driver_id = p_driver and l.status <> 'open' and l.id <= p_upto
    and not exists (select 1 from public.cash_settlements s where s.load_id = l.id or s.covered_load_ids @> array[l.id])
$$;

create or replace function public.wh_route_cash(p_from date, p_to date, p_driver uuid default null, p_franchise integer default null)
returns table (load_id integer, load_code text, driver_id uuid, driver_name text, route_date date, route_status text,
               float_issued numeric, cash_paid numeric, upi_paid numeric, expected_cash numeric, counted_cash numeric,
               difference numeric, settlement_id integer, counted_by_name text, counted_at timestamptz, count_note text,
               verified_by_name text, verified_at timestamptz, verify_note text, franchise_id integer, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare
  v_f integer := public.fr_scope(p_franchise);
  v_from timestamptz := p_from::timestamp at time zone 'Asia/Kolkata';
  v_to timestamptz := (p_to + 1)::timestamp at time zone 'Asia/Kolkata';
begin
  return query
  select l.id, l.code, l.driver_id, p.full_name, (l.started_at at time zone 'Asia/Kolkata')::date, z.st,
         coalesce(fl.amt, 0), coalesce(s.cash_paid, pay.cash), coalesce(s.upi_paid, pay.upi),
         coalesce(s.expected_cash, case when z.st = 'awaiting_count' then (select greatest(coalesce(sum(c.amount), 0), 0) from cash_ledger c where c.driver_id = l.driver_id) end),
         s.counted_cash, s.difference, coalesce(s.id, cv.id), cb.full_name, s.counted_at, s.count_note, vb.full_name, s.verified_at, s.verify_note, l.franchise_id, fr.code
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
        and b.load_id = any (case when z.st = 'awaiting_count' then array(select u.lid from public.wh_uncounted_loads(l.driver_id, l.id) u) else array[l.id] end)) pay
  where l.started_at >= v_from and l.started_at < v_to
    and (p_driver is null or l.driver_id = p_driver)
    and (v_f is null or l.franchise_id = v_f)
  order by l.started_at desc;
end $$;

/* the overview: "counts waiting" is the number of drivers who are back, have no open route, and whose latest route is not counted */
create or replace function public.hq_overview(p_from date, p_to date, p_franchise integer default null)
returns jsonb language plpgsql stable security definer set search_path to 'public'
as $$
declare v_today date := (now() at time zone 'Asia/Kolkata')::date; f integer := p_franchise; r jsonb;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select jsonb_build_object(
    'franchises_active', (select count(*) from franchises where active),
    'drivers_active',    (select count(*) from profiles where role = 'driver' and active and (f is null or franchise_id = f)),
    'leads_scheduled',   (select count(*) from leads where status = 'scheduled' and (f is null or franchise_id = f)),
    'leads_today',       (select count(*) from leads where status in ('scheduled','in_progress') and (slot at time zone 'Asia/Kolkata')::date = v_today and (f is null or franchise_id = f)),
    'leads_in_progress', (select count(*) from leads where status = 'in_progress' and (f is null or franchise_id = f)),
    'leads_late',        (select count(*) from leads where status = 'scheduled' and slot < now() - interval '3 hours' and (f is null or franchise_id = f)),
    'leads_closed',      (select count(*) from leads where status = 'closed' and (closed_at at time zone 'Asia/Kolkata')::date between p_from and p_to and (f is null or franchise_id = f)),
    'leads_cancelled',   (select count(*) from leads where status = 'cancelled' and (created_at at time zone 'Asia/Kolkata')::date between p_from and p_to and (f is null or franchise_id = f)),
    'paid_bills',        (select count(*) from hq_paid_bills where paid_day between p_from and p_to and (f is null or franchise_id = f)),
    'kg',                (select coalesce(sum(total_kg), 0) from hq_paid_bills where paid_day between p_from and p_to and (f is null or franchise_id = f)),
    'amount',            (select coalesce(sum(total_amount), 0) from hq_paid_bills where paid_day between p_from and p_to and (f is null or franchise_id = f)),
    'cash_amount',       (select coalesce(sum(total_amount), 0) from hq_paid_bills where payment_method = 'cash' and paid_day between p_from and p_to and (f is null or franchise_id = f)),
    'upi_amount',        (select coalesce(sum(total_amount), 0) from hq_paid_bills where payment_method = 'upi' and paid_day between p_from and p_to and (f is null or franchise_id = f)),
    'loads_open',        (select count(*) from loads where status = 'open' and (f is null or franchise_id = f)),
    'loads_waiting',     (select count(*) from loads where status = 'submitted' and (f is null or franchise_id = f)),
    'loads_flagged',     (select count(*) from loads where status = 'flagged' and (f is null or franchise_id = f)),
    'billed_kg_weighed', (select coalesce(sum(billed_kg), 0) from load_weighings where superseded_at is null and (weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to and (f is null or franchise_id = f)),
    'weighed_kg',        (select coalesce(sum(warehouse_kg), 0) from load_weighings where superseded_at is null and (weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to and (f is null or franchise_id = f)),
    'cash_in_field',     (select coalesce(sum(amount), 0) from cash_ledger where (f is null or franchise_id = f)),
    'counts_waiting',    (select count(*) from (select p.id, (select l.id from loads l where l.driver_id = p.id and l.status <> 'open' order by l.id desc limit 1) as last_id
                                                from profiles p where p.role = 'driver' and (f is null or p.franchise_id = f)) d
                          where d.last_id is not null
                            and not exists (select 1 from loads o where o.driver_id = d.id and o.status = 'open')
                            and not exists (select 1 from cash_settlements s where s.load_id = d.last_id or s.covered_load_ids @> array[d.last_id])),
    'counts_unverified', (select count(*) from cash_settlements where status = 'counted' and (f is null or franchise_id = f)),
    'disputes_open',     (select count(*) from cash_settlements s where s.status = 'disputed' and (f is null or s.franchise_id = f) and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)),
    'shortage_total',    (select coalesce(sum(-difference), 0) from cash_settlements where difference < 0 and (counted_at at time zone 'Asia/Kolkata')::date between p_from and p_to and (f is null or franchise_id = f)),
    'stock_kg',          (select coalesce(sum(stock_now_kg), 0) from wh_stock_report(v_today, v_today, f)),
    'stock_value',       (select coalesce(sum(stock_now_kg * rate_per_kg), 0) from wh_stock_report(v_today, v_today, f)),
    'req_open',          (select count(*) from hq_requirement_progress where status in ('open','partial') and (f is null or franchise_id = f)),
    'req_remaining_kg',  (select coalesce(sum(remaining_kg), 0) from hq_requirement_progress where status in ('open','partial') and (f is null or franchise_id = f)),
    'req_overdue',       (select count(*) from hq_requirement_progress where is_overdue and (f is null or franchise_id = f))
  ) into r;
  return r;
end $$;

/* open disputes for the HQ cash screen, without scanning every route */
create or replace function public.hq_open_disputes(p_franchise integer default null)
returns table (settlement_id integer, load_code text, driver_name text, franchise_code text, expected_cash numeric, counted_cash numeric,
               difference numeric, counted_by_name text, verified_by_name text, verify_note text, verified_at timestamptz)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select s.id, l.code, d.full_name, f.code, s.expected_cash, s.counted_cash, s.difference, cb.full_name, vb.full_name, s.verify_note, s.verified_at
  from cash_settlements s
  join loads l on l.id = s.load_id
  join profiles d on d.id = s.driver_id
  join franchises f on f.id = s.franchise_id
  left join profiles cb on cb.id = s.counted_by
  left join profiles vb on vb.id = s.verified_by
  where s.status = 'disputed' and (p_franchise is null or s.franchise_id = p_franchise)
    and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)
  order by s.verified_at desc;
end $$;
revoke all on function public.hq_open_disputes(integer) from public, anon;
grant execute on function public.hq_open_disputes(integer) to authenticated;
