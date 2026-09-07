"""Curated one-hop relations and non-public co-occurrence candidates."""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.models.database import Database
from app.retrieval import normalize_text, source_context


EVIDENCE_LEVELS = {"explicit", "inferred", "candidate"}
REVIEW_STATUSES = {"approved", "pending", "rejected"}


def _entities_by_name(database: Database) -> Dict[str, Mapping[str, Any]]:
    return {item["canonical_name"]: item for item in database.entity_catalog()}


def _resolve_selector(
    rows: Sequence[Mapping[str, Any]], selector: Mapping[str, Any]
) -> Optional[Mapping[str, Any]]:
    expected = normalize_text(str(selector.get("evidence_contains", "")))
    matches = []
    for row in rows:
        if str(row["external_id"]) != str(selector.get("external_id", "")):
            continue
        if selector.get("provider") and row["provider"] != selector["provider"]:
            continue
        if selector.get("version") is not None and str(row.get("version") or "") != str(selector["version"]):
            continue
        if expected and expected not in normalize_text(row["text"]):
            continue
        matches.append(row)
    matches.sort(key=lambda item: (int(item["chunk_position"]), item["evidence_id"]))
    return matches[0] if matches else None


def _validate_relation(
    relation: Mapping[str, Any],
    subject_id: int,
    object_id: int,
    evidence: Sequence[Mapping[str, Any]],
) -> List[str]:
    level = str(relation.get("evidence_level", ""))
    errors = []
    if level not in {"explicit", "inferred"}:
        errors.append("invalid_evidence_level")
    if not evidence:
        errors.append("evidence_required")
    if level == "explicit" and evidence:
        if not any(
            {subject_id, object_id}.issubset({int(entity["id"]) for entity in item["entities"]})
            for item in evidence
        ):
            errors.append("explicit_evidence_missing_relation_endpoint")
    if level == "inferred":
        if len({item["evidence_id"] for item in evidence}) < 2:
            errors.append("inference_requires_two_evidence_items")
        if not str(relation.get("reasoning", "")).strip():
            errors.append("inference_reasoning_required")
    return errors


def _insert_relation(
    connection: Any,
    subject_id: int,
    predicate: str,
    object_id: int,
    evidence_level: str,
    review_status: str,
    confidence: float,
    reasoning: str,
    origin: str,
    evidence_ids: Sequence[str],
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO relations (
            subject_id, predicate, object_id, evidence_level, review_status,
            confidence, reasoning, origin, is_stale
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(subject_id, predicate, object_id, origin) DO UPDATE SET
            evidence_level = excluded.evidence_level,
            review_status = excluded.review_status,
            confidence = excluded.confidence,
            reasoning = excluded.reasoning,
            is_stale = 0
        """,
        (subject_id, predicate, object_id, evidence_level, review_status,
         confidence, reasoning, origin),
    )
    row = connection.execute(
        "SELECT id FROM relations WHERE subject_id=? AND predicate=? AND object_id=? AND origin=?",
        (subject_id, predicate, object_id, origin),
    ).fetchone()
    relation_id = int(row["id"] if row else cursor.lastrowid)
    connection.execute("DELETE FROM relation_evidence WHERE relation_id = ?", (relation_id,))
    for evidence_id in evidence_ids:
        connection.execute(
            "INSERT INTO relation_evidence (relation_id, evidence_id) VALUES (?, ?)",
            (relation_id, evidence_id),
        )
    return relation_id


def build_relations(database: Database, catalogue_path: Path) -> Dict[str, Any]:
    database.initialize()
    payload = json.loads(Path(catalogue_path).read_text(encoding="utf-8"))
    catalogue = payload.get("relations") or []
    entities = _entities_by_name(database)
    rows = database.retrieval_rows()
    imported = 0
    rejected = []
    with database.connect() as connection:
        connection.execute("DELETE FROM relations WHERE origin = 'curated'")
        for index, relation in enumerate(catalogue):
            subject = entities.get(str(relation.get("subject", "")))
            object_ = entities.get(str(relation.get("object", "")))
            errors = []
            if subject is None:
                errors.append("unknown_subject")
            if object_ is None:
                errors.append("unknown_object")
            evidence = []
            for selector in relation.get("evidence", []):
                resolved = _resolve_selector(rows, selector)
                if resolved is None:
                    errors.append("evidence_selector_not_found")
                else:
                    evidence.append(resolved)
            if subject is not None and object_ is not None:
                errors.extend(
                    _validate_relation(relation, int(subject["id"]), int(object_["id"]), evidence)
                )
            if errors:
                rejected.append({"index": index, "relation": relation, "reasons": sorted(set(errors))})
                continue
            _insert_relation(
                connection,
                int(subject["id"]), str(relation["predicate"]), int(object_["id"]),
                str(relation["evidence_level"]), str(relation.get("review_status", "approved")),
                float(relation.get("confidence", 1.0)), str(relation.get("reasoning", "")),
                "curated", [item["evidence_id"] for item in evidence],
            )
            imported += 1

        connection.execute("DELETE FROM relations WHERE origin = 'cooccurrence'")
        evidence_by_pair: Dict[Tuple[int, int], List[str]] = defaultdict(list)
        for row in rows:
            entity_ids = sorted({int(item["id"]) for item in row["entities"]})
            for left, right in combinations(entity_ids, 2):
                if row["evidence_id"] not in evidence_by_pair[(left, right)]:
                    evidence_by_pair[(left, right)].append(row["evidence_id"])
        for (left, right), evidence_ids in evidence_by_pair.items():
            _insert_relation(
                connection, left, "co_occurs_with", right, "candidate", "pending",
                min(0.99, 0.3 + 0.1 * len(evidence_ids)), "", "cooccurrence", evidence_ids[:3],
            )
    audit = audit_relations(database)
    return {
        "curated_imported": imported,
        "curated_rejected": len(rejected),
        "rejections": rejected,
        "candidates": len(evidence_by_pair),
        "audit": audit,
    }


def audit_relations(database: Database, update: bool = True) -> Dict[str, Any]:
    return database.relation_audit(update=update)


def list_relations(
    database: Database,
    entity_name: Optional[str] = None,
    include_candidates: bool = False,
) -> List[Dict[str, Any]]:
    stale_ids = set(audit_relations(database, update=False)["stale_ids"])
    relations = database.relation_rows(entity_name, include_candidates=include_candidates)
    relation_evidence = {
        int(relation["id"]): list(relation.pop("evidence_ids")) for relation in relations
    }
    if relations:
        requested_evidence_ids = [
            evidence_id
            for evidence in relation_evidence.values()
            for evidence_id in evidence
        ]
        rows_by_evidence = {
            item["evidence_id"]: item
            for item in database.retrieval_rows_by_evidence_ids(requested_evidence_ids)
        }
    else:
        rows_by_evidence = {}
    output = []
    for relation in relations:
        if int(relation["id"]) in stale_ids:
            continue
        citations = []
        for evidence_id in relation_evidence[int(relation["id"])]:
            evidence = rows_by_evidence.get(evidence_id)
            if evidence:
                citations.append({
                    "evidence_id": evidence["evidence_id"], "quote": evidence["text"],
                    "source_title": evidence["title"], "source_kind": evidence["source_kind"],
                    "url": evidence["page_url"], "section_path": evidence["section_path"],
                    "version": evidence["version"],
                    "context_type": source_context(evidence["source_kind"]),
                })
        item = dict(relation)
        item["direction"] = (
            "outgoing" if entity_name == item["subject_name"] else
            "incoming" if entity_name == item["object_name"] else "subject_to_object"
        )
        item["citations"] = citations
        output.append(item)
    return output


def review_relation(
    database: Database,
    relation_id: int,
    review_status: str,
    predicate: Optional[str] = None,
    evidence_level: Optional[str] = None,
    reasoning: Optional[str] = None,
) -> Dict[str, Any]:
    if review_status not in REVIEW_STATUSES:
        raise ValueError("Unknown review status: %s" % review_status)
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM relations WHERE id = ?", (relation_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown relation id: %d" % relation_id)
        next_predicate = predicate or row["predicate"]
        next_level = evidence_level or row["evidence_level"]
        next_reasoning = reasoning if reasoning is not None else row["reasoning"]
        if review_status == "approved" and next_level == "candidate":
            raise ValueError("A candidate must be assigned an explicit or inferred evidence level before approval")
        if review_status == "approved" and row["origin"] == "cooccurrence" and not predicate:
            raise ValueError("A co-occurrence candidate must receive a reviewed semantic predicate before approval")
        if next_level not in EVIDENCE_LEVELS:
            raise ValueError("Unknown evidence level: %s" % next_level)
        if review_status == "approved":
            evidence_ids = [item["evidence_id"] for item in connection.execute(
                "SELECT evidence_id FROM relation_evidence WHERE relation_id = ?", (relation_id,)
            ).fetchall()]
            evidence_map = {item["evidence_id"]: item for item in database.retrieval_rows()}
            evidence = [evidence_map[item] for item in evidence_ids if item in evidence_map]
            errors = _validate_relation(
                {"evidence_level": next_level, "reasoning": next_reasoning},
                int(row["subject_id"]), int(row["object_id"]), evidence,
            )
            if errors:
                raise ValueError("Relation cannot be approved: %s" % ", ".join(errors))
        connection.execute(
            "UPDATE relations SET review_status=?, predicate=?, evidence_level=?, reasoning=? WHERE id=?",
            (review_status, next_predicate, next_level, next_reasoning, relation_id),
        )
    audit_relations(database)
    return {"relation_id": relation_id, "review_status": review_status,
            "predicate": next_predicate, "evidence_level": next_level}
