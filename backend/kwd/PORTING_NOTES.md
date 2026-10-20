# KWD (Scrappy Field) port: working notes

Source: React+Vite app "scrappy-field" (session "Scrappy Kitchen Waste Digester staff monitoring dashboard"),
source folder: <that session's scratch workspace>/app/src (53 files, ~8.3k lines) + docs/ + supabase/.
Live Supabase project (ref pdfcyfrxktpcryanfbgj) is the source of truth for rules (the repo SQL is incomplete).

## Decisions (confirmed by the owner)
- Scope: whole app: TSO, Zonal Manager, Head Office, Franchisee (+ HO franchise screens).
- UI: rewrite as Django templates + plain JS (NO React). Same classes/theme.css so it looks identical.
- Backend: port everything to Django (rules, RLS, 2 edge functions, storage, Excel), then import data.
- Auth: ONE login page / ONE users table; role picks the dashboard (middleware).

## Design
- Tables are prefixed kwd_ (profiles -> kwd_profiles ...) to avoid clashing with the scrap app. API names stay the Supabase names.
- Schema is created by raw DDL migration (exact constraints) - models are not used for these tables.
- kwd/engine.py: query engine that understands the same query shape supabase-js sends (select with embeds, filters, order,
  limit/range, single, count/head, insert/update/delete/upsert). Per-table read/write scopes = the old RLS policies.
- kwd/rules/*.py: ports of the Postgres triggers (visits, tasks, contacts, followups, verification calls, field_days,
  expense_items, expense_policy, recalc_field_day, pay_month, flag_day, franchise rules, audit_log).
- JS side: a tiny supabase-like client (static/kwd/js/sb.js) posts structured queries to /kwd/api/q, so the page code keeps its
  query chains. Photos: /kwd/api/storage. Edge functions: /kwd/api/fn/admin-users, /kwd/api/fn/resolve-map-link.
