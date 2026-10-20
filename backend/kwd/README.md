# Scrappy Field (Kitchen Waste Digester staff monitoring), inside this Django project

This is the app Territory Sales Officers, Zonal Managers, Head Office and franchise partners use to plan and log LSGD visits,
claim TA/DA, and run the franchise module (leads, sales, stock, targets, presentations). It used to be a React + Vite app on
its own Supabase project. It now lives here: the data in PostgreSQL tables `kwd_*`, the rules in Python, the screens as
plain JavaScript served by Django. There is no React and no build step.

Open it at `/kwd/` after signing in at `/login/` (one login page for every Scrappy role, see "Sign-in" below).

## Who sees what

| Role (staff profile) | Opens | What they get |
|---|---|---|
| `tso` | `/kwd/` | Today, LSGDs, log a visit (6 steps), follow-ups, my work (TA/DA requests, visits, Excel) |
| `zonal_manager` | `/kwd/` | Overview, visit review, TA/DA verification, planning, LSGDs, call-backs, plus their own field day |
| `head_office` | `/kwd/` | A choice: **Staff monitoring** (sign-off, TA/DA approval + monthly settlement, fraud check, staff logins, rates) or **Franchise** (leads, sales, stock, meetings, franchisees, targets and prices) |
| `franchisee` | `/kwd/` | Home, leads, sales, stock, meetings, targets |

The scrap app's roles (`driver`, `warehouse`, `supervisor`, `hq`) open `/collector/`, `/warehouse/`, `/hq/` as before.

## Sign-in: one login, the role picks the dashboard (`portal/`)

* One users table (`users`). A person has a scrap profile **or** a staff profile; that decides the dashboard
  (`portal/gate.py: destination()`).
* `/login/` is the only login page. It posts to `/login/`, which checks the password (same rules as `/auth/v1/token`:
  rate limit, newest login wins), answers with the dashboard address and the login the page must keep in the browser, and
  sets a signed, http-only cookie naming the login session.
* `portal.gate.PortalGate` (middleware) reads that cookie for **page** requests only. No cookie, or the session was replaced or
  signed out: redirect to `/login/`. Someone else's dashboard: redirect to your own. `/` goes to your dashboard or the login.
  Data calls (`/kwd/api/...`, `/rest/...`) are not touched: they carry their own token and guard themselves.
* A 10-second "hop" cookie stops a redirect loop if a dashboard bounces you back to `/`.

## Backend map

| Piece | File |
|---|---|
| Tables, views, checks, links, starting rows (14 districts, expense policy, 8 products) | `migrations/0001_kwd_schema.py` (raw SQL copied from the live database) |
| Column types, links between tables | `schema.py` |
| Who may read which rows (the old row-level-security policies) | `scope.py` |
| Query engine: the same query shape supabase-js sent (embeds, filters, order, count, single, insert/update/upsert/delete) | `engine.py` |
| Rules that were database triggers (visit flags, day recalculation, expense checks, claim steps, franchise stock/sales ...) | `rules/*.py` |
| Named actions (`pay_month`, `flag_day`, `fr_record_sale`, `fr_cancel_sale`), photo storage, the two edge functions (`admin-users`, `resolve-map-link`) | `api.py`, `functions.py`, `storage.py` |
| HTTP routes | `urls.py` (`/kwd/api/q`, `rpc/<name>`, `fn/<name>`, `storage/...`, `session`) |

Tables are prefixed `kwd_` so they sit beside the scrap app's tables; the pages still use the original names (`visits`,
`field_days` ...). The rules are Python, not database triggers, so they run on every write that goes through the API; data
copied in by the importer is copied exactly as it was.

## Frontend map (`static/kwd/js`, ES modules, no build)

* `core.js`: the runtime. `html` templates (escape everything unless marked safe), a `supabase`-style data client that
  posts to `/kwd/api/q` (so queries read like the old ones), `Screen` (state, `view()`, actions), `widget()` for rows and cards
  that need their own state, a DOM patcher that keeps typing, focus and scroll, token refresh.
* `ui.js` icons, mascot, stats, headers. `kit.js` sheets, photo picker, team loader, map-link helpers. `lib.js`, `expenses.js`,
  `fr.js` constants and helpers. `report.js`, `frReport.js` Excel (ExcelJS is loaded on demand from `vendor/`).
* `app.js` starts the right shell for the role. `shell.js` top bar, tab bar, side navigation.
* `pages/` one module per screen (`pages/zm/`, `pages/ho/`, `pages/fr/`, `pages/ho/fr/`). `css/theme.css` is the original
  stylesheet, unchanged; `css/kwd.css` holds the few additions.

A screen is `{ state, init, view(S, ctx), actions, widgets, after, destroyed }`. In `view`, `data-act="name"` calls
`actions.name(el, event)` on click, `data-submit`, `data-bind="path"` stores an input's value (`data-live` redraws as you
type), `data-change="name"` runs after the value is stored. `widget(this, 'name', key, props)` puts a child screen in the page;
the screen lists it under `widgets: { name: def }`, reads `ctx.props`, and reaches its parent through `ctx.parent`.

## Run it, test it

```bash
python manage.py migrate
python manage.py seed_kwd_demo            # development only: ho@/zm@/tso@/fr@demo.test (password in the command file)
DJANGO_DEBUG=1 python -m uvicorn scrappy.asgi:application --port 8000
# open http://127.0.0.1:8000/  ->  sign in
python manage.py test kwd portal          # staff app and sign-in tests (the whole suite: python manage.py test)
```

Static files are served by WhiteNoise straight from the apps' `static/` folders (`collectstatic` is optional).

## Move the data from the old Supabase project

```bash
python manage.py import_kwd_from_supabase --source "postgresql://postgres:PASSWORD@db.<ref>.supabase.co:5432/postgres" --dry-run
python manage.py import_kwd_from_supabase --source "postgresql://…" --supabase-url https://<ref>.supabase.co --service-key <service role key>
```

Read-only on the source, one transaction, ids kept, bcrypt passwords kept, counters continue after the highest id. It refuses
to run if the staff app already has data here or if a source email already exists in `users` (it lists them). Photos come from
`--storage-dir` (a download of the `visit-photos` bucket) or are downloaded with the service key; without either it tells you
how many are missing. Do a dry run first.

## Known limits (be aware)

* The rules were ported from the live database's functions and triggers and checked by 60+ automated tests, but the importer
  was exercised on a database built with the same table layout, **not** on the real Supabase project. Do the dry run.
* GPS and camera flows were driven in a browser with a stubbed location and a generated photo, not on a real phone.
* The home-made `Screen` runtime replaces React. It covers what this app needs; it is not a general framework.
