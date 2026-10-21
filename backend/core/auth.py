"""Login. Same addresses and answers as the service this replaces, so the dashboards need no change:
  POST /auth/v1/token?grant_type=password        {email, password}
  POST /auth/v1/token?grant_type=refresh_token   {refresh_token}
  POST /auth/v1/logout?scope=local
  GET  /auth/v1/user

A login gives an access token (valid one hour) and a refresh token. Only the newest login of a person stays valid
(older devices are signed out); that rule can be switched off with SINGLE_SESSION=0."""
import hashlib
import secrets
import time
from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from core.models import AuthSession, User
from core.services.common import ApiError, Ctx


class AuthError(Exception):
    def __init__(self, body, status=400):
        super().__init__(body.get("error_description") or body.get("message"))
        self.body = body
        self.status = status


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _issuer():
    return settings.PUBLIC_BASE_URL + "/auth/v1"


def make_access_token(user, session):
    now = int(time.time())
    payload = {"iss": _issuer(), "sub": str(user.pk), "aud": "authenticated", "role": "authenticated", "email": user.email,
               "session_id": str(session.pk), "iat": now, "exp": now + settings.ACCESS_TOKEN_SECONDS}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _token_response(user, session, refresh_token):
    return {
        "access_token": make_access_token(user, session),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_SECONDS,
        "expires_at": int(time.time()) + settings.ACCESS_TOKEN_SECONDS,
        "refresh_token": refresh_token,
        "user": {"id": str(user.pk), "aud": "authenticated", "role": "authenticated", "email": user.email},
    }


def _bad_login():
    return AuthError({"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials",
                      "error": "invalid_grant", "error_description": "Invalid login credentials"}, 400)


def login(email, password, ip=""):
    email = (email or "").strip().lower()
    keys = (f"loginfail:account:{email[:254]}:{ip[:64]}", f"loginfail:ip:{ip[:64]}")
    try:
        locked = any(cache.get(key, 0) >= settings.LOGIN_MAX_FAILURES for key in keys)
    except Exception as exc:
        if not settings.DEBUG:
            raise AuthError({"code": 503, "error_code": "rate_limit_unavailable", "error": "temporarily_unavailable",
                             "msg": "Login is temporarily unavailable.", "error_description": "Login is temporarily unavailable."}, 503) from exc
        locked = False
    if locked:
        raise AuthError({"code": 429, "error_code": "over_request_rate_limit", "error": "too_many_requests",
                         "msg": "Too many attempts. Try again in a few minutes.",
                         "error_description": "Too many attempts. Try again in a few minutes."}, 429)
    user = User.objects.filter(email=email, is_active=True).first() if email and password else None
    # always do the password work, so a wrong email takes as long as a wrong password
    ok = check_password(password or "", user.password if user else make_password("x"))
    if not (user and ok):
        try:
            for key in keys:
                cache.add(key, 0, settings.LOGIN_LOCK_SECONDS)
                cache.incr(key)
        except Exception as exc:
            if not settings.DEBUG:
                raise AuthError({"code": 503, "error_code": "rate_limit_unavailable", "error": "temporarily_unavailable",
                                 "msg": "Login is temporarily unavailable.", "error_description": "Login is temporarily unavailable."}, 503) from exc
        raise _bad_login()
    try:
        cache.delete(keys[0])
    except Exception:
        pass
    with transaction.atomic():
        refresh = secrets.token_urlsafe(32)
        session = AuthSession.objects.create(user=user, refresh_hash=_hash(refresh),
                                             expires_at=timezone.now() + timedelta(days=settings.REFRESH_TOKEN_DAYS))
        if settings.SINGLE_SESSION:      # newest login wins: this person's other devices are signed out
            AuthSession.objects.filter(user=user).exclude(pk=session.pk).delete()
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
    return _token_response(user, session, refresh)


def refresh_login(refresh_token):
    bad = AuthError({"code": 400, "error": "invalid_grant", "error_description": "Invalid Refresh Token: Refresh Token Not Found",
                     "msg": "Invalid Refresh Token: Refresh Token Not Found"}, 400)
    if not refresh_token:
        raise bad
    h = _hash(refresh_token)
    now = time.time()
    with transaction.atomic():
        s = AuthSession.objects.select_for_update().select_related("user").filter(refresh_hash=h).first()
        if s is None:
            # a token that was replaced a moment ago still works (two pages refreshing at the same time)
            cutoff = timezone.now() - timedelta(seconds=settings.REFRESH_REUSE_SECONDS * 2)
            for c in AuthSession.objects.select_for_update().select_related("user").filter(refreshed_at__gte=cutoff):
                if any(r[0] == h and now - r[1] <= settings.REFRESH_REUSE_SECONDS for r in c.recent):
                    s = c
                    break
        if s is None or s.expires_at < timezone.now() or not s.user.is_active:
            raise bad
        new = secrets.token_urlsafe(32)
        recent = [r for r in s.recent if now - r[1] <= settings.REFRESH_REUSE_SECONDS]
        recent.append([s.refresh_hash, now])
        s.recent = recent[-5:]
        s.refresh_hash = _hash(new)
        s.refreshed_at = timezone.now()
        s.expires_at = timezone.now() + timedelta(days=settings.REFRESH_TOKEN_DAYS)
        s.save(update_fields=["recent", "refresh_hash", "refreshed_at", "expires_at"])
        return _token_response(s.user, s, new)


def logout_session(session_id):
    AuthSession.objects.filter(pk=session_id).delete()


def decode_access_token(token):
    """Returns the claims, or raises AuthError(401)."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"], audience="authenticated",
                          options={"require": ["exp", "sub"]}, leeway=5)
    except jwt.ExpiredSignatureError:
        raise AuthError({"code": "PGRST303", "message": "JWT expired", "hint": None, "details": None}, 401)
    except jwt.PyJWTError:
        raise AuthError({"code": "PGRST301", "message": "Invalid JWT", "hint": None, "details": None}, 401)


def context_from_request(request, required=True):
    """The caller of this request (a Ctx), or None when there is no login and none is required."""
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if token.count(".") != 2:           # not a login token (for example the public key the page sends before login)
        if required:
            raise AuthError({"code": "PGRST301", "message": "Please log in again.", "hint": None, "details": None}, 401)
        return None
    claims = decode_access_token(token)
    return Ctx(claims["sub"], claims.get("session_id"))


def new_password():
    """A readable password (no look-alike characters): XXXX-XXXX-XXXX."""
    alpha = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    chars = "".join(secrets.choice(alpha) for _ in range(12))
    return f"{chars[:4]}-{chars[4:8]}-{chars[8:]}"
