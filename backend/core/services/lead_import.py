"""HQ's Excel upload. Each row is checked as it arrives and gets a result: created, duplicate, or error with the reason.
A bad row never stops the good ones. Same checks the database trigger made."""
import logging
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from core.models import Customer, Franchise, Lead, LeadImport, Profile
from core.services.common import ApiError, btrim, fetch, nullify

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

INPUT_FIELDS = ("customer_name", "phone", "address", "area", "upi_id", "driver_email", "pickup_date", "pickup_time",
                "items", "latitude", "longitude", "franchise_code")


def _s(v):
    return "" if v is None else str(v)


def _parse_date(text):
    t = btrim(text)
    try:
        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", t):
            y, m, d = (int(x) for x in t.split("-"))
            return date(y, m, d)
        if re.match(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$", t):
            d, m, y = (int(x) for x in re.split(r"[-/.]", t))
            return date(y, m, d)
    except ValueError:
        raise ApiError(f'Date "{t}" is not a real date. Use DD-MM-YYYY')
    raise ApiError(f'Date "{t}" not understood. Use DD-MM-YYYY')


def _parse_time(text):
    t = btrim(text).upper()
    if t == "":
        return time(9, 0)
    if not re.match(r"^\d{1,2}[:.]\d{2}", t):
        raise ApiError(f'Time "{text}" not understood. Use e.g. 11:30 AM')
    parts = t.replace(".", ":").split(":")
    h, m = int(parts[0]), int(parts[1][:2])
    ampm = re.search(r"(AM|PM)", t)
    ampm = ampm.group(1) if ampm else None
    if ampm == "PM" and h < 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    if h > 23 or m > 59:
        raise ApiError(f'Time "{text}" is not valid')
    return time(h, m, 0)


def _parse_location(lat_text, lng_text):
    la, ln = nullify(lat_text), nullify(lng_text)
    # "10.0159, 76.3419" pasted into the latitude cell alone also works
    if la is not None and ln is None and re.match(r"^\s*-?\d+(\.\d+)?\s*[, ;]\s*-?\d+(\.\d+)?\s*$", la):
        ln = btrim(re.sub(r"^.*[, ;]", "", la))
        la = btrim(re.sub(r"\s*[, ;].*$", "", la))
    if la is None and ln is None:
        return None, None
    if la is None or ln is None:
        raise ApiError("Give both latitude and longitude, or leave both blank")
    if not re.match(r"^-?\d+(\.\d+)?$", la) or not re.match(r"^-?\d+(\.\d+)?$", ln):
        raise ApiError(f'Latitude and longitude must be numbers (got "{la}", "{ln}")')
    lat, lng = Decimal(la), Decimal(ln)
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise ApiError(f'Latitude/longitude out of range (got "{la}", "{ln}"). Latitude first, then longitude')
    if not (6 <= lat <= 38) or not (67 <= lng <= 98):
        raise ApiError(f"Location ({la}, {ln}) is not in India. Check that latitude and longitude are not swapped")
    return lat, lng


def _check_and_create(ctx, d):
    """Validate one row and create its lead. Returns (status, lead_code, message)."""
    if not btrim(d["customer_name"]):
        raise ApiError("Customer name is missing")
    if not btrim(d["address"]):
        raise ApiError("Address is missing")
    phone = re.sub(r"\D", "", _s(d["phone"]))
    if len(phone) > 10:
        phone = phone[-10:]
    if len(phone) != 10:
        raise ApiError(f'Phone must have 10 digits (got "{_s(d["phone"])}")')

    em, fc = nullify(d["driver_email"]), nullify(d["franchise_code"])
    fc = fc.upper() if fc else None
    driver_id, franchise_id = None, None
    if em:
        row = fetch("""select p.id, p.active, p.franchise_id, f.code from users u join profiles p on p.id = u.id and p.role = 'driver'
                       left join franchises f on f.id = p.franchise_id where lower(u.email) = lower(%(e)s)""", {"e": em})
        if not row:
            raise ApiError(f'No driver with email "{em}"')
        row = row[0]
        if not row["active"]:
            raise ApiError(f"Driver {em} is inactive")
        if fc and fc != (row["code"] or "").upper():
            raise ApiError(f"Driver {em} belongs to franchise {row['code']}, not {fc}")
        driver_id, franchise_id = row["id"], row["franchise_id"]
    else:
        if not fc:
            raise ApiError("Give the franchise code (for example KKD)")
        fr = Franchise.objects.filter(code__iexact=fc, active=True).first()
        if fr is None:
            raise ApiError(f'No active franchise with code "{fc}"')
        franchise_id = fr.pk

    pickup_date = _parse_date(d["pickup_date"])
    pickup_time = _parse_time(d["pickup_time"])
    slot = datetime.combine(pickup_date, pickup_time, tzinfo=IST)
    if slot < timezone.now() - timedelta(days=1):
        raise ApiError(f"Pickup date {pickup_date.isoformat()} is in the past")
    lat, lng = _parse_location(d["latitude"], d["longitude"])

    found = fetch("""select id from customers where right(regexp_replace(phone, '\\D', '', 'g'), 10) = %(p)s order by id limit 1""", {"p": phone})
    if not found:
        cust = Customer.objects.create(name=btrim(d["customer_name"]), phone=phone, address=btrim(d["address"]),
                                       area=nullify(d["area"]), upi_id=nullify(d["upi_id"]))
        cust_id = cust.pk
    else:
        cust_id = found[0]["id"]
        upi = nullify(d["upi_id"])
        if upi:
            Customer.objects.filter(pk=cust_id, upi_id__isnull=True).update(upi_id=upi)

    dup = fetch("""select code from leads where customer_id = %(c)s and status in ('unassigned','scheduled','in_progress')
                   and (slot at time zone 'Asia/Kolkata')::date = %(d)s::date limit 1""", {"c": cust_id, "d": pickup_date.isoformat()})
    if dup:
        return "duplicate", dup[0]["code"], "Lead already exists for this customer on this day"

    lead = Lead.objects.create(customer_id=cust_id, driver_id=driver_id, status="unassigned" if driver_id is None else "scheduled",
                               franchise_id=franchise_id, slot=slot, items_said=nullify(d["items"]), created_by_id=ctx.uid,
                               latitude=lat, longitude=lng)
    msg = ("Created, waiting for the supervisor to assign a driver" if driver_id is None else "Created")
    if not btrim(d["pickup_time"]):
        msg += " (no time given, set to 9:00 AM)"
    if lat is None:
        msg += " (no map location)"
    return "created", lead.code, msg


def import_rows(ctx, rows):
    """Add the uploaded rows. Returns the stored rows (blank rows are skipped, as before)."""
    if ctx.role != "hq":
        raise ApiError('new row violates row-level security policy for table "lead_import"', status=403, code="42501")
    if not isinstance(rows, list):
        rows = [rows]
    out = []
    for raw in rows:
        d = {k: (raw or {}).get(k) for k in INPUT_FIELDS}
        if not any(btrim(_s(d[k])) for k in ("customer_name", "phone", "address", "driver_email", "franchise_code", "pickup_date")):
            continue
        try:
            with transaction.atomic():           # a failed row leaves nothing behind
                status, code, message = _check_and_create(ctx, d)
        except ApiError as e:
            status, code, message = "error", None, e.message
        except Exception as e:                   # never lose the whole upload over one strange row
            log.exception("lead import row failed")
            status, code, message = "error", None, "This row could not be read. Check every column."
        out.append(LeadImport.objects.create(
            **{k: (None if d[k] is None else _s(d[k])) for k in INPUT_FIELDS}, status=status, lead_code=code, message=message))
    return out
