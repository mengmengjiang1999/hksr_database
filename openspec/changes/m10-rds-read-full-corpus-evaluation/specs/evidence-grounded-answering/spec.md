## MODIFIED Requirements

### Requirement: Versioned real-question evaluation
The system MUST evaluate direct-answer correctness, evidence recall, citation coverage, unsupported-claim rejection, ambiguity behavior, and refusal accuracy on a versioned real-question set, and each report MUST bind those results to an immutable corpus fingerprint and selected read backend.

#### Scenario: Complete RDS corpus is evaluated
- **WHEN** the frozen 60-question set runs against the accepted RDS snapshot
- **THEN** the report distinguishes the complete-corpus result from historical partial-corpus runs and supports per-case comparison with the SQLite result

## ADDED Requirements

### Requirement: Complete-corpus grounding gates
RDS answers MUST achieve at least 90% direct-answer correctness on the frozen eligible set, every rendered factual claim MUST retain a resolvable citation whose evidence supports that claim, and every labelled unanswerable case MUST return an evidence-insufficient response without factual claims.

#### Scenario: A fluent answer lacks valid support
- **WHEN** an answer text appears correct but one factual claim has no resolvable supporting citation in the frozen RDS snapshot
- **THEN** the case fails grounding acceptance and cannot be offset by other correct questions

### Requirement: Model-independent acceptance
All M10 quality gates MUST run with constrained model generation disabled and SHALL remain deterministic and repeatable without outbound model access.

#### Scenario: Final ECS evaluation starts
- **WHEN** the M10 acceptance command loads application configuration
- **THEN** it verifies that no model adapter is enabled before executing or publishing results
