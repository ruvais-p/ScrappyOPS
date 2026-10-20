from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Franchise, Rate, ScrapItem

# the materials and starting rates the system launched with (HQ can change them any time on the Rates screen)
ITEMS = [("Iron", 28), ("Aluminium", 120), ("Paper", 10), ("Plastic", 12), ("Copper", 650), ("E-waste", 30)]


class Command(BaseCommand):
    help = "Create the first franchise (KKD, Kakkanad) and the starting materials with their rates, if they are not there yet."

    @transaction.atomic
    def handle(self, *args, **opts):
        if not Franchise.objects.exists():
            Franchise.objects.create(code="KKD", name="Kakkanad", district="Ernakulam")
            self.stdout.write("Franchise KKD created.")
        if not ScrapItem.objects.exists():
            for name, rate in ITEMS:
                item = ScrapItem.objects.create(name=name, active=True)
                Rate.objects.create(item=item, rate_per_kg=rate)
            self.stdout.write(f"{len(ITEMS)} materials created with their rates.")
        self.stdout.write(self.style.SUCCESS("Defaults are in place."))
