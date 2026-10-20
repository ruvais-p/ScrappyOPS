/* =====================================================================
   WAREHOUSE BACKEND · STEP 1 OF 4 · supervisor role and read access
   Project: suluhhbomiuwwocrfpxg
   WARNING: this step replaces one check constraint (profiles_role_check)
   so that 'supervisor' becomes a valid role. The Supabase connector
   treats that as a destructive statement and may ask for approval.
   ===================================================================== */

/* 1. allow a supervisor role (driver, hq, warehouse stay as they are) */
alter table public.profiles drop constraint profiles_role_check;
alter table public.profiles add constraint profiles_role_check
  check (role = any (array['driver','hq','warehouse','supervisor']));

/* 2. supervisors can read what warehouse staff can already read */
alter policy loads_read on public.loads
  using ((driver_id = auth.uid()) or (public.my_role() = any (array['hq','warehouse','supervisor'])));
alter policy cash_read on public.cash_ledger
  using ((driver_id = auth.uid()) or (public.my_role() = any (array['hq','warehouse','supervisor'])));
alter policy profiles_read on public.profiles
  using ((id = auth.uid()) or (public.my_role() = any (array['hq','warehouse','supervisor'])));
alter policy leads_read on public.leads
  using ((driver_id = auth.uid()) or (public.my_role() = any (array['hq','warehouse','supervisor'])));

/* 3. helper: is the caller warehouse-side staff (hq, warehouse or supervisor) */
create or replace function public.is_wh_staff()
returns boolean
language sql stable security definer set search_path to 'public'
as $$ select coalesce(public.my_role() in ('hq','warehouse','supervisor'), false) $$;

revoke all on function public.is_wh_staff() from public, anon;
grant execute on function public.is_wh_staff() to authenticated;
