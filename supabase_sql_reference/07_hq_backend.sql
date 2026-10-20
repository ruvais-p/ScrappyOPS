/* =====================================================================
   HQ BACKEND · STEP 7 · what the HQ dashboard reads and does
   Needs steps 1 to 6. Nothing here drops or deletes anything.
   Every function checks that the caller is HQ.
   - activity log (append only) for HQ decisions
   - summary functions, so totals are never cut off by the 1000-row API limit
   - safe actions: reassign or cancel a lead, set a rate, edit a team member,
     record the outcome of a disputed cash count
   - the old receive_cash is switched off: cash must go through count_route_cash
   ===================================================================== */

/* ---------- activity log: who did what, can never be edited ---------- */
create table if not exists public.hq_audit (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  by_id uuid references public.profiles(id),
  action text not null,
  ref text,
  detail jsonb
);
alter table public.hq_audit enable row level security;
create policy hq_audit_read on public.hq_audit for select to authenticated using ((select public.my_role()) = 'hq');
revoke all on public.hq_audit from anon;
revoke insert, update, delete, truncate on public.hq_audit from authenticated;

create or replace function public.guard_append_only()
returns trigger language plpgsql set search_path to 'public'
as $$ begin raise exception 'This record cannot be changed or deleted.'; end $$;
revoke all on function public.guard_append_only() from public, anon, authenticated;
create trigger hq_audit_guard before update or delete on public.hq_audit
  for each row execute function public.guard_append_only();

create or replace function public.hq_log(p_action text, p_ref text, p_detail jsonb)
returns void language sql security definer set search_path to 'public'
as $$ insert into public.hq_audit (by_id, action, ref, detail) values (auth.uid(), p_action, p_ref, p_detail) $$;
revoke all on function public.hq_log(text, text, jsonb) from public, anon, authenticated;

/* ---------- what HQ decided about a disputed cash count ---------- */
create table if not exists public.settlement_resolutions (
  id integer generated always as identity primary key,
  settlement_id integer not null unique references public.cash_settlements(id),
  decision text not null check (decision in ('recover_from_driver','write_off','no_action')),
  note text not null check (length(btrim(note)) > 0),
  resolved_by uuid not null references public.profiles(id),
  resolved_at timestamptz not null default now()
);
alter table public.settlement_resolutions enable row level security;
create policy settlement_resolutions_read on public.settlement_resolutions for select to authenticated using ((select public.is_wh_staff()));
revoke all on public.settlement_resolutions from anon;
revoke insert, update, delete, truncate on public.settlement_resolutions from authenticated;
create trigger settlement_resolutions_guard before update or delete on public.settlement_resolutions
  for each row execute function public.guard_append_only();

/* ---------- switch off the old cash handover that skipped the count ---------- */
create or replace function public.receive_cash(p_driver_id uuid, p_amount numeric)
returns void language plpgsql security definer set search_path to 'public'
as $$ begin raise exception 'Use the cash count on the Finance screen. It records the count and needs a supervisor to verify it.'; end $$;

/* ---------- one-screen summary for a date range ---------- */
create or replace function public.hq_overview(p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path to 'public'
as $$
declare v_today date := (now() at time zone 'Asia/Kolkata')::date; r jsonb;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select jsonb_build_object(
    'leads_scheduled',   (select count(*) from leads where status = 'scheduled'),
    'leads_today',       (select count(*) from leads where status in ('scheduled','in_progress') and (slot at time zone 'Asia/Kolkata')::date = v_today),
    'leads_in_progress', (select count(*) from leads where status = 'in_progress'),
    'leads_late',        (select count(*) from leads where status = 'scheduled' and slot < now() - interval '3 hours'),
    'leads_closed',      (select count(*) from leads where status = 'closed' and (closed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'leads_cancelled',   (select count(*) from leads where status = 'cancelled' and (created_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'paid_bills',        (select count(*) from bills where status = 'paid' and (paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'kg',                (select coalesce(sum(bt.total_kg), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'amount',            (select coalesce(sum(bt.total_amount), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'cash_amount',       (select coalesce(sum(bt.total_amount), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.status = 'paid' and b.payment_method = 'cash' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'upi_amount',        (select coalesce(sum(bt.total_amount), 0) from bills b join bill_totals bt on bt.bill_id = b.id where b.status = 'paid' and b.payment_method = 'upi' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'loads_open',        (select count(*) from loads where status = 'open'),
    'loads_waiting',     (select count(*) from loads where status = 'submitted'),
    'loads_flagged',     (select count(*) from loads where status = 'flagged'),
    'billed_kg_weighed', (select coalesce(sum(billed_kg), 0) from load_weighings where superseded_at is null and (weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'weighed_kg',        (select coalesce(sum(warehouse_kg), 0) from load_weighings where superseded_at is null and (weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'cash_in_field',     (select coalesce(sum(amount), 0) from cash_ledger),
    'counts_waiting',    (select count(*) from wh_route_cash(date '2026-01-01', v_today + 1) where route_status = 'awaiting_count'),
    'counts_unverified', (select count(*) from cash_settlements where status = 'counted'),
    'disputes_open',     (select count(*) from cash_settlements s where s.status = 'disputed' and not exists (select 1 from settlement_resolutions x where x.settlement_id = s.id)),
    'shortage_total',    (select coalesce(sum(-difference), 0) from cash_settlements where difference < 0 and (counted_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    'stock_kg',          (select coalesce(sum(stock_now_kg), 0) from wh_stock_report(v_today, v_today)),
    'stock_value',       (select coalesce(sum(stock_now_kg * rate_per_kg), 0) from wh_stock_report(v_today, v_today)),
    'req_open',          (select count(*) from hq_requirement_progress where status in ('open','partial')),
    'req_remaining_kg',  (select coalesce(sum(remaining_kg), 0) from hq_requirement_progress where status in ('open','partial')),
    'req_overdue',       (select count(*) from hq_requirement_progress where is_overdue)
  ) into r;
  return r;
end $$;

/* ---------- paid pickups per day (for the trend chart) ---------- */
create or replace function public.hq_daily(p_from date, p_to date)
returns table (day date, pickups bigint, kg numeric, amount numeric, cash_amount numeric, upi_amount numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select d.dd::date, count(b.id), coalesce(sum(bt.total_kg), 0), coalesce(sum(bt.total_amount), 0),
         coalesce(sum(bt.total_amount) filter (where b.payment_method = 'cash'), 0),
         coalesce(sum(bt.total_amount) filter (where b.payment_method = 'upi'), 0)
  from generate_series(p_from, least(p_to, p_from + 400), interval '1 day') d(dd)
  left join bills b on b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date = d.dd::date
  left join bill_totals bt on bt.bill_id = b.id
  group by d.dd order by d.dd;
end $$;

/* ---------- what was bought, by material ---------- */
create or replace function public.hq_item_summary(p_from date, p_to date)
returns table (item_id integer, item_name text, kg numeric, amount numeric, pickups bigint, avg_rate numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select i.id, i.name, coalesce(sum(bi.qty_kg), 0), coalesce(sum(bi.amount), 0), count(distinct b.id),
         case when sum(bi.qty_kg) > 0 then round(sum(bi.amount) / sum(bi.qty_kg), 2) else 0 end
  from scrap_items i
  left join bills b on b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to
  left join bill_items bi on bi.bill_id = b.id and bi.item_id = i.id
  where i.active
  group by i.id, i.name
  order by i.id;
end $$;

/* ---------- one line per driver ---------- */
create or replace function public.hq_driver_scorecard(p_from date, p_to date)
returns table (driver_id uuid, full_name text, active boolean, vehicle_no text, territory text, leads_assigned bigint,
               pickups bigint, kg numeric, amount numeric, avg_minutes numeric, weighed_billed_kg numeric, weighed_kg numeric,
               variance_pct numeric, loads_off_tolerance bigint, cash_in_hand numeric, cash_short numeric, disputes bigint)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select p.id, p.full_name, p.active, p.vehicle_no, p.territory,
    (select count(*) from leads l where l.driver_id = p.id and l.status <> 'cancelled' and (l.slot at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select count(*) from bills b join loads lo on lo.id = b.load_id where lo.driver_id = p.id and b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(bt.total_kg), 0) from bills b join loads lo on lo.id = b.load_id join bill_totals bt on bt.bill_id = b.id where lo.driver_id = p.id and b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(bt.total_amount), 0) from bills b join loads lo on lo.id = b.load_id join bill_totals bt on bt.bill_id = b.id where lo.driver_id = p.id and b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select round(avg(extract(epoch from (b.paid_at - b.created_at)) / 60)::numeric, 1) from bills b join loads lo on lo.id = b.load_id where lo.driver_id = p.id and b.status = 'paid' and (b.paid_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(w.billed_kg), 0) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(w.warehouse_kg), 0) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select case when sum(w.billed_kg) > 0 then round((sum(w.warehouse_kg) - sum(w.billed_kg)) / sum(w.billed_kg) * 100, 2) end from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select count(distinct w.load_id) from load_weighings w join loads lo on lo.id = w.load_id where lo.driver_id = p.id and w.superseded_at is null and not w.within_tolerance and (w.weighed_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id),
    (select coalesce(sum(-s.difference), 0) from cash_settlements s where s.driver_id = p.id and s.difference < 0 and (s.counted_at at time zone 'Asia/Kolkata')::date between p_from and p_to),
    (select count(*) from cash_settlements s where s.driver_id = p.id and s.status = 'disputed' and (s.counted_at at time zone 'Asia/Kolkata')::date between p_from and p_to)
  from profiles p where p.role = 'driver' order by p.active desc, p.full_name;
end $$;

/* ---------- bills with customer details (HQ may see them) ---------- */
create or replace function public.hq_bills(p_from date, p_to date, p_status text default null, p_driver uuid default null,
                                           p_search text default null, p_limit integer default 200)
returns table (bill_id integer, bill_no text, lead_code text, customer_name text, phone text, area text, driver_id uuid, driver_name text,
               load_code text, status text, payment_method text, upi_ref text, total_kg numeric, total_amount numeric,
               created_at timestamptz, sent_at timestamptz, whatsapp_opened_at timestamptz, confirmed_at timestamptz, paid_at timestamptz,
               confirm_proof_url text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select b.id, b.bill_no, ld.code, cu.name, cu.phone, cu.area, lo.driver_id, pr.full_name, lo.code, b.status, b.payment_method, b.upi_ref,
         bt.total_kg, bt.total_amount, b.created_at, b.sent_at, b.whatsapp_opened_at, b.confirmed_at, b.paid_at, b.confirm_proof_url
  from bills b
  join bill_totals bt on bt.bill_id = b.id
  join leads ld on ld.id = b.lead_id
  join customers cu on cu.id = ld.customer_id
  join loads lo on lo.id = b.load_id
  join profiles pr on pr.id = lo.driver_id
  where (b.created_at at time zone 'Asia/Kolkata')::date between p_from and p_to
    and (p_status is null or b.status = p_status)
    and (p_driver is null or lo.driver_id = p_driver)
    and (p_search is null or btrim(p_search) = '' or cu.name ilike '%' || btrim(p_search) || '%' or cu.phone ilike '%' || btrim(p_search) || '%'
         or b.bill_no ilike '%' || btrim(p_search) || '%' or ld.code ilike '%' || btrim(p_search) || '%' or coalesce(cu.area, '') ilike '%' || btrim(p_search) || '%')
  order by b.created_at desc
  limit greatest(least(p_limit, 500), 1);
end $$;

/* ---------- leads with customer and driver ---------- */
create or replace function public.hq_leads(p_from date, p_to date, p_status text default null, p_driver uuid default null,
                                           p_search text default null, p_limit integer default 300)
returns table (lead_id integer, code text, customer_name text, phone text, address text, area text, driver_id uuid, driver_name text,
               slot timestamptz, status text, items_said text, bill_no text, bill_status text, created_at timestamptz, closed_at timestamptz)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select l.id, l.code, cu.name, cu.phone, cu.address, cu.area, l.driver_id, pr.full_name, l.slot, l.status, l.items_said,
         b.bill_no, b.status, l.created_at, l.closed_at
  from leads l
  join customers cu on cu.id = l.customer_id
  join profiles pr on pr.id = l.driver_id
  left join bills b on b.lead_id = l.id
  where ((l.slot at time zone 'Asia/Kolkata')::date between p_from and p_to or (l.status in ('scheduled','in_progress') and p_status is not null))
    and (p_status is null or l.status = p_status)
    and (p_driver is null or l.driver_id = p_driver)
    and (p_search is null or btrim(p_search) = '' or cu.name ilike '%' || btrim(p_search) || '%' or cu.phone ilike '%' || btrim(p_search) || '%'
         or l.code ilike '%' || btrim(p_search) || '%' or coalesce(cu.area, '') ilike '%' || btrim(p_search) || '%')
  order by l.slot desc nulls last, l.id desc
  limit greatest(least(p_limit, 500), 1);
end $$;

/* ---------- loads with billed against weighed ---------- */
create or replace function public.hq_loads(p_from date, p_to date)
returns table (load_id integer, code text, driver_id uuid, driver_name text, vehicle_no text, status text, started_at timestamptz,
               submitted_at timestamptz, pickups bigint, billed_kg numeric, billed_amount numeric, weighed_kg numeric,
               variance_pct numeric, items_off bigint, resolution_note text)
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
         l.resolution_note
  from loads l join profiles p on p.id = l.driver_id
  where (l.started_at at time zone 'Asia/Kolkata')::date between p_from and p_to or l.status in ('submitted','flagged')
  order by l.id desc;
end $$;

/* ---------- the team, with e-mail and cash in hand ---------- */
create or replace function public.hq_team()
returns table (id uuid, full_name text, email text, role text, phone text, territory text, vehicle_no text, active boolean,
               cash_in_hand numeric, open_leads bigint)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select p.id, p.full_name, u.email::text, p.role, p.phone, p.territory, p.vehicle_no, p.active,
         (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id),
         (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress'))
  from profiles p left join auth.users u on u.id = p.id
  order by case p.role when 'hq' then 0 when 'supervisor' then 1 when 'warehouse' then 2 else 3 end, p.full_name;
end $$;

/* ---------- actions ---------- */
create or replace function public.hq_reassign_lead(p_lead_id integer, p_driver_id uuid)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_lead leads; v_name text;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_lead from leads where id = p_lead_id for update;
  if v_lead.id is null then raise exception 'Lead not found.'; end if;
  if v_lead.status <> 'scheduled' then raise exception 'Only a lead that has not been started can be reassigned (this one is %).', v_lead.status; end if;
  select full_name into v_name from profiles where id = p_driver_id and role = 'driver' and active;
  if v_name is null then raise exception 'Choose an active driver.'; end if;
  if v_lead.driver_id = p_driver_id then raise exception 'This lead is already with %.', v_name; end if;
  update leads set driver_id = p_driver_id where id = p_lead_id;
  perform public.hq_log('lead_reassigned', v_lead.code, jsonb_build_object('from', v_lead.driver_id, 'to', p_driver_id));
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
  perform public.hq_log('lead_cancelled', v_lead.code, jsonb_build_object('reason', btrim(p_reason)));
  return v_lead.code;
end $$;

create or replace function public.hq_set_rate(p_item_id integer, p_rate numeric)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_old numeric; v_name text;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if p_rate is null or p_rate <= 0 or p_rate > 100000 then raise exception 'Enter a rate between 0 and 100000 per kg.'; end if;
  select name into v_name from scrap_items where id = p_item_id and active;
  if v_name is null then raise exception 'Unknown material.'; end if;
  select rate_per_kg into v_old from current_rates where item_id = p_item_id;
  if v_old = p_rate then raise exception '% is already ₹% per kg.', v_name, p_rate; end if;
  insert into rates (item_id, rate_per_kg, set_by) values (p_item_id, p_rate, auth.uid());
  perform public.hq_log('rate_set', v_name, jsonb_build_object('old', v_old, 'new', p_rate));
  return v_name;
end $$;

create or replace function public.hq_update_profile(p_id uuid, p_full_name text, p_phone text, p_territory text, p_vehicle_no text, p_active boolean)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_old profiles;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_old from profiles where id = p_id for update;
  if v_old.id is null then raise exception 'Person not found.'; end if;
  if p_full_name is null or length(btrim(p_full_name)) = 0 then raise exception 'Enter a name.'; end if;
  if p_id = auth.uid() and not p_active then raise exception 'You cannot deactivate your own login.'; end if;
  if v_old.active and not p_active and v_old.role = 'driver' then
    if exists (select 1 from loads where driver_id = p_id and status = 'open') then raise exception 'This driver has a route on the road. Deactivate after the route ends.'; end if;
    if exists (select 1 from leads where driver_id = p_id and status in ('scheduled','in_progress')) then raise exception 'Reassign this driver''s open leads first.'; end if;
  end if;
  update profiles set full_name = btrim(p_full_name), phone = nullif(btrim(coalesce(p_phone, '')), ''), territory = nullif(btrim(coalesce(p_territory, '')), ''),
         vehicle_no = nullif(btrim(coalesce(p_vehicle_no, '')), ''), active = p_active where id = p_id;
  perform public.hq_log('profile_updated', v_old.full_name, jsonb_build_object('id', p_id, 'was_active', v_old.active, 'now_active', p_active));
  return btrim(p_full_name);
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
  perform public.hq_log('dispute_resolved', 'settlement ' || p_settlement_id, jsonb_build_object('decision', p_decision, 'difference', s.difference));
  return p_decision;
end $$;

/* ---------- who may call what ---------- */
revoke all on function public.receive_cash(uuid, numeric) from public, anon;
revoke all on function public.hq_overview(date, date) from public, anon;
revoke all on function public.hq_daily(date, date) from public, anon;
revoke all on function public.hq_item_summary(date, date) from public, anon;
revoke all on function public.hq_driver_scorecard(date, date) from public, anon;
revoke all on function public.hq_bills(date, date, text, uuid, text, integer) from public, anon;
revoke all on function public.hq_leads(date, date, text, uuid, text, integer) from public, anon;
revoke all on function public.hq_loads(date, date) from public, anon;
revoke all on function public.hq_team() from public, anon;
revoke all on function public.hq_reassign_lead(integer, uuid) from public, anon;
revoke all on function public.hq_cancel_lead(integer, text) from public, anon;
revoke all on function public.hq_set_rate(integer, numeric) from public, anon;
revoke all on function public.hq_update_profile(uuid, text, text, text, text, boolean) from public, anon;
revoke all on function public.hq_resolve_dispute(integer, text, text) from public, anon;
grant execute on function public.receive_cash(uuid, numeric) to authenticated;
grant execute on function public.hq_overview(date, date) to authenticated;
grant execute on function public.hq_daily(date, date) to authenticated;
grant execute on function public.hq_item_summary(date, date) to authenticated;
grant execute on function public.hq_driver_scorecard(date, date) to authenticated;
grant execute on function public.hq_bills(date, date, text, uuid, text, integer) to authenticated;
grant execute on function public.hq_leads(date, date, text, uuid, text, integer) to authenticated;
grant execute on function public.hq_loads(date, date) to authenticated;
grant execute on function public.hq_team() to authenticated;
grant execute on function public.hq_reassign_lead(integer, uuid) to authenticated;
grant execute on function public.hq_cancel_lead(integer, text) to authenticated;
grant execute on function public.hq_set_rate(integer, numeric) to authenticated;
grant execute on function public.hq_update_profile(uuid, text, text, text, text, boolean) to authenticated;
grant execute on function public.hq_resolve_dispute(integer, text, text) to authenticated;

/* live updates for the HQ dashboard */
alter publication supabase_realtime add table public.hq_audit, public.settlement_resolutions, public.leads;
