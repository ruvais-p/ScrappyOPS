from django.db import migrations


UP = """
alter table kwd_fr_leads add column source text not null default 'ho' check (source in ('ho','own'));
create index kwd_fr_leads_source_idx on kwd_fr_leads (source);
"""

DOWN = """
drop index if exists kwd_fr_leads_source_idx;
alter table kwd_fr_leads drop column if exists source;
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0008_fr_product_categories")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
