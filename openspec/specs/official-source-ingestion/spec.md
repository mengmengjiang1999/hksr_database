# official-source-ingestion Specification

## Purpose
TBD - created by archiving change m1-local-data-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Official source identity
The system MUST register Wiki content by official content ID and MUST accept Miyoushe posts as evidence only when the post and publisher carry official verification.

#### Scenario: Unverified post is discovered
- **WHEN** an account listing contains a post without official status or certification
- **THEN** the system excludes that post from registered evidence sources

### Requirement: Idempotent incremental ingestion
The system SHALL deduplicate sources and SHALL only request reparsing when stable official content changes.

#### Scenario: Unchanged source is fetched again
- **WHEN** a parsed source is fetched and its stable content fingerprint is unchanged
- **THEN** the system retains parsed status and does not duplicate documents or chunks

### Requirement: Traceable evidence storage
Every indexed chunk MUST identify its source, document section, position and original official page URL.

#### Scenario: Search result is returned
- **WHEN** a query matches an eligible chunk
- **THEN** the result includes the source identity, page URL, source type, section path and chunk text

### Requirement: Editorial content isolation
Wiki recommendations, guides, galleries, community commentary and similar editorial modules MUST NOT enter the formal evidence index.

#### Scenario: Character page contains guide modules
- **WHEN** an RPG page contains both character story and recommendation sections
- **THEN** story chunks are eligible and recommendation sections produce no evidence chunks

### Requirement: Diagnosable processing failures
Fetch or parse failures MUST be attached to the exact source and MUST NOT be silently discarded.

#### Scenario: Source parser rejects a payload
- **WHEN** a source response lacks required official content fields
- **THEN** the source enters error status with a diagnostic message
