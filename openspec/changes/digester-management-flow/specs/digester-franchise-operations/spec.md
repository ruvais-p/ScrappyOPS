## Purpose

Defines the Head Office and franchisee workflow for managing digester leads, presentations, sales, delivery, inventory, and targets.

## ADDED Requirements

### Requirement: Franchise leads are assigned and advanced by the responsible role
The system SHALL let Head Office assign leads to a franchisee and SHALL restrict franchisees to their own leads. Franchisees SHALL advance a lead through permitted contact, presentation, negotiation, won, or lost outcomes; a sale SHALL close a lead as won, and a closed won lead SHALL NOT be reopened.

#### Scenario: Head Office assigns a lead
- **WHEN** Head Office assigns a lead to a franchisee
- **THEN** the system SHALL attribute the assignment and expose the lead only to Head Office and that franchisee

#### Scenario: Franchisee records a lost outcome
- **WHEN** a franchisee marks an open lead as lost
- **THEN** the system SHALL require a reason and retain the status change in lead history

#### Scenario: Franchisee tries to mark a lead won without a sale
- **WHEN** a franchisee attempts to set a lead directly to won
- **THEN** the system SHALL reject the change and require the sale workflow

### Requirement: Presentations are scheduled and completed with evidence
The system SHALL allow a franchisee to schedule a presentation for its own business and lead, reschedule it with a recorded count, and complete or cancel it with the required outcome or reason. Completed presentations SHALL have a bounded detail-correction window.

#### Scenario: Franchisee completes a presentation
- **WHEN** the presentation date is eligible and the franchisee records an outcome and attendee count
- **THEN** the system SHALL mark it complete and update the related lead to the appropriate next stage

#### Scenario: Franchisee cancels a presentation
- **WHEN** the franchisee cancels a scheduled presentation
- **THEN** the system SHALL require a meaningful cancellation reason and prevent later edits to the cancelled appointment

### Requirement: Sales update financial and inventory records atomically
The system SHALL let an active franchisee record a sale using active products, positive quantities, valid customer details, and available stock. Recording a sale SHALL create its invoice details, reduce stock, update payment status, and close an associated lead in one transaction. Only Head Office SHALL cancel a sale; cancellation SHALL restore stock and preserve the reason and history.

#### Scenario: Franchisee records a sale with available stock
- **WHEN** a franchisee records a valid sale with sufficient stock
- **THEN** the system SHALL persist the sale and line items, update on-hand stock, and close its associated lead atomically

#### Scenario: Concurrent or oversized sale would overdraw stock
- **WHEN** a sale requests more stock than remains available
- **THEN** the system SHALL reject the sale without leaving a partial sale, invoice, lead update, or stock movement

#### Scenario: Head Office cancels a sale
- **WHEN** Head Office cancels an active sale with a valid reason
- **THEN** the system SHALL mark it cancelled, restore each sold quantity, and exclude it from active sales totals

### Requirement: Franchise stock and targets are auditable and scoped
The system SHALL maintain stock as a movement history, prevent movements from reducing stock below zero, and expose each franchisee only its own inventory and targets. Head Office SHALL manage products, stock supplied to franchisees, and monthly targets, and SHALL be able to review franchise performance across the network.

#### Scenario: Franchisee reports a stock adjustment
- **WHEN** a franchisee records damage, a return, or a count adjustment
- **THEN** the system SHALL require a note, record the responsible actor, and update stock without allowing a negative balance

#### Scenario: Head Office sets a monthly target
- **WHEN** Head Office saves a valid franchise target for a month
- **THEN** the system SHALL retain the setter and update time and show achievement from eligible recorded sales

#### Scenario: Franchisee requests another franchise's data
- **WHEN** a franchisee queries another franchisee's sales, stock, leads, or targets
- **THEN** the system SHALL return no out-of-scope rows
