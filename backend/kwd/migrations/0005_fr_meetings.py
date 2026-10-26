from django.db import migrations


UP = """
create table kwd_fr_meetings (
  id uuid primary key default gen_random_uuid(),
  scheduled_at timestamptz not null,
  meeting_type text not null check (meeting_type in ('B2B','B2C','B2G')),
  description text not null,
  status text not null default 'scheduled' check (status in ('scheduled','completed')),
  created_by uuid not null references kwd_profiles(id),
  created_at timestamptz not null default now(),
  completed_by uuid references kwd_profiles(id),
  completed_at timestamptz
);
create index kwd_fr_meetings_scheduled_at_idx on kwd_fr_meetings (scheduled_at desc);
"""

DOWN = "drop table if exists kwd_fr_meetings;"


class Migration(migrations.Migration):
    dependencies = [("kwd", "0004_fr_sale_item_tax_details")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
