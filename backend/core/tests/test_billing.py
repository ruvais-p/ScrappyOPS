"""Billing: a franchise invoices HQ for a finalized load; HQ invoices its buyers for the stock it holds."""
import json
from decimal import Decimal

from core.models import HqAudit
from core.services.billing import financial_year, today
from core.tests.base import Api
from core.tests.test_dispatch import DispatchBase

D = lambda v: Decimal(str(v))


class BillingFlow(DispatchBase):
    def setUp(self):
        super().setUp()
        self.tsup = Api(self.client, "tvm-sup@t.test")
        self.fy = financial_year(today())
        self.hq.ok("hq_set_item_tax", p_item_id=self.iron, p_hsn="7204", p_gst=18)
        self.hq.ok("hq_set_item_tax", p_item_id=self.paper, p_hsn="4707", p_gst=5)
        self.set_prices()

    def finalized_load(self, iron=5, paper=3):
        self.wh.ok("wh_submit_dispatch", p_lines=self.lines(iron, paper), p_vehicle_no="KL 07 HQ 1", p_note=None)
        load = self.wh.ok("wh_dispatches")[0]
        self.sup.ok("sup_review_dispatch", p_dispatch_id=load["id"], p_decision="finalize")
        return load["id"]

    def pdf(self, who, invoice_id):
        return self.client.post("/functions/v1/invoice-pdf", data=json.dumps({"invoice_id": invoice_id}), content_type="application/json", **who.h)

    # ------------------------------------------------------------------ materials and details
    def test_hsn_and_gst_are_set_by_hq_only(self):
        self.wh.fail("hq_set_item_tax", "Only HQ", p_item_id=self.iron, p_hsn="7204", p_gst=18)
        self.sup.fail("hq_set_item_tax", "Only HQ", p_item_id=self.iron, p_hsn="7204", p_gst=18)
        self.hq.fail("hq_set_item_tax", "4 to 8 digits", p_item_id=self.iron, p_hsn="72A", p_gst=18)
        self.hq.fail("hq_set_item_tax", "0 to 100", p_item_id=self.iron, p_hsn="7204", p_gst=150)
        items = {i["name"]: i for i in self.sup.ok("bill_items")}
        self.assertEqual((items["Iron"]["hsn_code"], D(items["Iron"]["gst_percent"]), items["Paper"]["hsn_code"]), ("7204", D(18), "4707"))
        self.wh.fail("bill_items", "Only the supervisor")                      # the warehouse manager has no part in prices or tax
        self.sup.fail("set_billing_details", "GSTIN", p_gstin="12345")
        self.sup.ok("set_billing_details", p_gstin="32abfcs0169r1zx", p_address="Kakkanad yard", p_phone="9446000000", p_email="kkd@t.test", p_state="Kerala")
        mine = self.sup.ok("bill_details")["franchise"]
        self.assertEqual((mine["code"], mine["gstin"], mine["address"]), ("KKD", "32ABFCS0169R1ZX", "Kakkanad yard"))
        self.wh.fail("set_billing_details", "Only the supervisor", p_gstin=None)
        self.assertIsNone(self.hq.ok("bill_details")["franchise"])              # HQ asked for no franchise

    # ------------------------------------------------------------------ the franchise invoices HQ
    def test_the_franchise_invoices_a_finalized_load(self):
        self.assertEqual(self.sup.ok("bill_pending_invoices"), [])              # nothing finalized yet
        load_id = self.finalized_load()
        pending = self.sup.ok("bill_pending_invoices")
        self.assertEqual(len(pending), 1)
        self.assertEqual((D(pending[0]["taxable"]), D(pending[0]["gst_amount"]), D(pending[0]["total"])), (D("126.50"), D("19.65"), D("146.15")))   # 102.50 + 18% and 24.00 + 5%
        self.wh.fail("bill_pending_invoices", "Only the supervisor")
        self.wh.fail("bill_create_purchase_invoice", "Only the supervisor", p_dispatch_id=load_id)
        self.tsup.fail("bill_create_purchase_invoice", "Load not found", p_dispatch_id=load_id)           # another franchise
        self.sup.fail("bill_create_purchase_invoice", "future", p_dispatch_id=load_id, p_invoice_date="2999-01-01")
        made = self.sup.ok("bill_create_purchase_invoice", p_dispatch_id=load_id, p_note="March stock")
        self.assertEqual((made["code"], D(made["total"])), (f"KKD/{self.fy}/0001", D("146.15")))
        self.sup.fail("bill_create_purchase_invoice", "already has an invoice", p_dispatch_id=load_id)
        self.assertEqual(self.sup.ok("bill_pending_invoices"), [])
        # who sees it
        mine = self.sup.ok("bill_invoices")
        self.assertEqual(len(mine), 1)
        inv = mine[0]
        self.assertEqual((inv["kind"], inv["franchise_code"], inv["load_code"], inv["payment_status"], inv["status"]), ("purchase", "KKD", "DP-0001", "unpaid", "issued"))
        self.assertEqual((D(inv["subtotal"]), D(inv["gst_total"]), D(inv["total"]), D(inv["total_kg"])), (D("126.50"), D("19.65"), D("146.15"), D(8)))
        self.assertEqual({x["item_name"]: (x["hsn_code"], D(x["gst_percent"]), D(x["rate"]), D(x["taxable"])) for x in inv["lines"]},
                         {"Iron": ("7204", D(18), D("20.5"), D("102.5")), "Paper": ("4707", D(5), D(8), D(24))})
        self.assertEqual(len(self.hq.ok("bill_invoices")), 1)
        self.assertEqual(self.tsup.ok("bill_invoices"), [])
        self.wh.fail("bill_invoices", "Only the supervisor")
        self.assertTrue(HqAudit.objects.filter(action="invoice_issued", ref=made["code"]).exists())
        # the PDF
        r = self.pdf(self.sup, made["id"])
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(r.content.startswith(b"%PDF") and len(r.content) > 3000)
        self.assertIn(f"KKD-{self.fy}-0001.pdf", r["Content-Disposition"])
        self.assertEqual(self.pdf(self.hq, made["id"]).status_code, 200)
        self.assertEqual(self.pdf(self.tsup, made["id"]).status_code, 404)
        self.assertEqual(self.pdf(self.wh, made["id"]).status_code, 403)

    def test_payment_and_cancelling(self):
        load_id = self.finalized_load()
        first = self.sup.ok("bill_create_purchase_invoice", p_dispatch_id=load_id)
        self.sup.fail("bill_mark_paid", "Only HQ", p_invoice_id=first["id"])
        self.sup.fail("bill_cancel_invoice", "Say why", p_invoice_id=first["id"], p_reason=" ")
        self.tsup.fail("bill_cancel_invoice", "not found", p_invoice_id=first["id"], p_reason="not ours")
        # cancelled: the load can be invoiced again, and the number is not reused
        self.sup.ok("bill_cancel_invoice", p_invoice_id=first["id"], p_reason="wrong date")
        self.sup.fail("bill_cancel_invoice", "already cancelled", p_invoice_id=first["id"], p_reason="again")
        self.assertEqual(len(self.sup.ok("bill_pending_invoices")), 1)
        second = self.sup.ok("bill_create_purchase_invoice", p_dispatch_id=load_id)
        self.assertEqual(second["code"], f"KKD/{self.fy}/0002")
        self.assertEqual([x["status"] for x in self.sup.ok("bill_invoices")], ["issued", "cancelled"])
        # HQ pays it
        self.hq.fail("bill_mark_paid", "valid", p_invoice_id=second["id"], p_paid_on="nonsense")
        self.hq.ok("bill_mark_paid", p_invoice_id=second["id"], p_reference="UTR 4025")
        self.hq.fail("bill_mark_paid", "already", p_invoice_id=second["id"])
        self.hq.fail("bill_mark_paid", "cancelled", p_invoice_id=first["id"])
        self.sup.fail("bill_cancel_invoice", "paid invoice", p_invoice_id=second["id"], p_reason="too late")
        paid = [x for x in self.sup.ok("bill_invoices") if x["id"] == second["id"]][0]
        self.assertEqual((paid["payment_status"], paid["payment_ref"]), ("paid", "UTR 4025"))
        self.assertEqual(self.pdf(self.hq, first["id"]).status_code, 200)         # a cancelled invoice can still be opened (it says CANCELLED)

    # ------------------------------------------------------------------ HQ invoices a buyer
    def test_hq_sells_its_stock_to_a_buyer(self):
        self.finalized_load()                                                     # HQ now holds 5 kg iron and 3 kg paper
        stock = {r["item_name"]: (D(r["received_kg"]), D(r["sold_kg"])) for r in self.hq.ok("hq_stock_summary")}
        self.assertEqual((stock["Iron"], stock["Paper"]), ((D(5), D(0)), (D(3), D(0))))
        self.sup.fail("hq_stock_summary", "Only HQ")
        self.sup.fail("hq_buyers", "Only HQ")
        self.sup.fail("hq_save_buyer", "Only HQ", p_name="Metro Recyclers")
        self.hq.fail("hq_save_buyer", "name", p_name=" ")
        self.hq.fail("hq_save_buyer", "GSTIN", p_name="Metro Recyclers", p_gstin="nope")
        buyer = self.hq.ok("hq_save_buyer", p_name="Metro Recyclers", p_gstin="32AAACM1234F1Z5", p_address="Industrial Estate, Aluva", p_state="Kerala")
        self.hq.fail("hq_save_buyer", "already exists", p_name="metro recyclers")
        self.assertEqual([b["name"] for b in self.hq.ok("hq_buyers")], ["Metro Recyclers"])
        line = lambda **kw: [{"item_id": self.iron, "kg": 4, "rate": 30, "gst_percent": 18, **kw}]
        self.sup.fail("bill_create_sale_invoice", "Only HQ", p_buyer_id=buyer, p_lines=line())
        self.hq.fail("bill_create_sale_invoice", "Choose the buyer", p_buyer_id=999, p_lines=line())
        self.hq.fail("bill_create_sale_invoice", "at least one", p_buyer_id=buyer, p_lines=[])
        self.hq.fail("bill_create_sale_invoice", "kg and the rate", p_buyer_id=buyer, p_lines=line(rate=0))
        self.hq.fail("bill_create_sale_invoice", "Not enough Iron in HQ stock. In hand: 5.0 kg", p_buyer_id=buyer, p_lines=line(kg=6))
        made = self.hq.ok("bill_create_sale_invoice", p_buyer_id=buyer, p_lines=line(), p_vehicle_no="KL 01 AB 1", p_note="first lot")
        self.assertEqual((made["code"], D(made["total"])), (f"HQ/{self.fy}/0001", D("141.60")))             # 4 x 30 = 120 + 18% = 141.60
        # what is left, and the same stock cannot be sold twice
        self.assertEqual({r["item_name"]: D(r["received_kg"]) - D(r["sold_kg"]) for r in self.hq.ok("hq_stock_summary")}["Iron"], D(1))
        self.hq.fail("bill_create_sale_invoice", "In hand: 1.0 kg", p_buyer_id=buyer, p_lines=line(kg=2))
        # the GST rate falls back to the material's own when the line leaves it out
        second = self.hq.ok("bill_create_sale_invoice", p_buyer_id=buyer, p_lines=[{"item_id": self.paper, "kg": 3, "rate": 10}])
        self.assertEqual((second["code"], D(second["total"])), (f"HQ/{self.fy}/0002", D("31.50")))          # 30 + 5%
        sale = [x for x in self.hq.ok("bill_invoices", p_kind="sale") if x["id"] == made["id"]][0]
        self.assertEqual((sale["buyer_name"], sale["vehicle_no"], sale["franchise_id"]), ("Metro Recyclers", "KL 01 AB 1", None))
        self.assertEqual(self.sup.ok("bill_invoices"), [])                         # a supervisor never sees HQ's sales
        self.assertEqual(self.pdf(self.hq, made["id"]).status_code, 200)
        self.assertEqual(self.pdf(self.sup, made["id"]).status_code, 404)
        # cancelling gives the stock back; paying locks the invoice
        self.hq.ok("bill_cancel_invoice", p_invoice_id=made["id"], p_reason="buyer backed out")
        self.assertEqual({r["item_name"]: D(r["received_kg"]) - D(r["sold_kg"]) for r in self.hq.ok("hq_stock_summary")}["Iron"], D(5))
        self.hq.ok("bill_mark_paid", p_invoice_id=second["id"])
        self.hq.fail("bill_cancel_invoice", "paid invoice", p_invoice_id=second["id"], p_reason="oops")
