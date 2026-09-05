## 1. Real-question baseline

- [x] 1.1 Define the versioned intent and failure taxonomy, including corpus gaps, parsing defects, entity ambiguity, ranking misses, generation failures, and correct refusals.
- [x] 1.2 Create an initial 50–100 case real-question dataset with evidence expectations and explicit pending-corpus cases.
- [x] 1.3 Add corpus snapshot fingerprints and a deterministic baseline report for the current ECS staging data.

## 2. Narrative identity model

- [x] 2.1 Add versioned storage for narrative people, playable forms, typed names, and stable form-to-person links.
- [x] 2.2 Implement a transactional migration and integrity audit for existing entities, aliases, evidence links, and approved relations.
- [x] 2.3 Curate and test the first identity case for `姬子`, base `姬子`, and `姬子·启行`, keeping `SP` explicitly player-facing.
- [x] 2.4 Extend entity browsing and indexing so exact playable forms remain distinct while controlled person expansion is available.

## 3. Intent-aware retrieval

- [x] 3.1 Implement deterministic Chinese intent detection and a structured query plan for identity, playable-form, relation, acquisition, temporal, descriptive, comparison, and unknown questions.
- [x] 3.2 Implement exact-form-first entity resolution, punctuation normalization, endpoint preservation, and explicit ambiguity results.
- [x] 3.3 Add relation retrieval that requires both endpoints or an approved connecting relation before forming an answer.
- [x] 3.4 Add Wiki-primary source weighting, evidence diversification, score diagnostics, and failure-classified retrieval evaluation.

## 4. Deterministic direct answers

- [x] 4.1 Add evidence-backed direct templates for identity, playable-form, approved relation, acquisition, and temporal intents.
- [x] 4.2 Add partial-answer and ambiguity behavior that separates supported conclusions from unsupported question parts.
- [x] 4.3 Preserve the existing extractive baseline as the generic fallback and verify claim-level citation compatibility.

## 5. Constrained generation

- [x] 5.1 Define the provider-neutral evidence packet, structured response schema, prompt version, timeout, and model adapter interface.
- [x] 5.2 Implement exact supporting-span, evidence-membership, inference, conflict, and unsupported-claim validation for generated drafts.
- [x] 5.3 Implement disabled, timeout, provider-error, invalid-schema, empty-validation, and policy-rejection fallbacks.
- [x] 5.4 Add secret-free usage telemetry, bounded validated-result caching, and deterministic fake-adapter tests without network access.

## 6. API and private interface

- [x] 6.1 Extend `POST /api/ask` compatibly with intent, resolved entities, ambiguity, partial support, generation outcome, and fallback fields.
- [x] 6.2 Render concise direct answers, narrative identity, playable forms, player terminology, and per-claim official citations in the private UI.
- [x] 6.3 Add API and browser regression tests for successful generation, deterministic fallback, ambiguity, partial answer, refusal, and legacy responses.

## 7. Validation and ECS rollout

- [x] 7.1 Run the full offline suite, strict OpenSpec validation, schema migration audit, evidence-link audit, and secret scan.
- [x] 7.2 Deploy deterministic entity, intent and direct-answer behavior to ECS behind a reversible feature flag and compare the real-question baseline.
- [ ] 7.3 Configure one optional private model trial without committing credentials, verify timeout and fallback, and record latency and usage limits.
- [x] 7.4 Re-run the versioned evaluation as Wiki coverage grows and defer final retrieval thresholds until the M7 corpus is sufficiently complete.

## 8. Interactive retrieval scalability

- [x] 8.1 Replace per-request full-corpus vector loading with bounded FTS and resolved-entity candidate loading.
- [x] 8.2 Add interactive retrieval concurrency protection and a finite browser request deadline.
- [x] 8.3 Add regression coverage for bounded candidate loading, busy responses, and browser timeout behavior.
- [x] 8.4 Run focused retrieval/API tests, the full offline suite, strict OpenSpec validation, and an ECS large-corpus latency and memory check.
