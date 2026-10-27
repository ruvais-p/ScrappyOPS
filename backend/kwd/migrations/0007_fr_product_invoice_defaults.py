from django.db import migrations


UP = """
alter table kwd_fr_products add column hsn_sac text;
alter table kwd_fr_products add column gst_percent numeric not null default 0 check (gst_percent >= 0 and gst_percent <= 100);
"""

DOWN = """
alter table kwd_fr_products drop column if exists gst_percent;
alter table kwd_fr_products drop column if exists hsn_sac;
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0006_fr_invoice_numbering")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
