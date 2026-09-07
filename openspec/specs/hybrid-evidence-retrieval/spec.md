# hybrid-evidence-retrieval Specification

## Purpose
TBD - created by archiving change m2-hybrid-evidence-retrieval. Update Purpose after archive.
## Requirements
### Requirement: Entity and alias matching
The system SHALL recognize curated canonical entities and aliases in questions and evidence, while player aliases MUST NOT be treated as factual evidence.

#### Scenario: Official alias appears in a question
- **WHEN** a question uses an official alias for a known character
- **THEN** evidence linked to the canonical character receives an entity-match signal

### Requirement: Local semantic retrieval
The system SHALL build and query a reproducible local semantic index without requiring a network service.

#### Scenario: Question wording differs from evidence
- **WHEN** a question shares semantic character features with an official passage but not an exact sentence
- **THEN** semantic mode returns a similarity-ranked evidence list

### Requirement: Explainable hybrid ranking
Every hybrid result MUST expose lexical, semantic, entity, section and source-quality score components.

#### Scenario: Hybrid search returns evidence
- **WHEN** the user searches in hybrid mode
- **THEN** every result includes the total score and all component scores

### Requirement: Pre-ranking evidence filters
The system SHALL filter candidates by source kind, version and context type before ranking.

#### Scenario: In-game context is requested
- **WHEN** a search limits context to `in_game`
- **THEN** promotional and official-supplement candidates are absent from results

### Requirement: Repeatable retrieval evaluation
The system MUST calculate Top 1 accuracy, Top 5 recall and unanswerable accuracy from a versioned evidence-labelled dataset.

#### Scenario: Evaluation command is run
- **WHEN** the dataset contains answerable and unanswerable questions
- **THEN** the report separates retrieval metrics from unanswerable detection metrics

### Requirement: Evidence-sized dialogue chunks
The system SHALL bound evidence chunks and SHALL record only explicitly labelled dialogue speakers.

#### Scenario: Quest dialogue contains speaker labels
- **WHEN** a chunk contains lines in `speaker：dialogue` form
- **THEN** the named speakers are stored and searchable without inferring omitted speakers

### Requirement: Deterministic question intent
The system SHALL classify supported questions into identity, playable-form, relation, acquisition, temporal, descriptive, comparison, or unknown intent before ranking evidence.

#### Scenario: User asks what relationship two names have
- **WHEN** a question has the form `A 和 B 有什么关系`
- **THEN** retrieval emits relation intent with separately resolved left and right entity candidates

### Requirement: Exact form resolution and ambiguity
Exact playable-form names MUST resolve before broader narrative-person aliases, and unresolved collisions MUST be returned as ambiguity rather than silently merged.

#### Scenario: Question names an alternate playable form
- **WHEN** the query contains the exact official form name `姬子·启行`
- **THEN** retrieval resolves that playable form and may expand to its narrative person without replacing the exact match

### Requirement: Relation endpoint coverage
Evidence ranked for a relation question MUST support both resolved endpoints or an approved evidence-backed relation connecting them.

#### Scenario: Top character profile mentions only one endpoint
- **WHEN** the highest generic similarity result contains only one side of a two-entity relation question
- **THEN** it cannot by itself produce a relation answer and the system continues retrieval or refuses

### Requirement: Failure-classified evaluation
Retrieval evaluation MUST classify failures as corpus missing, parse or chunk error, entity-resolution error, intent error, ranking miss, ambiguity, or correct no-answer behavior.

#### Scenario: Expected evidence has not yet been collected
- **WHEN** a labelled question references an official page still in discovered state
- **THEN** the report records a corpus gap instead of counting it as an unexplained ranking regression

### Requirement: Bounded candidate reranking
The system MUST use indexed lexical and resolved-entity candidates before loading semantic vectors, and MUST NOT deserialize or score the entire eligible corpus for one interactive query.

#### Scenario: Wiki corpus grows beyond ECS memory budget
- **WHEN** an interactive query is evaluated against a large collected corpus
- **THEN** semantic and entity reranking loads at most the configured candidate bound while preserving exact-entity candidates and score diagnostics
