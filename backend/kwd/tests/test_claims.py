from datetime import date, timedelta
from decimal import Decimal

from core.services.common import fetch, fetch_one
from kwd.rules.days import recalc_field_day
from kwd.rules.util import ist_today
from kwd.tests.base import KwdCase, QueryError, PNG


class ClaimTests(KwdCase):
    def setUp(self):
        super().setUp()
        self.make_world()

    def end_day(self, who, day, odo=1050, photo=True, **extra):
        v = {"end_at": "2026-01-01T00:00:00Z", "end_lat": 10.02, "end_lng": 76.34, "end_acc": 10, "end_odo": odo,
             "end_photo": who.upload() if photo else None}
        v.update(extra)
        return who.update("field_days", v, [["eq", "id", day["id"]]], select="*")[0]

    def submit(self, who, day, **extra):
        return who.update("field_days", {"status": "submitted", **extra}, [["eq", "id", day["id"]]], select="*")[0]

    # ------------------------------------------------------------------ starting and ending the day
    def test_start_day_rules(self):
        self.tso.fails("vehicle number", self.tso.insert, "field_days", {"travel_mode": "two_wheeler", "start_odo": 10, "start_photo": self.tso.upload()})
        self.tso.fails("odometer reading", self.tso.insert, "field_days", {"travel_mode": "car", "vehicle_no": "KL1", "start_photo": self.tso.upload()})
        self.tso.fails("photo of the odometer", self.tso.insert, "field_days", {"travel_mode": "car", "vehicle_no": "KL1", "start_odo": 10})
        self.tso.fails("photo of the odometer", self.tso.insert, "field_days", {"travel_mode": "car", "vehicle_no": "KL1", "start_odo": 10,
                                                                                "start_photo": f"{self.tso2_id}/stolen.png"})      # someone else's photo
        d = self.start_day(self.tso)
        self.assertEqual((d["status"], d["vehicle_no"], d["tso_id"], d["day"]), ("open", "KL 07 AB 1234", str(self.tso_id), str(ist_today())))
        e = self.tso.fails("duplicate key", self.start_day, self.tso)                                                              # one a day
        self.assertEqual(e.code, "23505")
        bus = self.start_day(self.tso2, mode="public_transport")
        self.assertEqual((bus["start_odo"], bus["travel_mode"]), (None, "public_transport"))

    def test_end_day_and_the_odometer(self):
        d = self.start_day(self.tso, odo=1000)
        self.tso.fails("lower than this morning", self.end_day, self.tso, d, odo=990)
        self.tso.fails("photo of the odometer", self.end_day, self.tso, d, odo=1040, photo=False)
        e = self.end_day(self.tso, d, odo=1040)
        self.assertEqual((e["end_odo"], e["odo_km"], e["ta_km"]), (1040, 40, 40))
        self.assertEqual(e["ta_amount"], 140)                                      # 40 km x Rs 3.50
        # the end of the day is written once
        again = self.tso.update("field_days", {"end_odo": 9999, "end_at": None}, [["eq", "id", d["id"]]], select="end_odo")[0]
        self.assertEqual(again["end_odo"], 1040)

    def test_status_jumps_are_refused(self):
        d = self.start_day(self.tso)
        self.tso.fails("only submit your own request", self.tso.update, "field_days", {"status": "ho_approved"}, [["eq", "id", d["id"]]])
        out = self.tso.update("field_days", {"ta_amount": 99999, "ta_km": 999, "start_odo": 1, "vehicle_no": "X", "ho_flag": True, "approved_amount": 5000},
                              [["eq", "id", d["id"]]], select="*")[0]
        self.assertEqual((out["ta_amount"], out["start_odo"], out["vehicle_no"], out["ho_flag"], out["approved_amount"]), (0, 1000, "KL 07 AB 1234", False, None))

    # ------------------------------------------------------------------ allowance and submitting
    def test_allowance_limits_and_bills(self):
        d = self.start_day(self.tso)
        self.end_day(self.tso, d)
        self.tso.fails("at most Rs 250", self.tso.update, "field_days", {"da_requested": 300}, [["eq", "id", d["id"]]])
        self.tso.fails("cannot be negative", self.tso.update, "field_days", {"da_requested": -5}, [["eq", "id", d["id"]]])
        self.assertEqual(self.tso.update("field_days", {"da_requested": 500, "night_halt": True, "halt_place": "Aluva"}, [["eq", "id", d["id"]]], select="da_requested, da_amount")[0],
                         {"da_requested": 500, "da_amount": 500})                                      # the maximum is higher with a night halt
        self.tso.fails("Upload the bill(s) for your allowance", self.submit, self.tso, d)
        self.tso.fails("allowance amount", self.tso.insert, "expense_items", {"day_id": d["id"], "category": "meals", "amount": 100, "description": "lunch"})
        self.tso.fails("Upload the bill photo", self.tso.insert, "expense_items", {"day_id": d["id"], "category": "da_bill", "amount": 0, "description": "hotel bill"})
        bill = self.tso.insert("expense_items", {"day_id": d["id"], "category": "da_bill", "amount": 777, "description": "hotel bill", "bill_path": self.tso.upload()}, select="*", single=True)
        self.assertEqual(bill["amount"], 0)                                                             # bills are evidence, the amount is typed on the request
        sub = self.submit(self.tso, d, tso_note="Long day in Aluva")
        self.assertEqual(sub["status"], "submitted")
        self.assertIsNotNone(sub["submitted_at"])
        self.tso.fails("submitted and locked", self.tso.update, "field_days", {"da_requested": 100, "status": "open"}, [["eq", "id", d["id"]]])
        self.tso.fails("locked", self.tso.insert, "expense_items", {"day_id": d["id"], "category": "bus_train", "amount": 50, "description": "bus fare"})
        self.tso.fails("locked", self.tso.q, "expense_items", "delete", filters=[["eq", "id", bill["id"]]])

    def test_end_the_day_before_submitting(self):
        d = self.start_day(self.tso)
        self.tso.fails("End your day", self.submit, self.tso, d)

    def test_bills_travel_amounts_and_duplicate_detection(self):
        d = self.start_day(self.tso, odo=1000)
        self.end_day(self.tso, d, odo=1100)
        photo = self.tso.upload("same-bill.png")
        a = self.tso.insert("expense_items", {"day_id": d["id"], "category": "bus_train", "amount": 60, "description": "bus to Aluva", "bill_path": photo}, select="*", single=True)
        self.assertEqual(a["flags"], [])
        photo2 = self.tso.upload("copy-of-bill.png")                                                    # the same picture again
        b = self.tso.insert("expense_items", {"day_id": d["id"], "category": "auto_taxi", "amount": 350, "description": "auto fare", "bill_path": photo2}, select="*", single=True)
        self.assertEqual(b["flags"], ["duplicate_bill"])
        c = self.tso.insert("expense_items", {"day_id": d["id"], "category": "lodging", "amount": 1500, "description": "lodge room"}, select="*", single=True)
        self.assertEqual(c["flags"], ["missing_bill"])                                                  # over Rs 100 and no photo
        self.tso.fails("Enter the amount", self.tso.insert, "expense_items", {"day_id": d["id"], "category": "other", "amount": 0, "description": "nothing"})
        self.tso.fails("Not your request", self.tso2.insert, "expense_items", {"day_id": d["id"], "category": "other", "amount": 10, "description": "stolen"})
        got = self.tso.select("field_days", "ta_km, ta_amount, lodging_amount, other_amount, flags, total_claimed", [["eq", "id", d["id"]]])[0]
        self.assertEqual(got["ta_km"], 100)
        self.assertEqual(got["ta_amount"], 100 * 3.5 + 60 + 350)                                         # odometer km x rate + travel bills
        self.assertEqual(got["lodging_amount"], 1500)
        for flag in ("duplicate_bill", "missing_bill", "lodging_over_cap", "lodging_without_halt", "auto_taxi_over_cap", "no_field_work"):
            self.assertIn(flag, got["flags"])
        self.assertEqual(got["total_claimed"], 100 * 3.5 + 60 + 350 + 1500)
        self.tso.q("expense_items", "delete", filters=[["eq", "id", c["id"]]])
        self.assertEqual(self.tso.select("field_days", "lodging_amount", [["eq", "id", d["id"]]])[0]["lodging_amount"], 0)
        events = [e["event"] for e in self.tso.select("claim_events", "event", [["eq", "day_id", d["id"]]], order=[["id", True]])]
        self.assertEqual(events[:2], ["started", "ended"])
        self.assertIn("bill_added", events)
        self.assertIn("bill_removed", events)
        self.assertEqual(self.tso.q("expense_items", "update", values={"amount": 1}, filters=[["eq", "id", a["id"]]], select="id")["data"], [])      # bills have no edit, only delete and add again

    def test_flags_from_visits_and_readings(self):
        d = self.start_day(self.tso, odo=1000)
        self.end_day(self.tso, d, odo=1300)                                                             # 300 km on the meter
        v = self.visit(self.tso, discussion="Detailed discussion with the secretary about the plan.")
        got = self.tso.select("field_days", "visits_count, gps_km, odo_km, flags", [["eq", "id", d["id"]]])[0]
        self.assertEqual(got["visits_count"], 1)
        self.assertIsNotNone(got["gps_km"])
        for flag in ("km_over_daily_limit", "km_above_gps"):
            self.assertIn(flag, got["flags"])
        self.assertNotIn("no_field_work", got["flags"])
        # a rejected visit no longer counts
        self.zm.update("visits", {"zm_status": "rejected", "zm_remark": "Not at the office"}, [["eq", "id", v["id"]]])
        got = self.tso.select("field_days", "visits_count, flags", [["eq", "id", d["id"]]])[0]
        self.assertEqual(got["visits_count"], 0)
        self.assertIn("visits_rejected", got["flags"])
        self.assertIn("no_field_work", got["flags"])

    def test_odometer_must_continue_from_the_last_day(self):
        past = date(2026, 1, 5)
        fetch("insert into kwd_field_days (tso_id, day, travel_mode, vehicle_no, start_odo, end_odo, end_at, status) values (%(t)s, %(d)s, 'two_wheeler', 'KL07AB1234', 5000, 5100, now(), 'open') returning 1",
              {"t": self.tso_id, "d": past})
        d = self.start_day(self.tso, odo=4000)                                                          # lower than the earlier day's end reading
        self.assertIn("odometer_overlap", self.tso.select("field_days", "flags", [["eq", "id", d["id"]]])[0]["flags"])

    # ------------------------------------------------------------------ approval chain
    def ready_request(self, who=None, odo_end=1040):
        who = who or self.tso
        d = self.start_day(who, odo=1000)
        self.end_day(who, d, odo=odo_end)
        who.update("field_days", {"da_requested": 100}, [["eq", "id", d["id"]]])
        return self.submit(who, d)

    def test_zm_verifies_then_ho_approves(self):
        d = self.ready_request()
        total = d["total_claimed"]
        self.assertEqual(total, 140 + 100)
        self.assertEqual(self.zm2.update("field_days", {"status": "zm_approved"}, [["eq", "id", d["id"]]], select="id"), [])           # not their team
        self.assertEqual(self.tso2.update("field_days", {"status": "zm_approved"}, [["eq", "id", d["id"]]], select="id"), [])           # a TSO sees nothing to update
        self.zm.fails("why the amount was cut", self.zm.update, "field_days", {"status": "zm_approved", "approved_amount": 200}, [["eq", "id", d["id"]]])
        self.zm.fails("between 0 and the requested", self.zm.update, "field_days", {"status": "zm_approved", "approved_amount": 999}, [["eq", "id", d["id"]]])
        self.zm.fails("Write the reason", self.zm.update, "field_days", {"status": "rejected"}, [["eq", "id", d["id"]]])
        ok = self.zm.update("field_days", {"status": "zm_approved", "approved_amount": 200, "zm_remark": "Fuel stop not counted", "end_odo": 1, "ta_amount": 1},
                            [["eq", "id", d["id"]]], select="*")[0]
        self.assertEqual((ok["status"], ok["approved_amount"], ok["zm_by"], ok["end_odo"], ok["ta_amount"]), ("zm_approved", 200, str(self.zm_id), 1040, 140))
        self.zm.fails("This step is not allowed", self.zm.update, "field_days", {"status": "ho_approved"}, [["eq", "id", d["id"]]])
        self.ho.fails("why the amount was cut", self.ho.update, "field_days", {"status": "ho_approved", "approved_amount": 150}, [["eq", "id", d["id"]]])
        fin = self.ho.update("field_days", {"status": "ho_approved"}, [["eq", "id", d["id"]]], select="status, approved_amount, ho_by")[0]
        self.assertEqual(fin, {"status": "ho_approved", "approved_amount": 200, "ho_by": str(self.ho_id)})
        self.ho.fails("paid monthly", self.ho.update, "field_days", {"status": "paid", "paid_ref": "UTR1"}, [["eq", "id", d["id"]]])
        events = [e["event"] for e in self.ho.select("claim_events", "event", [["eq", "day_id", d["id"]]], order=[["id", True]])]
        self.assertEqual(events[-3:], ["submitted", "zm_verified", "ho_approved"])

    def test_send_back_and_reject(self):
        d = self.ready_request()
        back = self.zm.update("field_days", {"status": "open", "zm_remark": "Add the odometer photo again"}, [["eq", "id", d["id"]]], select="status, approved_amount")[0]
        self.assertEqual(back, {"status": "open", "approved_amount": None})
        self.tso.update("field_days", {"tso_note": "fixed"}, [["eq", "id", d["id"]]])                    # editable again
        d2 = self.submit(self.tso, d)
        rej = self.ho.update("field_days", {"status": "rejected", "ho_remark": "Not a field day"}, [["eq", "id", d["id"]]], select="status")[0]
        self.assertEqual(rej["status"], "rejected")
        self.assertEqual(d2["status"], "submitted")

    def test_a_managers_own_request_goes_to_head_office(self):
        d = self.ready_request(self.zm)
        self.zm.fails("submitted and locked", self.zm.update, "field_days", {"status": "ho_approved"}, [["eq", "id", d["id"]]])           # their own request: locked for them
        self.assertEqual(self.zm.select("claim_events", "event", [["eq", "day_id", d["id"]]])[-1]["event"], "submitted")
        fin = self.ho.update("field_days", {"status": "ho_approved"}, [["eq", "id", d["id"]]], select="status")[0]                            # straight to HO
        self.assertEqual(fin["status"], "ho_approved")

    def test_who_sees_requests_bills_and_history(self):
        d = self.ready_request()
        self.assertEqual(len(self.tso.select("field_days", "id")), 1)
        self.assertEqual(len(self.zm.select("field_days", "id")), 1)
        self.assertEqual(len(self.ho.select("field_days", "id")), 1)
        for p in (self.tso2, self.zm2, self.fr):
            self.assertEqual(p.select("field_days", "id"), [])
            self.assertEqual(p.select("claim_events", "id"), [])
        rows = self.ho.select("field_days", "*, expense_items(*), person:profiles!field_days_tso_id_fkey(full_name, email)", [["eq", "id", d["id"]]])
        self.assertEqual(rows[0]["person"]["full_name"], "Tina Officer")
        inner = self.ho.select("field_days", "id, person:profiles!field_days_tso_id_fkey!inner(role)", [["eq", "status", "submitted"], ["neq", "person.role", "tso"]])
        self.assertEqual(inner, [])
        self.assertEqual(len(self.ho.select("field_days", "id, person:profiles!field_days_tso_id_fkey!inner(role)", [["eq", "person.role", "tso"]])), 1)

    # ------------------------------------------------------------------ flag and pay
    def last_month(self):
        first = ist_today().replace(day=1)
        end = first - timedelta(days=1)
        return end.replace(day=1), end

    def approved_day(self, tso_id, day, amount=300):
        return fetch_one("insert into kwd_field_days (tso_id, day, travel_mode, status, approved_amount, da_requested, da_amount) values (%(t)s, %(d)s, 'public_transport', 'ho_approved', %(a)s, %(a)s, %(a)s) returning id",
                         {"t": tso_id, "d": day, "a": amount})["id"]

    def test_flagging_and_the_monthly_payment(self):
        m, end = self.last_month()
        d1, d2, d3 = (self.approved_day(self.tso_id, m + timedelta(days=i), 300) for i in (0, 1, 2))
        self.zm.fails("Only Head Office", self.zm.rpc, "flag_day", p_day=str(d3), p_flag=True, p_reason="odd")
        self.ho.fails("Write the reason", self.ho.rpc, "flag_day", p_day=str(d3), p_flag=True, p_reason=" ")
        self.ho.rpc("flag_day", p_day=str(d3), p_flag=True, p_reason="Looks like a duplicate of another claim")
        self.ho.fails("already flagged", self.ho.rpc, "flag_day", p_day=str(d3), p_flag=True, p_reason="again")
        self.assertEqual(self.zm.select("claim_events", "event", [["eq", "day_id", str(d3)], ["eq", "event", "ho_flagged"]]), [])        # only HO sees flag events
        self.assertEqual(len(self.ho.select("claim_events", "event", [["eq", "day_id", str(d3)], ["eq", "event", "ho_flagged"]])), 1)
        self.zm.fails("Only Head Office can pay", self.zm.rpc, "pay_month", p_tso=str(self.tso_id), p_month=str(m), p_ref="UTR1")
        self.ho.fails("payment reference", self.ho.rpc, "pay_month", p_tso=str(self.tso_id), p_month=str(m), p_ref="")
        this_month = ist_today().replace(day=1)
        self.ho.fails("not over yet", self.ho.rpc, "pay_month", p_tso=str(self.tso_id), p_month=str(this_month), p_ref="UTR1")
        pay = self.ho.rpc("pay_month", p_tso=str(self.tso_id), p_month=str(m + timedelta(days=9)), p_ref=" UTR-42 ", p_note="September settlement")
        self.assertEqual((pay["days"], pay["amount"], pay["paid_ref"], pay["month"]), (2, 600, "UTR-42", str(m)))
        statuses = {r["id"]: r["status"] for r in self.ho.select("field_days", "id, status, payment_id")}
        self.assertEqual(sorted(statuses.values()), ["ho_approved", "paid", "paid"])                  # the flagged day is held back
        self.ho.fails("Nothing approved to pay", self.ho.rpc, "pay_month", p_tso=str(self.tso_id), p_month=str(m), p_ref="UTR2")
        self.ho.rpc("flag_day", p_day=str(d3), p_flag=False, p_reason="Checked, it is fine")
        pay2 = self.ho.rpc("pay_month", p_tso=str(self.tso_id), p_month=str(m), p_ref="UTR-43")
        self.assertEqual((pay2["days"], pay2["amount"]), (1, 300))
        # the person and their manager see the payments; others do not
        self.assertEqual(len(self.tso.select("expense_payments", "id")), 2)
        self.assertEqual(len(self.zm.select("expense_payments", "id")), 2)
        self.assertEqual(self.tso2.select("expense_payments", "id"), [])
        self.assertEqual(self.ho.select("audit_log", "action", [["eq", "action", "PAY_MONTH"]]), [{"action": "PAY_MONTH"}] * 2)

    def test_policy_is_changed_only_by_head_office_and_logged(self):
        self.assertEqual(self.tso.select("expense_policy", "rate_two_wheeler")[0]["rate_two_wheeler"], 3.5)
        self.assertEqual(self.zm.update("expense_policy", {"rate_two_wheeler": 99}, [["eq", "id", 1]], select="id"), [])
        out = self.ho.update("expense_policy", {"rate_two_wheeler": 4, "id": 7}, [["eq", "id", 1]], select="id, rate_two_wheeler, updated_by")[0]
        self.assertEqual((out["id"], out["rate_two_wheeler"], out["updated_by"]), (1, 4, str(self.ho_id)))
        log = self.ho.select("audit_log", "action, old_data, new_data", [["eq", "table_name", "expense_policy"]])[0]
        self.assertEqual((log["action"], log["old_data"]["rate_two_wheeler"], log["new_data"]["rate_two_wheeler"]), ("UPDATE", 3.5, 4))
        d = self.start_day(self.tso, odo=1000)
        e = self.end_day(self.tso, d, odo=1010)
        self.assertEqual(e["ta_amount"], 40)                                                            # the new rate applies
