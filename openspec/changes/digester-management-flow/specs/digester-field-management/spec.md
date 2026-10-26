## Purpose

Defines the role-scoped field management lifecycle for kitchen waste digester opportunities, LSGD visits, review, and field expense claims.

## ADDED Requirements

### Requirement: LSGD and staff access is role scoped
The system SHALL allow Head Office to manage network LSGDs and assignments, Zonal Managers to manage records within their districts and teams, and Territory Sales Officers to work only with LSGDs and tasks within their assigned scope.

#### Scenario: Staff member attempts to access an out-of-scope LSGD
- **WHEN** a staff member requests an LSGD outside their permitted district, team, or assignment scope
- **THEN** the system SHALL deny the record and SHALL NOT disclose its details

#### Scenario: Head Office imports unassigned LSGDs
- **WHEN** Head Office imports a valid LSGD list
- **THEN** the system SHALL create the records atomically and leave them available for assignment to a Zonal Manager

### Requirement: Field visits have a verifiable lifecycle
The system SHALL let a Territory Sales Officer plan or start an LSGD visit, record a quick check-in, complete visit details within three days, and record follow-up actions. The system SHALL let the Zonal Manager review the visit and Head Office sign off a Zonal Manager-reviewed visit.

#### Scenario: Territory Sales Officer logs and completes a visit
- **WHEN** the officer checks in at an in-scope LSGD and completes the visit details within three days
- **THEN** the system SHALL retain the visit evidence and make the visit available for Zonal Manager review

#### Scenario: Zonal Manager verifies a complete visit
- **WHEN** the Zonal Manager reviews a complete visit in their scope
- **THEN** the system SHALL record the reviewer and decision and make an eligible visit available for Head Office sign-off

#### Scenario: Head Office signs off a reviewed visit
- **WHEN** Head Office signs off a visit reviewed by a Zonal Manager
- **THEN** the system SHALL record the sign-off actor and time and preserve the review history

### Requirement: Field expense claims require staged verification and settlement
The system SHALL calculate field-day and expense claims from the configured policy, retain supporting evidence, and move a claim through Territory Sales Officer submission, Zonal Manager verification, Head Office approval, and monthly payment. A monthly settlement SHALL be recorded at most once per staff account and month.

#### Scenario: Claim is submitted and reviewed in order
- **WHEN** a Territory Sales Officer submits a complete claim
- **THEN** the claim SHALL become available to the appropriate Zonal Manager and Head Office stages, with each decision attributed to its actor

#### Scenario: Head Office pays a monthly settlement
- **WHEN** Head Office settles an eligible staff account for a month
- **THEN** the system SHALL record one payment with its reference and prevent a duplicate settlement for that account and month

#### Scenario: Claim fails policy or evidence checks
- **WHEN** a submitted claim violates the configured expense policy or required evidence rules
- **THEN** the system SHALL reject the invalid transition with an actionable reason and SHALL preserve the claim history
