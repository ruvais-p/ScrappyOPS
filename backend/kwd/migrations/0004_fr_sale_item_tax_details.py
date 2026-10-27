from django.db import migrations


UP = """
alter table kwd_fr_sale_items add column hsn_sac text;
alter table kwd_fr_sale_items add column gst_percent numeric not null default 0 check (gst_percent >= 0 and gst_percent <= 100);
alter table kwd_fr_sale_items add column gst_amount numeric generated always as ((qty::numeric * unit_price * gst_percent) / 100) stored;
"""

DOWN = """
alter table kwd_fr_sale_items drop column if exists gst_amount;
alter table kwd_fr_sale_items drop column if exists gst_percent;
alter table kwd_fr_sale_items drop column if exists hsn_sac;
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0003_fr_payment_receipts")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
