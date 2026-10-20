/* =====================================================================
   STEP 13 · customer location on leads (latitude / longitude)
   Leads can now carry the customer's map position. The upload file gets two
   optional columns, latitude and longitude. Collectors see an
   "Open in Google Maps" button on the lead. Existing leads have no location
   and keep working. Nothing is deleted or changed in old rows.
   ===================================================================== */

alter table public.leads add column if not exists latitude numeric(9,6), add column if not exists longitude numeric(9,6);
alter table public.leads drop constraint if exists leads_location_check;
alter table public.leads add constraint leads_location_check check (
  (latitude is null and longitude is null) or (latitude between -90 and 90 and longitude between -180 and 180));
alter table public.lead_import add column if not exists latitude text, add column if not exists longitude text;

create or replace function public.process_lead_import()
returns trigger
language plpgsql
security definer set search_path to 'public'
as $$
declare
  v_phone text; v_driver uuid; v_driver_active boolean; v_cust int; v_date date; v_time time;
  v_slot timestamptz; v_t text; v_ampm text; v_h int; v_m int; v_code text;
  v_lat numeric; v_lng numeric; v_la text; v_ln text;
begin
  if new.status <> 'new' then return new; end if;
  /* completely blank rows (e.g. empty lines from an Excel CSV export) are skipped */
  if coalesce(trim(new.customer_name), '') = '' and coalesce(trim(new.phone), '') = '' and coalesce(trim(new.address), '') = ''
     and coalesce(trim(new.driver_email), '') = '' and coalesce(trim(new.pickup_date), '') = '' then
    return null;
  end if;

  begin
    if coalesce(trim(new.customer_name), '') = '' then raise exception 'Customer name is missing'; end if;
    if coalesce(trim(new.address), '') = '' then raise exception 'Address is missing'; end if;

    v_phone := regexp_replace(coalesce(new.phone, ''), '\D', '', 'g');
    if length(v_phone) > 10 then v_phone := right(v_phone, 10); end if;
    if length(v_phone) <> 10 then raise exception 'Phone must have 10 digits (got "%")', coalesce(new.phone, ''); end if;

    select p.id, p.active into v_driver, v_driver_active
    from auth.users u join profiles p on p.id = u.id and p.role = 'driver'
    where lower(u.email) = lower(trim(coalesce(new.driver_email, '')));
    if v_driver is null then raise exception 'No driver with email "%"', coalesce(new.driver_email, ''); end if;
    if not v_driver_active then raise exception 'Driver % is inactive', new.driver_email; end if;

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

    /* location is optional; if given it must be a real position. "10.0159, 76.3419" pasted into the latitude cell alone also works */
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
    where customer_id = v_cust and status in ('scheduled', 'in_progress')
      and (slot at time zone 'Asia/Kolkata')::date = v_date
    limit 1;
    if v_code is not null then
      new.status := 'duplicate'; new.lead_code := v_code;
      new.message := 'Lead already exists for this customer on this day';
      return new;
    end if;

    insert into leads (customer_id, driver_id, slot, items_said, created_by, latitude, longitude)
    values (v_cust, v_driver, v_slot, nullif(trim(new.items), ''), auth.uid(), v_lat, v_lng)
    returning code into v_code;

    new.status := 'created'; new.lead_code := v_code;
    new.message := case when trim(coalesce(new.pickup_time, '')) = '' then 'Created (no time given, set to 9:00 AM)' else 'Created' end
                   || case when v_lat is null then ' (no map location)' else '' end;
  exception when others then
    new.status := 'error'; new.message := sqlerrm;
  end;
  return new;
end $$;

/* the collector's lead list now also returns the location */
drop function if exists public.my_leads();
create function public.my_leads()
returns table (lead_id integer, lead_code text, slot timestamptz, status text, items_said text, customer_name text, address text, area text,
               upi_masked text, bill_id integer, bill_no text, bill_status text, total_kg numeric, total_amount numeric, payment_method text,
               latitude numeric, longitude numeric)
language sql stable security definer set search_path to 'public'
as $$
  select l.id, l.code, l.slot, l.status, l.items_said,
         c.name, c.address, c.area,
         case when c.upi_id is null then null
              else left(c.upi_id, 3) || '••••' || substring(c.upi_id from position('@' in c.upi_id)) end,
         b.id, b.bill_no, b.status, bt.total_kg, bt.total_amount, b.payment_method,
         l.latitude, l.longitude
  from leads l
  join customers c on c.id = l.customer_id
  left join bills b on b.lead_id = l.id
  left join bill_totals bt on bt.bill_id = b.id
  where l.driver_id = auth.uid() and l.status <> 'cancelled'
  order by l.status = 'closed', l.slot nulls last, l.id
$$;
revoke all on function public.my_leads() from public, anon;
grant execute on function public.my_leads() to authenticated;
