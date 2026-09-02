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
The API SHALL expose question answering with status, claim-level citations, context and retrieval confidence from the M3 domain layer.

#### Scenario: Client posts a supported question
- **WHEN** `POST /api/ask` receives a non-empty question
- **THEN** it returns a grounded result without adding route-level facts

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
