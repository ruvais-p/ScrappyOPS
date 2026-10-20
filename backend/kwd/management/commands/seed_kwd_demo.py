"""Development only: a small staff-app world to click through (Head Office, a Zonal Manager, a TSO, a franchisee, and a few
LSGDs, a plan for today and a lead). Refuses to run unless DJANGO_DEBUG=1. Every demo login uses the password below.

    python manage.py seed_kwd_demo
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import User
from core.services.common import fetch, fetch_one

DEMO_PASSWORD = "Demo#Pass123"          # development only
PEOPLE = [
    ("ho@demo.test", "Hema Head Office", "head_office"),
    ("zm@demo.test", "Zara Zonal Manager", "zonal_manager"),
    ("tso@demo.test", "Tina Field Officer", "tso"),
    ("fr@demo.test", "Farid Franchise", "franchisee"),
]


class Command(BaseCommand):
    help = "Create demo staff-app logins and a little data (development only)."

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_kwd_demo is for development only. Set DJANGO_DEBUG=1 to run it.")
        ekm = fetch_one("select id from kwd_districts where name = 'Ernakulam'")["id"]
        ids = {}
        for email, name, role in PEOPLE:
            u = User.objects.filter(email=email).first() or User.objects.create_user(email, DEMO_PASSWORD)
            u.set_password(DEMO_PASSWORD)
            u.save()
            ids[role] = u.pk
            if not fetch_one("select 1 as x from kwd_profiles where id = %(i)s", {"i": u.pk}):
                fetch("insert into kwd_profiles (id, full_name, email, role, is_active) values (%(i)s, %(n)s, %(e)s, %(r)s, true) returning 1",
                      {"i": u.pk, "n": name, "e": email, "r": role})
        fetch("update kwd_profiles set manager_id = %(z)s where id = %(t)s returning 1", {"z": ids["zonal_manager"], "t": ids["tso"]})
        for uid in (ids["zonal_manager"], ids["tso"]):
            fetch("insert into kwd_user_districts (user_id, district_id) values (%(u)s, %(d)s) on conflict do nothing returning 1", {"u": uid, "d": ekm})
        fr = fetch_one("select id from kwd_fr_franchises where user_id = %(u)s", {"u": ids["franchisee"]})
        if not fr:
            fr = fetch_one("insert into kwd_fr_franchises (user_id, business_name, district_id) values (%(u)s, 'Farid Traders', %(d)s) returning id",
                           {"u": ids["franchisee"], "d": ekm})
        lsgds = []
        for name, typ, lat, lng in [("Thrikkakara Municipality", "municipality", 10.0159, 76.3419), ("Edathala Grama Panchayat", "grama_panchayat", None, None),
                                    ("Kalamassery Municipality", "municipality", 10.0536, 76.3199)]:
            row = fetch_one("select id from kwd_lsgds where name = %(n)s and district_id = %(d)s", {"n": name, "d": ekm})
            if not row:
                row = fetch_one("insert into kwd_lsgds (name, type, district_id, assigned_tso, office_lat, office_lng) values (%(n)s, %(t)s, %(d)s, %(s)s, %(la)s, %(ln)s) returning id",
                                {"n": name, "t": typ, "d": ekm, "s": ids["tso"], "la": lat, "ln": lng})
            lsgds.append(row["id"])
        if not fetch_one("select 1 as x from kwd_tasks where assigned_to = %(t)s and planned_date = current_date", {"t": ids["tso"]}):
            fetch("insert into kwd_tasks (lsgd_id, assigned_to, planned_date, purpose, assigned_by) values (%(l)s, %(t)s, current_date, 'Introduce KWD and the 90%% subsidy scheme', %(z)s) returning 1",
                  {"l": lsgds[0], "t": ids["tso"], "z": ids["zonal_manager"]})
        if not fetch_one("select 1 as x from kwd_fr_leads where franchise_id = %(f)s", {"f": fr["id"]}):
            fetch("insert into kwd_fr_leads (franchise_id, customer_name, customer_type, place, district_id, hq_note) values (%(f)s, 'Aluva Municipality', 'lsgd', 'Aluva', %(d)s, 'Annual plan meeting in March') returning 1",
                  {"f": fr["id"], "d": ekm})
        self.stdout.write(self.style.SUCCESS("Demo staff-app logins ready: " + ", ".join(e for e, _, _ in PEOPLE) + f"  (password: {DEMO_PASSWORD})"))
