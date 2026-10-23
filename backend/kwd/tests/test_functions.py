from core.models import User
from core.services.common import fetch_one
from kwd.functions import resolve_map_link
from kwd.tests.base import KwdCase, PW, Person, PNG, QueryError


class AdminUsersTests(KwdCase):
    def setUp(self):
        super().setUp()
        self.make_world()

    def test_only_head_office_manages_staff(self):
        self.zm.fails("Only Head Office", self.zm.fn, "admin-users", action="create", email="x@k.test", password="longenough1", full_name="X")
        self.tso.fails("Only Head Office", self.tso.fn, "admin-users", action="reset_password", id=self.tso2_id, password="longenough1")

    def test_create_update_deactivate_and_reset(self):
        self.ho.fails("at least 8 characters", self.ho.fn, "admin-users", action="create", email="n@k.test", password="short", full_name="N")
        self.ho.fails("Full name", self.ho.fn, "admin-users", action="create", email="n@k.test", password="longenough1", full_name=" ")
        self.ho.fails("already exists", self.ho.fn, "admin-users", action="create", email="TSO@k.test", password="longenough1", full_name="Dup")
        self.ho.fails("Business name", self.ho.fn, "admin-users", action="create", email="f@k.test", password="longenough1", full_name="F", profile={"role": "franchisee"})
        out = self.ho.fn("admin-users", action="create", email="New.Tso@K.test", password="longenough1", full_name="Nina New",
                         profile={"role": "tso", "manager_id": str(self.zm_id), "district_ids": [self.ekm, self.tsr], "phone": "9446000000"})
        new = Person(self.client, "new.tso@k.test", "longenough1")                                       # works straight away
        prof = new.select("profiles", "full_name, role, manager_id, is_active, phone")[0]
        self.assertEqual(prof, {"full_name": "Nina New", "role": "tso", "manager_id": str(self.zm_id), "is_active": True, "phone": "9446000000"})
        self.assertEqual(sorted(d["district_id"] for d in new.select("user_districts", "district_id")), sorted([self.ekm, self.tsr]))
        self.assertEqual(len(self.zm.select("user_districts", "district_id", [["eq", "user_id", out["id"]]])), 2)
        # a franchisee login also gets the business record
        fr = self.ho.fn("admin-users", action="create", email="shop@k.test", password="longenough1", full_name="Shop Owner",
                        profile={"role": "franchisee", "franchise": {"business_name": "Shop Traders", "district_id": self.ekm, "gstin": ""}})
        shop = Person(self.client, "shop@k.test", "longenough1")
        self.assertEqual(shop.select("fr_franchises", "business_name, gstin"), [{"business_name": "Shop Traders", "gstin": None}])
        # update: move to another manager, change the districts
        self.ho.fn("admin-users", action="update", id=out["id"], profile={"manager_id": str(self.zm2_id), "district_ids": [self.tsr]})
        self.assertEqual(self.ho.select("profiles", "manager_id", [["eq", "id", out["id"]]]), [{"manager_id": str(self.zm2_id)}])
        self.assertEqual(len(self.ho.select("user_districts", "district_id", [["eq", "user_id", out["id"]]])), 1)
        self.ho.fails("cannot deactivate or demote", self.ho.fn, "admin-users", action="update", id=str(self.ho_id), profile={"is_active": False})
        # deactivating signs the person out and blocks the login
        self.ho.fn("admin-users", action="update", id=out["id"], profile={"is_active": False})
        self.assertRaises(AssertionError, Person, self.client, "new.tso@k.test", "longenough1")
        self.assertFalse(User.objects.get(email="new.tso@k.test").is_active)
        self.ho.fn("admin-users", action="update", id=out["id"], profile={"is_active": True})
        again = Person(self.client, "new.tso@k.test", "longenough1")
        # reset a password
        self.ho.fails("at least 8", self.ho.fn, "admin-users", action="reset_password", id=out["id"], password="x")
        self.ho.fn("admin-users", action="reset_password", id=out["id"], password="brandnewpass1")
        self.assertRaises(AssertionError, Person, self.client, "new.tso@k.test", "longenough1")
        Person(self.client, "new.tso@k.test", "brandnewpass1")
        self.assertEqual(self.ho.select("audit_log", "action", [["eq", "table_name", "staff_admin"]], order=[["id", True]])[0:2],
                         [{"action": "CREATE_LOGIN"}, {"action": "CREATE_LOGIN"}])

    def test_an_inactive_person_has_no_access(self):
        self.ho.update("profiles", {"is_active": False}, [["eq", "id", str(self.tso_id)]])
        self.assertEqual(self.tso.select("lsgds", "id"), [])
        self.tso.fails("inactive", self.tso.rpc, "flag_day", p_day=str(self.tso_id), p_flag=True, p_reason="x")


class MapLinkTests(KwdCase):
    def test_coordinates_in_links(self):
        f = lambda url, ref=None: resolve_map_link({"url": url, "ref": ref})
        self.assertEqual(f("https://www.google.com/maps/place/Thrikkakara/@10.0159,76.3419,17z"), {"lat": 10.0159, "lng": 76.3419})
        self.assertEqual(f("https://www.google.com/maps?q=11.1950,76.2310"), {"lat": 11.195, "lng": 76.231})
        self.assertEqual(f("https://www.google.com/maps/place/X/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d10.5276!4d76.2144"), {"lat": 10.5276, "lng": 76.2144})

    def test_plus_codes(self):
        from kwd.functions import _olc_decode, _olc_encode
        code = _olc_encode(10.0159, 76.3419)
        back = _olc_decode(code)
        self.assertAlmostEqual(back["lat"], 10.0159, places=3)
        self.assertAlmostEqual(back["lng"], 76.3419, places=3)
        full = resolve_map_link({"url": code})
        self.assertAlmostEqual(full["lat"], 10.0159, places=3)
        short = code[4:]
        got = resolve_map_link({"url": short, "ref": {"lat": 10.0, "lng": 76.3}})            # a short code is placed near the district centre
        self.assertAlmostEqual(got["lat"], 10.0159, places=3)
        self.assertAlmostEqual(got["lng"], 76.3419, places=3)

    def test_refusals(self):
        from core.services.common import ApiError
        for bad in ("hello", "http://www.google.com/maps/@1,2", "https://evil.example.com/maps?q=1,2", "https://localhost/x"):
            with self.assertRaises(ApiError):
                resolve_map_link({"url": bad})


class StorageTests(KwdCase):
    def setUp(self):
        super().setUp()
        self.make_world()

    def test_photos_can_be_filed_under_dated_sub_folders(self):
        # the visit screen files each check-in photo under <user id>/<date>/<file>
        nested = f"{self.tso_id}/2026-10-20/abc123.jpg"
        r = self.client.post(f"/kwd/api/storage/upload?path={nested}", data=PNG, content_type="image/jpeg", **self.tso.h)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.zm.raw("/kwd/api/storage/sign", {"path": nested, "expiresIn": 60}).status_code, 200)
        self.assertNotEqual(self.tso2.raw("/kwd/api/storage/sign", {"path": nested, "expiresIn": 60}).status_code, 200)
        too_deep = f"{self.tso_id}/a/b/c/d.jpg"
        self.assertEqual(self.client.post(f"/kwd/api/storage/upload?path={too_deep}", data=PNG, content_type="image/jpeg", **self.tso.h).status_code, 403)

    def test_upload_sign_and_read(self):
        path = self.tso.upload("evidence.jpg")
        r = self.client.post(f"/kwd/api/storage/upload?path={path}", data=PNG, content_type="image/png", **self.tso.h)
        self.assertEqual(r.status_code, 409)                                                     # a file is never replaced
        other = f"{self.tso2_id}/mine.jpg"
        r = self.client.post(f"/kwd/api/storage/upload?path={other}", data=PNG, content_type="image/png", **self.tso.h)
        self.assertEqual(r.status_code, 403)                                                     # only into your own folder
        r = self.client.post(f"/kwd/api/storage/upload?path={self.tso_id}/x.jpg", data=b"not an image", content_type="text/plain", **self.tso.h)
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/kwd/api/storage/upload?path={self.tso_id}/../hack.jpg", data=PNG, content_type="image/png", **self.tso.h)
        self.assertEqual(r.status_code, 403)
        for who, ok in ((self.tso, True), (self.zm, True), (self.ho, True), (self.tso2, False), (self.fr, False)):
            r = who.raw("/kwd/api/storage/sign", {"path": path, "expiresIn": 300})
            self.assertEqual(r.status_code == 200, ok, who.email)
        url = self.zm.raw("/kwd/api/storage/sign", {"path": path, "expiresIn": 300}).json()["signedUrl"]
        got = self.client.get(url)
        self.assertEqual((got.status_code, got["Content-Type"]), (200, "image/jpeg"))
        self.assertTrue(b"".join(got.streaming_content).startswith(b"\xff\xd8"))          # stored as a JPEG, whatever was sent
        self.assertEqual(self.client.get("/kwd/api/storage/object?token=garbage").status_code, 404)
