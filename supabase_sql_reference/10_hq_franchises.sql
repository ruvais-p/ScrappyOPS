/* =====================================================================
   FRANCHISE STEP 10 · HQ: pick a franchise (or all), manage franchises and people
   Needs steps 8 and 9. Replaces the HQ reports from step 7 with franchise-aware versions
   (the old versions are removed). All functions check that the caller is HQ.
   ===================================================================== */

drop function if exists public.hq_log(text, text, jsonb);
create or replace function public.hq_log(p_action text, p_ref text, p_detail jsonb, p_franchise integer default null)
returns void language sql security definer set search_path to 'public'
as $$ insert into public.hq_audit (by_id, action, ref, detail, franchise_id) values (auth.uid(), p_action, p_ref, p_detail, p_franchise) $$;
revoke all on function public.hq_log(text, text, jsonb, integer) from public, anon, authenticated;

/* ---------- summary for the selected franchise (null = all) ---------- */
drop function if exists public.hq_overview(date, date);
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
    'counts_waiting',    (select count(*) from wh_route_cash(date '2026-01-01', v_today + 1, null, f) where route_status = 'awaiting_count'),
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

drop function if exists public.hq_daily(date, date);
create or replace function public.hq_daily(p_from date, p_to date, p_franchise integer default null)
returns table (day date, pickups bigint, kg numeric, amount numeric, cash_amount numeric, upi_amount numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select d.dd::date, count(pb.bill_id), coalesce(sum(pb.total_kg), 0), coalesce(sum(pb.total_amount), 0),
         coalesce(sum(pb.total_amount) filter (where pb.payment_method = 'cash'), 0),
         coalesce(sum(pb.total_amount) filter (where pb.payment_method = 'upi'), 0)
  from generate_series(p_from, least(p_to, p_from + 400), interval '1 day') d(dd)
  left join hq_paid_bills pb on pb.paid_day = d.dd::date and (p_franchise is null or pb.franchise_id = p_franchise)
  group by d.dd order by d.dd;
end $$;

drop function if exists public.hq_item_summary(date, date);
create or replace function public.hq_item_summary(p_from date, p_to date, p_franchise integer default null)
returns table (item_id integer, item_name text, kg numeric, amount numeric, pickups bigint, avg_rate numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select i.id, i.name, coalesce(sum(bi.qty_kg), 0), coalesce(sum(bi.amount), 0), count(distinct bi.bill_id),
         case when sum(bi.qty_kg) > 0 then round(sum(bi.amount) / sum(bi.qty_kg), 2) else 0 end
  from scrap_items i
  left join hq_paid_bills pb on pb.paid_day between p_from and p_to and (p_franchise is null or pb.franchise_id = p_franchise)
  left join bill_items bi on bi.bill_id = pb.bill_id and bi.item_id = i.id
  where i.active
  group by i.id, i.name
  order by i.id;
end $$;

drop function if exists public.hq_driver_scorecard(date, date);
create or replace function public.hq_driver_scorecard(p_from date, p_to date, p_franchise integer default null)
returns table (driver_id uuid, full_name text, active boolean, vehicle_no text, territory text, leads_assigned bigint,
               pickups bigint, kg numeric, amount numeric, avg_minutes numeric, weighed_billed_kg numeric, weighed_kg numeric,
               variance_pct numeric, loads_off_tolerance bigint, cash_in_hand numeric, cash_short numeric, disputes bigint, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select p.id, p.full_name, p.active, p.vehicle_no, p.territory,
    (select count(*) from leads l where l.driver_id = p.id and l.status <> 'cancelled' and (l.slot at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select count(*) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between p_from and p_to),
    (select coalesce(sum(pb.total_kg), 0) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between p_from and p_to),
    (select coalesce(sum(pb.total_amount), 0) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between p_from and p_to),
    (select round((avg(extract(epoch from (pb.paid_at - pb.created_at)) / 60))::numeric, 1) from hq_paid_bills pb where pb.driver_id = p.id and pb.paid_day between p_from and p_to),
    (select coalesce(sum(w.billed_kg), 0) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(w.warehouse_kg), 0) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select count(distinct w.load_id) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and not w.within_tolerance and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id),
    (select coalesce(sum(-s.difference), 0) from cash_settlements s where s.driver_id = p.id and s.difference < 0 and (s.counted_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select count(*) from cash_settlements s where s.driver_id = p.id and s.status = 'disputed' and (s.counted_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    fr.code
  from profiles p join franchises fr on fr.id = p.franchise_id
  where p.role = 'driver' and (p_franchise is null or p.franchise_id = p_franchise)
  order by p.active desc, fr.code, p.full_name;
end $$;

drop function if exists public.hq_bills(date, date, text, uuid, text, integer);
create or replace function public.hq_bills(p_from date, p_to date, p_status text default null, p_driver uuid default null,
                                           p_search text default null, p_limit integer default 200, p_franchise integer default null)
returns table (bill_id integer, bill_no text, lead_code text, customer_name text, phone text, area text, driver_id uuid, driver_name text,
               load_code text, status text, payment_method text, upi_ref text, total_kg numeric, total_amount numeric,
               created_at timestamptz, sent_at timestamptz, whatsapp_opened_at timestamptz, confirmed_at timestamptz, paid_at timestamptz,
               confirm_proof_url text, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select b.id, b.bill_no, ld.code, cu.name, cu.phone, cu.area, lo.driver_id, pr.full_name, lo.code, b.status, b.payment_method, b.upi_ref,
         bt.total_kg, bt.total_amount, b.created_at, b.sent_at, b.whatsapp_opened_at, b.confirmed_at, b.paid_at, b.confirm_proof_url, fr.code
  from bills b
  join bill_totals bt on bt.bill_id = b.id
  join leads ld on ld.id = b.lead_id
  join customers cu on cu.id = ld.customer_id
  join loads lo on lo.id = b.load_id
  join profiles pr on pr.id = lo.driver_id
  join franchises fr on fr.id = lo.franchise_id
  where (b.created_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    and (p_franchise is null or lo.franchise_id = p_franchise)
    and (p_status is null or b.status = p_status)
    and (p_driver is null or lo.driver_id = p_driver)
    and (p_search is null or btrim(p_search) = '' or cu.name ilike '%' || btrim(p_search) || '%' or cu.phone ilike '%' || btrim(p_search) || '%'
         or b.bill_no ilike '%' || btrim(p_search) || '%' or ld.code ilike '%' || btrim(p_search) || '%' or coalesce(cu.area, '') ilike '%' || btrim(p_search) || '%')
  order by b.created_at desc
  limit greatest(least(p_limit, 500), 1);
end $$;

drop function if exists public.hq_leads(date, date, text, uuid, text, integer);
create or replace function public.hq_leads(p_from date, p_to date, p_status text default null, p_driver uuid default null,
                                           p_search text default null, p_limit integer default 300, p_franchise integer default null)
returns table (lead_id integer, code text, customer_name text, phone text, address text, area text, driver_id uuid, driver_name text,
               slot timestamptz, status text, items_said text, bill_no text, bill_status text, created_at timestamptz, closed_at timestamptz, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select l.id, l.code, cu.name, cu.phone, cu.address, cu.area, l.driver_id, pr.full_name, l.slot, l.status, l.items_said,
         b.bill_no, b.status, l.created_at, l.closed_at, fr.code
  from leads l
  join customers cu on cu.id = l.customer_id
  join profiles pr on pr.id = l.driver_id
  join franchises fr on fr.id = l.franchise_id
  left join bills b on b.lead_id = l.id
  where ((l.slot at time zone 'Asia/Kolkata')::date between p_from and p_to or (l.status in ('scheduled','in_progress') and p_status is not null))
    and (p_franchise is null or l.franchise_id = p_franchise)
    and (p_status is null or l.status = p_status)
    and (p_driver is null or l.driver_id = p_driver)
    and (p_search is null or btrim(p_search) = '' or cu.name ilike '%' || btrim(p_search) || '%' or cu.phone ilike '%' || btrim(p_search) || '%'
         or l.code ilike '%' || btrim(p_search) || '%' or coalesce(cu.area, '') ilike '%' || btrim(p_search) || '%')
  order by l.slot desc nulls last, l.id desc
  limit greatest(least(p_limit, 500), 1);
end $$;

drop function if exists public.hq_loads(date, date);
create or replace function public.hq_loads(p_from date, p_to date, p_franchise integer default null)
returns table (load_id integer, code text, driver_id uuid, driver_name text, vehicle_no text, status text, started_at timestamptz,
               submitted_at timestamptz, pickups bigint, billed_kg numeric, billed_amount numeric, weighed_kg numeric,
               variance_pct numeric, items_off bigint, resolution_note text, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select l.id, l.code, l.driver_id, p.full_name, l.vehicle_no, l.status, l.started_at, l.submitted_at,
         (select count(*) from bills b where b.load_id = l.id and b.status = 'paid'),
         (select coalesce(sum(bt.total_kg), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.load_id = l.id and b.status = 'paid'),
         (select coalesce(sum(bt.total_amount), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.load_id = l.id and b.status = 'paid'),
         (select sum(w.warehouse_kg) from load_weighings w where w.load_id = l.id and w.superseded_at is null),
         (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w where w.load_id = l.id and w.superseded_at is null),
         (select count(*) from load_weighings w where w.load_id = l.id and w.superseded_at is null and not w.within_tolerance),
         l.resolution_note, fr.code
  from loads l join profiles p on p.id = l.driver_id join franchises fr on fr.id = l.franchise_id
  where ((l.started_at at time zone 'Asia/Kolkata')::date between p_from and p_to or l.status in ('submitted','flagged'))
    and (p_franchise is null or l.franchise_id = p_franchise)
  order by l.id desc;
end $$;

drop function if exists public.hq_team();
create or replace function public.hq_team(p_franchise integer default null)
returns table (id uuid, full_name text, email text, role text, phone text, territory text, vehicle_no text, active boolean,
               cash_in_hand numeric, open_leads bigint, franchise_id integer, franchise_code text, franchise_name text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select p.id, p.full_name, u.email::text, p.role, p.phone, p.territory, p.vehicle_no, p.active,
         (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id),
         (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress')),
         p.franchise_id, fr.code, fr.name
  from profiles p left join auth.users u on u.id = p.id left join franchises fr on fr.id = p.franchise_id
  where p_franchise is null or p.franchise_id = p_franchise or p.role = 'hq'
  order by case p.role when 'hq' then 0 when 'supervisor' then 1 when 'warehouse' then 2 else 3 end, fr.code, p.full_name;
end $$;

/* ---------- one line per franchise ---------- */
create or replace function public.hq_franchises(p_from date, p_to date)
returns table (franchise_id integer, code text, name text, district text, constituency text, active boolean,
               drivers bigint, staff bigint, leads_today bigint, leads_late bigint, pickups bigint, kg numeric, amount numeric,
               stock_kg numeric, cash_in_hand numeric, loads_open bigint, loads_waiting bigint, loads_flagged bigint,
               disputes_open bigint, counts_unverified bigint, variance_pct numeric, last_activity timestamptz)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_today date := (now() at time zone 'Asia/Kolkata')::date;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select f.id, f.code, f.name, f.district, f.constituency, f.active,
    (select count(*) from profiles p where p.franchise_id = f.id and p.role = 'driver' and p.active),
    (select count(*) from profiles p where p.franchise_id = f.id and p.role <> 'driver' and p.active),
    (select count(*) from leads l where l.franchise_id = f.id and l.status in ('scheduled','in_progress') and (l.slot at time zone 'Asia/Kolkata')::date = v_today),
    (select count(*) from leads l where l.franchise_id = f.id and l.status = 'scheduled' and l.slot < now() - interval '3 hours'),
    (select count(*) from hq_paid_bills pb where pb.franchise_id = f.id and pb.paid_day between p_from and p_to),
    (select coalesce(sum(pb.total_kg), 0) from hq_paid_bills pb where pb.franchise_id = f.id and pb.paid_day between p_from and p_to),
    (select coalesce(sum(pb.total_amount), 0) from hq_paid_bills pb where pb.franchise_id = f.id and pb.paid_day between p_from and p_to),
    (select coalesce(sum(public.wh_stock_kg(i.id, f.id)), 0) from scrap_items i where i.active),
    (select coalesce(sum(c.amount), 0) from cash_ledger c where c.franchise_id = f.id),
    (select count(*) from loads l where l.franchise_id = f.id and l.status = 'open'),
    (select count(*) from loads l where l.franchise_id = f.id and l.status = 'submitted'),
    (select count(*) from loads l where l.franchise_id = f.id and l.status = 'flagged'),
    (select count(*) from cash_settlements s where s.franchise_id = f.id and s.status = 'disputed' and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)),
    (select count(*) from cash_settlements s where s.franchise_id = f.id and s.status = 'counted'),
    (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w where w.franchise_id = f.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    greatest((select max(l.started_at) from loads l where l.franchise_id = f.id), (select max(pb.paid_at) from hq_paid_bills pb where pb.franchise_id = f.id))
  from franchises f
  order by f.code;
end $$;

/* ---------- franchises: add and edit ---------- */
create or replace function public.hq_add_franchise(p_code text, p_name text, p_district text default null, p_constituency text default null)
returns integer language plpgsql security definer set search_path to 'public'
as $$
declare v_code text := upper(btrim(coalesce(p_code, ''))); v_id integer;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if v_code !~ '^[A-Z0-9][A-Z0-9-]{1,11}$' then raise exception 'The code must be 2 to 12 letters, numbers or dashes (for example KKD).'; end if;
  if p_name is null or length(btrim(p_name)) = 0 then raise exception 'Enter the franchise name.'; end if;
  if exists (select 1 from franchises where code = v_code) then raise exception 'The code % is already used by another franchise.', v_code; end if;
  insert into franchises (code, name, district, constituency)
  values (v_code, btrim(p_name), nullif(btrim(coalesce(p_district, '')), ''), nullif(btrim(coalesce(p_constituency, '')), '')) returning id into v_id;
  perform public.hq_log('franchise_added', v_code, jsonb_build_object('name', btrim(p_name)), v_id);
  return v_id;
end $$;

create or replace function public.hq_update_franchise(p_id integer, p_code text, p_name text, p_district text, p_constituency text, p_active boolean)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_old franchises; v_code text := upper(btrim(coalesce(p_code, '')));
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_old from franchises where id = p_id for update;
  if v_old.id is null then raise exception 'Franchise not found.'; end if;
  if v_code !~ '^[A-Z0-9][A-Z0-9-]{1,11}$' then raise exception 'The code must be 2 to 12 letters, numbers or dashes (for example KKD).'; end if;
  if p_name is null or length(btrim(p_name)) = 0 then raise exception 'Enter the franchise name.'; end if;
  if exists (select 1 from franchises where code = v_code and id <> p_id) then raise exception 'The code % is already used by another franchise.', v_code; end if;
  if v_old.active and not p_active then
    if exists (select 1 from loads where franchise_id = p_id and status = 'open') then raise exception 'A driver of this franchise is on the road. Switch it off after the route ends.'; end if;
    if exists (select 1 from leads where franchise_id = p_id and status in ('scheduled','in_progress')) then raise exception 'This franchise still has open leads. Cancel or reassign them first.'; end if;
  end if;
  update franchises set code = v_code, name = btrim(p_name), district = nullif(btrim(coalesce(p_district, '')), ''),
         constituency = nullif(btrim(coalesce(p_constituency, '')), ''), active = p_active where id = p_id;
  perform public.hq_log('franchise_updated', v_code, jsonb_build_object('was_active', v_old.active, 'now_active', p_active, 'old_code', v_old.code), p_id);
  return v_code;
end $$;

/* ---------- people: add a person who already has a login, and edit ---------- */
create or replace function public.hq_add_person(p_email text, p_full_name text, p_role text, p_franchise integer,
                                                p_phone text default null, p_territory text default null, p_vehicle_no text default null)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_id uuid;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if p_role not in ('driver','warehouse','supervisor') then raise exception 'Role must be driver, warehouse or supervisor.'; end if;
  if p_full_name is null or length(btrim(p_full_name)) = 0 then raise exception 'Enter the name.'; end if;
  if not exists (select 1 from franchises where id = p_franchise and active) then raise exception 'Choose an active franchise.'; end if;
  select id into v_id from auth.users where lower(email) = lower(btrim(coalesce(p_email, '')));
  if v_id is null then raise exception 'No login with this email yet. Create it first in Supabase: Authentication, Users, Add user (tick Auto Confirm User).'; end if;
  if exists (select 1 from profiles where id = v_id) then raise exception 'This login is already set up.'; end if;
  insert into profiles (id, full_name, role, franchise_id, phone, territory, vehicle_no, active)
  values (v_id, btrim(p_full_name), p_role, p_franchise, nullif(btrim(coalesce(p_phone, '')), ''), nullif(btrim(coalesce(p_territory, '')), ''), nullif(btrim(coalesce(p_vehicle_no, '')), ''), true);
  perform public.hq_log('person_added', btrim(p_full_name), jsonb_build_object('role', p_role, 'email', lower(btrim(p_email))), p_franchise);
  return btrim(p_full_name);
end $$;

drop function if exists public.hq_update_profile(uuid, text, text, text, text, boolean);
create or replace function public.hq_update_profile(p_id uuid, p_full_name text, p_phone text, p_territory text, p_vehicle_no text, p_active boolean, p_franchise integer default null)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_old profiles; v_new_f integer;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_old from profiles where id = p_id for update;
  if v_old.id is null then raise exception 'Person not found.'; end if;
  if p_full_name is null or length(btrim(p_full_name)) = 0 then raise exception 'Enter a name.'; end if;
  if p_id = auth.uid() and not p_active then raise exception 'You cannot deactivate your own login.'; end if;
  v_new_f := case when v_old.role = 'hq' then null else coalesce(p_franchise, v_old.franchise_id) end;
  if v_old.role <> 'hq' and not exists (select 1 from franchises where id = v_new_f and (active or v_new_f = v_old.franchise_id)) then raise exception 'Choose an active franchise.'; end if;
  if v_old.role = 'driver' and (v_old.active and not p_active or v_new_f is distinct from v_old.franchise_id) then
    if exists (select 1 from loads where driver_id = p_id and status = 'open') then raise exception 'This driver has a route on the road. Do this after the route ends.'; end if;
    if exists (select 1 from leads where driver_id = p_id and status in ('scheduled','in_progress')) then raise exception 'Reassign this driver''s open leads first.'; end if;
  end if;
  if v_old.role = 'driver' and v_new_f is distinct from v_old.franchise_id then
    if exists (select 1 from cash_ledger where driver_id = p_id group by driver_id having sum(amount) <> 0) then raise exception 'This driver still holds cash. Count it before moving the driver to another franchise.'; end if;
  end if;
  update profiles set full_name = btrim(p_full_name), phone = nullif(btrim(coalesce(p_phone, '')), ''), territory = nullif(btrim(coalesce(p_territory, '')), ''),
         vehicle_no = nullif(btrim(coalesce(p_vehicle_no, '')), ''), active = p_active, franchise_id = v_new_f where id = p_id;
  perform public.hq_log('profile_updated', v_old.full_name,
    jsonb_build_object('id', p_id, 'was_active', v_old.active, 'now_active', p_active, 'from_franchise', v_old.franchise_id, 'to_franchise', v_new_f), v_new_f);
  return btrim(p_full_name);
end $$;

/* ---------- lead actions ---------- */
create or replace function public.hq_reassign_lead(p_lead_id integer, p_driver_id uuid)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_lead leads; v_name text; v_nf integer;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_lead from leads where id = p_lead_id for update;
  if v_lead.id is null then raise exception 'Lead not found.'; end if;
  if v_lead.status <> 'scheduled' then raise exception 'Only a lead that has not been started can be reassigned (this one is %).', v_lead.status; end if;
  select full_name, franchise_id into v_name, v_nf from profiles where id = p_driver_id and role = 'driver' and active;
  if v_name is null then raise exception 'Choose an active driver.'; end if;
  if v_lead.driver_id = p_driver_id then raise exception 'This lead is already with %.', v_name; end if;
  update leads set driver_id = p_driver_id, franchise_id = v_nf where id = p_lead_id;
  perform public.hq_log('lead_reassigned', v_lead.code,
    jsonb_build_object('from', v_lead.driver_id, 'to', p_driver_id, 'from_franchise', v_lead.franchise_id, 'to_franchise', v_nf), v_nf);
  return v_name;
end $$;

create or replace function public.hq_cancel_lead(p_lead_id integer, p_reason text)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_lead leads;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if p_reason is null or length(btrim(p_reason)) = 0 then raise exception 'Add a reason for cancelling.'; end if;
  select * into v_lead from leads where id = p_lead_id for update;
  if v_lead.id is null then raise exception 'Lead not found.'; end if;
  if v_lead.status <> 'scheduled' then raise exception 'Only a lead that has not been started can be cancelled (this one is %).', v_lead.status; end if;
  update leads set status = 'cancelled' where id = p_lead_id;
  perform public.hq_log('lead_cancelled', v_lead.code, jsonb_build_object('reason', btrim(p_reason)), v_lead.franchise_id);
  return v_lead.code;
end $$;

create or replace function public.hq_resolve_dispute(p_settlement_id integer, p_decision text, p_note text)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare s cash_settlements;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if p_decision not in ('recover_from_driver','write_off','no_action') then raise exception 'Choose what happens to the shortage.'; end if;
  if p_note is null or length(btrim(p_note)) = 0 then raise exception 'Add a note explaining the decision.'; end if;
  select * into s from cash_settlements where id = p_settlement_id for update;
  if s.id is null or s.status <> 'disputed' then raise exception 'This settlement is not disputed.'; end if;
  if exists (select 1 from settlement_resolutions where settlement_id = p_settlement_id) then raise exception 'This dispute has already been resolved.'; end if;
  insert into settlement_resolutions (settlement_id, decision, note, resolved_by) values (p_settlement_id, p_decision, btrim(p_note), auth.uid());
  perform public.hq_log('dispute_resolved', 'settlement ' || p_settlement_id, jsonb_build_object('decision', p_decision, 'difference', s.difference), s.franchise_id);
  return p_decision;
end $$;

/* ---------- who may call what ---------- */
revoke all on function public.hq_overview(date, date, integer) from public, anon;
revoke all on function public.hq_daily(date, date, integer) from public, anon;
revoke all on function public.hq_item_summary(date, date, integer) from public, anon;
revoke all on function public.hq_driver_scorecard(date, date, integer) from public, anon;
revoke all on function public.hq_bills(date, date, text, uuid, text, integer, integer) from public, anon;
revoke all on function public.hq_leads(date, date, text, uuid, text, integer, integer) from public, anon;
revoke all on function public.hq_loads(date, date, integer) from public, anon;
revoke all on function public.hq_team(integer) from public, anon;
revoke all on function public.hq_franchises(date, date) from public, anon;
revoke all on function public.hq_add_franchise(text, text, text, text) from public, anon;
revoke all on function public.hq_update_franchise(integer, text, text, text, text, boolean) from public, anon;
revoke all on function public.hq_add_person(text, text, text, integer, text, text, text) from public, anon;
revoke all on function public.hq_update_profile(uuid, text, text, text, text, boolean, integer) from public, anon;
revoke all on function public.hq_reassign_lead(integer, uuid) from public, anon;
revoke all on function public.hq_cancel_lead(integer, text) from public, anon;
revoke all on function public.hq_resolve_dispute(integer, text, text) from public, anon;
grant execute on function public.hq_overview(date, date, integer) to authenticated;
grant execute on function public.hq_daily(date, date, integer) to authenticated;
grant execute on function public.hq_item_summary(date, date, integer) to authenticated;
grant execute on function public.hq_driver_scorecard(date, date, integer) to authenticated;
grant execute on function public.hq_bills(date, date, text, uuid, text, integer, integer) to authenticated;
grant execute on function public.hq_leads(date, date, text, uuid, text, integer, integer) to authenticated;
grant execute on function public.hq_loads(date, date, integer) to authenticated;
grant execute on function public.hq_team(integer) to authenticated;
grant execute on function public.hq_franchises(date, date) to authenticated;
grant execute on function public.hq_add_franchise(text, text, text, text) to authenticated;
grant execute on function public.hq_update_franchise(integer, text, text, text, text, boolean) to authenticated;
grant execute on function public.hq_add_person(text, text, text, integer, text, text, text) to authenticated;
grant execute on function public.hq_update_profile(uuid, text, text, text, text, boolean, integer) to authenticated;
grant execute on function public.hq_reassign_lead(integer, uuid) to authenticated;
grant execute on function public.hq_cancel_lead(integer, text) to authenticated;
grant execute on function public.hq_resolve_dispute(integer, text, text) to authenticated;
