## Context

See `proposal.md` for motivation. The KWD module already has a PostgreSQL-backed query engine, Python write rules and scopes, action endpoints, server-rendered JavaScript screens, and focused tests. The README describes both staff monitoring and franchise operations, while `openspec/specs/` has no established capabilities.

## Goals / Non-Goals

**Goals:**

- Use the existing KWD data and role model as the source of truth for the acceptance contracts.
- Identify discrepancies between documented behavior, backend authorization and transitions, and the screens that expose those actions.
- Keep mutations transactional and retain the audit/history behavior already used by the module.

**Non-Goals:**

- Combine the staff-monitoring and franchise modules or create automatic conversion between their records.
- Replace the query engine, move data, or introduce a new frontend framework.
- Add roles or grant one role another role's privileges without a separately approved requirement.

## Decisions

- **Treat the README as the initial product contract, then verify it against code and tests.** The workflows are substantially implemented, so the change should result in code only for demonstrated mismatches; alternatives such as rewriting the modules would duplicate existing behavior and increase regression risk.
- **Keep staff and franchise capabilities as separate specs.** They share a product domain but have different roles, records, and lifecycles. Combining them would make access boundaries harder to review.
- **Preserve enforcement in backend rules and scopes.** Screens may guide users, but authorization and lifecycle checks must remain effective for direct API requests. Use the current Django/PostgreSQL mechanisms unless a concrete gap requires schema changes.
- **Add or update focused tests alongside each verified gap.** Existing KWD tests already exercise many transitions; extend those tests rather than creating an unrelated test harness.

## Risks / Trade-offs

- [The README may describe policy more broadly than current code or tests] → Resolve discrepancies against existing product requirements and document unresolved business decisions before changing observable behavior.
- [Broad role changes could expose network data] → Keep authorization checks and negative cross-scope scenarios in the acceptance review.
- [Some acceptance scenarios are already implemented] → Mark those as verified coverage; do not create redundant code changes.

## Migration Plan

No data migration is expected. If discovery finds a schema change necessary to satisfy an agreed requirement, add a reversible migration and document deployment and rollback steps in the implementation change before applying it.
