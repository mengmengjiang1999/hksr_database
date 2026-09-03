## 1. Safe PostgreSQL validation foundation

- [x] 1.1 Add the optional PostgreSQL client dependency and environment-only DSN configuration with secret redaction.
- [x] 1.2 Add versioned PostgreSQL migrations for production-shaped evidence tables, stable identifiers, entities, relations, embeddings, and ingestion state.
- [x] 1.3 Add an isolated validation schema, run registry, and guarded cleanup for deterministic synthetic data.
- [x] 1.4 Add unit tests for migration idempotency, SQL safety, configuration validation, and secret-free output.

## 2. Extension and environment probes

- [x] 2.1 Implement read-only discovery for server version, kernel version, TLS, extensions, roles, relation sizes, and database settings.
- [x] 2.2 Implement explicitly enabled functional probes for vector distance/index operations and each Chinese lexical extension.
- [x] 2.3 Document the required `shared_preload_libraries` change, controlled restart, and rollback for Chinese extensions.
- [x] 2.4 Record sanitized PostgreSQL 18 Serverless procurement configuration and verify the purchased instance through DMS.

## 3. Optional scale and retrieval tooling

- [x] 3.1 Implement deterministic generation and batched loading of one named 100,000-chunk, 1024-dimension synthetic fixture.
- [x] 3.2 Implement exact-search oracle and HNSW Recall@10 measurement over a versioned query set.
- [x] 3.3 Implement warm concurrent hybrid retrieval benchmark with concurrency 10 and P50/P95/P99 reporting.
- [x] 3.4 Implement relation-size, import-duration, index-build-duration, stable-update, and M6A estimate-deviation reporting.

## 4. Private cloud migration and execution

- [x] 4.1 Configure a same-VPC runner with a least-privilege runtime account and verify prohibited operations fail; retain it as the development, test, and deployment host.
- [x] 4.2 Add and run an idempotent SQLite-to-PostgreSQL importer for the current official corpus, verify matching counts and stable IDs, repeat it without duplicates, and confirm the runtime role remains read-only.
- [x] 4.3 Record the separately purchased Shanghai OSS bucket for future collection storage; recovery drills are deferred by explicit user decision.
- [x] 4.4 Deploy the application on the retained ECS host and verify private RDS access, health, read-only operation, and automatic process restart.
- [x] 4.5 Verify no synthetic rows were loaded, identify retained cloud resources, and confirm the RDS 4 RCU cap and automatic pause configuration.

## 5. Acceptance and handoff

- [x] 5.1 Produce sanitized JSON and Markdown reports separating automatic measurements from operator-attested evidence.
- [x] 5.2 Add deterministic tests and run the full project test suite plus strict OpenSpec validation.
- [x] 5.3 Document cloud setup, deployment, cost observations, deferred recovery scope, and the PostgreSQL architecture decision.
- [x] 5.4 Verify every M6B acceptance gate, archive the OpenSpec change, and commit the completed stage once.
