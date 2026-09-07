## ADDED Requirements

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
