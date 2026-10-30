"""The one-time copy of the staff app's data out of its Supabase project. The "Supabase" here is a second database built from the
same table definitions, with the tables presented the way Supabase does (a schema named like the app's tables, and a logins
table with bcrypt hashes)."""
import importlib
import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import bcrypt
import psycopg
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, TestCase, override_settings

from core.models import User
from core.services.common import fetch, fetch_one
from kwd import schema, storage
from kwd.tests.base import PNG

PW = "Old#Supabase1"


def server_url(dbname):
    s = connection.settings_dict
    return f"postgresql://{quote(s['USER'])}:{quote(s['PASSWORD'] or '')}@{s['HOST'] or 'localhost'}:{s['PORT'] or 5432}/{dbname}"


class ImportTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dbname = "kwd_src_" + uuid.uuid4().hex[:8]
        admin = psycopg.connect(server_url("postgres"), autocommit=True)
        admin.execute(f'create database "{cls.dbname}"')
        admin.close()
        cls.src = psycopg.connect(server_url(cls.dbname), autocommit=True)
        up = importlib.import_module("kwd.migrations.0001_kwd_schema").UP
        cls.src.execute("create table users (id uuid primary key, email text)")          # what kwd_profiles points at
        cls.src.execute(up)
        cls.src.execute("create schema app")
        for api, (table, _c, _g) in schema.TABLES.items():
            if cls.src.execute("select to_regclass(%s)", [table]).fetchone()[0]:           # tables added after the old project do not exist in it
                cls.src.execute(f'create view app."{api}" as select * from "{table}"')
        cls.src.execute("create schema authx")
        cls.src.execute("create table authx.users (id uuid primary key, email text, encrypted_password text, created_at timestamptz default now(), last_sign_in_at timestamptz)")
        cls.fill()

    @classmethod
    def tearDownClass(cls):
        cls.src.close()
        admin = psycopg.connect(server_url("postgres"), autocommit=True)
        admin.execute(f'drop database if exists "{cls.dbname}" with (force)')
        admin.close()
        super().tearDownClass()

    @classmethod
    def person(cls, email, name, role, manager=None):
        uid = uuid.uuid4()
        h = bcrypt.hashpw(PW.encode(), bcrypt.gensalt(4)).decode()
        cls.src.execute("insert into users (id, email) values (%s, %s)", [uid, email])
        cls.src.execute("insert into authx.users (id, email, encrypted_password) values (%s, %s, %s)", [uid, email.upper(), h])
        cls.src.execute("insert into kwd_profiles (id, full_name, email, role, manager_id, is_active) values (%s, %s, %s, %s, %s, true)", [uid, name, email, role, manager])
        return uid

    @classmethod
    def fill(cls):
        s = cls.src
        # the source's districts differ from the starting ones on purpose: they must replace them, ids included
        s.execute("delete from kwd_districts")
        s.execute("insert into kwd_districts (id, name) values (7, 'Ernakulam'), (9, 'Palakkad')")
        cls.zm = cls.person("zm@old.test", "Old Manager", "zonal_manager")
        cls.tso = cls.person("tso@old.test", "Old Officer", "tso", cls.zm)
        cls.fr_user = cls.person("fr@old.test", "Old Franchisee", "franchisee")
        s.execute("insert into kwd_user_districts (user_id, district_id) values (%s, 7), (%s, 7)", [cls.zm, cls.tso])
        cls.lsgd = uuid.uuid4()
        s.execute("insert into kwd_lsgds (id, name, type, district_id, assigned_tso) values (%s, 'Aluva Municipality', 'municipality', 7, %s)", [cls.lsgd, cls.tso])
        cls.photo = f"{cls.tso}/2026-09-01/board.jpg"
        cls.visit = uuid.uuid4()
        s.execute("insert into kwd_visits (id, lsgd_id, tso_id, photo_path, check_in_lat, check_in_lng, fraud_flags) values (%s, %s, %s, %s, 10.1, 76.3, %s)",
                  [cls.visit, cls.lsgd, cls.tso, cls.photo, ["unplanned"]])
        cls.day = uuid.uuid4()
        s.execute("insert into kwd_field_days (id, tso_id, day, travel_mode, status, ta_amount, da_requested, da_amount) values (%s, %s, '2026-09-01', 'none', 'ho_approved', 0, 100, 100)",
                  [cls.day, cls.tso])
        s.execute("insert into kwd_claim_events (day_id, actor, event, amount, meta) values (%s, %s, 'submitted', 100, %s)", [cls.day, cls.tso, psycopg.types.json.Jsonb({"k": 1})])
        s.execute("insert into kwd_claim_events (day_id, actor, event) values (%s, %s, 'ho_approved')", [cls.day, cls.zm])
        cls.fr = uuid.uuid4()
        s.execute("insert into kwd_fr_franchises (id, user_id, business_name, district_id) values (%s, %s, 'Old Traders', 9)", [cls.fr, cls.fr_user])
        cls.product = s.execute("select id from kwd_fr_products where code = 'KWD-120'").fetchone()[0]
        s.execute("insert into kwd_fr_stock_moves (franchise_id, product_id, kind, qty) values (%s, %s, 'opening', 4)", [cls.fr, cls.product])

    def run_import(self, *extra, **kw):
        out = StringIO()
        call_command("import_kwd_from_supabase", "--source", server_url(self.dbname), "--schema", "app", "--auth-schema", "authx", *extra, stdout=out, **kw)
        return out.getvalue()

    # --------------------------------------------------------------------------------------
    def test_data_logins_and_counters_come_across(self):
        self.run_import()
        self.assertEqual(fetch_one("select count(*) as n from kwd_profiles")["n"], 3)
        self.assertEqual([r["id"] for r in fetch("select id from kwd_districts order by id")], [7, 9])      # the source's own ids
        v = fetch_one("select * from kwd_visits")
        self.assertEqual((str(v["id"]), v["fraud_flags"], v["photo_path"]), (str(self.visit), ["unplanned"], self.photo))
        ev = fetch("select event, meta from kwd_claim_events order by id")
        self.assertEqual([e["event"] for e in ev], ["submitted", "ho_approved"])
        self.assertEqual(ev[0]["meta"], {"k": 1})
        # generated columns are worked out again here, not copied
        self.assertEqual(float(fetch_one("select total_claimed from kwd_field_days")["total_claimed"]), 100.0)
        # counters continue after the highest copied id: a new history line gets the next number
        new = fetch_one("insert into kwd_claim_events (day_id, actor, event) values (%(d)s, %(a)s, 'paid') returning id", {"d": self.day, "a": self.tso})
        self.assertEqual(new["id"], max(e["id"] for e in fetch("select id from kwd_claim_events")))
        self.assertGreater(new["id"], 2)
        # links between tables are strict again afterwards
        with self.assertRaises(Exception):
            fetch("insert into kwd_tasks (lsgd_id, assigned_to, assigned_by, planned_date, purpose) values (%(l)s, %(u)s, %(u)s, current_date, 'x') returning 1",
                  {"l": uuid.uuid4(), "u": self.tso})

    def test_old_passwords_still_work_and_the_person_lands_in_the_staff_app(self):
        self.run_import()
        c = Client()
        r = c.post("/login/", data=json.dumps({"email": "tso@old.test", "password": PW}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["redirect"], "/kwd/")
        h = {"HTTP_AUTHORIZATION": "Bearer " + r.json()["session"]["access_token"]}
        q = c.post("/kwd/api/q", data=json.dumps({"table": "visits", "op": "select", "select": "id, lsgds(name)", "filters": [], "order": []}),
                   content_type="application/json", **h)
        self.assertEqual(q.status_code, 200, q.content)
        self.assertEqual(q.json()["data"][0]["lsgds"]["name"], "Aluva Municipality")

    def test_dry_run_changes_nothing(self):
        out = self.run_import("--dry-run")
        self.assertIn("Dry run", out)
        self.assertEqual(fetch_one("select count(*) as n from kwd_profiles")["n"], 0)
        self.assertEqual(fetch_one("select count(*) as n from kwd_districts")["n"], 14)          # the starting rows are still there
        self.assertFalse(User.objects.filter(email="tso@old.test").exists())

    def test_it_refuses_a_login_that_already_exists_here(self):
        User.objects.create_user("tso@old.test", "x")
        with self.assertRaises(CommandError) as e:
            self.run_import()
        self.assertIn("tso@old.test", str(e.exception))
        self.assertEqual(fetch_one("select count(*) as n from kwd_profiles")["n"], 0)             # nothing half-done

    def test_it_refuses_when_the_staff_app_already_has_data(self):
        self.run_import()
        with self.assertRaises(CommandError):
            self.run_import()

    def test_photos_are_copied_from_a_folder_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as bucket, override_settings(MEDIA_ROOT=Path(media)):
            f = Path(bucket) / self.photo
            f.parent.mkdir(parents=True)
            f.write_bytes(PNG)
            out = self.run_import("--storage-dir", bucket)
            self.assertIn("1 copied", out)
            self.assertTrue(storage.file_of(self.photo).read_bytes().startswith(b"\xff\xd8"))      # saved as a JPEG, like every upload
            self.assertTrue(storage.exists(self.photo))

    def test_a_photo_that_is_not_a_picture_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as bucket, override_settings(MEDIA_ROOT=Path(media)):
            f = Path(bucket) / self.photo
            f.parent.mkdir(parents=True)
            f.write_bytes(b"jpeg-bytes")
            out = self.run_import("--storage-dir", bucket)
            self.assertIn("not a readable photo", out)
            self.assertIn("Staff app data imported.", out)
            self.assertFalse(storage.exists(self.photo))

    def test_without_a_photo_source_it_says_what_is_missing(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=Path(media)):
            out = self.run_import()
            self.assertIn("1 photo(s) are referenced", out)
            self.assertFalse(storage.exists(self.photo))
