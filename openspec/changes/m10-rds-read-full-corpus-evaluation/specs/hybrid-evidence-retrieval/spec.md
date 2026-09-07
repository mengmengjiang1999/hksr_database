## MODIFIED Requirements

### Requirement: Bounded candidate reranking
The system MUST use indexed lexical and resolved-entity candidates before loading semantic vectors on either SQLite or PostgreSQL, MUST NOT deserialize or score the entire eligible corpus for one interactive query, and SHALL enforce the same configured candidate bounds across backends.

#### Scenario: Complete corpus is queried through RDS
- **WHEN** an interactive query is evaluated against the 20,291-chunk corpus
- **THEN** lexical and entity queries use bounded indexed candidates, semantic reranking loads at most the configured candidate bound, and diagnostics report the bound without a full-corpus vector scan

## ADDED Requirements

### Requirement: Cross-backend retrieval equivalence
SQLite and PostgreSQL retrieval SHALL preserve intent, entity resolution, filters, source priority, endpoint coverage, score-component meaning, diversification, and expected Top 5 evidence even when backend-native lexical scores are not numerically identical.

#### Scenario: Shadow retrieval is compared
- **WHEN** the frozen 60-question set runs against both backends
- **THEN** every case has the same intent and resolved stable entity keys and any difference in expected Top 5 evidence is reported as a cutover-blocking mismatch

### Requirement: Complete-corpus retrieval gate
The frozen core answerable set MUST achieve at least 85% Top 5 evidence recall on RDS, with corpus gaps and labelled ambiguities reported separately rather than silently removed from the denominator.

#### Scenario: RDS retrieval acceptance is calculated
- **WHEN** all frozen questions have completed without infrastructure errors
- **THEN** the report publishes numerator, denominator, exclusions with reasons, source-kind breakdown, and the hard-gate result
