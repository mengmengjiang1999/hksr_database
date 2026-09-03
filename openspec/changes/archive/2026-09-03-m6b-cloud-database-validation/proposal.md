## Why

M6A established that the first-round corpus fits comfortably in PostgreSQL, but capacity formulas do not prove that the selected mainland-China managed database supports the required extensions, stable evidence identities, or real-evidence migration. A purchased Alibaba Cloud RDS PostgreSQL 18 Serverless instance and same-VPC ECS host in Shanghai now provide the environment for that proof and for continued cloud development. Performance, synthetic scale validation, and recovery drills are deferred until corpus size or operational requirements make them relevant.

## What Changes

- Add a reproducible PostgreSQL schema and migration path for sources, documents, chunks, embeddings, entities, relations, evidence bindings, and ingestion state.
- Validate `pgvector` plus available Chinese lexical-search extensions on the purchased PostgreSQL 18 Serverless Basic instance.
- Retain deterministic fixture and benchmark tooling for a later opt-in capacity exercise, but do not execute it or make it an M6B acceptance gate.
- Add an idempotent import path for the currently collected official SQLite corpus and future incremental updates, preserving evidence identities and provenance.
- Record procurement-time configuration and observed RDS storage measurements without storing credentials.
- Deploy and smoke-test the application on the retained same-VPC ECS host while keeping it private.
- Record the same-region OSS purchase for future collection artifacts without making a restore drill an M6B gate.
- Import only official material already collected by the evidence pipeline; completing the planned corpus remains a later stage.

## Capabilities

### New Capabilities

- `cloud-database-validation`: Reproducible validation of the selected mainland-China PostgreSQL/pgvector deployment, including extensions, schema portability, real-evidence migration, security, and private application execution.

### Modified Capabilities

None.

## Impact

- Adds PostgreSQL migration, real-evidence import, optional fixture/benchmark, and validation modules and CLI commands.
- Adds an optional PostgreSQL client dependency and environment-based connection configuration.
- Adds versioned M6B configuration and result artifacts with secrets excluded.
- Exercises the user-provisioned Alibaba Cloud RDS PostgreSQL 18 Serverless instance and retained same-VPC ECS host; cloud mutations remain limited to the M6B resources explicitly placed in scope.
- Does not replace the SQLite local demo during M6B and does not change the evidence-grounding contract.
