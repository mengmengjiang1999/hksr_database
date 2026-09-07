# constrained-answer-generation Specification

## Purpose
TBD - created by archiving change m9-entity-aware-grounded-qa. Update Purpose after archive.
## Requirements
### Requirement: Retrieved evidence is the complete generation boundary
The generator MUST receive only the question, resolved intent and entities, allowed presentation instructions, and the official evidence retrieved for the current request.

#### Scenario: Model knowledge contains an uncited fact
- **WHEN** a model could answer from pretrained memory but the current evidence package does not contain the fact
- **THEN** the generated result contains no such factual claim and the system refuses or answers only the supported portion

### Requirement: Provider-neutral structured generation
The system SHALL expose a replaceable model adapter whose response is validated against a versioned schema containing claim type, claim text, evidence IDs, and exact supporting spans.

#### Scenario: A configured provider returns prose instead of the schema
- **WHEN** the model response cannot be parsed as the required structured result
- **THEN** the response is rejected and the request uses the deterministic fallback

### Requirement: Deterministic post-generation validation
Every generated factual claim MUST pass the existing evidence-membership, support, inference, conflict, and citation checks before it can appear in an answer.

#### Scenario: Generated claim cites unrelated retrieved evidence
- **WHEN** its supporting span is absent from the cited evidence or its evidence requirements are incomplete
- **THEN** the claim is removed with a machine-readable rejection reason

### Requirement: Safe fallback behavior
The system MUST fall back to deterministic intent templates or the extractive baseline when generation is disabled, unavailable, invalid, or exceeds its timeout.

#### Scenario: Model request times out
- **WHEN** the configured generation deadline expires
- **THEN** the user still receives a validated extractive answer or an evidence-insufficient response without an uncaught service error

### Requirement: Secret-free generation observability
Generation logs MUST record provider-neutral model identity, prompt version, latency, token usage, outcome and validation counts without credentials, full raw evidence, or private configuration.

#### Scenario: Generation succeeds on ECS
- **WHEN** operational metadata is recorded
- **THEN** it is sufficient to compare cost and reliability while containing no model secret or private evidence body
