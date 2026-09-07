# evidence-backed-relations Specification

## Purpose
TBD - created by archiving change m4-evidence-backed-relations. Update Purpose after archive.
## Requirements
### Requirement: Evidence-bound one-hop relations
Every approved relation MUST bind one or more current stable evidence IDs and identify its subject, predicate, object, evidence level and review status.

#### Scenario: Approved relation is imported
- **WHEN** a curated explicit relation resolves to valid entities and evidence
- **THEN** the relation is stored with its evidence bindings and approved status

### Requirement: Explicit relation validation
An explicit relation MUST have evidence linked to both its subject and object entities.

#### Scenario: Evidence mentions only one endpoint
- **WHEN** an explicit relation selector resolves to a chunk without both entities
- **THEN** the import rejects the relation instead of publishing it

### Requirement: Inferred relation transparency
An inferred relation MUST bind at least two evidence items and MUST include a non-empty reasoning explanation.

#### Scenario: Inferred relation lacks reasoning
- **WHEN** a curated inferred relation has no reasoning text
- **THEN** it is rejected or kept non-public

### Requirement: Co-occurrence remains a candidate
Entity co-occurrence MUST create only pending candidate relations and MUST NOT become an approved semantic relation automatically.

#### Scenario: Two entities share a chunk
- **WHEN** candidate discovery finds both entities in one evidence item
- **THEN** it records a `co_occurs_with` pending candidate hidden from default results

### Requirement: Reviewable visibility
Default entity relation queries MUST return only approved relations with valid evidence; callers MAY explicitly request pending candidates.

#### Scenario: Player requests an entity card
- **WHEN** no administrative candidate flag is provided
- **THEN** rejected, pending and stale relations are absent

### Requirement: Evidence invalidation audit
The system SHALL identify relations whose bound evidence IDs no longer exist after source or chunk updates.

#### Scenario: Source content changes
- **WHEN** a relation references an evidence ID absent from the current corpus
- **THEN** the audit marks that relation stale and default queries hide it

### Requirement: Relation evidence cards
Each visible relation SHALL expose subject and object types, direction, evidence level, reasoning when applicable, and inspectable official citations.

#### Scenario: Approved relation is queried
- **WHEN** a user requests relations for either endpoint
- **THEN** the response includes direction and full citation provenance

### Requirement: Typed identity and form predicates
The controlled relation catalog SHALL support typed `playable_form_of`, `same_narrative_identity`, and `alternate_playable_form` predicates in addition to existing world relations.

#### Scenario: Alternate playable form is approved
- **WHEN** official evidence establishes that `姬子·启行` is a distinct playable form of the narrative person `姬子`
- **THEN** the relation is stored with typed endpoints, direction, evidence and review status

### Requirement: Alias does not prove form identity
Alias matching or name similarity alone MUST NOT automatically approve a playable-form or same-narrative-identity relation.

#### Scenario: Similar names co-occur
- **WHEN** two names share tokens or appear in one chunk without an explicit identity link
- **THEN** they remain separate or pending and are not shown as the same person in factual answers
