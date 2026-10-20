"""Live updates: every change to the tables the dashboards watch sends a short note ("loads changed in franchise 3").
The website server listens for these notes and tells the open pages to refresh. No row data travels in the note."""
from django.db import migrations

TABLES = ["leads", "loads", "bills", "cash_ledger", "load_weighings", "hq_requirements", "hq_releases",
          "cash_settlements", "hq_audit", "settlement_resolutions"]

FUNCTION = r"""
create or replace function notify_change() returns trigger language plpgsql as $$
declare r record; f integer; d uuid;
begin
  if tg_op = 'DELETE' then r := old; else r := new; end if;
  case tg_table_name
    when 'bills' then select franchise_id, driver_id into f, d from loads where id = r.load_id;
    when 'settlement_resolutions' then select franchise_id, driver_id into f, d from cash_settlements where id = r.settlement_id;
    when 'load_weighings' then f := r.franchise_id; select driver_id into d from loads where id = r.load_id;
    when 'hq_audit' then f := r.franchise_id;
    when 'hq_requirements' then f := r.franchise_id;
    when 'hq_releases' then f := r.franchise_id;
    else f := r.franchise_id; d := r.driver_id;
  end case;
  perform pg_notify('scrappy_changes', json_build_object('t', tg_table_name, 'op', tg_op, 'f', f, 'd', d)::text);
  return null;
end $$;
"""

CREATE = FUNCTION + "\n".join(
    f"create trigger {t}_notify after insert or update or delete on {t} for each row execute function notify_change();" for t in TABLES)
DROP = "\n".join(f"drop trigger if exists {t}_notify on {t};" for t in TABLES) + "\ndrop function if exists notify_change();"


class Migration(migrations.Migration):
    dependencies = [("core", "0002_views_counters_guards")]
    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
