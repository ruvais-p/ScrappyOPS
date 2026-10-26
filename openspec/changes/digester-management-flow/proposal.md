## Why

The KWD app already contains substantial field-sales and franchise workflows, but the repository has no OpenSpec requirements describing how those pieces fit together. That leaves role boundaries, lifecycle transitions, and handoffs dependent on code and the README, making future changes hard to review against the intended process.

## What Changes

- Establish role-based requirements for LSGD ownership, visit planning and logging, Zonal Manager verification, Head Office sign-off, and TA/DA claim settlement.
- Establish role-based requirements for franchise lead follow-up, presentations, sale recording, delivery and installation, stock movements, targets, and Head Office oversight.
- Verify the existing Django rules and screens against those requirements; implement only concrete gaps found during that review.
- Preserve the two management work areas as separate workflows. No automatic conversion of staff visits or opportunities into franchise leads is specified by the current README.

## Capabilities

### New Capabilities

- `digester-field-management`: LSGD assignment, visits, follow-ups, review, sign-off, and field expense claims.
- `digester-franchise-operations`: franchise leads, presentations, sales, inventory, targets, and Head Office monitoring.

### Modified Capabilities

None. The repository currently has no published OpenSpec capabilities.

## Impact

The change covers `backend/kwd/rules/`, `backend/kwd/scope.py`, `backend/kwd/api.py`, KWD management screens under `backend/kwd/static/kwd/js/pages/`, and their tests. The README-described behavior is largely implemented already; the proposal first makes that behavior explicit, then limits code changes to verified discrepancies. No new dependency or data migration is assumed unless discovery proves one necessary.
