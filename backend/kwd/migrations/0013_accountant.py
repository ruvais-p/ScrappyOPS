from django.db import migrations

UP = """
alter table kwd_profiles drop constraint kwd_profiles_role_check;
alter table kwd_profiles add constraint kwd_profiles_role_check check (role in ('head_office','zonal_manager','tso','franchisee','telecaller','accountant'));
"""

DOWN = """
alter table kwd_profiles drop constraint kwd_profiles_role_check;
alter table kwd_profiles add constraint kwd_profiles_role_check check (role in ('head_office','zonal_manager','tso','franchisee','telecaller'));
"""


class Migration(migrations.Migration):
    dependencies = [("kwd", "0012_tc_stock")]
    operations = [migrations.RunSQL(UP, reverse_sql=DOWN)]
