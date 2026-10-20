/* =====================================================================
   STEP 15 · leads go to the franchise, the supervisor splits them among drivers
           · a driver can mark a pickup "could not complete" with a reason
   Needs step 14. Nothing is deleted. Old leads keep working as they are.

   NEW LEAD STATES
     unassigned : uploaded by HQ for a franchise, no driver yet
     failed     : the driver could not complete the pickup (reason + note kept)
   HQ upload     : franchise_code (for example KKD). driver_email still works and
                   gives a lead that is already assigned.
   ASSIGNMENT    : supervisors (and HQ) assign or split leads, only inside the
                   supervisor's own franchise.
   ===================================================================== */

alter table public.leads drop constraint if exists leads_status_check;
alter table public.leads add constraint leads_status_check
  check (status = any (array['unassigned','scheduled','in_progress','closed','cancelled','failed']));
alter table public.leads drop constraint if exists leads_driver_check;
alter table public.leads add constraint leads_driver_check check (driver_id is not null or status in ('unassigned','cancelled'));
alter table public.leads add column if not exists fail_reason text, add column if not exists fail_note text, add column if not exists failed_at timestamptz;
alter table public.lead_import add column if not exists franchise_code text;
create index if not exists leads_fr_status_idx on public.leads (franchise_id, status);

/* a lead with no driver takes the franchise it was uploaded for */
create or replace function public.fr_from_driver() returns trigger
language plpgsql security definer set search_path to 'public' as $$
begin
  if new.driver_id is not null then
    select franchise_id into new.franchise_id from public.profiles where id = new.driver_id;
  end if;
  if new.franchise_id is null then raise exception 'This lead has no franchise.'; end if;
  return new;
end $$;

/* ---------------- upload: franchise code, driver optional ---------------- */
create or replace function public.process_lead_import()
returns trigger
language plpgsql
security definer set search_path to 'public'
as $$
declare
  v_phone text; v_driver uuid; v_driver_active boolean; v_dfr integer; v_fr integer; v_frcode text; v_cust int; v_date date; v_time time;
  v_slot timestamptz; v_t text; v_ampm text; v_h int; v_m int; v_code text;
  v_lat numeric; v_lng numeric; v_la text; v_ln text; v_em text; v_fc text;
begin
  if new.status <> 'new' then return new; end if;
  if coalesce(trim(new.customer_name), '') = '' and coalesce(trim(new.phone), '') = '' and coalesce(trim(new.address), '') = ''
     and coalesce(trim(new.driver_email), '') = '' and coalesce(trim(new.franchise_code), '') = '' and coalesce(trim(new.pickup_date), '') = '' then
    return null;
  end if;

  begin
    if coalesce(trim(new.customer_name), '') = '' then raise exception 'Customer name is missing'; end if;
    if coalesce(trim(new.address), '') = '' then raise exception 'Address is missing'; end if;

    v_phone := regexp_replace(coalesce(new.phone, ''), '\D', '', 'g');
    if length(v_phone) > 10 then v_phone := right(v_phone, 10); end if;
    if length(v_phone) <> 10 then raise exception 'Phone must have 10 digits (got "%")', coalesce(new.phone, ''); end if;

    v_em := nullif(trim(coalesce(new.driver_email, '')), ''); v_fc := upper(nullif(trim(coalesce(new.franchise_code, '')), ''));
    if v_em is not null then
      select p.id, p.active, p.franchise_id into v_driver, v_driver_active, v_dfr
      from auth.users u join profiles p on p.id = u.id and p.role = 'driver'
      where lower(u.email) = lower(v_em);
      if v_driver is null then raise exception 'No driver with email "%"', v_em; end if;
      if not v_driver_active then raise exception 'Driver % is inactive', v_em; end if;
      select code into v_frcode from franchises where id = v_dfr;
      if v_fc is not null and v_fc <> upper(v_frcode) then raise exception 'Driver % belongs to franchise %, not %', v_em, v_frcode, v_fc; end if;
      v_fr := v_dfr;
    else
      if v_fc is null then raise exception 'Give the franchise code (for example KKD)'; end if;
      select id into v_fr from franchises where upper(code) = v_fc and active;
      if v_fr is null then raise exception 'No active franchise with code "%"', v_fc; end if;
    end if;

    v_t := trim(coalesce(new.pickup_date, ''));
    if v_t ~ '^\d{4}-\d{1,2}-\d{1,2}$' then v_date := to_date(v_t, 'YYYY-MM-DD');
    elsif v_t ~ '^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$' then v_date := to_date(regexp_replace(v_t, '[-.]', '/', 'g'), 'DD/MM/YYYY');
    else raise exception 'Date "%" not understood. Use DD-MM-YYYY', v_t; end if;

    v_t := upper(trim(coalesce(new.pickup_time, '')));
    if v_t = '' then v_time := '09:00';
    else
      if v_t !~ '^\d{1,2}[:.]\d{2}' then raise exception 'Time "%" not understood. Use e.g. 11:30 AM', new.pickup_time; end if;
      v_h := split_part(regexp_replace(v_t, '\.', ':'), ':', 1)::int;
      v_m := left(split_part(regexp_replace(v_t, '\.', ':'), ':', 2), 2)::int;
      v_ampm := substring(v_t from '(AM|PM)');
      if v_ampm = 'PM' and v_h < 12 then v_h := v_h + 12; end if;
      if v_ampm = 'AM' and v_h = 12 then v_h := 0; end if;
      if v_h > 23 or v_m > 59 then raise exception 'Time "%" is not valid', new.pickup_time; end if;
      v_time := make_time(v_h, v_m, 0);
    end if;
    v_slot := (v_date + v_time) at time zone 'Asia/Kolkata';
    if v_slot < now() - interval '1 day' then raise exception 'Pickup date % is in the past', v_date; end if;

    v_la := nullif(trim(coalesce(new.latitude, '')), ''); v_ln := nullif(trim(coalesce(new.longitude, '')), '');
    if v_la is not null and v_ln is null and v_la ~ '^\s*-?\d+(\.\d+)?\s*[, ;]\s*-?\d+(\.\d+)?\s*$' then
      v_ln := trim(regexp_replace(v_la, '^.*[, ;]', '')); v_la := trim(regexp_replace(v_la, '\s*[, ;].*$', ''));
    end if;
    if v_la is not null or v_ln is not null then
      if v_la is null or v_ln is null then raise exception 'Give both latitude and longitude, or leave both blank'; end if;
      if v_la !~ '^-?\d+(\.\d+)?$' or v_ln !~ '^-?\d+(\.\d+)?$' then raise exception 'Latitude and longitude must be numbers (got "%", "%")', v_la, v_ln; end if;
      v_lat := v_la::numeric; v_lng := v_ln::numeric;
      if v_lat not between -90 and 90 or v_lng not between -180 and 180 then raise exception 'Latitude/longitude out of range (got "%", "%"). Latitude first, then longitude', v_la, v_ln; end if;
      if v_lat not between 6 and 38 or v_lng not between 67 and 98 then raise exception 'Location (%, %) is not in India. Check that latitude and longitude are not swapped', v_la, v_ln; end if;
    end if;

    select id into v_cust from customers where right(regexp_replace(phone, '\D', '', 'g'), 10) = v_phone order by id limit 1;
    if v_cust is null then
      insert into customers (name, phone, address, area, upi_id)
      values (trim(new.customer_name), v_phone, trim(new.address), nullif(trim(new.area), ''), nullif(trim(new.upi_id), ''))
      returning id into v_cust;
    else
      update customers set upi_id = coalesce(upi_id, nullif(trim(new.upi_id), '')) where id = v_cust;
    end if;

    select code into v_code from leads
    where customer_id = v_cust and status in ('unassigned', 'scheduled', 'in_progress')
      and (slot at time zone 'Asia/Kolkata')::date = v_date
    limit 1;
    if v_code is not null then
      new.status := 'duplicate'; new.lead_code := v_code;
      new.message := 'Lead already exists for this customer on this day';
      return new;
    end if;

    insert into leads (customer_id, driver_id, status, franchise_id, slot, items_said, created_by, latitude, longitude)
    values (v_cust, v_driver, case when v_driver is null then 'unassigned' else 'scheduled' end, v_fr, v_slot, nullif(trim(new.items), ''), auth.uid(), v_lat, v_lng)
    returning code into v_code;

    new.status := 'created'; new.lead_code := v_code;
    new.message := case when v_driver is null then 'Created, waiting for the supervisor to assign a driver' else 'Created' end
                   || case when trim(coalesce(new.pickup_time, '')) = '' then ' (no time given, set to 9:00 AM)' else '' end
                   || case when v_lat is null then ' (no map location)' else '' end;
  exception when others then
    new.status := 'error'; new.message := sqlerrm;
  end;
  return new;
end $$;

/* ---------------- supervisor: see and assign leads ---------------- */
create or replace function public.wh_leads(p_from date, p_to date, p_status text default null, p_driver uuid default null,
                                           p_search text default null, p_limit integer default 500, p_franchise integer default null)
returns table (lead_id integer, code text, customer_name text, phone text, address text, area text, latitude numeric, longitude numeric,
               slot timestamptz, status text, items_said text, driver_id uuid, driver_name text, fail_reason text, fail_note text,
               failed_at timestamptz, bill_no text, total_amount numeric, franchise_code text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_f integer := public.fr_scope(p_franchise);
begin
  return query
  select l.id, l.code, cu.name, cu.phone, cu.address, cu.area, l.latitude, l.longitude, l.slot, l.status, l.items_said,
         l.driver_id, pr.full_name, l.fail_reason, l.fail_note, l.failed_at, b.bill_no, bt.total_amount, fr.code
  from leads l
  join customers cu on cu.id = l.customer_id
  join franchises fr on fr.id = l.franchise_id
  left join profiles pr on pr.id = l.driver_id
  left join bills b on b.lead_id = l.id
  left join lateral (select sum(bi.amount) as total_amount from bill_items bi where bi.bill_id = b.id) bt on b.id is not null
  where (v_f is null or l.franchise_id = v_f)
    and ((l.slot at time zone 'Asia/Kolkata')::date between p_from and p_to
         or l.status = 'unassigned'
         or (l.status = 'failed' and l.failed_at >= now() - interval '7 days'))
    and (p_status is null or l.status = p_status)
    and (p_driver is null or l.driver_id = p_driver)
    and (p_search is null or btrim(p_search) = '' or cu.name ilike '%' || btrim(p_search) || '%' or cu.phone ilike '%' || btrim(p_search) || '%'
         or l.code ilike '%' || btrim(p_search) || '%' or coalesce(cu.area, '') ilike '%' || btrim(p_search) || '%')
  order by (l.status = 'unassigned') desc, l.slot nulls last, l.id
  limit greatest(least(p_limit, 1000), 1);
end $$;

create or replace function public.wh_lead_counts(p_franchise integer default null)
returns table (unassigned bigint, failed_recent bigint, open_today bigint)
language plpgsql stable security definer set search_path to 'public'
as $$
declare v_f integer := public.fr_scope(p_franchise); v_today date := (now() at time zone 'Asia/Kolkata')::date;
begin
  return query select
    (select count(*) from leads l where l.status = 'unassigned' and (v_f is null or l.franchise_id = v_f)),
    (select count(*) from leads l where l.status = 'failed' and l.failed_at >= now() - interval '3 days' and (v_f is null or l.franchise_id = v_f)),
    (select count(*) from leads l where l.status in ('scheduled','in_progress') and (l.slot at time zone 'Asia/Kolkata')::date = v_today and (v_f is null or l.franchise_id = v_f));
end $$;

create or replace function public.wh_driver_workload(p_date date, p_franchise integer default null)
returns table (driver_id uuid, full_name text, vehicle_no text, territory text, leads_day bigint, open_now bigint)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
declare v_f integer := public.fr_scope(p_franchise);
begin
  return query
  select p.id, p.full_name, p.vehicle_no, p.territory,
         (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress','closed') and (l.slot at time zone 'Asia/Kolkata')::date = p_date),
         (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress'))
  from profiles p
  where p.role = 'driver' and p.active and (v_f is null or p.franchise_id = v_f)
  order by p.full_name;
end $$;

create or replace function public.wh_assign_leads(p_lead_ids integer[], p_driver uuid)
returns integer
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_role text := my_role(); v_f integer; v_drv profiles; r leads; n integer := 0; codes text[] := '{}'; v_ids integer[];
begin
  if v_role not in ('supervisor', 'hq') then raise exception 'Only the supervisor can assign leads.'; end if;
  select array_agg(distinct x) into v_ids from unnest(p_lead_ids) x;
  if v_ids is null or cardinality(v_ids) = 0 then raise exception 'Select at least one lead.'; end if;
  if cardinality(v_ids) > 200 then raise exception 'Assign at most 200 leads at a time.'; end if;
  if p_driver is not null then
    select * into v_drv from profiles where id = p_driver and role = 'driver' and active;
    if v_drv.id is null then raise exception 'Choose an active driver.'; end if;
  end if;
  if v_role = 'supervisor' then
    v_f := my_franchise();
    if v_f is null then raise exception 'Your login is not assigned to a franchise.'; end if;
    if p_driver is not null and v_drv.franchise_id is distinct from v_f then raise exception 'That driver is not in your franchise.'; end if;
  end if;
  for r in select * from leads where id = any (v_ids) order by id for update loop
    if v_role = 'supervisor' and r.franchise_id <> v_f then raise exception 'Lead % is not in your franchise.', r.code; end if;
    if p_driver is not null and v_drv.franchise_id <> r.franchise_id then raise exception 'Lead % belongs to a different franchise than this driver.', r.code; end if;
    if r.status not in ('unassigned', 'scheduled', 'failed') then raise exception 'Lead % is % and cannot be assigned.', r.code, r.status; end if;
    if p_driver is null and r.status <> 'scheduled' then raise exception 'Lead % is already unassigned or not completed.', r.code; end if;
    update leads set driver_id = p_driver, status = case when p_driver is null then 'unassigned' else 'scheduled' end,
                     fail_reason = null, fail_note = null, failed_at = null
     where id = r.id;
    n := n + 1; codes := codes || r.code;
  end loop;
  if n <> cardinality(v_ids) then raise exception 'Some of the selected leads were not found.'; end if;
  perform public.hq_log(case when p_driver is null then 'leads_unassigned' else 'leads_assigned' end, n || ' lead' || case when n = 1 then '' else 's' end,
    jsonb_build_object('driver', p_driver, 'driver_name', v_drv.full_name, 'codes', to_jsonb(codes)), coalesce(v_f, v_drv.franchise_id));
  return n;
end $$;

/* even split: leads are sorted by area, then time, and handed out in blocks so each driver gets neighbouring areas */
create or replace function public.wh_split_leads(p_lead_ids integer[], p_driver_ids uuid[])
returns jsonb
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_role text := my_role(); v_drivers uuid[]; v_ids integer[]; n integer; k integer; base integer; extra integer; i integer; d integer;
  v_out jsonb := '[]'::jsonb; v_names text; grp integer[]; v_count integer;
begin
  if v_role not in ('supervisor', 'hq') then raise exception 'Only the supervisor can assign leads.'; end if;
  select array_agg(distinct x) into v_drivers from unnest(p_driver_ids) x;
  if v_drivers is null or cardinality(v_drivers) = 0 then raise exception 'Choose at least one driver.'; end if;
  k := cardinality(v_drivers);
  select array_agg(l.id order by coalesce(cu.area, ''), l.slot, l.id) into v_ids
    from leads l join customers cu on cu.id = l.customer_id where l.id = any (p_lead_ids);
  if v_ids is null or cardinality(v_ids) = 0 then raise exception 'Select at least one lead.'; end if;
  n := cardinality(v_ids); base := n / k; extra := n % k;
  for d in 1..k loop
    grp := '{}';
    for i in 0..n - 1 loop
      if base = 0 then
        if i = d - 1 then grp := grp || v_ids[i + 1]; end if;
      elsif i < extra * (base + 1) then
        if i / (base + 1) = d - 1 then grp := grp || v_ids[i + 1]; end if;
      else
        if extra + (i - extra * (base + 1)) / base = d - 1 then grp := grp || v_ids[i + 1]; end if;
      end if;
    end loop;
    if cardinality(grp) > 0 then
      v_count := public.wh_assign_leads(grp, v_drivers[d]);
      select full_name into v_names from profiles where id = v_drivers[d];
      v_out := v_out || jsonb_build_array(jsonb_build_object('driver_id', v_drivers[d], 'name', v_names, 'count', v_count));
    end if;
  end loop;
  return v_out;
end $$;

/* ---------------- driver: pickup could not be completed ---------------- */
create or replace function public.fail_pickup(p_lead_id integer, p_reason text, p_note text default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_lead leads; v_bill bills; v_note text := nullif(btrim(coalesce(p_note, '')), ''); v_kg numeric := 0; v_n integer := 0; v_loadid integer;
  v_reasons text[] := array['Customer not at home', 'Customer cancelled', 'Phone not reachable', 'Wrong address or location',
                            'No scrap, or too little', 'Customer did not agree to the rate', 'Vehicle or other problem on my side', 'Other'];
begin
  if my_role() <> 'driver' then raise exception 'Only drivers can do this.'; end if;
  if p_reason is null or not (p_reason = any (v_reasons)) then raise exception 'Choose a reason.'; end if;
  if p_reason = 'Other' and v_note is null then raise exception 'Write a short note for "Other".'; end if;
  if v_note is not null and length(v_note) > 300 then raise exception 'Keep the note under 300 characters.'; end if;
  select * into v_lead from leads where id = p_lead_id and driver_id = auth.uid() for update;
  if v_lead.id is null then raise exception 'This lead is not assigned to you.'; end if;
  if v_lead.status not in ('scheduled', 'in_progress') then raise exception 'This lead is already %.', v_lead.status; end if;

  select * into v_bill from bills where lead_id = p_lead_id for update;
  if v_bill.id is not null then
    if v_bill.status <> 'draft' then raise exception 'The bill was already sent to the customer. Finish this pickup or ask HQ to cancel the bill.'; end if;
    select coalesce(sum(qty_kg), 0), count(*) into v_kg, v_n from bill_items where bill_id = v_bill.id;
    v_loadid := v_bill.load_id;
    delete from bill_items where bill_id = v_bill.id;
    delete from bills where id = v_bill.id;
    if v_loadid is not null and not exists (select 1 from bills where load_id = v_loadid)
       and not exists (select 1 from load_weighings where load_id = v_loadid) and not exists (select 1 from cash_settlements where load_id = v_loadid)
       and exists (select 1 from loads where id = v_loadid and status = 'open' and driver_id = auth.uid()) then
      delete from loads where id = v_loadid;
    end if;
  end if;

  update leads set status = 'failed', fail_reason = p_reason, fail_note = v_note, failed_at = now() where id = p_lead_id;
  perform public.hq_log('lead_failed', v_lead.code,
    jsonb_build_object('reason', p_reason, 'note', v_note, 'driver', auth.uid(), 'draft_kg_discarded', v_kg, 'draft_items_discarded', v_n), v_lead.franchise_id);
  return v_lead.code;
end $$;

/* ---------------- existing functions, extended ---------------- */
create or replace function public.start_pickup(p_lead_id integer)
returns integer
language plpgsql security definer set search_path to 'public'
as $$
declare v_lead leads; v_load int; v_bill int;
begin
  if my_role() <> 'driver' then raise exception 'Only drivers can start pickups.'; end if;
  select * into v_lead from leads where id = p_lead_id and driver_id = auth.uid();
  if v_lead.id is null then raise exception 'This lead is not assigned to you.'; end if;
  if v_lead.status not in ('scheduled', 'in_progress') then raise exception 'This lead is already %.', v_lead.status; end if;

  select id into v_bill from bills where lead_id = p_lead_id;
  if v_bill is not null then return v_bill; end if;

  select id into v_load from loads where driver_id = auth.uid() and status = 'open';
  if v_load is null then
    insert into loads (driver_id, vehicle_no)
    select auth.uid(), vehicle_no from profiles where id = auth.uid()
    returning id into v_load;
  end if;

  insert into bills (lead_id, load_id) values (p_lead_id, v_load) returning id into v_bill;
  update leads set status = 'in_progress' where id = p_lead_id;
  return v_bill;
end $$;

drop function if exists public.my_leads();
create function public.my_leads()
returns table (lead_id integer, lead_code text, slot timestamptz, status text, items_said text, customer_name text, address text, area text,
               upi_masked text, bill_id integer, bill_no text, bill_status text, total_kg numeric, total_amount numeric, payment_method text,
               latitude numeric, longitude numeric, phone text, fail_reason text, fail_note text, failed_at timestamptz)
language sql stable security definer set search_path to 'public'
as $$
  select l.id, l.code, l.slot, l.status, l.items_said,
         c.name, c.address, c.area,
         case when c.upi_id is null then null
              else left(c.upi_id, 3) || '••••' || substring(c.upi_id from position('@' in c.upi_id)) end,
         b.id, b.bill_no, b.status, bt.total_kg, bt.total_amount, b.payment_method,
         l.latitude, l.longitude, c.phone, l.fail_reason, l.fail_note, l.failed_at
  from leads l
  join customers c on c.id = l.customer_id
  left join bills b on b.lead_id = l.id
  left join bill_totals bt on bt.bill_id = b.id
  where l.driver_id = auth.uid() and l.status not in ('cancelled', 'unassigned')
  order by l.status in ('closed', 'failed'), l.slot nulls last, l.id
$$;

drop function if exists public.hq_leads(date, date, text, uuid, text, integer, integer);
create function public.hq_leads(p_from date, p_to date, p_status text default null, p_driver uuid default null, p_search text default null,
                                p_limit integer default 300, p_franchise integer default null)
returns table (lead_id integer, code text, customer_name text, phone text, address text, area text, driver_id uuid, driver_name text, slot timestamptz,
               status text, items_said text, bill_no text, bill_status text, created_at timestamptz, closed_at timestamptz, franchise_code text,
               fail_reason text, fail_note text, failed_at timestamptz, latitude numeric, longitude numeric)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  return query
  select l.id, l.code, cu.name, cu.phone, cu.address, cu.area, l.driver_id, pr.full_name, l.slot, l.status, l.items_said,
         b.bill_no, b.status, l.created_at, l.closed_at, fr.code, l.fail_reason, l.fail_note, l.failed_at, l.latitude, l.longitude
  from leads l
  join customers cu on cu.id = l.customer_id
  join franchises fr on fr.id = l.franchise_id
  left join profiles pr on pr.id = l.driver_id
  left join bills b on b.lead_id = l.id
  where ((l.slot at time zone 'Asia/Kolkata')::date between p_from and p_to or (l.status in ('unassigned','scheduled','in_progress','failed') and p_status is not null))
    and (p_franchise is null or l.franchise_id = p_franchise)
    and (p_status is null or l.status = p_status)
    and (p_driver is null or l.driver_id = p_driver)
    and (p_search is null or btrim(p_search) = '' or cu.name ilike '%' || btrim(p_search) || '%' or cu.phone ilike '%' || btrim(p_search) || '%'
         or l.code ilike '%' || btrim(p_search) || '%' or coalesce(cu.area, '') ilike '%' || btrim(p_search) || '%')
  order by l.slot desc nulls last, l.id desc
  limit greatest(least(p_limit, 500), 1);
end $$;
revoke all on function public.hq_leads(date, date, text, uuid, text, integer, integer) from public, anon;
grant execute on function public.hq_leads(date, date, text, uuid, text, integer, integer) to authenticated;

create or replace function public.hq_reassign_lead(p_lead_id integer, p_driver_id uuid)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_lead leads; v_name text; v_nf integer;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_lead from leads where id = p_lead_id for update;
  if v_lead.id is null then raise exception 'Lead not found.'; end if;
  if v_lead.status not in ('unassigned', 'scheduled', 'failed') then raise exception 'Only a lead that has not been started can be assigned (this one is %).', v_lead.status; end if;
  select full_name, franchise_id into v_name, v_nf from profiles where id = p_driver_id and role = 'driver' and active;
  if v_name is null then raise exception 'Choose an active driver.'; end if;
  if v_lead.driver_id = p_driver_id and v_lead.status = 'scheduled' then raise exception 'This lead is already with %.', v_name; end if;
  update leads set driver_id = p_driver_id, franchise_id = v_nf, status = 'scheduled', fail_reason = null, fail_note = null, failed_at = null where id = p_lead_id;
  perform public.hq_log('lead_reassigned', v_lead.code,
    jsonb_build_object('from', v_lead.driver_id, 'to', p_driver_id, 'from_franchise', v_lead.franchise_id, 'to_franchise', v_nf, 'was', v_lead.status), v_nf);
  return v_name;
end $$;

create or replace function public.hq_cancel_lead(p_lead_id integer, p_reason text)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_lead leads;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if p_reason is null or length(btrim(p_reason)) = 0 then raise exception 'Add a reason for cancelling.'; end if;
  select * into v_lead from leads where id = p_lead_id for update;
  if v_lead.id is null then raise exception 'Lead not found.'; end if;
  if v_lead.status not in ('unassigned', 'scheduled', 'failed') then raise exception 'Only a lead that has not been started can be cancelled (this one is %).', v_lead.status; end if;
  update leads set status = 'cancelled' where id = p_lead_id;
  perform public.hq_log('lead_cancelled', v_lead.code, jsonb_build_object('reason', btrim(p_reason), 'was', v_lead.status), v_lead.franchise_id);
  return v_lead.code;
end $$;

revoke all on function public.wh_leads(date, date, text, uuid, text, integer, integer) from public, anon;
revoke all on function public.wh_lead_counts(integer) from public, anon;
revoke all on function public.wh_driver_workload(date, integer) from public, anon;
revoke all on function public.wh_assign_leads(integer[], uuid) from public, anon;
revoke all on function public.wh_split_leads(integer[], uuid[]) from public, anon;
revoke all on function public.fail_pickup(integer, text, text) from public, anon;
grant execute on function public.wh_leads(date, date, text, uuid, text, integer, integer) to authenticated;
grant execute on function public.wh_lead_counts(integer) to authenticated;
grant execute on function public.wh_driver_workload(date, integer) to authenticated;
grant execute on function public.wh_assign_leads(integer[], uuid) to authenticated;
grant execute on function public.wh_split_leads(integer[], uuid[]) to authenticated;
grant execute on function public.fail_pickup(integer, text, text) to authenticated;
revoke all on function public.my_leads() from public, anon;
grant execute on function public.my_leads() to authenticated;
revoke all on function public.hq_reassign_lead(integer, uuid) from public, anon;
revoke all on function public.hq_cancel_lead(integer, text) from public, anon;
grant execute on function public.hq_reassign_lead(integer, uuid) to authenticated;
grant execute on function public.hq_cancel_lead(integer, text) to authenticated;

/* the overview counts the new states (the rest of hq_overview is unchanged from step 12) */
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
    'leads_unassigned',  (select count(*) from leads where status = 'unassigned' and (f is null or franchise_id = f)),
    'leads_failed',      (select count(*) from leads where status = 'failed' and (failed_at at time zone 'Asia/Kolkata')::date between p_from and p_to and (f is null or franchise_id = f)),
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
