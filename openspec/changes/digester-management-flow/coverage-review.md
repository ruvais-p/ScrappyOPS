# Coverage review

This review maps the proposal scenarios to the existing implementation and tests. The backend test command could not run in this environment because PostgreSQL is unavailable; the named tests were inspected but are not reported as passing.

## Field management

| Behavior | Implementation | Existing test coverage |
|---|---|---|
| District and LSGD row scope | `backend/kwd/scope.py` (`can_see_lsgd`, `read`); `backend/kwd/rules/simple.py` (`Lsgds`, `Tasks`) | `backend/kwd/tests/test_engine.py` (`test_who_sees_which_lsgds`, `test_only_listed_people_write`); `backend/kwd/tests/test_visits.py` (`test_who_may_visit`, `test_tasks_done_only_by_a_visit_and_only_for_my_team`) |
| Visit check-in evidence, completion deadline, and immutable evidence | `backend/kwd/rules/visits.py` (`Visits.before_insert`, `before_update`) | `backend/kwd/tests/test_visits.py` (`test_every_fraud_flag`, `test_details_can_be_added_later_within_the_time_limits`, `test_evidence_cannot_be_edited_by_the_owner`) |
| ZM review and HO sign-off | `backend/kwd/rules/visits.py` (`Visits.before_update`) | `backend/kwd/tests/test_visits.py` (`test_zonal_manager_review_rules`, `test_a_manager_cannot_review_their_own_visit_head_office_does`, `test_head_office_sign_off`) |
| Follow-ups and opportunities | `backend/kwd/rules/simple.py` (`Followups`, `Opportunities`); `backend/kwd/scope.py` | `backend/kwd/tests/test_visits.py` (`test_followups`, `test_opportunity_rules`) |
| Claim calculation, evidence, staged review, and monthly settlement | `backend/kwd/rules/days.py` (`recalc_field_day`, `FieldDays`, `ExpenseItems`, `pay_month`) | `backend/kwd/tests/test_claims.py` (start/end, policy, evidence, approvals, monthly settlement, and `test_a_managers_own_request_goes_to_head_office`) |
| Network LSGD CSV import | `backend/kwd/static/kwd/js/pages/zm/zmlsgds.js`; write transaction in `backend/kwd/api.py` and `backend/kwd/engine.py` | Added `test_ignore_duplicate_upsert_preserves_existing_lsgd_and_bulk_writes_are_atomic` in `backend/kwd/tests/test_engine.py`; execution is pending a PostgreSQL test database |

**Policy requiring confirmation:** existing tests allow Head Office to sign off a detailed visit before a ZM review and to approve a ZM's own claim directly. The proposal currently says ZM review is mandatory before Head Office action.

## Franchise operations

| Behavior | Implementation | Existing test coverage |
|---|---|---|
| Franchise row scope and product permissions | `backend/kwd/scope.py` (`fr_can_see`, `read`); `backend/kwd/rules/franchise.py` (`FrFranchises`, `FrProducts`) | `backend/kwd/tests/test_franchise.py` (`test_products_and_people`) |
| Lead assignment, status transitions, and history | `backend/kwd/rules/franchise.py` (`FrLeads`) | `backend/kwd/tests/test_franchise.py` (`test_ho_hands_out_leads_and_the_franchisee_works_them`) |
| Presentation scheduling, completion, cancellation, and lead updates | `backend/kwd/rules/franchise.py` (`FrPresentations`) | `backend/kwd/tests/test_franchise.py` (`test_presentations`) |
| Sale recording, stock lock, line items, lead closure, payment, delivery, installation, and cancellation | `backend/kwd/rules/franchise.py` (`FrSales`, `record_sale`, `cancel_sale`, `add_stock_move`) | `backend/kwd/tests/test_franchise.py` (`test_record_sale_moves_stock_and_closes_the_lead`, `test_delivery_and_installation_follow_the_rules`, `test_head_office_cancels_and_flags_sales`) |
| Stock movement integrity and target management | `backend/kwd/rules/franchise.py` (`FrStockMoves`, `FrTargets`); `backend/kwd/scope.py` views | `backend/kwd/tests/test_franchise.py` (`test_stock_rules`, `test_targets_are_head_office_only`) |
| Cross-franchise read isolation | `backend/kwd/scope.py` (`fr_can_see`, franchise table readers and views) | `backend/kwd/tests/test_franchise.py` checks empty foreign-franchise reads across leads, sales, targets, and stock |

No additional franchise behavior gap was confirmed in this code review. The existing tests cover the proposed scenarios; no franchise rule rewrite is planned.
