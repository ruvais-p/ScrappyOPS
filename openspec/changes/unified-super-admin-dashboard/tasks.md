## 1. Access and reporting foundation

- [x] 1.1 Add an explicit Super Admin authorization grant and enforce it on dashboard routes and report data; verify authorized access succeeds and other roles are denied at the server boundary.
- [x] 1.2 Define and document the shared report filters, India-local date handling, calendar months, and financial-year boundaries; verify report queries return the expected period labels at boundary dates.
- [x] 1.3 Add read-only aggregated reporting for scrap purchases, item rates, load weighings, and raw-material stock; verify totals reconcile to paid bills and warehouse source reports for a selected date range and franchise.
- [x] 1.4 Add read-only aggregated reporting for digester invoices, receipts, outstanding balances, product sales, franchise targets, product stock, deliveries, and distinct lead/opportunity pipelines; verify aggregates reconcile to source records and cancellation/payment rules.
- [x] 1.5 Add TA/DA summaries by TSO, period, and requested/approved/paid status with assigned district labels as context; verify each field-day claim is counted once and no unsupported district or franchise amount is inferred.
- [x] 1.6 Add a distinct Super Admin role and account provisioning command, and enforce that role on the reporting RPC.

## 2. Super Admin dashboard

- [x] 2.1 Add the Super Admin entry point and page shell with date range, business stream, and applicable franchise filters; verify filter changes update each supported report and display active scope.
- [x] 2.2 Add overview indicators and trend charts for scrap purchases, digester sales, receipts, dues, and inventory; verify labels, units, scopes, and periods distinguish purchase outlay, sales value, collections, raw-material kg, and product units.
- [x] 2.3 Add product performance views for month and financial year with quantity, sales value, realized average selling price, list price, and clearly labeled monthly averages; verify zero-sales products do not show a misleading realized price.
- [x] 2.4 Add separate franchise performance tables, pipeline stage charts, and scrap/digester flow diagrams; verify stage names and weighted pipeline calculations remain domain-specific.
- [x] 2.5 Add metric definitions and per-stream loading/error states; verify partial source failure is clearly identified and is not presented as a complete combined result.
- [x] 2.6 Route Super Admin through the shared login to its read-only dashboard shell, with role-appropriate sign-out and no HQ operational navigation.

## 3. Integration and release

- [ ] 3.1 Validate the dashboard against representative core HQ and KWD source records, including date boundaries, franchise filters, partial payments, stock, and TA/DA states; record reconciliation results.
- [ ] 3.2 Verify role-based access, responsive dashboard rendering, and navigation within the intended Head Office experience; confirm operational records remain unchanged when the dashboard is viewed.
- [x] 3.3 Document Super Admin grant provisioning, metric definitions, and the rollback switch; verify disabling the feature removes access without requiring operational data migration.
