/* =====================================================================
   HQ STEP 11 · add, remove and restore materials (scrap items)
   Needs step 10. HQ only. Nothing is ever deleted: "remove" switches a
   material off so drivers can no longer pick it, and past bills, weighings
   and stock history keep working. A removed material can be restored.
   A material cannot be removed while it is still in use:
     - stock of it is held at any franchise
     - an open or partly released HQ requirement asks for it
     - a load that is on the road, waiting for weighing or flagged contains it
   ===================================================================== */

create or replace function public.hq_add_item(p_name text, p_rate numeric)
returns integer language plpgsql security definer set search_path to 'public'
as $$
declare v_name text := regexp_replace(btrim(coalesce(p_name, '')), '\s+', ' ', 'g'); v_id integer; v_dup scrap_items;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  if length(v_name) < 2 or length(v_name) > 30 then raise exception 'The name must be 2 to 30 characters.'; end if;
  if v_name !~ '^[A-Za-z0-9][A-Za-z0-9 &/().,+-]*$' then raise exception 'Use letters, numbers and spaces in the name.'; end if;
  if p_rate is null or p_rate <= 0 or p_rate > 100000 then raise exception 'Enter a rate between 0 and 100000 per kg.'; end if;
  select * into v_dup from scrap_items where lower(name) = lower(v_name);
  if v_dup.id is not null then
    if v_dup.active then raise exception '% already exists.', v_dup.name; end if;
    raise exception '% was removed earlier. Restore it instead of adding it again.', v_dup.name;
  end if;
  insert into scrap_items (name, active) values (v_name, true) returning id into v_id;
  insert into rates (item_id, rate_per_kg, set_by) values (v_id, p_rate, auth.uid());
  perform public.hq_log('item_added', v_name, jsonb_build_object('rate', p_rate));
  return v_id;
end $$;

create or replace function public.hq_set_item_active(p_item_id integer, p_active boolean)
returns text language plpgsql security definer set search_path to 'public'
as $$
declare v_item scrap_items; v_n numeric; v_code text;
begin
  if my_role() <> 'hq' then raise exception 'HQ only.'; end if;
  select * into v_item from scrap_items where id = p_item_id for update;
  if v_item.id is null then raise exception 'Material not found.'; end if;
  if v_item.active = p_active then raise exception '% is already %.', v_item.name, case when p_active then 'active' else 'removed' end; end if;

  if not p_active then
    if (select count(*) from scrap_items where active) <= 1 then raise exception 'You cannot remove the last material.'; end if;
    v_n := public.wh_stock_kg(p_item_id, null);
    if v_n > 0.0001 then raise exception 'There is still % kg of % in the yards. Release it to HQ first.', round(v_n, 1), v_item.name; end if;
    select string_agg(code, ', ') into v_code from hq_requirement_progress where item_id = p_item_id and status in ('open','partial');
    if v_code is not null then raise exception 'HQ requirement % still asks for %. Cancel it first.', v_code, v_item.name; end if;
    select string_agg(distinct l.code, ', ') into v_code
      from bill_items bi join bills b on b.id = bi.bill_id join loads l on l.id = b.load_id
     where bi.item_id = p_item_id and l.status in ('open','submitted','flagged');
    if v_code is not null then raise exception '% is in loads that are not finished yet (%). Try again after they are weighed.', v_item.name, v_code; end if;
  else
    if not exists (select 1 from rates where item_id = p_item_id) then raise exception 'This material has no rate. Add it again with a rate.'; end if;
  end if;

  update scrap_items set active = p_active where id = p_item_id;
  perform public.hq_log(case when p_active then 'item_restored' else 'item_removed' end, v_item.name, '{}'::jsonb);
  return v_item.name;
end $$;

revoke all on function public.hq_add_item(text, numeric) from public, anon;
revoke all on function public.hq_set_item_active(integer, boolean) from public, anon;
grant execute on function public.hq_add_item(text, numeric) to authenticated;
grant execute on function public.hq_set_item_active(integer, boolean) to authenticated;
