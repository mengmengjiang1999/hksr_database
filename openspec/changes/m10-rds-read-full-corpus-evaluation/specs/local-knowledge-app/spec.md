## MODIFIED Requirements

### Requirement: Browser API contract stability
Search results, source details, catalog metadata, entity details, relation cards, status, and grounded answers MUST expose the same fields, traceability, error semantics, and stable identities independently of the selected SQLite or PostgreSQL read backend.

#### Scenario: Browser opens an RDS search result
- **WHEN** a search result is returned by PostgreSQL and its `source_id` is used with `GET /api/sources/{id}`
- **THEN** the detail response identifies the same official source, retains its URL and processing metadata, and requires no backend-specific browser behavior

### Requirement: Bounded interactive retrieval
The private application MUST prevent overlapping interactive retrieval from exhausting the service, MUST bound database acquisition and statement execution, and MUST terminate the browser loading state after a finite request deadline on either backend.

#### Scenario: RDS retrieval capacity is occupied or waking
- **WHEN** a request cannot obtain capacity or finish within the configured deadline
- **THEN** the API returns a retryable busy or unavailable response and the browser renders an actionable error before 25 seconds instead of loading indefinitely

## ADDED Requirements

### Requirement: Secret-safe backend readiness
Application readiness and administrative status SHALL identify the selected backend, schema compatibility, snapshot fingerprint, pool state, and last bounded database error category without returning a DSN, host, database name, account name, password, or protected configuration.

#### Scenario: Operator checks status after RDS cutover
- **WHEN** the private status endpoint is called
- **THEN** it confirms RDS readiness and the accepted corpus fingerprint using only sanitized fields

### Requirement: Read endpoints remain side-effect free
All user-facing and status reads MUST use read-only backend operations and MUST NOT initialize schemas, rebuild indexes, update stale flags, write telemetry into the evidence database, trigger synchronization, or modify collection state.

#### Scenario: Read-only role serves the full API smoke set
- **WHEN** catalog, search, source, entity, relation, status, and ask endpoints are exercised using the RDS runtime role
- **THEN** every response succeeds without granting or attempting a database write
