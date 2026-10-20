/* =====================================================================
   WAREHOUSE BACKEND · STEP 6 · one cash count per driver, not per route
   Needs steps 1 to 4 (step 5 is the small security tidy-up, already applied).
   Why: a driver can run several routes on one float and hand cash back only
   at the end of the day. Counting route by route deadlocked.
   Nothing here drops or deletes anything.
   Rules after this step:
     - the driver must have no route on the road
     - the count is made on the driver's LATEST ended route
     - expected cash = the driver's full cash in hand (ledger balance)
     - the count covers every earlier ended route of that driver that has
       not been counted yet; those routes show as "Included in last count"
   ===================================================================== */

alter table public.cash_settlements
  add column if not exists covered_load_ids integer[] not null default '{}';

/* ended routes of a driver, up to and including p_upto, that no count has covered yet (internal helper) */
create or replace function public.wh_uncounted_loads(p_driver uuid, p_upto integer)
returns table (lid integer)
language sql stable security definer set search_path to 'public'
as $$
  select l.id from public.loads l
  where l.driver_id = p_driver and l.status <> 'open' and l.id <= p_upto
    and not exists (select 1 from public.cash_settlements s where s.load_id = l.id or l.id = any(s.covered_load_ids))
$$;
revoke all on function public.wh_uncounted_loads(uuid, integer) from public, anon, authenticated;

/* a counted settlement stays frozen, including which routes it covers */
create or replace function public.guard_settlements()
returns trigger language plpgsql set search_path to 'public'
as $$
begin
  if tg_op = 'DELETE' then raise exception 'Cash settlements cannot be deleted.'; end if;
  if old.status <> 'counted' then raise exception 'This settlement is final.'; end if;
  if (new.load_id, new.driver_id, new.expected_cash, new.counted_cash, new.cash_paid, new.upi_paid, new.counted_by, new.counted_at, new.count_note, new.covered_load_ids)
     is distinct from
     (old.load_id, old.driver_id, old.expected_cash, old.counted_cash, old.cash_paid, old.upi_paid, old.counted_by, old.counted_at, old.count_note, old.covered_load_ids)
  then raise exception 'Counted amounts cannot be changed.'; end if;
  return new;
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
  perform 1 from loads where driver_id = v_load.driver_id for update;      /* one count per driver at a time */
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

/* route list for the Finance screen. route_status is one of:
   on_route, driver_out (ended, but the driver has another route out), awaiting_count (ready to count),
   with_last (ended, will be counted with the driver's last route), included (covered by a count),
   counted, verified, disputed.   For an included route, settlement_id is the count that covers it. */
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
         s.counted_cash, s.difference, coalesce(s.id, cv.id), cb.full_name, s.counted_at, s.count_note, vb.full_name, s.verified_at, s.verify_note
  from loads l
  join profiles p on p.id = l.driver_id
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
  order by l.started_at desc;
end $$;

revoke all on function public.count_route_cash(integer, numeric, text) from public, anon;
revoke all on function public.wh_route_cash(date, date, uuid) from public, anon;
grant execute on function public.count_route_cash(integer, numeric, text) to authenticated;
grant execute on function public.wh_route_cash(date, date, uuid) to authenticated;

revoke all on function public.guard_settlements() from public, anon, authenticated;
