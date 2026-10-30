# Purchase / warehouse approval branch review

Reviewed `63acac9` against its parent `dff6c4a` (41 changed files). Earlier merged features were consulted where the new code depends on them; this is not an audit of every historical commit.

## Coverage

| Area | Files reviewed | Checks |
| --- | --- | --- |
| Scrap billing | `core/models.py`, `core/services/billing.py`, `core/services/tax_invoice.py`, `core/api/views.py`, `scrappy/urls.py`, core migrations `0007` and `0008`, `core/tests/test_billing.py` | Role/franchise isolation, invoice numbering, stock checks and locks, payment/cancellation, PDF access, numeric precision, historical details and schema constraints. |
| Warehouse dispatch | `core/services/dispatch.py`, `core/tests/test_dispatch.py`, `dashboards/warehouse/index.html` | Requested and requestless lines, mixed loads, reserved stock, supervisor approval, resubmission, price visibility and billing controls. |
| HQ dashboard | `dashboards/hq/index.html` | Billing RPC contracts, buyer management, invoice actions, stock display, HSN/GST editing and downloads. |
| Franchise API/data | `kwd/api.py`, `engine.py`, `schema.py`, `scope.py`, `rules/__init__.py`, `rules/franchise.py`, `urls.py`, migrations `0008` and `0009` | Category primary keys and permissions, own-lead ownership, product validation, sales/stock transactions, tax-inclusive prices and PDF authorization. |
| Franchise PDF | `kwd/invoice_pdf.py` | Authorization at the caller, escaped text, file naming, item/tax totals and cancelled-invoice display. |
| Shared frontend | `kwd/static/kwd/js/app.js`, `core.js`, `fr.js`, `kwd/templates/kwd/app.html` | Module integration, authenticated download flow and target aggregation. |
| Franchise pages | `pages/fr/app.js`, `home.js`, `leads.js`, `parts.js` | Own-lead creation/editing, widgets, product selection, GST price mode, sales payloads, PDF downloads and target display. |
| Head Office pages | `pages/ho/fr/app.js`, `invoices.js`, `leads.js`, `sales.js`, `stock.js`, `targets.js` | Filtering, billing actions, product/category creation, target saving, legacy targets and price edits. |
| Tests/docs | `kwd/tests/test_franchise.py`, `test_import.py`, backend and KWD READMEs, `docs_developer_handover.md` | Coverage of new behavior, compatibility with old import schemas and consistency with the implemented workflow. |

Paths beginning with `core/`, `kwd/`, or `scrappy/` are under `backend/`. Frontend `pages/` paths are under `backend/kwd/static/kwd/js/`.

## Corrections made

1. **Issued scrap invoices changed after master-data edits.** Store seller/buyer identity and material names on issue, and use those snapshots in PDFs and invoice listings. A new migration backfills existing rows.
2. **Database rounding could disagree with invoice totals and reserved stock.** Reject excess precision and out-of-range values before calculating or saving weights, rates, GST and totals.
3. **Malformed requests could fail with server errors or coerce unintended IDs.** Validate invoice-download payloads and dispatch lines; normalize HQ franchise IDs and reject nonexistent/inactive requestless-load franchises. A missing own-lead franchise now produces a permission error.
4. **Product edits bypassed tax validation.** Validate edited HSN/GST and finite, non-negative prices, including product creation. Handle a missing HSN safely in the price editor.
5. **GST-inclusive bulk sales drifted from their line totals.** Retain Decimal division precision instead of rounding the pre-tax unit price to six places. Reject fractional unit quantities and non-finite prices, GST and payments.
6. **Legacy overall targets overrode product targets.** Choose targets per franchise, respect explicit zero product targets, suppress obsolete value targets, and remove the legacy overall row after saving product targets. Do not rewrite hidden inactive-product targets. Reject fractional target units and show units rather than currency in the home-page unit comparison.

## Validation

- Complete backend suite: **138 tests passed**, using isolated PostgreSQL 16 and the repository's declared dependencies.
- After the final invoice-list and product-validation adjustments, all **35 focused backend tests passed** again.
- Added coverage includes invoice identity changes/backfill, numeric precision, malformed PDF/load input, requestless-load corrections, concurrent HQ sales, product validation and bulk GST calculations.
- Frontend regression checks: **3 passed** (`node backend/kwd/tests/test_achievement.mjs`), including mixed legacy/product targets, zero targets and clearing saved targets.
- Python syntax and all 15 changed JavaScript modules/inline scripts passed syntax checks; `git diff --check` passed.
- Model/migration consistency checked with `makemigrations --check --dry-run`.

## Security follow-up

The branch's new invoice and dispatch APIs now reject malformed resource IDs and filter values before database lookup. Buyer active state must be a JSON boolean; buyer/franchise billing text is bounded, and invoice and dispatch line lists are capped at 100. This prevents invalid requests from turning into server errors and limits the work a single request can force. Role and franchise checks remain on the server. The focused security suite passed 36 tests, followed by the billing tests after filter validation was added.

## Deployment and limits

Run migrations before serving the updated application. Existing scrap invoice identities are frozen using details available at migration time; the database does not contain older versions to reconstruct.

Tests ran locally on Python 3.10/PostgreSQL 16. Browser end-to-end interaction and the production Docker/Python 3.12 environment were not exercised. KWD PDF company/product details still follow the existing KWD print behavior; the new immutable identity snapshots apply to scrap billing.

The untracked `cred` file was neither read nor changed. No changes were committed, pushed or deployed.
