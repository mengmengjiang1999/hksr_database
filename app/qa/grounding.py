"""Deterministic claim grounding and extractive answer baseline for M3."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.models.database import Database
from app.retrieval import hybrid_search, normalize_text, semantic_terms


CLAIM_TYPES = {"explicit", "inferred", "conflicted"}
DEFAULT_MINIMUM_SCORE = 0.18
INSUFFICIENT_MESSAGE = "当前本地知识库中没有找到足以支持结论的官方文本。"


def _unique_strings(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _citation(database: Database, evidence: Mapping[str, Any]) -> Dict[str, Any]:
    context = database.evidence_context(evidence["evidence_id"], window=1)
    return {
        "evidence_id": evidence["evidence_id"],
        "quote": evidence["text"],
        "source_title": evidence["title"],
        "source_kind": evidence["source_kind"],
        "official_status": evidence["official_status"],
        "external_id": evidence["external_id"],
        "url": evidence["page_url"],
        "section_path": evidence["section_path"],
        "speaker": evidence["speaker"],
        "version": evidence["version"],
        "context_type": evidence["context_type"],
        "adjacent_context": [
            item for item in context["context"] if not item["is_target"]
        ],
    }


def _validate_conflict_alternatives(
    alternatives: Any,
    evidence_map: Mapping[str, Mapping[str, Any]],
    bound_evidence_ids: Sequence[str],
) -> Tuple[bool, List[str]]:
    if not isinstance(alternatives, list) or len(alternatives) < 2:
        return False, ["conflict_alternatives_required"]
    errors = []
    for alternative in alternatives:
        if not isinstance(alternative, Mapping):
            errors.append("invalid_conflict_alternative")
            continue
        evidence_id = str(alternative.get("evidence_id", ""))
        text = str(alternative.get("text", ""))
        evidence = evidence_map.get(evidence_id)
        if evidence is None:
            errors.append("evidence_not_retrieved")
        elif evidence_id not in bound_evidence_ids:
            errors.append("alternative_not_bound_to_claim")
        elif not normalize_text(text) or normalize_text(text) not in normalize_text(evidence["text"]):
            errors.append("alternative_not_supported")
    return not errors, _unique_strings(errors)


def validate_claims(
    database: Database,
    retrieved: Sequence[Mapping[str, Any]],
    draft_claims: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate structured drafts against only the evidence retrieved this turn."""
    evidence_map = {str(item["evidence_id"]): item for item in retrieved}
    accepted = []
    rejected = []
    for index, draft in enumerate(draft_claims):
        claim_type = str(draft.get("type", ""))
        text = str(draft.get("text", "")).strip()
        evidence_ids = _unique_strings(draft.get("evidence_ids") or [])
        reasons: List[str] = []
        if claim_type not in CLAIM_TYPES:
            reasons.append("invalid_claim_type")
        if not text:
            reasons.append("empty_claim")
        missing = [item for item in evidence_ids if item not in evidence_map]
        if missing:
            reasons.append("evidence_not_retrieved")
        bound = [evidence_map[item] for item in evidence_ids if item in evidence_map]

        support_check = "direct"
        if claim_type == "explicit":
            if not bound:
                reasons.append("evidence_required")
            elif not any(
                normalize_text(text) in normalize_text(evidence["text"])
                for evidence in bound
            ):
                reasons.append("claim_not_directly_supported")
        elif claim_type == "inferred":
            support_check = "structural_only"
            if len(bound) < 2:
                reasons.append("inference_requires_two_evidence_items")
            steps = [str(item).strip() for item in draft.get("reasoning_steps") or [] if str(item).strip()]
            if not steps:
                reasons.append("reasoning_steps_required")
        elif claim_type == "conflicted":
            support_check = "conflict_structure"
            if len(bound) < 2:
                reasons.append("conflict_requires_two_evidence_items")
            identities = {
                (item["provider"], item["external_id"], str(item.get("version") or ""))
                for item in bound
            }
            if len(identities) < 2:
                reasons.append("conflict_requires_distinct_source_or_version")
            valid_alternatives, alternative_errors = _validate_conflict_alternatives(
                draft.get("alternatives"), evidence_map, evidence_ids
            )
            if not valid_alternatives:
                reasons.extend(alternative_errors)

        if reasons:
            rejected.append(
                {"index": index, "text": text, "type": claim_type,
                 "reasons": _unique_strings(reasons)}
            )
            continue
        accepted.append(
            {
                "text": text,
                "type": claim_type,
                "evidence_ids": evidence_ids,
                "reasoning_steps": list(draft.get("reasoning_steps") or []),
                "alternatives": list(draft.get("alternatives") or []),
                "support_check": support_check,
                "citations": [_citation(database, evidence) for evidence in bound],
            }
        )
    return {"accepted": accepted, "rejected": rejected}


def _excerpt_units(text: str) -> List[str]:
    units = [item.strip() for item in re.split(r"(?<=[。！？!?；;])|\n+", text) if item.strip()]
    return units or [text.strip()]


def _best_extractive_excerpt(question: str, text: str, maximum_characters: int = 320) -> str:
    if len(text) <= maximum_characters:
        return text.strip()
    units = _excerpt_units(text)
    query_terms = set(semantic_terms(question))
    choices = []
    for start in range(len(units)):
        for width in range(1, 4):
            candidate = "\n".join(units[start : start + width]).strip()
            if len(candidate) < 8 or len(candidate) > maximum_characters:
                continue
            candidate_terms = set(semantic_terms(candidate))
            overlap = len(query_terms & candidate_terms)
            density = overlap / max(1, len(candidate_terms))
            choices.append((overlap, density, -len(candidate), candidate))
    if not choices:
        return text[:maximum_characters].strip()
    return max(choices)[-1]


def _answer_from_validation(
    question: str,
    retrieved: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any],
    minimum_score: float,
) -> Dict[str, Any]:
    accepted = list(validation["accepted"])
    if not accepted:
        return {
            "question": question,
            "status": "uncertain",
            "answer": INSUFFICIENT_MESSAGE,
            "claims": [],
            "rejected_claims": list(validation["rejected"]),
            "retrieval": {
                "candidate_count": len(retrieved),
                "top_score": retrieved[0]["score"] if retrieved else 0.0,
                "minimum_score": minimum_score,
            },
        }
    types = {item["type"] for item in accepted}
    status = "conflicted" if "conflicted" in types else "inferred" if "inferred" in types else "explicit"
    return {
        "question": question,
        "status": status,
        "answer": "\n".join(item["text"] for item in accepted),
        "claims": accepted,
        "rejected_claims": list(validation["rejected"]),
        "retrieval": {
            "candidate_count": len(retrieved),
            "top_score": retrieved[0]["score"] if retrieved else 0.0,
            "minimum_score": minimum_score,
        },
    }


def ground_draft(
    database: Database,
    question: str,
    draft_claims: Sequence[Mapping[str, Any]],
    limit: int = 8,
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
    source_kinds: Optional[Sequence[str]] = None,
    contexts: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    retrieved = hybrid_search(
        database, question, limit=limit, source_kinds=source_kinds, contexts=contexts
    )
    if not retrieved or retrieved[0]["score"] < minimum_score:
        return _answer_from_validation(
            question, retrieved, {"accepted": [], "rejected": []}, minimum_score
        )
    validation = validate_claims(database, retrieved, draft_claims)
    return _answer_from_validation(question, retrieved, validation, minimum_score)


def answer_question(
    database: Database,
    question: str,
    limit: int = 8,
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
    source_kinds: Optional[Sequence[str]] = None,
    contexts: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return a safe extractive answer; no model memory participates."""
    retrieved = hybrid_search(
        database, question, limit=limit, source_kinds=source_kinds, contexts=contexts
    )
    if not retrieved or retrieved[0]["score"] < minimum_score:
        return _answer_from_validation(
            question, retrieved, {"accepted": [], "rejected": []}, minimum_score
        )
    top = retrieved[0]
    excerpt = _best_extractive_excerpt(question, top["text"])
    validation = validate_claims(
        database,
        retrieved,
        [{"text": excerpt, "type": "explicit", "evidence_ids": [top["evidence_id"]]}],
    )
    return _answer_from_validation(question, retrieved, validation, minimum_score)


def evaluate_answers(database: Database, dataset_path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    answerable = 0
    answered_with_expected_evidence = 0
    unanswerable = 0
    refused = 0
    factual_claims = 0
    cited_claims = 0
    details = []
    for case in cases:
        result = answer_question(database, case["question"])
        if case.get("unanswerable"):
            unanswerable += 1
            correct = result["status"] == "uncertain" and not result["claims"]
            refused += int(correct)
            details.append({"id": case["id"], "status": result["status"], "correct": correct})
            continue
        answerable += 1
        expected = normalize_text(case["evidence_contains"])
        citations = [citation for claim in result["claims"] for citation in claim["citations"]]
        correct = any(expected in normalize_text(citation["quote"]) for citation in citations)
        answered_with_expected_evidence += int(correct)
        factual_claims += len(result["claims"])
        cited_claims += sum(bool(claim["citations"]) for claim in result["claims"])
        details.append({"id": case["id"], "status": result["status"], "correct": correct})
    return {
        "schema_version": 1,
        "cases": len(cases),
        "answerable_cases": answerable,
        "unanswerable_cases": unanswerable,
        "expected_evidence_accuracy": round(answered_with_expected_evidence / answerable, 4) if answerable else 0.0,
        "citation_coverage": round(cited_claims / factual_claims, 4) if factual_claims else 1.0,
        "refusal_accuracy": round(refused / unanswerable, 4) if unanswerable else None,
        "details": details,
    }
