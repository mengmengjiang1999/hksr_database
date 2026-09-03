# Cloud Database Validation

## Purpose

Define the reproducible, secret-safe migration and validation contract for the
private mainland-China PostgreSQL deployment and its retained ECS application
environment.

## Requirements

### Requirement: Sanitized environment discovery
The validator MUST record database engine, major and minor version, extension availability, connection security, selected capacity bounds, and storage observations without persisting credentials, endpoints, account names, provider resource identifiers, or access tokens.

#### Scenario: Environment report is generated
- **WHEN** an operator runs discovery against the M6B database
- **THEN** the machine-readable report contains compatibility facts and no configured secret or prohibited identifier

### Requirement: Required retrieval extensions
The cloud database MUST support creation and use of `vector`, and the validator SHALL report creation results for `pg_jieba`, `zhparser`, and `pg_bigm`, including any required preload configuration.

#### Scenario: Extensions are probed
- **WHEN** the extension validation command runs with mutation explicitly enabled
- **THEN** it executes a functional vector query and records an explicit supported, unavailable, or configuration-required result for every Chinese retrieval candidate

### Requirement: Idempotent evidence schema
PostgreSQL migrations MUST be repeatable and SHALL preserve stable evidence identifiers derived from source, document, and content keys rather than database row identifiers.

#### Scenario: Unchanged content is imported twice
- **WHEN** the same source content is migrated or upserted more than once
- **THEN** it retains one stable evidence identity and does not duplicate the current evidence row

### Requirement: Synthetic validation isolation
Scale fixtures MUST be deterministic, explicitly marked synthetic, scoped to a unique run identifier, and excluded from official evidence queries.

#### Scenario: Benchmark fixtures coexist with application data
- **WHEN** the application executes a default evidence query during a validation run
- **THEN** no synthetic validation chunk is eligible as factual evidence

### Requirement: Real official-evidence migration
The validator MUST import the currently collected official SQLite corpus into PostgreSQL without manufacturing benchmark evidence, SHALL preserve source provenance and stable evidence identifiers, and MUST reject rows marked synthetic.

#### Scenario: Current official corpus is imported
- **WHEN** the real-evidence migration completes
- **THEN** PostgreSQL source, document, and chunk counts match the eligible SQLite source data and every imported chunk remains reachable through its stable evidence identifier

#### Scenario: The same corpus is imported twice
- **WHEN** an operator repeats the real-evidence import without changing the SQLite source
- **THEN** no source, document, chunk, entity, relation, or evidence binding is duplicated

### Requirement: Stable incremental updates
Incremental PostgreSQL writes MUST NOT change the evidence identifier of unchanged chunks and MUST invalidate or replace only content whose stable source content key changed.

#### Scenario: One document changes
- **WHEN** an update changes one document while leaving another unchanged
- **THEN** unchanged chunks retain their evidence identifiers and changed chunks receive deterministically updated identities

### Requirement: Private least-privilege execution
Cloud validation MUST use private RDS connectivity from the same VPC, SHALL use a dedicated ingestion role for real-evidence writes, and SHALL use a runtime role without instance administration, role administration, unrelated schema privileges, or production evidence write privileges.

#### Scenario: Runtime credential is inspected
- **WHEN** the security probe runs as the application role
- **THEN** official evidence reads succeed while production writes, role creation, database creation, and unrelated schema mutation fail

### Requirement: Private cloud application execution
M6B MUST deploy the current application revision on the retained same-VPC ECS host and SHALL verify that it can read the migrated official corpus through the private RDS connection without publishing an Internet-facing service.

#### Scenario: Cloud application smoke test is reviewed
- **WHEN** the M6B report is finalized
- **THEN** the application health and read-only database probes succeed on ECS and the report omits secrets, endpoints, usernames, and provider resource identifiers

### Requirement: Cost and cleanup guardrails
The validation workflow MUST keep the RDS maximum at 4 RCU, SHALL retain automatic pause, and MUST identify every retained resource and imported real-data batch for explicit review.

#### Scenario: Validation finishes
- **WHEN** the final audit runs
- **THEN** it reports the RCU cap, automatic-pause state, remaining temporary resources, synthetic row count of zero, imported official row counts, and procurement-time price observation
