#!/usr/bin/env python
"""DEVELOPMENT: log in as someone and call one action, to watch other open pages update live.
    python tools/poke.py http://127.0.0.1:8000 supervisor@scrappy.test 'Scrappy#2026' wh_lead_counts '{}'"""
import json
import sys
import urllib.request

base, email, pw, fn, args = sys.argv[1:6]


def call(path, body, token=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or "null")


tok = call("/auth/v1/token?grant_type=password", {"email": email, "password": pw})["access_token"]
print(json.dumps(call("/rest/v1/rpc/" + fn, json.loads(args), tok), indent=1))
