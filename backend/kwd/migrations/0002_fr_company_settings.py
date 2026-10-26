from django.db import migrations


CREATE = """
create table kwd_fr_company_settings (
  id smallint primary key default 1 check (id = 1),
  company_name text not null default 'SCRAPPY INNOVATIONS PVT LTD.',
  address text not null default E'HO. WP 18/108 - H,J,K\n1st FLOOR SAJ BUILDING\nMANJERI ROAD WANDOOR\nPIN 679328',
  phone text not null default '+918592964750',
  gstin text not null default '32ABFCS0169R1ZX',
  email text not null default 'info@scrappyinnovations.com',
  state text not null default 'Kerala',
  updated_by uuid references kwd_profiles(id),
  updated_at timestamptz not null default now()
);
insert into kwd_fr_company_settings (id) values (1);
"""

DROP = "drop table if exists kwd_fr_company_settings;"


class Migration(migrations.Migration):
    dependencies = [("kwd", "0001_kwd_schema")]
    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
