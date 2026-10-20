from datetime import date, timedelta

from core.services.common import fetch, fetch_one
from kwd.tests.base import KwdCase, QueryError
from kwd.rules.util import ist_today


class VisitTests(KwdCase):
    def setUp(self):
        super().setUp()
        self.make_world()

    def plan(self, who=None, assignee=None, lsgd=None, day=None):
        return (who or self.zm).insert("tasks", {"lsgd_id": lsgd or self.lsgd, "assigned_to": assignee or self.tso_id,
                                                  "planned_date": str(day or ist_today()), "purpose": "Introduce the digester"}, select="*", single=True)

    def test_planned_visit_inside_the_geofence_has_no_flags_and_ticks_the_task(self):
        t = self.plan()
        v = self.visit(self.tso)
        self.assertEqual(v["fraud_flags"], [])
        self.assertEqual(v["task_id"], t["id"])
        self.assertLess(v["distance_from_office_m"], 50)
        self.assertEqual(self.tso.select("tasks", "status", [["eq", "id", t["id"]]]), [{"status": "done"}])
        self.assertEqual(v["zm_status"], "pending")

    def test_every_fraud_flag(self):
        v = self.visit(self.tso)                                                               # nothing planned
        self.assertEqual(v["fraud_flags"], ["unplanned"])
        far = self.visit(self.tso, lat=10.2, lng=76.5)                                          # about 27 km from the office
        self.assertIn("outside_geofence", far["fraud_flags"])
        self.assertIn("impossible_travel", far["fraud_flags"])                                  # the previous visit was seconds ago
        self.assertIn("weak_gps", self.visit(self.tso, acc=250)["fraud_flags"])
        nogps = self.tso.insert("visits", {"lsgd_id": self.lsgd, "photo_path": self.tso.upload()}, select="*", single=True)
        self.assertIn("no_gps", nogps["fraud_flags"])
        noloc = self.visit(self.tso, lsgd=self.lsgd_noloc)
        self.assertIn("lsgd_location_missing", noloc["fraud_flags"])
        for _ in range(4):
            last = self.visit(self.tso)
        self.assertIn("high_volume_day", last["fraud_flags"])                                   # eight were already made today, so the 9th is flagged

    def test_the_server_decides_time_and_owner(self):
        v = self.tso.insert("visits", {"lsgd_id": self.lsgd, "photo_path": self.tso.upload(), "check_in_lat": 10.0159, "check_in_lng": 76.3419,
                                        "tso_id": self.tso2_id, "check_in_at": "2020-01-01T00:00:00Z", "zm_status": "verified",
                                        "fraud_flags": [], "distance_from_office_m": 0}, select="*", single=True)
        self.assertEqual(v["tso_id"], str(self.tso_id))
        self.assertTrue(v["check_in_at"].startswith(str(ist_today().year)))
        self.assertEqual((v["zm_status"], v["distance_from_office_m"] is not None), ("pending", True))

    def test_who_may_visit(self):
        self.ho.fails("row-level security", self.ho.insert, "visits", {"lsgd_id": self.lsgd, "photo_path": self.ho.upload()})
        self.tso2.fails("row-level security", self.tso2.insert, "visits", {"lsgd_id": self.lsgd, "photo_path": self.tso2.upload()})   # not their LSGD
        self.fr.fails("row-level security", self.fr.insert, "visits", {"lsgd_id": self.lsgd, "photo_path": self.fr.upload()})
        v = self.visit(self.zm)                                                                  # a manager visits too
        self.assertEqual(v["tso_id"], str(self.zm_id))

    def test_visits_are_private_to_the_people_who_may_see_them(self):
        v = self.visit(self.tso)
        self.assertEqual(len(self.tso.select("visits", "id")), 1)
        self.assertEqual(len(self.zm.select("visits", "id")), 1)
        self.assertEqual(len(self.ho.select("visits", "id")), 1)
        self.assertEqual(self.tso2.select("visits", "id"), [])
        self.assertEqual(self.zm2.select("visits", "id"), [])
        joined = self.zm.select("visits", "id, lsgds(name, districts(name)), visit_contacts(contacts(name, designation))")
        self.assertEqual(joined[0]["lsgds"]["districts"]["name"], "Ernakulam")
        self.assertEqual(joined[0]["visit_contacts"][0]["contacts"]["designation"], "Secretary")

    def test_details_can_be_added_later_within_the_time_limits(self):
        v = self.visit(self.tso)
        self.assertIsNone(v["details_at"])
        self.tso.fails("at least 20 characters", self.tso.update, "visits", {"discussion": "too short"}, [["eq", "id", v["id"]]])
        done = self.tso.update("visits", {"discussion": "Met the secretary; agreed a demo next week.", "outcome": "positive", "interest_level": 4,
                                            "next_followup_on": str(ist_today() + timedelta(days=7))}, [["eq", "id", v["id"]]], select="*")[0]
        self.assertIsNotNone(done["details_at"])
        # after the quick check-in is 3 days old, it can no longer be completed
        v2 = self.visit(self.tso)
        fetch("update kwd_visits set check_in_at = now() - interval '4 days' where id = %(i)s returning 1", {"i": v2["id"]})
        self.tso.fails("3 days to add details are over", self.tso.update, "visits", {"discussion": "Written far too late to be believed."}, [["eq", "id", v2["id"]]])
        # a completed visit locks 12 hours after check-in
        fetch("update kwd_visits set check_in_at = now() - interval '13 hours' where id = %(i)s returning 1", {"i": v["id"]})
        self.tso.fails("locked 12 hours", self.tso.update, "visits", {"discussion": "Changing the story after a night's sleep."}, [["eq", "id", v["id"]]])

    def test_evidence_cannot_be_edited_by_the_owner(self):
        v = self.visit(self.tso, discussion="A proper discussion of the digester with the secretary.")
        out = self.tso.update("visits", {"check_in_lat": 1.0, "photo_path": "x/y.png", "fraud_flags": [], "distance_from_office_m": 1, "zm_status": "verified",
                                          "zm_remark": "great", "check_in_at": "2020-01-01T00:00:00Z"}, [["eq", "id", v["id"]]], select="*")[0]
        for c in ("check_in_lat", "photo_path", "fraud_flags", "distance_from_office_m", "check_in_at"):
            self.assertEqual(out[c], v[c], c)
        self.assertEqual((out["zm_status"], out["zm_remark"]), ("pending", None))                # cannot review their own visit
        co = self.tso.update("visits", {"check_out_at": "2026-01-01T00:00:00Z"}, [["eq", "id", v["id"]]], select="check_out_at")[0]["check_out_at"]
        self.assertTrue(co.startswith(str(ist_today().year)))                                    # check-out time is the server's too

    def test_zonal_manager_review_rules(self):
        quick = self.visit(self.tso)
        full = self.visit(self.tso, discussion="Discussed the proposal and the DPC schedule with the secretary.")
        self.zm.fails("details of this visit are not filled in", self.zm.update, "visits", {"zm_status": "verified"}, [["eq", "id", quick["id"]]])
        ok = self.zm.update("visits", {"zm_status": "verified", "zm_remark": "Called and confirmed", "discussion": "tampered", "ho_signed_at": "2026-01-01T00:00:00Z"},
                            [["eq", "id", full["id"]]], select="*")[0]
        self.assertEqual((ok["zm_status"], ok["zm_reviewed_by"], ok["discussion"], ok["ho_signed_at"]), ("verified", str(self.zm_id), full["discussion"], None))
        self.assertEqual(self.zm2.update("visits", {"zm_status": "rejected"}, [["eq", "id", full["id"]]], select="id"), [])    # not their district
        self.assertEqual(self.tso2.update("visits", {"zm_status": "rejected"}, [["eq", "id", full["id"]]], select="id"), [])
        self.tso.fails("already reviewed", self.tso.update, "visits", {"discussion": "Trying to rewrite it after review, which is locked."}, [["eq", "id", full["id"]]])
        flagged = self.zm.update("visits", {"zm_status": "flagged", "zm_remark": "Looks odd"}, [["eq", "id", quick["id"]]], select="zm_status")[0]
        self.assertEqual(flagged["zm_status"], "flagged")

    def test_a_manager_cannot_review_their_own_visit_head_office_does(self):
        v = self.visit(self.zm, discussion="Visited the municipality office to discuss the plan.")
        out = self.zm.update("visits", {"zm_status": "verified"}, [["eq", "id", v["id"]]], select="zm_status")[0]
        self.assertEqual(out["zm_status"], "pending")
        self.assertEqual(self.ho.update("visits", {"zm_status": "verified", "ho_remark": "ok"}, [["eq", "id", v["id"]]], select="zm_status, zm_reviewed_by")[0],
                         {"zm_status": "verified", "zm_reviewed_by": str(self.ho_id)})

    def test_head_office_sign_off(self):
        quick = self.visit(self.tso)
        full = self.visit(self.tso, discussion="Detailed discussion about the annual plan inclusion.")
        self.ho.fails("not filled in", self.ho.update, "visits", {"ho_signed_at": "2026-01-01T00:00:00Z"}, [["eq", "id", quick["id"]]])
        out = self.ho.update("visits", {"ho_signed_at": "2026-01-01T00:00:00Z", "discussion": "x"}, [["eq", "id", full["id"]]], select="ho_signed_by, ho_signed_at, discussion")[0]
        self.assertEqual(out["ho_signed_by"], str(self.ho_id))
        self.assertTrue(out["ho_signed_at"].startswith(str(ist_today().year)))
        self.assertEqual(out["discussion"], full["discussion"])

    def test_tasks_done_only_by_a_visit_and_only_for_my_team(self):
        t = self.plan()
        self.tso.fails("row-level security", self.tso.insert, "tasks", {"lsgd_id": self.lsgd, "assigned_to": self.tso_id, "planned_date": str(ist_today()), "purpose": "self"})
        self.zm.fails("row-level security", self.zm.insert, "tasks", {"lsgd_id": self.lsgd, "assigned_to": self.tso2_id, "planned_date": str(ist_today()), "purpose": "not mine"})
        self.zm.fails("row-level security", self.zm.insert, "tasks", {"lsgd_id": self.lsgd_tsr, "assigned_to": self.tso_id, "planned_date": str(ist_today()), "purpose": "other district"})
        self.zm.fails("marked done only by a visit", self.zm.update, "tasks", {"status": "done"}, [["eq", "id", t["id"]]])
        self.assertEqual(self.zm.update("tasks", {"status": "cancelled", "assigned_by": self.tso_id}, [["eq", "id", t["id"]]], select="status, assigned_by")[0],
                         {"status": "cancelled", "assigned_by": str(self.zm_id)})
        self.assertEqual(self.tso.select("tasks", "id", [["eq", "id", t["id"]]]), [{"id": t["id"]}])
        self.assertEqual(self.tso2.select("tasks", "id"), [])
        self.zm.q("tasks", "delete", filters=[["eq", "id", t["id"]]])
        self.assertEqual(self.zm.select("tasks", "id"), [])

    def test_verification_calls_and_contacts(self):
        v = self.visit(self.tso)
        c = self.contact(self.tso)
        self.tso.fails("row-level security", self.tso.insert, "contacts", {"lsgd_id": self.lsgd, "name": "Self Verified", "designation": "X", "verified_by": self.tso_id})
        self.tso.fails("row-level security", self.tso.insert, "verification_calls", {"contact_id": c["id"], "visit_id": v["id"], "outcome": "confirmed"})
        call = self.zm.insert("verification_calls", {"contact_id": c["id"], "visit_id": v["id"], "outcome": "denied", "called_by": self.tso_id}, select="*", single=True)
        self.assertEqual((call["called_by"], call["confirmed"]), (str(self.zm_id), False))
        call2 = self.zm.insert("verification_calls", {"contact_id": c["id"], "outcome": "unreachable"}, select="confirmed", single=True)
        self.assertIsNone(call2["confirmed"])
        self.zm2.fails("row-level security", self.zm2.insert, "verification_calls", {"contact_id": c["id"], "outcome": "confirmed"})
        self.assertEqual(self.tso.select("verification_calls", "id"), [])
        # a manager verifies the contact; the stamp is the server's and cannot be undone
        out = self.zm.update("contacts", {"verified_at": "2020-01-01T00:00:00Z", "verified_by": self.tso_id, "lsgd_id": self.lsgd_tsr}, [["eq", "id", c["id"]]], select="*")[0]
        self.assertEqual((out["verified_by"], out["lsgd_id"]), (str(self.zm_id), str(self.lsgd)))
        again = self.zm.update("contacts", {"verified_at": None, "verified_by": None}, [["eq", "id", c["id"]]], select="verified_by, verified_at")[0]
        self.assertEqual(again["verified_by"], str(self.zm_id))
        self.assertIsNotNone(again["verified_at"])
        self.assertEqual(self.tso.update("contacts", {"name": "Hacked"}, [["eq", "id", c["id"]]], select="id"), [])      # a TSO cannot edit contacts

    def test_followups(self):
        f = self.tso.insert("followups", {"lsgd_id": self.lsgd, "due_on": str(ist_today() - timedelta(days=1)), "mode": "call", "notes": "Call the secretary"}, select="*", single=True)
        self.assertEqual(f["assigned_to"], str(self.tso_id))
        overdue = self.tso.select("v_overdue_followups", "id, lsgd_name")
        self.assertEqual(overdue, [{"id": f["id"], "lsgd_name": "Thrikkakara Municipality"}])
        self.tso.fails("row-level security", self.tso.insert, "followups", {"lsgd_id": self.lsgd, "assigned_to": self.tso2_id, "due_on": str(ist_today())})
        done = self.tso.update("followups", {"done_at": "2020-01-01T00:00:00Z", "done_note": "Spoke to him"}, [["eq", "id", f["id"]]], select="done_at")[0]["done_at"]
        self.assertTrue(done.startswith(str(ist_today().year)))
        self.assertEqual(self.tso.select("v_overdue_followups", "id"), [])
        self.assertEqual(len(self.zm.select("followups", "id")), 1)            # the manager of that district sees it
        self.assertEqual(self.zm2.select("followups", "id"), [])

    def test_opportunity_rules(self):
        o = self.tso.insert("opportunities", {"lsgd_id": self.lsgd, "stage": "first_meeting", "expected_units": 20, "probability": 25}, select="*", single=True)
        self.assertEqual((o["owner_id"], o["expected_value"], o["financial_year"]), (str(self.tso_id), 20 * 5880, "2026-27"))
        self.assertRaises(QueryError, self.tso.insert, "opportunities", {"lsgd_id": self.lsgd})          # one deal per LSGD per year
        self.tso2.fails("row-level security", self.tso2.insert, "opportunities", {"lsgd_id": self.lsgd, "financial_year": "2027-28"})
        up = self.zm.update("opportunities", {"stage": "demo_done"}, [["eq", "id", o["id"]]], select="stage, updated_at")[0]
        self.assertEqual(up["stage"], "demo_done")
