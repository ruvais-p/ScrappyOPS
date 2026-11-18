from django.db import migrations

UP = """
create table kwd_lsgd_updates (
  id uuid primary key default gen_random_uuid(),
  lsgd_id uuid not null references kwd_lsgds(id),
  tso_id uuid not null references kwd_profiles(id),
  happened_on date not null,
  mode text not null default 'visit' check (mode in ('visit','call','whatsapp','email')),
  contact_ids uuid[] not null default '{}',
  discussion text not null,
  outcome text,
  interest_level smallint check (interest_level between 1 and 5),
  created_at timestamptz not null default now()
);
create index kwd_lsgd_updates_lsgd_idx on kwd_lsgd_updates (lsgd_id, happened_on desc);
"""

DOWN = "drop table kwd_lsgd_updates;"


class Migration(migrations.Migration):
    dependencies = [("kwd", "0014_work_from_home")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
