## ADDED Requirements

### Requirement: Runtime schema and index audit
Cloud validation MUST compare the deployed RDS objects with the application read contract, including M9 identity data, eligible-evidence filters, stable keys, required constraints, and required indexes.

#### Scenario: Migration is ready for application reads
- **WHEN** the runtime schema audit completes
- **THEN** it reports every required object and index version without exposing a credential, endpoint, account name, or provider resource identifier

### Requirement: Production read-role verification
The cloud acceptance workflow SHALL test the actual application read role from the same-VPC ECS and MUST prove both required query access and denied production mutations.

#### Scenario: Application role validation runs on ECS
- **WHEN** the role executes the fixed privilege matrix
- **THEN** all application reads pass while evidence writes, ingestion-state writes, schema changes, role changes, and unrelated-schema access fail

### Requirement: Cutover and rollback audit
Cloud validation MUST record backend configuration, readiness, normalized shadow comparison, active-service smoke results, and a successful SQLite rollback drill without recording protected configuration values.

#### Scenario: Final RDS cutover is accepted
- **WHEN** the service is switched to RDS and then temporarily rolled back in the drill
- **THEN** both transitions pass their smoke gates and the report contains no secret or private endpoint
