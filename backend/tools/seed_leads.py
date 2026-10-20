#!/usr/bin/env python
"""DEVELOPMENT: add a few test leads through the same upload the HQ page uses.
    python tools/seed_leads.py http://127.0.0.1:8000 hq@scrappy.test 'Scrappy#2026' driver@scrappy.test"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

base, email, pw, driver = sys.argv[1:5]


def call(path, body=None, token=None, headers=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {}), **(headers or {})})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or "null")


tok = call("/auth/v1/token?grant_type=password", {"email": email, "password": pw})["access_token"]
today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%m-%Y")
rows = [
    {"customer_name": "Anil Kumar", "phone": "9000000001", "address": "12, Lake View Road", "area": "Kakkanad", "driver_email": driver, "pickup_date": today, "pickup_time": "10:00 AM", "items": "iron, paper", "latitude": "10.0159", "longitude": "76.3419"},
    {"customer_name": "Lakshmi Menon", "phone": "9000000002", "address": "Flat 4B, Sunrise Apartments", "area": "Edapally", "driver_email": driver, "pickup_date": today, "pickup_time": "11:30 AM", "items": "aluminium, plastic"},
    {"customer_name": "Safeek M", "phone": "9000000003", "address": "7, Market Road", "area": "Aluva", "driver_email": driver, "pickup_date": today, "pickup_time": "2:00 PM", "items": "iron"},
    {"customer_name": "Bindu Thomas", "phone": "9000000004", "address": "Villa 9, Palm Grove", "area": "Kakkanad", "franchise_code": "KKD", "pickup_date": today, "pickup_time": "4:00 PM", "items": "paper"},
    {"customer_name": "Rahul Nair", "phone": "9000000005", "address": "22, Temple Road", "area": "Thrippunithura", "franchise_code": "KKD", "pickup_date": today, "pickup_time": "5:30 PM", "items": "e-waste"},
]
out = call("/rest/v1/lead_import", rows, tok, {"Prefer": "return=representation"})
for r in out:
    print(r["status"], r["lead_code"], "-", r["message"])
