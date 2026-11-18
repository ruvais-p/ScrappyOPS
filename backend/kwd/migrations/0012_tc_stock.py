from django.db import migrations


CREATE = """
create table kwd_tc_stock_moves (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references kwd_fr_products(id),
  qty integer not null check (qty <> 0),
  kind text not null check (kind in ('opening','received','sale','sale_cancel','damaged','returned','count_adjust')),
  sale_id uuid references kwd_tc_sales(id),
  ref_no text,
  note text,
  created_by uuid,
  created_at timestamptz not null default now()
);
create index kwd_tc_stock_moves_product_id_idx on kwd_tc_stock_moves (product_id);
"""

DROP = "drop table if exists kwd_tc_stock_moves;"


class Migration(migrations.Migration):
    dependencies = [("kwd", "0011_tc_billing")]
    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
