## Context

M6A projected roughly 7,120 first-round chunks and about 1.67 GiB for a deliberately conservative 100,000-chunk PostgreSQL scenario. The local demo still uses SQLite and deterministic sparse vectors. The selected proof-of-concept environment is Alibaba Cloud RDS PostgreSQL 18 Serverless Basic in `cn-shanghai`, with 0.5–4 RCU, 20 GiB high-performance cloud disk, a private VPC address, and automatic pause enabled. The instance and an empty `hksr` database already exist; credentials are user-held and must never enter repository artifacts.

M6B must establish observed compatibility and a safe incremental path for real official evidence before the project commits to PostgreSQL for the growing corpus. The retained ECS host becomes the development, test, and deployment environment. Console-only configuration remains operator-attested, while restore drills are explicitly deferred.

## Goals / Non-Goals

**Goals:**

- Prove PostgreSQL 18 extension availability and creation for vector and Chinese lexical retrieval.
- Provide an idempotent schema that preserves the existing stable evidence identity contract.
- Import the currently collected official corpus and verify counts, provenance, stable identities, and idempotent incremental behavior.
- Verify private connectivity, least privilege, automatic-pause cost controls, and private application execution on ECS.
- Produce a machine-readable report whose measurements can be reproduced without exposing secrets.

**Non-Goals:**

- Replacing SQLite as the default local application database.
- Completing collection of every planned official source or publishing a public application.
- Treating synthetic benchmark text as official evidence.
- Selecting a production high-availability topology or final RPO/RTO.
- Running RDS backup restoration or OSS historical-version restoration drills.
- Creating an independent vector database, search cluster, or graph database.

## Decisions

### Validate PostgreSQL 18 as purchased

Use the live purchased major version instead of preserving M6A's PostgreSQL 17 planning assumption. Alibaba Cloud's current extension catalog lists PostgreSQL 18 support for pgvector, pg_jieba, zhparser, and pg_bigm. The actual instance remains the final source of truth through `pg_available_extensions` and extension-creation probes.

Alternative: recreate on PostgreSQL 17. Rejected unless an acceptance-critical extension fails on 18, because downgrading requires a replacement instance and the current catalog gives no compatibility reason to do so.

### Keep the proof private

Run SQL through DMS for initial probes and from the retained same-VPC ECS host for repeatable imports and application execution. Do not create an RDS public endpoint. The host receives least-privilege credentials through a protected runtime environment and remains the project's development, test, and deployment machine.

Alternative: whitelist the developer's public IP. Rejected because it weakens the architecture being tested and makes network results less representative.

### Separate migrations, probes, and operator evidence

Version SQL migrations in the repository. A Python validation command connects using `HKSR_POSTGRES_DSN`, runs read-only probes by default, and requires an explicit flag for schema or fixture mutation. Console-only settings and cloud application results are recorded in sanitized evidence without instance IDs, endpoints, usernames, passwords, tokens, or AccessKeys.

Alternative: put all steps in a shell script or console runbook. Rejected because it would be difficult to unit-test, reproduce, and safely separate destructive fixture cleanup from observation.

### Isolate synthetic scale data

Keep the implemented generated-fixture path isolated in a dedicated validation schema with a run identifier and `synthetic = true`, but defer executing it. If capacity testing is requested later, validation rows cannot be returned by application evidence queries and cleanup must target one explicit run identifier.

### Compare approximate search with an exact oracle

Retain deterministic exact/HNSW comparison and concurrency tooling for a later explicit performance stage. M6B does not execute the synthetic benchmark or claim a latency/recall gate.

### Import real evidence incrementally

Treat the local SQLite evidence database as the migration source for the current official corpus. Upsert sources, documents, chunks, entities, aliases, evidence links, relations, relation evidence, and ingestion state in dependency order. Preserve stable external keys and evidence IDs, reject synthetic rows, verify source/document/chunk counts after import, and make a repeated import produce no duplicates. Use a dedicated ingestion credential for writes and retain a separate read-only runtime credential.

### Treat Chinese lexical extensions as experiments

Verify all advertised candidates, including required preload settings, but retain character n-gram retrieval as the portable baseline. The report selects a Chinese lexical strategy only from measured retrieval quality and operational complexity; plugin availability alone does not decide it.

## Risks / Trade-offs

- **[Serverless cold starts distort latency]** → Record cold-start latency separately, hold the instance awake for the timed run, and re-enable automatic pause afterward.
- **[0.5 RCU cannot build HNSW efficiently]** → Permit scaling up to the already capped 4 RCU and record build duration and peak RCU; do not raise the cap without approval.
- **[Preloaded Chinese extensions require restart]** → Change only documented parameters, schedule one controlled restart, and capture before/after values.
- **[Current real corpus is small]** → Treat the first import as a migration/integrity gate, not a performance claim; repeat incremental imports as official collection grows.
- **[Storage auto-expansion creates lasting cost]** → Check free space before import, stop before projected use approaches 20 GiB, and record actual relation sizes.
- **[Cloud-console evidence is not automatically reproducible]** → Require dated, sanitized attestations without credentials or provider resource IDs.
- **[Basic series is not production HA]** → Treat recovery results as a PoC gate only; production topology remains a later decision.
- **[Serverless does not support RDS PostgreSQL SSL]** → Keep ECS and RDS in the same private VPC, do not expose either database or application publicly, require explicit user acceptance for non-SSL transport, and require TLS again if the database topology changes.

## Migration Plan

1. Probe server version, extensions, connection encryption, roles, and database settings through DMS.
2. Configure preload requirements and create accepted extensions in `hksr`.
3. Create the versioned schemas with an owner role and a separate least-privilege runtime role.
4. Run local unit tests for SQL rendering, fixture determinism, report validation, and safety gates.
5. Configure the retained same-VPC ECS host, inject the DSN outside Git, and run migration/probe commands.
6. Upload the current local SQLite evidence database to the private runner, import only official rows with stable upserts, and verify counts and idempotency.
7. Verify the read-only runtime role can query official evidence while the ingestion role alone can write it.
8. Deploy the application privately on ECS and run health, read-only database, and restart smoke tests.
9. Confirm automatic pause remains configured and archive M6B if all migration gates pass.

Rollback consists of removing only imported rows identified by stable source keys when explicitly requested, revoking temporary ingestion/runtime roles, reverting preload parameters if they are not retained, and releasing only explicitly identified temporary resources. The purchased RDS instance is not released as part of an automated rollback.

## Open Questions

- Does PostgreSQL 18 Serverless Basic expose every catalog-listed Chinese extension on the purchased kernel build?
- Which process manager and private access path should the retained ECS deployment use before a public application stage is authorized?
