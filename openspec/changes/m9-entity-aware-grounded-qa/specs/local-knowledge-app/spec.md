## MODIFIED Requirements

### Requirement: Grounded answer API
The API SHALL expose question answering with direct answer text, status, resolved intent and entities, ambiguity or partial-answer state, claim-level citations, context, retrieval confidence, generation outcome, and fallback metadata from the domain layer.

#### Scenario: Client posts a supported relation question
- **WHEN** `POST /api/ask` receives a non-empty relation question with sufficient official evidence
- **THEN** it returns a concise grounded answer and typed entity resolution without adding route-level facts

#### Scenario: Generation falls back
- **WHEN** optional model generation is unavailable or rejected
- **THEN** the same endpoint returns a validated deterministic result and identifies the fallback without exposing internal errors or secrets

## ADDED Requirements

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
