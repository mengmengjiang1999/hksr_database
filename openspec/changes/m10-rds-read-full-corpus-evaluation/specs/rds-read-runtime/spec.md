## ADDED Requirements

### Requirement: Backend-neutral read contract
The application SHALL execute every user-facing source, document, evidence, catalog, entity, narrative-identity, relation, retrieval, citation-context, and status read through one backend-neutral contract implemented by both SQLite and PostgreSQL.

#### Scenario: RDS backend serves the private application
- **WHEN** the application starts with the PostgreSQL read backend selected
- **THEN** every existing read-only HTTP endpoint retains its response fields and semantics without opening the SQLite evidence file

### Requirement: Complete PostgreSQL read schema
The PostgreSQL schema MUST contain the current eligible corpus, stable evidence identities, retrieval metadata and vectors, source dispositions, entity links, reviewed relations, narrative people, playable forms, and typed identity names required by the M8 and M9 read paths.

#### Scenario: Schema readiness is checked before cutover
- **WHEN** the RDS startup probe compares the deployed schema with the required application schema version
- **THEN** cutover is blocked if a required table, column, constraint, index dependency, corpus row set, or M9 identity record is absent

### Requirement: Stable cross-backend identities
Externally visible source and evidence identifiers MUST resolve consistently across SQLite and PostgreSQL, and comparisons SHALL use stable provider, external, document, chunk, entity, and identity keys rather than assuming independently generated row IDs are equivalent.

#### Scenario: A search result opens its source after cutover
- **WHEN** RDS search returns a result and the browser requests its `source_id`
- **THEN** the source detail resolves to the same provider and external source represented by the SQLite baseline and all citations retain the same stable evidence IDs

### Requirement: Read-only least-privilege sessions
The PostgreSQL runtime MUST use a dedicated credential that can read only the required `hksr` objects, SHALL open read-only transactions, and MUST NOT mutate evidence, metadata, ingestion state, schemas, roles, or unrelated databases.

#### Scenario: Runtime privileges are probed
- **WHEN** acceptance runs permitted reads and representative INSERT, UPDATE, DELETE, DDL, role, and unrelated-schema operations with the runtime credential
- **THEN** required reads succeed and every prohibited operation fails without changing RDS state

### Requirement: Bounded connection lifecycle
The RDS adapter MUST bound its connection count, connection and statement timeouts, acquisition wait, idle lifetime, and shutdown behavior, and SHALL expose secret-free health data for pool use and query timeouts.

#### Scenario: RDS resumes from an automatic pause
- **WHEN** initial connection establishment is delayed or unavailable
- **THEN** readiness remains false or returns a retryable bounded failure, no request waits indefinitely, and no DSN, host, database name, user name, or password is exposed

### Requirement: Explicit selection and fail-closed behavior
The active read backend MUST be selected by an explicit validated configuration value. A failed PostgreSQL startup or request MUST NOT silently answer from a stale SQLite copy; rollback requires an explicit operator change to the SQLite backend.

#### Scenario: RDS becomes unavailable after cutover
- **WHEN** the selected PostgreSQL backend cannot satisfy its bounded read or readiness probe
- **THEN** the service reports a retryable unavailable state and does not silently mix or substitute SQLite results

### Requirement: Read-only shadow comparison
Before cutover, the system SHALL support an operator-invoked shadow run that sends a fixed evaluation workload to both backends, compares normalized results, and does not affect the user response or mutate either corpus.

#### Scenario: SQLite and RDS disagree
- **WHEN** normalized source identities, evidence IDs, classifications, citations, or expected Top 5 evidence differ
- **THEN** the comparison report identifies the question and field-level mismatch and blocks the cutover gate

### Requirement: Reversible cutover
The PostgreSQL cutover MUST be reversible by configuration and service restart alone while the accepted SQLite snapshot is retained, and rollback MUST NOT delete data, reverse schema migrations, enable collection, or enable model generation.

#### Scenario: Rollback drill is performed
- **WHEN** the backend flag is restored to SQLite and the private service is restarted
- **THEN** readiness and the fixed smoke set pass using SQLite with the same API/UI contract
