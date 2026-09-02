# cloud-capacity-planning Specification

## Purpose
TBD - created by archiving change m6a-cloud-capacity-validation. Update Purpose after archive.
## Requirements
### Requirement: Reproducible measured baseline
The system SHALL measure source, document, chunk, character, vector, raw-object and SQLite storage counts from a supplied local dataset without network access.

#### Scenario: Operator audits the current sample
- **WHEN** the capacity command receives a database and raw-object directory
- **THEN** it emits machine-readable measured values derived from those inputs

### Requirement: Explicit projection assumptions
The system MUST separate measured values from projected corpus values and SHALL record target counts, vector dimensions, byte-width and index multiplier.

#### Scenario: Projection is reviewed
- **WHEN** a reviewer opens the report
- **THEN** every projected byte count can be reproduced from recorded assumptions

### Requirement: Multiple capacity scenarios
The system SHALL model 10,000, 50,000, 100,000 and 1,000,000 chunk scenarios for dense vectors and planned indexes.

#### Scenario: Architecture threshold is evaluated
- **WHEN** projected chunks remain at or below 100,000
- **THEN** PostgreSQL with pgvector remains the default candidate unless performance evidence rejects it

### Requirement: Mainland China storage decision
The M6A report MUST define a mainland China deployment baseline that separates immutable source objects from relational facts and rebuildable indexes.

#### Scenario: Cloud proof of concept is prepared
- **WHEN** M6B begins procurement planning
- **THEN** the report identifies required RDS, OSS, network, backup and extension acceptance checks

### Requirement: Evidence and uncertainty labels
The report MUST distinguish local measurements, official-directory observations, formula-based estimates and unverified procurement values.

#### Scenario: Dynamic cloud price is unavailable
- **WHEN** a price depends on region, contract or current discount
- **THEN** the report records the billing dimension and requires a procurement-date official quote instead of inventing a fixed price

### Requirement: No cloud mutation
M6A SHALL NOT create cloud resources or upload source content.

#### Scenario: Capacity validation runs
- **WHEN** the audit and tests complete
- **THEN** only local report artifacts are changed
