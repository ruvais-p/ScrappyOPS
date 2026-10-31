import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import override_settings

from core.models import (Bill, HqAudit, HqRelease, ImmutableError, LoadWeighing, Profile, Rate, ScrapItem, User)
from core.tests.base import Api, PW, ScrappyTestCase, today_dmy
from core.services.common import fetch

IST = ZoneInfo("Asia/Kolkata")
ISO = lambda: datetime.now(IST).strftime("%Y-%m-%d")


class World(ScrappyTestCase):
    """A day in two franchises, so isolation can be checked."""

    def setUp(self):
        super().setUp()
        self.make_team()
        self.hq, self.sup, self.wh = Api(self.client, "hq@t.test"), Api(self.client, "sup@t.test"), Api(self.client, "wh@t.test")
        self.drv, self.drv2 = Api(self.client, "drv@t.test"), Api(self.client, "drv2@t.test")
        self.twh, self.tsup, self.tdrv = Api(self.client, "tvm-wh@t.test"), Api(self.client, "tvm-sup@t.test"), Api(self.client, "tvm-drv@t.test")
        rates = self.drv.rows("current_rates?select=item_id,item_name&order=item_id")
        self.iron = [r for r in rates if r["item_name"] == "Iron"][0]["item_id"]

    def pickup(self, drv, email, name, phone, qty, method="upi"):
        self.upload_lead(self.hq, driver_email=email, name=name, phone=phone)
        lead = [l for l in drv.ok("my_leads") if l["customer_name"] == name][0]
        bill = drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        drv.ok("set_bill_item", p_bill_id=bill, p_item_id=self.iron, p_qty_kg=qty, p_photo_url=None, p_typed=True)
        drv.ok("send_bill", p_bill_id=bill)
        drv.ok("mark_bill_shared", p_bill_id=bill)
        drv.ok("confirm_bill", p_bill_id=bill, p_proof_url=None)
        drv.ok("pay_bill", p_bill_id=bill, p_method=method, p_upi_ref="402512345678")
        return bill


class IsolationTests(World):
    def test_each_role_sees_only_its_own_rows(self):
        self.pickup(self.drv, "drv@t.test", "Anil", "9446012345", 10)
        self.pickup(self.tdrv, "tvm-drv@t.test", "Tina", "9446012399", 7)
        self.drv.ok("end_route"); self.tdrv.ok("end_route")
        kkd_load = self.wh.rows("loads?select=id,code")
        tvm_load = self.twh.rows("loads?select=id,code")
        self.assertEqual((len(kkd_load), len(tvm_load)), (1, 1))
        self.assertEqual(len(self.hq.rows("loads?select=id")), 2)
        self.assertEqual(len(self.drv.rows("loads?select=id")), 1)
        self.assertEqual(len(self.drv2.rows("loads?select=id")), 0)
        # a warehouse cannot weigh or look into another franchise's load
        self.twh.fail("record_load_weighing", "another franchise", p_load_id=kkd_load[0]["id"], p_note=None, p_weights=[{"item_id": self.iron, "kg": 10}])
        self.wh.fail("count_route_cash", "another franchise", p_load_id=tvm_load[0]["id"], p_counted=0, p_note=None)
        self.assertEqual(self.twh.rows(f"bills?select=id&load_id=eq.{kkd_load[0]['id']}"), [])
        self.assertEqual(len(self.wh.rows("bills?select=id,load_id&status=eq.paid&limit=5000")), 1)
        # people: staff see their own franchise plus HQ; a collector sees only themselves
        names = sorted(p["full_name"] for p in self.wh.rows("profiles?select=full_name"))
        self.assertEqual(names, sorted(["Sumi Supervisor", "Sumesh Warehouse", "Second Warehouse", "Basim Collector", "Rahul Collector", "HQ Admin"]))
        self.assertEqual([p["full_name"] for p in self.drv.rows("profiles?select=full_name&id=eq." + self.drv2.uid)], [])
        self.assertEqual([p["full_name"] for p in self.drv.rows("profiles?select=full_name&id=eq." + self.hq.uid)], [])
        self.assertEqual(len(self.hq.rows("profiles?select=id")), 9)
        # reports follow the same rule, even when a franchise is asked for by name
        mine = self.twh.ok("wh_pickups", p_from=ISO(), p_to=ISO(), p_load_id=None, p_franchise=self.kkd.pk)
        self.assertEqual([r["franchise_code"] for r in mine], ["TVM"])
        both = self.hq.ok("wh_pickups", p_from=ISO(), p_to=ISO(), p_load_id=None, p_franchise=None)
        self.assertEqual(sorted(r["franchise_code"] for r in both), ["KKD", "TVM"])
        only = self.hq.ok("wh_pickups", p_from=ISO(), p_to=ISO(), p_load_id=None, p_franchise=self.tvm.pk)
        self.assertEqual([r["franchise_code"] for r in only], ["TVM"])
        # a collector is not warehouse staff
        self.drv.fail("wh_pickups", "Not allowed", p_from=ISO(), p_to=ISO(), p_load_id=None, p_franchise=None)
        self.drv.fail("hq_overview", "HQ only", p_from=ISO(), p_to=ISO())
        # stock is kept per franchise
        self.wh.ok("record_load_weighing", p_load_id=kkd_load[0]["id"], p_note=None, p_weights=[{"item_id": self.iron, "kg": 10}])
        self.twh.ok("record_load_weighing", p_load_id=tvm_load[0]["id"], p_note=None, p_weights=[{"item_id": self.iron, "kg": 7}])
        stock = lambda who: [r for r in who.ok("wh_stock_report", p_from=ISO(), p_to=ISO()) if r["item_name"] == "Iron"][0]["stock_now_kg"]
        self.assertEqual((stock(self.wh), stock(self.twh)), (10, 7))
        self.assertEqual([r for r in self.hq.ok("wh_stock_report", p_from=ISO(), p_to=ISO()) if r["item_name"] == "Iron"][0]["stock_now_kg"], 17)
        # HQ's request is for one franchise, and only that franchise's supervisor can release against it
        self.hq.ok("raise_requirement", p_item_id=self.iron, p_required_kg=5, p_due_date=None, p_note=None, p_franchise=self.kkd.pk)
        rid = self.hq.rows("hq_requirement_progress?select=id")[0]["id"]
        self.tsup.fail("release_to_hq", "another franchise", p_requirement_id=rid, p_kg=2, p_vehicle_no="KL 1", p_note=None)
        self.sup.ok("release_to_hq", p_requirement_id=rid, p_kg=5, p_vehicle_no="KL 1", p_note=None)
        self.assertEqual(self.tsup.rows("hq_releases?select=id"), [])

    def test_hq_overview_and_reports_run(self):
        self.pickup(self.drv, "drv@t.test", "Anil", "9446012345", 10)
        self.wh.ok("issue_float", p_driver_id=self.drv.uid, p_amount=300, p_note=None)
        self.drv.ok("end_route")
        a, b = ISO(), ISO()
        ov = self.hq.ok("hq_overview", p_from=a, p_to=b)
        for key in ("franchises_active", "drivers_active", "leads_closed", "paid_bills", "kg", "amount", "upi_amount", "loads_waiting",
                    "cash_in_field", "counts_waiting", "stock_kg", "stock_value", "req_open", "leads_unassigned"):
            self.assertIn(key, ov)
        self.assertEqual((ov["paid_bills"], ov["kg"], ov["amount"], ov["loads_waiting"], ov["counts_waiting"]), (1, 10, 280, 1, 1))
        self.assertEqual(self.hq.ok("hq_overview", p_from=a, p_to=b, p_franchise=self.tvm.pk)["paid_bills"], 0)
        daily = self.hq.ok("hq_daily", p_from=a, p_to=b)
        self.assertEqual((len(daily), daily[0]["pickups"], daily[0]["amount"]), (1, 1, 280))
        self.assertEqual(self.hq.ok("hq_item_summary", p_from=a, p_to=b)[0]["item_name"], "Iron")
        score = self.hq.ok("hq_driver_scorecard", p_from=a, p_to=b)
        self.assertEqual([s["full_name"] for s in score if s["pickups"]], ["Basim Collector"])
        bills = self.hq.ok("hq_bills", p_from=a, p_to=b)
        self.assertEqual((bills[0]["status"], bills[0]["customer_name"], bills[0]["total_amount"]), ("paid", "Anil", 280))
        self.assertEqual(len(self.hq.ok("hq_bills", p_from=a, p_to=b, p_search="anil")), 1)
        self.assertEqual(len(self.hq.ok("hq_bills", p_from=a, p_to=b, p_search="nobody")), 0)
        self.assertEqual(len(self.hq.ok("hq_leads", p_from=a, p_to=b, p_status="closed")), 1)
        self.assertEqual(self.hq.ok("hq_loads", p_from=a, p_to=b)[0]["pickups"], 1)
        team = self.hq.ok("hq_team")
        self.assertEqual(len(team), 9)
        self.assertEqual([t["email"] for t in team if t["role"] == "hq"], ["hq@t.test"])
        fr = {f["code"]: f for f in self.hq.ok("hq_franchises", p_from=a, p_to=b)}
        self.assertEqual((fr["KKD"]["pickups"], fr["KKD"]["drivers"], fr["KKD"]["staff"], fr["TVM"]["pickups"]), (1, 2, 3, 0))
        self.assertEqual(self.wh.ok("wh_transactions", p_from=a, p_to=b)[0]["kind"] in ("upi_payout", "float_issued"), True)
        self.assertEqual(len(self.wh.ok("wh_transactions", p_from=a, p_to=b, p_driver=self.drv.uid, p_limit=1)), 1)
        rc = self.wh.ok("wh_route_cash", p_from=a, p_to=b)
        self.assertEqual((rc[0]["route_status"], rc[0]["float_issued"], rc[0]["expected_cash"]), ("awaiting_count", 300, 300))

    def test_hq_people_and_franchise_rules(self):
        self.sup.fail("hq_add_franchise", "HQ only", p_code="XYZ", p_name="X")
        self.hq.fail("hq_add_franchise", "2 to 12", p_code="x", p_name="Bad")
        self.hq.fail("hq_add_franchise", "already used", p_code="kkd", p_name="Dup")
        fid = self.hq.ok("hq_add_franchise", p_code="ekm-1", p_name="Ernakulam One", p_district="Ernakulam", p_constituency="Ernakulam")
        self.assertEqual(self.hq.rows(f"franchises?select=code&id=eq.{fid}")[0]["code"], "EKM-1")
        self.hq.fail("hq_update_franchise", "Enter the franchise name", p_id=fid, p_code="EKM-1", p_name=" ", p_district=None, p_constituency=None, p_active=True)
        self.assertEqual(self.hq.ok("hq_update_franchise", p_id=fid, p_code="EKM-1", p_name="E One", p_district=None, p_constituency=None, p_active=False), "EKM-1")
        # a driver with an open lead cannot be moved or switched off
        self.upload_lead(self.hq)
        self.hq.fail("hq_update_profile", "open leads", p_id=self.drv.uid, p_full_name="Basim", p_phone=None, p_territory=None, p_vehicle_no=None, p_active=False)
        self.hq.fail("hq_update_profile", "own login", p_id=self.hq.uid, p_full_name="HQ", p_phone=None, p_territory=None, p_vehicle_no=None, p_active=False)
        self.assertEqual(self.hq.ok("hq_update_profile", p_id=self.drv2.uid, p_full_name="Rahul K", p_phone="99", p_territory="Edapally", p_vehicle_no="KL 1", p_active=True), "Rahul K")
        # an inactive franchise cannot receive people
        self.hq.fail("hq_update_profile", "active franchise", p_id=self.drv2.uid, p_full_name="Rahul K", p_phone=None, p_territory=None, p_vehicle_no=None, p_active=True, p_franchise=fid)
        # a deactivated person cannot do anything, even with a login that is still open
        self.hq.ok("hq_update_profile", p_id=self.drv2.uid, p_full_name="Rahul K", p_phone=None, p_territory=None, p_vehicle_no=None, p_active=False)
        self.assertEqual(self.drv2.ok("my_leads"), [])
        self.drv2.fail("start_pickup", "Only drivers", p_lead_id=1)

    def test_rates_and_materials(self):
        self.sup.fail("hq_set_rate", "HQ only", p_item_id=self.iron, p_rate=30)
        self.hq.fail("hq_set_rate", "between 0 and 100000", p_item_id=self.iron, p_rate=0)
        self.hq.fail("hq_set_rate", "already", p_item_id=self.iron, p_rate=28)
        self.assertEqual(self.hq.ok("hq_set_rate", p_item_id=self.iron, p_rate=31.5), "Iron")
        self.assertEqual([r for r in self.drv.rows("current_rates?select=item_name,rate_per_kg") if r["item_name"] == "Iron"][0]["rate_per_kg"], 31.5)
        self.assertEqual(len(self.hq.rows("rates?select=id,item_id,rate_per_kg&order=id.desc&limit=100")), 7)      # history is kept
        # a new rate applies to the next weighing only
        self.upload_lead(self.hq)
        lead = self.drv.ok("my_leads")[0]
        bill = self.drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        self.drv.ok("set_bill_item", p_bill_id=bill, p_item_id=self.iron, p_qty_kg=2, p_photo_url=None, p_typed=True)
        self.assertEqual(self.drv.rows(f"bill_items?select=amount,rate_per_kg&bill_id=eq.{bill}")[0]["amount"], 63)
        # materials
        item = self.hq.ok("hq_add_item", p_name="Brass", p_rate=400)
        self.hq.fail("hq_add_item", "already exists", p_name="brass", p_rate=1)
        self.hq.fail("hq_add_item", "2 to 30", p_name="B", p_rate=1)
        self.assertIn("Brass", [r["item_name"] for r in self.drv.rows("current_rates?select=item_name")])
        self.hq.ok("hq_set_item_active", p_item_id=item, p_active=False)
        self.assertNotIn("Brass", [r["item_name"] for r in self.drv.rows("current_rates?select=item_name")])
        self.hq.fail("hq_add_item", "Restore it", p_name="Brass", p_rate=1)
        self.hq.ok("hq_set_item_active", p_item_id=item, p_active=True)
        self.hq.fail("hq_set_item_active", "already active", p_item_id=item, p_active=True)
        self.hq.fail("hq_set_item_active", "in loads that are not finished", p_item_id=self.iron, p_active=False)

    def test_activity_log_is_written_and_cannot_be_changed(self):
        self.hq.ok("hq_set_rate", p_item_id=self.iron, p_rate=40)
        log = self.hq.rows("hq_audit?select=id,action,ref,detail&order=id.desc&limit=200")
        self.assertEqual((log[0]["action"], log[0]["ref"], log[0]["detail"]["new"]), ("rate_set", "Iron", 40))
        self.assertEqual(self.wh.rows("hq_audit?select=id"), [])           # only HQ may read it
        entry = HqAudit.objects.first()
        entry.action = "tampered"
        with self.assertRaises(ImmutableError):
            entry.save()
        with self.assertRaises(ImmutableError):
            HqAudit.objects.all().delete()


class RestFormatTests(World):
    def test_filters_order_limit_and_errors(self):
        rows = self.hq.rows("scrap_items?select=id,name&active=eq.true&order=id")
        self.assertEqual([r["name"] for r in rows], ["Iron", "Aluminium", "Paper", "Plastic", "Copper", "E-waste"])
        self.assertEqual([r["name"] for r in self.hq.rows("scrap_items?select=name&order=name.desc&limit=2")], ["Plastic", "Paper"])
        ids = [r["id"] for r in rows]                       # database ids keep counting between tests, so work from what is there
        self.assertEqual([r["id"] for r in self.hq.rows(f"scrap_items?select=id&id=in.({ids[0]},{ids[2]})&order=id")], [ids[0], ids[2]])
        self.assertEqual(len(self.hq.rows(f"scrap_items?select=id&id=neq.{ids[0]}")), 5)
        self.assertEqual(len(self.hq.rows(f"scrap_items?select=id&id=gte.{ids[4]}")), 2)
        self.assertEqual(len(self.hq.rows(f"scrap_items?select=id&id=not.in.({ids[0]},{ids[1]})")), 4)
        self.assertEqual(self.hq.rows("loads?select=id&submitted_at=is.null"), [])
        self.assertEqual(len(self.hq.rows("scrap_items?select=*")[0]), 3)
        self.assertEqual(self.hq.get("scrap_items?select=nope").status_code, 400)
        self.assertEqual(self.hq.get("scrap_items?nope=eq.1").status_code, 400)
        self.assertEqual(self.hq.get("scrap_items?id=eq.abc").status_code, 400)
        self.assertEqual(self.hq.get("customers?select=id").status_code, 404)           # tables that are not listed cannot be read
        self.assertEqual(self.hq.get("users?select=email,password").status_code, 404)
        r = self.client.post("/rest/v1/scrap_items", data=json.dumps({"name": "Gold"}), content_type="application/json", **self.hq.h)
        self.assertEqual(r.status_code, 403)                                            # tables cannot be written to directly
        self.assertEqual(self.client.get("/rest/v1/scrap_items?select=id").status_code, 401)
        self.assertEqual(self.hq.call("no_such_action").status_code, 404)
        self.assertEqual(self.hq.call("hq_log", p_action="x", p_ref="y", p_detail={}).status_code, 404)   # internal helpers are not reachable
        self.assertEqual(self.hq.call("hq_set_rate", wrong=1).status_code, 404)

    def test_sql_injection_attempts_are_just_text(self):
        self.assertEqual(self.hq.get("scrap_items?name=eq.x';drop table scrap_items;--").status_code, 200)
        self.assertEqual(self.hq.get("scrap_items?order=id;drop table scrap_items").status_code, 400)
        self.assertEqual(self.hq.get("scrap_items?select=id;drop table x").status_code, 400)
        self.assertEqual(ScrapItem.objects.count(), 6)
        out = self.hq.ok("hq_bills", p_from=ISO(), p_to=ISO(), p_search="'; drop table bills; --")
        self.assertEqual(out, [])

    def test_realistic_page_loads(self):
        """The queries the three dashboards make when they open."""
        self.pickup(self.drv, "drv@t.test", "Anil", "9446012345", 10)
        uid = self.drv.uid
        for q in (f"profiles?select=full_name,role,territory,vehicle_no,franchise_id&id=eq.{uid}", "current_rates?select=item_id,item_name,rate_per_kg&order=item_id",
                  f"driver_cash_in_hand?select=cash_in_hand&driver_id=eq.{uid}",
                  f"cash_ledger?select=id,entry_type,amount,bill_id,note,created_at&driver_id=eq.{uid}&order=created_at.asc,id.asc",
                  "loads?select=id,code,status,started_at,submitted_at,warehouse_kg&order=id.desc&limit=10",
                  "load_item_totals?select=load_id,item_name,total_kg,total_value", "bill_totals?select=bill_id,bill_no,load_id,payment_method,total_kg,total_amount&status=eq.paid",
                  f"franchises?select=code,name&id=eq.{self.kkd.pk}"):
            self.assertEqual(self.drv.get(q).status_code, 200, q)
        for q in ("scrap_items?select=id,name&active=eq.true&order=id",
                  "profiles?select=id,full_name,role,vehicle_no,territory,active",
                  "loads?select=id,code,driver_id,vehicle_no,status,started_at,submitted_at,warehouse_kg,weighed_at,weighing_note,resolved_at,resolved_by,resolution_note&order=id.desc&limit=1000",
                  "bills?select=id,load_id&status=eq.paid&limit=5000",
                  "load_weighings?select=load_id,item_id,billed_kg,warehouse_kg,within_tolerance,weighed_by,weighed_at&superseded_at=is.null&limit=5000",
                  "hq_requirement_progress?select=*&order=id.desc&limit=500",
                  "hq_releases?select=id,code,requirement_id,item_id,kg,vehicle_no,note,released_by,released_at&order=released_at.desc&limit=500",
                  "wh_stock_movements?select=day,kind,item_id,item_name,kg,ref,happened_at&order=happened_at.desc&limit=3000",
                  "driver_cash_in_hand?select=*"):
            self.assertEqual(self.wh.get(q).status_code, 200, q)
        for q in ("franchises?select=id,code,name,district,constituency,active&order=code",
                  "lead_import?select=id,customer_name,phone,driver_email,franchise_code,pickup_date,status,message,lead_code,imported_at&order=id.desc&limit=60",
                  "hq_releases?select=id,code,requirement_id,item_id,kg,vehicle_no,note,released_by,released_at,franchise_id&order=released_at.desc&limit=200",
                  "settlement_resolutions?select=settlement_id,decision,note,resolved_by,resolved_at&order=id.desc&limit=500",
                  "current_rates?select=item_id,item_name,rate_per_kg,effective_from&order=item_id",
                  "rates?select=id,item_id,rate_per_kg,effective_from,set_by&order=id.desc&limit=100",
                  "hq_audit?select=id,at,by_id,action,ref,detail,franchise_id&order=id.desc&limit=200",
                  f"profiles?id=eq.{self.hq.uid}&select=id,full_name,role,active"):
            self.assertEqual(self.hq.get(q).status_code, 200, q)


class PasswordChangeTests(ScrappyTestCase):
    def setUp(self):
        super().setUp()
        self.person("person@t.test", "Test Person", "driver")
        self.api = Api(self.client, "person@t.test")

    def change(self, current=PW, password="Changed#Pass456"):
        return self.client.patch("/auth/v1/user", data=json.dumps({"current_password": current, "password": password}),
                                 content_type="application/json", **self.api.h)

    def test_user_can_change_own_password_and_keep_current_session(self):
        self.assertEqual(self.change().status_code, 200)
        self.assertEqual(self.client.get("/auth/v1/user", **self.api.h).status_code, 200)
        self.assertEqual(Api(self.client, "person@t.test", "Changed#Pass456").email, "person@t.test")
        old = self.client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": "person@t.test", "password": PW}),
                               content_type="application/json")
        self.assertEqual(old.status_code, 400)

    def test_current_password_and_new_password_are_validated(self):
        self.assertEqual(self.change(current="wrong password").status_code, 403)
        self.assertIn("current password", self.change(current="wrong password").json()["message"].lower())
        self.assertEqual(self.change(password="short").status_code, 400)
        self.assertEqual(self.change(password=PW).status_code, 400)
        self.assertTrue(User.objects.get(email="person@t.test").check_password(PW))


class PdfAndLoginTests(World):
    def test_bill_pdf_and_customer_link(self):
        bill = self.pickup(self.drv, "drv@t.test", "Anil", "9446012345", 10)
        r = self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json", **self.drv.h)
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        self.assertTrue(out["url"].endswith(str(Bill.objects.get(pk=bill).share_token)))
        self.assertGreater(out["bytes"], 2000)
        link = self.client.get("/functions/v1/bill-pdf?t=" + str(Bill.objects.get(pk=bill).share_token))      # the customer needs no login
        self.assertEqual(link.status_code, 200)
        body = b"".join(link.streaming_content)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(link["Cache-Control"], "no-store, max-age=0")
        # who may make it
        other = Api(self.client, "drv2@t.test")
        self.assertEqual(self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json", **other.h).status_code, 403)
        self.assertEqual(self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json", **self.twh.h).status_code, 403)
        self.assertEqual(self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json", **self.wh.h).status_code, 200)
        self.assertEqual(self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json", **self.hq.h).status_code, 200)
        self.assertEqual(self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": 0}), content_type="application/json", **self.drv.h).status_code, 400)
        self.assertEqual(self.client.get("/functions/v1/bill-pdf?t=not-a-token").status_code, 404)
        self.assertEqual(self.client.get("/functions/v1/bill-pdf?t=" + "0" * 8 + "-0000-0000-0000-" + "0" * 12).status_code, 404)

    def test_unpaid_bill_pdf_and_draft_refused(self):
        self.upload_lead(self.hq)
        lead = self.drv.ok("my_leads")[0]
        bill = self.drv.ok("start_pickup", p_lead_id=lead["lead_id"])
        post = lambda: self.client.post("/functions/v1/bill-pdf", data=json.dumps({"bill_id": bill}), content_type="application/json", **self.drv.h)
        self.assertEqual(post().status_code, 400)                  # still a draft
        self.drv.ok("set_bill_item", p_bill_id=bill, p_item_id=self.iron, p_qty_kg=3.25, p_photo_url=None, p_typed=True)
        self.drv.ok("send_bill", p_bill_id=bill)
        self.assertEqual(post().status_code, 200)

    def test_invoice_text_helpers(self):
        from core.services.invoice import in_words, money
        self.assertEqual(in_words(0), "Rupees Zero only")
        self.assertEqual(in_words(1234567.5), "Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven and Fifty Paise only")
        self.assertEqual(money(1234567.5), "12,34,567.50")
        self.assertEqual(money(0), "0.00")

    def test_creating_logins_and_resetting_passwords(self):
        post = lambda who, body: self.client.post("/functions/v1/hq-logins", data=json.dumps(body), content_type="application/json", **who.h)
        body = {"action": "create", "franchise_id": self.kkd.pk, "people": [
            {"role": "driver", "full_name": "New Collector", "email": "New@Scrappy.test", "vehicle_no": "KL 9", "password": ""},
            {"role": "warehouse", "full_name": "Fixed Pw", "email": "fixed@scrappy.test", "password": "ChosenPass1"},
            {"role": "hq", "full_name": "Sneaky", "email": "sneaky@scrappy.test"},
            {"role": "driver", "full_name": "Short", "email": "short@scrappy.test", "password": "abc"},
            {"role": "driver", "full_name": "Dup", "email": "drv@t.test"}]}
        self.assertEqual(post(self.wh, body).status_code, 403)                  # only HQ
        res = post(self.hq, body).json()
        r = res["results"]
        self.assertTrue(r[0]["ok"] and len(r[0]["password"]) == 14)              # a readable password, shown once
        self.assertTrue(r[1]["ok"] and r[1]["password_set_by_hq"] and "password" not in r[1])
        self.assertIn("collector, warehouse manager or supervisor", r[2]["error"])
        self.assertIn("8 to 72", r[3]["error"])
        self.assertIn("already exists", r[4]["error"])
        self.assertFalse(User.objects.filter(email="sneaky@scrappy.test").exists())
        newbie = Api(self.client, "new@scrappy.test", r[0]["password"])         # the new person can log in at once
        self.assertEqual(newbie.rows(f"profiles?select=role,franchise_id&id=eq.{newbie.uid}")[0]["role"], "driver")
        Api(self.client, "fixed@scrappy.test", "ChosenPass1")
        # reset a password: the old one stops working and the person is signed out everywhere
        rr = post(self.hq, {"action": "reset_password", "user_id": newbie.uid, "password": ""}).json()["results"][0]
        self.assertTrue(rr["ok"] and rr["password"])
        self.assertFalse(newbie.ok("session_valid"))
        bad = self.client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": "new@scrappy.test", "password": r[0]["password"]}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        Api(self.client, "new@scrappy.test", rr["password"])
        self.assertEqual(post(self.hq, {"action": "reset_password", "user_id": self.hq.uid}).status_code, 403)    # HQ passwords are not reset here
        super_user = self.person("super@t.test", "Super", "super_admin", franchise=None, is_super_admin=True)
        self.assertEqual(post(self.hq, {"action": "reset_password", "user_id": str(super_user.pk)}).status_code, 403)
        self.hq.fail("hq_update_profile", "Super Admin accounts", p_id=str(super_user.pk), p_full_name="Changed")
        super_admin = Api(self.client, "super@t.test")
        self.assertEqual(len(super_admin.ok("hq_team")), 9)
        kwd_user = User.objects.create_user("field@kwd.test", PW)
        fetch("""insert into kwd_profiles (id, full_name, email, phone, role, is_active)
                 values (%(u)s, 'KWD Field Member', 'field@kwd.test', '9446000000', 'tso', true) returning id""",
              {"u": kwd_user.pk})
        company_team = super_admin.ok("hq_team")
        self.assertEqual([p["source"] for p in company_team if p["id"] == str(kwd_user.pk)], ["kwd"])
        self.assertEqual(super_admin.ok("hq_update_kwd_profile", p_id=str(kwd_user.pk), p_full_name="KWD Member",
                                        p_phone="9446111111", p_active=False), "KWD Member")
        self.assertFalse(User.objects.get(pk=kwd_user.pk).is_active)
        self.assertEqual(super_admin.ok("hq_update_profile", p_id=self.hq.uid, p_full_name="HQ Admin", p_phone="9999999999",
                                        p_territory=None, p_vehicle_no=None, p_active=True), "HQ Admin")
        reset_hq = post(super_admin, {"action": "reset_password", "user_id": self.hq.uid, "password": "NewHqPass123"})
        self.assertEqual(reset_hq.status_code, 200)
        self.assertEqual(post(super_admin, {"action": "reset_password", "user_id": str(super_user.pk)}).status_code, 403)
        self.assertTrue(HqAudit.objects.filter(action="password_reset").exists())

    def test_hq_cannot_claim_field_staff_login(self):
        staff = User.objects.create_user("field@t.test", PW)
        fetch("insert into kwd_profiles (id, full_name, email, role, is_active) values (%(u)s, 'Field User', 'field@t.test', 'tso', true) returning id",
              {"u": staff.pk})
        self.hq.fail("hq_add_person", "belongs to the field app", p_email="field@t.test", p_full_name="Field User",
                     p_role="driver", p_franchise=self.kkd.pk)
        self.assertFalse(Profile.objects.filter(pk=staff.pk).exists())
