"""One front door for every dashboard. A person logs in once (/login/); their role picks the dashboard; this middleware keeps
people out of dashboards that are not theirs.

How it works
  - Logging in sets a signed, http-only cookie that names the login session. Pages are plain files, so the browser has no
    token to show when it asks for a page; the cookie is what lets the server decide who is asking.
  - The cookie is only trusted while the login session still exists. Logging in on another device (newest login wins) or
    signing out ends it, so a stale cookie never opens a dashboard.
  - The data calls (/rest, /kwd/api ...) are NOT guarded here: they carry their own login token and are checked by the
    code that serves them.

Role -> dashboard
  driver                                 -> /collector/
  warehouse, supervisor                  -> /warehouse/
  hq                                     -> /hq/
  super_admin                            -> /super-admin/
  tso, zonal_manager, head_office, franchisee (Scrappy Field, the staff app) -> /kwd/
"""
import time

from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect
from django.utils import timezone

from core.models import AuthSession, Profile
from core.services.common import fetch_one

COOKIE = "scrappy_gate"
HOP = "scrappy_hop"           # set for a few seconds when we send someone to a dashboard; breaks redirect loops
SALT = "portal.gate"

SCRAP_ROLES = {"driver": "collector", "warehouse": "warehouse", "supervisor": "warehouse", "hq": "hq",
               "super_admin": "super_admin"}
KWD_ROLES = {"tso", "zonal_manager", "head_office", "franchisee"}
DASH_PATH = {"collector": "/collector/", "warehouse": "/warehouse/", "hq": "/hq/", "kwd": "/kwd/",
             "super_admin": "/super-admin/"}
# where each dashboard keeps its login in the browser (the pages read these)
STORAGE_KEY = {"collector": "scrappy_session", "warehouse": "scrappy_wh_session", "hq": "scrappy_hq_session",
               "kwd": "scrappy_kwd_session", "super_admin": "scrappy_super_admin_session"}


def destination(user_id):
    """The dashboard this login belongs to ('collector', 'warehouse', 'hq' or 'kwd'), or None when the login has no role."""
    profile = Profile.objects.filter(pk=user_id, active=True).values("role", "is_super_admin").first()
    role = profile["role"] if profile else None
    if role == "super_admin" and not profile["is_super_admin"]:
        return None
    if role in SCRAP_ROLES:
        return SCRAP_ROLES[role]
    row = fetch_one("select role from kwd_profiles where id = %(u)s and is_active", {"u": user_id})
    if row and row["role"] in KWD_ROLES:
        return "kwd"
    return None


def dashboard_of(path):
    """Which dashboard a page address belongs to, or None for public addresses."""
    for name, prefix in DASH_PATH.items():
        if path == prefix.rstrip("/") or path.startswith(prefix):
            if name == "kwd" and path.startswith("/kwd/api/"):
                return None                       # data calls guard themselves
            return name
    return None


# ------------------------------------------------------------------------------------------------ the cookie
def set_login_cookie(response, user_id, session_id):
    value = signing.dumps({"u": str(user_id), "s": str(session_id)}, salt=SALT, compress=False)
    response.set_cookie(COOKIE, value, max_age=settings.REFRESH_TOKEN_DAYS * 86400, httponly=True, samesite="Lax",
                        secure=not settings.DEBUG, path="/")


def clear_login_cookie(response):
    response.delete_cookie(COOKIE, path="/", samesite="Lax")


def read_login(request):
    """(user_id, session_id) from the cookie when it is genuine and its login session is still open, else None."""
    if hasattr(request, "_portal_login"):
        return request._portal_login
    found = None
    raw = request.COOKIES.get(COOKIE)
    if raw:
        try:
            data = signing.loads(raw, salt=SALT, max_age=settings.REFRESH_TOKEN_DAYS * 86400)
            if AuthSession.objects.filter(pk=data["s"], user_id=data["u"], expires_at__gt=timezone.now()).exists():
                found = (data["u"], data["s"])
        except (signing.BadSignature, KeyError, ValueError):
            found = None
    request._portal_login = found
    return found


def current_destination(request):
    login = read_login(request)
    return destination(login[0]) if login else None


def end_session_of_cookie(request):
    """Sign out the login session named by the cookie (used by /logout/)."""
    raw = request.COOKIES.get(COOKIE)
    if not raw:
        return
    try:
        data = signing.loads(raw, salt=SALT)
        AuthSession.objects.filter(pk=data["s"], user_id=data["u"]).delete()
    except (signing.BadSignature, KeyError, ValueError):
        pass


def send_to(dest, with_hop=True):
    resp = HttpResponseRedirect(DASH_PATH[dest])
    resp["Cache-Control"] = "no-store"
    if with_hop:
        resp.set_cookie(HOP, "1", max_age=10, httponly=True, samesite="Lax", path="/")
    return resp


def to_login(request, clear=False, keep_query=True):
    qs = request.META.get("QUERY_STRING", "")
    resp = HttpResponseRedirect("/login/" + ("?" + qs if qs and keep_query else ""))
    resp["Cache-Control"] = "no-store"
    if clear:
        clear_login_cookie(resp)
    return resp


# ------------------------------------------------------------------------------------------------ the middleware
class PortalGate:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ("GET", "HEAD"):
            redirect = self.check(request)
            if redirect is not None:
                return redirect
        return self.get_response(request)

    def check(self, request):
        path = request.path
        if path in ("/", "/index.html"):
            dest = current_destination(request)
            if dest and "m" not in request.GET and not request.COOKIES.get(HOP):
                return send_to(dest)
            # not signed in, or a dashboard just sent them back (its own login ended): start again at the login page
            return to_login(request, clear=bool(request.COOKIES.get(COOKIE)))
        dash = dashboard_of(path)
        if dash is None:
            return None
        login = read_login(request)
        if login is None:
            return to_login(request, clear=bool(request.COOKIES.get(COOKIE)), keep_query=False)
        dest = destination(login[0])
        if dest is None:
            return to_login(request, clear=True, keep_query=False)
        if dest != dash:
            return send_to(dest)
        return None
