"""Freeze existing invoice identities using the details available at migration time."""
from django.db import migrations, models


def snapshot_existing(apps, schema_editor):
    Invoice = apps.get_model("core", "Invoice")
    InvoiceLine = apps.get_model("core", "InvoiceLine")
    alias = schema_editor.connection.alias
    defaults = {
        "company_name": "SCRAPPY INNOVATIONS PVT LTD.",
        "address": "HO. WP 18/108 - H,J,K\n1st FLOOR SAJ BUILDING\nMANJERI ROAD WANDOOR\nPIN 679328",
        "phone": "+918592964750", "gstin": "32ABFCS0169R1ZX",
        "email": "info@scrappyinnovations.com", "state": "Kerala",
    }
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("select company_name, address, phone, gstin, email, state from kwd_fr_company_settings where id = 1")
        row = cursor.fetchone()
    hq = {key: (value or defaults[key]) for key, value in zip(defaults, row or [None] * len(defaults))}
    hq["name"] = hq.pop("company_name")
    for invoice in Invoice.objects.using(alias).select_related("franchise", "buyer").iterator():
        party = invoice.franchise if invoice.kind == "purchase" else invoice.buyer
        details = {key: getattr(party, key) for key in ("name", "address", "phone", "email", "gstin", "state")}
        seller, buyer = (details, hq) if invoice.kind == "purchase" else (hq, details)
        Invoice.objects.using(alias).filter(pk=invoice.pk).update(seller_details=seller, buyer_details=buyer)
    for line in InvoiceLine.objects.using(alias).select_related("item").iterator():
        InvoiceLine.objects.using(alias).filter(pk=line.pk).update(item_name=line.item.name)


class Migration(migrations.Migration):
    dependencies = [("core", "0008_dispatch_without_request"), ("kwd", "0002_fr_company_settings")]
    operations = [
        migrations.AddField(model_name="invoice", name="seller_details", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="invoice", name="buyer_details", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="invoiceline", name="item_name", field=models.TextField(default="")),
        migrations.RunPython(snapshot_existing, migrations.RunPython.noop),
    ]
