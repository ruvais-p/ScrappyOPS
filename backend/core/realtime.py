"""Live updates for the dashboards, over a websocket at /realtime/v1/websocket (the address and message format the pages
already use). When something changes, open pages are told "loads changed" and refresh themselves.

How it works: the database sends a short note on every change (see migration 0003). Each server process listens for
those notes and passes them on to the pages connected to it, but only to people allowed to see that data:
  HQ: everything. Warehouse and supervisor: their franchise. Collector: only their own work.
No row data is ever sent, only the table name and the kind of change."""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone

import psycopg
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, connection
from django.utils import timezone as django_timezone
from psycopg.conninfo import make_conninfo

from core import auth
from core.models import AuthSession, Profile

log = logging.getLogger("scrappy.realtime")

# who may be told about which table
STAFF_TABLES = {"hq_requirements", "hq_releases", "hq_dispatches", "settlement_resolutions"}
HQ_ONLY_TABLES = {"hq_audit"}
HEARTBEAT_TIMEOUT = 90          # seconds of silence before a page is considered gone
IDENTITY_CHECK_SECONDS = 10     # revoked sessions and role changes stop live notifications promptly


def _identity(token):
    """(user id, role, franchise id, token expiry) for a valid login token, else None. Runs in a thread (database access)."""
    close_old_connections()
    try:
        claims = auth.decode_access_token(token)
    except auth.AuthError:
        return None
    sid, uid = claims.get("session_id"), claims["sub"]
    if not sid or not AuthSession.objects.filter(pk=sid, user_id=uid, user__is_active=True,
                                                 expires_at__gt=django_timezone.now()).exists():
        return None
    prof = Profile.objects.filter(pk=uid, active=True).first()
    if prof is None:
        return None
    return {"uid": str(uid), "role": prof.role, "franchise": prof.franchise_id, "exp": claims["exp"], "sid": sid}


class Client:
    def __init__(self, send):
        self.send = send
        self.queue = asyncio.Queue(maxsize=200)
        self.topics = {}           # topic -> set of table names asked for
        self.who = None
        self.token = None
        self.last_seen = time.time()
        self.ref = 0

    def sees(self, change):
        w = self.who
        if not w or w["exp"] + 60 < time.time():       # an old login stops receiving until the page sends a fresh token
            return False
        t, f, d = change["t"], change.get("f"), change.get("d")
        if w["role"] == "hq":
            return True
        if t in HQ_ONLY_TABLES:
            return False
        if w["role"] in ("warehouse", "supervisor"):
            return f is not None and f == w["franchise"]
        if w["role"] == "driver":
            return t not in STAFF_TABLES and d is not None and d == w["uid"]
        return False


class Hub:
    """Listens to the database's change notes in one background thread per server process (works on every operating system)
    and hands each note to the pages connected to this process."""

    def __init__(self):
        self.clients = set()
        self.thread = None
        self.loop = None
        self._lock = threading.Lock()

    def ensure_started(self):
        self.loop = asyncio.get_running_loop()
        with self._lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._listen, name="scrappy-change-listener", daemon=True)
                self.thread.start()

    def _listen(self):
        db = connection.settings_dict
        info = make_conninfo(dbname=db["NAME"], user=db["USER"] or None, password=db["PASSWORD"] or None,
                             host=db["HOST"] or None, port=db["PORT"] or None)
        while True:
            try:
                with psycopg.connect(info, autocommit=True) as conn:
                    conn.execute("listen scrappy_changes")
                    log.info("listening for changes")
                    while True:
                        for note in conn.notifies(timeout=25):
                            try:
                                change = json.loads(note.payload)
                            except ValueError:
                                continue
                            self.loop.call_soon_threadsafe(self.dispatch, change)
                        conn.execute("select 1")          # nothing for a while: make sure the connection is still alive
            except Exception as e:
                log.warning("change listener lost its connection (%s); retrying", e)
                time.sleep(2)

    def dispatch(self, change):
        for c in list(self.clients):
            if not c.sees(change):
                continue
            for topic, tables in c.topics.items():
                if tables and change["t"] not in tables:
                    continue
                msg = {"topic": topic, "event": "postgres_changes", "ref": None, "payload": {
                    "ids": [0], "data": {"schema": "public", "table": change["t"], "type": change["op"],
                                         "commit_timestamp": datetime.now(timezone.utc).isoformat(), "errors": None}}}
                try:
                    c.queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass                    # the page is behind; it also refreshes by itself every 15 seconds


hub = Hub()


def _origin_ok(scope):
    allowed = settings.CORS_ALLOWED_ORIGINS
    if "*" in allowed:
        return True
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    origin = headers.get("origin", "")
    if not origin:
        return True
    host = headers.get("host", "")
    return origin in allowed or origin.split("://", 1)[-1] == host


async def handle_websocket(scope, receive, send):
    first = await receive()
    if first["type"] != "websocket.connect":
        return
    if not _origin_ok(scope):
        await send({"type": "websocket.close", "code": 4403})
        return
    await send({"type": "websocket.accept"})
    hub.ensure_started()

    async def raw_send(obj):
        await send({"type": "websocket.send", "text": json.dumps(obj, separators=(",", ":"))})

    client = Client(raw_send)
    hub.clients.add(client)

    async def writer():
        while True:
            await raw_send(await client.queue.get())

    wtask = asyncio.get_running_loop().create_task(writer())

    async def recheck_identity():
        while True:
            await asyncio.sleep(IDENTITY_CHECK_SECONDS)
            token = client.token
            if not token:
                continue
            try:
                who = await sync_to_async(_identity)(token)
            except Exception:
                log.exception("Could not recheck websocket login")
                who = None
            # A token replacement may have arrived while the database check ran.
            if client.token == token:
                client.who = who
                if who is None:
                    return 4401

    vtask = asyncio.get_running_loop().create_task(recheck_identity())
    async def read_messages():
        while True:
            try:
                event = await asyncio.wait_for(receive(), timeout=HEARTBEAT_TIMEOUT)
            except asyncio.TimeoutError:
                break
            if event["type"] == "websocket.disconnect":
                break
            if event["type"] != "websocket.receive" or not event.get("text"):
                continue
            client.last_seen = time.time()
            try:
                m = json.loads(event["text"])
                topic, ev, payload, ref = m.get("topic"), m.get("event"), m.get("payload") or {}, m.get("ref")
            except (ValueError, AttributeError):
                continue
            reply = lambda status, response=None: raw_send({"topic": topic, "event": "phx_reply", "ref": ref,
                                                            "payload": {"status": status, "response": response or {}}})
            if not isinstance(topic, str) or not isinstance(payload, dict):
                continue
            if ev == "heartbeat":
                await reply("ok")
            elif ev == "phx_join":
                who = await sync_to_async(_identity)(payload.get("access_token", ""))
                if not who:
                    await reply("error", {"reason": "Please log in again."})
                    return 4401
                config = payload.get("config", {})
                changes = config.get("postgres_changes", []) if isinstance(config, dict) else None
                if not isinstance(changes, list) or not all(isinstance(c, dict) and isinstance(c.get("table"), str) for c in changes):
                    await reply("error", {"reason": "Invalid subscription"})
                    continue
                client.who = who
                client.token = payload["access_token"]
                wanted = {c.get("table") for c in changes if c.get("table")}
                client.topics[topic] = wanted
                await reply("ok", {"postgres_changes": [{"id": i, "event": "*", "schema": "public", "table": t} for i, t in enumerate(sorted(wanted))]})
            elif ev == "access_token":
                who = await sync_to_async(_identity)(payload.get("access_token", ""))
                if who:
                    client.who = who
                    client.token = payload["access_token"]
                else:
                    client.who = None
                    client.token = None
                    return 4401
            elif ev == "phx_leave":
                client.topics.pop(topic, None)
                await reply("ok")
    tasks = (wtask, vtask, asyncio.create_task(read_messages()))
    code = 1000
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            code = task.result() or code
    except OSError:
        pass  # Transport already disconnected.
    except Exception:
        code = 1011
        log.exception("websocket failed")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        client.topics.clear()
        hub.clients.discard(client)
        try:
            await send({"type": "websocket.close", "code": code})
        except Exception:
            pass
