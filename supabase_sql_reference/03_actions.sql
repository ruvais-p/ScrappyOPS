/* =====================================================================
   WAREHOUSE BACKEND · STEP 3 OF 4 · the actions the dashboard can call
   Needs steps 1 and 2 first.
   Every function checks the caller's role itself and is callable by
   logged-in users only (never by the public / anon key).
   ===================================================================== */

/* the weighing tolerance, in percent, per material. Change it here in one place. */
create or replace function public.wh_tolerance_pct()
returns numeric language sql immutable as $$ select 2::numeric $$;

/* ---------- 1. weigh a load, material by material ----------
   p_weights example: [{"item_id":1,"kg":41.5},{"item_id":2,"kg":12}]
   A material is OK when |weighed - billed| / billed <= 2%.
   If every material is OK the load becomes 'reconciled', otherwise 'flagged'.   */
create or replace function public.record_load_weighing(p_load_id integer, p_weights jsonb, p_note text default null)
returns jsonb
language plpgsql security definer set search_path to 'public'
as $$
declare
  v_load loads; r record; v_tol numeric := public.wh_tolerance_pct();
  v_all_ok boolean := true; v_ok boolean; v_tb numeric := 0; v_tw numeric := 0;
  v_out jsonb := '[]'::jsonb; v_missing text; v_status text;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can record weighing.'; end if;
  if jsonb_typeof(p_weights) is distinct from 'array' or jsonb_array_length(p_weights) = 0 then
    raise exception 'Send the weight of each material as a list.';
  end if;

  select * into v_load from loads where id = p_load_id for update;
  if v_load.id is null then raise exception 'Load not found.'; end if;
  if v_load.status <> 'submitted' then
    raise exception 'This load is not waiting for weighing (status: %).', v_load.status;
  end if;

  if (select count(*) from jsonb_array_elements(p_weights) x(j) join scrap_items i on i.id = (x.j->>'item_id')::int)
     <> jsonb_array_length(p_weights) then
    raise exception 'Unknown material in the list.';
  end if;
  if (select count(distinct (x.j->>'item_id')) from jsonb_array_elements(p_weights) x(j)) <> jsonb_array_length(p_weights) then
    raise exception 'Each material can be entered only once.';
  end if;

  select string_agg(i.name, ', ') into v_missing
  from (select bi.item_id from bills b join bill_items bi on bi.bill_id = b.id
        where b.load_id = p_load_id and b.status = 'paid' group by bi.item_id) bl
  join scrap_items i on i.id = bl.item_id
  where not exists (select 1 from jsonb_array_elements(p_weights) x(j) where (x.j->>'item_id')::int = bl.item_id);
  if v_missing is not null then raise exception 'Enter the weight for: %.', v_missing; end if;

  update load_weighings set superseded_at = now() where load_id = p_load_id and superseded_at is null;

  for r in
    select i.id as item_id, i.name, coalesce(bl.kg, 0) as billed, (x.j->>'kg')::numeric as w
    from jsonb_array_elements(p_weights) x(j)
    join scrap_items i on i.id = (x.j->>'item_id')::int
    left join (select bi.item_id, sum(bi.qty_kg) as kg from bills b join bill_items bi on bi.bill_id = b.id
               where b.load_id = p_load_id and b.status = 'paid' group by bi.item_id) bl on bl.item_id = i.id
    order by i.id
  loop
    if r.w is null or r.w < 0 or r.w > 100000 then
      raise exception 'The weight of % must be between 0 and 100000 kg.', r.name;
    end if;
    v_ok := case when r.billed > 0 then abs(r.w - r.billed) / r.billed <= v_tol / 100 else r.w = 0 end;
    v_all_ok := v_all_ok and v_ok;
    insert into load_weighings (load_id, item_id, billed_kg, warehouse_kg, within_tolerance, weighed_by)
    values (p_load_id, r.item_id, r.billed, r.w, v_ok, auth.uid());
    v_tb := v_tb + r.billed; v_tw := v_tw + r.w;
    v_out := v_out || jsonb_build_object('item', r.name, 'billed_kg', r.billed, 'warehouse_kg', r.w,
               'diff_pct', case when r.billed > 0 then round((r.w - r.billed) / r.billed * 100, 2) end, 'ok', v_ok);
  end loop;

  v_status := case when v_all_ok then 'reconciled' else 'flagged' end;
  update loads set warehouse_kg = v_tw, status = v_status, checked_by = auth.uid(),
         weighed_at = now(), weighing_note = p_note
  where id = p_load_id;

  return jsonb_build_object('status', v_status, 'billed_kg', v_tb, 'warehouse_kg', v_tw, 'tolerance_pct', v_tol, 'items', v_out);
end $$;

/* the old single-total function is switched off so it cannot bypass the per-material check */
create or replace function public.record_weighing(p_load_id integer, p_warehouse_kg numeric)
returns text
language plpgsql security definer set search_path to 'public'
as $$
begin
  raise exception 'Use record_load_weighing, which checks every material.';
end $$;

/* ---------- 2. HQ decides what happens to a flagged load ----------
   p_action 'accept'  : HQ accepts the difference, load becomes reconciled
   p_action 'reweigh' : load goes back to 'submitted' so it can be weighed again      */
create or replace function public.resolve_flagged_load(p_load_id integer, p_action text, p_note text)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_load loads; r record;
begin
  if my_role() <> 'hq' then raise exception 'Only HQ can resolve a flagged load.'; end if;
  if p_action not in ('accept','reweigh') then raise exception 'Action must be accept or reweigh.'; end if;
  if p_note is null or length(btrim(p_note)) = 0 then raise exception 'Add a note explaining the decision.'; end if;
  select * into v_load from loads where id = p_load_id for update;
  if v_load.id is null or v_load.status <> 'flagged' then raise exception 'This load is not flagged.'; end if;

  if p_action = 'accept' then
    update loads set status = 'reconciled', resolved_by = auth.uid(), resolved_at = now(), resolution_note = p_note where id = p_load_id;
    return 'reconciled';
  end if;

  for r in select item_id, warehouse_kg from load_weighings where load_id = p_load_id and superseded_at is null loop
    perform 1 from scrap_items where id = r.item_id for update;
    if public.wh_stock_kg(r.item_id) - r.warehouse_kg < 0 then
      raise exception 'Cannot re-weigh: stock from this load has already been released to HQ.';
    end if;
  end loop;
  update load_weighings set superseded_at = now() where load_id = p_load_id and superseded_at is null;
  update loads set status = 'submitted', warehouse_kg = null, checked_by = null, weighed_at = null,
         resolved_by = auth.uid(), resolved_at = now(), resolution_note = p_note where id = p_load_id;
  return 'submitted';
end $$;

/* ---------- 3. HQ requirements ---------- */
create or replace function public.raise_requirement(p_item_id integer, p_required_kg numeric, p_due_date date default null, p_note text default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_code text;
begin
  if my_role() <> 'hq' then raise exception 'Only HQ can raise a requirement.'; end if;
  if p_required_kg is null or p_required_kg <= 0 then raise exception 'Enter the kg HQ needs.'; end if;
  insert into hq_requirements (item_id, required_kg, due_date, note, raised_by)
  values (p_item_id, p_required_kg, p_due_date, p_note, auth.uid()) returning code into v_code;
  return v_code;
end $$;

create or replace function public.cancel_requirement(p_requirement_id integer, p_note text)
returns void
language plpgsql security definer set search_path to 'public'
as $$
begin
  if my_role() <> 'hq' then raise exception 'Only HQ can cancel a requirement.'; end if;
  if p_note is null or length(btrim(p_note)) = 0 then raise exception 'Add a reason for cancelling.'; end if;
  update hq_requirements set status = 'cancelled', cancelled_at = now(), cancel_note = p_note
  where id = p_requirement_id and status = 'open';
  if not found then raise exception 'Requirement not found or already cancelled.'; end if;
end $$;

/* ---------- 4. release stock to HQ (the trigger in step 2 checks stock and the remaining need) ---------- */
create or replace function public.release_to_hq(p_requirement_id integer, p_kg numeric, p_vehicle_no text, p_note text default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare v_item integer; v_code text;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can release stock.'; end if;
  select item_id into v_item from hq_requirements where id = p_requirement_id;
  if v_item is null then raise exception 'Requirement not found.'; end if;
  insert into hq_releases (requirement_id, item_id, kg, vehicle_no, note, released_by)
  values (p_requirement_id, v_item, p_kg, coalesce(p_vehicle_no, ''), p_note, auth.uid()) returning code into v_code;
  return v_code;
end $$;

/* ---------- 5. cash: issue float, count at end of route, supervisor verifies ---------- */
create or replace function public.issue_float(p_driver_id uuid, p_amount numeric, p_note text default null)
returns numeric
language plpgsql security definer set search_path to 'public'
as $$
declare v_bal numeric;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can issue float.'; end if;
  if p_amount is null or p_amount <= 0 or p_amount > 500000 then raise exception 'Enter an amount between 1 and 500000.'; end if;
  if not exists (select 1 from profiles where id = p_driver_id and role = 'driver' and active) then
    raise exception 'That is not an active driver.';
  end if;
  insert into cash_ledger (driver_id, entry_type, amount, note, created_by)
  values (p_driver_id, 'float_issued', p_amount, coalesce(p_note, 'Float issued at warehouse'), auth.uid());
  select coalesce(sum(amount), 0) into v_bal from cash_ledger where driver_id = p_driver_id;
  return v_bal;
end $$;

/* Count the cash a driver hands back after ending a route.
   Expected = the driver's ledger balance up to the moment the route was ended.
   The ledger gets a handover for the expected amount (so the driver's balance returns to zero);
   what was really counted and any shortage or surplus live in cash_settlements.        */
create or replace function public.count_route_cash(p_load_id integer, p_counted numeric, p_note text default null)
returns jsonb
language plpgsql security definer set search_path to 'public'
as $$
declare v_load loads; v_exp numeric; v_bal numeric; v_cash numeric; v_upi numeric; v_id integer;
begin
  if my_role() not in ('warehouse','hq') then raise exception 'Only warehouse staff can count cash.'; end if;
  if p_counted is null or p_counted < 0 or p_counted > 1000000 then raise exception 'Enter the cash you counted.'; end if;
  select * into v_load from loads where id = p_load_id for update;
  if v_load.id is null then raise exception 'Load not found.'; end if;
  if v_load.status = 'open' then raise exception 'The driver has not ended this route yet.'; end if;
  if exists (select 1 from cash_settlements where load_id = p_load_id) then raise exception 'Cash for this route was already counted.'; end if;
  if exists (select 1 from loads l where l.driver_id = v_load.driver_id and l.id < v_load.id and l.status <> 'open'
             and not exists (select 1 from cash_settlements s where s.load_id = l.id)) then
    raise exception 'Count this driver''s earlier route first.';
  end if;

  select greatest(coalesce(sum(amount), 0), 0) into v_exp from cash_ledger
  where driver_id = v_load.driver_id and created_at <= coalesce(v_load.submitted_at, now());
  select coalesce(sum(amount), 0) into v_bal from cash_ledger where driver_id = v_load.driver_id;
  if v_bal < v_exp then raise exception 'The driver has already spent cash on a newer route. Ask HQ to review the ledger.'; end if;
  if p_counted <> v_exp and (p_note is null or length(btrim(p_note)) = 0) then
    raise exception 'The count differs from the expected ₹%. Add a note.', v_exp;
  end if;

  select coalesce(sum(bi.amount) filter (where b.payment_method = 'cash'), 0),
         coalesce(sum(bi.amount) filter (where b.payment_method = 'upi'), 0)
    into v_cash, v_upi
  from bills b join bill_items bi on bi.bill_id = b.id where b.load_id = p_load_id and b.status = 'paid';

  insert into cash_settlements (load_id, driver_id, expected_cash, counted_cash, cash_paid, upi_paid, counted_by, count_note)
  values (p_load_id, v_load.driver_id, v_exp, p_counted, v_cash, v_upi, auth.uid(), p_note) returning id into v_id;

  if v_exp > 0 then
    insert into cash_ledger (driver_id, entry_type, amount, note, created_by)
    values (v_load.driver_id, 'handover', -v_exp,
            'Route ' || v_load.code || ': counted ₹' || p_counted || ', expected ₹' || v_exp, auth.uid());
  end if;
  return jsonb_build_object('settlement_id', v_id, 'expected', v_exp, 'counted', p_counted, 'difference', p_counted - v_exp, 'status', 'counted');
end $$;

/* A different person (supervisor, or HQ) verifies or disputes the count. */
create or replace function public.verify_settlement(p_settlement_id integer, p_decision text, p_note text default null)
returns text
language plpgsql security definer set search_path to 'public'
as $$
declare s cash_settlements;
begin
  if my_role() not in ('supervisor','hq') then raise exception 'Only a supervisor can verify cash.'; end if;
  if p_decision not in ('verify','dispute') then raise exception 'Decision must be verify or dispute.'; end if;
  select * into s from cash_settlements where id = p_settlement_id for update;
  if s.id is null then raise exception 'Settlement not found.'; end if;
  if s.status <> 'counted' then raise exception 'This settlement is already %.', s.status; end if;
  if s.counted_by = auth.uid() then raise exception 'The person who counted the cash cannot verify it.'; end if;
  if (s.difference <> 0 or p_decision = 'dispute') and (p_note is null or length(btrim(p_note)) = 0) then
    raise exception 'Add a note explaining the difference or the dispute.';
  end if;
  update cash_settlements
     set status = case p_decision when 'verify' then 'verified' else 'disputed' end,
         verified_by = auth.uid(), verified_at = now(), verify_note = p_note
   where id = p_settlement_id;
  return case p_decision when 'verify' then 'verified' else 'disputed' end;
end $$;

/* ---------- who may call what ---------- */
revoke all on function public.wh_tolerance_pct() from public, anon;
revoke all on function public.record_load_weighing(integer, jsonb, text) from public, anon;
revoke all on function public.record_weighing(integer, numeric) from public, anon;
revoke all on function public.resolve_flagged_load(integer, text, text) from public, anon;
revoke all on function public.raise_requirement(integer, numeric, date, text) from public, anon;
revoke all on function public.cancel_requirement(integer, text) from public, anon;
revoke all on function public.release_to_hq(integer, numeric, text, text) from public, anon;
revoke all on function public.issue_float(uuid, numeric, text) from public, anon;
revoke all on function public.count_route_cash(integer, numeric, text) from public, anon;
revoke all on function public.verify_settlement(integer, text, text) from public, anon;
grant execute on function public.wh_tolerance_pct() to authenticated;
grant execute on function public.record_load_weighing(integer, jsonb, text) to authenticated;
grant execute on function public.record_weighing(integer, numeric) to authenticated;
grant execute on function public.resolve_flagged_load(integer, text, text) to authenticated;
grant execute on function public.raise_requirement(integer, numeric, date, text) to authenticated;
grant execute on function public.cancel_requirement(integer, text) to authenticated;
grant execute on function public.release_to_hq(integer, numeric, text, text) to authenticated;
grant execute on function public.issue_float(uuid, numeric, text) to authenticated;
grant execute on function public.count_route_cash(integer, numeric, text) to authenticated;
grant execute on function public.verify_settlement(integer, text, text) to authenticated;
