import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from core.models import Franchise, Profile, User

PW = "Test#Pass123"


class Api:
    """A logged-in person talking to the server the way the dashboards do."""

    def __init__(self, client, email, password=PW):
        self.client, self.email = client, email
        r = client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": email, "password": password}),
                        content_type="application/json")
        assert r.status_code == 200, r.content
        self.tok = r.json()
        self.h = {"HTTP_AUTHORIZATION": "Bearer " + self.tok["access_token"], "HTTP_APIKEY": "ignored"}
        self.uid = self.tok["user"]["id"]

    def call(self, fn, **args):
        return self.client.post(f"/rest/v1/rpc/{fn}", data=json.dumps(args), content_type="application/json", **self.h)

    def ok(self, fn, **args):
        r = self.call(fn, **args)
        assert r.status_code == 200, f"{fn} -> {r.status_code} {r.content}"
        return r.json()

    def fail(self, fn, contains, **args):
        r = self.call(fn, **args)
        assert r.status_code >= 400, f"{fn} should have failed but gave {r.status_code} {r.content}"
        msg = r.json().get("message", "")
        assert contains.lower() in msg.lower(), f"{fn}: expected '{contains}' in '{msg}'"
        return r

    def get(self, path):
        return self.client.get("/rest/v1/" + path, **self.h)

    def rows(self, path):
        r = self.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.content}"
        return r.json()


def today_dmy():
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%m-%Y")


class ScrappyTestCase(TestCase):
    def setUp(self):
        cache.clear()
        call_command("seed_defaults", stdout=__import__("io").StringIO())
        self.kkd = Franchise.objects.get(code="KKD")
        self.tvm = Franchise.objects.create(code="TVM", name="Thiruvananthapuram", district="Thiruvananthapuram")

    def person(self, email, name, role, franchise="kkd", **extra):
        u = User.objects.create_user(email, PW)
        fr = getattr(self, franchise) if isinstance(franchise, str) else franchise
        Profile.objects.create(user=u, full_name=name, role=role, franchise=None if role == "hq" else fr, **extra)
        return u

    def make_team(self):
        self.person("hq@t.test", "HQ Admin", "hq")
        self.person("sup@t.test", "Sumi Supervisor", "supervisor")
        self.person("wh@t.test", "Sumesh Warehouse", "warehouse")
        self.person("wh2@t.test", "Second Warehouse", "warehouse")
        self.person("drv@t.test", "Basim Collector", "driver", vehicle_no="KL-07-AB-1234")
        self.person("drv2@t.test", "Rahul Collector", "driver")
        self.person("tvm-wh@t.test", "TVM Warehouse", "warehouse", franchise="tvm")
        self.person("tvm-sup@t.test", "TVM Supervisor", "supervisor", franchise="tvm")
        self.person("tvm-drv@t.test", "TVM Collector", "driver", franchise="tvm")

    def upload_lead(self, hq, driver_email="drv@t.test", name="Anil Kumar", phone="9446012345", area="Kakkanad", **extra):
        row = {"customer_name": name, "phone": phone, "address": "12, Test Road", "area": area, "pickup_date": today_dmy(),
               "pickup_time": "11:30 AM", "items": "iron, paper"}
        if driver_email:
            row["driver_email"] = driver_email
        else:
            row["franchise_code"] = "KKD"
        row.update(extra)
        r = hq.client.post("/rest/v1/lead_import", data=json.dumps([row]), content_type="application/json",
                           HTTP_PREFER="return=representation", **hq.h)
        assert r.status_code == 201, r.content
        return r.json()[0]
