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
The system SHALL run the same frozen 60-question dataset on SQLite and RDS and report per-case intent, resolved entities, expected and retrieved evidence, Top 5 result, direct-answer correctness, refusal, ambiguity, partial support, citations, latency, and failure classification.

#### Scenario: One question fails
- **WHEN** a case does not meet its labelled expectation
- **THEN** the report assigns corpus gap, parse or chunk defect, entity-resolution error, intent error, ranking miss, answer error, citation error, backend mismatch, or expected ambiguity without silently changing the label

### Requirement: Quality acceptance gates
On the frozen eligible core set, Top 5 evidence recall MUST be at least 85%, direct-answer correctness MUST be at least 90% and no more than two percentage points below the frozen SQLite full-corpus baseline, every factual claim MUST have a resolvable supporting citation, and every labelled unanswerable question MUST refuse without factual claims.

#### Scenario: Metrics are evaluated for release
- **WHEN** the final RDS evaluation completes
- **THEN** acceptance fails if any hard threshold is missed, even when the aggregate question score appears acceptable

### Requirement: Failure-first tuning
The first SQLite and RDS full-corpus baselines MUST run before adding retrieval indexes, changing ranking weights, or changing capacity, and remediation SHALL follow corpus, parsing, entity, version, retrieval, and answer-layer ownership before parameter tuning.

#### Scenario: A ranking miss is caused by absent evidence
- **WHEN** diagnostics show the expected official evidence is absent from the frozen corpus
- **THEN** the case remains a corpus or parsing defect and is not hidden by lowering the retrieval threshold or relabelling the expectation

### Requirement: Reproducible performance profile
Performance acceptance MUST use a versioned workload and record cold and warm runs separately, at least 30 measured runs per endpoint class after warm-up, concurrency levels 1 and 2, P50 and P95 latency, timeouts, errors, peak process RSS, per-request RSS delta, pool occupancy, database sessions, and query-plan evidence.

#### Scenario: Warm private workload is accepted
- **WHEN** search, source detail, catalog, entity, relation, and ask workloads run against RDS
- **THEN** warm search P95 is at most 5 seconds, warm ask P95 is at most 8 seconds, all requests finish or fail actionably before the 25-second browser deadline, peak process RSS remains below 1 GiB, and per-request RSS growth remains below 256 MiB

### Requirement: Serverless wake behavior
RDS automatic-pause wake time MUST be measured outside warm latency percentiles and SHALL produce bounded readiness or retry behavior rather than a hanging browser request.

#### Scenario: A cold database exceeds the interactive budget
- **WHEN** RDS wake-up cannot complete within the configured connection and request deadlines
- **THEN** the API returns a retryable unavailable response before 25 seconds and the UI exits its loading state with an actionable message

### Requirement: Cost and capacity evidence
The final report MUST record the observation window, request volume, RDS capacity settings, automatic-pause state, connection usage, provider-reported consumption and cost using sanitized values, and MUST NOT raise the 4-RCU cap or disable automatic pause within M10 without separate approval.

#### Scenario: Baseline performance is insufficient
- **WHEN** a latency or concurrency gate fails at the current RDS settings
- **THEN** the plan first records query and index evidence and does not treat capacity expansion as an automatic remediation
