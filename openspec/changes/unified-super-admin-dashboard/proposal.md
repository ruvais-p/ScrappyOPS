## Why

Business owners currently need to switch between the scrap collection HQ portal and the KWD Head Office module to understand purchases, customer sales, inventory, pipelines, product performance, and field expenses. A unified, read-only business intelligence page will make operational performance easier to compare across franchises while preserving the meaning and security boundaries of each business flow.

## What Changes

- Add a Super Admin dashboard that summarizes scrap collection and digester franchise operations in one view, with date range, business stream, and franchise filters.
- Route a separate, read-only Super Admin role from the shared login to its own dashboard entry, isolated from HQ operational controls.
- Show paid scrap purchases, collected weight, customer sales, sales collections and dues, and separate inventory views for raw materials and digester products.
- Add product performance by month and financial year, including quantity, sales value, realized average selling price, and configured list price where available.
- Show the distinct scrap pickup and digester sales pipelines, franchise-level performance, and available targets and delivery indicators.
- Show TA/DA requested, approved, and paid amounts by field staff and district; expose franchise-level TA/DA only when an explicit, valid staff-to-franchise mapping exists.
- Provide charts and business-flow views with clear definitions, units, and source periods so purchase outlay, sales value, cash collected, stock, and pipeline are not conflated.

## Capabilities

### New Capabilities
- `super-admin-business-intelligence`: Cross-stream, read-only business analytics for authorized Super Admin users.

### Modified Capabilities

## Impact

- Core HQ reporting and warehouse data: paid pickup bills, bill items, load weighings, and warehouse stock.
- KWD Head Office reporting: franchise sales, products, stock movements, targets, leads/opportunities, and field-day TA/DA claims and payments.
- HQ/Head Office navigation, access control, and reporting interfaces; likely requires aggregated read endpoints or equivalent reporting queries across the existing data sources.
- No existing operational workflows or records are changed by dashboard viewing.
