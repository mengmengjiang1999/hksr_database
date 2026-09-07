# local-knowledge-app Specification

## Purpose
TBD - created by archiving change m5-local-product. Update Purpose after archive.
## Requirements
### Requirement: Local-only default server
The application server MUST bind to `127.0.0.1` by default and SHALL require an explicit option to use another host.

#### Scenario: User starts the server without host options
- **WHEN** the `serve` command is run with defaults
- **THEN** Uvicorn listens only on the loopback interface

### Requirement: Grounded answer API
The API SHALL expose question answering with direct answer text, status, resolved intent and entities, ambiguity or partial-answer state, claim-level citations, context, retrieval confidence, generation outcome, and fallback metadata from the domain layer.

#### Scenario: Client posts a supported relation question
- **WHEN** `POST /api/ask` receives a non-empty relation question with sufficient official evidence
- **THEN** it returns a concise grounded answer and typed entity resolution without adding route-level facts

#### Scenario: Generation falls back
- **WHEN** optional model generation is unavailable or rejected
- **THEN** the same endpoint returns a validated deterministic result and identifies the fallback without exposing internal errors or secrets

### Requirement: Knowledge browsing APIs
The API SHALL expose evidence search, source details, entity details and approved relation cards.

#### Scenario: Client opens an entity
- **WHEN** `GET /api/entities/{id}` resolves an entity
- **THEN** it returns aliases and only default-visible evidence-backed relations

### Requirement: Explicit administrative sync
Synchronization MUST run only through an explicit administrative POST and SHALL report each executed stage and failure.

#### Scenario: Status is viewed
- **WHEN** a client calls a read-only status or knowledge endpoint
- **THEN** no source fetch, parse or index mutation is triggered

### Requirement: Local status visibility
The administrative status endpoint SHALL report source, document, chunk, index, entity, relation and stale-relation counts.

#### Scenario: Local database is initialized
- **WHEN** `GET /api/admin/status` is called
- **THEN** the response identifies the database and all pipeline counts

### Requirement: Evidence-first web interface
The local page MUST show answer status and place citations under their claims with expandable original text, context, source metadata and official links.

#### Scenario: Answer contains an explicit claim
- **WHEN** the browser renders the answer
- **THEN** the claim's own citations are visible without relying on a paragraph-level source list

### Requirement: Product regression coverage
The system MUST test API validation, grounded responses, safe relation visibility, status behavior and static application delivery.

#### Scenario: Local app test suite runs
- **WHEN** tests use a temporary initialized database
- **THEN** they exercise HTTP endpoints without accessing the external network

### Requirement: Read-only catalog metadata API
The API SHALL expose a catalog metadata endpoint containing source status totals and the available parsed source types, contexts, and versions needed by knowledge browsing clients.

#### Scenario: Client loads browser metadata
- **WHEN** `GET /api/catalog` is called
- **THEN** it returns deterministic JSON facets and processing counts without fetching, parsing, indexing, or otherwise mutating stored data

### Requirement: Browser API contract stability
Search results and source details MUST expose stable identifiers and traceability fields required by the browser independently of the configured persistence backend.

#### Scenario: Browser opens a search result
- **WHEN** a search result is returned and its `source_id` is used with `GET /api/sources/{id}`
- **THEN** the detail response identifies the same source and retains its official page URL and processing metadata

### Requirement: Identity-aware answer presentation
The private interface SHALL distinguish narrative identity, playable forms, official wording and player terminology while keeping citations attached to factual claims.

#### Scenario: User asks about a character SP form
- **WHEN** the answer contains a same-person conclusion and a separate playable-form distinction
- **THEN** both facts are displayed directly, player shorthand is visibly non-official, and official evidence remains expandable

### Requirement: Bounded interactive retrieval
The private application MUST prevent overlapping interactive retrieval from exhausting the service and MUST terminate the browser loading state after a finite request deadline.

#### Scenario: Retrieval capacity is already occupied
- **WHEN** another interactive retrieval request exceeds the configured concurrency capacity
- **THEN** the API returns a retryable busy response and the browser renders an actionable error instead of loading indefinitely
