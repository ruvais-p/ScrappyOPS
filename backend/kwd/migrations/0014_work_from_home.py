from django.db import migrations

UP = """
alter table kwd_field_days add column work_mode text not null default 'field' check (work_mode in ('field','home'));
alter table kwd_field_days add column route_at timestamptz;
alter table kwd_field_days add column route_lat double precision;
alter table kwd_field_days add column route_lng double precision;
alter table kwd_field_days add column route_acc real;
"""

DOWN = """
alter table kwd_field_days drop column route_acc, drop column route_lng, drop column route_lat, drop column route_at, drop column work_mode;
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0013_accountant")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
