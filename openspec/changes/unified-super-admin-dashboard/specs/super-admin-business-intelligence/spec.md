## Purpose

Provide authorized business administrators with one read-only view of performance across scrap collection and digester franchise operations, while keeping each stream's financial measures, inventory units, and workflow stages distinct.

## ADDED Requirements

### Requirement: Authorized access to cross-stream dashboard
The shared login SHALL route active users with the explicit Super Admin role and grant to a distinct, read-only dashboard entry. The system SHALL expose its underlying report data only to those users. Super Admin access SHALL NOT grant permission to create, update, or delete operational records or expose HQ operational navigation.

#### Scenario: Shared login routes Super Admin to its dashboard
- **WHEN** an active Super Admin submits valid credentials at the shared login
- **THEN** the system opens the read-only business intelligence dashboard

#### Scenario: Other roles use the Super Admin sign-in
- **WHEN** an HQ, KWD Head Office, franchise, driver, warehouse, or supervisor account submits valid credentials at the Super Admin sign-in
- **THEN** the system rejects Super Admin entry and does not open the dashboard

#### Scenario: Authorized administrator opens dashboard
- **WHEN** an authorized Super Admin opens the dashboard
- **THEN** the system shows the business streams and report data permitted for that account

#### Scenario: Unauthorized user requests dashboard data
- **WHEN** a user without Super Admin access requests the dashboard or its report data
- **THEN** the system denies the request regardless of client-side navigation or filter values

### Requirement: Filter business reports
The dashboard SHALL let an authorized user select a reporting date range and business stream, and SHALL provide franchise filtering for data that has a franchise association. Each displayed report SHALL identify its selected period and scope.

#### Scenario: Apply date and business filters
- **WHEN** the user selects a date range and one business stream
- **THEN** the dashboard updates the applicable measures to that period and stream and labels the active scope

#### Scenario: Show data without franchise association
- **WHEN** a report contains records that cannot be associated with a franchise
- **THEN** the dashboard presents those records in an unassigned or non-franchise group rather than attributing them to a franchise

### Requirement: Report scrap purchases and raw-material inventory
The dashboard SHALL report scrap purchase activity using paid pickup bills and their item lines, including purchase amount, collected weight, and average purchase rate per kg. It SHALL report raw-material inventory in weight units separately from digester product inventory in unit counts.

#### Scenario: View scrap purchase summary
- **WHEN** the user views a period's scrap purchase report
- **THEN** the dashboard shows paid bill count, collected kg, purchase amount, and weighted average purchase rate per kg for the selected scope

#### Scenario: View raw-material stock
- **WHEN** the user views scrap inventory
- **THEN** the dashboard shows current raw-material stock by item and franchise or warehouse, with valuation labeled as an estimate when based on current buy rates

### Requirement: Report digester sales, collections, and dues
The dashboard SHALL distinguish digester invoice sales value from customer payments received and unpaid balance. It SHALL use the available invoice and receipt data and identify the financial measure shown.

#### Scenario: View sales and collection totals
- **WHEN** the user views digester sales for a reporting period
- **THEN** the dashboard displays invoiced sales value, payments received during the selected period, and outstanding balance as separate measures

#### Scenario: Filter sales by franchise
- **WHEN** the user filters digester sales to one franchise
- **THEN** invoices, receipts, and outstanding amounts are limited to that franchise and the selected reporting scope

### Requirement: Report product performance over time
The dashboard SHALL report digester product sales by calendar month and financial year, including quantity sold, sales value, and realized average selling price. It SHALL show configured list price separately from realized selling price and SHALL label the averaging period used for any monthly average.

#### Scenario: Compare product sales periods
- **WHEN** the user views product performance for a month or financial year
- **THEN** the dashboard shows quantities and sales value for each product with realized average selling price calculated from sales value divided by quantity sold

#### Scenario: Product has no sales in period
- **WHEN** a product has no qualifying sales in the selected period
- **THEN** its quantity and value are shown as zero and realized average selling price is shown as unavailable rather than as a misleading zero price

### Requirement: Show separate sales pipelines and franchise performance
The dashboard SHALL present scrap pickup leads, digester franchise leads, and KWD public-sector opportunities as distinct pipelines with their own stage definitions. It SHALL distinguish unweighted expected value from probability-weighted pipeline value and SHALL show a franchise attribution only where the source record provides one.

#### Scenario: View pipeline by stage
- **WHEN** the user views pipeline analytics
- **THEN** each pipeline is grouped by its own stage labels and shows count, unweighted value where available, and weighted value where probability is available

#### Scenario: Compare franchise performance
- **WHEN** the user views franchise performance
- **THEN** the dashboard shows stream-appropriate measures per franchise, including scrap purchases and raw stock or digester sales, targets, product stock, and delivery status as applicable

### Requirement: Report TA/DA with valid attribution
The dashboard SHALL show TA/DA claim amounts by field staff, distinguishing requested, approved, and paid amounts, and SHALL display the staff member's assigned district labels as context. It SHALL NOT aggregate claim amounts by district unless a field-day-to-district relationship exists. It SHALL group TA/DA by franchise only when an explicit and valid staff-to-franchise relationship exists; otherwise the report SHALL preserve staff attribution without inferring a franchise.

#### Scenario: View TA/DA status
- **WHEN** an authorized user views field expense analytics
- **THEN** the dashboard shows requested, approved, and paid amounts and identifies the claim status and reporting period

#### Scenario: Field-day has no district or franchise relationship
- **WHEN** a TA/DA claim's staff member has no explicit franchise association
- **THEN** the claim is included once in the staff total, assigned district labels are shown only as context, and no district amount or franchise amount is inferred

### Requirement: Explain measures and business flows
The dashboard SHALL provide concise definitions, units, and period labels for its key measures and SHALL visualize the scrap acquisition flow separately from the digester sales flow. It SHALL NOT label a comparison of scrap purchase outlay and digester sales value as profit or margin without a supported material cost linkage.

#### Scenario: Interpret business metrics
- **WHEN** the user views a chart or summary measure
- **THEN** the dashboard identifies the measure, unit, period, and applicable calculation or definition

#### Scenario: View business flow diagrams
- **WHEN** the user views business flow analytics
- **THEN** scrap lead, pickup, payment, weighing, and inventory stages are shown separately from digester lead, sale, collection, delivery, and stock stages
