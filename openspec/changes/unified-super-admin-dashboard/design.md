## Context

See `proposal.md` for the motivation and `specs/super-admin-business-intelligence/spec.md` for observable behavior. The current application keeps the data in two domains: core HQ reports paid scrap bills and warehouse stock; KWD Head Office reports digester franchise sales, product stock, leads/opportunities, and field expenses. KWD sales include invoice totals, amounts received, payment status, and receipt rows. KWD TA/DA is attached to TSO field days and claims; it has district/staff relationships but no franchise foreign key. Existing Head Office roles are distinct, and the codebase does not currently define a unified Super Admin role.

## Goals / Non-Goals

**Goals:**
- Provide a single, read-only analytics surface over the two existing business domains.
- Provide a distinct Super Admin role routed by the shared login to a dashboard isolated from HQ operational navigation and actions.
- Reuse each domain's authoritative data and authorization rules, with explicit cross-domain Super Admin authorization.
- Keep units, period definitions, source semantics, and business-flow stages visible and distinct.

**Non-Goals:**
- Merge the operational schemas or workflows for scrap collection and digester sales.
- Add or infer a staff-to-franchise relationship for TA/DA reporting.
- Treat combined scrap purchase outlay and digester sales as profit, margin, or a consolidated income statement.
- Replace the existing operational dashboards, invoice screens, or reporting tools.

## Decisions

1. **Build a read-only aggregation layer over existing sources.** Use domain-owned report queries/endpoints to aggregate core HQ and KWD data, and expose a dashboard-facing response model. Do not write a new duplicate analytics ledger or alter operational transaction flows. This keeps existing records authoritative and avoids coupling the domains' different schemas. A direct client-side fan-out to all raw tables was considered, but it would duplicate aggregation logic in the browser and make authorization and definitions harder to keep consistent.

2. **Create an explicit, separate Super Admin role and dashboard route.** The shared login routes Super Admin users to a read-only dashboard shell. An active profile must have the `super_admin` role and explicit grant before requesting reports. Existing HQ and KWD Head Office roles alone do not imply cross-domain access. Every report boundary checks authorization server-side; a client-only route guard cannot protect report data.

3. **Keep business streams and their measures separate.** Scrap acquisition reports use paid pickup bills, item weights, warehouse weighing, and raw-material stock. Digester sales reports use invoices, receipts, sales items, stock movements, and delivery records. Charts may be adjacent for comparison, but their labels and definitions must preserve differences in meaning and unit. Do not calculate combined profit from these sources without a supported cost-to-product linkage.

4. **Use explicit calendar and financial period rules.** Date filters use India-local business dates. Product performance supports calendar-month and financial-year views; financial year follows the existing KWD financial-year convention. A monthly average must state whether it is sales per elapsed month in the selected range or a full-year monthly average.

5. **Handle TA/DA at the strongest supported attribution level.** Aggregate claims by staff member, status, and period; show assigned districts as context only because field days do not have a district foreign key and a staff member may serve multiple districts. Show district or franchise subtotals only when an explicit relationship to the field day exists. Do not infer either grouping from a TSO's territory or a nearby digester franchise.

6. **Use separate flow diagrams and pipeline calculations.** Scrap pickup leads and KWD franchise leads/public-sector opportunities have different lifecycle stages. Show each lifecycle separately; probability-weight only opportunities with a defined probability and show the unweighted amount alongside it. Avoid one normalized funnel that implies stage equivalence.

## Risks / Trade-offs

- [Separate identity and permissions across the two domains may make Super Admin onboarding unclear] → Provide a distinct login, one Super Admin role, and a documented account provisioning flow; enforce the role server-side for every source.
- [Aggregating independent report sources can yield partial results when one domain is unavailable] → Return per-stream loading/error states and avoid presenting a partial result as a complete combined total.
- [Different business dates, financial periods, and payment semantics can make totals appear inconsistent] → Apply India-local dates consistently and label invoice value, receipts, outstanding balance, purchase amount, and pipeline distinctly.
- [Some historical TA/DA records cannot be assigned to a franchise] → Leave those records in staff/district totals and show unassigned amounts explicitly if a franchise grouping is available.
- [Large date ranges may make dashboard aggregation slow] → Use bounded date windows, database aggregation, and measured query performance; defer caching until observed usage justifies it.

## Migration Plan

1. Add the explicit Super Admin authorization path and read-only aggregate report access.
2. Add the dashboard navigation and analytics views, verifying both business domains and failure states independently.
3. Release behind the Super Admin permission and validate metric definitions against source records.
4. Roll back by removing the navigation/permission grant and disabling aggregate report access; no operational records require data migration or rollback.

## Open Questions

- Which current users should receive the initial Super Admin grant, and who will manage that grant? The dashboard contract assumes explicit authorization but leaves account assignment to release configuration.
- If franchise-wise TA/DA is later required, what authoritative relationship maps a TSO to a franchise and how should historical claims be assigned?
