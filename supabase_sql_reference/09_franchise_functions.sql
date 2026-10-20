/* =====================================================================
   FRANCHISE STEP 9 · warehouse, supervisor and HQ actions respect franchises
   Needs step 8. Replaces the functions from steps 3, 4 and 6.
   - warehouse and supervisor staff can only act on their own franchise
   - stock is kept per franchise
   - reports take an optional franchise (HQ only: null = all franchises)
   The old versions of the changed reports are removed (they had no franchise).
   ===================================================================== */

/* ---------- stock, per franchise (null franchise = all). Internal only ---------- */
drop function if exists public.wh_stock_kg(integer);
create or replace function public.wh_stock_kg(p_item_id integer, p_franchise integer)
returns numeric language sql stable security definer set search_path to 'public'
as $$
  select coalesce((select sum(w.warehouse_kg) from public.load_weighings w join public.loads l on l.id = w.load_id
                   where w.item_id = p_item_id and w.superseded_at is null and l.status in ('reconciled','flagged')
                     and (p_franchise is null or w.franchise_id = p_franchise)), 0)
       - coalesce((select sum(kg) from public.hq_releases where item_id = p_item_id and (p_franchise is null or franchise_id = p_franchise)), 0)
$$;
revoke all on function public.wh_stock_kg(integer, integer) from public, anon, authenticated;

/* releases: one at a time per material AND franchise, never more than the stock of that franchise */
create or replace function public.guard_release_stock()
returns trigger language plpgsql security definer set search_path to 'public'
as $$
declare v_item integer; v_status text; v_req numeric; v_done numeric; v_stock numeric;
begin
  perform pg_advisory_xact_lock(new.item_id, new.franchise_id);
  select item_id, status, required_kg into v_item, v_status, v_req from public.hq_requirements where id = new.requirement_id;
  if v_item is null then raise exception 'Requirement not found.'; end if;
  if v_item <> new.item_id then raise exception 'This release is for a different material than the request.'; end if;
  if v_status <> 'open' then raise exception 'This request has been cancelled.'; end if;
  select coalesce(sum(kg), 0) into v_done from public.hq_releases where requirement_id = new.requirement_id;
  if new.kg > (v_req - v_done) + 0.0001 then
    raise exception 'HQ only needs % kg more for this request.', round(v_req - v_done, 1);
  end if;
  v_stock := public.wh_stock_kg(new.item_id, new.franchise_id);
  if new.kg > v_stock + 0.0001 then
    raise exception 'Not enough stock. In the yard: % kg.', round(v_stock, 1);
  end if;
  return new;
end $$;
revoke all on function public.guard_release_stock() from public, anon, authenticated;

/* ---------- weighing ---------- */
create or replace function public.record_load_weighing(p_load_id integer, p_weights jsonb, p_note text default null)
returns jsonb
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_load loads; r record; v_tol numeric := public.wh_tolerance_pct();
  v_all_ok boolean := true; v_ok boolean; v_tb numeric := 0; v_tw numeric := 0;
  v_out jsonb := '[]'::jsonb; v_missing text; v_status text;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can record weighing.'; end if;
  if jsonb_typeof(p_weights) is distinct from 'array' or jsonb_array_length(p_weights) = 0 then
    raise exception 'Send the weight of each material as a list.';
  end if;

  select * into v_load from loads where id = p_load_id for update;
  if v_load.id is null then raise exception 'Load not found.'; end if;
  if not public.fr_ok(v_load.franchise_id) then raise exception 'This load belongs to another franchise.'; end if;
  if v_load.status <> 'submitted' then
    raise exception 'This load is not waiting for weighing (status: %).', v_load.status;
  end if;

  if (select count(*) from jsonb_array_elements(p_weights) x(j) join scrap_items i on i.id = (x.j->>'item_id')::int)
     <> jsonb_array_length(p_weights) then
    raise exception 'Unknown material in the list.';
  end if;
  if (select count(distinct (x.j->>'item_id')) from jsonb_array_elements(p_weights) x(j)) <> jsonb_array_length(p_weights) then
    raise exception 'Each material can be entered only once.';
  end if;

  select string_agg(i.name, ', ') into v_missing
  from (select bi.item_id from bills b join bill_items bi on bi.bill_id = b.id
        where b.load_id = p_load_id and b.status = 'paid' group by bi.item_id) bl
  join scrap_items i on i.id = bl.item_id
  where not exists (select 1 from jsonb_array_elements(p_weights) x(j) where (x.j->>'item_id')::int = bl.item_id);
  if v_missing is not null then raise exception 'Enter the weight for: %.', v_missing; end if;

  update load_weighings set superseded_at = now() where load_id = p_load_id and superseded_at is null;

  for r in
    select i.id as item_id, i.name, coalesce(bl.kg, 0) as billed, (x.j->>'kg')::numeric as w
    from jsonb_array_elements(p_weights) x(j)
    join scrap_items i on i.id = (x.j->>'item_id')::int
    left join (select bi.item_id, sum(bi.qty_kg) as kg from bills b join bill_items bi on bi.bill_id = b.id
               where b.load_id = p_load_id and b.status = 'paid' group by bi.item_id) bl on bl.item_id = i.id
    order by i.id
  loop
    if r.w is null or r.w < 0 or r.w > 100000 then
      raise exception 'The weight of % must be between 0 and 100000 kg.', r.name;
    end if;
    v_ok := case when r.billed > 0 then abs(r.w - r.billed) / r.billed <= v_tol / 100 else r.w = 0 end;
    v_all_ok := v_all_ok and v_ok;
    insert into load_weighings (load_id, item_id, billed_kg, warehouse_kg, within_tolerance, weighed_by)
    values (p_load_id, r.item_id, r.billed, r.w, v_ok, auth.uid());
    v_tb := v_tb + r.billed; v_tw := v_tw + r.w;
    v_out := v_out || jsonb_build_object('item', r.name, 'billed_kg', r.billed, 'warehouse_kg', r.w,
               'diff_pct', case when r.billed > 0 then round((r.w - r.billed) / r.billed * 100, 2) end, 'ok', v_ok);
  end loop;

  v_status := case when v_all_ok then 'reconciled' else 'flagged' end;
  update loads set warehouse_kg = v_tw, status = v_status, checked_by = auth.uid(),
         weighed_at = now(), weighing_note = p_note
  where id = p_load_id;

  return jsonb_build_object('status', v_status, 'billed_kg', v_tb, 'warehouse_kg', v_tw, 'tolerance_pct', v_tol, 'items', v_out);
end $$;

create or replace function public.resolve_flagged_load(p_load_id integer, p_action text, p_note text)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_load loads; r record;
begin
  if my_role() <> 'hq' then raise exception 'Only HQ can resolve a flagged load.'; end if;
  if p_action not in ('accept','reweigh') then raise exception 'Action must be accept or reweigh.'; end if;
  if p_note is null or length(btrim(p_note)) = 0 then raise exception 'Add a note explaining the decision.'; end if;
  select * into v_load from loads where id = p_load_id for update;
  if v_load.id is null or v_load.status <> 'flagged' then raise exception 'This load is not flagged.'; end if;

  if p_action = 'accept' then
    update loads set status = 'reconciled', resolved_by = auth.uid(), resolved_at = now(), resolution_note = p_note where id = p_load_id;
    return 'reconciled';
  end if;

  for r in select item_id, warehouse_kg from load_weighings where load_id = p_load_id and superseded_at is null loop
    perform pg_advisory_xact_lock(r.item_id, v_load.franchise_id);
    if public.wh_stock_kg(r.item_id, v_load.franchise_id) - r.warehouse_kg < 0 then
      raise exception 'Cannot re-weigh: stock from this load has already been released to HQ.';
    end if;
  end loop;
  update load_weighings set superseded_at = now() where load_id = p_load_id and superseded_at is null;
  update loads set status = 'submitted', warehouse_kg = null, checked_by = null, weighed_at = null,
         resolved_by = auth.uid(), resolved_at = now(), resolution_note = p_note where id = p_load_id;
  return 'submitted';
end $$;

/* ---------- HQ requirements: raised by HQ for one franchise ---------- */
drop function if exists public.raise_requirement(integer, numeric, date, text);
create or replace function public.raise_requirement(p_item_id integer, p_required_kg numeric, p_due_date date default null, p_note text default null, p_franchise integer default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_code text;
begin
  if my_role() <> 'hq' then raise exception 'Only HQ can raise a requirement.'; end if;
  if p_franchise is null then raise exception 'Choose the franchise this request is for.'; end if;
  if not exists (select 1 from franchises where id = p_franchise and active) then raise exception 'That franchise is not active.'; end if;
  if p_required_kg is null or p_required_kg <= 0 then raise exception 'Enter the kg HQ needs.'; end if;
  insert into hq_requirements (item_id, required_kg, due_date, note, raised_by, franchise_id)
  values (p_item_id, p_required_kg, p_due_date, p_note, auth.uid(), p_franchise) returning code into v_code;
  return v_code;
end $$;

create or replace function public.release_to_hq(p_requirement_id integer, p_kg numeric, p_vehicle_no text, p_note text default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_item integer; v_f integer; v_code text;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can release stock.'; end if;
  select item_id, franchise_id into v_item, v_f from hq_requirements where id = p_requirement_id;
  if v_item is null then raise exception 'Requirement not found.'; end if;
  if not public.fr_ok(v_f) then raise exception 'This request belongs to another franchise.'; end if;
  insert into hq_releases (requirement_id, item_id, kg, vehicle_no, note, released_by)
  values (p_requirement_id, v_item, p_kg, coalesce(p_vehicle_no, ''), p_note, auth.uid()) returning code into v_code;
  return v_code;
end $$;

/* ---------- cash ---------- */
create or replace function public.issue_float(p_driver_id uuid, p_amount numeric, p_note text default null)
returns numeric
language plpgsql security definer set search_path to 'public'
as $$
declare v_bal numeric; v_f integer;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can issue float.'; end if;
  if p_amount is null or p_amount <= 0 or p_amount > 500000 then raise exception 'Enter an amount between 1 and 500000.'; end if;
  select franchise_id into v_f from profiles where id = p_driver_id and role = 'driver' and active;
  if v_f is null then raise exception 'That is not an active driver.'; end if;
  if not public.fr_ok(v_f) then raise exception 'This driver belongs to another franchise.'; end if;
  insert into cash_ledger (driver_id, entry_type, amount, note, created_by)
  values (p_driver_id, 'float_issued', p_amount, coalesce(p_note, 'Float issued at warehouse'), auth.uid());
  select coalesce(sum(amount), 0) into v_bal from cash_ledger where driver_id = p_driver_id;
  return v_bal;
end $$;

create or replace function public.count_route_cash(p_load_id integer, p_counted numeric, p_note text default null)
returns jsonb
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_load loads; v_exp numeric; v_cash numeric; v_upi numeric; v_id integer;
  v_cov integer[]; v_last_id integer; v_last_code text; v_codes text;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can count cash.'; end if;
  if p_counted is null or p_counted < 0 or p_counted > 1000000 then raise exception 'Enter the cash you counted.'; end if;
  select * into v_load from loads where id = p_load_id;
  if v_load.id is null then raise exception 'Load not found.'; end if;
  if not public.fr_ok(v_load.franchise_id) then raise exception 'This route belongs to another franchise.'; end if;
  perform 1 from loads where driver_id = v_load.driver_id for update;
  select * into v_load from loads where id = p_load_id;

  if v_load.status = 'open' then raise exception 'The driver has not ended this route yet.'; end if;
  if exists (select 1 from cash_settlements s where s.load_id = p_load_id or p_load_id = any(s.covered_load_ids)) then
    raise exception 'Cash for this route was already counted.';
  end if;
  if exists (select 1 from loads where driver_id = v_load.driver_id and status = 'open') then
    raise exception 'This driver still has a route on the road. Count the cash when the driver is back.';
  end if;
  select id, code into v_last_id, v_last_code from loads
   where driver_id = v_load.driver_id and status <> 'open' order by id desc limit 1;
  if v_last_id <> p_load_id then
    raise exception 'Count from the driver''s latest route (%). One count covers all of this driver''s routes.', v_last_code;
  end if;

  select coalesce(array_agg(x.lid order by x.lid) filter (where x.lid <> p_load_id), '{}') into v_cov
  from public.wh_uncounted_loads(v_load.driver_id, p_load_id) x;

  select greatest(coalesce(sum(amount), 0), 0) into v_exp from cash_ledger where driver_id = v_load.driver_id;
  if p_counted <> v_exp and (p_note is null or length(btrim(p_note)) = 0) then
    raise exception 'The count differs from the expected ₹%. Add a note.', v_exp;
  end if;

  select coalesce(sum(bi.amount) filter (where b.payment_method = 'cash'), 0),
         coalesce(sum(bi.amount) filter (where b.payment_method = 'upi'), 0)
    into v_cash, v_upi
  from bills b join bill_items bi on bi.bill_id = b.id
  where b.status = 'paid' and (b.load_id = p_load_id or b.load_id = any(v_cov));

  insert into cash_settlements (load_id, driver_id, expected_cash, counted_cash, cash_paid, upi_paid, counted_by, count_note, covered_load_ids)
  values (p_load_id, v_load.driver_id, v_exp, p_counted, v_cash, v_upi, auth.uid(), p_note, v_cov) returning id into v_id;

  select string_agg(code, ', ' order by id) into v_codes from loads where id = p_load_id or id = any(v_cov);
  if v_exp > 0 then
    insert into cash_ledger (driver_id, entry_type, amount, note, created_by)
    values (v_load.driver_id, 'handover', -v_exp,
            'Routes ' || v_codes || ': counted ₹' || p_counted || ', expected ₹' || v_exp, auth.uid());
  end if;
  return jsonb_build_object('settlement_id', v_id, 'expected', v_exp, 'counted', p_counted, 'difference', p_counted - v_exp,
                            'status', 'counted', 'routes', v_codes);
end $$;

create or replace function public.verify_settlement(p_settlement_id integer, p_decision text, p_note text default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare s cash_settlements;
begin
  if my_role() not in ('supervisor','hq') then raise exception 'Only a supervisor can verify cash.'; end if;
  if p_decision not in ('verify','dispute') then raise exception 'Decision must be verify or dispute.'; end if;
  select * into s from cash_settlements where id = p_settlement_id for update;
  if s.id is null then raise exception 'Settlement not found.'; end if;
  if not public.fr_ok(s.franchise_id) then raise exception 'This settlement belongs to another franchise.'; end if;
  if s.status <> 'counted' then raise exception 'This settlement is already %.', s.status; end if;
  if s.counted_by = auth.uid() then raise exception 'The person who counted the cash cannot verify it.'; end if;
  if (s.difference <> 0 or p_decision = 'dispute') and (p_note is null or length(btrim(p_note)) = 0) then
    raise exception 'Add a note explaining the difference or the dispute.';
  end if;
  update cash_settlements
     set status = case p_decision when 'verify' then 'verified' else 'disputed' end,
         verified_by = auth.uid(), verified_at = now(), verify_note = p_note
   where id = p_settlement_id;
  return case p_decision when 'verify' then 'verified' else 'disputed' end;
end $$;

/* ---------- reports: franchise staff see their franchise, HQ may pick one (null = all) ---------- */
drop function if exists public.wh_stock_report(date, date);
create or replace function public.wh_stock_report(p_from date, p_to date, p_franchise integer default null)
returns table (item_id integer, item_name text, rate_per_kg numeric, opening_kg numeric, received_kg numeric,
               released_kg numeric, closing_kg numeric, closing_value numeric, hq_open_need_kg numeric, stock_now_kg numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_f integer := public.fr_scope(p_franchise);
begin
  return query
  select cr.item_id, cr.item_name, cr.rate_per_kg,
         coalesce(sum(case when m.day < p_from then (case m.kind when 'received' then m.kg else -m.kg end) end), 0),
         coalesce(sum(case when m.day between p_from and p_to and m.kind = 'received' then m.kg end), 0),
         coalesce(sum(case when m.day between p_from and p_to and m.kind = 'released' then m.kg end), 0),
         coalesce(sum(case when m.day <= p_to then (case m.kind when 'received' then m.kg else -m.kg end) end), 0),
         coalesce(sum(case when m.day <= p_to then (case m.kind when 'received' then m.kg else -m.kg end) end), 0) * cr.rate_per_kg,
         (select coalesce(sum(q.remaining_kg), 0) from hq_requirement_progress q where q.item_id = cr.item_id and q.status in ('open','partial') and (v_f is null or q.franchise_id = v_f)),
         public.wh_stock_kg(cr.item_id, v_f)
  from current_rates cr
  left join wh_stock_movements m on m.item_id = cr.item_id and (v_f is null or m.franchise_id = v_f)
  group by cr.item_id, cr.item_name, cr.rate_per_kg
  order by cr.item_id;
end $$;

drop function if exists public.wh_pickups(date, date, integer);
create or replace function public.wh_pickups(p_from date, p_to date, p_load_id integer default null, p_franchise integer default null)
returns table (bill_id integer, bill_no text, lead_code text, area text, load_id integer, load_code text,
               driver_name text, paid_at timestamptz, payment_method text, total_kg numeric, total_amount numeric, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_f integer := public.fr_scope(p_franchise);
begin
  return query
  select b.id, b.bill_no, ld.code, cu.area, b.load_id, lo.code, pr.full_name, b.paid_at, b.payment_method,
         bt.total_kg, bt.total_amount, fr.code
  from bills b
  join bill_totals bt on bt.bill_id = b.id
  join leads ld on ld.id = b.lead_id
  join customers cu on cu.id = ld.customer_id
  join loads lo on lo.id = b.load_id
  join profiles pr on pr.id = lo.driver_id
  join franchises fr on fr.id = lo.franchise_id
  where b.status = 'paid'
    and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    and (p_load_id is null or b.load_id = p_load_id)
    and (v_f is null or lo.franchise_id = v_f)
  order by b.paid_at desc;
end $$;

drop function if exists public.wh_transactions(date, date, uuid, integer);
create or replace function public.wh_transactions(p_from date, p_to date, p_driver uuid default null, p_limit integer default 200, p_franchise integer default null)
returns table (txn_at timestamptz, driver_id uuid, driver_name text, kind text, cash_effect numeric, amount numeric,
               bill_no text, lead_code text, area text, ref text, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_f integer := public.fr_scope(p_franchise);
begin
  return query
  select * from (
    select c.created_at, c.driver_id, pr.full_name, c.entry_type, c.amount, abs(c.amount),
           b.bill_no, ld.code, cu.area, c.note, fr.code
    from cash_ledger c
    join profiles pr on pr.id = c.driver_id
    join franchises fr on fr.id = c.franchise_id
    left join bills b on b.id = c.bill_id
    left join leads ld on ld.id = b.lead_id
    left join customers cu on cu.id = ld.customer_id
    where (c.created_at at time zone 'Asia/Kolkata')::date between p_from and p_to
      and (v_f is null or c.franchise_id = v_f)
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
      and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to
      and (v_f is null or lo.franchise_id = v_f)
  ) t(txn_at, driver_id, driver_name, kind, cash_effect, amount, bill_no, lead_code, area, ref, franchise_code)
  where (p_driver is null or t.driver_id = p_driver)
  order by t.txn_at desc
  limit greatest(least(p_limit, 1000), 1);
end $$;

drop function if exists public.wh_route_cash(date, date, uuid);
create or replace function public.wh_route_cash(p_from date, p_to date, p_driver uuid default null, p_franchise integer default null)
returns table (load_id integer, load_code text, driver_id uuid, driver_name text, route_date date, route_status text,
               float_issued numeric, cash_paid numeric, upi_paid numeric, expected_cash numeric, counted_cash numeric,
               difference numeric, settlement_id integer, counted_by_name text, counted_at timestamptz, count_note text,
               verified_by_name text, verified_at timestamptz, verify_note text, franchise_id integer, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_f integer := public.fr_scope(p_franchise);
begin
  return query
  select l.id, l.code, l.driver_id, p.full_name,
         (l.started_at at time zone 'Asia/Kolkata')::date,
         z.st,
         coalesce((select sum(c.amount) from cash_ledger c where c.driver_id = l.driver_id and c.entry_type = 'float_issued'
                   and (c.created_at at time zone 'Asia/Kolkata')::date = (l.started_at at time zone 'Asia/Kolkata')::date), 0),
         coalesce(s.cash_paid, (select coalesce(sum(bi.amount), 0) from bills b join bill_items bi on bi.bill_id = b.id
                                where b.status = 'paid' and b.payment_method = 'cash'
                                  and (b.load_id = l.id or (z.st = 'awaiting_count' and b.load_id in (select u.lid from public.wh_uncounted_loads(l.driver_id, l.id) u))))),
         coalesce(s.upi_paid, (select coalesce(sum(bi.amount), 0) from bills b join bill_items bi on bi.bill_id = b.id
                               where b.status = 'paid' and b.payment_method = 'upi'
                                 and (b.load_id = l.id or (z.st = 'awaiting_count' and b.load_id in (select u.lid from public.wh_uncounted_loads(l.driver_id, l.id) u))))),
         coalesce(s.expected_cash, case when z.st = 'awaiting_count'
                    then (select greatest(coalesce(sum(c.amount), 0), 0) from cash_ledger c where c.driver_id = l.driver_id) end),
         s.counted_cash, s.difference, coalesce(s.id, cv.id), cb.full_name, s.counted_at, s.count_note, vb.full_name, s.verified_at, s.verify_note,
         l.franchise_id, fr.code
  from loads l
  join profiles p on p.id = l.driver_id
  join franchises fr on fr.id = l.franchise_id
  left join cash_settlements s on s.load_id = l.id
  left join cash_settlements cv on l.id = any(cv.covered_load_ids)
  left join profiles cb on cb.id = s.counted_by
  left join profiles vb on vb.id = s.verified_by
  cross join lateral (select case
      when s.id is not null then s.status
      when cv.id is not null then 'included'
      when l.status = 'open' then 'on_route'
      when exists (select 1 from loads o where o.driver_id = l.driver_id and o.status = 'open') then 'driver_out'
      when l.id = (select max(x.id) from loads x where x.driver_id = l.driver_id and x.status <> 'open') then 'awaiting_count'
      else 'with_last' end as st) z
  where (l.started_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    and (p_driver is null or l.driver_id = p_driver)
    and (v_f is null or l.franchise_id = v_f)
  order by l.started_at desc;
end $$;

/* ---------- who may call what ---------- */
revoke all on function public.record_load_weighing(integer, jsonb, text) from public, anon;
revoke all on function public.resolve_flagged_load(integer, text, text) from public, anon;
revoke all on function public.raise_requirement(integer, numeric, date, text, integer) from public, anon;
revoke all on function public.release_to_hq(integer, numeric, text, text) from public, anon;
revoke all on function public.issue_float(uuid, numeric, text) from public, anon;
revoke all on function public.count_route_cash(integer, numeric, text) from public, anon;
revoke all on function public.verify_settlement(integer, text, text) from public, anon;
revoke all on function public.wh_stock_report(date, date, integer) from public, anon;
revoke all on function public.wh_pickups(date, date, integer, integer) from public, anon;
revoke all on function public.wh_transactions(date, date, uuid, integer, integer) from public, anon;
revoke all on function public.wh_route_cash(date, date, uuid, integer) from public, anon;
grant execute on function public.record_load_weighing(integer, jsonb, text) to authenticated;
grant execute on function public.resolve_flagged_load(integer, text, text) to authenticated;
grant execute on function public.raise_requirement(integer, numeric, date, text, integer) to authenticated;
grant execute on function public.release_to_hq(integer, numeric, text, text) to authenticated;
grant execute on function public.issue_float(uuid, numeric, text) to authenticated;
grant execute on function public.count_route_cash(integer, numeric, text) to authenticated;
grant execute on function public.verify_settlement(integer, text, text) to authenticated;
grant execute on function public.wh_stock_report(date, date, integer) to authenticated;
grant execute on function public.wh_pickups(date, date, integer, integer) to authenticated;
grant execute on function public.wh_transactions(date, date, uuid, integer, integer) to authenticated;
grant execute on function public.wh_route_cash(date, date, uuid, integer) to authenticated;
