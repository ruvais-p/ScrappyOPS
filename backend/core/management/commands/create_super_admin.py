import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Profile, User


class Command(BaseCommand):
    help = "Create a separate, read-only Super Admin login for business intelligence."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--password", help="If omitted, enter a password interactively")

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"] or getpass.getpass("Password (at least 8 characters): ")
        if len(password) < 8:
            raise CommandError("The password must be at least 8 characters.")
        if User.objects.filter(email=email).exists():
            raise CommandError("That email already has a login. Use set_super_admin to promote an active HQ login.")
        user = User.objects.create_user(email, password)
        Profile.objects.create(
            user=user,
            full_name=options["name"].strip(),
            role="super_admin",
            active=True,
            is_super_admin=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Super Admin login ready: {email}"))
