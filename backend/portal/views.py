"""The login page, the sign-out address, and the staff app's page."""
import json
import time

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from core import auth
from core.api.views import _client_ip
from portal import gate


def _json(data, status=200):
    r = JsonResponse(data, status=status)
    r["Cache-Control"] = "no-store"
    return r


def _session_for(dest, out):
    """What the dashboard expects to find in the browser after login."""
    expires_ms = int(time.time() * 1000) + int(out.get("expires_in") or 3600) * 1000
    if dest == "kwd":
        return {"access_token": out["access_token"], "refresh_token": out["refresh_token"], "expires_at": expires_ms, "user": out["user"]}
    return {"access_token": out["access_token"], "refresh_token": out["refresh_token"], "expires_at": expires_ms, "user_id": out["user"]["id"]}


@csrf_exempt
def login(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return _json({"error": "Send the email and password."}, 400)
        try:
            out = auth.login(data.get("email"), data.get("password"), _client_ip(request))
        except auth.AuthError as e:
            body = e.body
            text = body.get("error_description") or body.get("msg") or body.get("message") or "Login failed. Try again."
            if body.get("error_code") == "invalid_credentials" or "invalid login" in text.lower():
                text = "That email and password don’t match. Try again."
            return _json({"error": text}, e.status)
        uid = out["user"]["id"]
        sid = auth.decode_access_token(out["access_token"])["session_id"]
        dest = gate.destination(uid)
        if dest is None:                       # a login without a role opens nothing
            auth.logout_session(sid)
            return _json({"error": "This login is not set up yet. Ask Head Office."}, 403)
        resp = _json({"dest": dest, "redirect": gate.DASH_PATH[dest], "storage_key": gate.STORAGE_KEY[dest],
                      "all_storage_keys": list(gate.STORAGE_KEY.values()), "session": _session_for(dest, out)})
        gate.set_login_cookie(resp, uid, sid)
        resp.delete_cookie(gate.HOP, path="/")
        return resp

    # the page itself
    dest = gate.current_destination(request)
    if dest and "m" not in request.GET and not request.COOKIES.get(gate.HOP):
        return gate.send_to(dest)
    resp = render(request, "portal/login.html", {"message": request.GET.get("m", "")[:200]})
    resp["Cache-Control"] = "no-store"
    if request.COOKIES.get(gate.COOKIE) and (dest is None or "m" in request.GET or request.COOKIES.get(gate.HOP)):
        gate.clear_login_cookie(resp)           # the page that sent them here says they are logged out
    resp.delete_cookie(gate.HOP, path="/")
    return resp


@csrf_exempt
def logout(request):
    gate.end_session_of_cookie(request)
    if request.method == "POST":
        resp = HttpResponse(status=204)
    else:
        resp = gate.to_login(request, keep_query=True)
    gate.clear_login_cookie(resp)
    resp.delete_cookie(gate.HOP, path="/")
    return resp


def kwd_app(request):
    """The staff app (Scrappy Field). The gate has already checked that this person belongs here."""
    resp = render(request, "kwd/app.html")
    resp["Cache-Control"] = "no-cache"
    return resp
