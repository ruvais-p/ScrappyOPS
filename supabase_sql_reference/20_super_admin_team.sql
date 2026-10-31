/* Super Admin team management.
   Adds the Team screen's narrowly scoped read/update permissions without granting
   the Super Admin access to other operational HQ actions. */

drop function if exists public.hq_team(integer);
create function public.hq_team(p_franchise integer default null)
returns table (id uuid, full_name text, email text, role text, phone text, territory text, vehicle_no text, active boolean,
               cash_in_hand numeric, open_leads bigint, franchise_id integer, franchise_code text, franchise_name text,
               source text, business_name text, address text)
language plpgsql stable security definer set search_path to 'public'
as $$
#variable_conflict use_column
begin
  if my_role() not in ('hq', 'super_admin') then raise exception 'HQ or Super Admin access is required.'; end if;
  return query
  select p.id, p.full_name, u.email::text, p.role, p.phone, p.territory, p.vehicle_no, p.active,
         (select coalesce(sum(c.amount), 0) from cash_ledger c where c.driver_id = p.id),
         (select count(*) from leads l where l.driver_id = p.id and l.status in ('scheduled','in_progress')),
         p.franchise_id, fr.code, fr.name, 'scrap'::text, null::text, null::text
  from profiles p left join auth.users u on u.id = p.id left join franchises fr on fr.id = p.franchise_id
  where (p_franchise is null or p.franchise_id = p_franchise or p.role = 'hq')
    and p.role <> 'super_admin'
  union all
  select p.id, p.full_name, coalesce(u.email, p.email)::text, p.role, p.phone,
         coalesce(ff.territory, string_agg(distinct d.name, ', ' order by d.name))::text,
         null::text, p.is_active, 0::numeric, 0::bigint, null::integer, null::text, null::text,
         'kwd'::text, ff.business_name, ff.address
  from kwd_profiles p
  left join auth.users u on u.id = p.id
  left join kwd_fr_franchises ff on ff.user_id = p.id
  left join kwd_user_districts ud on ud.user_id = p.id
  left join kwd_districts d on d.id = ud.district_id
  group by p.id, p.full_name, u.email, p.email, p.role, p.phone, p.is_active,
           ff.territory, ff.business_name, ff.address
  order by source, role, full_name;
end $$;

create or replace function public.hq_update_kwd_profile(p_id uuid, p_full_name text, p_phone text, p_active boolean)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_old kwd_profiles;
begin
  if my_role() <> 'super_admin' then raise exception 'Super Admin access is required.'; end if;
  select * into v_old from kwd_profiles where id = p_id for update;
  if v_old.id is null then raise exception 'KWD member not found.'; end if;
  if p_full_name is null or length(btrim(p_full_name)) = 0 then raise exception 'Enter a name.'; end if;
  update kwd_profiles set full_name = btrim(p_full_name), phone = nullif(btrim(coalesce(p_phone, '')), ''), is_active = p_active where id = p_id;
  update auth.users set banned_until = case when p_active then null else 'infinity'::timestamptz end where id = p_id;
  perform public.hq_log('kwd_profile_updated', v_old.full_name,
    jsonb_build_object('id', p_id, 'role', v_old.role, 'was_active', v_old.is_active, 'now_active', p_active), null);
  return btrim(p_full_name);
end $$;

create or replace function public.hq_update_profile(p_id uuid, p_full_name text, p_phone text, p_territory text, p_vehicle_no text, p_active boolean, p_franchise integer default null)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_old profiles; v_new_f integer;
begin
  if my_role() not in ('hq', 'super_admin') then raise exception 'HQ or Super Admin access is required.'; end if;
  select * into v_old from profiles where id = p_id for update;
  if v_old.id is null then raise exception 'Person not found.'; end if;
  if v_old.role = 'super_admin' or v_old.is_super_admin then raise exception 'Super Admin accounts cannot be edited here.'; end if;
  if p_full_name is null or length(btrim(p_full_name)) = 0 then raise exception 'Enter a name.'; end if;
  if p_id = auth.uid() and not p_active then raise exception 'You cannot deactivate your own login.'; end if;
  v_new_f := case when v_old.role = 'hq' then null else coalesce(p_franchise, v_old.franchise_id) end;
  if v_old.role <> 'hq' and not exists (select 1 from franchises where id = v_new_f and (active or v_new_f = v_old.franchise_id)) then raise exception 'Choose an active franchise.'; end if;
  if v_old.role = 'driver' and (v_old.active and not p_active or v_new_f is distinct from v_old.franchise_id) then
    if exists (select 1 from loads where driver_id = p_id and status = 'open') then raise exception 'This driver has a route on the road. Do this after the route ends.'; end if;
    if exists (select 1 from leads where driver_id = p_id and status in ('scheduled','in_progress')) then raise exception 'Reassign this driver''s open leads first.'; end if;
  end if;
  if v_old.role = 'driver' and v_new_f is distinct from v_old.franchise_id and
     exists (select 1 from cash_ledger where driver_id = p_id group by driver_id having sum(amount) <> 0)
  then raise exception 'This driver still holds cash. Count it before moving the driver to another franchise.'; end if;
  update profiles set full_name = btrim(p_full_name), phone = nullif(btrim(coalesce(p_phone, '')), ''),
         territory = nullif(btrim(coalesce(p_territory, '')), ''), vehicle_no = nullif(btrim(coalesce(p_vehicle_no, '')), ''),
         active = p_active, franchise_id = v_new_f where id = p_id;
  perform public.hq_log('profile_updated', v_old.full_name,
    jsonb_build_object('id', p_id, 'was_active', v_old.active, 'now_active', p_active,
                       'from_franchise', v_old.franchise_id, 'to_franchise', v_new_f), v_new_f);
  return btrim(p_full_name);
end $$;

revoke all on function public.hq_team(integer) from public, anon;
revoke all on function public.hq_update_profile(uuid, text, text, text, text, boolean, integer) from public, anon;
revoke all on function public.hq_update_kwd_profile(uuid, text, text, boolean) from public, anon;
grant execute on function public.hq_team(integer) to authenticated;
grant execute on function public.hq_update_profile(uuid, text, text, text, text, boolean, integer) to authenticated;
grant execute on function public.hq_update_kwd_profile(uuid, text, text, boolean) to authenticated;

alter policy franchises_read on public.franchises using (
  (select public.my_role()) in ('hq', 'super_admin') or id = (select public.my_franchise()));
