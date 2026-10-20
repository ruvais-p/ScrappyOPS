import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import TestCase

from core.api.views import Encoder
from core.models import User
from core.services.common import fetch, fetch_one

PW = "Test#Pass123"
IST = ZoneInfo("Asia/Kolkata")
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?"
       b"\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82")


class QueryError(Exception):
    def __init__(self, error, status):
        super().__init__(error.get("message"))
        self.message, self.code, self.status = error.get("message", ""), error.get("code"), status


class Person:
    """A logged-in person talking to the staff API the way the pages do."""

    def __init__(self, client, email, password=PW):
        self.client, self.email = client, email
        r = client.post("/auth/v1/token?grant_type=password", data=json.dumps({"email": email, "password": password}), content_type="application/json")
        assert r.status_code == 200, r.content
        self.tok = r.json()
        self.uid = self.tok["user"]["id"]
        self.h = {"HTTP_AUTHORIZATION": "Bearer " + self.tok["access_token"]}

    def raw(self, path, body):
        return self.client.post(path, data=json.dumps(body, cls=Encoder), content_type="application/json", **self.h)

    def q(self, table, op="select", **kw):
        r = self.raw("/kwd/api/q", {"table": table, "op": op, **kw})
        body = r.json()
        if r.status_code >= 400:
            raise QueryError(body["error"], r.status_code)
        return body

    def select(self, table, select="*", filters=None, **kw):
        return self.q(table, select=select, filters=filters or [], **kw)["data"]

    def insert(self, table, values, select=None, single=False):
        return self.q(table, "insert", values=values, select=select, single=single)["data"]

    def update(self, table, values, filters, select=None):
        return self.q(table, "update", values=values, filters=filters, select=select)["data"]

    def rpc(self, fn, **args):
        r = self.raw(f"/kwd/api/rpc/{fn}", args)
        body = r.json()
        if r.status_code >= 400:
            raise QueryError(body["error"], r.status_code)
        return body["data"]

    def fn(self, name, **body):
        r = self.raw(f"/kwd/api/fn/{name}", body)
        out = r.json()
        if r.status_code >= 400:
            raise QueryError(out["error"], r.status_code)
        return out

    def upload(self, name=None):
        path = f"{self.uid}/{name or uuid.uuid4().hex[:12]}.png"
        r = self.client.post(f"/kwd/api/storage/upload?path={path}", data=PNG, content_type="image/png", **self.h)
        assert r.status_code == 200, r.content
        return path

    def fails(self, contains, fn, *a, **k):
        try:
            fn(*a, **k)
        except QueryError as e:
            assert contains.lower() in e.message.lower(), f"expected '{contains}' in '{e.message}'"
            return e
        raise AssertionError(f"should have failed with '{contains}'")


class KwdCase(TestCase):
    def setUp(self):
        cache.clear()
        self.users = {}

    def person_row(self, email, name, role, manager=None, active=True, districts=()):
        u = User.objects.create_user(email, PW)
        fetch("insert into kwd_profiles (id, full_name, email, role, manager_id, is_active) values (%(i)s, %(n)s, %(e)s, %(r)s, %(m)s, %(a)s) returning 1",
              {"i": u.pk, "n": name, "e": email, "r": role, "m": manager, "a": active})
        for d in districts:
            fetch("insert into kwd_user_districts (user_id, district_id) values (%(u)s, %(d)s) returning 1", {"u": u.pk, "d": d})
        return u.pk

    def make_world(self):
        """HO, two zonal managers (Ernakulam / Thrissur), a TSO under each, one franchisee, and a few LSGDs."""
        ekm = fetch_one("select id from kwd_districts where name = 'Ernakulam'")["id"]
        tsr = fetch_one("select id from kwd_districts where name = 'Thrissur'")["id"]
        self.ekm, self.tsr = ekm, tsr
        self.ho_id = self.person_row("ho@k.test", "Head Office", "head_office")
        self.zm_id = self.person_row("zm@k.test", "Zed Manager", "zonal_manager", districts=[ekm])
        self.zm2_id = self.person_row("zm2@k.test", "Other Manager", "zonal_manager", districts=[tsr])
        self.tso_id = self.person_row("tso@k.test", "Tina Officer", "tso", manager=self.zm_id, districts=[ekm])
        self.tso2_id = self.person_row("tso2@k.test", "Tom Officer", "tso", manager=self.zm2_id, districts=[tsr])
        self.fr_user = self.person_row("fr@k.test", "Fran Chisee", "franchisee")
        self.fr_user2 = self.person_row("fr2@k.test", "Other Franchisee", "franchisee")
        self.fr_id = fetch_one("insert into kwd_fr_franchises (user_id, business_name, district_id) values (%(u)s, 'Fran Traders', %(d)s) returning id", {"u": self.fr_user, "d": ekm})["id"]
        self.fr2_id = fetch_one("insert into kwd_fr_franchises (user_id, business_name, district_id) values (%(u)s, 'Other Traders', %(d)s) returning id", {"u": self.fr_user2, "d": tsr})["id"]
        # office near Kakkanad
        self.lsgd = fetch_one("insert into kwd_lsgds (name, type, district_id, office_lat, office_lng) values ('Thrikkakara Municipality', 'municipality', %(d)s, 10.0159, 76.3419) returning id", {"d": ekm})["id"]
        self.lsgd_noloc = fetch_one("insert into kwd_lsgds (name, type, district_id) values ('Edathala Grama Panchayat', 'grama_panchayat', %(d)s) returning id", {"d": ekm})["id"]
        self.lsgd_tsr = fetch_one("insert into kwd_lsgds (name, type, district_id, office_lat, office_lng) values ('Thrissur Corporation', 'corporation', %(d)s, 10.5276, 76.2144) returning id", {"d": tsr})["id"]
        self.ho, self.zm, self.zm2 = Person(self.client, "ho@k.test"), Person(self.client, "zm@k.test"), Person(self.client, "zm2@k.test")
        self.tso, self.tso2 = Person(self.client, "tso@k.test"), Person(self.client, "tso2@k.test")
        self.fr, self.fr2 = Person(self.client, "fr@k.test"), Person(self.client, "fr2@k.test")

    def contact(self, who, lsgd=None, name="Mr Secretary", phone="9446012345"):
        return who.insert("contacts", {"lsgd_id": lsgd or self.lsgd, "name": name, "designation": "Secretary", "phone": phone}, select="*", single=True)

    def visit(self, who, lsgd=None, lat=10.0160, lng=76.3420, acc=20, discussion=None, contacts=1, **extra):
        v = {"lsgd_id": lsgd or self.lsgd, "check_in_lat": lat, "check_in_lng": lng, "gps_accuracy_m": acc, "photo_path": who.upload()}
        if discussion:
            v["discussion"] = discussion
        v.update(extra)
        row = who.insert("visits", v, select="*", single=True)
        for i in range(contacts):
            c = self.contact(who, lsgd, name=f"Person {i}", phone=f"94460123{i}0")
            who.insert("visit_contacts", {"visit_id": row["id"], "contact_id": c["id"]})
        return row

    def start_day(self, who, odo=1000, mode="two_wheeler"):
        d = {"travel_mode": mode, "start_lat": 10.0, "start_lng": 76.3, "start_acc": 15}
        if mode in ("two_wheeler", "car"):
            d.update(vehicle_no="kl 07 ab 1234", start_odo=odo, start_photo=who.upload())
        return who.insert("field_days", d, select="*", single=True)
