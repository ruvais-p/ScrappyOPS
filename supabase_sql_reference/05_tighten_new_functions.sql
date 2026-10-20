/* =====================================================================
   WAREHOUSE BACKEND · STEP 5 · tidy-up (already applied as wh_05)
   Trigger functions cannot be called through the API, and the tolerance
   function gets a fixed search path.
   ===================================================================== */
revoke all on function public.guard_release_stock() from public, anon, authenticated;
revoke all on function public.guard_weighings() from public, anon, authenticated;
revoke all on function public.guard_releases_readonly() from public, anon, authenticated;
revoke all on function public.guard_settlements() from public, anon, authenticated;
alter function public.wh_tolerance_pct() set search_path to 'public';
