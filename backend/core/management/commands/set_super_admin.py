from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Profile


class Command(BaseCommand):
    help = "Promote an existing HQ login to a separate Super Admin role, or return it to HQ."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("action", choices=("grant", "revoke"))

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        profile = Profile.objects.select_for_update().filter(user__email=email).first()
        if profile is None:
            raise CommandError(f"No profile found for {email}.")
        if profile.role not in ("hq", "super_admin") or not profile.active:
            raise CommandError("Only an active HQ or Super Admin login can be changed.")
        granting = options["action"] == "grant"
        profile.role = "super_admin" if granting else "hq"
        profile.is_super_admin = granting
        profile.save(update_fields=["role", "is_super_admin"])
        verb = "granted to" if profile.is_super_admin else "revoked from"
        self.stdout.write(self.style.SUCCESS(f"Super Admin access {verb} {email}."))
