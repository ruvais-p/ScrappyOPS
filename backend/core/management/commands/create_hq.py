import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Profile, User


class Command(BaseCommand):
    help = "Create (or reset the password of) an HQ login. HQ logins cannot be made from the website, so the first one is made here."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True, help="Full name shown in the side panel")
        parser.add_argument("--password", help="If left out you are asked for it (nothing is shown while typing)")

    @transaction.atomic
    def handle(self, *args, **o):
        email = o["email"].strip().lower()
        password = o["password"] or getpass.getpass("Password (at least 8 characters): ")
        if len(password) < 8:
            raise CommandError("The password must be at least 8 characters.")
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email, password)
        else:
            user.set_password(password)
            user.save(update_fields=["password"])
        prof = Profile.objects.filter(pk=user.pk).first()
        if prof is None:
            Profile.objects.create(user=user, full_name=o["name"].strip(), role="hq", franchise=None, active=True)
        elif prof.role != "hq":
            raise CommandError(f"{email} already belongs to a {prof.role}. Use a different email.")
        self.stdout.write(self.style.SUCCESS(f"HQ login ready: {email}"))
