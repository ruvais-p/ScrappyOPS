from django.db import migrations


UP = """
create table kwd_fr_product_categories (
  key text primary key check (key ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
  name text not null unique check (length(trim(both from name)) >= 2),
  sort smallint not null default 0
);
insert into kwd_fr_product_categories (key, name, sort) values
  ('digester', 'Digester', 1), ('inoculum', 'Inoculum', 2), ('burner', 'Burner', 3), ('incinerator', 'Incinerator', 4);
alter table kwd_fr_products drop constraint kwd_fr_products_category_check;
alter table kwd_fr_products add constraint kwd_fr_products_category_fkey foreign key (category) references kwd_fr_product_categories(key);
"""

DOWN = """
alter table kwd_fr_products drop constraint if exists kwd_fr_products_category_fkey;
alter table kwd_fr_products add constraint kwd_fr_products_category_check check (category in ('digester','inoculum','burner','incinerator'));
drop table if exists kwd_fr_product_categories;
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0007_fr_product_invoice_defaults")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
