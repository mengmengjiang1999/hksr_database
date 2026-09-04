## MODIFIED Requirements

### Requirement: Official source identity
The system MUST treat Miyoushe Wiki content registered by official content ID as the primary official evidence source. It MUST treat official-account posts as supplementary and accept them as evidence only when both the post and publisher carry official verification. Every rejected Miyoushe listing item MUST retain a non-evidence disposition and reason for inventory accounting.

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

### Requirement: Complete Wiki game-catalog access list
The system MUST discover every item under the official Wiki `游戏图鉴` root, register one source per unique official `content_id`, and exclude separate editorial guide channels. Characters, light cones, relics, enemies, achievements, furniture, all task types, outfits, materials, consumables, task items, valuables, end-game modes, Simulated Universe data, events, readables, special items, shops, collectibles, and other in-game catalog categories MUST be included.

#### Scenario: One content ID appears in multiple catalog channels
- **WHEN** the Wiki directory lists the same official content ID in two or more included channels
- **THEN** the access list contains one source with a deterministic primary category and reports the duplicate channel occurrences

#### Scenario: The catalog is discovered again after a game update
- **WHEN** a later ECS discovery receives existing and newly added official content IDs
- **THEN** existing fetched or parsed state remains intact and only new IDs expand the access list

#### Scenario: Editorial guides are outside the game catalog
- **WHEN** a Wiki channel is a separate editorial guide channel rather than a child of the `游戏图鉴` root
- **THEN** it is not registered by the game-catalog discovery command
