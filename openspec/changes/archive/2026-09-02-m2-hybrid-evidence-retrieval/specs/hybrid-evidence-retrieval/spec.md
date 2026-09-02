## ADDED Requirements

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
