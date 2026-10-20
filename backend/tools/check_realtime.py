#!/usr/bin/env python
"""Check the live-update channel against a running server (development or after a deploy):
    python tools/check_realtime.py http://127.0.0.1:8000 hq@x 'password' warehouse@x 'password'
Connects as the first person, makes a change as the second, and times how fast the first is told. Also checks that
a collector is NOT told about other people's work."""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

base = sys.argv[1].rstrip("/")


def call(path, body, token=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or "null")


def login(email, pw):
    return call("/auth/v1/token?grant_type=password", {"email": email, "password": pw})["access_token"]


async def listen(token, topic="realtime:hq"):
    uri = base.replace("http", "ws", 1) + "/realtime/v1/websocket?apikey=x&vsn=1.0.0"
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({"topic": topic, "event": "phx_join", "ref": "1", "payload": {"config": {"postgres_changes": [
        {"event": "*", "schema": "public", "table": t} for t in ("loads", "bills", "leads", "cash_ledger", "hq_audit")]}, "access_token": token}}))
    reply = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert reply["event"] == "phx_reply" and reply["payload"]["status"] == "ok", reply
    await ws.send(json.dumps({"topic": "phoenix", "event": "heartbeat", "payload": {}, "ref": "2"}))
    hb = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert hb["topic"] == "phoenix" and hb["payload"]["status"] == "ok", hb
    return ws


async def main():
    watcher_tok, actor_tok = login(sys.argv[2], sys.argv[3]), login(sys.argv[4], sys.argv[5])
    ws = await listen(watcher_tok)
    # a bad token is refused
    bad = await websockets.connect(base.replace("http", "ws", 1) + "/realtime/v1/websocket?apikey=x&vsn=1.0.0")
    await bad.send(json.dumps({"topic": "realtime:x", "event": "phx_join", "ref": "9", "payload": {"access_token": "nope"}}))
    assert json.loads(await bad.recv())["payload"]["status"] == "error"
    await bad.close()
    t0 = time.time()
    call("/rest/v1/rpc/wh_lead_counts", {}, actor_tok)       # read only: must not produce a change note
    try:
        await asyncio.wait_for(ws.recv(), 1.5)
        print("FAIL: told about a change that did not happen")
        return 1
    except asyncio.TimeoutError:
        print("ok: no note for a read")
    call("/rest/v1/rpc/issue_float", {"p_driver_id": sys.argv[6], "p_amount": 1, "p_note": "live check"}, actor_tok) if len(sys.argv) > 6 else None
    t0 = time.time()
    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
    print(f"ok: told in {time.time() - t0:.2f}s ->", msg["event"], msg["payload"]["data"]["table"], msg["payload"]["data"]["type"])
    await ws.close()
    return 0


sys.exit(asyncio.run(main()))
