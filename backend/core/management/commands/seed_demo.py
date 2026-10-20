from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Franchise, Profile, User


class Command(BaseCommand):
    help = "DEVELOPMENT ONLY: make one login for every role (HQ, supervisor, warehouse manager, collector) with a known password."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Scrappy#2026")

    @transaction.atomic
    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=1. Never use known passwords on a live system.")
        from django.core.management import call_command
        call_command("seed_defaults")
        fr = Franchise.objects.get(code="KKD")
        people = [("hq@scrappy.test", "HQ Admin", "hq", None), ("supervisor@scrappy.test", "Sumi Supervisor", "supervisor", fr),
                  ("warehouse@scrappy.test", "Sumesh Warehouse", "warehouse", fr), ("driver@scrappy.test", "Basim Collector", "driver", fr)]
        for email, name, role, f in people:
            u = User.objects.filter(email=email).first() or User.objects.create_user(email, o["password"])
            Profile.objects.get_or_create(user=u, defaults={"full_name": name, "role": role, "franchise": f,
                                                            "vehicle_no": "KL-07-AB-1234" if role == "driver" else None})
            self.stdout.write(f"{role:11} {email}")
        self.stdout.write(self.style.SUCCESS(f"Demo logins ready. Password: {o['password']}"))
