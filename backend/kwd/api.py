"""HTTP side of the staff app: one data endpoint the pages post their queries to, the few named actions, photo storage, and the
two helpers (manage logins, resolve a map link). Logins are the same tokens as the rest of the system."""
import json
import logging

from django.db import DataError, IntegrityError, transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core import auth
from core.api.views import Encoder
from core.models import ImmutableError
from core.services.common import ApiError
from kwd import functions, storage
from kwd.engine import run_query
from kwd.rules import RULES, days, franchise
from kwd.scope import HO, KCtx, ZM

log = logging.getLogger("kwd.api")


def jr(data, status=200):
    r = HttpResponse(json.dumps(data, cls=Encoder, separators=(",", ":")), status=status, content_type="application/json")
    r["Cache-Control"] = "no-store"
    return r


def err(message, status=400, code="P0001", details=None, hint=None):
    return jr({"error": {"message": message, "code": code, "details": details, "hint": hint}}, status)


def caller(request):
    c = auth.context_from_request(request)
    return KCtx(c.uid, c.session_id)


def body_of(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        raise ApiError("The request body is not valid JSON.", code="PGRST102")


def guarded(view):
    """Common wrapper: sign-in check, one database transaction per request, and plain-language errors."""
    @csrf_exempt
    def wrapped(request, *a, **k):
        try:
            ctx = caller(request)
        except auth.AuthError as e:
            return err(e.body.get("message") or e.body.get("error_description") or "Please log in again.", e.status, str(e.body.get("code", "401")))
        try:
            if not ctx.session_valid():
                raise ApiError("You were logged out because this account was opened on another device.", code="PGRST301", status=401)
            with transaction.atomic():
                return view(request, ctx, *a, **k)
        except ApiError as e:
            return err(e.message, e.status, e.code, e.details, e.hint)
        except ImmutableError as e:
            return err(str(e))
        except IntegrityError as e:
            text = str(e)
            log.warning("kwd write refused by the database: %s", text)
            if "duplicate key" in text or "unique" in text.lower():
                name = text.split('"')[1] if '"' in text else "key"
                return err(f'duplicate key value violates unique constraint "{name}"', 409, "23505")
            return err("That change is not allowed. Check the values and try again.", 400, "23000")
        except DataError as e:
            log.warning("kwd bad value: %s", e)
            return err("One of the values is not valid.", 400, "22000")
        except Exception:
            log.exception("kwd request failed")
            return err("Something went wrong on the server. Try again.", 500, "XX000")
    return wrapped


@csrf_exempt
def session_status(request):
    """Is this login still the person's newest one? Polled by the page; never raises. valid is null when it cannot tell
    (for example the access token just expired), so the page does not sign anyone out by mistake."""
    try:
        c = auth.context_from_request(request, required=False)
    except auth.AuthError:
        return jr({"valid": None})
    if c is None:
        return jr({"valid": None})
    return jr({"valid": c.session_valid()})


@guarded
def query(request, ctx):
    if request.method != "POST":
        return err("Use POST", 405)
    return jr(run_query(ctx, body_of(request)))


ACTIONS = {
    "pay_month": lambda ctx, a: days.pay_month(ctx, a.get("p_tso"), a.get("p_month"), a.get("p_ref"), a.get("p_note")),
    "flag_day": lambda ctx, a: days.flag_day(ctx, a.get("p_day"), a.get("p_flag"), a.get("p_reason")),
    "fr_record_sale": lambda ctx, a: franchise.record_sale(ctx, **{k: v for k, v in a.items()}),
    "fr_cancel_sale": lambda ctx, a: franchise.cancel_sale(ctx, a.get("p_sale"), a.get("p_reason")),
}


@guarded
def rpc(request, ctx, fn):
    if request.method != "POST":
        return err("Use POST", 405)
    if fn not in ACTIONS:
        return err(f"Could not find the function public.{fn} in the schema cache", 404, "PGRST202")
    ctx.need_active()
    return jr({"data": ACTIONS[fn](ctx, body_of(request))})


@guarded
def function(request, ctx, name):
    if request.method != "POST":
        return err("Use POST", 405)
    ctx.need_active()
    body = body_of(request)
    if name == "admin-users":
        return jr(functions.admin_users(ctx, body))
    if name == "resolve-map-link":
        return jr(functions.resolve_map_link(body))
    return err("Unknown function", 404)


# ---------------------------------------------------------------------------------------------- photos
MAX_PHOTO = 8 * 1024 * 1024


@guarded
def storage_upload(request, ctx):
    """POST raw image bytes with ?path=<user id>/<file name>. A person can add files only under their own folder."""
    if request.method != "POST":
        return err("Use POST", 405)
    ctx.need_active()
    path = request.GET.get("path", "")
    if not storage.valid_name(path) or path.split("/")[0] != str(ctx.uid):
        raise ApiError('new row violates row-level security policy for table "objects"', status=403, code="42501")
    data = request.body
    if not data or len(data) > MAX_PHOTO:
        raise ApiError("The photo is empty or too large (limit 8 MB).")
    ctype = request.headers.get("Content-Type", "")
    if not ctype.startswith("image/"):
        raise ApiError("Only photos can be uploaded.")
    try:
        storage.save(path, data)
    except FileExistsError:
        raise ApiError("The resource already exists", status=409, code="Duplicate")
    return jr({"path": path})


@guarded
def storage_sign(request, ctx):
    if request.method != "POST":
        return err("Use POST", 405)
    ctx.need_active()
    b = body_of(request)
    path = b.get("path", "")
    if not storage.valid_name(path):
        raise ApiError("Object not found", status=404)
    if path.split("/")[0] != str(ctx.uid) and ctx.role not in (ZM, HO):
        raise ApiError("Object not found", status=404)
    if not storage.exists(path):
        raise ApiError("Object not found", status=404)
    seconds = min(int(b.get("expiresIn") or 3600), 86400 * 7)
    return jr({"signedUrl": f"/kwd/api/storage/object?token={storage.sign(path, seconds)}&e={seconds}"})


def storage_object(request):
    """The link a signed address points to. It works for the time it was made for, for whoever holds it."""
    try:
        seconds = min(int(request.GET.get("e", "3600")), 86400 * 7)
        path = storage.unsign(request.GET.get("token", ""), seconds)
    except Exception:
        raise Http404()
    if not storage.exists(path):
        raise Http404()
    import mimetypes
    resp = FileResponse(open(storage.file_of(path), "rb"), content_type=mimetypes.guess_type(path)[0] or "image/jpeg")
    resp["Cache-Control"] = "private, max-age=300"
    return resp
