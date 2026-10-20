/* =====================================================================
   WAREHOUSE BACKEND · STEP 2 OF 4 · tables, row access, fraud guards
   Needs step 1 first (uses is_wh_staff).
   Nothing here drops or deletes anything.
   ===================================================================== */

/* ---------- extra columns on loads (all optional, driver app unaffected) ---------- */
alter table public.loads
  add column if not exists weighed_at timestamptz,
  add column if not exists weighing_note text,
  add column if not exists resolved_by uuid references public.profiles(id),
  add column if not exists resolved_at timestamptz,
  add column if not exists resolution_note text;

create sequence if not exists public.requirement_code_seq;
create sequence if not exists public.release_code_seq start 301;

/* ---------- per-material weighing (history is kept; current rows have superseded_at null) ---------- */
create table if not exists public.load_weighings (
  id bigint generated always as identity primary key,
  load_id integer not null references public.loads(id),
  item_id integer not null references public.scrap_items(id),
  billed_kg numeric not null check (billed_kg >= 0),
  warehouse_kg numeric not null check (warehouse_kg >= 0),
  within_tolerance boolean not null,
  weighed_by uuid not null references public.profiles(id),
  weighed_at timestamptz not null default now(),
  superseded_at timestamptz
);
create unique index if not exists load_weighings_current_uq on public.load_weighings (load_id, item_id) where superseded_at is null;
create index if not exists load_weighings_item_idx on public.load_weighings (item_id);

/* ---------- what HQ asks the warehouse to supply ---------- */
create table if not exists public.hq_requirements (
  id integer generated always as identity primary key,
  code text not null unique default ('RQ-' || lpad(nextval('public.requirement_code_seq')::text, 4, '0')),
  item_id integer not null references public.scrap_items(id),
  required_kg numeric not null check (required_kg > 0),
  due_date date,
  note text,
  status text not null default 'open' check (status in ('open','cancelled')),
  raised_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  cancelled_at timestamptz,
  cancel_note text
);

/* ---------- stock released to HQ against a requirement (append only) ---------- */
create table if not exists public.hq_releases (
  id integer generated always as identity primary key,
  code text not null unique default ('RL-' || lpad(nextval('public.release_code_seq')::text, 4, '0')),
  requirement_id integer not null references public.hq_requirements(id),
  item_id integer not null references public.scrap_items(id),
  kg numeric not null check (kg > 0),
  vehicle_no text not null check (length(btrim(vehicle_no)) > 0),
  note text,
  released_by uuid not null references public.profiles(id),
  released_at timestamptz not null default now()
);
create index if not exists hq_releases_req_idx on public.hq_releases (requirement_id);
create index if not exists hq_releases_item_idx on public.hq_releases (item_id);

/* ---------- end-of-route cash count and supervisor verification ---------- */
create table if not exists public.cash_settlements (
  id integer generated always as identity primary key,
  load_id integer not null unique references public.loads(id),
  driver_id uuid not null references public.profiles(id),
  expected_cash numeric not null check (expected_cash >= 0),
  counted_cash numeric not null check (counted_cash >= 0),
  difference numeric generated always as (counted_cash - expected_cash) stored,
  cash_paid numeric not null default 0,
  upi_paid numeric not null default 0,
  status text not null default 'counted' check (status in ('counted','verified','disputed')),
  counted_by uuid not null references public.profiles(id),
  counted_at timestamptz not null default now(),
  count_note text,
  verified_by uuid references public.profiles(id),
  verified_at timestamptz,
  verify_note text,
  constraint settle_two_people check (verified_by is null or verified_by <> counted_by)
);
create index if not exists cash_settlements_driver_idx on public.cash_settlements (driver_id);

/* ---------- row access: read only. All writing goes through the functions in step 3 ---------- */
alter table public.load_weighings enable row level security;
alter table public.hq_requirements enable row level security;
alter table public.hq_releases enable row level security;
alter table public.cash_settlements enable row level security;

create policy load_weighings_read on public.load_weighings for select to authenticated
  using ((select public.is_wh_staff()) or exists (select 1 from public.loads l where l.id = load_id and l.driver_id = auth.uid()));
create policy hq_requirements_read on public.hq_requirements for select to authenticated
  using ((select public.is_wh_staff()));
create policy hq_releases_read on public.hq_releases for select to authenticated
  using ((select public.is_wh_staff()));
create policy cash_settlements_read on public.cash_settlements for select to authenticated
  using ((select public.is_wh_staff()) or driver_id = auth.uid());

revoke all on public.load_weighings, public.hq_requirements, public.hq_releases, public.cash_settlements from anon;
revoke insert, update, delete, truncate on public.load_weighings, public.hq_requirements, public.hq_releases, public.cash_settlements from authenticated;

/* ---------- stock in the yard for one material (internal helper, not callable by users) ---------- */
create or replace function public.wh_stock_kg(p_item_id integer)
returns numeric
language sql stable security definer set search_path to 'public'
as $$
  select coalesce((select sum(w.warehouse_kg) from public.load_weighings w join public.loads l on l.id = w.load_id
                   where w.item_id = p_item_id and w.superseded_at is null and l.status in ('reconciled','flagged')), 0)
       - coalesce((select sum(kg) from public.hq_releases where item_id = p_item_id), 0)
$$;
revoke all on function public.wh_stock_kg(integer) from public, anon, authenticated;

/* ---------- fraud guard 1: weighings can never be edited or deleted, only marked superseded ---------- */
create or replace function public.guard_weighings()
returns trigger language plpgsql set search_path to 'public'
as $$
begin
  if tg_op = 'DELETE' then raise exception 'Weighing records cannot be deleted.'; end if;
  if old.superseded_at is not null or new.superseded_at is null
     or (new.load_id, new.item_id, new.billed_kg, new.warehouse_kg, new.within_tolerance, new.weighed_by, new.weighed_at)
        is distinct from
        (old.load_id, old.item_id, old.billed_kg, old.warehouse_kg, old.within_tolerance, old.weighed_by, old.weighed_at)
  then raise exception 'Weighing records cannot be edited. Re-weigh the load instead.'; end if;
  return new;
end $$;
create trigger load_weighings_guard before update or delete on public.load_weighings
  for each row execute function public.guard_weighings();

/* ---------- fraud guard 2: releases are append only, and can never exceed stock or what HQ asked for ---------- */
create or replace function public.guard_releases_readonly()
returns trigger language plpgsql set search_path to 'public'
as $$
begin
  raise exception 'Releases to HQ cannot be changed. Ask HQ to raise a correction.';
end $$;
create trigger hq_releases_readonly before update or delete on public.hq_releases
  for each row execute function public.guard_releases_readonly();

create or replace function public.guard_release_stock()
returns trigger language plpgsql security definer set search_path to 'public'
as $$
declare v_item integer; v_status text; v_req numeric; v_done numeric; v_stock numeric;
begin
  perform 1 from public.scrap_items where id = new.item_id for update;   /* one release per material at a time */
  select item_id, status, required_kg into v_item, v_status, v_req from public.hq_requirements where id = new.requirement_id;
  if v_item is null then raise exception 'Requirement not found.'; end if;
  if v_item <> new.item_id then raise exception 'This release is for a different material than the request.'; end if;
  if v_status <> 'open' then raise exception 'This request has been cancelled.'; end if;
  select coalesce(sum(kg), 0) into v_done from public.hq_releases where requirement_id = new.requirement_id;
  if new.kg > (v_req - v_done) + 0.0001 then
    raise exception 'HQ only needs % kg more for this request.', round(v_req - v_done, 1);
  end if;
  v_stock := public.wh_stock_kg(new.item_id);
  if new.kg > v_stock + 0.0001 then
    raise exception 'Not enough stock. In the yard: % kg.', round(v_stock, 1);
  end if;
  return new;
end $$;
create trigger hq_releases_stock_guard before insert on public.hq_releases
  for each row execute function public.guard_release_stock();

/* ---------- fraud guard 3: a counted settlement can only move to verified or disputed, never be re-counted ---------- */
create or replace function public.guard_settlements()
returns trigger language plpgsql set search_path to 'public'
as $$
begin
  if tg_op = 'DELETE' then raise exception 'Cash settlements cannot be deleted.'; end if;
  if old.status <> 'counted' then raise exception 'This settlement is final.'; end if;
  if (new.load_id, new.driver_id, new.expected_cash, new.counted_cash, new.cash_paid, new.upi_paid, new.counted_by, new.counted_at, new.count_note)
     is distinct from
     (old.load_id, old.driver_id, old.expected_cash, old.counted_cash, old.cash_paid, old.upi_paid, old.counted_by, old.counted_at, old.count_note)
  then raise exception 'Counted amounts cannot be changed.'; end if;
  return new;
end $$;
create trigger cash_settlements_guard before update or delete on public.cash_settlements
  for each row execute function public.guard_settlements();
