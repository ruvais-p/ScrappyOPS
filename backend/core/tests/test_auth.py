import json
import time
from datetime import timedelta

import jwt

from django.test import override_settings
from django.conf import settings
from django.utils import timezone

from core.models import AuthSession, User
from core.tests.base import Api, PW, ScrappyTestCase


class AuthTests(ScrappyTestCase):
    def test_login_wrong_password_and_rate_limit(self):
        self.make_team()
        bad = lambda: self.client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": "hq@t.test", "password": "nope"}),
                                       content_type="application/json")
        r = bad()
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_description"], "Invalid login credentials")
        with override_settings(LOGIN_MAX_FAILURES=3):
            for _ in range(3):
                bad()
            r = bad()
            self.assertEqual(r.status_code, 429)
            good = self.client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": "hq@t.test", "password": PW}),
                                    content_type="application/json")
            self.assertEqual(good.status_code, 429)          # locked even for the right password, for a while

    def test_unknown_email_looks_like_wrong_password(self):
        r = self.client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": "nobody@x.test", "password": "whatever1"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_description"], "Invalid login credentials")

    def test_account_limit_cannot_be_evaded_by_changing_ip(self):
        self.make_team()
        with override_settings(LOGIN_MAX_FAILURES=2):
            for address in ("198.51.100.1", "198.51.100.2"):
                r = self.client.post("/auth/v1/token?grant_type=password",
                                     data=json.dumps({"email": "hq@t.test", "password": "wrong"}),
                                     content_type="application/json", REMOTE_ADDR=address)
                self.assertEqual(r.status_code, 400)
            r = self.client.post("/auth/v1/token?grant_type=password",
                                 data=json.dumps({"email": "hq@t.test", "password": PW}),
                                 content_type="application/json", REMOTE_ADDR="198.51.100.3")
            self.assertEqual(r.status_code, 429)

    def test_malformed_login_and_sessionless_token_are_rejected(self):
        self.make_team()
        for body in ('[]', '{"email": 12, "password": "guess"}'):
            r = self.client.post("/auth/v1/token?grant_type=password", data=body, content_type="application/json")
            self.assertEqual(r.status_code, 400)
        user = User.objects.get(email="drv@t.test")
        now = int(time.time())
        forged = jwt.encode({"iss": settings.PUBLIC_BASE_URL + "/auth/v1", "aud": "authenticated",
                             "sub": str(user.pk), "iat": now, "exp": now + 60}, settings.JWT_SECRET, algorithm="HS256")
        r = self.client.get("/rest/v1/scrap_items", HTTP_AUTHORIZATION="Bearer " + forged)
        self.assertEqual(r.status_code, 401)

    def test_expired_session_cannot_read_public_catalog(self):
        self.make_team()
        person = Api(self.client, "drv@t.test")
        AuthSession.objects.filter(user_id=person.uid).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(person.get("scrap_items").status_code, 401)

    def test_newest_login_wins(self):
        self.make_team()
        first = Api(self.client, "drv@t.test")
        self.assertTrue(first.ok("session_valid"))
        second = Api(self.client, "drv@t.test")          # logs in on another phone
        self.assertFalse(first.ok("session_valid"))      # the page checks this every 20 seconds and signs out
        self.assertTrue(second.ok("session_valid"))
        first.fail("my_leads", "opened on another device")
        # the old phone cannot keep itself alive with its refresh token either
        r = self.client.post("/auth/v1/token?grant_type=refresh_token", data=json.dumps({"refresh_token": first.tok["refresh_token"]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(AuthSession.objects.filter(user__email="drv@t.test").count(), 1)

    @override_settings(SINGLE_SESSION=False)
    def test_single_session_can_be_switched_off(self):
        self.make_team()
        a, b = Api(self.client, "drv@t.test"), Api(self.client, "drv@t.test")
        self.assertTrue(a.ok("session_valid") and b.ok("session_valid"))

    def test_refresh_and_two_pages_refreshing_together(self):
        self.make_team()
        a = Api(self.client, "wh@t.test")
        post = lambda tok: self.client.post("/auth/v1/token?grant_type=refresh_token", data=json.dumps({"refresh_token": tok}), content_type="application/json")
        r1 = post(a.tok["refresh_token"])
        self.assertEqual(r1.status_code, 200)
        r2 = post(a.tok["refresh_token"])                # the same old token again, a moment later (another tab)
        self.assertEqual(r2.status_code, 200)
        new = r2.json()
        h = {"HTTP_AUTHORIZATION": "Bearer " + new["access_token"]}
        self.assertEqual(self.client.post("/rest/v1/rpc/session_valid", data="{}", content_type="application/json", **h).json(), True)
        # and the token from the first refresh still works as well
        r3 = post(r1.json()["refresh_token"])
        self.assertEqual(r3.status_code, 200)
        # a token nobody ever had is refused
        self.assertEqual(post("garbage").status_code, 400)

    def test_logout_ends_only_this_login(self):
        self.make_team()
        a = Api(self.client, "wh@t.test")
        r = self.client.post("/auth/v1/logout?scope=local", **a.h)
        self.assertEqual(r.status_code, 204)
        self.assertFalse(a.ok("session_valid"))

    def test_expired_and_missing_tokens_are_401(self):
        self.make_team()
        r = self.client.post("/rest/v1/rpc/my_leads", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/rest/v1/rpc/my_leads", data="{}", content_type="application/json", HTTP_AUTHORIZATION="Bearer sb_publishable_abc")
        self.assertEqual(r.status_code, 401)
        with override_settings(ACCESS_TOKEN_SECONDS=-60):
            a = Api(self.client, "wh@t.test")
        r = a.call("my_leads")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["message"], "JWT expired")

    def test_user_endpoint_gives_the_email(self):
        self.make_team()
        a = Api(self.client, "Sup@T.test")               # email is not case sensitive
        r = self.client.get("/auth/v1/user", **a.h)
        self.assertEqual(r.json()["email"], "sup@t.test")

    def test_passwords_imported_from_bcrypt_still_work(self):
        import bcrypt
        h = bcrypt.hashpw(b"OldSupabase#1", bcrypt.gensalt(rounds=4, prefix=b"2a")).decode()
        u = User.objects.create_user("old@t.test", "temp")
        User.objects.filter(pk=u.pk).update(password="bcrypt$" + h)       # how the import command stores it
        r = self.client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": "old@t.test", "password": "OldSupabase#1"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
