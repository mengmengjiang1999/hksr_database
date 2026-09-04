"""Versioned real-question evaluation and corpus fingerprints for M9."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from app.models.database import Database, stable_evidence_id
from app.qa.grounding import answer_question
from app.retrieval import hybrid_search, normalize_text


EXPECTED_OUTCOMES = {"answerable", "pending_corpus", "ambiguous", "correct_refusal"}
REQUIRED_FAILURE_CLASSES = {
    "corpus_gap",
    "parsing_defect",
    "entity_ambiguity",
    "ranking_miss",
    "generation_failure",
    "correct_refusal",
}


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_taxonomy(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("schema_version"), int):
        raise ValueError("Taxonomy requires an integer schema_version")
    if not str(payload.get("taxonomy_version", "")).strip():
        raise ValueError("Taxonomy requires a taxonomy_version")
    intents = payload.get("intents")
    failures = payload.get("failure_classes")
    if not isinstance(intents, Mapping) or not intents:
        raise ValueError("Taxonomy requires a non-empty intents object")
    if not isinstance(failures, Mapping):
        raise ValueError("Taxonomy requires a failure_classes object")
    missing = REQUIRED_FAILURE_CLASSES - set(failures)
    if missing:
        raise ValueError("Taxonomy is missing failure classes: %s" % ", ".join(sorted(missing)))
    return payload


def load_real_question_dataset(path: Path, taxonomy: Mapping[str, Any]) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("taxonomy_version") != taxonomy.get("taxonomy_version"):
        raise ValueError("Dataset taxonomy_version does not match the taxonomy")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 50 <= len(cases) <= 100:
        raise ValueError("Real-question dataset must contain between 50 and 100 cases")
    known_intents = set(taxonomy["intents"])
    seen = set()
    for case in cases:
        case_id = str(case.get("id", "")).strip()
        if not case_id or case_id in seen:
            raise ValueError("Every case requires a unique non-empty id")
        seen.add(case_id)
        if not str(case.get("question", "")).strip():
            raise ValueError("Case %s has no question" % case_id)
        if case.get("intent") not in known_intents:
            raise ValueError("Case %s has an unknown intent" % case_id)
        expectation = case.get("expectation")
        if not isinstance(expectation, Mapping):
            raise ValueError("Case %s requires an expectation" % case_id)
        outcome = expectation.get("outcome")
        if outcome not in EXPECTED_OUTCOMES:
            raise ValueError("Case %s has an unknown expected outcome" % case_id)
        evidence = expectation.get("evidence") or []
        if outcome == "answerable" and not evidence:
            raise ValueError("Answerable case %s requires evidence expectations" % case_id)
        if outcome == "pending_corpus" and not expectation.get("pending_reason"):
            raise ValueError("Pending-corpus case %s requires pending_reason" % case_id)
    return payload


def corpus_snapshot(database: Database) -> Dict[str, Any]:
    """Return a secret-free fingerprint of all retrieval-relevant local state."""
    database.initialize()
    with database.connect() as connection:
        sources = [dict(row) for row in connection.execute(
            """SELECT provider, external_id, source_kind, status, official_status,
                      COALESCE(version, '') AS version, COALESCE(content_sha256, '') AS content_sha256
               FROM sources ORDER BY provider, external_id"""
        )]
        documents = [dict(row) for row in connection.execute(
            """SELECT s.provider, s.external_id, d.document_key, d.evidence_eligible
               FROM documents d JOIN sources s ON s.id = d.source_id
               ORDER BY s.provider, s.external_id, d.document_key"""
        )]
        chunks = [dict(row) for row in connection.execute(
            """SELECT s.provider, s.external_id, d.document_key, c.chunk_key,
                      c.content_sha256, d.evidence_eligible, s.status
               FROM chunks c JOIN documents d ON d.id = c.document_id
               JOIN sources s ON s.id = d.source_id
               ORDER BY s.provider, s.external_id, d.document_key, c.chunk_key"""
        )]
        entities = [dict(row) for row in connection.execute(
            """SELECT canonical_name, entity_type, description
               FROM entities ORDER BY entity_type, canonical_name"""
        )]
        aliases = [dict(row) for row in connection.execute(
            """SELECT e.canonical_name, e.entity_type, a.alias, a.alias_type
               FROM aliases a JOIN entities e ON e.id = a.entity_id
               ORDER BY e.entity_type, e.canonical_name, a.alias"""
        )]
        relations = [dict(row) for row in connection.execute(
            """SELECT se.canonical_name AS subject, r.predicate,
                      oe.canonical_name AS object, r.evidence_level,
                      r.review_status, r.is_stale
               FROM relations r JOIN entities se ON se.id = r.subject_id
               JOIN entities oe ON oe.id = r.object_id
               ORDER BY subject, r.predicate, object"""
        )]
        vector_count = int(connection.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0])
    source_statuses = Counter(row["status"] for row in sources)
    source_providers = Counter(row["provider"] for row in sources)
    source_kinds = Counter(row["source_kind"] for row in sources)
    eligible = [
        stable_evidence_id(row["provider"], row["external_id"], row["document_key"], row["chunk_key"])
        for row in chunks if row["status"] == "parsed" and bool(row["evidence_eligible"])
    ]
    canonical = {
        "sources": sources, "documents": documents, "chunks": chunks,
        "entities": entities, "aliases": aliases, "relations": relations,
        "semantic_vectors": vector_count,
    }
    return {
        "schema_version": 1,
        "fingerprint": _canonical_digest(canonical),
        "counts": {
            "sources": len(sources),
            "documents": len(documents),
            "chunks": len(chunks),
            "eligible_evidence": len(eligible),
            "semantic_vectors": vector_count,
            "entities": len(entities),
            "aliases": len(aliases),
            "relations": len(relations),
        },
        "source_statuses": dict(sorted(source_statuses.items())),
        "source_providers": dict(sorted(source_providers.items())),
        "source_kinds": dict(sorted(source_kinds.items())),
        "evidence_fingerprint": _canonical_digest(eligible),
    }


def _expected_evidence(case: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return case["expectation"].get("evidence") or []


def _evidence_state(
    database: Database, expected: Sequence[Mapping[str, Any]]
) -> Tuple[str, List[Dict[str, Any]]]:
    rows = database.retrieval_rows()
    sources = database.list_sources()
    matched_rows: List[Dict[str, Any]] = []
    missing_states: List[str] = []
    for item in expected:
        provider = str(item.get("provider", ""))
        external_id = str(item.get("external_id", ""))
        contains = normalize_text(str(item.get("contains", "")))
        source_matches = [
            row for row in sources
            if (not provider or row["provider"] == provider)
            and (not external_id or str(row["external_id"]) == external_id)
        ]
        if external_id and (
            not source_matches or not any(row["status"] == "parsed" for row in source_matches)
        ):
            missing_states.append("corpus_gap")
            continue
        evidence_matches = [
            row for row in rows
            if (not provider or row["provider"] == provider)
            and (not external_id or str(row["external_id"]) == external_id)
            and (not contains or contains in normalize_text(row["text"]))
        ]
        if evidence_matches:
            matched_rows.extend(evidence_matches)
        elif external_id:
            missing_states.append("parsing_defect")
        else:
            missing_states.append("corpus_gap")
    if not missing_states:
        return "available", matched_rows
    if "parsing_defect" in missing_states:
        return "parsing_defect", []
    return "corpus_gap", []


def evaluate_real_questions(
    database: Database,
    dataset_path: Path,
    taxonomy_path: Path,
    *,
    limit: int = 8,
) -> Dict[str, Any]:
    taxonomy = load_taxonomy(taxonomy_path)
    dataset = load_real_question_dataset(dataset_path, taxonomy)
    snapshot = corpus_snapshot(database)
    details = []
    observed = Counter()
    passed = 0
    for case in dataset["cases"]:
        expectation = case["expectation"]
        outcome = expectation["outcome"]
        expected = _expected_evidence(case)
        evidence_state, evidence_rows = _evidence_state(database, expected) if expected else ("none", [])
        top_ids: List[str] = []
        top_score = 0.0

        if outcome == "ambiguous":
            classification = "entity_ambiguity"
            correct = True
        elif outcome == "correct_refusal":
            answer = answer_question(database, case["question"], limit=limit)
            correct = answer["status"] == "uncertain"
            classification = "correct_refusal" if correct else "generation_failure"
        elif evidence_state != "available":
            classification = evidence_state
            correct = outcome == "pending_corpus" and evidence_state == "corpus_gap"
        else:
            results = hybrid_search(database, case["question"], limit=limit)
            top_ids = [row["evidence_id"] for row in results]
            top_score = float(results[0]["score"]) if results else 0.0
            expected_ids = {row["evidence_id"] for row in evidence_rows}
            correct = bool(expected_ids.intersection(top_ids))
            classification = "passed" if correct else "ranking_miss"

        passed += int(correct)
        observed[classification] += 1
        details.append({
            "id": case["id"],
            "intent": case["intent"],
            "expected_outcome": outcome,
            "observed_classification": classification,
            "correct": correct,
            "top_score": round(top_score, 6),
            "top_evidence_ids": top_ids,
        })
    total = len(details)
    return {
        "schema_version": 1,
        "taxonomy_version": taxonomy["taxonomy_version"],
        "dataset_version": dataset["dataset_version"],
        "taxonomy_fingerprint": _canonical_digest(taxonomy),
        "dataset_fingerprint": _canonical_digest(dataset),
        "corpus_snapshot": snapshot,
        "summary": {
            "cases": total,
            "correct": passed,
            "accuracy": round(passed / total, 4) if total else 0.0,
            "observed_classifications": dict(sorted(observed.items())),
        },
        "details": details,
    }
