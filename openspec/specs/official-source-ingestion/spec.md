# official-source-ingestion Specification

## Purpose
TBD - created by archiving change m1-local-data-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Official source identity
The system MUST treat Miyoushe Wiki content registered by official content ID as the primary official evidence source. It MUST treat official-account posts as supplementary and accept them as evidence only when both the post and publisher carry official verification. Every rejected Miyoushe listing item MUST retain a non-evidence disposition and reason for inventory accounting.

#### Scenario: Unverified post is discovered
- **WHEN** an account listing contains a post without official status or certification
- **THEN** the system excludes that post from registered evidence sources and records an unverified exclusion reason

### Requirement: Complete official-account inventory
The system MUST support a cursor-based Miyoushe official-account scan that can resume across bounded runs and can prove completion only from the upstream terminal condition rather than an expected historical count.

#### Scenario: A bounded discovery run stops before the terminal page
- **WHEN** the invocation reaches its configured page cap while the upstream listing has a next cursor
- **THEN** the inventory remains incomplete and stores the cursor required by the next ECS run

#### Scenario: New posts appear after a completed inventory
- **WHEN** a later incremental scan discovers previously unseen official post IDs
- **THEN** it registers only the new identities while preserving the completed historical checkpoint and existing source identities

### Requirement: Complete Wiki game-catalog access list
The system MUST discover every item under the official Wiki `游戏图鉴` root, register one source per unique official `content_id`, and exclude separate editorial guide channels. Characters, light cones, relics, enemies, achievements, furniture, all task types, outfits, materials, consumables, task items, valuables, end-game modes, Simulated Universe data, events, readables, special items, shops, collectibles, and other in-game catalog categories MUST be included.

#### Scenario: One content ID appears in multiple catalog channels
- **WHEN** the Wiki directory lists the same official content ID in two or more included channels
- **THEN** the access list contains one source with a deterministic primary category and reports the duplicate channel occurrences

#### Scenario: The catalog is discovered again after a game update
- **WHEN** a later ECS discovery receives existing and newly added official content IDs
- **THEN** existing fetched or parsed state remains intact and only new IDs expand the access list

#### Scenario: Existing Wiki content is rechecked after a game update
- **WHEN** a controlled refresh fetches an already parsed content ID
- **THEN** the system advances a resumable refresh checkpoint, leaves matching content hashes parsed without another OSS upload, and sends only changed content through private persistence, parsing, and RDS reconciliation

#### Scenario: Editorial guides are outside the game catalog
- **WHEN** a Wiki channel is a separate editorial guide channel rather than a child of the `游戏图鉴` root
- **THEN** it is not registered by the game-catalog discovery command

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
