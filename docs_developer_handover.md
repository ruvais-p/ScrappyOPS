# Scrappy App: Developer Handover

**Goal:** rebuild the existing Scrappy App exactly as it is today. No new features, no redesign.
**Company:** Scrappy Innovations, Kerala. Scrap-collection franchises (one franchise per Assembly Constituency).
**Live project files:** `Scrappy App Files/scrappy_app/` (deployable folder), `Scrappy App Files/warehouse_sql/` (database scripts).


> **Update:** a Django backend now exists that replaces Supabase with the same behaviour: see `scrappy_backend/README.md`.
> Sections 0 and 6 of this file describe the old Supabase project; the rules in sections 3, 5 and 11 apply unchanged to the Django version.


---

## 0. Read this first: what is and isn't in this document

| Source | Status |
|---|---|
| Warehouse, HQ, franchise, lead-assignment, cash and invoice database scripts (`warehouse_sql/01` to `19`) | Written out in the files. The exact SQL is the source of truth. |
| Front-end code (launcher, collector, warehouse, HQ) | Complete, in `scrappy_app/`. |
| Edge functions `bill-pdf` and `hq-logins` | Source in `warehouse_sql/bill-pdf/` and `warehouse_sql/hq-logins_edge_function.ts`. |
| **Base tables and early functions**: `profiles`, `customers`, `leads`, `loads`, `bills`, `bill_items`, `scrap_items`, `cash_ledger`, `lead_import`, `app_secrets`, and the functions `my_role`, `my_leads`, `set_bill_item`, `send_bill`, `confirm_bill`, `pay_bill`, `mark_bill_shared`, `end_route`, `bill_whatsapp`, `_my_bill`, `session_valid` | **Created directly in the Supabase project `suluhhbomiuwwocrfpxg` before the SQL files were kept. They are not in the `.sql` files.** |

**Action for the developer:** get Supabase access to project `suluhhbomiuwwocrfpxg` and run `supabase db dump --schema public` (plus the `auth.sessions` trigger from step 16). That dump plus the `.sql` files is the exact database. Section 6 describes what those missing pieces do so you can check the dump against it. Do not rewrite them from this description alone.

---

## 1. Product in one paragraph

A single web app, installable on phones (PWA), with one login page that sends each person to the right dashboard by role. **Collectors (drivers)** visit customers, weigh scrap, create a bill, get the customer's agreement, pay the customer (UPI or cash) and end the route. **Warehouse staff** weigh the load again and check it against the bills; **supervisors** assign leads, verify cash and release stock to HQ. **HQ** sees every franchise, uploads leads, sets rates, manages people and franchises, raises stock requirements, and resolves disputes. HQ is the only buyer of warehouse stock.

---

## 2. Tech stack and hosting

| Layer | Choice |
|---|---|
| Front end | Plain static HTML/CSS/JS, **no framework, no build step needed at runtime**. One `index.html` per dashboard with inline CSS/JS, plus a shared `brand.css`. |
| Hosting | Cloudflare Workers static assets. Live at `scrappy-manager.scrappyinnovationsltd.workers.dev`. |
| Back end | Supabase (Postgres + Auth + Row Level Security + Edge Functions + Realtime + Storage). |
| Supabase project | `suluhhbomiuwwocrfpxg` (URL `https://suluhhbomiuwwocrfpxg.supabase.co`). The publishable (anon) key is in `scrappy_app/index.html`. Never put the service-role key in the front end. |
| Data access | Front end calls PostgREST (`/rest/v1/rpc/<function>` and a few read-only `/rest/v1/<table>` reads) with the user's JWT. Realtime over websocket for live refresh. |
| PDF | Edge function `bill-pdf` using `pdf-lib 1.17.1`, standard Helvetica. |
| Fonts | Sora (headings), DM Sans (body), from Google Fonts. |
| Installable | `manifest.webmanifest`, icons (192, 512, maskable, apple-touch), and a do-nothing service worker `sw.js` (installability only; it caches nothing). |

### Folder layout (must be kept)
```
scrappy_app/
  index.html            login launcher (role routing)
  collector/index.html  driver dashboard
  warehouse/index.html  warehouse + supervisor dashboard
  hq/index.html         HQ dashboard
  brand.css             shared visual layer (loaded by all three dashboards)
  badge.webp, logo.webp login badge and cached logo
  bill-badge.png        used by the invoice PDF (fetched by the edge function)
  manifest.webmanifest, sw.js, icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png
```
Note: the invoice PDF function fetches `bill-badge.png` from the live site. If the domain changes, update `BADGE_URL` in `bill-pdf/invoice.ts` and redeploy the function.

---

## 3. Roles and exact permissions

Role is stored in `profiles.role`. Allowed values: `driver`, `warehouse`, `supervisor`, `hq`.
Every role except `hq` belongs to exactly **one franchise** (`profiles.franchise_id`, enforced by a check constraint). HQ belongs to none and sees all. The database enforces everything below; the front end only hides buttons.

| Role | Dashboard | Label in side panel | Can do | Cannot do |
|---|---|---|---|---|
| `driver` | Collector (`/collector/`) | Collector | See own leads. Start a pickup. Enter weights per material. Send bill, record customer agreement, pay (UPI with UTR, or cash from cash-in-hand). Mark pickup "could not complete" with a reason. End route. See own cash and loads. | See other drivers' data, change rates, assign leads. |
| `warehouse` | Warehouse (`/warehouse/`) | Warehouse manager | Weigh submitted loads material by material. Issue cash float to drivers. Count route cash. View leads, inventory, HQ requirements, finance in own franchise. | **Release stock to HQ** (moved to supervisor). Verify cash. Assign leads. Resolve flagged loads. |
| `supervisor` | Warehouse (`/warehouse/`) | Supervisor | **Release stock to HQ.** Verify or dispute cash counts (must be a different person from the counter). Assign and split leads among drivers (own franchise only). Opens on the Finance tab. | Weigh loads. Raise requirements. Change rates. |
| `hq` | HQ (`/hq/`) | HQ | Everything, across all franchises or one chosen franchise: upload leads, reassign or cancel leads, set rates, add items, raise or cancel stock requirements, resolve flagged loads and disputed cash, manage franchises and people, reset passwords, read the activity log. HQ can also perform any warehouse/supervisor action. | Warehouse dashboard shows "HQ uses the HQ dashboard" if an HQ user opens it. |

Role-to-dashboard routing in the launcher: `driver → collector`, `warehouse → warehouse`, `supervisor → warehouse`, `hq → hq`. An inactive profile or unknown role is refused with a message.

### Button rules in the warehouse dashboard
```
canWeigh   = warehouse or hq
canRelease = supervisor or hq      (changed from warehouse in step 19)
canVerify  = supervisor or hq
canAssign  = supervisor or hq
isHQ       = hq (cancel requirement, resolve flagged load)
```

---

## 4. Screens per dashboard

### Launcher (`/`)
Split login page: brand panel (animated badge reveal, drifting reduce/reuse/recycle shapes, role chips) and a form panel (email, password). Signs in with Supabase Auth, reads the profile, stores the session under a per-dashboard key (`scrappy_session`, `scrappy_wh_session`, `scrappy_hq_session`) and redirects. Opening screen and the login button show the brand "hop" loader. A `?m=` query shows a message such as "You were logged out because this account was opened on another device."

### Collector (driver)
Left panel: franchise card, **name / "Collector" / email**, nav, Log out.
Tabs: **Home** (KPIs: paid to customers, UPI vs cash, cash in hand), **Pickup** (today's leads; tabs Open / Closed / Failed), **Loads**, **Cash**.
Pickup flow for one lead:
1. **Start pickup** (`start_pickup`) → lead becomes `in_progress`, a draft bill is created.
2. **Weighing**: one quantity box per scrap item at the current rate. The amount next to each item, the bill lines and the total update **as you type**. Each quantity is saved with `set_bill_item` (saves are queued so none are dropped). Lock-bill button enables when any weight is entered.
3. **Send bill** (`send_bill`), then share on WhatsApp (`bill_whatsapp` builds the text; `mark_bill_shared`).
4. **Customer agreement** (`confirm_bill`).
5. **Pay**: UPI (enter the 12-digit UTR; the customer's UPI id is shown masked) or Cash (only if enough cash in hand). `pay_bill`. Lead becomes `closed`.
6. **Could not complete** (`fail_pickup`) only before the bill is sent. Reasons: Customer not at home; Customer cancelled; Phone not reachable; Wrong address or location; No scrap, or too little; Customer did not agree to the rate; Vehicle or other problem on my side; Other (note allowed).
7. **End route** (`end_route`) → load goes to `submitted`. Driver takes the load to the warehouse.

### Warehouse / Supervisor
Tabs: **Overview**, **Leads** (assign and split), **Reconcile loads** (weighing), **Inventory**, **HQ requirements** (release stock), **Finance** (float, cash count, verification). Weighing tolerance is shown in the footer (±2%).

### HQ
Tabs: **Overview**, **Franchises**, **Leads** (upload + reassign/cancel), **Pickups and bills**, **Loads and weighing**, **Stock and requests**, **Cash**, **Team**, **Rates**, **Activity log**. A franchise picker scopes every report (or "all").

### Common behaviour
- Side panel shows employee name, designation, email on every dashboard.
- Auto-refresh pill; Realtime plus a 15-second refresh when the tab is visible.
- **One login per person, newest wins** (section 7).
- Mobile: nav becomes a bottom/foot bar, Log out is shown in the nav on phones. Layouts for phone and landscape must be kept.

---

## 5. Business rules (do not change)

**Lead states:** `unassigned` (HQ upload for a franchise, no driver) → `scheduled` → `in_progress` → `closed`; also `cancelled` and `failed`. A lead without a driver may only be `unassigned` or `cancelled`.
**Bill states:** `draft` (labelled "Weighing") → `sent` ("Bill sent") → `confirmed` → `paid`.
**Load (route) states:** `open` → `submitted` (driver ended route) → `reconciled` or `flagged` (after warehouse weighing). HQ resolves a flagged load by **accept** (becomes reconciled) or **reweigh** (back to submitted); a note is mandatory.
**Settlement states:** `counted` → `verified` or `disputed` (final).

**Warehouse weighing** (`record_load_weighing`): weights are entered per material as `[{"item_id":1,"kg":41.5}, ...]`. A material is OK when `|weighed − billed| / billed ≤ 2%` (single function `wh_tolerance_pct()`). All OK → load `reconciled`, otherwise `flagged`. Every billed material must be entered. Old weighings are kept and marked `superseded_at`.

**Stock** in the yard for a material = sum of current warehouse weights of loads that are `reconciled` or `flagged`, minus all releases to HQ.

**HQ requirements and releases:** HQ raises a requirement (code `RQ-0001`...) for an item and kg. The supervisor releases stock against it (code `RL-0301`...) with a vehicle number. The database refuses a release larger than the remaining need or than the stock, refuses a cancelled requirement, and locks the item row so two releases cannot race.

**Vehicle loads for HQ (dispatch flow, added after the first handover):** stock now leaves the yard in two hands.
1. HQ raises requirements as before and sets **what it pays the franchise per kg** for each material (`hq_set_buy_rate`, HQ's Rates tab; price history in `hq_buy_rates`, current price in view `current_hq_buy_rates`). The price is the same for every franchise.
2. When the HQ pickup vehicle is loaded, the **warehouse manager** enters the quantity of each material and the vehicle number and sends it to the supervisor (`wh_submit_dispatch`, code `DP-0001`...). One load carries one franchise's stock, one line per HQ request. Nothing leaves the stock yet, but the kg are reserved so two waiting loads cannot promise the same stock or more than HQ asked for.
3. The **supervisor** finalizes it or sends it back with a reason (`sup_review_dispatch`). A different person from the preparer must decide. Finalizing creates the normal `hq_releases` rows (so stock and requirement progress work as before) and fixes the price per kg and the amount on each line; a later price change never alters a finalized load. If HQ has not set a price for a material the supervisor is told to ask HQ. A sent-back load is corrected and resent with the same code (`wh_submit_dispatch` with `p_dispatch_id`); the warehouse manager can also withdraw it (`wh_withdraw_dispatch`).
   A load does not need an HQ request: a line with `item_id` instead of `requirement_id` loads a material HQ has not asked for (shown as "No request"; its `hq_releases` row has no requirement). Stock is checked the same way, and HQ must pass `p_franchise_id` when no line names a request.
4. **Prices are for the supervisor and HQ only**: `sup_stock_value` (the supervisor's "Sale prices" section: stock, HQ price per kg, stock value, sold to HQ, waiting for approval) and the price columns of `wh_dispatches` are refused or left out for warehouse managers and drivers. The tables are not readable through `/rest/v1`.
The old one-step `release_to_hq` still exists in the API but the warehouse screen no longer offers it.

**Billing (tax invoices, added after the first handover):** two kinds, both on the `invoices` / `invoice_lines` tables and both downloadable as a PDF (`POST /functions/v1/invoice-pdf {invoice_id}`).
- **Purchase invoice: a franchise invoices HQ.** The supervisor makes it from a finalized load (`bill_create_purchase_invoice`): same kg and price per kg as the load, GST added from the material's rate. One invoice per load; cancelling it (while unpaid) lets the load be invoiced again. The seller is the franchise (GSTIN, address, phone, email, state: `set_billing_details`, shown as "Our billing details" in the supervisor's Billing tab); the buyer is HQ (the company settings of the franchise module).
- **Sale invoice: HQ invoices a buyer.** HQ keeps a list of buyers (`hq_save_buyer`) and sells from the stock it holds, which is everything released to it (`hq_releases`) minus what it has already invoiced (`bill_create_sale_invoice`; it refuses to sell more than HQ holds, one sale at a time per material). Cancelling returns the stock.
- **HSN code and GST rate per material** are set by HQ on the Rates tab (`hq_set_item_tax`) and copied onto each invoice line when the invoice is made.
- **Invoice history:** seller/buyer details and material names are copied when a scrap invoice is issued. Later edits to master data do not change its PDF or invoice list. Migration `0009_invoice_snapshots` backfills older invoices using currently available details.
- **Input precision:** scrap invoice weights accept up to three decimal places; rates and GST accept two. Extra precision is rejected before calculating stock or totals, so stored values and printed amounts agree.
- **Numbers:** `<franchise code>/<financial year>/<0001>` for a franchise (KKD/2627/0001) and `HQ/2627/0001` for HQ; numbers are never reused after a cancellation. Payment is marked by HQ (`bill_mark_paid`: paid to the franchise, or received from the buyer); a paid invoice cannot be cancelled.
- **Who sees what:** HQ sees every invoice; a supervisor sees only their own franchise's invoices to HQ; warehouse managers and drivers see none (invoices carry prices).

**Cash:** 
- `issue_float` (warehouse/hq): positive amount up to ₹5,00,000 to an active driver, written to `cash_ledger` as `float_issued`.
- Paying a customer in cash reduces the driver's cash-in-hand; the driver cannot pay cash beyond cash in hand.
- `count_route_cash` (warehouse/hq): counts the cash a driver hands back after a route. Expected = ledger balance at the time the route was submitted. Earlier routes must be counted first. A note is mandatory if the count differs. It writes a `handover` entry for the expected amount and a `cash_settlements` row (expected, counted, difference, cash paid, UPI paid).
- `verify_settlement` (supervisor/hq): **a different person from the counter** must verify or dispute; a note is mandatory for any difference or dispute (DB check `settle_two_people`).
- HQ resolves disputes (`hq_resolve_dispute`) and can receive cash (`receive_cash`).

**Lead upload (HQ):** rows go into `lead_import`; trigger `process_lead_import` validates and creates customers and leads. Rules: phone 10 digits (last 10 kept); date `YYYY-MM-DD` or `DD-MM-YYYY`; time like `11:30 AM` (default 09:00); no date more than a day in the past; latitude/longitude optional but both or neither, must fall inside India (lat 6–38, lng 67–98), and "10.0159, 76.3419" pasted into the latitude cell alone is accepted; `franchise_code` (e.g. `KKD`) creates an `unassigned` lead, `driver_email` creates an already assigned lead; a second lead for the same customer on the same day is marked `duplicate`. Template: `SUPABASE FILES/Scrappy_Lead_Upload_Template.xlsx`.

**Tamper protection (database triggers):** weighings cannot be edited or deleted; releases and the activity log are append-only; a counted settlement can only move to verified or disputed; settlements cannot be deleted.

**Timezone:** all "today" logic uses `Asia/Kolkata`.

**Money format:** Indian rupee, `₹`, Indian digit grouping on invoices.

---

## 6. Database

### 6.1 Tables
Built in the SQL files unless marked *(base)*.

| Table | Purpose / key columns |
|---|---|
| `profiles` *(base)* | `id` (= auth user id), `full_name`, `role`, `franchise_id`, `phone`, `territory`, `vehicle_no`, `active`. Check: role in driver/warehouse/supervisor/hq; non-HQ must have a franchise. |
| `franchises` | `id`, `code` (unique, `^[A-Z0-9][A-Z0-9-]{1,11}$`), `name`, `district`, `constituency`, `active`. First franchise: `KKD` Kakkanad, Ernakulam (all pre-existing data was assigned to it). |
| `customers` *(base)* | `name`, `phone`, `address`, `area`, `upi_id`. Matched by last 10 digits of phone. |
| `scrap_items` *(base)* | Materials with name, `rate_per_kg`, active flag. HQ adds items and sets rates. |
| `leads` *(base + steps 13, 15)* | `code`, `customer_id`, `driver_id`, `franchise_id`, `slot`, `items_said`, `status`, `latitude`/`longitude`, `fail_reason`, `fail_note`, `failed_at`, `closed_at`, `created_by`, `created_at`. |
| `lead_import` *(base + steps 13, 15)* | HQ bulk-upload staging: customer_name, phone, address, area, upi_id, items, pickup_date, pickup_time, driver_email, franchise_code, latitude, longitude, plus result `status`, `lead_code`, `message`. |
| `loads` *(base + step 2)* | A driver's route: `code`, `driver_id`, `franchise_id`, `status`, `started_at`, `submitted_at`, `warehouse_kg`, `checked_by`, `weighed_at`, `weighing_note`, `resolved_by`, `resolved_at`, `resolution_note`. |
| `bills`, `bill_items` *(base)* | Bill per pickup: load, status, payment method, UPI reference, share token, paid time; items with `item_id`, `qty_kg`, `rate_per_kg`, `amount`. Views `bill_totals` and `hq_paid_bills` total them. |
| `cash_ledger` *(base)* | Driver cash entries: `entry_type` (`float_issued`, payment, `handover`...), signed `amount`, `note`, `created_by`, `franchise_id`. |
| `load_weighings` | Per-material warehouse weighing (see rule above). Unique current row per (load, item). |
| `hq_requirements` | HQ stock requests. `status` open / cancelled. |
| `hq_releases` | Stock released to HQ. Append only. |
| `cash_settlements` | One per counted route. |
| `settlement_resolutions` | Records how disputes were resolved. |
| `hq_audit` | Append-only activity log (`by_id`, `action`, `ref`, `detail`, `franchise_id`). |
| `app_secrets` *(base)* | Server-only secrets such as `bill_pdf_test_key` (must be NULL in production). |

Sequences: `requirement_code_seq`, `release_code_seq` (starts 301). Triggers copy `franchise_id` onto new leads, loads, cash entries, weighings, settlements and releases from their driver, load or requirement.

### 6.2 Views
`wh_stock_movements`, `hq_requirement_progress`, `hq_paid_bills`, `bill_totals`. All created `with (security_invoker = true)` so row-level security still applies.

### 6.3 Functions (callable by logged-in users only, never by `anon`)
Every function is `security definer`, sets `search_path` to `public`, checks `my_role()` itself, and has `revoke ... from public, anon` then `grant execute ... to authenticated`.

- **Identity:** `my_role()`, `my_franchise()`, `is_wh_staff()`, `fr_ok(f)`, `fr_scope(f)`, `session_valid()`.
- **Collector:** `my_leads()`, `start_pickup`, `set_bill_item`, `send_bill`, `mark_bill_shared`, `confirm_bill`, `pay_bill`, `fail_pickup`, `end_route`, `bill_whatsapp(p_bill_id integer)`.
- **Warehouse / supervisor:** `wh_tolerance_pct`, `record_load_weighing`, `record_weighing` (deliberately disabled), `resolve_flagged_load`, `release_to_hq` (supervisor, hq), `issue_float`, `count_route_cash`, `verify_settlement`, `wh_leads`, `wh_lead_counts`, `wh_driver_workload`, `wh_assign_leads`, `wh_split_leads`, `wh_stock_report`, `wh_pickups`, `wh_transactions`, `wh_route_cash`, `wh_uncounted_loads`.
- **HQ:** `hq_overview`, `hq_daily`, `hq_item_summary`, `hq_driver_scorecard`, `hq_bills`, `hq_leads`, `hq_loads`, `hq_team`, `hq_franchises`, `hq_add_franchise`, `hq_update_franchise`, `hq_add_person`, `hq_update_profile`, `hq_reassign_lead`, `hq_cancel_lead`, `hq_set_rate`, `hq_add_item`, `hq_set_item_active`, `hq_resolve_dispute`, `hq_open_disputes`, `raise_requirement`, `cancel_requirement`, `receive_cash`, `hq_log`, `hq_end_sessions`.
- **Franchise scope:** list functions take an optional `p_franchise`. For non-HQ it is forced to the caller's own franchise; for HQ `null` means all.

### 6.4 Row-level security
RLS is on for every table. `authenticated` users have **select only** via policies; all writing happens through the functions above (`revoke insert, update, delete, truncate` on the tables). `anon` has no table access. Franchise staff see only their franchise's rows; a driver sees only their own rows; HQ sees all.

### 6.5 Migration order
Apply in this order after the base schema dump: `01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 18 → 19`. (There is no step 17.) Steps 16, 18 and 19 are marked "already applied, do not run again" in their headers. Replaying on a fresh database: take the live dump instead of re-running those three.

---

## 7. Authentication and sessions

- Supabase Auth, email + password. **Users are created by HQ**, not self-sign-up. No public sign-up.
- Creating a person: edge function `hq-logins` (HQ-only, verified from the caller's token and an active HQ profile). Actions: `create` (makes the auth user and profile for roles driver/warehouse/supervisor, either with an HQ-typed password or a generated `XXXX-XXXX-XXXX` one returned once and never stored) and `reset_password` (also ends the person's open sessions via `hq_end_sessions`). HQ logins cannot be created or reset here. `verify_jwt` is false; the function checks the token itself.
- **Single session:** trigger `one_session_per_user` on `auth.sessions` deletes a user's other sessions on new login; `session_valid()` is checked by `my_role()`, `my_franchise()`, `my_leads()`, `_my_bill()` and `end_route()`; each dashboard also calls `session_valid()` every 20 seconds and signs out with "You were logged out because this account was opened on another device." To switch off: `drop trigger if exists one_session_per_user on auth.sessions;`
- Passwords: the front end never stores them. Only the Supabase session is kept in `localStorage` under the per-dashboard key.

---

## 8. Edge functions

| Function | Purpose | Notes |
|---|---|---|
| `bill-pdf` (v7) | Builds the invoice PDF from the database (never from the phone), stores it in the private `bills` storage bucket, returns a fixed link `…/functions/v1/bill-pdf?t=<token>` that always serves the newest PDF (so after payment the same link shows PAID). | `verify_jwt=false`; the driver call is verified with `jose` against the project JWKS; customer link uses an unguessable UUID token. Test mode only when `app_secrets.bill_pdf_test_key` has 32+ characters (keep NULL). Do **not** embed large base64 in the function source; the badge is fetched at runtime and verified by length (4963 bytes) and an FNV-1a hash. If the fetch fails it draws a text badge and never blocks a bill. |
| `hq-logins` (v2) | Create logins and reset passwords (section 7). | Uses the service-role key server-side only. |

### Invoice design (A4, one page, pdf-lib, Helvetica)
Oxblood header band with badge; info card (bill no, date, collector, franchise, customer name and phone); rotated **PAID** / **NOT PAID YET** stamp; items table (item, kg, rate, amount); payment box (method, UPI reference); oxblood total box with total in words; note; footer with the brand line. Reference preview: `invoice_preview/index.html`.

### WhatsApp message (built by `bill_whatsapp` + collector)
Greets the customer by first name, gives bill number, weight and amount to receive, then the PDF link, "Please check it and tell <collector> if all is correct. This same link shows PAID once we pay you." and the brand line **"Waste management, made simple."**

---

## 9. Brand and UI specification

Source: Scrappy Brand Book v3.5 (`C:\Local Disk-D\Scrappy App\Branding\Scrappy-Brand-Book-v3_5.html`). The visual layer is `brand.css`, injected after each dashboard's own CSS. It is **visual only**: it never changes layout, so phone and landscape layouts stay intact.

| Token | Value |
|---|---|
| Oxblood (primary) | `#8B1E24`; scale `#74181E`, `#5E1318`, `#300A0C`; tint `#F5DEDF` |
| Pearl (background) | `#F7F7F7` |
| Ink (text) | `#2A2426` |
| Fonts | Sora 600/700 (headings), DM Sans (body) |
| Radii | 14 / 12 / 10 px |
| Buttons | oxblood, 48 px high, radius 12 |
| Tab/lead cards | thin status bar on the left edge (`.lead.live` oxblood) |
| Brand shapes | reduce ▽, reuse ●, recycle △ |
| Loader | CSS "hop" loader (`hop.svg`, 64 px, oxblood), used on every loading block, the boot screen and the login button's busy state. The old spinner is hidden. |

Known deliberate choices: no coloured "service bar" at the bottom of the left panel (hidden on all dashboards); the in-progress lead card is square-cornered (a stray oval outline was removed); `prefers-reduced-motion` is respected. Dark mode is **not** implemented.

Performance targets already met and to be kept: no framework, one cached `logo.webp` shared by all pages, fonts preconnected, no images inlined as base64 except tiny assets.

---

## 10. Build and deploy

1. Create the Supabase project (or use `suluhhbomiuwwocrfpxg`), apply the database dump and migrations (section 6.5), set the edge functions, create the private storage bucket `bills`.
2. Set the Supabase URL and publishable key in `scrappy_app/index.html` (placeholders `__SUPABASE_URL__`, `__SUPABASE_KEY__` in the template).
3. Upload the whole `scrappy_app/` folder to Cloudflare (Workers static assets) and keep the folder structure.
4. If the domain changes: update `BADGE_URL` in `bill-pdf/invoice.ts`, redeploy `bill-pdf`, and update the Supabase Auth site URL.
5. Create franchise `KKD` (exists) and the first HQ user manually in Supabase (HQ logins cannot be made through the app). Then HQ creates everyone else from the **Team** tab.

The three dashboards currently ship as pre-assembled single files. The original build pipeline (templates plus a small Node script that swaps fonts, links `brand.css`, replaces the logo and injects the loader) is not required to rebuild; developing directly in the three `index.html` files is acceptable.

---

## 11. Acceptance checklist (the rebuilt app must pass all)

**Login and roles**
- [ ] Each of the four roles lands on the right dashboard; wrong dashboard is refused; inactive users are refused.
- [ ] Logging in on a second device signs out the first within 20 seconds with the stated message.
- [ ] Side panel shows name, designation, email.

**Collector**
- [ ] Typing a quantity updates that item's amount, the bill lines and the total immediately; moving straight to the next box never loses a save.
- [ ] Bill cannot be sent with no weight; cash payment is blocked when it exceeds cash in hand; UPI needs a UTR.
- [ ] WhatsApp text and PDF link work; the link shows PAID after payment.
- [ ] "Could not complete" is only possible before the bill is sent.

**Warehouse / supervisor**
- [ ] Weighing flags a load when any material differs by more than 2%.
- [ ] Only supervisor/HQ see the Release button; only HQ can cancel a requirement or resolve a flagged load.
- [ ] A release larger than stock or remaining need is rejected with the stated message.
- [ ] The person who counted cash cannot verify it.

**HQ**
- [ ] Franchise picker scopes all reports; "all" works.
- [ ] Lead upload validations behave as in section 5; duplicate leads are reported.
- [ ] Rate changes, resolutions and cancellations appear in the activity log and cannot be edited.

**Security**
- [ ] `anon` cannot read any table or call any function.
- [ ] A user from franchise A cannot read franchise B data, even by calling the REST API directly.
- [ ] Weighings, releases, audit log and settlements cannot be edited or deleted.
- [ ] No service-role key in any front-end file; `bill_pdf_test_key` is NULL.

---

## 12. Open items (not part of "exactly the same", for the owner to decide)

- 61 TEST leads in the database should be cancelled before real use.
- The in-dashboard login forms (separate from the main launcher) still use the older spinner.
- Dark mode is not implemented.
- Real-device checks still pending: real logins with the email in the side panel, the live invoice badge after redeploy, and a real WhatsApp send.
