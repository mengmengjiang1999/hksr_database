## Context

M7 finished with 7,845 sources, 6,709 documents, and 20,291 eligible evidence chunks synchronized between the accepted SQLite snapshot and private RDS. All sources have a disposition (`eligible_evidence` 5,661, `excluded_operational` 11, `excluded_unavailable` 2,173), unverified evidence is zero, stable evidence IDs are unique, and the application service is active. The ECS application nevertheless constructs `Database(Path(...))`, initializes SQLite at startup, and several API, retrieval, identity, and relation paths execute SQLite SQL directly.

The existing PostgreSQL migrations and importer prove private connectivity, stable evidence migration, pgvector support, and count reconciliation, but they do not yet provide the full M9 identity schema or an application read adapter. The last ECS M9 evaluation scored 56/60 (93.33%) against about 1,890 chunks; it is useful historical evidence but cannot certify the 20,291-chunk corpus. M10 must preserve the M8 API/UI contract, validate quality on the complete corpus, and cut over without enabling a model or the disabled M7 collection timer.

## Goals / Non-Goals

**Goals:**

- Make every private application read work from RDS with a dedicated read-only role and no SQLite file dependency.
- Preserve stable evidence, source and entity navigation plus all current API response and failure semantics.
- Establish PostgreSQL schema parity for M7 dispositions and M9 narrative identities, including the indexes required by the selected read queries.
- Compare SQLite and RDS deterministically before cutover and retain an explicit, tested SQLite rollback.
- Freeze a complete-corpus manifest and produce a reproducible quality report.
- Meet hard grounding, refusal, Top 5, and direct-answer gates with model generation disabled.

**Non-Goals:**

- Running or selecting a model provider, configuring model credentials, or enabling model generation.
- Enabling `hksr-m7.timer`, changing collection cadence, or moving ingestion writes into the application process.
- Changing public API routes or rebuilding the browser for backend-specific behavior.
- RDS performance benchmarking, memory profiling, concurrency load testing, cold-start measurement, cost acceptance, capacity changes, or ECS upgrades.
- Increasing the evaluation set beyond the frozen 60 cases, changing labels to improve a score, or claiming that the earlier 1,890-chunk report covers the full corpus.
- Adding public access, authentication, HTTPS, review UI, backup-restore drills, or M11/M12 operations.

## Decisions

### Introduce an explicit read-store boundary

Define a typed read-store protocol containing the exact operations used by catalog, source details, status, entity resolution, narrative identities, approved relations, evidence lookup and context, lexical/entity candidate generation, bounded retrieval row loading, and retrieval metadata. `SQLiteReadStore` wraps current behavior and `PostgresReadStore` implements the same returned dictionaries and ordering. API, grounding, retrieval, identity, and relation code stop issuing ad hoc SQL through `database.connect()` on user-facing paths.

The existing mutable `Database` remains the SQLite ingestion/index implementation. Administrative sync rejects the PostgreSQL read backend and continues to require an explicit ingestion path; the normal application process receives only a read store.

Alternative: make the current `Database` dynamically translate SQL placeholders and JSON types. Rejected because SQLite initialization, FTS virtual tables, transaction commits, JSON encoding, booleans and PostgreSQL query plans have materially different semantics and would keep raw backend-specific SQL scattered across domain code.

### Preserve API identity while compare by natural keys

Stable evidence ID remains `provider:external_id:document_key:chunk_key`. The RDS synchronization and schema audit preserve the accepted SQLite numeric IDs for currently exposed sources and entities; any existing conflict blocks cutover. Internally, reconciliation and shadow comparison use provider/external ID, document/chunk keys, stable evidence IDs, canonical entity type/name, and M9 stable identity keys, so a generated database row ID is never treated as proof of equivalence.

Search and entity responses may keep their existing integer fields, but adapter normalization must prove that each returned integer resolves to the same stable source or entity on both backends. Tie-breaking uses stable evidence identity after normalized score components so independent physical row ordering cannot change results.

Alternative: change routes immediately to string natural keys. Rejected because M10 promises no API/UI breaking change; additive stable-key fields can be considered later.

### Migrate schema with the ingestion role, never at application startup

Add versioned PostgreSQL migrations for the M7 dispositions required by coverage/status reads, M9 `narrative_people`, `playable_forms`, and `identity_names`, retrieval metadata, and any public-ID or normalized-search support proven necessary by the audit. Backfill from the accepted SQLite snapshot through the existing secret-safe import workflow, reconcile counts and stable keys, then grant SELECT on the minimum objects to the runtime role.

`PostgresReadStore` checks a schema-version marker and fingerprint but never runs DDL, creates an extension, or backfills data. Missing or incompatible schema makes readiness fail closed.

Alternative: let application startup call `CREATE TABLE IF NOT EXISTS`, matching SQLite. Rejected because a production runtime role must not own DDL or evidence writes and startup side effects make rollback and auditing ambiguous.

### Use a small lazy pool and bounded read-only transactions

Use Psycopg 3 plus its pool package with `min_size=0` and `max_size=2`, matching the current small private service. Connections are established lazily. Configure bounded pool acquisition, connection and statement timeouts, idle and maximum lifetime recycling, TCP keepalive, `default_transaction_read_only=on`, and clean application shutdown. These are correctness safeguards against stuck requests, not performance acceptance criteria.

Readiness exposes only backend type, compatible schema/fingerprint, pool counts and categorized errors. It never serializes exception connection strings. The DSN stays in the existing protected ECS configuration path with restrictive permissions, is excluded from Git and reports, and is redacted before logging. Acceptance scans code, deployment artifacts and reports for credentials and private identifiers.

Alternative: open one new connection for each database method. Rejected because one request invokes several reads and unconstrained connection setup can exhaust RDS sessions.

### Bound unavailable-database behavior

No periodic keepalive will be added, and the collection timer remains disabled. Routine process health does not issue unbounded database calls.

If RDS is unavailable, pool acquisition or connection timeout produces a sanitized retryable response and the page exits its loading state. The application does not silently fall back to a stale SQLite copy. Operators may explicitly rollback the configured backend.

Alternative: automatically switch to SQLite on error. Rejected because it can return stale, mixed-corpus results without user awareness.

### Generate bounded candidates in PostgreSQL and rerank identically

Preserve M9's maximum 200 entity candidates and 500 total rerank candidates as the initial bounds. PostgreSQL performs bounded lexical and entity-link candidate queries with source, version and context filters pushed down, then returns only selected rows and embeddings for the existing deterministic score components and diversification. It must not stream or deserialize all 20,291 vectors for an interactive request.

Use one Chinese lexical strategy already proven functionally available by the M6B extension probe and add only the indexes required by that query plus entity, relation, source and evidence-key lookups. Functional tests must prove Chinese matching, filters and bounded candidate loading. M10 does not compare index performance or add HNSW because semantic scoring remains bounded by lexical/entity candidates.

Alternative: add every available GIN and HNSW index. Rejected because they are not required for the selected functional query path.

### Use an offline shadow runner rather than live double reads

Add an operator-invoked command that loads a fixed manifest and sends the same API/domain workload to SQLite and RDS. It normalizes backend-native score differences while comparing intent, stable resolved entity keys, response status, expected Top 5 stable evidence IDs, accepted claims and citations, source/detail navigation, catalog counts and relation visibility. It writes JSON plus a human-readable sanitized summary.

Shadow results do not alter a user response, cache, database, evaluation labels, or backend selection. A field-level mismatch is a cutover blocker unless it is documented as a harmless numeric-score difference and all downstream behavior is equal.

Alternative: double-read every live ECS request. Rejected because it doubles database work and provides less reproducible evidence than a fixed workload.

### Freeze evaluation inputs before diagnosis or tuning

Create a M10 manifest for the accepted M7 snapshot that verifies the known counts, all source dispositions, zero unverified evidence, unique stable evidence IDs, and a deterministic fingerprint over stable identity plus content hashes. Bind the existing `m9-real-questions-v1` 60-case dataset, taxonomy version, application revision, backend, schema/index version, retrieval bounds and ranking configuration to each result.

Run untouched SQLite and RDS baselines first. Reports must preserve per-case expected evidence, answerability and ambiguity labels and classify failures into corpus gap, parse/chunk defect, entity resolution, intent, ranking, answer, citation, backend mismatch, or expected ambiguity. Remediation proceeds in that ownership order; labels and denominators cannot be changed silently. Any justified dataset correction creates a new dataset version and reruns both baselines.

Alternative: tune RDS until the aggregate equals the historical 56/60 result. Rejected because that result covered only 1,890 chunks and aggregate equality can hide citation, refusal, or backend regressions.

### Use hard quality gates

Quality acceptance uses the frozen eligible core set: Top 5 recall at least 85%; direct-answer correctness at least 90% and no more than two percentage points below the frozen SQLite full-corpus baseline; factual citation coverage and citation resolution/support 100%; every labelled unanswerable case refuses with no factual claim. Corpus gaps and expected ambiguities are reported with explicit denominators and are never used to hide infrastructure errors.

### Cut over through explicit gates and retain configuration rollback

`HKSR_READ_BACKEND=sqlite|postgres` selects exactly one response backend. A preflight command checks migration version, privileges, snapshot fingerprint, required counts, identity/relation integrity, index readiness, and secret-free configuration. Cutover requires strict OpenSpec validation, offline tests, full API contract tests against both adapters, a clean shadow report, quality gates, and a rollback drill.

The deploy changes the protected backend flag, restarts the private service, and runs a fixed smoke set while `HKSR_M9_ENTITY_QA_ENABLED=1`, generation remains unconfigured, and `hksr-m7.timer` remains disabled. Rollback restores `sqlite`, restarts, and reruns the smoke set; it does not drop RDS objects, delete evidence, alter OSS, enable collection, or rewrite Git history.

Alternative: remove SQLite immediately after the first RDS success. Rejected because the required reversible transition would be lost before operational behavior is established.

## Risks / Trade-offs

- [SQLite FTS and PostgreSQL lexical scores differ] → Compare stable Top 5 evidence and downstream answer behavior, retain score components, and allow numeric differences only when normalized behavior passes.
- [Current RDS schema lacks M7/M9 read objects] → Audit first, migrate with the ingestion role, reconcile every stable key and count, and fail application readiness on partial schema.
- [Direct SQL remains outside the new store] → Add a test/lint audit for SQLite-only imports, placeholder syntax and `connect()` use in application read paths.
- [Numeric IDs diverge between existing stores] → Reconcile exposed IDs before cutover, use stable natural keys for proof, and block rather than guess or silently remap conflicting public IDs.
- [Full corpus changes correct rankings] → Freeze manifest and labels first, diagnose per case, and compare both backends rather than forcing byte-identical score values.
- [Reports leak infrastructure information] → Store only sanitized configuration categories and run credential/private-identifier scans before commit.
- [Read code accidentally mutates state] → Run the full endpoint suite under the read-only role and assert unchanged fingerprints, counts, dispositions and relation state before and after.

## Migration Plan

1. Freeze the accepted SQLite/RDS manifest and 60-question inputs; record untouched SQLite and RDS quality baselines before ranking changes.
2. Extract the read-store contract and make existing SQLite tests pass unchanged; add adapter contract fixtures for every read operation and eliminate raw SQL from user-facing domain/API paths.
3. Add PostgreSQL schema-parity migrations and importer support with the ingestion role; backfill M7 dispositions, M9 identities and retrieval metadata, then reconcile IDs, stable keys, counts and fingerprints.
4. Implement the least-privilege PostgreSQL adapter, lazy bounded pool, sanitized readiness and fail-closed configuration. Verify the privilege matrix on same-VPC ECS.
5. Add the indexes required by the selected functional lexical/entity/context query path and verify bounded candidate behavior.
6. Run the offline SQLite/RDS shadow comparison and fix data, parsing, entity, intent, ranking, answer or citation failures without changing frozen labels silently.
7. Run full local tests, both-backend contract tests, strict OpenSpec validation, secret scans, and the complete 60-case quality evaluation.
8. Perform a rehearsal cutover and explicit SQLite rollback on ECS; confirm service health, fixed API/UI smoke cases, model disabled state, timer disabled state and unchanged database fingerprints.
9. After all hard gates pass and the user approves implementation/cutover, set the protected backend flag to PostgreSQL, restart, rerun smoke and acceptance checks, and retain the accepted SQLite snapshot for rollback.

Rollback sets the protected backend flag to `sqlite`, restarts the service, and reruns readiness plus the fixed smoke set. If push is rejected or remote history has advanced, stop without pull, merge, rebase, force push, or remote overwrite. Database rollback never drops migrated RDS data or indexes during the incident; cleanup is a later reviewed action.

## Open Questions

- Which Chinese lexical strategy already validated in M6B should implement the required functional matching behavior in the RDS adapter?
- Do existing RDS source and entity IDs already match every exposed SQLite ID, or is an explicit public-ID backfill required before adapter work can pass?
