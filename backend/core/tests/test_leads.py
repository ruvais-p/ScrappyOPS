import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.models import Customer, Franchise, Lead, LeadImport
from core.tests.base import Api, ScrappyTestCase, today_dmy

IST = ZoneInfo("Asia/Kolkata")


class LeadUploadTests(ScrappyTestCase):
    def setUp(self):
        super().setUp()
        self.make_team()
        self.hq = Api(self.client, "hq@t.test")

    def send(self, *rows):
        r = self.client.post("/rest/v1/lead_import", data=json.dumps(list(rows)), content_type="application/json",
                             HTTP_PREFER="return=representation", **self.hq.h)
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def row(self, **kw):
        base = {"customer_name": "Anil Kumar", "phone": "9446012345", "address": "12 Test Road", "area": "Kakkanad",
                "driver_email": "drv@t.test", "pickup_date": today_dmy(), "pickup_time": "11:30 AM", "items": "iron"}
        base.update(kw)
        return base

    def test_good_row_goes_to_the_franchise_not_to_a_driver(self):
        out = self.send(self.row(driver_email=None, franchise_code="KKD"))[0]
        self.assertEqual((out["status"], out["message"]),
                         ("created", "Created, waiting for the supervisor to assign a driver (no map location)"))
        lead = Lead.objects.get(code=out["lead_code"])
        self.assertEqual((lead.status, lead.franchise.code, lead.driver_id), ("unassigned", "KKD", None))
        self.assertEqual(lead.slot.astimezone(IST).strftime("%H:%M"), "11:30")

    def test_a_driver_email_in_the_file_is_ignored(self):
        out = self.send(self.row(franchise_code="KKD"))[0]               # row() names drv@t.test
        self.assertEqual(out["status"], "created")
        self.assertIn("driver_email ignored", out["message"])
        lead = Lead.objects.get(code=out["lead_code"])
        self.assertEqual((lead.status, lead.driver_id), ("unassigned", None))

    def test_a_row_without_a_franchise_waits_for_hq(self):
        out = self.send(self.row(driver_email=None))[0]
        self.assertEqual(out["status"], "created")
        self.assertIn("waiting for HQ to give it to a franchise", out["message"])
        lead = Lead.objects.get(code=out["lead_code"])
        self.assertEqual((lead.status, lead.franchise_id, lead.driver_id), ("unassigned", None, None))

    def test_row_for_a_franchise_waits_for_the_supervisor(self):
        out = self.send(self.row(driver_email=None, franchise_code="kkd", latitude="10.0159, 76.3419"))[0]
        self.assertEqual(out["status"], "created")
        self.assertIn("waiting for the supervisor", out["message"])
        lead = Lead.objects.get(code=out["lead_code"])
        self.assertEqual((lead.status, lead.driver_id, float(lead.latitude)), ("unassigned", None, 10.0159))
        self.assertEqual(float(lead.longitude), 76.3419)

    def test_every_check(self):
        cases = [
            (dict(customer_name=""), "Customer name is missing"),
            (dict(address=" "), "Address is missing"),
            (dict(phone="12345"), "Phone must have 10 digits"),
            (dict(franchise_code="ZZZ"), 'No active franchise with code "ZZZ"'),
            (dict(pickup_date="tomorrow"), "not understood"),
            (dict(pickup_date="31-02-2030"), "not a real date"),
            (dict(pickup_date=(datetime.now(IST) - timedelta(days=5)).strftime("%d-%m-%Y")), "in the past"),
            (dict(pickup_time="noonish"), "not understood"),
            (dict(pickup_time="25:00"), "not valid"),
            (dict(latitude="10.0"), "both latitude and longitude"),
            (dict(latitude="abc", longitude="76"), "must be numbers"),
            (dict(latitude="76.3", longitude="10.0"), "not in India"),
            (dict(latitude="95", longitude="76"), "out of range"),
        ]
        for fields, expect in cases:
            out = self.send(self.row(**fields))[0]
            self.assertEqual(out["status"], "error", (fields, out))
            self.assertIn(expect, out["message"], (fields, out))
        self.assertEqual(Lead.objects.count(), 0)                         # a bad row leaves nothing behind
        self.assertEqual(Customer.objects.count(), 0)

    def test_times_and_dates_in_every_format(self):
        d = datetime.now(IST).strftime("%Y-%m-%d")
        for i, (date, time, hhmm) in enumerate([(d, "2:15 PM", "14:15"), (d, "14.15", "14:15"), (d, "12:05 AM", "00:05"),
                                                 (today_dmy().replace("-", "/"), "", "09:00"), (today_dmy().replace("-", "."), "9:00", "09:00")]):
            out = self.send(self.row(phone=f"94460123{i}0", pickup_date=date, pickup_time=time))[0]
            self.assertEqual(out["status"], "created", out)
            slot = Lead.objects.get(code=out["lead_code"]).slot.astimezone(IST)
            self.assertEqual(slot.strftime("%H:%M"), hhmm, (date, time))

    def test_same_customer_same_day_is_a_duplicate_and_blank_rows_are_skipped(self):
        first = self.send(self.row())[0]
        outs = self.send(self.row(customer_name="Anil K", phone="+91 94460 12345"), {"customer_name": "", "phone": ""})
        self.assertEqual(len(outs), 1)                                    # the empty row is not stored
        self.assertEqual((outs[0]["status"], outs[0]["lead_code"]), ("duplicate", first["lead_code"]))
        self.assertEqual(Customer.objects.count(), 1)                     # matched by the last 10 digits of the phone
        self.assertEqual(Lead.objects.count(), 1)

    def test_only_hq_may_upload(self):
        wh = Api(self.client, "wh@t.test")
        r = self.client.post("/rest/v1/lead_import", data=json.dumps([self.row()]), content_type="application/json", **wh.h)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(wh.rows("lead_import?select=id"), [])            # and cannot read the inbox either
        self.assertEqual(len(self.hq.rows("lead_import?select=id,status,message&order=id.desc&limit=60")), 0)


class AssignmentTests(ScrappyTestCase):
    def setUp(self):
        super().setUp()
        self.make_team()
        self.hq, self.sup, self.wh = Api(self.client, "hq@t.test"), Api(self.client, "sup@t.test"), Api(self.client, "wh@t.test")
        self.tsup = Api(self.client, "tvm-sup@t.test")
        self.drv, self.drv2 = Api(self.client, "drv@t.test"), Api(self.client, "drv2@t.test")
        self.leads = []
        for i, area in enumerate(["Edapally", "Kakkanad", "Aluva", "Kakkanad", "Edapally", "Aluva"]):
            row = self.upload_lead(self.hq, driver_email=None, name=f"Cust {i}", phone=f"94460000{i:02d}", area=area)
            self.leads.append(row["lead_code"])
        self.ids = {l["code"]: l["lead_id"] for l in self.sup.ok("wh_leads", p_from="2020-01-01", p_to="2099-01-01")}

    def test_supervisor_sees_unassigned_leads_and_assigns(self):
        counts = self.sup.ok("wh_lead_counts")[0]
        self.assertEqual(counts["unassigned"], 6)
        everyone = self.sup.ok("wh_leads", p_from="2020-01-01", p_to="2099-01-01", p_status="unassigned")
        self.assertEqual(len(everyone), 6)
        self.wh.fail("wh_assign_leads", "Only the supervisor", p_lead_ids=[everyone[0]["lead_id"]], p_driver=self.drv.uid)
        n = self.sup.ok("wh_assign_leads", p_lead_ids=[everyone[0]["lead_id"], everyone[1]["lead_id"]], p_driver=self.drv.uid)
        self.assertEqual(n, 2)
        self.assertEqual(len(self.drv.ok("my_leads")), 2)
        self.assertEqual(self.sup.ok("wh_lead_counts")[0]["unassigned"], 4)
        # take them back
        self.assertEqual(self.sup.ok("wh_assign_leads", p_lead_ids=[everyone[0]["lead_id"]], p_driver=None), 1)
        self.assertEqual(len(self.drv.ok("my_leads")), 1)
        self.sup.fail("wh_assign_leads", "Select at least one", p_lead_ids=[], p_driver=self.drv.uid)
        self.sup.fail("wh_assign_leads", "Choose an active driver", p_lead_ids=[everyone[2]["lead_id"]], p_driver=self.sup.uid)

    def test_even_split_by_area(self):
        out = self.sup.ok("wh_split_leads", p_lead_ids=list(self.ids.values()), p_driver_ids=[self.drv.uid, self.drv2.uid])
        self.assertEqual(sorted(o["count"] for o in out), [3, 3])
        areas = lambda who: sorted(l["area"] for l in who.ok("my_leads"))
        # sorted by area then handed out in blocks: Aluva+Aluva+Edapally | Edapally+Kakkanad+Kakkanad
        sets = sorted([areas(self.drv), areas(self.drv2)])
        self.assertEqual(sets, [["Aluva", "Aluva", "Edapally"], ["Edapally", "Kakkanad", "Kakkanad"]])
        self.assertEqual(self.sup.ok("wh_driver_workload", p_date=datetime.now(IST).strftime("%Y-%m-%d"))[0]["open_now"], 3)

    def test_split_uneven(self):
        out = self.sup.ok("wh_split_leads", p_lead_ids=list(self.ids.values())[:5], p_driver_ids=[self.drv.uid, self.drv2.uid])
        self.assertEqual(sorted(o["count"] for o in out), [2, 3])

    def test_another_franchise_is_off_limits(self):
        lid = list(self.ids.values())[0]
        self.tsup.fail("wh_assign_leads", "not in your franchise", p_lead_ids=[lid], p_driver=Api(self.client, "tvm-drv@t.test").uid)
        self.tsup.fail("wh_assign_leads", "not in your franchise", p_lead_ids=[lid], p_driver=self.drv.uid)
        self.assertEqual(self.tsup.ok("wh_leads", p_from="2020-01-01", p_to="2099-01-01"), [])
        self.sup.fail("wh_assign_leads", "not in your franchise", p_lead_ids=[lid], p_driver=Api(self.client, "tvm-drv@t.test").uid)

    def test_failed_pickup_comes_back_to_the_supervisor(self):
        lid = list(self.ids.values())[0]
        self.sup.ok("wh_assign_leads", p_lead_ids=[lid], p_driver=self.drv.uid)
        self.drv.ok("fail_pickup", p_lead_id=lid, p_reason="Phone not reachable", p_note=None)
        failed = self.sup.ok("wh_leads", p_from="2020-01-01", p_to="2099-01-01", p_status="failed")
        self.assertEqual((len(failed), failed[0]["fail_reason"]), (1, "Phone not reachable"))
        self.assertEqual(self.sup.ok("wh_lead_counts")[0]["failed_recent"], 1)
        self.sup.ok("wh_assign_leads", p_lead_ids=[lid], p_driver=self.drv2.uid)                 # try again with another collector
        again = self.drv2.ok("my_leads")[0]
        self.assertEqual((again["status"], again["fail_reason"]), ("scheduled", None))

    def test_hq_reassign_and_cancel(self):
        lid = list(self.ids.values())[0]
        self.sup.fail("hq_reassign_lead", "HQ only", p_lead_id=lid, p_driver_id=self.drv.uid)
        self.assertEqual(self.hq.ok("hq_reassign_lead", p_lead_id=lid, p_driver_id=self.drv.uid), "Basim Collector")
        self.hq.fail("hq_reassign_lead", "already with", p_lead_id=lid, p_driver_id=self.drv.uid)
        self.assertEqual(self.hq.ok("hq_reassign_lead", p_lead_id=lid, p_driver_id=self.drv2.uid), "Rahul Collector")
        self.hq.fail("hq_cancel_lead", "reason", p_lead_id=lid, p_reason=" ")
        code = self.hq.ok("hq_cancel_lead", p_lead_id=lid, p_reason="customer called")
        self.assertTrue(code.startswith("SC-"))
        self.assertEqual(self.drv2.ok("my_leads"), [])
        self.hq.fail("hq_cancel_lead", "has not been started", p_lead_id=lid, p_reason="again")
        # a reassigned lead moves to the other driver's franchise
        tvm_drv = Api(self.client, "tvm-drv@t.test")
        lid2 = list(self.ids.values())[1]
        self.hq.ok("hq_reassign_lead", p_lead_id=lid2, p_driver_id=tvm_drv.uid)
        self.assertEqual(Lead.objects.get(pk=lid2).franchise.code, "TVM")


class HqGivesLeadsToFranchiseTests(ScrappyTestCase):
    """HQ uploads leads and gives them to franchises (in bulk); the franchise's supervisor gives them to drivers."""

    def setUp(self):
        super().setUp()
        self.make_team()
        self.hq, self.sup, self.tsup = Api(self.client, "hq@t.test"), Api(self.client, "sup@t.test"), Api(self.client, "tvm-sup@t.test")
        self.drv = Api(self.client, "drv@t.test")
        self.ids = []
        for i in range(4):
            out = self.upload_lead(self.hq, driver_email=None, name=f"Cust {i}", phone=f"94461000{i:02d}", franchise_code="")
            self.ids.append(Lead.objects.get(code=out["lead_code"]).pk)
        self.kkd = Franchise.objects.get(code="KKD").pk
        self.tvm = Franchise.objects.get(code="TVM").pk

    def mine(self, who):
        return who.ok("wh_leads", p_from="2020-01-01", p_to="2099-01-01")

    def test_nobody_but_hq_sees_a_lead_before_it_is_given(self):
        self.assertEqual(self.mine(self.sup), [])
        self.assertEqual(self.sup.ok("wh_lead_counts")[0]["unassigned"], 0)
        self.assertEqual(len(self.hq.ok("hq_leads", p_from="2020-01-01", p_to="2099-01-01", p_status="no_franchise")), 4)
        self.assertEqual(self.hq.ok("hq_overview", p_from="2020-01-01", p_to="2099-01-01")["leads_no_franchise"], 4)

    def test_bulk_give_then_supervisor_gives_to_a_driver(self):
        out = self.hq.ok("hq_assign_leads_to_franchise", p_lead_ids=self.ids[:3], p_franchise=self.kkd)
        self.assertEqual((out["count"], out["franchise_code"]), (3, "KKD"))
        self.assertEqual(len(self.mine(self.sup)), 3)
        self.assertEqual(self.mine(self.tsup), [])                        # another franchise sees nothing
        self.assertEqual(len(self.hq.ok("hq_leads", p_from="2020-01-01", p_to="2099-01-01", p_status="no_franchise")), 1)
        self.assertEqual(self.sup.ok("wh_assign_leads", p_lead_ids=self.ids[:2], p_driver=self.drv.uid), 2)
        self.assertEqual(len(self.drv.ok("my_leads")), 2)
        audit = self.hq.rows("hq_audit?select=action,detail&action=eq.leads_to_franchise")
        self.assertEqual(len(audit), 1)

    def test_a_lead_can_move_to_another_franchise_until_a_driver_has_it(self):
        self.hq.ok("hq_assign_leads_to_franchise", p_lead_ids=[self.ids[0]], p_franchise=self.kkd)
        self.hq.ok("hq_assign_leads_to_franchise", p_lead_ids=[self.ids[0]], p_franchise=self.tvm)
        self.assertEqual(Lead.objects.get(pk=self.ids[0]).franchise_id, self.tvm)
        self.hq.ok("hq_assign_leads_to_franchise", p_lead_ids=[self.ids[1]], p_franchise=self.kkd)
        self.sup.ok("wh_assign_leads", p_lead_ids=[self.ids[1]], p_driver=self.drv.uid)
        self.hq.fail("hq_assign_leads_to_franchise", "already with a driver", p_lead_ids=[self.ids[1]], p_franchise=self.tvm)
        self.assertEqual(Lead.objects.get(pk=self.ids[1]).franchise_id, self.kkd)

    def test_checks(self):
        self.hq.fail("hq_assign_leads_to_franchise", "Select at least one", p_lead_ids=[], p_franchise=self.kkd)
        self.hq.fail("hq_assign_leads_to_franchise", "Choose an active franchise", p_lead_ids=self.ids, p_franchise=None)
        self.hq.fail("hq_assign_leads_to_franchise", "not found", p_lead_ids=[999999], p_franchise=self.kkd)
        self.sup.fail("hq_assign_leads_to_franchise", "", p_lead_ids=self.ids, p_franchise=self.kkd)
        self.assertEqual(Lead.objects.filter(franchise__isnull=True).count(), 4)
