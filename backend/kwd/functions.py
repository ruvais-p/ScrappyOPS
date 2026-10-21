"""The two server helpers the staff app used: Head Office managing logins, and turning a Google Maps link into coordinates."""
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

from psycopg.types.json import Jsonb

from core.models import User
from core.services.common import ApiError, fetch, fetch_one
from kwd.scope import HO

ROLES = ("tso", "zonal_manager", "head_office", "franchisee")


# ---------------------------------------------------------------------------------------------- admin-users
def _apply_profile(uid, p):
    """Keep the person's profile, districts and (for a franchisee) business record in step with what Head Office entered."""
    if p.get("role") is not None and p["role"] not in ROLES:
        raise ApiError("Unknown role")
    patch = {k: p[k] for k in ("full_name", "phone", "role", "is_active") if k in p}
    if "manager_id" in p or p.get("role") == "franchisee":
        patch["manager_id"] = (p.get("manager_id") or None) if p.get("role") in ("tso", None) else None
    if patch:
        sets = ", ".join(f"{k} = %({k})s" for k in patch)
        fetch(f"update kwd_profiles set {sets} where id = %(id)s returning 1", {**patch, "id": uid})
    if isinstance(p.get("district_ids"), list):
        fetch("delete from kwd_user_districts where user_id = %(u)s returning 1", {"u": uid})
        for d in p["district_ids"]:
            fetch("insert into kwd_user_districts (user_id, district_id) values (%(u)s, %(d)s) returning 1", {"u": uid, "d": int(d)})
    if p.get("role") == "franchisee" or p.get("franchise"):
        fr = p.get("franchise") or {}
        row = {k: (None if fr[k] == "" else fr[k]) for k in ("business_name", "district_id", "territory", "address", "gstin") if k in fr}
        if "is_active" in p:
            row["is_active"] = p["is_active"]
        existing = fetch_one("select id from kwd_fr_franchises where user_id = %(u)s", {"u": uid})
        if existing:
            if row:
                sets = ", ".join(f"{k} = %({k})s" for k in row)
                fetch(f"update kwd_fr_franchises set {sets} where user_id = %(u)s returning 1", {**row, "u": uid})
        else:
            if not row.get("business_name"):
                raise ApiError("Business name is needed for a franchisee")
            cols = ["user_id"] + list(row)
            fetch(f"insert into kwd_fr_franchises ({', '.join(cols)}) values ({', '.join('%(' + c + ')s' for c in cols)}) returning 1", {**row, "user_id": uid})
    if "is_active" in p:
        # a deactivated person cannot keep using an old login
        User.objects.filter(pk=uid).update(is_active=bool(p["is_active"]))
        if not p["is_active"]:
            from core.models import AuthSession
            AuthSession.objects.filter(user_id=uid).delete()


def _log(ctx, row_id, what, body):
    shown = {**body, **({"password": "***"} if body.get("password") else {})}
    fetch_one("insert into kwd_audit_log (table_name, row_id, action, new_data, actor) values ('staff_admin', %(r)s, %(a)s, %(n)s, %(u)s) returning id",
              {"r": row_id, "a": what, "n": Jsonb(shown), "u": ctx.uid})


def admin_users(ctx, body):
    """Create a login, update a person, or reset a password. Only active Head Office may call it."""
    if ctx.role != HO:
        raise ApiError("Only Head Office can manage staff", status=403)
    action = body.get("action")
    if action == "create":
        email, password, name = str(body.get("email") or "").strip().lower(), body.get("password") or "", (body.get("full_name") or "").strip()
        if not email or len(password) < 8:
            raise ApiError("Email and a password of at least 8 characters are needed")
        if not name:
            raise ApiError("Full name is needed")
        prof = body.get("profile") or {}
        if prof.get("role") == "franchisee" and not ((prof.get("franchise") or {}).get("business_name") or "").strip():
            raise ApiError("Business name is needed for a franchisee")
        if User.objects.filter(email=email).exists():
            raise ApiError("A login with this email already exists")
        user = User.objects.create_user(email, password)
        fetch("insert into kwd_profiles (id, full_name, email, phone, is_active) values (%(i)s, %(n)s, %(e)s, null, false) returning 1",
              {"i": user.pk, "n": name, "e": email})
        _apply_profile(user.pk, {**prof, "full_name": name, "is_active": True})
        _log(ctx, user.pk, "CREATE_LOGIN", body)
        return {"id": str(user.pk)}
    if action == "update":
        if not body.get("id"):
            raise ApiError("Missing id")
        prof = body.get("profile") or {}
        if str(body["id"]) == str(ctx.uid) and (prof.get("is_active") is False or (prof.get("role") and prof["role"] != "head_office")):
            raise ApiError("You cannot deactivate or demote your own login")
        _apply_profile(UUID(str(body["id"])), prof)
        _log(ctx, body["id"], "UPDATE_STAFF", body)
        return {"ok": True}
    if action == "reset_password":
        if not body.get("id") or len(body.get("password") or "") < 8:
            raise ApiError("A password of at least 8 characters is needed")
        u = User.objects.filter(pk=body["id"]).first()
        if not u:
            raise ApiError("User not found")
        u.set_password(body["password"])
        u.save(update_fields=["password"])
        from core.models import AuthSession
        AuthSession.objects.filter(user_id=u.pk).delete()     # the old password may be in someone else's hands
        _log(ctx, body["id"], "RESET_PASSWORD", body)
        return {"ok": True}
    raise ApiError("Unknown action")


# ---------------------------------------------------------------------------------------------- resolve-map-link
ALLOWED_HOSTS = {"maps.app.goo.gl", "goo.gl", "google.com", "www.google.com", "maps.google.com", "consent.google.com"}
PATTERNS = [
    re.compile(r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)"),
    re.compile(r"[?&](?:q|query|ll|destination|daddr)=(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)"),
    re.compile(r"/search/(-?\d{1,2}\.\d+)\s*,\s*\+?(-?\d{1,3}\.\d+)"),
    re.compile(r"/place/(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)"),
    re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),
]
A = "23456789CFGHJMPQRVWX"
RES = [20, 1, 0.05, 0.0025, 0.000125]
PLUS = re.compile(r"(?:^|[\s,=+])([23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{0,7})(?=$|[\s,&+])", re.I)


def _allowed(u):
    try:
        return (u.scheme == "https" and u.hostname in ALLOWED_HOSTS and
                u.username is None and u.password is None and u.port in (None, 443))
    except ValueError:
        return False


def _decode_safe(t):
    try:
        return urllib.parse.unquote(t.replace("+", " "), errors="strict")
    except Exception:
        return t


def _from_coords(text):
    s = _decode_safe(text)
    for p in PATTERNS:
        m = p.search(s)
        if m:
            return {"lat": float(m.group(1)), "lng": float(m.group(2))}
    return None


def _olc_encode(lat, lng):
    la = min(max(lat, -90), 89.9999999) + 90
    ln = ((lng + 180) % 360 + 360) % 360
    code = ""
    for r in RES:
        dl, dg = math.floor(la / r), math.floor(ln / r)
        la -= dl * r
        ln -= dg * r
        code += A[dl] + A[dg]
    return code[:8] + "+" + code[8:]


def _olc_decode(code):
    c = code.replace("+", "").upper()
    lat, lng, lat_r, lng_r = -90.0, -180.0, 0.0, 0.0
    for i in range(0, min(10, len(c)), 2):
        r = RES[i // 2]
        lat += A.index(c[i]) * r
        lng += A.index(c[i + 1]) * r
        lat_r = lng_r = r
    for i in range(10, len(c)):
        d = A.index(c[i])
        lat_r /= 5
        lng_r /= 4
        lat += (d // 4) * lat_r
        lng += (d % 4) * lng_r
    return {"lat": lat + lat_r / 2, "lng": lng + lng_r / 2}


def _olc_recover(short, ref):
    sep = short.index("+")
    pad = 8 - sep
    if pad <= 0:
        return _olc_decode(short)
    res = 20 ** (2 - pad / 2)
    half = res / 2
    c = _olc_decode(_olc_encode(ref["lat"], ref["lng"])[:pad] + short.upper())
    if ref["lat"] + half < c["lat"] and c["lat"] - res >= -90:
        c["lat"] -= res
    elif ref["lat"] - half > c["lat"] and c["lat"] + res <= 90:
        c["lat"] += res
    if ref["lng"] + half < c["lng"]:
        c["lng"] -= res
    elif ref["lng"] - half > c["lng"]:
        c["lng"] += res
    return c


def _from_plus(text, ref):
    try:
        raw = urllib.parse.unquote(text, errors="strict")
    except Exception:
        raw = text
    m = PLUS.search(raw)
    if not m:
        return None
    code = m.group(1).upper()
    short = code.index("+") < 8
    if short and not ref:
        return None
    p = _olc_recover(code, ref) if short else _olc_decode(code)
    return {"lat": round(p["lat"], 6), "lng": round(p["lng"], 6), "plusCode": code}


def _find(text, ref):
    return _from_coords(text) or _from_plus(text, ref)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def resolve_map_link(body):
    """Google Maps link (also short links) or Plus Code -> {lat, lng}. Only Google hosts are ever fetched, and only addresses
    are read, never the page."""
    link = str(body.get("url") or "").strip()
    ref = None
    r = body.get("ref")
    if isinstance(r, dict):
        try:
            ref = {"lat": float(r["lat"]), "lng": float(r["lng"])}
        except Exception:
            ref = None
    if not re.match(r"^https?:", link, re.I):
        p = _from_plus(link, ref)
        if p:
            return p
        raise ApiError('Paste a Google Maps link, a Plus Code or "lat, lng".')
    try:
        url = urllib.parse.urlparse(link)
    except Exception:
        raise ApiError("That is not a web link.")
    if not _allowed(url):
        raise ApiError("Only Google Maps links are supported.")
    direct = _find(link, ref)
    if direct:
        return direct
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        cur = link
        for _ in range(6):
            req = urllib.request.Request(cur, headers={"User-Agent": "Mozilla/5.0 (ScrappyField link resolver)", "Accept-Language": "en"})
            try:
                opener.open(req, timeout=6).close()
                break
            except urllib.error.HTTPError as e:
                loc = e.headers.get("Location")
                if not (300 <= e.code < 400 and loc):
                    break
                nxt = urllib.parse.urljoin(cur, loc)
                q = urllib.parse.parse_qs(urllib.parse.urlparse(nxt).query)
                target = q["continue"][0] if q.get("continue") else nxt
                if not _allowed(urllib.parse.urlparse(target)):
                    raise ApiError("That link does not lead to Google Maps.")
                found = _find(target, ref)
                if found:
                    return found
                cur = target
        raise ApiError("No exact location in that link. In Google Maps, long-press the pin and copy the numbers shown (like 11.19, 76.23).", status=422)
    except ApiError:
        raise
    except Exception:
        raise ApiError("Could not open that link right now. Try again, or paste \"lat, lng\".", status=502)
