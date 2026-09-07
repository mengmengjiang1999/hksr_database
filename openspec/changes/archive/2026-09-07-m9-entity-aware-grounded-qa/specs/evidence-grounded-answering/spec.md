## ADDED Requirements

### Requirement: Direct intent-aware answer
The grounded answer layer SHALL answer the detected question intent directly before presenting supporting excerpts and related knowledge.

#### Scenario: Two playable forms share one narrative identity
- **WHEN** validated entity links establish that two independently selectable forms belong to one narrative person
- **THEN** the answer states the gameplay distinction and narrative identity in concise language with claim-level citations

### Requirement: Partial-answer transparency
When only part of a multi-part question is supported, the system MUST separate supported claims from unsupported parts instead of completing the answer from model memory.

#### Scenario: Narrative identity is supported but release reason is not
- **WHEN** evidence proves two forms are the same person but does not explain why the new form was released
- **THEN** the answer states the supported identity and explicitly marks the release-reason portion as unconfirmed

### Requirement: Versioned real-question evaluation
The system MUST evaluate direct-answer correctness, evidence recall, citation coverage, unsupported-claim rejection, ambiguity behavior, and refusal accuracy on a versioned real-question set.

#### Scenario: Corpus coverage grows during M7
- **WHEN** the same evaluation set runs against a later corpus snapshot
- **THEN** the report identifies the corpus snapshot and supports comparison without changing expected answers silently
