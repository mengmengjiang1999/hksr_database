## Why

The database and private ECS deployment are ready, but the evidence corpus still contains only five sample sources and the current Miyoushe discovery path has not completed the official account history. The next stage will collect official material safely and incrementally on ECS without a large burst of requests; local execution is avoided by operating procedure rather than a host-specific lock.

Miyoushe Wiki remains the primary official evidence source. The verified official-account history collected by this change is supplementary and does not replace or outrank Wiki evidence.

## What Changes

- Add resumable cursor-based discovery that walks the verified official Miyoushe account to its reported last page.
- Document ECS as the intended runtime for ordinary collection commands without adding a host restriction or an extra network-activation flag.
- Add conservative pacing, small batches, jitter, backoff, retry budgets, pause/resume controls, and a single-run lock.
- Allow a recorded ECS-only unlimited daily-budget override for the initial inventory while preserving the 15–30 second request interval, bounded batches, circuit breaker, and the 60-request safe default.
- Separate metadata discovery from body fetching so M7B can inventory slowly before downloading content in bounded batches.
- Persist raw canonical responses and a content-hash manifest to the private OSS data layer without storing video binaries.
- Classify discovered items as eligible evidence, excluded operational/community content, permanently unavailable remote content, missing-text video, or manual review; never manufacture missing subtitles.
- Generalize cloud import batch identifiers beyond M6B and incrementally reconcile eligible SQLite staging data into RDS with per-batch audits.
- Add a disabled-by-default systemd timer for later incremental synchronization after the initial inventory is reviewed.
- Keep the application and RDS private; operational commands and runbooks launch real collection on ECS rather than the developer workstation.

## Capabilities

### New Capabilities
- `cloud-miyoushe-ingestion`: Cloud-operated, slowly paced, resumable discovery, raw snapshot storage, classification, incremental RDS reconciliation, and scheduled synchronization of verified Miyoushe official content.

### Modified Capabilities
- `official-source-ingestion`: Extend official-source discovery from bounded sample pages to a complete cursor walk with explicit terminal, exclusion, and review states.

## Impact

- Affects the collector pipeline, CLI, source and batch state, OSS integration, PostgreSQL import validation, deployment scripts, systemd configuration, reports, and tests.
- Real network execution is launched from the ECS deployment directory by procedure; local work uses deterministic fixtures and mocked responses, without a host-specific technical prohibition.
- Requires an ECS RAM role scoped to the designated private OSS bucket. No AccessKey is stored in the repository or deployment environment.
- Initial M7B operation remains manually started and deliberately slow; the recurring timer is enabled only after batch audit acceptance.
- Video media download, speech-to-text generation, Wiki full-channel collection, public serving, and recovery drills remain out of scope.
