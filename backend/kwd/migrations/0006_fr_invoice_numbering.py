from django.db import migrations


UP = """
alter table kwd_fr_sales drop constraint if exists kwd_fr_sales_customer_type_check;
update kwd_fr_sales set customer_type = case customer_type
  when 'private' then 'B2C'
  when 'lsgd' then 'B2G'
  when 'institution' then 'B2B'
  when 'business' then 'B2B'
  else customer_type
end;
alter table kwd_fr_sales add constraint kwd_fr_sales_customer_type_check check (customer_type in ('B2B','B2C','B2G'));

create table kwd_fr_invoice_counters (
  business_year text primary key check (business_year ~ '^[0-9]{4}$'),
  last_number integer not null check (last_number > 0)
);
"""

DOWN = """
drop table if exists kwd_fr_invoice_counters;
alter table kwd_fr_sales drop constraint if exists kwd_fr_sales_customer_type_check;
update kwd_fr_sales set customer_type = case customer_type
  when 'B2C' then 'private'
  when 'B2G' then 'lsgd'
  when 'B2B' then 'business'
  else customer_type
end;
alter table kwd_fr_sales add constraint kwd_fr_sales_customer_type_check check (customer_type in ('private','lsgd','institution','business'));
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0005_fr_meetings")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
