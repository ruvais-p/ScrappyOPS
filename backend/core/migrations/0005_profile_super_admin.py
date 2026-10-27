from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_hq_dispatch_and_buy_rates"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="is_super_admin",
            field=models.BooleanField(default=False),
        ),
    ]
