## Context

M7 finished with 7,845 sources, 6,709 documents, and 20,291 eligible evidence chunks synchronized between the accepted SQLite snapshot and private RDS. All sources have a disposition (`eligible_evidence` 5,661, `excluded_operational` 11, `excluded_unavailable` 2,173), unverified evidence is zero, stable evidence IDs are unique, and the application service is active. The ECS application nevertheless constructs `Database(Path(...))`, initializes SQLite at startup, and several API, retrieval, identity, and relation paths execute SQLite SQL directly.

The existing PostgreSQL migrations and importer prove private connectivity, stable evidence migration, pgvector support, and count reconciliation, but they do not yet provide the full M9 identity schema or an application read adapter. The last ECS M9 evaluation scored 56/60 (93.33%) against about 1,890 chunks; it is useful historical evidence but cannot certify the 20,291-chunk corpus. M10 must measure the current system before tuning, preserve the M8 API/UI contract, and cut over without enabling a model or the disabled M7 collection timer.

## Goals / Non-Goals

**Goals:**

- Make every private application read work from RDS with a dedicated read-only role and no SQLite file dependency.
- Preserve stable evidence, source and entity navigation plus all current API response and failure semantics.
- Establish PostgreSQL schema parity for M7 dispositions and M9 narrative identities, then choose only measured retrieval indexes.
- Compare SQLite and RDS deterministically before cutover and retain an explicit, tested SQLite rollback.
- Freeze a complete-corpus manifest and produce reproducible quality, performance, memory, connection, query-plan, cold-wake, and cost reports.
- Meet hard grounding, refusal, Top 5, direct-answer, timeout and memory gates with model generation disabled.

**Non-Goals:**

- Running or selecting a model provider, configuring model credentials, or enabling model generation.
- Enabling `hksr-m7.timer`, changing collection cadence, or moving ingestion writes into the application process.
- Changing public API routes or rebuilding the browser for backend-specific behavior.
- Expanding RDS beyond the existing 4-RCU maximum, disabling automatic pause, upgrading ECS, or purchasing capacity before measurement and separate approval.
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

Use Psycopg 3 plus its pool package with `min_size=0` and a provisional `max_size=2`, matching the current small private workload and concurrency levels under test. Connections are established lazily so M10 does not defeat RDS automatic pause. Configure a bounded pool acquisition wait, a 10-second connection timeout, an 8-second default statement timeout for warm interactive reads, idle and maximum lifetime recycling, TCP keepalive, `default_transaction_read_only=on`, and clean application shutdown. Final values may tighten after the recorded baseline but may not exceed the 25-second browser deadline.

Readiness exposes only backend type, compatible schema/fingerprint, pool counts and categorized errors. It never serializes exception connection strings. The DSN stays in the existing protected ECS configuration path with restrictive permissions, is excluded from Git and reports, and is redacted before logging. Acceptance scans code, deployment artifacts and reports for credentials and private identifiers.

Alternative: open one new connection for each database method. Rejected because one request invokes several reads, connection setup amplifies serverless wake latency, and unconstrained concurrent setup can exhaust RDS sessions.

### Keep cold-wake behavior distinct from warm request latency

No periodic keepalive will be added, and the collection timer remains disabled. Deployment probes may intentionally wake RDS, but routine process health must not continuously prevent automatic pause. Evaluation records a cold sequence from first connection through readiness and first successful query separately from warm P50/P95 runs.

If wake-up exceeds the interactive budget, pool acquisition or connection timeout produces a sanitized retryable 503 before the browser's 25-second abort; the page exits loading state. The application does not silently fall back to a stale SQLite copy. Operators may explicitly rollback the configured backend.

Alternative: keep RDS permanently warm or automatically switch to SQLite on error. Rejected because the former changes cost behavior without evidence and the latter can return stale, mixed-corpus results without user awareness.

### Generate bounded candidates in PostgreSQL and rerank identically

Preserve M9's maximum 200 entity candidates and 500 total rerank candidates as the initial bounds. PostgreSQL performs bounded lexical and entity-link candidate queries with source, version and context filters pushed down, then returns only selected rows and embeddings for the existing deterministic score components and diversification. It must not stream or deserialize all 20,291 vectors for an interactive request.

Before adding indexes, capture representative `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans and timings on the frozen corpus. Compare built-in text search and only the actually available Chinese candidates (`pg_bigm`, `pg_jieba`, `zhparser`) in a controlled migration. For each candidate record build time, relation and index size, recall, P50/P95 latency, buffer reads, and M7 sync impact. Retain the smallest index combination that meets gates; remove unused experimental indexes. HNSW is not added unless evidence shows server-side vector candidate generation is necessary, since semantic scoring is already bounded by lexical/entity candidates.

Alternative: add every available GIN and HNSW index before benchmarking. Rejected because the 20,291-row corpus may not need them and unused indexes raise storage, synchronization and serverless-resume cost.

### Use an offline shadow runner rather than live double reads

Add an operator-invoked command that loads a fixed manifest and sends the same API/domain workload to SQLite and RDS. It normalizes backend-native score differences while comparing intent, stable resolved entity keys, response status, expected Top 5 stable evidence IDs, accepted claims and citations, source/detail navigation, catalog counts and relation visibility. It writes JSON plus a human-readable sanitized summary.

Shadow results do not alter a user response, cache, database, evaluation labels, or backend selection. A field-level mismatch is a cutover blocker unless it is documented as a harmless numeric-score difference and all downstream behavior is equal.

Alternative: double-read every live ECS request. Rejected because it doubles database work and latency, risks waking RDS unnecessarily, and provides less reproducible evidence than a fixed workload.

### Freeze evaluation inputs before diagnosis or tuning

Create a M10 manifest for the accepted M7 snapshot that verifies the known counts, all source dispositions, zero unverified evidence, unique stable evidence IDs, and a deterministic fingerprint over stable identity plus content hashes. Bind the existing `m9-real-questions-v1` 60-case dataset, taxonomy version, application revision, backend, schema/index version, retrieval bounds and ranking configuration to each result.

Run untouched SQLite and RDS baselines first. Reports must preserve per-case expected evidence, answerability and ambiguity labels and classify failures into corpus gap, parse/chunk defect, entity resolution, intent, ranking, answer, citation, backend mismatch, or expected ambiguity. Remediation proceeds in that ownership order; labels and denominators cannot be changed silently. Any justified dataset correction creates a new dataset version and reruns both baselines.

Alternative: tune RDS until the aggregate equals the historical 56/60 result. Rejected because that result covered only 1,890 chunks and aggregate equality can hide citation, refusal, or backend regressions.

### Combine hard quality gates with measured performance gates

Quality acceptance uses the frozen eligible core set: Top 5 recall at least 85%; direct-answer correctness at least 90% and no more than two percentage points below the frozen SQLite full-corpus baseline; factual citation coverage and citation resolution/support 100%; every labelled unanswerable case refuses with no factual claim. Corpus gaps and expected ambiguities are reported with explicit denominators and are never used to hide infrastructure errors.

Performance uses versioned search, source, catalog, entity, relation, and ask workloads. After warm-up, collect at least 30 runs per endpoint class at concurrency 1 and 2. Record cold and warm separately, P50/P95, timeouts/errors, process peak RSS and per-request RSS delta, pool occupancy, database sessions, and query plans. Provisional hard gates are warm search P95 at most 5 seconds, warm ask P95 at most 8 seconds, every request finishing or failing actionably before 25 seconds, process peak RSS below 1 GiB, and per-request RSS growth below 256 MiB. These gates directly prevent recurrence of the observed long spinner and roughly 1.7-GB request behavior.

The report also records the observation window, workload volume, current maximum RCU, automatic-pause state, sanitized consumption/cost, index sizes and connections. Failure leads first to query/index diagnosis, not an automatic capacity increase.

Alternative: define only latency averages. Rejected because averages hide serverless cold starts, tail latency, memory spikes and concurrency failures.

### Cut over through explicit gates and retain configuration rollback

`HKSR_READ_BACKEND=sqlite|postgres` selects exactly one response backend. A preflight command checks migration version, privileges, snapshot fingerprint, required counts, identity/relation integrity, index readiness, and secret-free configuration. Cutover requires strict OpenSpec validation, offline tests, full API contract tests against both adapters, a clean shadow report, quality gates, performance/memory gates, a cold-wake observation, and a rollback drill.

The deploy changes the protected backend flag, restarts the private service, and runs a fixed smoke set while `HKSR_M9_ENTITY_QA_ENABLED=1`, generation remains unconfigured, and `hksr-m7.timer` remains disabled. Rollback restores `sqlite`, restarts, and reruns the smoke set; it does not drop RDS objects, delete evidence, alter OSS, enable collection, or rewrite Git history.

Alternative: remove SQLite immediately after the first RDS success. Rejected because the required reversible transition would be lost before operational behavior is established.

## Risks / Trade-offs

- [SQLite FTS and PostgreSQL lexical scores differ] → Compare stable Top 5 evidence and downstream answer behavior, retain score components, and allow numeric differences only when normalized behavior passes.
- [Current RDS schema lacks M7/M9 read objects] → Audit first, migrate with the ingestion role, reconcile every stable key and count, and fail application readiness on partial schema.
- [Direct SQL remains outside the new store] → Add a test/lint audit for SQLite-only imports, placeholder syntax and `connect()` use in application read paths.
- [Numeric IDs diverge between existing stores] → Reconcile exposed IDs before cutover, use stable natural keys for proof, and block rather than guess or silently remap conflicting public IDs.
- [Serverless resume exceeds connection timeout] → Measure cold wake separately, return bounded retryable failure, keep UI deadline behavior, and do not disable automatic pause in M10.
- [A connection pool keeps RDS awake] → Use a lazy zero-minimum pool, recycle idle connections, avoid periodic database health queries, and include pause/cost observation in acceptance.
- [Indexes improve latency but harm sync cost] → Measure build size/time and a representative M7 sync before retaining an index; keep rollback DDL for each migration.
- [Full corpus changes correct rankings] → Freeze manifest and labels first, diagnose per case, and compare both backends rather than forcing byte-identical score values.
- [Reports leak infrastructure information] → Store only sanitized configuration categories and aggregate cost/capacity values; run credential/private-identifier scans before commit.
- [Read code accidentally mutates state] → Run the full endpoint suite under the read-only role and assert unchanged fingerprints, counts, dispositions and relation state before and after.

## Migration Plan

1. Freeze the accepted SQLite/RDS manifest and 60-question inputs; record untouched SQLite and RDS query/performance baselines before schema/index tuning.
2. Extract the read-store contract and make existing SQLite tests pass unchanged; add adapter contract fixtures for every read operation and eliminate raw SQL from user-facing domain/API paths.
3. Add PostgreSQL schema-parity migrations and importer support with the ingestion role; backfill M7 dispositions, M9 identities and retrieval metadata, then reconcile IDs, stable keys, counts and fingerprints.
4. Implement the least-privilege PostgreSQL adapter, lazy bounded pool, sanitized readiness and fail-closed configuration. Verify the privilege matrix on same-VPC ECS.
5. Run query-plan experiments on the frozen corpus, add only the selected lexical/entity/context indexes, and record before/after size, time, recall and sync impact.
6. Run the offline SQLite/RDS shadow comparison and fix data, parsing, entity, intent, ranking, answer or citation failures without changing frozen labels silently.
7. Run full local tests, both-backend contract tests, strict OpenSpec validation, secret scans, complete 60-case quality evaluation, warm/cold performance, concurrency, memory and cost measurements.
8. Perform a rehearsal cutover and explicit SQLite rollback on ECS; confirm service health, fixed API/UI smoke cases, model disabled state, timer disabled state and unchanged database fingerprints.
9. After all hard gates pass and the user approves implementation/cutover, set the protected backend flag to PostgreSQL, restart, rerun smoke and acceptance checks, and retain the accepted SQLite snapshot for rollback.

Rollback sets the protected backend flag to `sqlite`, restarts the service, and reruns readiness plus the fixed smoke set. If push is rejected or remote history has advanced, stop without pull, merge, rebase, force push, or remote overwrite. Database rollback never drops migrated RDS data or indexes during the incident; cleanup is a later reviewed action.

## Open Questions

- Which Chinese lexical strategy and exact index combination meets the frozen recall and latency gates with the smallest measured size? This is intentionally resolved by the baseline/experiment task, not assumed in advance.
- What is the observed RDS automatic-pause wake distribution on the retained instance, and can it finish within the interactive deadline without changing the pause policy?
- Do existing RDS source and entity IDs already match every exposed SQLite ID, or is an explicit public-ID backfill required before adapter work can pass?
- After the untouched full-corpus baseline, should performance limits be tightened below the provisional 5-second search and 8-second ask P95 gates? Any relaxation requires explicit review; it is not an implementation shortcut.
