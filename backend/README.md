# Scrappy backend (Django)

This is the server for the Scrappy App. It replaces the Supabase project. The three dashboards (collector, warehouse, HQ) and
the login page are **the same files as before**; only the address they talk to changes.

* Same login addresses, same data calls, same answers as Supabase, so **no screen was redesigned or rewritten**.
* Every rule that lived in Supabase's database functions is now Python in `core/services/`, with the same checks and the same
  messages ("Not enough cash in hand", "The person who counted the cash cannot verify it", and so on).
* The invoice PDF and the WhatsApp text are made by this server.
* Live updates (the green **LIVE** dot) work through a websocket that this server provides.

Tested on PostgreSQL 16 / Python 3.12 / Django 5.2: **48 automated tests pass** (login rules, the full pickup day, weighing,
stock, cash counting, franchise isolation, uploads, reports, PDF, concurrency), and the real dashboards were run against it
in a browser (login, a complete pickup to payment, PDF bill, warehouse and HQ screens, live updates).

---

## 1. What is where

```
scrappy_backend/
  scrappy/            settings, URLs, ASGI entry (also serves the live-update websocket)
  core/
    models.py         every table (same names and columns as the old database)
    migrations/       0001 tables · 0002 reporting views, running numbers, tamper guards · 0003 live-update notes
    auth.py           login, refresh, logout, "newest login wins", rate limit
    api/              views.py (HTTP), rest.py (table reads, per-role), frontend.py (optional: serve the website)
    realtime.py       live updates websocket
    services/
      pickup.py       collector: start, weigh, send, WhatsApp text, agree, pay, could-not-complete, end route
      warehouse.py    weighing + tolerance, stock, HQ requirements, releases, float, cash count, verify, leads assign/split, reports
      hq.py           HQ reports, franchises, people, rates, materials, lead moves, dispute decisions
      lead_import.py  HQ Excel upload checks (phone, date, time, location, driver, franchise, duplicates)
      invoice.py      the branded A4 bill (ReportLab)
    management/commands/  create_hq, seed_defaults, seed_demo, import_from_supabase, regenerate_pdfs
    tests/            the automated tests
  tools/              point_frontend.py (switch the website to this server), seed_leads.py, poke.py, check_realtime.py
  deploy/             entrypoint.sh, Caddyfile (HTTPS), backup.sh
  Dockerfile · docker-compose.yml · .env.example · requirements.txt
```

## 2. How the old addresses map to this server

| The pages call | Now answered by |
|---|---|
| `POST /auth/v1/token?grant_type=password` and `refresh_token` | `core/auth.py` |
| `POST /auth/v1/logout?scope=local`, `GET /auth/v1/user` | `core/api/views.py` |
| `POST /rest/v1/rpc/<action>` (51 actions) | `core/services/*` (registered by name) |
| `GET /rest/v1/<table or view>?select=…&col=eq.…&order=…&limit=…` (19 tables) | `core/api/rest.py` |
| `POST /rest/v1/lead_import` (HQ upload) | `core/services/lead_import.py` |
| `POST/GET /functions/v1/bill-pdf` (make the bill, customer link) | `views.bill_pdf` + `services/invoice.py` |
| `POST /functions/v1/hq-logins` (create logins, reset passwords) | `views.hq_logins` |
| `wss /realtime/v1/websocket` (live updates) | `core/realtime.py` |

A page can read **only** the 19 listed tables/views and **only** the listed columns, and each role sees only its rows
(collector: own work; warehouse and supervisor: own franchise; HQ: all). Tables cannot be written to directly; every change
goes through a named action that checks the caller's role. Internal helpers (`hq_log`, …) are not reachable.

## 3. Roles (unchanged)

`driver` (collector) · `warehouse` (warehouse manager) · `supervisor` · `hq`. Stock is released to HQ by the **supervisor**
(or HQ). Each non-HQ person belongs to exactly one franchise and cannot touch another franchise's data. The full permission
table is in `SCRAPPY_APP_DEVELOPER_HANDOVER.md`.

## 4. Run it on your computer (development)

Needs Python 3.12 and PostgreSQL 14+.

```bash
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
createdb scrappy                                           # or any PostgreSQL database
export DJANGO_DEBUG=1 DATABASE_URL=postgresql://postgres@localhost:5432/scrappy
python manage.py migrate
python manage.py seed_demo                                 # demo logins for every role, password Scrappy#2026 (development only)
python tools/point_frontend.py ../scrappy_app ./site       # website files that call this server
export FRONTEND_DIR=$PWD/site PUBLIC_BASE_URL=http://127.0.0.1:8000
uvicorn scrappy.asgi:application --port 8000               # open http://127.0.0.1:8000
```

Run the tests: `python manage.py test core --settings=scrappy.settings_test` (the test settings use a fast password method; never use them live).

## 5. Go live (Docker, one machine)

1. A Linux machine (2 GB RAM is plenty to start) with Docker, and a domain name pointing at it (for example `api.scrappy.in`).
2. Copy this folder to the machine. `cp .env.example .env`, then fill in `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`,
   `DJANGO_ALLOWED_HOSTS`, `PUBLIC_BASE_URL=https://api.scrappy.in`, and add `SITE_ADDRESS=api.scrappy.in`.
3. Make the website files: `python tools/point_frontend.py /path/to/scrappy_app ./site` (no `--api`: the pages and the data
   share one address). Set `FRONTEND_DIR=/srv/site` in `.env`.
   *Prefer to keep the website on Cloudflare?* Run `python tools/point_frontend.py /path/to/scrappy_app ./out --api https://api.scrappy.in`,
   upload `./out` to Cloudflare, and set `CORS_ALLOWED_ORIGINS=https://your-site-address` in `.env`.
4. `docker compose up -d --build`. HTTPS certificates are fetched and renewed automatically.
5. Create the first HQ login: `docker compose exec web python manage.py create_hq --email you@company.com --name "Your Name"`.
   HQ then creates every other login from the **Team** screen.
6. Set up the nightly backup (section 7).

Several server processes are started (4). If you later run more than one **machine**, add `REDIS_URL` so the wrong-password
counters are shared; live updates already work across processes (the database tells every process).

## 6. Move the existing data from Supabase

Do this once, on an empty database, **before** switching the pages over.

```bash
# 1. In Supabase: Project Settings → Database → Connection string (URI). Use the one that starts postgresql://postgres:…
docker compose exec web python manage.py import_from_supabase --source "postgresql://postgres:PASSWORD@db.xxxx.supabase.co:5432/postgres" --dry-run
docker compose exec web python manage.py import_from_supabase --source "postgresql://…"        # the real copy
docker compose exec web python manage.py regenerate_pdfs                                        # make every sent bill's PDF again
```

* The old database is only read, never changed. The import is one transaction: it either all lands or nothing does.
* Logins keep their **passwords** (Supabase's bcrypt hashes are accepted as they are). A login that had no password needs an HQ reset.
* Ids and codes are kept: bill numbers, lead codes, load codes, share tokens. New numbers continue after the highest old one.
* Suggested switch-over: ask everyone to finish their routes → run the import → check a few screens → point the pages to the new
  server → keep Supabase untouched for a couple of weeks → then close it.
* **Old WhatsApp bill links** (`…supabase.co/functions/v1/bill-pdf?t=…`) stop working when Supabase is closed. New bills use the new address.
  If customers must still open old links, keep the Supabase project alive (read only) for as long as you need them.

## 7. Backups and day-to-day

* **Database + PDF bills** both matter. `deploy/backup.sh /backups` writes both (run nightly from cron, and copy the files off the machine).
* Update: pull the new code, `docker compose up -d --build` (tables are updated automatically).
* Reset a password: HQ → Team. Switch off the "one login per person" rule: `SINGLE_SESSION=0`.
* Weighing tolerance (default 2%): `WEIGHING_TOLERANCE_PCT`.
* Logs: `docker compose logs -f web`.

## 8. Security notes

* Logins use bcrypt/PBKDF2 hashes; tokens are signed (HS256, `JWT_SECRET`, defaults to the secret key) and expire in one hour;
  refresh tokens are random and stored only as hashes. 10 wrong passwords per email and address pause login for 15 minutes.
* "Newest login wins": a new login signs the person out on other devices at once (the old device's token stops working).
* Records that must never change are protected twice (in the Python code **and** by database triggers): the cash ledger, the
  activity log, releases to HQ, cash-count decisions, weighings (only "superseded"), and bills after they are sent.
* Stock releases and cash payments take locks, so two people acting at the same moment can never overdraw stock or cash
  (proved by `core/tests/test_concurrency.py`).
* Searches and filters are always passed to the database as values, never joined into the SQL text.
* No cookies are used, so cross-site request forgery does not apply (the CSRF middleware is deliberately absent).
* The public bill link is an unguessable 128-bit token and shows only that one bill.

## 9. Differences from the old system (be aware)

1. **Three small functions were rebuilt from how the screens use them**, because their original text was not available:
   `set_bill_item` (a weight of 0 removes the line; the rate is always HQ's current rate), `mark_bill_shared`, and the exact
   wording of a few rarely seen messages. Everything else was ported from the original SQL. Check these once with a real pickup.
2. PDFs are drawn with ReportLab instead of pdf-lib. The layout was compared by eye with the approved design and matches;
   the badge picture is read from `core/static_assets/bill-badge.png` (no download at bill time).
3. PDFs are files in `MEDIA_ROOT` (in Docker: the `media` volume) instead of Supabase storage. Back that folder up.
4. Added: login rate limit, a 60-second grace for a refresh token that was just replaced (two tabs refreshing together),
   database-level guards, and tests. Removed: the temporary "test key" mode of the PDF function.
5. Needs **PostgreSQL** (it uses row locks, advisory locks, `LISTEN/NOTIFY` and a few Postgres-only report queries).
6. Not tested here: the Docker/Caddy files themselves (no Docker on the build machine) and a run against a real Supabase export
   (the import was tested against a database built with the same table layout, including bcrypt logins). Do the dry run first.
