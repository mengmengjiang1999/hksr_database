## ADDED Requirements

### Requirement: Immutable full-corpus manifest
Every M10 evaluation MUST record a secret-free immutable manifest containing the backend, schema and index versions, source, document and eligible-evidence counts, disposition totals, stable-evidence-ID uniqueness, dataset version, retrieval configuration, and a deterministic corpus fingerprint.

#### Scenario: The accepted M7 corpus is evaluated
- **WHEN** the 7,845-source, 6,709-document, 20,291-evidence snapshot is selected for the M10 baseline
- **THEN** the report proves those counts, all 7,845 dispositions, zero unverified evidence, unique stable evidence IDs, and an unchanged fingerprint before scoring questions

### Requirement: Honest baseline separation
Historical reports produced from smaller corpora MUST remain labelled with their original fingerprints and counts and MUST NOT be presented as complete-corpus acceptance.

#### Scenario: The M9 56-of-60 report is referenced
- **WHEN** an M10 report compares against the 1,890-chunk M9 run
- **THEN** it labels that result as historical and reports M10 acceptance only from the frozen complete-corpus manifest

### Requirement: Versioned full question evaluation
The system SHALL run the same frozen 60-question dataset on SQLite and RDS and report per-case intent, resolved entities, expected and retrieved evidence, Top 5 result, direct-answer correctness, refusal, ambiguity, partial support, citations, and failure classification.

#### Scenario: One question fails
- **WHEN** a case does not meet its labelled expectation
- **THEN** the report assigns corpus gap, parse or chunk defect, entity-resolution error, intent error, ranking miss, answer error, citation error, backend mismatch, or expected ambiguity without silently changing the label

### Requirement: Quality acceptance gates
On the frozen eligible core set, Top 5 evidence recall MUST be at least 85%, direct-answer correctness MUST be at least 90% and no more than two percentage points below the frozen SQLite full-corpus baseline, every factual claim MUST have a resolvable supporting citation, and every labelled unanswerable question MUST refuse without factual claims.

#### Scenario: Metrics are evaluated for release
- **WHEN** the final RDS evaluation completes
- **THEN** acceptance fails if any hard threshold is missed, even when the aggregate question score appears acceptable

### Requirement: Failure-first tuning
The first SQLite and RDS full-corpus baselines MUST run before changing ranking weights, and remediation SHALL follow corpus, parsing, entity, version, retrieval, and answer-layer ownership before parameter tuning.

#### Scenario: A ranking miss is caused by absent evidence
- **WHEN** diagnostics show the expected official evidence is absent from the frozen corpus
- **THEN** the case remains a corpus or parsing defect and is not hidden by lowering the retrieval threshold or relabelling the expectation
