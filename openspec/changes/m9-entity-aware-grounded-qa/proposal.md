## Why

The growing Wiki corpus can retrieve related text, but the current extractive baseline does not understand question intent or distinguish a narrative person from separate playable forms. This causes relation questions such as “姬子和姬子·启行有什么关系” to return a character profile instead of a direct, evidence-backed answer, so answer quality work should proceed in parallel with M7 collection.

## What Changes

- Model narrative people separately from playable forms, official names, and player-facing shorthand without presenting community terminology as official evidence.
- Add deterministic question-intent and entity-resolution behavior for identity, playable-form, relation, acquisition, temporal, descriptive, and unanswerable questions.
- Build a versioned real-question evaluation set and diagnostics that separate corpus gaps, retrieval misses, entity ambiguity, answer-generation failures, and correct refusals.
- Require relation retrieval to cover both resolved endpoints or explicitly refuse when the current evidence does not support the requested relation.
- Add a provider-neutral constrained generation interface that receives only the current official evidence package and emits structured claims with evidence IDs.
- Validate every generated claim with the existing deterministic grounding boundary, falling back to the extractive baseline when generation is disabled, unavailable, invalid, or times out.
- Extend the private UI and API to return a concise direct answer, evidence status, identity/form explanation, claim-level citations, and safe failure or ambiguity states.
- Keep M7 collection independent and running; final full-corpus ranking thresholds and acceptance remain gated on sufficient Wiki ingestion.

## Capabilities

### New Capabilities

- `narrative-entity-model`: Represents narrative identities, playable forms, official aliases, and evidence-backed links between them.
- `constrained-answer-generation`: Generates natural answers only from retrieved official evidence and passes structured claims through deterministic validation and fallback rules.

### Modified Capabilities

- `hybrid-evidence-retrieval`: Adds intent-aware retrieval, exact form resolution, endpoint coverage for relation questions, ambiguity reporting, and failure diagnostics.
- `evidence-grounded-answering`: Extends the grounding contract from a single extractive excerpt to validated multi-claim answers while preserving refusal, inference, conflict, and citation rules.
- `evidence-backed-relations`: Adds narrative-identity and playable-form predicates without turning aliases or co-occurrence into unsupported facts.
- `local-knowledge-app`: Extends the ask API and private interface with direct-answer, resolved-entity, intent, ambiguity, fallback, and generation metadata.

## Impact

- Affects entity and relation storage, curated catalogs, retrieval ranking, question answering, API response contracts, the private web interface, evaluation fixtures, and ECS configuration for an optional model provider.
- Introduces an optional outbound model dependency, but no model credential is stored in Git, SQLite, reports, or browser responses.
- Does not stop or alter M7 request pacing, expose the application publicly, fine-tune a model, permit model-memory facts, or make full-corpus acceptance claims before collection is sufficiently complete.
