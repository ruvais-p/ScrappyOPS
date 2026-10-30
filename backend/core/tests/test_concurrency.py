"""Two people acting at the same moment must never overdraw stock or cash."""
import threading
from decimal import Decimal

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from core.models import (Bill, BillItem, Buyer, CashLedger, Counter, Customer, Franchise, HqRelease, HqRequirement, Invoice, Lead, Load,
                         LoadWeighing, Profile, Rate, ScrapItem, User)
from core.services import billing, pickup, warehouse
from core.services.common import ApiError, Ctx


def run_together(jobs):
    """Run each job in its own thread and database connection, started at the same moment. Returns [result or exception]."""
    results, barrier = [None] * len(jobs), threading.Barrier(len(jobs))

    def work(i, job):
        try:
            barrier.wait(5)
            with transaction.atomic():
                results[i] = job()
        except Exception as e:
            results[i] = e
        finally:
            connection.close()

    threads = [threading.Thread(target=work, args=(i, j)) for i, j in enumerate(jobs)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    return results


class ConcurrencyTests(TransactionTestCase):
    # The staff app's tables (kwd_*) point at the logins table. Naming the apps lets the between-test cleanup use
    # TRUNCATE ... CASCADE, which empties those tables too instead of failing on the link.
    available_apps = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.postgres", "core", "kwd"]

    def setUp(self):
        with transaction.atomic():
            # this kind of test empties every table between tests, so the running numbers are put back
            for name, value in (("lead_code", 1000), ("load_code", 0), ("bill_no", 0), ("requirement_code", 0), ("release_code", 300)):
                Counter.objects.update_or_create(name=name, defaults={"value": value})
            self.fr = Franchise.objects.create(code="KKD", name="Kakkanad")
            self.item = ScrapItem.objects.create(name="Iron")
            Rate.objects.create(item=self.item, rate_per_kg=30)
            mk = lambda email, role: Profile.objects.create(user=User.objects.create_user(email, "x"), full_name=email, role=role,
                                                           franchise=None if role == "hq" else self.fr)
            self.sup, self.sup2, self.drv = mk("s1@t.test", "supervisor"), mk("s2@t.test", "supervisor"), mk("d@t.test", "driver")

    def test_two_releases_cannot_take_the_same_stock(self):
        with transaction.atomic():
            load = Load.objects.create(driver=self.drv, franchise=self.fr, status="reconciled")
            LoadWeighing.objects.create(load=load, item=self.item, billed_kg=10, warehouse_kg=10, within_tolerance=True, weighed_by=self.sup, franchise=self.fr)
            req = HqRequirement.objects.create(item=self.item, required_kg=100, franchise=self.fr)
        jobs = [lambda c=Ctx(p.pk): warehouse.release_to_hq(c, req.pk, 8, "KL 1", None) for p in (self.sup, self.sup2)]
        out = run_together(jobs)
        ok = [r for r in out if isinstance(r, str)]
        bad = [r for r in out if isinstance(r, ApiError)]
        self.assertEqual((len(ok), len(bad)), (1, 1), out)
        self.assertIn("Not enough stock", bad[0].message)
        self.assertEqual(HqRelease.objects.count(), 1)
        self.assertEqual(warehouse.stock_kg(self.item.pk, self.fr.pk), Decimal("2"))

    def test_two_sale_invoices_cannot_sell_the_same_hq_stock(self):
        with transaction.atomic():
            hq = Profile.objects.create(user=User.objects.create_user("hq@t.test", "x"), full_name="HQ", role="hq")
            buyer = Buyer.objects.create(name="Buyer")
            HqRelease.objects.create(item=self.item, kg=10, vehicle_no="KL 1", released_by=self.sup, franchise=self.fr)
        args = (buyer.pk, [{"item_id": self.item.pk, "kg": 8, "rate": 30}])
        out = run_together([lambda: billing.bill_create_sale_invoice(Ctx(hq.pk), *args) for _ in range(2)])
        self.assertEqual(sum(isinstance(r, dict) for r in out), 1, out)
        self.assertEqual(sum(isinstance(r, ApiError) for r in out), 1, out)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(billing.hq_in_hand(self.item.pk), Decimal("2"))

    def test_two_cash_payments_cannot_spend_the_same_cash(self):
        bills = []
        with transaction.atomic():
            CashLedger.objects.create(driver=self.drv, entry_type="float_issued", amount=500, franchise=self.fr)
            load = Load.objects.create(driver=self.drv, franchise=self.fr)
            for i in range(2):
                cust = Customer.objects.create(name=f"C{i}", phone=f"900000000{i}", address="x")
                lead = Lead.objects.create(customer=cust, driver=self.drv, franchise=self.fr, status="in_progress")
                b = Bill.objects.create(lead=lead, load=load)
                BillItem.objects.create(bill=b, item=self.item, qty_kg=10, rate_per_kg=30)          # 300 each
                Bill.objects.filter(pk=b.pk).update(status="confirmed")
                bills.append(b.pk)
        jobs = [lambda b=b: pickup.pay_bill(Ctx(self.drv.pk), b, "cash") for b in bills]
        out = run_together(jobs)
        self.assertEqual(sum(isinstance(r, ApiError) for r in out), 1, out)
        self.assertEqual(sum(r is None for r in out), 1, out)
        bal = CashLedger.objects.filter(driver=self.drv).aggregate(s=__import__("django.db.models", fromlist=["Sum"]).Sum("amount"))["s"]
        self.assertEqual(bal, Decimal("200"))
        self.assertEqual(Bill.objects.filter(status="paid").count(), 1)

    def test_one_pickup_started_twice_makes_one_bill(self):
        with transaction.atomic():
            cust = Customer.objects.create(name="C", phone="9000000000", address="x")
            lead = Lead.objects.create(customer=cust, driver=self.drv, franchise=self.fr)
        out = run_together([lambda: pickup.start_pickup(Ctx(self.drv.pk), lead.pk) for _ in range(3)])
        ids = {r for r in out if isinstance(r, int)}
        self.assertEqual((len(ids), Bill.objects.count(), Load.objects.count()), (1, 1, 1), out)
