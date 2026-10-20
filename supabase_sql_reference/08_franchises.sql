/* =====================================================================
   FRANCHISE STEP 8 · franchises, who belongs where, row access
   Needs steps 1 to 7. Everything that exists today becomes franchise KKD (Kakkanad).
   Nothing here drops or deletes anything.
   Rules after this step:
     - every driver, warehouse and supervisor login belongs to ONE franchise
     - HQ belongs to none and sees all
     - staff of a franchise can read only that franchise's rows (the database enforces it)
   ===================================================================== */

create table if not exists public.franchises (
  id integer generated always as identity primary key,
  code text not null unique check (code ~ '^[A-Z0-9][A-Z0-9-]{1,11}$'),
  name text not null check (length(btrim(name)) > 0),
  district text,
  constituency text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.franchises enable row level security;
insert into public.franchises (code, name, district)
select 'KKD', 'Kakkanad', 'Ernakulam' where not exists (select 1 from public.franchises where code = 'KKD');

/* ---------- people: staff belong to one franchise, HQ to none ---------- */
alter table public.profiles add column if not exists franchise_id integer references public.franchises(id);
update public.profiles set franchise_id = (select id from public.franchises where code = 'KKD')
 where role <> 'hq' and franchise_id is null;
do $ begin
  if not exists (select 1 from pg_constraint where conname = 'profiles_franchise_check') then
    alter table public.profiles add constraint profiles_franchise_check check (role = 'hq' or franchise_id is not null);
  end if;
end $;

/* ---------- who is the caller, and which franchise ---------- */
create or replace function public.my_franchise()
returns integer language sql stable security definer set search_path to 'public'
as $$ select franchise_id from public.profiles where id = auth.uid() and active $$;

create or replace function public.fr_ok(p_f integer)
returns boolean language sql stable security definer set search_path to 'public'
as $$
  select case public.my_role()
    when 'hq' then true
    when 'warehouse' then p_f is not null and p_f = public.my_franchise()
    when 'supervisor' then p_f is not null and p_f = public.my_franchise()
    else false end
$$;

/* the franchise a report should cover: staff always get their own, HQ gets what it asked for (null = all) */
create or replace function public.fr_scope(p_f integer)
returns integer language plpgsql stable security definer set search_path to 'public'
as $$
declare r text := public.my_role(); f integer;
begin
  if r = 'hq' then return p_f; end if;
  if r in ('warehouse','supervisor') then
    f := public.my_franchise();
    if f is null then raise exception 'Your login is not assigned to a franchise.'; end if;
    return f;
  end if;
  raise exception 'Not allowed.';
end $$;

revoke all on function public.my_franchise() from public, anon;
revoke all on function public.fr_ok(integer) from public, anon;
revoke all on function public.fr_scope(integer) from public, anon;
grant execute on function public.my_franchise() to authenticated;
grant execute on function public.fr_ok(integer) to authenticated;
grant execute on function public.fr_scope(integer) to authenticated;

/* ---------- every business table carries its franchise ---------- */
do $$
declare v_kk integer; t text;
begin
  select id into v_kk from public.franchises where code = 'KKD';
  foreach t in array array['leads','loads','cash_ledger','load_weighings','cash_settlements','hq_requirements','hq_releases'] loop
    execute format('alter table public.%I add column if not exists franchise_id integer not null default %s references public.franchises(id)', t, v_kk);
    execute format('alter table public.%I alter column franchise_id drop default', t);
  end loop;
end $$;
alter table public.hq_audit add column if not exists franchise_id integer references public.franchises(id);

/* ---------- new rows pick up the franchise automatically ---------- */
create or replace function public.fr_from_driver()
returns trigger language plpgsql security definer set search_path to 'public'
as $$
begin
  select franchise_id into new.franchise_id from public.profiles where id = new.driver_id;
  if new.franchise_id is null then raise exception 'This person is not assigned to a franchise.'; end if;
  return new;
end $$;

create or replace function public.fr_from_load()
returns trigger language plpgsql security definer set search_path to 'public'
as $$
begin
  select franchise_id into new.franchise_id from public.loads where id = new.load_id;
  return new;
end $$;

create or replace function public.fr_from_requirement()
returns trigger language plpgsql security definer set search_path to 'public'
as $$
begin
  select franchise_id into new.franchise_id from public.hq_requirements where id = new.requirement_id;
  return new;
end $$;
revoke all on function public.fr_from_driver() from public, anon, authenticated;
revoke all on function public.fr_from_load() from public, anon, authenticated;
revoke all on function public.fr_from_requirement() from public, anon, authenticated;

create trigger leads_a_franchise before insert on public.leads for each row execute function public.fr_from_driver();
create trigger loads_a_franchise before insert on public.loads for each row execute function public.fr_from_driver();
create trigger cash_ledger_a_franchise before insert on public.cash_ledger for each row execute function public.fr_from_driver();
create trigger load_weighings_a_franchise before insert on public.load_weighings for each row execute function public.fr_from_load();
create trigger cash_settlements_a_franchise before insert on public.cash_settlements for each row execute function public.fr_from_load();
create trigger hq_releases_a_franchise before insert on public.hq_releases for each row execute function public.fr_from_requirement();

/* ---------- indexes, so 140 franchises stay fast ---------- */
create index if not exists profiles_franchise_idx on public.profiles (franchise_id);
create index if not exists leads_franchise_idx on public.leads (franchise_id, status);
create index if not exists leads_driver_idx on public.leads (driver_id);
create index if not exists loads_franchise_idx on public.loads (franchise_id, status);
create index if not exists loads_driver_idx on public.loads (driver_id, status);
create index if not exists bills_load_idx on public.bills (load_id);
create index if not exists bill_items_bill_idx on public.bill_items (bill_id);
create index if not exists cash_ledger_driver_idx on public.cash_ledger (driver_id);
create index if not exists cash_ledger_franchise_idx on public.cash_ledger (franchise_id);
create index if not exists load_weighings_load_idx on public.load_weighings (load_id);
create index if not exists load_weighings_franchise_idx on public.load_weighings (franchise_id);
create index if not exists cash_settlements_franchise_idx on public.cash_settlements (franchise_id);
create index if not exists hq_requirements_franchise_idx on public.hq_requirements (franchise_id, status);
create index if not exists hq_releases_franchise_idx on public.hq_releases (franchise_id);
create index if not exists hq_audit_franchise_idx on public.hq_audit (franchise_id);

/* ---------- row access: own rows, or own franchise for staff, or everything for HQ ---------- */
create policy franchises_read on public.franchises for select to authenticated
  using ((select public.my_role()) = 'hq' or id = (select public.my_franchise()));
revoke all on public.franchises from anon;
revoke insert, update, delete, truncate on public.franchises from authenticated;

alter policy loads_read on public.loads using (
  driver_id = auth.uid() or (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy leads_read on public.leads using (
  driver_id = auth.uid() or (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy cash_read on public.cash_ledger using (
  driver_id = auth.uid() or (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy profiles_read on public.profiles using (
  id = auth.uid() or role = 'hq' or (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy load_weighings_read on public.load_weighings using (
  (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise()))
  or exists (select 1 from public.loads l where l.id = load_id and l.driver_id = auth.uid()));
alter policy hq_requirements_read on public.hq_requirements using (
  (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy hq_releases_read on public.hq_releases using (
  (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy cash_settlements_read on public.cash_settlements using (
  driver_id = auth.uid() or (select public.my_role()) = 'hq'
  or ((select public.my_role()) in ('warehouse','supervisor') and franchise_id = (select public.my_franchise())));
alter policy settlement_resolutions_read on public.settlement_resolutions using (
  exists (select 1 from public.cash_settlements s where s.id = settlement_id));

/* ---------- views carry the franchise too ---------- */
create or replace view public.wh_stock_movements with (security_invoker = true) as
  select (w.weighed_at at time zone 'Asia/Kolkata')::date as day, 'received'::text as kind, w.item_id, i.name as item_name,
         w.warehouse_kg as kg, l.code as ref, w.weighed_at as happened_at, w.franchise_id
  from public.load_weighings w
  join public.loads l on l.id = w.load_id
  join public.scrap_items i on i.id = w.item_id
  where w.superseded_at is null and l.status in ('reconciled','flagged')
  union all
  select (r.released_at at time zone 'Asia/Kolkata')::date, 'released', r.item_id, i.name, r.kg, r.code, r.released_at, r.franchise_id
  from public.hq_releases r
  join public.scrap_items i on i.id = r.item_id;

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
            and q.due_date < (now() at time zone 'Asia/Kolkata')::date) as is_overdue,
         q.franchise_id
  from public.hq_requirements q
  join public.scrap_items i on i.id = q.item_id
  left join (select requirement_id, sum(kg) as kg from public.hq_releases group by requirement_id) r on r.requirement_id = q.id;

/* one row per paid bill with its franchise, driver and day (used for every total) */
create or replace view public.hq_paid_bills with (security_invoker = true) as
  select b.id as bill_id, lo.franchise_id, lo.driver_id, b.load_id, b.payment_method, b.paid_at,
         (b.paid_at at time zone 'Asia/Kolkata')::date as paid_day, b.created_at, bt.total_kg, bt.total_amount
  from public.bills b
  join public.loads lo on lo.id = b.load_id
  join public.bill_totals bt on bt.bill_id = b.id
  where b.status = 'paid';
revoke all on public.hq_paid_bills from anon;
grant select on public.hq_paid_bills to authenticated;
