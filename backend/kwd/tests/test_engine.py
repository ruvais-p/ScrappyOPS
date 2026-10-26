from kwd.tests.base import KwdCase, QueryError


class ReadTests(KwdCase):
    def setUp(self):
        super().setUp()
        self.make_world()

    def test_who_sees_which_lsgds(self):
        names = lambda p: sorted(r["name"] for r in p.select("lsgds", "name"))
        self.assertEqual(names(self.ho), ["Edathala Grama Panchayat", "Thrikkakara Municipality", "Thrissur Corporation"])
        self.assertEqual(names(self.zm), ["Edathala Grama Panchayat", "Thrikkakara Municipality"])         # own district only
        self.assertEqual(names(self.zm2), ["Thrissur Corporation"])
        self.assertEqual(names(self.tso), ["Edathala Grama Panchayat", "Thrikkakara Municipality"])
        self.assertEqual(names(self.fr), [])                                                           # a franchisee has no field-staff data

    def test_nested_selects_filters_order_count_single(self):
        rows = self.ho.select("lsgds", "id, name, type, districts(name)", [["eq", "type", "municipality"]])
        self.assertEqual(rows[0]["districts"], {"name": "Ernakulam"})
        rows = self.ho.select("lsgds", "name, districts(name)", order=[["name", True]], limit=2)
        self.assertEqual([r["name"] for r in rows], ["Edathala Grama Panchayat", "Thrikkakara Municipality"])
        self.assertEqual(self.ho.q("lsgds", select="id", count="exact", head=True)["count"], 3)
        self.assertEqual(self.ho.q("lsgds", select="id", count="exact", range=[0, 0])["count"], 3)
        one = self.ho.q("lsgds", select="name", filters=[["eq", "name", "Thrissur Corporation"]], single=True)["data"]
        self.assertEqual(one, {"name": "Thrissur Corporation"})
        none = self.ho.q("lsgds", select="name", filters=[["eq", "name", "nothing"]], maybe=True)["data"]
        self.assertIsNone(none)
        self.ho.fails("multiple (or no) rows", self.ho.q, "lsgds", select="name", single=True)
        self.assertEqual(len(self.ho.select("lsgds", "id", [["in", "name", ["Thrissur Corporation", "Edathala Grama Panchayat"]]])), 2)
        self.assertEqual(len(self.ho.select("lsgds", "id", [["not", "name", "eq", "Thrissur Corporation"]])), 2)
        self.assertEqual(len(self.ho.select("lsgds", "id", [["is", "office_lat", None]])), 1)

    def test_one_to_many_and_inner_joins(self):
        c1 = self.contact(self.zm)
        c2 = self.contact(self.zm, name="Mr President", phone="9446099999")
        rows = self.zm.select("lsgds", "name, contacts(name, phone)", [["eq", "id", self.lsgd]])
        self.assertEqual(sorted(c["name"] for c in rows[0]["contacts"]), ["Mr President", "Mr Secretary"])
        # !inner keeps only rows with a match, and can filter on the joined row
        inner = self.zm.select("contacts", "id, lsgds!inner(name, type)", [["eq", "lsgds.type", "municipality"]])
        self.assertEqual(len(inner), 2)
        inner = self.zm.select("contacts", "id, lsgds!inner(name, type)", [["eq", "lsgds.type", "corporation"]])
        self.assertEqual(inner, [])
        # hint on a link between the same two tables
        r = self.ho.select("profiles", "full_name, manager:profiles!profiles_manager_id_fkey(full_name)", [["eq", "email", "tso@k.test"]])
        self.assertEqual(r[0]["manager"]["full_name"], "Zed Manager")

    def test_errors_for_bad_requests(self):
        self.ho.fails("not find the table", self.ho.q, "nothing_here")
        self.ho.fails("column", self.ho.q, "lsgds", select="nope")
        self.ho.fails("column", self.ho.q, "lsgds", select="*", filters=[["eq", "nope", 1]])
        self.ho.fails("permission denied", self.ho.q, "audit_log", "insert", values={"table_name": "x", "action": "y"})
        r = self.client.post("/kwd/api/q", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_views_are_cut_down_to_what_you_may_see(self):
        self.ho.insert("opportunities", {"lsgd_id": self.lsgd, "stage": "demo_done", "expected_units": 10, "probability": 40})
        self.ho.insert("opportunities", {"lsgd_id": self.lsgd_tsr, "stage": "new", "expected_units": 5, "probability": 10})
        everything = self.ho.select("v_pipeline", "*")
        self.assertEqual(sorted((r["district"], r["units"]) for r in everything), [("Ernakulam", 10), ("Thrissur", 5)])
        mine = self.zm.select("v_pipeline", "*")
        self.assertEqual([(r["district"], r["units"], r["value"], r["weighted_value"]) for r in mine], [("Ernakulam", 10, 58800, 23520)])
        self.assertEqual(self.fr.select("v_pipeline", "*"), [])

    def test_profiles_and_people_visibility(self):
        names = lambda p: sorted(r["full_name"] for r in p.select("profiles", "full_name"))
        self.assertEqual(len(names(self.ho)), 7)
        self.assertEqual(names(self.tso), ["Tina Officer"])
        self.assertEqual(names(self.zm), ["Tina Officer", "Zed Manager"])
        # a manager also sees people who share a district
        self.assertIn("Zed Manager", names(self.zm))
        self.assertEqual(self.tso.select("user_districts", "district_id"), [{"district_id": self.ekm}])
        self.assertEqual(self.tso.select("districts", "name", order=[["id", True]], limit=1), [{"name": "Thiruvananthapuram"}])
        self.assertEqual(self.tso.select("audit_log", "id"), [])                                         # only Head Office reads the log

    def test_only_listed_people_write(self):
        self.tso.fails("row-level security", self.tso.insert, "lsgds", {"name": "X", "type": "municipality", "district_id": self.ekm})
        self.zm.fails("row-level security", self.zm.insert, "lsgds", {"name": "X", "type": "municipality", "district_id": self.tsr})   # not their district
        row = self.zm.insert("lsgds", {"name": "New Panchayat", "type": "grama_panchayat", "district_id": self.ekm}, select="*", single=True)
        self.assertEqual(row["name"], "New Panchayat")
        # an update that matches no allowed row changes nothing and does not fail
        self.assertEqual(self.zm2.update("lsgds", {"name": "Hacked"}, [["eq", "id", row["id"]]], select="id"), [])
        self.assertEqual(self.zm.update("lsgds", {"office_lat": 10.1, "office_lng": 76.3}, [["eq", "id", row["id"]]], select="office_lat")[0]["office_lat"], 10.1)
        self.assertEqual(self.ho.insert("districts", {"name": "Test District"}, select="name", single=True), {"name": "Test District"})
        self.tso.fails("row-level security", self.tso.insert, "districts", {"name": "Nope"})
        self.assertEqual(len(self.ho.select("audit_log", "table_name, action", [["eq", "table_name", "lsgds"]])), 2)   # insert + update logged
        self.zm.q("lsgds", "delete", filters=[["eq", "id", row["id"]]])
        self.assertEqual(self.ho.select("lsgds", "id", [["eq", "id", row["id"]]]), [])
        self.assertEqual(self.ho.select("audit_log", "action", [["eq", "table_name", "lsgds"], ["eq", "action", "DELETE"]])[0]["action"], "DELETE")

    def test_upsert(self):
        o = self.ho.q("opportunities", "upsert", values={"lsgd_id": self.lsgd, "financial_year": "2026-27", "stage": "new", "expected_units": 3},
                      onConflict="lsgd_id,financial_year", select="*", single=True)["data"]
        o2 = self.ho.q("opportunities", "upsert", values={"lsgd_id": self.lsgd, "financial_year": "2026-27", "stage": "demo_done", "expected_units": 8},
                       onConflict="lsgd_id,financial_year", select="*", single=True)["data"]
        self.assertEqual((o["id"], o2["stage"], o2["expected_units"]), (o["id"], "demo_done", 8))
        self.assertEqual(o2["expected_value"], 8 * 5880)                                       # generated by the database
        self.ho.fails("DEFAULT", self.ho.insert, "opportunities", {"lsgd_id": self.lsgd_noloc, "expected_value": 1})

    def test_ignore_duplicate_upsert_preserves_existing_lsgd_and_bulk_writes_are_atomic(self):
        before = self.ho.select("lsgds", "name, office_lat, assigned_tso", [["eq", "id", self.lsgd]])[0]
        skipped = self.ho.q("lsgds", "upsert", values={"name": before["name"], "district_id": self.ekm, "type": "corporation",
                                                           "office_lat": 11.0, "assigned_tso": None},
                            onConflict="name,district_id", ignoreDuplicates=True, select="*")["data"]
        self.assertEqual(skipped, [])
        self.assertEqual(self.ho.select("lsgds", "name, office_lat, assigned_tso", [["eq", "id", self.lsgd]])[0], before)
        self.fr.fails("row-level security", self.fr.q, "lsgds", "upsert", values={"name": before["name"], "district_id": self.ekm,
                                                                                    "type": "corporation"},
                      onConflict="name,district_id", ignoreDuplicates=True)

        self.ho.fails("not allowed", self.ho.q, "lsgds", "upsert", values=[
            {"name": "Atomic import first row", "district_id": self.ekm, "type": "municipality"},
            {"name": "Atomic import invalid row", "district_id": 99999, "type": "municipality"},
        ], onConflict="name,district_id", ignoreDuplicates=True)
        self.assertEqual(self.ho.select("lsgds", "id", [["eq", "name", "Atomic import first row"]]), [])
