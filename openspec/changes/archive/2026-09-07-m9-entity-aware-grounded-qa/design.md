## Context

M7 is collecting 5,292 unique Wiki pages on ECS while the M8 private browser already exposes a growing SQLite-backed corpus. The current question-answering baseline retrieves one highest-scoring chunk and returns an extractive excerpt. It can preserve citations but does not represent question intent, and the entity catalog currently treats some separately selectable character forms as ordinary aliases of one character. The first observed failure is `姬子` versus `姬子·启行`: gameplay exposes two units, narrative evidence describes one person, and player shorthand calls the latter an SP form.

This change must improve answer usefulness before full collection finishes without weakening the evidence boundary. M7 remains operationally independent, final ranking thresholds remain provisional until the corpus is sufficiently complete, and model credentials and raw prompts remain private ECS configuration.

## Goals / Non-Goals

**Goals:**

- Represent narrative people and playable forms without losing exact-name retrieval.
- Answer common intent classes directly and refuse unsupported relations.
- Build a real-question regression set that explains whether failures come from missing data, parsing, entity resolution, intent, ranking, generation, or validation.
- Add optional natural answer generation whose output cannot bypass deterministic evidence checks.
- Preserve claim-level citations, source priority, conflict handling and a deterministic fallback.

**Non-Goals:**

- Waiting for M7 to finish before development begins.
- Treating `SP` or other community shorthand as an official fact.
- Letting a model query the database freely, browse the Internet, use uncited memory, or write collection state.
- Fine-tuning a model, publishing the service, replacing SQLite with RDS, or declaring final full-corpus quality acceptance.
- Selecting or paying for a model provider, configuring provider credentials, or running a real private-provider trial; these require a separate future OpenSpec change and explicit approval.
- Automatically approving identity relations based only on name similarity or co-occurrence.

## Decisions

### Separate the person layer from the playable-form layer

Add stable typed entities for `narrative_person` and `playable_form`. Each playable form owns its exact official title and page identity and links to a person through reviewed evidence-backed relations. Punctuation variants such as `·` and `•` may normalize to the same form; a distinct official form title is not demoted to a plain alias.

Alternative: keep one character entity with all form names as aliases. Rejected because exact-form search, gameplay comparison and same-person questions become indistinguishable.

### Use deterministic intent and entity resolution before evidence ranking

Parse a bounded set of Chinese question patterns into an explicit query plan. Exact form names win over shorter aliases, while person expansion remains available as a controlled second step. Relation plans retain two endpoints and require either evidence covering both or an approved relation edge.

Alternative: ask the model to infer intent and retrieve in one opaque call. Rejected because retrieval failures would be difficult to reproduce and model unavailability would break basic questions.

### Build evaluation in two layers

The first frozen set uses currently collected evidence and includes answerable, ambiguous and deliberately unanswerable cases. Cases whose official page is still pending are retained as `corpus_missing` expectations rather than false retrieval failures. A later M7-complete snapshot promotes eligible cases into the acceptance set. Reports always record corpus counts and a snapshot fingerprint.

Alternative: postpone all evaluation until collection ends. Rejected because entity and intent defects can be found and fixed now.

### Keep generation behind a structured evidence packet

Introduce a provider-neutral adapter that receives only the question plan and a bounded evidence packet. It returns JSON claims with evidence IDs and exact supporting spans. Deterministic code validates membership, exact spans, claim type requirements, inference multiplicity and conflicts. Direct templates may add fixed non-factual connective language, but unsupported factual text never survives validation.

The adapter is disabled by default. Invalid JSON, timeout, provider error, empty validated claims or policy rejection falls back to deterministic intent templates and then the existing extractive baseline. M9 verifies this boundary with deterministic fake adapters and does not configure or call a real provider.

Alternative: let the model write a polished answer and check only that citations exist. Rejected because unrelated citations would not prevent hallucinated claims.

### Keep Wiki evidence primary during retrieval

Intent-aware ranking preserves Wiki as the primary source and uses verified official-account material as supplementary evidence. Result diversification prevents multiple near-identical chunks from one page from consuming the whole evidence packet. Source preference does not override endpoint coverage or exact-form resolution.

Alternative: rank all official sources only by similarity. Rejected because promotional or operational wording could outrank direct in-game material.

### Bound semantic reranking to indexed candidates

Use FTS and resolved entity-to-chunk links as the candidate-generation stage, then load vectors and entity annotations only for a bounded union of those chunk IDs. Semantic, entity, section, source-quality and diversity scoring continue to run on that candidate set. A query with no indexed candidates returns no evidence instead of loading every vector in the corpus.

Alternative: deserialize and score every eligible chunk for every request. Rejected because request latency and memory grow linearly with the collected corpus and concurrent requests can exhaust the private ECS instance.

The API admits only a bounded number of simultaneous retrieval requests, and the browser aborts a request that exceeds its deadline so a failed worker cannot leave the interface loading indefinitely.

### Extend the existing API compatibly

Keep `POST /api/ask` and all existing fields. Add versioned fields for intent, resolved entities, ambiguity, partial support, generation outcome and fallback. The browser renders these fields when present and remains compatible with deterministic responses.

Alternative: create a second answer endpoint. Rejected because it duplicates client behavior and complicates fallback.

## Risks / Trade-offs

- [Official pages do not explicitly state every same-person link] → Keep links pending until supported; allow a curated reviewed relation with multiple official citations.
- [Entity migration breaks existing relation IDs] → Use stable semantic keys, migrate in a transaction, and audit every existing evidence and relation reference before deployment.
- [Deterministic Chinese intent patterns miss unusual wording] → Fall back to generic retrieval, record unknown intent, and expand patterns from failed real questions.
- [A model returns persuasive unsupported prose] → Require structured claims and exact support spans, validate before rendering, and default to fallback.
- [Growing corpus changes rankings] → Record corpus fingerprints and separate provisional metrics from final M7-complete acceptance.
- [Candidate bounding drops a weak lexical-only semantic match] → Union FTS candidates with exact resolved-entity links, retain score diagnostics, and cover known questions with retrieval regression tests.
- [Concurrent retrieval exhausts ECS memory] → Bound candidate count, reject excess concurrent searches, and expose a finite browser deadline.
- [Generation adds latency and cost] → Bound evidence size and timeout, record provider-neutral usage, cache only validated results by corpus and prompt version, and keep generation optional.
- [SQLite work is later replaced by RDS] → Keep entity, retrieval and answer behavior behind existing domain/API contracts; schedule the RDS read adapter as a separate infrastructure change.

## Migration Plan

1. Add the real-question taxonomy, fixtures and baseline failure report without changing user-visible answers.
2. Add typed entity tables or fields and migrate a small curated set, beginning with `姬子` and `姬子·启行`; run relation and citation integrity audits.
3. Deploy deterministic intent resolution, form-aware retrieval and direct templates behind a feature flag; compare old and new results.
4. Extend the API and UI compatibly and validate the fixed question set locally and on ECS.
5. Add the disabled-by-default model adapter, secret configuration boundary, structured validation, timeout and fallback; verify it offline with deterministic fake adapters. Any real private-provider trial is deferred to a separate future change.
6. Re-run evaluation as M7 grows, then freeze final thresholds after sufficient Wiki coverage.

Rollback disables generation and intent-aware answering, restores the extractive path, and retains the additive entity records and evaluation reports for diagnosis. No rollback step deletes collected sources, raw objects, evidence or M7 checkpoints.

## Deferred Decisions

- Which model provider and cost ceiling should be used for a future private generation trial? This remains undecided and is outside M9 acceptance.
- How should future provider credentials be provisioned and rotated on ECS? No credential is configured by M9.
- Which official passages are sufficient to approve same-narrative-identity links when the Wiki exposes separate playable pages but does not state the link in one sentence?
- Should gameplay-only statistics and build advice remain outside answers even when present in Wiki modules, or become an explicitly selectable question scope later?
