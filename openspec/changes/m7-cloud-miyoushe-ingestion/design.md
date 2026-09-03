## Context

M6B migrated the currently collected five-source corpus into a private Alibaba Cloud RDS PostgreSQL 18 Serverless instance and retained the same-VPC ECS host for development, testing, and deployment. The current Miyoushe collector can fetch a bounded number of official-account pages, validate official status, fetch post bodies, parse them into an ECS-local SQLite staging database, and reconcile that staging database into RDS. It does not yet provide a durable cursor checkpoint, conservative request budgets, OSS raw-response storage, complete-discovery proof, or scheduled incremental execution.

The user wants real collection work to run on ECS and specifically rejects a large one-shot M7B crawl. This is an operational preference rather than a requirement to make local execution technically impossible. The developer workstation is used for editing, review, and mocked or fixture-based tests; runbooks launch real discovery and fetching on ECS.

Miyoushe Wiki is the primary official source. Verified official-account posts are a supplementary corpus and remain subject to classification before they may contribute evidence.

## Goals / Non-Goals

**Goals:**

- Walk the verified official account history to its terminal cursor across multiple small, resumable ECS runs.
- Keep request volume deliberately low through hard batch caps, delay jitter, daily budgets, retries, and circuit breaking.
- Store canonical raw responses in the private OSS bucket before considering a fetch durable.
- Classify every discovered post into an explicit evidence, exclusion, missing-text, or review state.
- Incrementally parse eligible content in SQLite staging and reconcile it into RDS without duplicate evidence identities.
- Produce reports that prove inventory completeness, batch pacing, failure handling, OSS persistence, and RDS count agreement.
- Prepare a disabled-by-default systemd timer for later incremental synchronization.

**Non-Goals:**

- Running planned production collection on the developer workstation.
- Adding a host-specific marker that makes local network execution technically impossible.
- Downloading or redistributing video binaries.
- Generating speech-to-text when an official subtitle is absent.
- Completing Wiki character, quest, or readable discovery.
- Publishing the application or database to the Internet.
- Replacing the application read path with PostgreSQL in this change.
- Running recovery drills or synthetic scale benchmarks.

## Decisions

### Use ordinary collection commands under an ECS operating convention

Discovery and fetching remain ordinary network commands without an extra activation flag. Deployment documentation and operator procedures run them from the retained ECS host. The implementation does not inspect machine identity, require a root-managed marker, or otherwise attempt to enforce the workstation preference technically.

Alternative: require an explicit network flag, `/etc/hksr/collector-enabled`, instance metadata, a hostname check, or an `HKSR_COLLECTION_ENV=ecs` variable. Rejected because the user wants a remembered workflow convention, not additional technical protection.

### Separate discovery, fetch, parse, and RDS reconciliation

Discovery stores only verified metadata and the next cursor. Body fetching is a separate bounded command; parsing and RDS reconciliation operate only on already stored content. Each stage records a run ID and can resume without repeating completed work.

Alternative: one command walks all pages and downloads every body. Rejected because it creates request bursts, makes interruption recovery unclear, and conflicts with the user's M7B pacing requirement.

### Use conservative hard defaults

- Discovery reads at most two 20-item pages per invocation.
- Body fetching processes at most ten posts per invocation.
- Requests wait a random 15–30 seconds between attempts.
- The shared daily network budget defaults to 60 successful or failed requests.
- A request receives at most three attempts with exponential backoff and `Retry-After` support.
- Three consecutive remote failures open a circuit breaker and stop the run.

Operators may lower these values. Raising a per-run cap or daily budget requires an explicit override recorded in the run report; scheduled units always use defaults. Initial M7B batches are launched manually and reviewed before the next batch.

For the 2026-09-03 initial M7B inventory, the user first approved a 300-request UTC daily budget and then explicitly removed the daily total limit. The initial-inventory override uses `0` to mean unlimited while retaining request accounting, the 15–30 second interval, ten-body invocation cap, retry limit, and circuit breaker. The ECS private environment records this override; the application and unattended recurring timer retain the 60-request default when no override is supplied.

Alternative: maximize throughput until rate limiting occurs. Rejected because endpoint stability is not guaranteed and speed is not an acceptance objective.

### Persist cursor and item state in ECS-local SQLite

Add collection runs, account checkpoints, request budgets, source dispositions, fetch attempts, and raw-object manifests to the existing staging database. Cursor updates and discovered items commit atomically after each successful page. An OS file lock prevents overlapping collector runs.

SQLite builds differ across the workstation and ECS. When a transported FTS5 table references an unavailable tokenizer, initialization removes only that derived FTS table and its triggers, compacts the freed pages, and rebuilds the index with the locally supported tokenizer. Source, document, chunk, checkpoint, and raw-object tables remain untouched, and deployment takes a database backup before the first repair.

Alternative: store operational state only in RDS. Rejected for the first full crawl because a local durable spool simplifies pause/resume and avoids coupling every source request to database availability.

### Make OSS persistence part of fetch completion

Canonical JSON is written to a protected local spool, hashed, and uploaded through the ECS RAM role to a deterministic private OSS object key. The manifest records the hash and object version metadata without credentials or provider resource identifiers in committed reports. A source becomes `fetched` only after local hash verification and successful OSS upload.

Alternative: save raw responses only on the ECS disk. Rejected because the host is now a runtime machine rather than the durable raw-data layer.

### Default uncertain material to review, never evidence

Official identity is mandatory but not sufficient for evidence eligibility. Deterministic classification rules may exclude known operational/community categories; unknown or ambiguous items enter `manual_review`. Videos without official machine-readable text enter `missing_official_text`. Neither state contributes chunks or RDS evidence.

Alternative: index every post from the official account. Rejected because announcements and community operations are not necessarily lore evidence.

### Skip permanent non-zero body responses

An HTTP-successful body response with a non-zero Miyoushe business `retcode` is recorded as `excluded_unavailable`, including only the bounded return code in the sanitized batch report. The source status becomes `skipped`, contributes no raw object or evidence, and is not retried. This follows the user's explicit instruction to skip every non-zero business response. Transport failures, retryable HTTP responses, OSS failures, and circuit-breaker events remain real failures and still stop the guarded batch workflow.

### Reuse SQLite-to-RDS reconciliation with generalized batch IDs

Extend the guarded real-import batch format to accept M7 collection batch IDs. Each reviewed fetch batch is parsed, indexed, imported, and audited separately. Stable source/content keys remain the identity boundary, and rerunning the same batch must not add rows.

### Install scheduling but leave it disabled

Provide a systemd oneshot unit and timer with locking, request budgets, and journal logging. The timer is installed disabled during M7A/M7B. It is enabled only after the complete initial inventory, at least three clean manual batches, and explicit user approval.

## Risks / Trade-offs

- **[Miyoushe changes undocumented response fields or cursor behavior]** → Validate response contracts, retain the last good checkpoint, stop instead of guessing, and quarantine the new payload shape for review.
- **[The account contains far more posts than the old estimate]** → Bound request rate, batch size, retries, and consecutive failures; report inventory growth and never convert the estimate into an automatic completion target.
- **[HTTP 429 or anti-automation response]** → Honor `Retry-After`, open the circuit breaker, and require a later manual resume; do not rotate identities or evade controls.
- **[A process stops after OSS upload but before database commit]** → Use deterministic object keys and content hashes so replay is safe.
- **[OSS RAM role is too broad]** → Restrict it to the one private bucket and the M7 prefix; reject static AccessKeys.
- **[Classification rules discard useful evidence]** → Store excluded metadata and reasons, make rules versioned, and support later human reclassification without refetching unchanged bodies.
- **[Official videos lack subtitles]** → Record `missing_official_text`; do not infer dialogue from titles, comments, or generated transcripts.
- **[Serverless RDS transport is non-SSL]** → Continue only across the existing same-VPC private path under the user's recorded risk acceptance; do not create a public endpoint.
- **[Content caching and redistribution have policy implications]** → Keep raw data private and limit this change to internal evidence processing; public use requires a separate compliance review.

## Migration Plan

1. Add deterministic unit tests for cursor walks, budgets, locking, classification, object manifests, and import batch IDs without real source access.
2. Add collection state migrations and the bounded discovery and fetching commands.
3. Add OSS upload through the ECS RAM role and verify it with one non-sensitive probe object.
4. Deploy to ECS and run M7A discovery for at most two pages and fetch at most ten bodies from the documented cloud working directory.
5. Review the M7A report, classification results, raw-object hashes, parser failures, and RDS reconciliation before continuing.
6. Run M7B in repeated two-page discovery and ten-body fetch batches under the explicitly authorized initial-inventory budget mode. Audit every generated batch report.
7. Continue until the official listing reports its terminal cursor and every discovered item has a disposition.
8. Complete M7C reconciliation, search sampling, reports, and three clean incremental no-change runs.
9. Install the timer disabled; enable it only after explicit approval.

Rollback disables the timer, stops future collection, and retains checkpoints and private raw objects for diagnosis. Database rollback, if explicitly requested, targets only the recorded M7 batch/source identities; it never drops the shared schema or deletes older M6 evidence.

## Open Questions

- Which exact forum/channel/category identifiers reliably separate lore material from operational announcements after the M7A sample is observed?
- Does the existing ECS instance have an attachable RAM role with only the required OSS prefix permissions, or must one be created in the console?
- What long-term incremental frequency is appropriate after the initial account inventory: daily or every three days?
