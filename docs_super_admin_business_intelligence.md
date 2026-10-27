# Super Admin business intelligence

The `/login/` front door routes an active Super Admin profile to the read-only dashboard at `/super-admin/`. It accepts only the `super_admin` role with the explicit `is_super_admin` grant. The reporting RPC repeats this authorization check, so hiding dashboard navigation is not the security boundary. Super Admin accounts cannot use HQ operational actions.

## Grant or revoke access

Run from `backend/` after applying migrations to create a separate account (the password is entered interactively):

```sh
python manage.py migrate
python manage.py create_super_admin --email admin@example.com --name "Business Administrator"
```

To promote an existing active HQ login instead, use:

```sh
python manage.py set_super_admin admin@example.com grant
```

That promotion changes its role to Super Admin. Return it to the HQ role with `python manage.py set_super_admin admin@example.com revoke`. KWD Head Office, franchise, driver, and warehouse roles do not receive access by virtue of those roles.

For local development only, sign in at `http://127.0.0.1:8000/login/` with `superadmin@scrappy.test` / `Scrappy#2026`. The portal routes the account to `/super-admin/`.

## Metric definitions

- **Scrap purchases:** paid pickup bills in the selected India-local date range. Average purchase rate is total paid amount divided by billed kg.
- **Weighing reconciliation:** non-superseded load weighings in the selected India-local date range; billed and warehouse weights are shown separately.
- **Raw-material inventory:** current warehouse stock in kg. Estimated value multiplies that stock by the current buy rate; it is not historical cost accounting.
- **Digester sales:** active invoices issued in the selected date range. Customer receipts use receipt dates in the selected range. Outstanding is the current balance on active invoices issued in that range.
- **Product realized average price:** active sale line value divided by quantity sold. Products with no sales have no realized price.
- **Monthly average sales:** selected-period product sales divided by the number of calendar months touched by the date range.
- **Financial year:** April through March. Quick filters select the current financial year-to-date or the previous complete financial year.
- **Inventory units:** scrap inventory is kg; digester inventory is product units. They are not added together.
- **Pipelines:** scrap pickup leads, digester franchise leads, and KWD public-sector opportunities use separate stages. Opportunity weighted value is expected value multiplied by probability; franchise leads do not have a probability-weighted value.
- **TA/DA:** claims are grouped once per TSO, with assigned districts displayed as context. Field days have no district or franchise foreign key, so no district or franchise amount is inferred.

The dashboard does not calculate profit by comparing scrap purchase outlay with digester sales. The current data does not link acquired materials to digester product cost.

## Rollback

Revoke access by demoting the account with `set_super_admin ... revoke` or deactivating it. The feature can be removed by reverting the dashboard/API change and adding a later migration to drop the role and profile flag. No operational business records are created or modified by dashboard reads.
