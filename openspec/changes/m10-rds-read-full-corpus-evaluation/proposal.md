## Why

M7 has finished with 20,291 eligible evidence chunks synchronized to RDS, while the ECS application still reads a SQLite copy and the latest 60-question M9 report covered only 1,890 chunks. The next stage must make the private application read the complete RDS corpus through a reversible, read-only path and establish honest full-corpus quality acceptance.

## What Changes

- Add a PostgreSQL/RDS read backend for sources, documents, evidence, catalog facets, entities, narrative identities, relations, retrieval candidates, vectors, and administrative status while preserving stable evidence IDs and the existing HTTP/UI contract.
- Add missing PostgreSQL schema parity and the indexes required by bounded lexical, entity, relation, evidence-context, and vector reads.
- Use a least-privilege runtime role, bounded connection management, explicit timeouts, secret-safe diagnostics, and read-only transactions; application reads must not mutate ingestion state or production evidence.
- Add a backend feature flag with startup validation, SQLite/RDS shadow comparison, an explicit cutover gate, and a tested rollback that requires neither data deletion nor schema reversal.
- Freeze a complete-corpus snapshot manifest and rerun the versioned 60-question evaluation against both backends, reporting Top 5 recall, direct-answer correctness, refusals, ambiguity, corpus gaps, ranking misses, and claim-level citation coverage.
- Treat the existing 56/60 report as a limited historical baseline only; it MUST NOT be presented as acceptance for the 20,291-chunk corpus.
- Keep constrained model generation disabled and keep `hksr-m7.timer` disabled throughout M10.

## Capabilities

### New Capabilities

- `rds-read-runtime`: Covers backend-neutral read behavior, PostgreSQL schema parity, least-privilege connections, shadow comparison, controlled cutover, and rollback.
- `full-corpus-quality-evaluation`: Covers immutable corpus manifests, cross-backend evaluation, quality gates, and failure classification.

### Modified Capabilities

- `cloud-database-validation`: Extends cloud validation from migration probes to production read-role, schema/index, connection, and rollback acceptance.
- `hybrid-evidence-retrieval`: Requires backend-equivalent bounded candidate retrieval and defines complete-corpus Top 5 reporting and acceptance.
- `evidence-grounded-answering`: Defines complete-corpus direct-answer, refusal, and factual citation acceptance without an online model.
- `local-knowledge-app`: Makes the existing API/UI contract backend-independent and adds secret-safe backend readiness without introducing read-side mutations.

## Impact

- Affects `app/models`, retrieval and grounding read interfaces, FastAPI startup and status reporting, PostgreSQL migrations, deployment configuration, evaluation commands, test fixtures, and M10 acceptance reports.
- Adds the existing optional `psycopg` cloud dependency to the ECS application runtime; it does not add a model provider or a new public endpoint.
- Operates on the retained same-VPC ECS, RDS, and SQLite snapshot without changing the current RDS capacity or automatic-pause configuration.
- No API or browser breaking change is intended. The ingestion pipeline, OSS raw objects, collection timer, and model configuration remain outside this change.
