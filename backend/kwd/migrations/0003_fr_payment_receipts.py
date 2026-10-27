from django.db import migrations


CREATE = """
create table kwd_fr_payment_receipts (
  id uuid primary key default gen_random_uuid(),
  sale_id uuid not null references kwd_fr_sales(id),
  amount numeric not null check (amount > 0),
  method text not null check (method in ('cash','upi','bank_transfer','cheque','card','other')),
  reference text,
  received_by uuid not null references kwd_profiles(id),
  received_at timestamptz not null default now()
);
create index kwd_fr_payment_receipts_sale_id_received_at_idx on kwd_fr_payment_receipts (sale_id, received_at desc);
"""

DROP = "drop table if exists kwd_fr_payment_receipts;"


class Migration(migrations.Migration):
    dependencies = [("kwd", "0002_fr_company_settings")]
    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
