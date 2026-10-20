"""One login, the role picks the dashboard, and the gate keeps people out of dashboards that are not theirs."""
import json

from django.test import Client

from core.models import AuthSession, Franchise, Profile, User
from kwd.tests.base import KwdCase, PW
from portal import gate


class GateTests(KwdCase):
    def setUp(self):
        super().setUp()
        fr = Franchise.objects.create(code="KKD", name="Kakkanad", district="Ernakulam")
        for email, role in [("drv@p.test", "driver"), ("wh@p.test", "warehouse"), ("sup@p.test", "supervisor"), ("hq@p.test", "hq")]:
            u = User.objects.create_user(email, PW)
            Profile.objects.create(user=u, full_name=email.split("@")[0], role=role, franchise=None if role == "hq" else fr)
        self.person_row("tso@p.test", "Tina Officer", "tso")
        self.person_row("zm@p.test", "Zed Manager", "zonal_manager")
        self.person_row("ho@p.test", "Head Office", "head_office")
        self.person_row("fr@p.test", "Fran Chisee", "franchisee")
        User.objects.create_user("norole@p.test", PW)
        self.person_row("off@p.test", "Switched Off", "tso", active=False)

    def login(self, email, password=PW, client=None):
        c = client or Client()
        r = c.post("/login/", data=json.dumps({"email": email, "password": password}), content_type="application/json")
        return c, r

    # ------------------------------------------------------------------------------------------ role -> dashboard
    def test_each_role_lands_on_its_own_dashboard(self):
        expect = {"drv@p.test": "/collector/", "wh@p.test": "/warehouse/", "sup@p.test": "/warehouse/", "hq@p.test": "/hq/",
                  "tso@p.test": "/kwd/", "zm@p.test": "/kwd/", "ho@p.test": "/kwd/", "fr@p.test": "/kwd/"}
        for email, path in expect.items():
            c, r = self.login(email)
            self.assertEqual(r.status_code, 200, email)
            body = r.json()
            self.assertEqual(body["redirect"], path, email)
            self.assertIn(gate.COOKIE, c.cookies, email)
            self.assertTrue(c.cookies[gate.COOKIE]["httponly"])
            # the browser keeps the login where that dashboard reads it
            self.assertEqual(body["storage_key"], gate.STORAGE_KEY[body["dest"]])
            self.assertTrue(body["session"]["access_token"] and body["session"]["refresh_token"])

    def test_kwd_login_is_stored_in_the_format_the_staff_app_reads(self):
        _, r = self.login("tso@p.test")
        s = r.json()["session"]
        self.assertEqual(r.json()["storage_key"], "scrappy_kwd_session")
        self.assertEqual(s["user"]["email"], "tso@p.test")
        self.assertGreater(s["expires_at"], 10 ** 12)          # milliseconds

    def test_scrap_login_is_stored_in_the_format_the_dashboards_read(self):
        _, r = self.login("drv@p.test")
        s = r.json()["session"]
        self.assertEqual(r.json()["storage_key"], "scrappy_session")
        self.assertEqual(set(s), {"access_token", "refresh_token", "expires_at", "user_id"})

    def test_login_without_a_role_opens_nothing_and_leaves_no_session(self):
        for email in ("norole@p.test", "off@p.test"):
            c, r = self.login(email)
            self.assertEqual(r.status_code, 403, email)
            self.assertNotIn(gate.COOKIE, c.cookies)
        self.assertFalse(AuthSession.objects.filter(user__email__in=["norole@p.test", "off@p.test"]).exists())

    def test_wrong_password_is_refused_in_plain_words(self):
        c, r = self.login("tso@p.test", "nope")
        self.assertEqual(r.status_code, 400)
        self.assertIn("don’t match", r.json()["error"])
        self.assertNotIn(gate.COOKIE, c.cookies)

    # ------------------------------------------------------------------------------------------ the gate
    def test_dashboards_need_a_login(self):
        c = Client()
        for path in ("/collector/", "/warehouse/", "/hq/", "/kwd/", "/hq/index.html", "/kwd"):
            r = c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertEqual(r["Location"], "/login/", path)

    def test_you_cannot_open_someone_elses_dashboard(self):
        c, _ = self.login("tso@p.test")
        for path in ("/hq/", "/collector/", "/warehouse/"):
            r = c.get(path)
            self.assertEqual((r.status_code, r["Location"]), (302, "/kwd/"), path)
        c, _ = self.login("drv@p.test")
        r = c.get("/kwd/")
        self.assertEqual((r.status_code, r["Location"]), (302, "/collector/"))
        r = c.get("/hq/")
        self.assertEqual(r["Location"], "/collector/")

    def test_staff_app_page_opens_for_staff(self):
        for email in ("tso@p.test", "zm@p.test", "ho@p.test", "fr@p.test"):
            c, _ = self.login(email)
            r = c.get("/kwd/")
            self.assertEqual(r.status_code, 200, email)
            self.assertIn(b"/static/kwd/js/app.js", r.content)
            self.assertEqual(r["Cache-Control"], "no-cache")

    def test_data_calls_are_not_page_gated(self):
        # they carry a token and guard themselves; without one they answer 401 JSON, not a redirect to the login page
        r = Client().post("/kwd/api/q", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(Client().get("/healthz").status_code, 200)

    def test_front_door_sends_you_to_your_dashboard_or_the_login(self):
        self.assertEqual(Client().get("/")["Location"], "/login/")
        c, _ = self.login("hq@p.test")
        r = c.get("/")
        self.assertEqual((r.status_code, r["Location"]), (302, "/hq/"))

    def test_a_dashboard_that_bounces_you_back_does_not_loop(self):
        c, _ = self.login("hq@p.test")
        r = c.get("/")                                  # sent to /hq/, with the short "hop" marker
        self.assertEqual(r["Location"], "/hq/")
        r = c.get("/")                                  # the dashboard had no browser login and sent us back
        self.assertEqual(r["Location"], "/login/")
        self.assertEqual(c.cookies[gate.COOKIE].value, "")      # the stale cookie is cleared, so the login page shows
        r = c.get("/login/")
        self.assertEqual(r.status_code, 200)

    def test_logged_out_message_is_shown_and_clears_the_cookie(self):
        c, _ = self.login("tso@p.test")
        r = c.get("/login/?m=You+were+logged+out")
        self.assertEqual(r.status_code, 200)
        self.assertIn("You were logged out", r.content.decode())
        self.assertEqual(c.cookies[gate.COOKIE].value, "")

    def test_login_page_for_a_signed_in_person_goes_to_their_dashboard(self):
        c, _ = self.login("zm@p.test")
        r = c.get("/login/")
        self.assertEqual((r.status_code, r["Location"]), (302, "/kwd/"))

    # ------------------------------------------------------------------------------------------ sessions
    def test_newest_login_wins_and_the_old_cookie_stops_working(self):
        old, _ = self.login("tso@p.test")
        self.assertEqual(old.get("/kwd/").status_code, 200)
        self.login("tso@p.test")                               # same person, another device
        r = old.get("/kwd/")
        self.assertEqual((r.status_code, r["Location"]), (302, "/login/"))

    def test_sign_out_ends_the_session_and_the_cookie(self):
        c, _ = self.login("tso@p.test")
        r = c.post("/logout/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(AuthSession.objects.filter(user__email="tso@p.test").exists())
        self.assertEqual(c.get("/kwd/")["Location"], "/login/")

    def test_sign_out_by_address_goes_to_the_login_page(self):
        c, _ = self.login("tso@p.test")
        r = c.get("/logout/?m=Bye")
        self.assertEqual((r.status_code, r["Location"]), (302, "/login/?m=Bye"))
        self.assertEqual(c.get("/kwd/")["Location"], "/login/")

    def test_a_forged_or_tampered_cookie_opens_nothing(self):
        c, _ = self.login("tso@p.test")
        c.cookies[gate.COOKIE] = c.cookies[gate.COOKIE].value[:-3] + "xyz"
        self.assertEqual(c.get("/kwd/")["Location"], "/login/")
        c2 = Client()
        c2.cookies[gate.COOKIE] = "abc.def.ghi"
        self.assertEqual(c2.get("/hq/")["Location"], "/login/")

    def test_a_role_change_moves_the_person_to_the_new_dashboard(self):
        c, _ = self.login("tso@p.test")
        Profile  # (core profile not involved: change the staff role instead)
        from core.services.common import fetch
        fetch("update kwd_profiles set is_active = false where email = 'tso@p.test' returning 1")
        self.assertEqual(c.get("/kwd/")["Location"], "/login/")     # switched off: no dashboard at all

    # ------------------------------------------------------------------------------------------ session poll + static files
    def test_session_poll_tells_when_the_login_was_replaced(self):
        c = Client()
        _, r = self.login("tso@p.test", client=c)
        tok = r.json()["session"]["access_token"]
        h = {"HTTP_AUTHORIZATION": "Bearer " + tok}
        self.assertEqual(c.get("/kwd/api/session", **h).json(), {"valid": True})
        self.login("tso@p.test")
        self.assertEqual(c.get("/kwd/api/session", **h).json(), {"valid": False})
        self.assertEqual(c.get("/kwd/api/session").json(), {"valid": None})        # no token: cannot tell

    def test_static_files_are_served(self):
        c = Client()
        for path, kind in (("/static/kwd/js/app.js", "javascript"), ("/static/kwd/css/theme.css", "css"), ("/static/portal/login.js", "javascript"),
                           ("/static/kwd/brand/scrappy-wordmark-oxblood.svg", "svg")):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(kind, r["Content-Type"], path)

    def test_login_page_renders(self):
        r = Client().get("/login/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="login-form"', html)
        self.assertIn("/static/portal/login.js", html)
