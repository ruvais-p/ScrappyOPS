from decimal import Decimal

from core.models import CashLedger, ImmutableError, LoadWeighing, HqAudit
from core.tests.base import Api, ScrappyTestCase, today_dmy


class FullDay(ScrappyTestCase):
    """One collector's whole day, then the warehouse, HQ and cash side."""

    def setUp(self):
        super().setUp()
        self.make_team()
        self.hq, self.sup = Api(self.client, "hq@t.test"), Api(self.client, "sup@t.test")
        self.wh, self.drv = Api(self.client, "wh@t.test"), Api(self.client, "drv@t.test")
        rates = self.drv.rows("current_rates?select=item_id,item_name,rate_per_kg&order=item_id")
        self.item = {r["item_name"]: r for r in rates}
        self.iron, self.paper = self.item["Iron"]["item_id"], self.item["Paper"]["item_id"]

    def pickup(self, drv, name, phone, weights, method="upi", driver_email="drv@t.test"):
        """A complete pickup up to payment. Returns (lead_id, bill_id)."""
        self.upload_lead(self.hq, driver_email=driver_email, name=name, phone=phone)
        lead = [l for l in drv.ok("my_leads") if l["customer_name"] == name][0]
        bill_id = drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        for item_id, qty in weights.items():
            drv.ok("set_bill_item", p_bill_id=bill_id, p_item_id=item_id, p_qty_kg=qty, p_photo_url=None, p_typed=True)
        drv.ok("send_bill", p_bill_id=bill_id)
        drv.ok("mark_bill_shared", p_bill_id=bill_id)
        drv.ok("confirm_bill", p_bill_id=bill_id, p_proof_url=None)
        drv.ok("pay_bill", p_bill_id=bill_id, p_method=method, p_upi_ref="402512345678" if method == "upi" else None)
        return lead["lead_id"], bill_id

    # ------------------------------------------------------------------ the collector
    def test_collector_flow_step_by_step(self):
        row = self.upload_lead(self.hq)
        self.assertEqual(row["status"], "created")
        self.assertTrue(row["lead_code"].startswith("SC-"))
        leads = self.drv.ok("my_leads")
        self.assertEqual(len(leads), 1)
        lead = leads[0]
        self.assertEqual((lead["status"], lead["phone"], lead["customer_name"]), ("scheduled", "9446012345", "Anil Kumar"))
        self.assertIsNone(lead["bill_id"])

        bill_id = self.drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        self.assertEqual(self.drv.ok("start_pickup", p_lead_id=lead["lead_id"]), bill_id)       # pressing it twice changes nothing
        self.drv.ok("set_bill_item", p_bill_id=bill_id, p_item_id=self.iron, p_qty_kg=10, p_photo_url=None, p_typed=True)
        self.drv.ok("set_bill_item", p_bill_id=bill_id, p_item_id=self.paper, p_qty_kg=5.5, p_photo_url=None, p_typed=True)
        items = {i["item_id"]: i for i in self.drv.rows(f"bill_items?select=item_id,qty_kg,rate_per_kg,amount&bill_id=eq.{bill_id}")}
        self.assertEqual(items[self.iron]["amount"], 280)           # 10 kg at the HQ rate of 28: the driver cannot choose a rate
        self.assertEqual(items[self.paper]["amount"], 55)
        # changing a weight, and clearing a line with 0
        self.drv.ok("set_bill_item", p_bill_id=bill_id, p_item_id=self.paper, p_qty_kg=4, p_photo_url=None, p_typed=True)
        self.drv.ok("set_bill_item", p_bill_id=bill_id, p_item_id=self.paper, p_qty_kg=0, p_photo_url=None, p_typed=True)
        self.assertEqual(len(self.drv.rows(f"bill_items?select=item_id&bill_id=eq.{bill_id}")), 1)
        self.drv.ok("set_bill_item", p_bill_id=bill_id, p_item_id=self.paper, p_qty_kg=5.5, p_photo_url=None, p_typed=True)
        self.drv.fail("set_bill_item", "between 0 and 100000", p_bill_id=bill_id, p_item_id=self.paper, p_qty_kg=-3, p_photo_url=None, p_typed=True)
        self.drv.fail("set_bill_item", "Unknown material", p_bill_id=bill_id, p_item_id=9999, p_qty_kg=1, p_photo_url=None, p_typed=True)

        self.drv.fail("confirm_bill", "Send the bill to the customer first", p_bill_id=bill_id, p_proof_url=None)
        self.drv.fail("bill_whatsapp", "must be locked", p_bill_id=bill_id)
        sent = self.drv.ok("send_bill", p_bill_id=bill_id)[0]
        self.assertEqual(sent["whatsapp_number"], "919446012345")
        self.drv.fail("send_bill", "already been sent", p_bill_id=bill_id)
        self.drv.fail("set_bill_item", "locked", p_bill_id=bill_id, p_item_id=self.iron, p_qty_kg=3, p_photo_url=None, p_typed=True)

        msg = self.drv.ok("bill_whatsapp", p_bill_id=bill_id)[0]["message"]
        self.assertIn("Hi Anil, thank you for choosing Scrappy!", msg)
        self.assertIn("Weight: 15.5 kg", msg)
        self.assertIn("You will receive: *Rs 335*", msg)
        self.drv.fail("confirm_bill", "WhatsApp first", p_bill_id=bill_id, p_proof_url=None)       # cannot be agreed before it was sent
        self.drv.ok("mark_bill_shared", p_bill_id=bill_id)
        self.drv.ok("confirm_bill", p_bill_id=bill_id, p_proof_url=None)

        self.drv.fail("pay_bill", "Not enough cash in hand", p_bill_id=bill_id, p_method="cash", p_upi_ref=None)
        self.drv.fail("pay_bill", "UTR", p_bill_id=bill_id, p_method="upi", p_upi_ref="123")
        self.drv.fail("pay_bill", "Choose UPI or cash", p_bill_id=bill_id, p_method="cheque", p_upi_ref=None)
        self.assertEqual(self.wh.ok("issue_float", p_driver_id=self.drv.uid, p_amount=1000, p_note=None), 1000)
        self.drv.ok("pay_bill", p_bill_id=bill_id, p_method="cash", p_upi_ref=None)
        cash = self.drv.rows(f"driver_cash_in_hand?select=cash_in_hand&driver_id=eq.{self.drv.uid}")
        self.assertEqual(cash[0]["cash_in_hand"], 665)
        self.assertEqual(self.drv.ok("my_leads")[0]["status"], "closed")
        self.drv.fail("pay_bill", "must confirm", p_bill_id=bill_id, p_method="cash", p_upi_ref=None)      # no paying twice

        code = self.drv.ok("end_route")
        self.assertEqual(code, "LD-0001")
        self.drv.fail("end_route", "no open load")

    def test_a_collector_cannot_touch_someone_elses_bill(self):
        _lead, bill = self.pickup(self.drv, "Anil", "9446012345", {self.iron: 4})
        other = Api(self.client, "drv2@t.test")
        other.fail("send_bill", "not yours", p_bill_id=bill)
        other.fail("set_bill_item", "not yours", p_bill_id=bill, p_item_id=self.iron, p_qty_kg=1, p_photo_url=None, p_typed=True)
        self.assertEqual(other.rows(f"bill_items?select=id&bill_id=eq.{bill}"), [])      # and cannot even read it

    def test_could_not_complete(self):
        self.upload_lead(self.hq)
        lead = self.drv.ok("my_leads")[0]
        self.drv.fail("fail_pickup", "Choose a reason", p_lead_id=lead["lead_id"], p_reason="because", p_note=None)
        self.drv.fail("fail_pickup", "short note", p_lead_id=lead["lead_id"], p_reason="Other", p_note=None)
        bill = self.drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        self.drv.ok("set_bill_item", p_bill_id=bill, p_item_id=self.iron, p_qty_kg=2, p_photo_url=None, p_typed=True)
        self.drv.ok("fail_pickup", p_lead_id=lead["lead_id"], p_reason="Customer not at home", p_note=None)
        again = self.drv.ok("my_leads")[0]
        self.assertEqual((again["status"], again["fail_reason"], again["bill_id"]), ("failed", "Customer not at home", None))
        self.assertEqual(self.drv.rows("loads?select=id"), [])           # the route that was started only for it is gone
        self.assertTrue(HqAudit.objects.filter(action="lead_failed").exists())
        self.drv.fail("start_pickup", "already failed", p_lead_id=lead["lead_id"])
        # a bill that was already sent cannot be thrown away
        self.upload_lead(self.hq, name="Second", phone="9446099999")
        l2 = [l for l in self.drv.ok("my_leads") if l["customer_name"] == "Second"][0]
        b2 = self.drv.ok("start_pickup", p_lead_id=l2["lead_id"])
        self.drv.ok("set_bill_item", p_bill_id=b2, p_item_id=self.iron, p_qty_kg=2, p_photo_url=None, p_typed=True)
        self.drv.ok("send_bill", p_bill_id=b2)
        self.drv.fail("fail_pickup", "already sent", p_lead_id=l2["lead_id"], p_reason="Customer cancelled", p_note=None)
        self.drv.fail("end_route", "Finish or pay", )

    # ------------------------------------------------------------------ warehouse and stock
    def test_weighing_stock_requirements_and_releases(self):
        self.pickup(self.drv, "Anil", "9446012345", {self.iron: 10, self.paper: 5.5})
        self.drv.ok("end_route")
        load = self.wh.rows("loads?select=id,code,status&order=id.desc")[0]
        self.assertEqual(load["status"], "submitted")
        self.wh.fail("record_load_weighing", "Enter the weight for", p_load_id=load["id"], p_weights=[{"item_id": self.iron, "kg": 10}], p_note=None)
        self.wh.fail("record_load_weighing", "Each material", p_load_id=load["id"], p_weights=[{"item_id": self.iron, "kg": 10}, {"item_id": self.iron, "kg": 9}], p_note=None)
        self.wh.fail("record_load_weighing", "Unknown material", p_load_id=load["id"], p_weights=[{"item_id": 9999, "kg": 10}], p_note=None)
        self.drv.fail("record_load_weighing", "Only warehouse staff", p_load_id=load["id"], p_weights=[{"item_id": self.iron, "kg": 10}], p_note=None)
        res = self.wh.ok("record_load_weighing", p_load_id=load["id"], p_note=None,
                         p_weights=[{"item_id": self.iron, "kg": 10.1}, {"item_id": self.paper, "kg": 5.5}])
        self.assertEqual(res["status"], "reconciled")                    # 1% off is inside the 2% tolerance
        self.assertEqual(res["tolerance_pct"], 2)
        self.wh.fail("record_load_weighing", "not waiting for weighing", p_load_id=load["id"], p_note=None,
                     p_weights=[{"item_id": self.iron, "kg": 10}, {"item_id": self.paper, "kg": 5.5}])
        today = today_dmy()
        iso = "-".join(reversed(today.split("-")))
        stock = {r["item_name"]: r for r in self.wh.ok("wh_stock_report", p_from=iso, p_to=iso)}
        self.assertEqual(stock["Iron"]["stock_now_kg"], 10.1)
        self.assertEqual(stock["Iron"]["received_kg"], 10.1)

        req = self.hq.ok("raise_requirement", p_item_id=self.iron, p_required_kg=8, p_due_date=None, p_note="for the mill", p_franchise=self.kkd.pk)
        self.assertEqual(req, "RQ-0001")
        self.wh.fail("raise_requirement", "Only HQ", p_item_id=self.iron, p_required_kg=1, p_due_date=None, p_note=None, p_franchise=self.kkd.pk)
        prog = self.wh.rows("hq_requirement_progress?select=*&order=id.desc")[0]
        self.assertEqual((prog["status"], prog["remaining_kg"]), ("open", 8))
        self.wh.fail("release_to_hq", "Only warehouse staff", p_requirement_id=prog["id"], p_kg=1, p_vehicle_no="KL 1", p_note=None)  # supervisor's job now
        self.sup.fail("release_to_hq", "HQ only needs 8.0 kg", p_requirement_id=prog["id"], p_kg=9, p_vehicle_no="KL 1", p_note=None)
        self.sup.fail("release_to_hq", "vehicle", p_requirement_id=prog["id"], p_kg=3, p_vehicle_no="", p_note=None)
        self.assertEqual(self.sup.ok("release_to_hq", p_requirement_id=prog["id"], p_kg=5, p_vehicle_no="KL 01 AA 1", p_note=None), "RL-0301")
        self.assertEqual(self.wh.rows("hq_requirement_progress?select=status,released_kg")[0]["status"], "partial")
        self.sup.ok("release_to_hq", p_requirement_id=prog["id"], p_kg=3, p_vehicle_no="KL 01 AA 1", p_note=None)
        self.assertEqual(self.wh.rows("hq_requirement_progress?select=status")[0]["status"], "completed")
        self.sup.fail("release_to_hq", "HQ only needs 0.0", p_requirement_id=prog["id"], p_kg=1, p_vehicle_no="KL 1", p_note=None)

        # stock can never go below zero: ask for more than is left (2.1 kg) in a new request
        req2 = self.hq.ok("raise_requirement", p_item_id=self.iron, p_required_kg=50, p_due_date=None, p_note=None, p_franchise=self.kkd.pk)
        rid = [r for r in self.wh.rows("hq_requirement_progress?select=id,code") if r["code"] == req2][0]["id"]
        self.sup.fail("release_to_hq", "Not enough stock. In the yard: 2.1 kg", p_requirement_id=rid, p_kg=10, p_vehicle_no="KL 1", p_note=None)
        self.hq.ok("cancel_requirement", p_requirement_id=rid, p_note="not needed")
        self.sup.fail("release_to_hq", "cancelled", p_requirement_id=rid, p_kg=1, p_vehicle_no="KL 1", p_note=None)
        self.hq.fail("cancel_requirement", "already cancelled", p_requirement_id=rid, p_note="again")
        # records of what left the yard can never be edited
        self.assertEqual(len(self.hq.rows("hq_releases?select=code,kg,vehicle_no&order=id.asc")), 2)

    def test_flagged_load_and_hq_decision(self):
        self.pickup(self.drv, "Anil", "9446012345", {self.iron: 10})
        self.drv.ok("end_route")
        load = self.wh.rows("loads?select=id")[0]["id"]
        res = self.wh.ok("record_load_weighing", p_load_id=load, p_note="scale 2", p_weights=[{"item_id": self.iron, "kg": 8}])
        self.assertEqual(res["status"], "flagged")
        self.assertEqual(res["items"][0]["diff_pct"], -20)
        self.wh.fail("resolve_flagged_load", "Only HQ", p_load_id=load, p_action="accept", p_note="ok")
        self.hq.fail("resolve_flagged_load", "note", p_load_id=load, p_action="accept", p_note=" ")
        self.hq.ok("resolve_flagged_load", p_load_id=load, p_action="reweigh", p_note="weigh again")
        self.assertEqual(self.wh.rows(f"loads?select=status&id=eq.{load}")[0]["status"], "submitted")
        history = LoadWeighing.objects.filter(load_id=load)
        self.assertEqual((history.count(), history.filter(superseded_at__isnull=True).count()), (1, 0))   # history is kept
        res = self.wh.ok("record_load_weighing", p_load_id=load, p_note=None, p_weights=[{"item_id": self.iron, "kg": 7}])
        self.assertEqual(res["status"], "flagged")
        self.hq.ok("resolve_flagged_load", p_load_id=load, p_action="accept", p_note="customer had less")
        self.assertEqual(self.wh.rows(f"loads?select=status&id=eq.{load}")[0]["status"], "reconciled")
        self.hq.fail("resolve_flagged_load", "not flagged", p_load_id=load, p_action="accept", p_note="x")

    def test_reweigh_blocked_when_stock_already_left(self):
        self.pickup(self.drv, "Anil", "9446012345", {self.iron: 10})
        self.drv.ok("end_route")
        load = self.wh.rows("loads?select=id")[0]["id"]
        self.wh.ok("record_load_weighing", p_load_id=load, p_note=None, p_weights=[{"item_id": self.iron, "kg": 8}])      # flagged, 8 kg in yard
        self.hq.ok("raise_requirement", p_item_id=self.iron, p_required_kg=8, p_due_date=None, p_note=None, p_franchise=self.kkd.pk)
        rid = self.wh.rows("hq_requirement_progress?select=id")[0]["id"]
        self.sup.ok("release_to_hq", p_requirement_id=rid, p_kg=8, p_vehicle_no="KL 01", p_note=None)
        self.hq.fail("resolve_flagged_load", "already been released", p_load_id=load, p_action="reweigh", p_note="again")

    # ------------------------------------------------------------------ cash
    def test_cash_count_and_verification_rules(self):
        self.wh.ok("issue_float", p_driver_id=self.drv.uid, p_amount=2000, p_note="morning float")
        self.pickup(self.drv, "Anil", "9446012345", {self.iron: 10}, method="cash")        # pays 280 in cash
        self.pickup(self.drv, "Bindu", "9446012346", {self.iron: 5}, method="upi")         # 140 by UPI
        self.wh.fail("count_route_cash", "not ended this route", p_load_id=self.wh.rows("loads?select=id")[0]["id"], p_counted=1720, p_note=None)
        self.drv.ok("end_route")
        load = self.wh.rows("loads?select=id,code")[0]
        self.wh.fail("count_route_cash", "Enter the cash you counted", p_load_id=load["id"], p_counted=-5, p_note=None)
        self.wh.fail("count_route_cash", "differs from the expected ₹1720", p_load_id=load["id"], p_counted=1700, p_note=None)
        res = self.wh.ok("count_route_cash", p_load_id=load["id"], p_counted=1700, p_note="₹20 note torn")
        self.assertEqual((res["expected"], res["counted"], res["difference"], res["status"]), (1720, 1700, -20, "counted"))
        self.assertEqual(self.drv.rows(f"driver_cash_in_hand?select=cash_in_hand&driver_id=eq.{self.drv.uid}")[0]["cash_in_hand"], 0)
        self.wh.fail("count_route_cash", "already counted", p_load_id=load["id"], p_counted=1700, p_note="x")
        sid = res["settlement_id"]
        self.wh.fail("verify_settlement", "Only a supervisor", p_settlement_id=sid, p_decision="verify", p_note="ok")
        self.sup.fail("verify_settlement", "note", p_settlement_id=sid, p_decision="verify", p_note=None)       # there is a difference
        self.sup.fail("verify_settlement", "verify or dispute", p_settlement_id=sid, p_decision="maybe", p_note="x")
        self.assertEqual(self.sup.ok("verify_settlement", p_settlement_id=sid, p_decision="dispute", p_note="Torn note, driver says 20 short"), "disputed")
        self.sup.fail("verify_settlement", "already disputed", p_settlement_id=sid, p_decision="verify", p_note="x")

        disputes = self.hq.ok("hq_open_disputes")
        self.assertEqual((len(disputes), disputes[0]["difference"]), (1, -20))
        self.assertEqual(self.hq.ok("hq_overview", p_from="2020-01-01", p_to="2099-01-01")["disputes_open"], 1)
        self.sup.fail("hq_resolve_dispute", "HQ only", p_settlement_id=sid, p_decision="write_off", p_note="x")
        self.hq.fail("hq_resolve_dispute", "Choose what happens", p_settlement_id=sid, p_decision="nothing", p_note="x")
        self.assertEqual(self.hq.ok("hq_resolve_dispute", p_settlement_id=sid, p_decision="write_off", p_note="small"), "write_off")
        self.hq.fail("hq_resolve_dispute", "already been resolved", p_settlement_id=sid, p_decision="write_off", p_note="again")
        self.assertEqual(self.hq.ok("hq_open_disputes"), [])

    def test_person_who_counted_cannot_verify(self):
        self.pickup(self.drv, "Anil", "9446012345", {self.iron: 10}, method="upi")
        self.drv.ok("end_route")
        load = self.hq.rows("loads?select=id")[0]["id"]
        res = self.hq.ok("count_route_cash", p_load_id=load, p_counted=0, p_note=None)       # HQ counted
        self.hq.fail("verify_settlement", "cannot verify it", p_settlement_id=res["settlement_id"], p_decision="verify", p_note=None)
        self.assertEqual(self.sup.ok("verify_settlement", p_settlement_id=res["settlement_id"], p_decision="verify", p_note=None), "verified")

    def test_one_count_covers_all_routes_of_the_day(self):
        self.wh.ok("issue_float", p_driver_id=self.drv.uid, p_amount=1000, p_note=None)
        self.pickup(self.drv, "Anil", "9446012345", {self.iron: 10}, method="cash")          # 280
        self.drv.ok("end_route")
        self.pickup(self.drv, "Bindu", "9446012346", {self.iron: 5}, method="cash")          # 140
        loads = self.wh.rows("loads?select=id,code&order=id.asc")
        self.wh.fail("count_route_cash", "still has a route on the road", p_load_id=loads[0]["id"], p_counted=1, p_note="x")
        self.drv.ok("end_route")
        self.wh.fail("count_route_cash", "latest route (LD-0002)", p_load_id=loads[0]["id"], p_counted=1, p_note="x")
        res = self.wh.ok("count_route_cash", p_load_id=loads[1]["id"], p_counted=580, p_note=None)
        self.assertEqual(res["routes"], "LD-0001, LD-0002")
        rc = {r["load_code"]: r for r in self.wh.ok("wh_route_cash", p_from="2020-01-01", p_to="2099-01-01")}
        self.assertEqual(rc["LD-0001"]["route_status"], "included")
        self.assertEqual(rc["LD-0002"]["route_status"], "counted")
        self.assertEqual(rc["LD-0002"]["cash_paid"], 420)

    def test_cash_ledger_cannot_be_edited(self):
        self.wh.ok("issue_float", p_driver_id=self.drv.uid, p_amount=500, p_note=None)
        entry = CashLedger.objects.get()
        entry.amount = 99999
        with self.assertRaises(ImmutableError):
            entry.save()
        with self.assertRaises(ImmutableError):
            CashLedger.objects.all().delete()
        with self.assertRaises(ImmutableError):
            CashLedger.objects.update(amount=1)
        # and the database itself refuses, even for a raw edit
        from django.db import connection, transaction
        with self.assertRaises(Exception):
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("update cash_ledger set amount = 1")
        self.wh.fail("issue_float", "between 1 and 500000", p_driver_id=self.drv.uid, p_amount=600000, p_note=None)
        self.wh.fail("issue_float", "not an active driver", p_driver_id=self.sup.uid, p_amount=10, p_note=None)

    def test_old_cash_shortcut_is_off(self):
        self.wh.fail("receive_cash", "cash count", p_driver_id=self.drv.uid, p_amount=10)
        self.wh.fail("record_weighing", "record_load_weighing", p_load_id=1, p_warehouse_kg=10)
