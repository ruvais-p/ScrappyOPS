from django.db import migrations


CREATE = """
create table kwd_tc_sales (
  id uuid primary key default gen_random_uuid(),
  telecaller_id uuid not null references kwd_profiles(id),
  lead_id uuid references kwd_tc_leads(id),
  customer_name text not null,
  customer_type text not null check (customer_type in ('B2B','B2C','B2G')),
  phone text,
  district_id smallint references kwd_districts(id),
  place text,
  sale_date date not null,
  invoice_no text,
  total numeric not null default 0,
  amount_received numeric not null default 0 check (amount_received >= 0),
  payment_status text generated always as (case when amount_received <= 0 then 'pending' when amount_received < total then 'partial' else 'paid' end) stored,
  status text not null default 'active' check (status in ('active','cancelled')),
  cancel_reason text,
  cancelled_by uuid,
  cancelled_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now()
);
create index kwd_tc_sales_telecaller_id_sale_date_idx on kwd_tc_sales (telecaller_id, sale_date desc);

create table kwd_tc_sale_items (
  id uuid primary key default gen_random_uuid(),
  sale_id uuid not null references kwd_tc_sales(id),
  product_id uuid not null references kwd_fr_products(id),
  hsn_sac text,
  qty integer not null check (qty > 0),
  unit_price numeric not null check (unit_price > 0),
  gst_percent numeric not null default 0 check (gst_percent >= 0 and gst_percent <= 100),
  gst_amount numeric generated always as ((qty::numeric * unit_price * gst_percent) / 100) stored,
  line_total numeric generated always as ((qty)::numeric * unit_price) stored
);
create index kwd_tc_sale_items_sale_id_idx on kwd_tc_sale_items (sale_id);

create table kwd_tc_payment_receipts (
  id uuid primary key default gen_random_uuid(),
  sale_id uuid not null references kwd_tc_sales(id),
  amount numeric not null check (amount > 0),
  method text not null check (method in ('cash','upi','bank_transfer','cheque','card','other')),
  reference text,
  received_by uuid not null references kwd_profiles(id),
  received_at timestamptz not null default now()
);
create index kwd_tc_payment_receipts_sale_id_received_at_idx on kwd_tc_payment_receipts (sale_id, received_at desc);

create table kwd_tc_invoice_counters (
  business_year text primary key check (business_year ~ '^[0-9]{4}$'),
  last_number integer not null check (last_number > 0)
);
"""

DROP = """
drop table if exists kwd_tc_invoice_counters;
drop table if exists kwd_tc_payment_receipts;
drop table if exists kwd_tc_sale_items;
drop table if exists kwd_tc_sales;
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0010_telecaller")]
    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
