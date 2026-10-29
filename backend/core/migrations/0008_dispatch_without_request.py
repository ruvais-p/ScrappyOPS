import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    """A warehouse manager can load stock for HQ without an HQ request: the release and the load line then have no requirement."""

    dependencies = [("core", "0007_billing_invoices_buyers")]
    operations = [
        migrations.AlterField(model_name="hqrelease", name="requirement", field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="releases", to="core.hqrequirement")),
        migrations.AlterField(model_name="hqdispatchline", name="requirement", field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.hqrequirement")),
        migrations.AddConstraint(model_name="hqdispatchline", constraint=models.UniqueConstraint(
            condition=Q(requirement__isnull=True), fields=("dispatch", "item"), name="hq_dispatch_lines_item_once")),
    ]
