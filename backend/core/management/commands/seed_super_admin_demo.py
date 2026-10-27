"""Add clearly labelled sample transactions for exercising the Super Admin BI dashboard.

Development only. Safe to repeat: every seeded record is found by its demo marker before insertion.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction
from django.utils import timezone

from core.models import (Bill, BillItem, Customer, Franchise, Lead, Load, LoadWeighing,
                         Profile, ScrapItem)
from core.services.common import fetch, fetch_one


class Command(BaseCommand):
    help = "Seed additive, clearly named sample purchases, sales, inventory, leads, and TA/DA for the BI dashboard."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_super_admin_demo is development-only; set DJANGO_DEBUG=1.")

        call_command("seed_demo", verbosity=0)
        call_command("seed_kwd_demo", verbosity=0)
        now = timezone.now()
        today = timezone.localdate()
        fy_start = today.year if today.month >= 4 else today.year - 1
        demo_days = [datetime(fy_start, 4, 15).date(), datetime(fy_start, 7, 15).date(), today]
        demo_days = [d for d in demo_days if d <= today]

        franchise = Franchise.objects.get(code="KKD")
        driver = Profile.objects.get(user__email="driver@scrappy.test")
        warehouse = Profile.objects.get(user__email="warehouse@scrappy.test")
        iron = ScrapItem.objects.get(name__iexact="Iron", active=True)
        rate = iron.rates.order_by("-effective_from").values_list("rate_per_kg", flat=True).first() or Decimal("28")
        customer, _ = Customer.objects.get_or_create(
            phone="9000001001",
            defaults={"name": "Demo Sample Household", "address": "Demo Road, Kakkanad", "area": "Kakkanad"},
        )
        for idx, (day, kg) in enumerate(zip(demo_days, (Decimal("120"), Decimal("85"), Decimal("145"))), 1):
            stamp = timezone.make_aware(datetime.combine(day, time(12, 0)))
            lead_code = f"DEMO-SA-PICKUP-{idx:03d}"
            lead, _ = Lead.objects.get_or_create(
                code=lead_code,
                defaults={"customer": customer, "driver": driver, "franchise": franchise, "slot": stamp,
                          "items_said": "Demo: iron and mixed recyclable material", "status": "closed",
                          "created_by": driver, "closed_at": stamp},
            )
            load, _ = Load.objects.get_or_create(
                code=f"DEMO-SA-LOAD-{idx:03d}",
                defaults={"driver": driver, "franchise": franchise, "vehicle_no": "KL-07-AB-1234",
                          "status": "reconciled", "submitted_at": stamp, "warehouse_kg": kg - Decimal("2")},
            )
            bill, _ = Bill.objects.get_or_create(
                bill_no=f"DEMO-SA-SCRAP-{idx:03d}",
                defaults={"lead": lead, "load": load, "status": "draft", "payment_method": "upi",
                          "paid_at": stamp, "confirmed_at": stamp, "upi_ref": f"DEMO-SA-UPI-{idx:03d}"},
            )
            has_item = BillItem.objects.filter(bill=bill, item=iron).exists()
            if bill.status == "draft":
                BillItem.objects.get_or_create(bill=bill, item=iron, defaults={"qty_kg": kg, "rate_per_kg": rate})
                bill.status = "paid"
                bill.payment_method = "upi"
                bill.save(update_fields=["status", "payment_method"])
            elif not has_item:
                raise CommandError(f"Demo bill {bill.bill_no} is already locked without its sample line item.")
            LoadWeighing.objects.get_or_create(
                load=load, item=iron,
                defaults={"billed_kg": kg, "warehouse_kg": kg - Decimal("2"),
                          "within_tolerance": True, "weighed_by": warehouse, "franchise": franchise},
            )

        scheduled_stamp = timezone.make_aware(datetime.combine(today, time(16, 0)))
        Lead.objects.get_or_create(
            code="DEMO-SA-PICKUP-SCHEDULED",
            defaults={"customer": customer, "driver": driver, "franchise": franchise, "slot": scheduled_stamp,
                      "items_said": "Demo: scheduled collection", "status": "scheduled", "created_by": driver},
        )

        # The KWD demo command supplies the Head Office, TSO, district, and franchise identities.
        tso = fetch_one("select id from kwd_profiles where email = 'tso@demo.test' and is_active")
        hq = fetch_one("select id from kwd_profiles where email = 'ho@demo.test' and is_active")
        kwd_franchise = fetch_one("select id, district_id from kwd_fr_franchises where user_id = (select id from kwd_profiles where email = 'fr@demo.test')")
        if not (tso and hq and kwd_franchise):
            raise CommandError("KWD demo identities were not created.")

        product = fetch_one("select id, list_price, gst_percent from kwd_fr_products where code = 'KWD-120' and is_active")
        if not product:
            raise CommandError("The KWD-120 demo product was not found.")
        fetch("update kwd_fr_products set list_price = coalesce(list_price, 5880), gst_percent = coalesce(gst_percent, 5), "
              "hsn_sac = coalesce(hsn_sac, '84198990') where id = %(p)s returning id", {"p": product["id"]})

        sale_rows = [
            (demo_days[0], "B2B", "Demo · Green Leaf Apartments", 2, Decimal("5880"), Decimal("12348"), "delivered", Decimal("12348")),
            (demo_days[min(1, len(demo_days) - 1)], "B2C", "Demo · Anu Menon", 1, Decimal("5880"), Decimal("6174"), "dispatched", Decimal("3000")),
            (today, "B2G", "Demo · Kakkanad Municipality", 3, Decimal("5880"), Decimal("18522"), "pending", Decimal("5000")),
        ]
        business_year = f"{fy_start % 100:02d}{(fy_start + 1) % 100:02d}"
        for idx, (day, customer_type, name, qty, unit_price, total, delivery, received) in enumerate(sale_rows, 1):
            marker = f"SUPERADMIN-DEMO-{idx:03d}"
            sale = fetch_one("select id, invoice_no from kwd_fr_sales where franchise_id=%(f)s and sale_date=%(d)s "
                             "and flags @> array['superadmin_demo']::text[] and customer_name=%(n)s",
                             {"f": kwd_franchise["id"], "d": day, "n": name})
            if not sale:
                counter = fetch_one(
                    "insert into kwd_fr_invoice_counters (business_year,last_number) values (%(fy)s,1) "
                    "on conflict (business_year) do update set last_number=kwd_fr_invoice_counters.last_number+1 returning last_number",
                    {"fy": business_year},
                )["last_number"]
                invoice_no = f"{customer_type}/{business_year}/{day:%m%d}/{counter:03d}"
                sale = fetch_one(
                    "insert into kwd_fr_sales (franchise_id,customer_name,customer_type,district_id,place,sale_date,invoice_no,total,amount_received,"
                    "needs_install,delivery_status,installation_status,flags,created_by) values (%(f)s,%(n)s,%(ct)s,%(d)s,'Kakkanad',%(day)s,%(inv)s,%(total)s,%(received)s,"
                    "true,%(delivery)s,'pending',array['superadmin_demo'],%(by)s) returning id,invoice_no",
                    {"f": kwd_franchise["id"], "n": name, "ct": customer_type, "d": kwd_franchise["district_id"], "day": day,
                     "inv": invoice_no, "total": total, "received": received, "delivery": delivery, "by": tso["id"]},
                )
                fetch("insert into kwd_fr_sale_items (sale_id,product_id,hsn_sac,qty,unit_price,gst_percent) "
                      "values (%(s)s,%(p)s,'84198990',%(q)s,%(price)s,5) returning id",
                      {"s": sale["id"], "p": product["id"], "q": qty, "price": unit_price})
                ref = marker
                fetch("insert into kwd_fr_payment_receipts (sale_id,amount,method,reference,received_by,received_at) "
                      "values (%(s)s,%(a)s,'bank_transfer',%(ref)s,%(by)s,%(at)s) returning id",
                      {"s": sale["id"], "a": received, "ref": ref, "by": hq["id"],
                       "at": timezone.make_aware(datetime.combine(day, time(14, 0)))})
            if not fetch_one("select 1 as x from kwd_fr_stock_moves where franchise_id=%(f)s and product_id=%(p)s "
                             "and ref_no='SUPERADMIN-DEMO-OPENING'", {"f": kwd_franchise["id"], "p": product["id"]}):
                fetch("insert into kwd_fr_stock_moves (franchise_id,product_id,qty,kind,ref_no,note,created_by) "
                      "values (%(f)s,%(p)s,20,'opening','SUPERADMIN-DEMO-OPENING','Super Admin demo opening stock',%(by)s) returning id",
                      {"f": kwd_franchise["id"], "p": product["id"], "by": hq["id"]})
            if not fetch_one("select 1 as x from kwd_fr_stock_moves where sale_id=%(s)s and kind='sale'", {"s": sale["id"]}):
                fetch("insert into kwd_fr_stock_moves (franchise_id,product_id,qty,kind,sale_id,ref_no,note,created_by) "
                      "values (%(f)s,%(p)s,%(q)s,'sale',%(s)s,%(ref)s,'Super Admin demo sale',%(by)s) returning id",
                      {"f": kwd_franchise["id"], "p": product["id"], "q": -qty, "s": sale["id"],
                       "ref": marker, "by": tso["id"]})

        for month in sorted({day.replace(day=1) for day in demo_days}):
            if not fetch_one("select 1 as x from kwd_fr_targets where franchise_id=%(f)s and product_id=%(p)s and month=%(m)s",
                             {"f": kwd_franchise["id"], "p": product["id"], "m": month}):
                fetch("insert into kwd_fr_targets (franchise_id,product_id,month,target_units,target_amount,set_by) "
                      "values (%(f)s,%(p)s,%(m)s,6,35280,%(by)s) returning id",
                      {"f": kwd_franchise["id"], "p": product["id"], "m": month, "by": hq["id"]})

        district_lsgd = fetch_one("select id from kwd_lsgds where name='Kalamassery Municipality' order by id limit 1")
        if district_lsgd and not fetch_one("select 1 as x from kwd_opportunities where lsgd_id=%(l)s and financial_year=%(fy)s",
                                           {"l": district_lsgd["id"], "fy": f"{fy_start}-{str(fy_start + 1)[-2:]}"}):
            fetch("insert into kwd_opportunities (lsgd_id,financial_year,owner_id,stage,expected_units,unit_price,probability,expected_close) "
                  "values (%(l)s,%(fy)s,%(o)s,'proposal_submitted',4,5880,60,%(close)s) returning id",
                  {"l": district_lsgd["id"], "fy": f"{fy_start}-{str(fy_start + 1)[-2:]}", "o": tso["id"], "close": today + timedelta(days=30)})

        expense_days = [(today - timedelta(days=1), "submitted", 350, 250, None),
                        (today - timedelta(days=3), "ho_approved", 420, 250, Decimal("620")),
                        (today - timedelta(days=5), "paid", 500, 400, Decimal("850"))]
        for idx, (day, status, ta, da, approved) in enumerate(expense_days, 1):
            if not fetch_one("select 1 as x from kwd_field_days where tso_id=%(t)s and day=%(d)s", {"t": tso["id"], "d": day}):
                fetch("insert into kwd_field_days (tso_id,day,travel_mode,vehicle_no,start_odo,end_odo,ta_km,ta_amount,da_amount,"
                      "status,submitted_at,approved_amount,ho_by,ho_at,paid_by,paid_at,paid_ref,visits_count) values "
                      "(%(t)s,%(d)s,'two_wheeler','KL-07-DEMO',14500,14580,80,%(ta)s,%(da)s,%(status)s,%(submitted)s,%(approved)s,"
                      "%(ho)s,%(ho_at)s,%(paid_by)s,%(paid_at)s,%(ref)s,2) returning id",
                      {"t": tso["id"], "d": day, "ta": ta, "da": da, "status": status, "submitted": now,
                       "approved": approved, "ho": hq["id"] if approved is not None else None,
                       "ho_at": now if approved is not None else None,
                       "paid_by": hq["id"] if status == "paid" else None,
                       "paid_at": now if status == "paid" else None,
                       "ref": f"DEMO-TA-DA-{idx:03d}" if status == "paid" else None})

        counts = fetch_one("select (select count(*) from hq_paid_bills p join bills b on b.id=p.bill_id where left(b.bill_no,14)='DEMO-SA-SCRAP-') as scrap_bills, "
                           "(select count(*) from kwd_fr_sales where flags @> array['superadmin_demo']::text[]) as digester_sales, "
                           "(select count(*) from kwd_field_days where tso_id=%(t)s and left(paid_ref,11)='DEMO-TA-DA-') as paid_claims",
                           {"t": tso["id"]})
        self.stdout.write(self.style.SUCCESS(
            f"Super Admin sample data ready (additive/idempotent): {counts['scrap_bills']} scrap bills, "
            f"{counts['digester_sales']} digester invoices, {counts['paid_claims']} paid TA/DA claims."
        ))
