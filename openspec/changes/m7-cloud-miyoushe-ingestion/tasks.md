## 1. Runtime convention and deterministic coverage

- [x] 1.1 Document ECS as the normal runtime for ordinary real-collection commands without adding an activation flag, host marker, or machine-identity check.
- [x] 1.2 Add deterministic mocked tests for multi-run cursor resume, terminal detection, duplicate post IDs, malformed responses, and newly appearing posts.
- [x] 1.3 Add deterministic pacing tests for the two-page discovery cap, ten-body fetch cap, 15–30 second jitter bounds, 60-request default daily budget, approved finite or unlimited recorded overrides, retry budget, and three-failure circuit breaker.
- [x] 1.4 Add lock, interruption, secret-redaction, and report-schema tests without contacting Miyoushe, OSS, RDS, or ECS metadata services.

## 2. Resumable staging and classification

- [x] 2.1 Add versioned SQLite migrations for collection runs, account checkpoints, daily request budgets, source dispositions, fetch attempts, and raw-object manifests.
- [x] 2.2 Implement atomic one-page cursor commits and resume behavior that distinguishes bounded pause from upstream terminal completion.
- [x] 2.3 Implement versioned classification states and reasons for eligible evidence, operational exclusions, missing official text, manual review, and unverified listing items.
- [x] 2.4 Add review commands that can reclassify an item without refetching unchanged content and that never promote unverified items.

## 3. Slow collector and private raw storage

- [x] 3.1 Split official-account metadata discovery from post-body fetching and expose separate bounded CLI commands with conservative pacing defaults.
- [x] 3.2 Implement delayed requests, jitter, `Retry-After`, exponential backoff, shared daily accounting, circuit breaking, and a single-run OS lock.
- [x] 3.3 Add canonical response hashing, protected local spooling, and deterministic private OSS object manifests without video binary download.
- [x] 3.4 Add OSS upload through an ECS RAM role and refuse static AccessKey configuration or a successful fetch state before OSS persistence.
- [x] 3.5 Generalize real-import batch validation for unique M7 identifiers and produce per-batch SQLite-to-RDS reconciliation audits.

## 4. M7A cloud pilot

- [x] 4.1 Deploy the tested collector revision to ECS and verify that the production runbook launches the ordinary collection commands from the cloud working directory without an activation flag or host-specific marker.
- [x] 4.2 Attach a least-privilege ECS RAM role limited to the designated private OSS M7 prefix and verify it with one non-sensitive probe object.
- [x] 4.3 Run exactly one ECS discovery pilot of at most two 20-item pages and record cursor, pacing, official verification, and disposition totals.
- [x] 4.4 Run exactly one ECS body-fetch pilot of at most ten posts, persist raw hashes to OSS, parse eligible items, and reconcile the pilot batch into RDS twice without duplicates.
- [x] 4.5 Review M7A categories, empty text, video subtitle availability, parser failures, rate-limit signals, and reports before authorizing M7B.

## 5. M7B slow complete inventory and ingestion

- [x] 5.1 Execute each remaining metadata discovery invocation on ECS with at most two pages, stopping for a report review after every invocation.
- [x] 5.2 Execute body fetching on ECS in batches of at most ten posts, never exceeding the shared daily request budget, and stop immediately when the circuit breaker opens.
- [x] 5.3 After each reviewed fetch batch, parse only eligible items and upload raw snapshots; reconcile named periodic groups and the final M7 batch into RDS, repeat the final batch once, and verify count stability.
- [x] 5.4 Continue the recorded small-batch loop across separate runs until the upstream official listing reaches its terminal cursor; do not infer completion from an expected item count.
- [x] 5.5 Resolve or explicitly retain every manual-review item and verify that all discovered items have a final or review disposition with no unverified evidence rows.

## 6. M7C acceptance and controlled incrementals

- [x] 6.1 Rebuild ECS-local indexes, sample lore-related retrieval traceability, and compare eligible SQLite staging counts with the final RDS audit.
- [ ] 6.2 Run three manually initiated no-change incremental checks and verify stable cursors, hashes, evidence IDs, row counts, and request-budget behavior.
- [x] 6.3 Add systemd oneshot and timer units with locking and journal logging, install them on ECS, and confirm the recurring timer remains disabled.
- [x] 6.4 Produce sanitized JSON and Markdown completion reports covering inventory, dispositions, pacing, retries, OSS persistence, RDS batches, exclusions, and unresolved items.
- [x] 6.5 Run the full local offline test suite, full ECS test suite, strict OpenSpec validation, and secret scan; enable recurring collection only after separate explicit user approval.

## 7. Complete Wiki game-catalog ingestion

- [x] 7.1 Implement official Wiki `游戏图鉴` directory discovery with stable detail URLs, deterministic source kinds, and cross-channel `content_id` deduplication.
- [x] 7.2 Add deterministic tests for catalog coverage, achievement inclusion, guide exclusion, duplicate IDs, task categories, malformed responses, and idempotent rediscovery.
- [x] 7.3 Deploy the catalog discovery command to ECS, register the current unique Wiki access list, and verify the observed and deduplicated counts without interrupting the official-account collector.
- [x] 7.4 Fetch and privately persist every queued Wiki detail on ECS with bounded pacing, restartable state, parsing, and sanitized progress reports.
- [x] 7.5 Reconcile parsed Wiki evidence into RDS, verify category and unique-ID totals, and add the Wiki catalog to controlled incremental synchronization.
