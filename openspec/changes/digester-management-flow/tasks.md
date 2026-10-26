## 1. Trace and verify field management

- [x] 1.1 Map LSGD scope, assignments, visit completion, review, and sign-off to the field-management requirements; record code and test coverage for each scenario in `coverage-review.md`.
- [x] 1.2 Map expense policy, claim transitions, evidence, and monthly settlement to the field-management requirements; record code and test coverage for each scenario in `coverage-review.md`.
- [ ] 1.3 Implement only confirmed field-management gaps and add focused tests proving the required role boundaries and transitions.

## 2. Trace and verify franchise operations

- [x] 2.1 Map lead and presentation transitions to the franchise requirements; record code and test coverage for each scenario in `coverage-review.md`.
- [x] 2.2 Map sale, payment, cancellation, stock, and target behavior to the franchise requirements; record code and test coverage for each scenario in `coverage-review.md`.
- [x] 2.3 Implement only confirmed franchise gaps and add focused tests for atomicity, stock safety, and cross-franchise isolation; the review found no franchise rule gap.

## 3. Review end-to-end access and behavior

- [x] 3.1 Check each dashboard action against backend authorization so hidden controls are not the only access barrier; the backend rules enforce the reviewed role boundaries.
- [x] 3.2 Reconcile the KWD README with verified behavior and report unresolved review-stage policy in `coverage-review.md` without inventing new transitions.
