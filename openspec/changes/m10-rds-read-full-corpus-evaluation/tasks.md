## 1. Freeze inputs and untouched baselines

- [ ] 1.1 Add a secret-safe M10 manifest command that records backend, schema/index versions, retrieval configuration, dataset version, counts, dispositions, stable-evidence uniqueness, and a deterministic corpus fingerprint.
- [ ] 1.2 Freeze and verify the accepted 7,845-source, 6,709-document, 20,291-evidence manifest with 5,661 eligible, 11 operationally excluded, 2,173 unavailable, zero unverified evidence, and no synthetic evidence.
- [ ] 1.3 Bind `m9-real-questions-v1` and its taxonomy to the manifest without changing case labels or expectations.
- [ ] 1.4 Run and retain untouched SQLite and RDS 60-case quality baselines before ranking weights are changed.
- [ ] 1.5 Label the 1,890-chunk 56/60 M9 report as historical partial-corpus evidence in every comparison and M10 summary.

## 2. Backend-neutral read boundary

- [ ] 2.1 Inventory every application, API, retrieval, grounding, identity, relation, catalog, status, and citation-context read plus direct SQLite SQL and side effect.
- [ ] 2.2 Define the typed read-store protocol and normalized row/result models for all current user-facing read operations.
- [ ] 2.3 Implement `SQLiteReadStore` as a behavior-preserving wrapper and keep mutable SQLite ingestion/index operations outside the read contract.
- [ ] 2.4 Refactor API and domain read paths to use the protocol, including relation audits in non-mutating mode, without changing HTTP fields or browser behavior.
- [ ] 2.5 Add contract tests for ordering, filters, stable identities, JSON/boolean normalization, missing records, citations, relation visibility, and status counts.
- [ ] 2.6 Add a regression audit that rejects SQLite-only imports, placeholder syntax, schema initialization, commits, or raw `connect()` calls in user-facing read paths.

## 3. PostgreSQL schema parity and synchronization

- [ ] 3.1 Add idempotent PostgreSQL migrations for M7 dispositions, M9 narrative people/playable forms/typed names, retrieval metadata, stable exposed IDs, and any normalized-search fields required by the read contract.
- [ ] 3.2 Extend the SQLite-to-RDS synchronization to preserve exposed source/entity IDs and stable natural keys and to backfill every new read object without synthetic rows.
- [ ] 3.3 Add migration and importer tests for repeat execution, constraints, foreign keys, approved identity evidence, relation preservation, conflict blocking, and secret-free failures.
- [ ] 3.4 Record explicit rollback DDL for each new index or additive schema object without using rollback as part of normal application failover.
- [ ] 3.5 Apply migrations and backfill on RDS with the ingestion role, then reconcile table counts, all dispositions, identity and relation audits, stable evidence IDs, exposed IDs, and the frozen fingerprint.

## 4. PostgreSQL read adapter and least privilege

- [ ] 4.1 Add the Psycopg pool dependency and validated `sqlite|postgres` backend configuration with DSN redaction and no implicit fallback.
- [ ] 4.2 Implement `PostgresReadStore` queries for every protocol method with stable ordering, bounded result sizes, normalized types, and no application DDL.
- [ ] 4.3 Configure a lazy zero-minimum pool, provisional maximum of two connections, bounded acquisition/connect/statement timeouts, read-only transactions, recycling, and clean shutdown.
- [ ] 4.4 Add secret-safe readiness and status fields for backend, schema/fingerprint compatibility, pool counts, and categorized bounded errors.
- [ ] 4.5 Reject administrative sync/index mutation through the PostgreSQL runtime store and prove all normal endpoints remain side-effect free.
- [ ] 4.6 Run the shared adapter contract and full API suites against SQLite and an isolated PostgreSQL fixture before accessing production RDS.
- [ ] 4.7 Create and validate the same-VPC ECS runtime privilege matrix: required reads pass; evidence, ingestion-state and schema writes plus role and unrelated-schema access fail.

## 5. Bounded RDS retrieval

- [ ] 5.1 Implement PostgreSQL lexical and entity candidate queries with source, version, context, eligibility, and parsed-state filters pushed down.
- [ ] 5.2 Preserve the initial 200 entity and 500 total rerank bounds and load vectors/entity annotations only for the bounded candidate union.
- [ ] 5.3 Replace physical-row tie breaks with stable evidence ordering and preserve intent, endpoint coverage, source weighting, score components, and diversification semantics.
- [ ] 5.4 Add the PostgreSQL indexes required by the selected functional lexical and entity queries, with idempotent migrations and rollback statements.
- [ ] 5.5 Add regression tests proving interactive retrieval loads only the configured bounded candidate set rather than the full evidence/vector corpus.

## 6. SQLite/RDS shadow comparison

- [ ] 6.1 Implement an operator-invoked, read-only shadow command that runs the fixed manifest workload against both backends and emits sanitized JSON and Markdown reports.
- [ ] 6.2 Normalize backend-native numeric scores while comparing intent, stable entity keys, classification, expected Top 5 evidence, claims, citations, filters, source navigation, catalog counts, and relation visibility.
- [ ] 6.3 Add field-level mismatch diagnostics, explicit harmless-score-difference rules, nonzero exit status on blockers, and unchanged before/after corpus fingerprints.
- [ ] 6.4 Run the complete shadow suite and resolve every cutover-blocking data or behavior mismatch without silently changing the frozen dataset.

## 7. Complete-corpus quality acceptance

- [ ] 7.1 Extend the evaluation report with backend, full manifest, per-case expected/retrieved stable evidence, direct-answer result, refusal, ambiguity, partial support, citation validation, and failure owner.
- [ ] 7.2 Run the frozen 60 questions on SQLite and RDS with model generation disabled and no infrastructure failures.
- [ ] 7.3 Report Top 5 numerator/denominator and source breakdown, direct-answer correctness, refusal accuracy, ambiguity, factual citation coverage/support, and all failure classifications.
- [ ] 7.4 Diagnose failures in corpus, parsing/chunking, entity/version, intent, retrieval, answer, and citation order before tuning ranking parameters.
- [ ] 7.5 Correct justified defects with regression cases; if any label correction is required, version the dataset and rerun untouched baselines for both backends.
- [ ] 7.6 Pass the hard gates: Top 5 at least 85%, direct-answer correctness at least 90% and within two points of SQLite, factual citation coverage/support 100%, and all labelled unanswerable cases correctly refused.

## 8. ECS rehearsal, rollback, and cutover

- [ ] 8.1 Update private deployment configuration and runbooks for the protected DSN, explicit backend flag, pool/timeouts, readiness, model-disabled state, and disabled `hksr-m7.timer`.
- [ ] 8.2 Deploy the dual-backend-capable revision to ECS with SQLite still active and verify service, API/UI smoke, no secrets, and unchanged corpus state.
- [ ] 8.3 Rehearse RDS selection, restart, readiness, fixed browse/ask smoke cases, and application operation without the SQLite evidence file.
- [ ] 8.4 Explicitly rollback to SQLite by configuration and restart, rerun readiness and smoke, and prove that neither backend, OSS, model state, nor collection state was mutated.
- [ ] 8.5 Present the complete shadow, quality, privilege, and rollback evidence for explicit production-cutover approval.
- [ ] 8.6 After approval, switch the private application to RDS, restart, rerun smoke and hard gates, retain the accepted SQLite snapshot, and stop on any mismatch without silent fallback.

## 9. Final verification and handoff

- [ ] 9.1 Run focused migration/adapter/retrieval/evaluation/deployment tests and the full local offline suite.
- [ ] 9.2 Run the corresponding ECS integration and 60-case acceptance suites with the production read role and model generation disabled.
- [ ] 9.3 Run strict OpenSpec validation, `git diff --check`, credential/private-identifier scans, generated/runtime-data review, and a scoped Git diff review.
- [ ] 9.4 Confirm the application is active on the approved backend, model generation is disabled, and `hksr-m7.timer` is disabled.
- [ ] 9.5 Publish sanitized JSON/Markdown acceptance and rollback reports with commit revision, corpus fingerprint, exact denominators, unresolved failures, and commands required to reproduce the result.
