# evidence-grounded-answering Specification

## Purpose
TBD - created by archiving change m3-evidence-grounded-qa. Update Purpose after archive.
## Requirements
### Requirement: Stable evidence identity
Every citation MUST use an evidence identifier that remains stable when unchanged source content is reparsed.

#### Scenario: Database rows are replaced during reparse
- **WHEN** the same source content is parsed into new SQLite row IDs
- **THEN** its evidence identifier remains based on source, document and content keys rather than row IDs

### Requirement: Retrieved-evidence boundary
A factual claim MUST cite one or more evidence items returned for the current question; evidence outside that candidate set MUST be rejected.

#### Scenario: Draft cites an arbitrary database chunk
- **WHEN** the cited evidence was not retrieved for the current question
- **THEN** the claim is removed with an `evidence_not_retrieved` reason

### Requirement: Explicit claim support
An `explicit` claim MUST be directly present in one cited official evidence item after safe text normalization.

#### Scenario: Draft adds remembered information
- **WHEN** claim text is absent from every cited evidence item
- **THEN** the claim is rejected as unsupported

### Requirement: Transparent inference
An `inferred` claim MUST cite at least two evidence items and MUST expose non-empty reasoning steps while clearly identifying the claim as inference.

#### Scenario: Inference has only one citation
- **WHEN** an inferred draft binds fewer than two evidence items
- **THEN** the claim is rejected or downgraded rather than presented as fact

### Requirement: Conflict preservation
A `conflicted` result MUST cite evidence from distinct sources or versions and MUST present the alternatives without silently selecting one.

#### Scenario: Official sources disagree
- **WHEN** a conflict draft binds distinct official source or version values
- **THEN** the answer is labelled conflicted and retains each cited alternative

### Requirement: Evidence insufficiency refusal
The system MUST return `uncertain` without factual claims when retrieval confidence is insufficient or no claim passes validation.

#### Scenario: Question is outside the local corpus
- **WHEN** no retrieved result reaches the configured confidence threshold
- **THEN** the system states that current official evidence is insufficient

### Requirement: Claim-level citations and context
Every accepted factual claim MUST list its own citations, and each citation SHALL expose source title, section, version, context, official URL and adjacent text context.

#### Scenario: Accepted claim is rendered
- **WHEN** a claim passes validation
- **THEN** its evidence can be inspected with provenance and neighbouring chunks

### Requirement: Repeatable grounding evaluation
The system MUST report citation coverage, unsupported-claim rejection and insufficient-evidence refusal from deterministic tests.

#### Scenario: Grounding suite runs
- **WHEN** supported, unsupported, inferred, conflicted and unanswerable cases are evaluated
- **THEN** results can be compared without an online model dependency
