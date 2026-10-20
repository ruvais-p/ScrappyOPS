/* =====================================================================
   WAREHOUSE BACKEND · STEP 4 OF 4 · reports for the dashboard and live updates
   Needs steps 1 to 3 first.
   Customer names and phone numbers are never returned. Only the lead
   code and the area are shown to warehouse staff.
   ===================================================================== */

/* ---------- stock movements: every kg that came in or went out, with its Indian-time date ---------- */
create or replace view public.wh_stock_movements with (security_invoker = true) as
  select (w.weighed_at at time zone 'Asia/Kolkata')::date as day, 'received'::text as kind, w.item_id, i.name as item_name,
         w.warehouse_kg as kg, l.code as ref, w.weighed_at as happened_at
  from public.load_weighings w
  join public.loads l on l.id = w.load_id
  join public.scrap_items i on i.id = w.item_id
  where w.superseded_at is null and l.status in ('reconciled','flagged')
  union all
  select (r.released_at at time zone 'Asia/Kolkata')::date, 'released', r.item_id, i.name, r.kg, r.code, r.released_at
  from public.hq_releases r
  join public.scrap_items i on i.id = r.item_id;

/* ---------- HQ requirements with completion status ---------- */
create or replace view public.hq_requirement_progress with (security_invoker = true) as
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
            and q.due_date < (now() at time zone 'Asia/Kolkata')::date) as is_overdue
  from public.hq_requirements q
  join public.scrap_items i on i.id = q.item_id
  left join (select requirement_id, sum(kg) as kg from public.hq_releases group by requirement_id) r on r.requirement_id = q.id;

/* ---------- inventory for any date range: opening + received - released = closing ---------- */
create or replace function public.wh_stock_report(p_from date, p_to date)
returns table (item_id integer, item_name text, rate_per_kg numeric, opening_kg numeric, received_kg numeric,
               released_kg numeric, closing_kg numeric, closing_value numeric, hq_open_need_kg numeric, stock_now_kg numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if not is_wh_staff() then raise exception 'Not allowed.'; end if;
  return query
  select cr.item_id, cr.item_name, cr.rate_per_kg,
         coalesce(sum(case when m.day < p_from then (case m.kind when 'received' then m.kg else -m.kg end) end), 0),
         coalesce(sum(case when m.day between p_from and p_to and m.kind = 'received' then m.kg end), 0),
         coalesce(sum(case when m.day between p_from and p_to and m.kind = 'released' then m.kg end), 0),
         coalesce(sum(case when m.day <= p_to then (case m.kind when 'received' then m.kg else -m.kg end) end), 0),
         coalesce(sum(case when m.day <= p_to then (case m.kind when 'received' then m.kg else -m.kg end) end), 0) * cr.rate_per_kg,
         (select coalesce(sum(q.remaining_kg), 0) from hq_requirement_progress q where q.item_id = cr.item_id and q.status in ('open','partial')),
         public.wh_stock_kg(cr.item_id)
  from current_rates cr
  left join wh_stock_movements m on m.item_id = cr.item_id
  group by cr.item_id, cr.item_name, cr.rate_per_kg
  order by cr.item_id;
end $$;

/* ---------- paid pickups (lead code and area only) ---------- */
create or replace function public.wh_pickups(p_from date, p_to date, p_load_id integer default null)
returns table (bill_id integer, bill_no text, lead_code text, area text, load_id integer, load_code text,
               driver_name text, paid_at timestamptz, payment_method text, total_kg numeric, total_amount numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if not is_wh_staff() then raise exception 'Not allowed.'; end if;
  return query
  select b.id, b.bill_no, ld.code, cu.area, b.load_id, lo.code, pr.full_name, b.paid_at, b.payment_method,
         bt.total_kg, bt.total_amount
  from bills b
  join bill_totals bt on bt.bill_id = b.id
  join leads ld on ld.id = b.lead_id
  join customers cu on cu.id = ld.customer_id
  join loads lo on lo.id = b.load_id
  join profiles pr on pr.id = lo.driver_id
  where b.status = 'paid'
    and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    and (p_load_id is null or b.load_id = p_load_id)
  order by b.paid_at desc;
end $$;

/* ---------- every cash and UPI movement per driver (lead code and area only) ---------- */
create or replace function public.wh_transactions(p_from date, p_to date, p_driver uuid default null, p_limit integer default 200)
returns table (txn_at timestamptz, driver_id uuid, driver_name text, kind text, cash_effect numeric, amount numeric,
               bill_no text, lead_code text, area text, ref text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if not is_wh_staff() then raise exception 'Not allowed.'; end if;
  return query
  select * from (
    select c.created_at, c.driver_id, pr.full_name, c.entry_type, c.amount, abs(c.amount),
           b.bill_no, ld.code, cu.area, c.note
    from cash_ledger c
    join profiles pr on pr.id = c.driver_id
    left join bills b on b.id = c.bill_id
    left join leads ld on ld.id = b.lead_id
    left join customers cu on cu.id = ld.customer_id
    where (c.created_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    union all
    select b.paid_at, lo.driver_id, pr.full_name, 'upi_payout', 0::numeric, bt.total_amount,
           b.bill_no, ld.code, cu.area, b.upi_ref
    from bills b
    join bill_totals bt on bt.bill_id = b.id
    join loads lo on lo.id = b.load_id
    join profiles pr on pr.id = lo.driver_id
    join leads ld on ld.id = b.lead_id
    join customers cu on cu.id = ld.customer_id
    where b.status = 'paid' and b.payment_method = 'upi'
      and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to
  ) t(txn_at, driver_id, driver_name, kind, cash_effect, amount, bill_no, lead_code, area, ref)
  where (p_driver is null or t.driver_id = p_driver)
  order by t.txn_at desc
  limit greatest(least(p_limit, 1000), 1);
end $$;

/* ---------- daily route settlement: float, cash paid, expected balance, count, verification ---------- */
create or replace function public.wh_route_cash(p_from date, p_to date, p_driver uuid default null)
returns table (load_id integer, load_code text, driver_id uuid, driver_name text, route_date date, route_status text,
               float_issued numeric, cash_paid numeric, upi_paid numeric, expected_cash numeric, counted_cash numeric,
               difference numeric, settlement_id integer, counted_by_name text, counted_at timestamptz, count_note text,
               verified_by_name text, verified_at timestamptz, verify_note text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if not is_wh_staff() then raise exception 'Not allowed.'; end if;
  return query
  select l.id, l.code, l.driver_id, p.full_name,
         (l.started_at at time zone 'Asia/Kolkata')::date,
         case when s.id is not null then s.status when l.status = 'open' then 'on_route' else 'awaiting_count' end,
         coalesce((select sum(c.amount) from cash_ledger c where c.driver_id = l.driver_id and c.entry_type = 'float_issued'
                   and (c.created_at at time zone 'Asia/Kolkata')::date = (l.started_at at time zone 'Asia/Kolkata')::date), 0),
         coalesce(s.cash_paid, (select sum(bi.amount) from bills b join bill_items bi on bi.bill_id = b.id
                                where b.load_id = l.id and b.status = 'paid' and b.payment_method = 'cash'), 0),
         coalesce(s.upi_paid, (select sum(bi.amount) from bills b join bill_items bi on bi.bill_id = b.id
                               where b.load_id = l.id and b.status = 'paid' and b.payment_method = 'upi'), 0),
         coalesce(s.expected_cash, (select greatest(coalesce(sum(c.amount), 0), 0) from cash_ledger c
                                    where c.driver_id = l.driver_id and c.created_at <= coalesce(l.submitted_at, now()))),
         s.counted_cash, s.difference, s.id, cb.full_name, s.counted_at, s.count_note, vb.full_name, s.verified_at, s.verify_note
  from loads l
  join profiles p on p.id = l.driver_id
  left join cash_settlements s on s.load_id = l.id
  left join profiles cb on cb.id = s.counted_by
  left join profiles vb on vb.id = s.verified_by
  where (l.started_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    and (p_driver is null or l.driver_id = p_driver)
  order by l.started_at desc;
end $$;

/* ---------- permissions ---------- */
revoke all on public.wh_stock_movements, public.hq_requirement_progress from anon;
grant select on public.wh_stock_movements, public.hq_requirement_progress to authenticated;
revoke all on function public.wh_stock_report(date, date) from public, anon;
revoke all on function public.wh_pickups(date, date, integer) from public, anon;
revoke all on function public.wh_transactions(date, date, uuid, integer) from public, anon;
revoke all on function public.wh_route_cash(date, date, uuid) from public, anon;
grant execute on function public.wh_stock_report(date, date) to authenticated;
grant execute on function public.wh_pickups(date, date, integer) to authenticated;
grant execute on function public.wh_transactions(date, date, uuid, integer) to authenticated;
grant execute on function public.wh_route_cash(date, date, uuid) to authenticated;

/* ---------- live updates: the dashboard subscribes to these tables (row access still applies) ---------- */
alter publication supabase_realtime add table
  public.loads, public.bills, public.cash_ledger,
  public.load_weighings, public.hq_requirements, public.hq_releases, public.cash_settlements;
