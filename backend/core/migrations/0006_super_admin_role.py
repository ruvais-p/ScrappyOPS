from django.db import migrations, models
from django.db.models import Q


def promote_existing_grants(apps, schema_editor):
    Profile = apps.get_model("core", "Profile")
    Profile.objects.filter(role="hq", is_super_admin=True).update(role="super_admin")


def restore_hq_role(apps, schema_editor):
    Profile = apps.get_model("core", "Profile")
    Profile.objects.filter(role="super_admin").update(role="hq")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_profile_super_admin"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="profile",
            name="profiles_role_check",
        ),
        migrations.AddConstraint(
            model_name="profile",
            constraint=models.CheckConstraint(
                condition=Q(role__in=("driver", "hq", "warehouse", "supervisor", "super_admin")),
                name="profiles_role_check",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="profile",
            name="profiles_franchise_check",
        ),
        migrations.AddConstraint(
            model_name="profile",
            constraint=models.CheckConstraint(
                condition=Q(role__in=("hq", "super_admin")) | Q(franchise__isnull=False),
                name="profiles_franchise_check",
            ),
        ),
        migrations.RunPython(promote_existing_grants, restore_hq_role),
    ]
