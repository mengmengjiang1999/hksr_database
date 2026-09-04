## ADDED Requirements

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
