from django.core.management.base import BaseCommand
from django.conf import settings

from core.models import Bill
from core.services.invoice import bill_data, build_pdf


class Command(BaseCommand):
    help = "Make (or remake) the PDF of every bill that has been sent, so customer links work after moving to this server."

    def add_arguments(self, parser):
        parser.add_argument("--missing-only", action="store_true", help="Skip bills whose PDF file already exists")

    def handle(self, *args, **o):
        folder = settings.MEDIA_ROOT / "bills"
        folder.mkdir(parents=True, exist_ok=True)
        done = failed = skipped = 0
        for bill in Bill.objects.exclude(status="draft").select_related("load").order_by("id"):
            path = folder / f"{bill.bill_no}.pdf"
            if o["missing_only"] and path.exists():
                skipped += 1
                continue
            try:
                d = bill_data(bill)
                if not d["items"]:
                    skipped += 1
                    continue
                path.write_bytes(build_pdf(d))
                Bill.objects.filter(pk=bill.pk).update(pdf_path=path.name)
                done += 1
            except Exception as e:
                failed += 1
                self.stderr.write(f"{bill.bill_no}: {e}")
        self.stdout.write(self.style.SUCCESS(f"{done} PDFs made, {skipped} skipped, {failed} failed."))
