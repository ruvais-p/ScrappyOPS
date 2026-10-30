"""Stock going to HQ on a vehicle: the warehouse manager enters the quantity of each material, the supervisor finalizes it,
HQ sets the price it pays, and only the supervisor (and HQ) can see prices."""
from decimal import Decimal

from core.models import HqAudit, HqRelease
from core.tests.base import Api, ScrappyTestCase


class DispatchBase(ScrappyTestCase):
    """A franchise with 10 kg of iron and 5.5 kg of paper in the yard and HQ requests for iron and paper."""

    def setUp(self):
        super().setUp()
        self.make_team()
        self.hq, self.sup = Api(self.client, "hq@t.test"), Api(self.client, "sup@t.test")
        self.wh, self.drv = Api(self.client, "wh@t.test"), Api(self.client, "drv@t.test")
        rates = self.drv.rows("current_rates?select=item_id,item_name,rate_per_kg&order=item_id")
        item = {r["item_name"]: r["item_id"] for r in rates}
        self.iron, self.paper = item["Iron"], item["Paper"]
        # 10 kg iron and 5.5 kg paper reach the yard
        self.upload_lead(self.hq, name="Anil", phone="9446012345")
        lead = self.drv.ok("my_leads")[0]
        bill = self.drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        for i, q in ((self.iron, 10), (self.paper, 5.5)):
            self.drv.ok("set_bill_item", p_bill_id=bill, p_item_id=i, p_qty_kg=q, p_photo_url=None, p_typed=True)
        self.drv.ok("send_bill", p_bill_id=bill)
        self.drv.ok("mark_bill_shared", p_bill_id=bill)
        self.drv.ok("confirm_bill", p_bill_id=bill, p_proof_url=None)
        self.drv.ok("pay_bill", p_bill_id=bill, p_method="upi", p_upi_ref="402512345678")
        self.drv.ok("end_route")
        load = self.wh.rows("loads?select=id&order=id.desc")[0]
        self.wh.ok("record_load_weighing", p_load_id=load["id"], p_note=None,
                   p_weights=[{"item_id": self.iron, "kg": 10}, {"item_id": self.paper, "kg": 5.5}])
        self.rq_iron = self.request(self.iron, 8)
        self.rq_paper = self.request(self.paper, 4)

    def request(self, item, kg):
        code = self.hq.ok("raise_requirement", p_item_id=item, p_required_kg=kg, p_due_date=None, p_note=None, p_franchise=self.kkd.pk)
        return [r for r in self.wh.rows("hq_requirement_progress?select=id,code") if r["code"] == code][0]["id"]

    def lines(self, iron=5, paper=3):
        return [{"requirement_id": self.rq_iron, "kg": iron}, {"requirement_id": self.rq_paper, "kg": paper}]

    def set_prices(self):
        self.hq.ok("hq_set_buy_rate", p_item_id=self.iron, p_rate=20.5)
        self.hq.ok("hq_set_buy_rate", p_item_id=self.paper, p_rate=8)


class DispatchFlow(DispatchBase):
    def test_requestless_load_validates_precision_and_franchise(self):
        self.wh.fail("wh_submit_dispatch", "at most", p_lines=[{"item_id": self.paper, "kg": 1}] * 101, p_vehicle_no="KL 1")
        for line, message in ((42, "object"), ({"item_id": self.paper, "kg": "0.0004"}, "decimal places"),
                              ({"item_id": 1.5, "kg": 1}, "valid request")):
            self.wh.fail("wh_submit_dispatch", message, p_lines=[line], p_vehicle_no="KL 1")
        self.hq.fail("wh_submit_dispatch", "active franchise", p_lines=[{"item_id": self.paper, "kg": 1}],
                     p_vehicle_no="KL 1", p_franchise_id=99999)
        self.hq.ok("wh_submit_dispatch", p_lines=[{"item_id": self.paper, "kg": 1}], p_vehicle_no="KL 1", p_franchise_id=str(self.kkd.pk))
        load = self.hq.ok("wh_dispatches")[0]
        self.hq.ok("wh_submit_dispatch", p_lines=[{"item_id": self.paper, "kg": 2}], p_vehicle_no="KL 2",
                   p_franchise_id=str(self.kkd.pk), p_dispatch_id=load["id"])
        self.assertEqual(self.hq.ok("wh_dispatches")[0]["total_kg"], 2)

    # ------------------------------------------------------------------ the whole path
    def test_warehouse_prepares_supervisor_finalizes_at_hq_price(self):
        self.set_prices()
        code = self.wh.ok("wh_submit_dispatch", p_lines=self.lines(), p_vehicle_no="KL 07 HQ 1", p_note="first load")
        self.assertEqual(code, "DP-0001")
        # nothing has left the yard yet
        self.assertEqual(self.hq.rows("hq_releases?select=id"), [])
        mine = self.wh.ok("wh_dispatches")[0]
        self.assertEqual((mine["status"], mine["vehicle_no"], len(mine["lines"])), ("pending", "KL 07 HQ 1", 2))
        self.assertEqual(Decimal(str(mine["total_kg"])), Decimal("8"))
        # the warehouse manager never sees a price
        self.assertTrue(all("price_per_kg" not in x and "amount" not in x and "expected_amount" not in x for x in mine["lines"]))
        self.assertNotIn("total_amount", mine)
        # the supervisor sees what it would be worth at today's price
        seen = self.sup.ok("wh_dispatches", p_status="pending")[0]
        self.assertEqual(Decimal(str(seen["total_amount"])), Decimal("126.50"))
        # sent back, corrected, sent again
        self.sup.fail("sup_review_dispatch", "reason", p_dispatch_id=mine["id"], p_decision="reject", p_note="")
        self.sup.ok("sup_review_dispatch", p_dispatch_id=mine["id"], p_decision="reject", p_note="Paper weight looks wrong")
        again = self.wh.ok("wh_dispatches", p_status="rejected")[0]
        self.assertEqual(again["review_note"], "Paper weight looks wrong")
        self.sup.fail("sup_review_dispatch", "not waiting", p_dispatch_id=mine["id"], p_decision="finalize")
        self.wh.ok("wh_submit_dispatch", p_dispatch_id=mine["id"], p_lines=self.lines(5, 2.5), p_vehicle_no="KL 07 HQ 1", p_note=None)
        # the supervisor finalizes
        res = self.sup.ok("sup_review_dispatch", p_dispatch_id=mine["id"], p_decision="finalize", p_note=None)
        self.assertEqual(res["status"], "finalized")
        self.assertEqual(Decimal(str(res["amount"])), Decimal("122.50"))              # 5 x 20.50 + 2.5 x 8
        self.assertEqual(sorted(r.kg for r in HqRelease.objects.all()), [Decimal("2.500"), Decimal("5.000")])
        self.assertEqual({r["status"]: r["released_kg"] for r in self.wh.rows("hq_requirement_progress?select=status,released_kg&order=id.asc")[:1]},
                         {"partial": 5})
        self.assertTrue(HqAudit.objects.filter(action="dispatch_finalized", ref="DP-0001").exists())
        # a price change later does not touch a finalized load
        self.hq.ok("hq_set_buy_rate", p_item_id=self.iron, p_rate=30)
        done = self.sup.ok("wh_dispatches", p_status="finalized")[0]
        self.assertEqual(Decimal(str(done["total_amount"])), Decimal("122.50"))
        self.assertEqual({x["item_name"]: Decimal(str(x["price_per_kg"])) for x in done["lines"]}, {"Iron": Decimal("20.50"), "Paper": Decimal("8.00")})
        self.wh.fail("wh_withdraw_dispatch", "already been finalized", p_dispatch_id=mine["id"])
        # the supervisor's section: stock, price per kg, value
        sv = self.sup.ok("sup_stock_value")
        row = {r["item_name"]: r for r in sv["items"]}
        self.assertEqual((Decimal(str(row["Iron"]["stock_kg"])), Decimal(str(row["Iron"]["price_per_kg"])), Decimal(str(row["Iron"]["value"]))),
                         (Decimal("5"), Decimal("30.00"), Decimal("150.00")))
        self.assertEqual(Decimal(str(sv["sold_amount"])), Decimal("122.50"))
        self.assertEqual((sv["sold_loads"], sv["pending_loads"]), (1, 0))

    # ------------------------------------------------------------------ who may do what
    def test_only_the_right_person_can_do_each_step(self):
        self.drv.fail("wh_submit_dispatch", "warehouse manager", p_lines=self.lines(), p_vehicle_no="KL 1")
        self.sup.fail("wh_submit_dispatch", "warehouse manager", p_lines=self.lines(), p_vehicle_no="KL 1")
        self.wh.fail("hq_set_buy_rate", "Only HQ", p_item_id=self.iron, p_rate=10)
        self.sup.fail("hq_set_buy_rate", "Only HQ", p_item_id=self.iron, p_rate=10)
        self.wh.fail("sup_stock_value", "supervisor")                                  # prices are not for the warehouse manager
        self.drv.fail("sup_stock_value", "supervisor")
        self.wh.fail("sup_review_dispatch", "supervisor", p_dispatch_id=1, p_decision="finalize")
        self.wh.fail("wh_submit_dispatch", "vehicle", p_lines=self.lines(), p_vehicle_no=" ")
        self.wh.fail("wh_submit_dispatch", "at least one", p_lines=[], p_vehicle_no="KL 1")
        self.wh.fail("wh_submit_dispatch", "listed twice", p_lines=self.lines() + [{"requirement_id": self.rq_iron, "kg": 1}], p_vehicle_no="KL 1")
        code = self.wh.ok("wh_submit_dispatch", p_lines=self.lines(), p_vehicle_no="KL 1")
        d = self.wh.ok("wh_dispatches")[0]
        # no price set for HQ's purchase yet: the supervisor is told to ask HQ
        self.sup.fail("sup_review_dispatch", "has not set the price", p_dispatch_id=d["id"], p_decision="finalize")
        self.set_prices()
        # another franchise's people cannot see or touch it
        tsup, twh = Api(self.client, "tvm-sup@t.test"), Api(self.client, "tvm-wh@t.test")
        self.assertEqual(tsup.ok("wh_dispatches"), [])
        tsup.fail("sup_review_dispatch", "not found", p_dispatch_id=d["id"], p_decision="finalize")
        twh.fail("wh_withdraw_dispatch", "not found", p_dispatch_id=d["id"])
        # HQ prepared it itself: a different person must approve
        d2 = self.hq.ok("wh_submit_dispatch", p_lines=[{"requirement_id": self.rq_iron, "kg": 1}], p_vehicle_no="KL 2")
        self.assertEqual(d2, "DP-0002")
        hq_id = [x for x in self.hq.ok("wh_dispatches") if x["code"] == d2][0]["id"]
        self.hq.fail("sup_review_dispatch", "different person", p_dispatch_id=hq_id, p_decision="finalize")
        self.sup.ok("sup_review_dispatch", p_dispatch_id=hq_id, p_decision="finalize")
        self.assertEqual(code, "DP-0001")
        self.wh.ok("wh_withdraw_dispatch", p_dispatch_id=d["id"], p_note="vehicle did not come")
        self.assertEqual(self.wh.ok("wh_dispatches", p_status="withdrawn")[0]["code"], "DP-0001")

    # ------------------------------------------------------------------ loading without an HQ request
    def test_a_load_can_go_to_hq_without_a_request(self):
        self.set_prices()
        # paper only: nobody asked for this load, and the yard holds 5.5 kg of it
        self.wh.fail("wh_submit_dispatch", "Every line", p_lines=[{"item_id": self.paper, "requirement_id": self.rq_paper, "kg": 1}], p_vehicle_no="KL 9")
        self.wh.fail("wh_submit_dispatch", "Not enough Paper", p_lines=[{"item_id": self.paper, "kg": 6}], p_vehicle_no="KL 9")
        self.wh.fail("wh_submit_dispatch", "listed twice", p_lines=[{"item_id": self.paper, "kg": 1}, {"item_id": self.paper, "kg": 1}], p_vehicle_no="KL 9")
        self.wh.fail("wh_submit_dispatch", "Unknown material", p_lines=[{"item_id": 99999, "kg": 1}], p_vehicle_no="KL 9")
        code = self.wh.ok("wh_submit_dispatch", p_lines=[{"item_id": self.paper, "kg": 2}, {"requirement_id": self.rq_iron, "kg": 3}], p_vehicle_no="KL 9")
        d = [x for x in self.sup.ok("wh_dispatches") if x["code"] == code][0]
        by = {x["item_name"]: x for x in d["lines"]}
        self.assertEqual((by["Paper"]["requirement_id"], by["Paper"]["requirement_code"]), (None, None))
        self.assertIsNotNone(by["Iron"]["requirement_id"])
        # the waiting load holds the paper: only 3.5 kg is left to promise
        self.wh.fail("wh_submit_dispatch", "Not enough Paper", p_lines=[{"item_id": self.paper, "kg": 4}], p_vehicle_no="KL 10")
        self.sup.ok("sup_review_dispatch", p_dispatch_id=d["id"], p_decision="finalize")
        rels = self.hq.rows("hq_releases?select=requirement_id,item_id,kg&order=id")
        self.assertEqual(sorted((r["requirement_id"] is None, Decimal(str(r["kg"]))) for r in rels), [(False, Decimal("3")), (True, Decimal("2"))])
        # the stock left the yard, and HQ's open request for paper is untouched
        prog = {r["id"]: r for r in self.hq.rows("hq_requirement_progress?select=id,released_kg")}
        self.assertEqual(Decimal(str(prog[self.rq_paper]["released_kg"])), Decimal("0"))
        # only HQ has to say which franchise when the load names no request
        self.hq.fail("wh_submit_dispatch", "Choose the franchise", p_lines=[{"item_id": self.paper, "kg": 1}], p_vehicle_no="KL 11")
        self.hq.ok("wh_submit_dispatch", p_lines=[{"item_id": self.paper, "kg": 1}], p_vehicle_no="KL 11", p_franchise_id=self.kkd.pk)

    # ------------------------------------------------------------------ stock cannot be promised twice
    def test_two_waiting_loads_cannot_promise_the_same_stock(self):
        self.wh.fail("wh_submit_dispatch", "HQ only needs 8.0 kg", p_lines=[{"requirement_id": self.rq_iron, "kg": 9}], p_vehicle_no="KL 1")
        self.wh.fail("wh_submit_dispatch", "Every line", p_lines=[{"requirement_id": self.rq_iron, "kg": 0}], p_vehicle_no="KL 1")
        self.wh.ok("wh_submit_dispatch", p_lines=[{"requirement_id": self.rq_iron, "kg": 6}], p_vehicle_no="KL 1")
        # 6 kg of the 8 kg HQ asked for are already on a load waiting for the supervisor
        self.wh.fail("wh_submit_dispatch", "HQ only needs 2.0 kg", p_lines=[{"requirement_id": self.rq_iron, "kg": 3}], p_vehicle_no="KL 2")
        self.wh.ok("wh_submit_dispatch", p_lines=[{"requirement_id": self.rq_iron, "kg": 2}], p_vehicle_no="KL 2")
        # more than is in the yard: a bigger request for paper (only 5.5 kg weighed in)
        big = self.request(self.paper, 50)
        self.wh.fail("wh_submit_dispatch", "Not enough Paper", p_lines=[{"requirement_id": big, "kg": 6}], p_vehicle_no="KL 3")
        # cancelling a request stops a waiting load from being finalized
        self.hq.ok("cancel_requirement", p_requirement_id=self.rq_iron, p_note="not needed")
        self.set_prices()
        first = self.sup.ok("wh_dispatches", p_status="pending")[-1]
        self.sup.fail("sup_review_dispatch", "cancelled", p_dispatch_id=first["id"], p_decision="finalize")
