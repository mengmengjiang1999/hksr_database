## MODIFIED Requirements

### Requirement: Official source identity
The system MUST register Wiki content by official content ID and MUST accept Miyoushe posts as evidence only when both the post and publisher carry official verification. Every rejected Miyoushe listing item MUST retain a non-evidence disposition and reason for inventory accounting.

#### Scenario: Unverified post is discovered
- **WHEN** an account listing contains a post without official status or certification
- **THEN** the system excludes that post from registered evidence sources and records an unverified exclusion reason

## ADDED Requirements

### Requirement: Complete official-account inventory
The system MUST support a cursor-based Miyoushe official-account scan that can resume across bounded runs and can prove completion only from the upstream terminal condition rather than an expected historical count.

#### Scenario: A bounded discovery run stops before the terminal page
- **WHEN** the invocation reaches its configured page cap while the upstream listing has a next cursor
- **THEN** the inventory remains incomplete and stores the cursor required by the next ECS run

#### Scenario: New posts appear after a completed inventory
- **WHEN** a later incremental scan discovers previously unseen official post IDs
- **THEN** it registers only the new identities while preserving the completed historical checkpoint and existing source identities
