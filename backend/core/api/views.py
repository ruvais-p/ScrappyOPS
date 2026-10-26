"""The HTTP surface. Same addresses and answer formats as the service this replaces."""
import inspect
import json
import ipaddress
import logging
import time
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.db import DataError, IntegrityError, connection, transaction
from django.http import FileResponse, HttpResponse, JsonResponse

from core import auth
from core.models import (AuthSession, Bill, BillItem, Franchise, HqAudit, ImmutableError, Lead, Load, Profile, ScrapItem,
                         User)
from core.services import hq as hq_service            # noqa: F401  (registers the HQ actions)
from core.services import super_admin as super_admin_service  # noqa: F401
from core.services import lead_import                 # noqa: F401
from core.services import dispatch, pickup, warehouse   # noqa: F401  (register the collector, warehouse and stock-to-HQ actions)
from core.services.common import ApiError, Ctx, UUID_RE, btrim
from core.services.registry import RPC, rpc

log = logging.getLogger("scrappy.api")


# ---------------------------------------------------------------------------------------------- JSON
class Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() and abs(o) < 10**15 else float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


def jr(data, status=200):
    resp = HttpResponse(json.dumps(data, cls=Encoder, separators=(",", ":")), status=status, content_type="application/json")
    resp["Cache-Control"] = "no-store"
    return resp


def err(message, status=400, code="P0001", details=None, hint=None):
    return jr({"code": code, "details": details, "hint": hint, "message": message}, status)


def body_json(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body)
    except ValueError:
        raise ApiError("The request body is not valid JSON.", code="PGRST102")


def healthz(request):
    with connection.cursor() as cur:
        cur.execute("select 1")
    return jr({"ok": True})


# ---------------------------------------------------------------------------------------------- login
def _client_ip(request):
    # Caddy overwrites X-Real-IP; never trust the caller-controlled X-Forwarded-For chain.
    candidate = request.META.get("HTTP_X_REAL_IP", "") or request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"


def token(request):
    if request.method != "POST":
        return jr({"msg": "Use POST"}, 405)
    grant = request.GET.get("grant_type", "")
    try:
        data = body_json(request)
        if grant == "password":
            out = auth.login(data.get("email"), data.get("password"), _client_ip(request))
        elif grant == "refresh_token":
            out = auth.refresh_login(data.get("refresh_token"))
        else:
            return jr({"error": "unsupported_grant_type", "error_description": "Unsupported grant type", "msg": "Unsupported grant type"}, 400)
        return jr(out)
    except auth.AuthError as e:
        return jr(e.body, e.status)
    except ApiError as e:
        return jr({"error": "invalid_request", "error_description": e.message, "msg": e.message}, 400)


def logout(request):
    if request.method != "POST":
        return jr({"msg": "Use POST"}, 405)
    try:
        ctx = auth.context_from_request(request, required=False)
        if ctx and ctx.session_id:
            auth.logout_session(ctx.session_id)
    except auth.AuthError:
        pass                                  # already signed out: nothing to do
    return HttpResponse(status=204)


def user_info(request):
    try:
        ctx = auth.context_from_request(request)
    except auth.AuthError as e:
        return jr(e.body, e.status)
    if not ctx.session_valid():
        return jr({"code": 403, "error_code": "session_not_found", "msg": "Session not found"}, 403)
    u = User.objects.filter(pk=ctx.uid).first()
    if u is None:
        return jr({"code": 403, "error_code": "user_not_found", "msg": "User not found"}, 403)
    return jr({"id": str(u.pk), "aud": "authenticated", "role": "authenticated", "email": u.email,
               "created_at": u.created_at, "last_sign_in_at": u.last_login})


# ---------------------------------------------------------------------------------------------- actions (rpc)
@rpc()
def session_valid(ctx):
    """False once the same person has logged in somewhere else."""
    return ctx.session_valid()


def rpc_call(request, fn):
    if request.method != "POST":
        return jr({"message": "Use POST"}, 405)
    try:
        ctx = auth.context_from_request(request)
    except auth.AuthError as e:
        return jr(e.body, e.status)
    handler = RPC.get(fn)
    if handler is None:
        return err(f"Could not find the function public.{fn} in the schema cache", 404, "PGRST202")
    try:
        args = body_json(request)
        if not isinstance(args, dict):
            raise ApiError("The arguments must be a JSON object.", code="PGRST102")
        try:
            inspect.signature(handler).bind(ctx, **args)
        except TypeError:
            return err(f"Could not find the function public.{fn}({', '.join(sorted(args))}) in the schema cache", 404, "PGRST202")
        if fn != "session_valid" and not ctx.session_valid():
            raise ApiError("You were logged out because this account was opened on another device.")
        with transaction.atomic():
            result = handler(ctx, **args)
        return jr(result)
    except ApiError as e:
        return err(e.message, e.status, e.code, e.details, e.hint)
    except ImmutableError as e:
        return err(str(e), 400, "P0001")
    except (IntegrityError, DataError) as e:
        log.warning("rpc %s rejected by the database: %s", fn, e)
        return err("That change is not allowed. Check the values and try again.", 400, "23000")
    except Exception:
        log.exception("rpc %s failed", fn)
        return err("Something went wrong on the server. Try again.", 500, "XX000")


# ---------------------------------------------------------------------------------------------- tables
def rest_table(request, table):
    from core.api.rest import query_table
    try:
        ctx = auth.context_from_request(request)
    except auth.AuthError as e:
        return jr(e.body, e.status)
    try:
        if request.method == "GET":
            return jr(query_table(ctx, table, {k: v for k, v in request.GET.items()}))
        if request.method == "POST" and table == "lead_import":
            from core.services.lead_import import import_rows
            from core.models import LeadImport
            with transaction.atomic():
                rows = import_rows(ctx, body_json(request))
            wants = "return=representation" in request.headers.get("Prefer", "")
            if not wants:
                return HttpResponse(status=201)
            cols = ["id", "customer_name", "phone", "address", "area", "upi_id", "driver_email", "pickup_date", "pickup_time", "items",
                    "status", "message", "lead_code", "imported_at", "latitude", "longitude", "franchise_code"]
            data = list(LeadImport.objects.filter(pk__in=[r.pk for r in rows]).order_by("id").values(*cols))
            return jr(data, 201)
        return err(f'permission denied for table {table}', 403, "42501")
    except ApiError as e:
        return err(e.message, e.status, e.code, e.details, e.hint)
    except (IntegrityError, DataError) as e:
        log.warning("table %s rejected by the database: %s", table, e)
        return err("That request is not valid.", 400, "22000")
    except Exception:
        log.exception("table %s failed", table)
        return err("Something went wrong on the server. Try again.", 500, "XX000")


# ---------------------------------------------------------------------------------------------- PDF bill
def _plain(msg, status):
    r = HttpResponse(msg, status=status, content_type="text/plain; charset=utf-8")
    r["Cache-Control"] = "no-store"
    return r


def bill_pdf(request):
    from core.services.invoice import build_pdf, bill_data
    if request.method == "GET":
        # the customer's link: always the newest PDF, so after payment it shows PAID
        t = request.GET.get("t", "")
        if not UUID_RE.match(t):
            return _plain("This bill link is not valid.", 404)
        bill = Bill.objects.filter(share_token=t).first()
        path = (settings.MEDIA_ROOT / "bills" / f"{bill.bill_no}.pdf") if bill and bill.pdf_path else None
        if not path or not path.exists():
            return _plain("This bill is not ready yet. Please try again in a minute.", 404)
        resp = FileResponse(open(path, "rb"), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{bill.bill_no}.pdf"'
        resp["Cache-Control"] = "no-store, max-age=0"
        return resp
    if request.method != "POST":
        return jr({"error": "Use POST"}, 405)
    try:
        ctx = auth.context_from_request(request)
    except auth.AuthError:
        return jr({"error": "Please log in again."}, 401)
    if not ctx.session_valid():
        return jr({"error": "Please log in again."}, 401)
    try:
        data = body_json(request)
        bill_id = int(data.get("bill_id"))
        if bill_id <= 0:
            raise ValueError
    except (ValueError, TypeError, ApiError):
        return jr({"error": "bill_id is required"}, 400)
    try:
        bill = Bill.objects.select_related("load").filter(pk=bill_id).first()
        if bill is None:
            return jr({"error": "Bill not found"}, 404)
        if str(bill.load.driver_id) != str(ctx.uid) and ctx.role not in ("hq", "warehouse"):
            return jr({"error": "This bill is not yours."}, 403)
        if bill.status == "draft":
            return jr({"error": "Lock the bill before making the PDF."}, 400)
        d = bill_data(bill)
        if not d["items"]:
            return jr({"error": "This bill has no items."}, 400)
        pdf = build_pdf(d)
        folder = settings.MEDIA_ROOT / "bills"
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{bill.bill_no}.tmp"
        tmp.write_bytes(pdf)
        tmp.replace(folder / f"{bill.bill_no}.pdf")          # replaced in one step, so a customer never gets half a file
        Bill.objects.filter(pk=bill.pk).update(pdf_path=f"{bill.bill_no}.pdf")
        return jr({"url": f"{settings.PUBLIC_BASE_URL}/functions/v1/bill-pdf?t={bill.share_token}", "bill_no": bill.bill_no,
                   "status": bill.status, "bytes": len(pdf)})
    except Exception:
        log.exception("bill-pdf failed")
        return jr({"error": "Could not make the PDF bill. Try again."}, 500)


# ---------------------------------------------------------------------------------------------- creating logins (HQ)
def hq_logins(request):
    import re
    if request.method != "POST":
        return jr({"error": "Use POST"}, 405)
    try:
        ctx = auth.context_from_request(request)
    except auth.AuthError:
        return jr({"error": "Please log in again."}, 401)
    if ctx.role != "hq":
        return jr({"error": "Only HQ can create logins."}, 403)
    try:
        body = body_json(request)
    except ApiError:
        return jr({"error": "Something went wrong. Try again."}, 400)
    action = body.get("action", "create")
    clean = lambda v, mx=80: re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:mx]
    try:
        if action == "reset_password":
            target = str(body.get("user_id", ""))
            if not UUID_RE.match(target):
                return jr({"error": "Choose a person."}, 400)
            prof = Profile.objects.filter(pk=target).first()
            if prof is None:
                return jr({"error": "Person not found."}, 404)
            if prof.role == "hq":
                return jr({"error": "HQ passwords cannot be reset from here."}, 403)
            user = User.objects.get(pk=target)
            password, generated = str(body.get("password") or ""), False
            if password == "":
                password, generated = auth.new_password(), True
            elif len(password) < 8 or len(password) > 72:
                return jr({"error": "A password must be 8 to 72 characters."}, 400)
            with transaction.atomic():
                user.set_password(password)
                user.save(update_fields=["password"])
                hq_service.end_sessions(user.pk)           # the old password may be in someone else's hands
                HqAudit.objects.create(by_id=ctx.uid, action="password_reset", ref=prof.full_name,
                                       detail={"role": prof.role, "set_by_hq": not generated}, franchise_id=prof.franchise_id)
            res = {"ok": True, "role": prof.role, "full_name": prof.full_name, "email": user.email}
            res.update({"password": password} if generated else {"password_set_by_hq": True})
            return jr({"results": [res]})
        if action != "create":
            return jr({"error": "Unknown action."}, 400)
        try:
            fid = int(body.get("franchise_id"))
        except (TypeError, ValueError):
            fid = 0
        people = body.get("people") if isinstance(body.get("people"), list) else []
        if fid <= 0:
            return jr({"error": "Choose the franchise."}, 400)
        if not 1 <= len(people) <= 10:
            return jr({"error": "Send between 1 and 10 people."}, 400)
        fr = Franchise.objects.filter(pk=fid).first()
        if fr is None or not fr.active:
            return jr({"error": "That franchise is not active."}, 400)
        email_re = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
        results = []
        for p in people:
            role, full_name, email = clean(p.get("role"), 20), clean(p.get("full_name")), clean(p.get("email"), 120).lower()
            row = {"role": role, "full_name": full_name, "email": email}
            if role not in ("driver", "warehouse", "supervisor"):
                results.append({**row, "ok": False, "error": "Role must be collector, warehouse manager or supervisor."}); continue
            if not full_name:
                results.append({**row, "ok": False, "error": "Enter the name."}); continue
            if not email_re.match(email):
                results.append({**row, "ok": False, "error": "Enter a valid email address."}); continue
            password, generated = str(p.get("password") or ""), False
            if password == "":
                password, generated = auth.new_password(), True
            elif len(password) < 8 or len(password) > 72:
                results.append({**row, "ok": False, "error": "A password must be 8 to 72 characters."}); continue
            if User.objects.filter(email=email).exists():
                results.append({**row, "ok": False, "error": "A login with this email already exists. Use a different email."}); continue
            try:
                with transaction.atomic():                 # the login and the profile are made together or not at all
                    User.objects.create_user(email, password)
                    hq_service.hq_add_person(ctx, p_email=email, p_full_name=full_name, p_role=role, p_franchise=fid,
                                             p_phone=clean(p.get("phone"), 20) or None, p_territory=clean(p.get("territory"), 60) or None,
                                             p_vehicle_no=(clean(p.get("vehicle_no"), 20) or None) if role == "driver" else None)
            except ApiError as e:
                results.append({**row, "ok": False, "error": e.message}); continue
            results.append({**row, "ok": True, **({"password": password} if generated else {"password_set_by_hq": True})})
        return jr({"franchise": {"id": fr.pk, "code": fr.code, "name": fr.name}, "results": results})
    except Exception:
        log.exception("hq-logins failed")
        return jr({"error": "Something went wrong. Try again."}, 500)
