# cloud-miyoushe-ingestion Specification

## Purpose

Define the safe, resumable, private, and observable cloud workflow for collecting verified Miyoushe official-account and Wiki content, persisting raw snapshots, and reconciling eligible evidence into RDS.

## Requirements

### Requirement: Cloud-operated collection workflow
The system SHALL expose ordinary network-capable Miyoushe discovery and fetching commands without an extra activation flag, host-specific marker, or machine-identity check. Deployment documentation and operating procedures SHALL run real collection from the retained ECS deployment directory.

#### Scenario: Documented real collection is launched
- **WHEN** an operator follows the production runbook to invoke discovery or fetching
- **THEN** the ordinary command runs from the ECS deployment directory without requiring an activation flag or checking machine identity

### Requirement: Conservatively paced batches
The collector MUST enforce bounded discovery and fetch batches, request delay jitter, a shared daily request budget, finite retries, and a consecutive-failure circuit breaker.

#### Scenario: A default M7B fetch batch runs
- **WHEN** an operator starts one fetch invocation without overrides
- **THEN** no more than ten post bodies are attempted, requests wait 15–30 seconds apart, and the shared daily total cannot exceed 60 requests

#### Scenario: An approved unlimited initial-inventory override runs
- **WHEN** an operator supplies the recorded zero-valued M7B daily-budget override from the ECS private configuration
- **THEN** discovery and fetching continue recording every request without a daily-total cutoff while retaining the default 15–30 second request delay, per-invocation caps, retry limit, and circuit breaker

#### Scenario: Remote failures repeat
- **WHEN** three consecutive source requests fail or a finite daily request budget is exhausted
- **THEN** the collector stops the run, preserves its checkpoint, and issues no further request until a later resume

### Requirement: Resumable terminal-cursor discovery
The collector MUST atomically persist each successful official-account page, its discovered item identities, and the next cursor, and MUST distinguish a paused checkpoint from a terminal account inventory.

#### Scenario: Discovery resumes after interruption
- **WHEN** a later ECS run resumes an incomplete account scan
- **THEN** it starts from the last committed cursor without duplicating previously discovered sources

#### Scenario: The listing reaches its final page
- **WHEN** the official API reports its terminal condition
- **THEN** the account checkpoint is marked complete with the observed item count and terminal timestamp

### Requirement: Portable derived SQLite index
The ECS staging database MUST preserve source data and collection checkpoints when its SQLite runtime cannot load a tokenizer used by a transported derived FTS index, and MUST rebuild only the derived FTS objects with a supported tokenizer.

#### Scenario: ECS cannot load a transported trigram index
- **WHEN** database initialization encounters `no such tokenizer` while opening the existing FTS table
- **THEN** it removes and rebuilds only the FTS table and triggers, retains all source and collection rows, and passes SQLite integrity validation

### Requirement: Durable private raw snapshots
Every successfully fetched body MUST be canonicalized, hashed, retained in the private local spool, and uploaded through the ECS RAM role to the designated private OSS prefix before the source is marked fetched.

#### Scenario: OSS upload fails
- **WHEN** a canonical response cannot be persisted to the private OSS prefix
- **THEN** the source remains pending or failed with its local hash recorded and is not parsed as durable evidence

### Requirement: Explicit content disposition
Every discovered official item MUST have one of the versioned dispositions `eligible_evidence`, `excluded_operational`, `excluded_unavailable`, `missing_official_text`, or `manual_review`, with a reason and classifier version.

#### Scenario: A body endpoint returns a non-zero business code
- **WHEN** an HTTP-successful Miyoushe body response has a non-zero `retcode`
- **THEN** the item is marked `excluded_unavailable` and `skipped`, the bounded return code is counted in the sanitized report, no raw body or evidence is persisted, and later fetch batches do not retry it

#### Scenario: An official video has no machine-readable official text
- **WHEN** its fetched response contains metadata but no official body or subtitle text
- **THEN** it is marked `missing_official_text` and contributes no generated transcript or factual evidence chunk

#### Scenario: Classification is ambiguous
- **WHEN** deterministic rules cannot establish evidence eligibility
- **THEN** the item enters `manual_review` and remains excluded from parsing and RDS evidence

### Requirement: Audited incremental RDS reconciliation
The workflow MUST reconcile only eligible parsed staging content into RDS under a unique M7 batch identifier and MUST report stable identities, source counts, evidence counts, synthetic row counts, and duplicate behavior for each batch.

#### Scenario: The same reviewed batch is reconciled twice
- **WHEN** an operator reruns an unchanged M7 batch
- **THEN** RDS row counts and stable evidence identities remain unchanged and the report marks the batch as repeated

#### Scenario: Periodic RDS reconciliation is temporarily unavailable
- **WHEN** a Wiki collection loop exhausts bounded retries for an intermediate RDS reconciliation while queued pages remain
- **THEN** it records a sanitized failure, continues durable local collection and OSS persistence, and still requires a successful final reconciliation before reporting completion

### Requirement: Disabled-by-default scheduling
The deployment SHALL provide a locked, observable systemd collection timer but MUST leave it disabled until the initial terminal inventory, three clean manual batches, and explicit user approval are recorded.

#### Scenario: M7B is deployed for its first manual batch
- **WHEN** the systemd units are installed on ECS
- **THEN** the service can be invoked manually while the recurring timer remains disabled

### Requirement: Secret-free collection observability
Each collection run MUST emit a sanitized report containing stage counts, pacing decisions, retry counts, checkpoint state, disposition totals, OSS persistence results, and RDS reconciliation results without cookies, credentials, private endpoints, raw bodies, or provider resource identifiers.

#### Scenario: A batch report is committed
- **WHEN** collection results are serialized for project review
- **THEN** the report contains operational measurements and hashes but no secret, endpoint, raw response, or account credential
