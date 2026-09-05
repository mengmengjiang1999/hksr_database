"""Deterministic claim grounding and extractive answer baseline for M3."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.models.database import Database
from app.knowledge import identity_catalog, list_relations
from app.retrieval import (
    hybrid_search, intent_search, normalize_text, semantic_terms, source_context,
)


CLAIM_TYPES = {"explicit", "inferred", "conflicted"}
DEFAULT_MINIMUM_SCORE = 0.18
INSUFFICIENT_MESSAGE = "当前本地知识库中没有找到足以支持结论的官方文本。"
AMBIGUITY_MESSAGE = "这个问题涉及多个可玩形态，请先明确你想问的具体形态。"


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
        "context_type": evidence.get("context_type") or source_context(evidence["source_kind"]),
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


def _base_metadata(plan: Mapping[str, Any], strategy: str) -> Dict[str, Any]:
    return {
        "intent": plan["intent"],
        "query_plan": plan,
        "resolved_entities": plan["entities"],
        "ambiguity": plan["ambiguity"],
        "answer_strategy": strategy,
        "partial_support": {"is_partial": False, "supported_parts": [], "unsupported_parts": []},
    }


def _structured_claim(
    database: Database, text: str, evidence_ids: Sequence[str], support_check: str,
) -> Optional[Dict[str, Any]]:
    rows = {
        row["evidence_id"]: row
        for row in database.retrieval_rows_by_evidence_ids(evidence_ids)
    }
    evidence = [rows[item] for item in _unique_strings(evidence_ids) if item in rows]
    if not evidence:
        return None
    return {
        "text": text, "type": "explicit", "evidence_ids": [row["evidence_id"] for row in evidence],
        "reasoning_steps": [], "alternatives": [], "support_check": support_check,
        "citations": [_citation(database, row) for row in evidence],
    }


def _identity_direct_answer(database: Database, question: str, plan: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    people = identity_catalog(database)
    mentioned = {item["canonical_name"] for item in plan["entities"]}
    for person in people:
        forms = person["playable_forms"]
        form_names = {form["canonical_name"] for form in forms}
        if plan["intent"] == "playable_form" and (
            person["canonical_name"] in mentioned or mentioned.intersection(form_names)
        ):
            names = "、".join(form["canonical_name"] for form in forms)
            claim = _structured_claim(
                database, "%s目前有 %d 个已审核可玩形态：%s。" % (
                    person["canonical_name"], len(forms), names
                ), [form["evidence_id"] for form in forms], "approved_identity_links",
            )
            if claim:
                return {"answer": claim["text"], "claims": [claim], "strategy": "playable_form_template",
                        "identity": _identity_payload(person)}
        if plan["intent"] in {"identity", "relation", "comparison"}:
            endpoint_names = {item["canonical_name"] for item in plan["relation_endpoints"]}
            if len(endpoint_names.intersection(form_names)) >= 2 or (
                person["canonical_name"] in mentioned and bool(mentioned.intersection(form_names - {person["canonical_name"]}))
            ):
                selected = [form for form in forms if form["canonical_name"] in mentioned]
                claim = _structured_claim(
                    database,
                    "%s属于剧情人物%s的可玩形态；它们是同一人物的不同实机形态。" % (
                        "和".join(form["canonical_name"] for form in selected), person["canonical_name"]
                    ),
                    [form["evidence_id"] for form in selected], "approved_identity_links",
                )
                if claim:
                    return {"answer": claim["text"], "claims": [claim],
                            "strategy": "identity_relation_template",
                            "identity": _identity_payload(person)}
    return None


def _identity_payload(person: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "narrative_person": person["canonical_name"],
        "playable_forms": [form["canonical_name"] for form in person["playable_forms"]],
        "player_terminology": sorted({
            name["name"] for form in person["playable_forms"] for name in form["names"]
            if name["name_type"] == "player_shorthand"
        }),
    }


def _approved_relation_answer(database: Database, plan: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    endpoints = {item["canonical_name"] for item in plan["relation_endpoints"]}
    if len(endpoints) < 2:
        return None
    predicate_labels = {"member_of": "隶属于", "associated_with": "关联于", "knows": "认识"}
    for entity in endpoints:
        for relation in list_relations(database, entity):
            if {relation["subject_name"], relation["object_name"]} != endpoints:
                continue
            text = "%s%s%s。" % (
                relation["subject_name"], predicate_labels.get(relation["predicate"], relation["predicate"]),
                relation["object_name"],
            )
            evidence_ids = [item["evidence_id"] for item in relation["citations"]]
            claim = _structured_claim(database, text, evidence_ids, "approved_relation")
            if claim:
                return {"answer": text, "claims": [claim], "strategy": "approved_relation_template"}
    return None


def _intent_excerpt(question: str, text: str, intent: str) -> str:
    if intent not in {"identity", "acquisition", "temporal"}:
        return _best_extractive_excerpt(question, text)
    keywords = {
        "identity": ("身份", "是", "称为"),
        "acquisition": ("获取", "获得", "解锁", "触发", "开拓等级", "条件"),
        "temporal": ("日期", "时间", "版本", "开放", "实装", "年", "月", "日"),
    }[intent]
    units = _excerpt_units(text)
    matching = []
    for index, unit in enumerate(units):
        if any(word in unit for word in keywords) or (
            intent == "temporal" and re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", unit)
        ):
            matching.append(unit)
            if index + 1 < len(units) and len(unit) <= 24:
                matching.append(units[index + 1])
    return _best_extractive_excerpt(
        question, "\n".join(_unique_strings(matching)) if matching else text
    )


def _answer_single(
    database: Database, question: str, limit: int, minimum_score: float,
    source_kinds: Optional[Sequence[str]], contexts: Optional[Sequence[str]],
) -> Dict[str, Any]:
    search = intent_search(
        database, question, limit=limit, source_kinds=source_kinds, contexts=contexts
    )
    plan = search["query_plan"]
    metadata = _base_metadata(plan, "extractive_fallback")
    if search["status"] == "ambiguous":
        result = _answer_from_validation(
            question, search["results"], {"accepted": [], "rejected": []}, minimum_score
        )
        result["answer"] = AMBIGUITY_MESSAGE
        result.update(metadata)
        result["answer_strategy"] = "ambiguity"
        return result
    identity_answer = _identity_direct_answer(database, question, plan)
    if identity_answer:
        result = {
            "question": question, "status": "explicit", "answer": identity_answer["answer"],
            "claims": identity_answer["claims"], "rejected_claims": [],
            "retrieval": {"candidate_count": len(search["results"]),
                          "top_score": search["results"][0]["score"] if search["results"] else 0.0,
                          "minimum_score": minimum_score},
            **_base_metadata(plan, identity_answer["strategy"]),
        }
        result["identity"] = identity_answer["identity"]
        return result
    if plan["intent"] == "relation":
        relation_answer = _approved_relation_answer(database, plan)
        if relation_answer:
            return {
                "question": question, "status": "explicit", "answer": relation_answer["answer"],
                "claims": relation_answer["claims"], "rejected_claims": [],
                "retrieval": {"candidate_count": len(search["results"]),
                              "top_score": search["results"][0]["score"] if search["results"] else 0.0,
                              "minimum_score": minimum_score},
                **_base_metadata(plan, relation_answer["strategy"]),
            }
    retrieved = search["answerable_results"]
    if not retrieved or retrieved[0]["score"] < minimum_score:
        result = _answer_from_validation(
            question, retrieved, {"accepted": [], "rejected": []}, minimum_score
        )
        result.update(metadata)
        result["answer_strategy"] = "safe_refusal"
        return result
    top = retrieved[0]
    excerpt = _intent_excerpt(question, top["text"], plan["intent"])
    validation = validate_claims(
        database, retrieved,
        [{"text": excerpt, "type": "explicit", "evidence_ids": [top["evidence_id"]]}],
    )
    result = _answer_from_validation(question, retrieved, validation, minimum_score)
    result.update(metadata)
    result["answer_strategy"] = (
        "%s_template" % plan["intent"] if plan["intent"] in {"identity", "acquisition", "temporal"}
        else "extractive_fallback"
    )
    return result


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
    """Return a deterministic intent-aware answer; no model memory participates."""
    parts = [item.strip(" ，,。") for item in re.split(r"(?:以及|并且|同时|；|;)", question) if item.strip()]
    if len(parts) <= 1:
        return _answer_single(
            database, question, limit, minimum_score, source_kinds, contexts
        )
    first_plan = intent_search(database, parts[0], limit=1)["query_plan"]
    subject = first_plan["entities"][0]["canonical_name"] if first_plan["entities"] else ""
    results = []
    for index, part in enumerate(parts):
        expanded = part
        if index and subject and not any(
            item["canonical_name"] in part for item in first_plan["entities"]
        ):
            expanded = subject + part
        results.append(_answer_single(
            database, expanded, limit, minimum_score, source_kinds, contexts
        ))
    supported = [item for item in results if item["status"] != "uncertain"]
    unsupported = [parts[index] for index, item in enumerate(results) if item["status"] == "uncertain"]
    if not supported:
        result = results[0]
        result["partial_support"] = {"is_partial": False, "supported_parts": [],
                                     "unsupported_parts": parts}
        return result
    result = dict(supported[0])
    result["question"] = question
    result["answer"] = "\n".join(item["answer"] for item in supported)
    result["claims"] = [claim for item in supported for claim in item["claims"]]
    result["status"] = "partial" if unsupported else "explicit"
    result["answer_strategy"] = "multi_part"
    result["partial_support"] = {
        "is_partial": bool(unsupported),
        "supported_parts": [parts[index] for index, item in enumerate(results) if item["status"] != "uncertain"],
        "unsupported_parts": unsupported,
    }
    return result


def answer_question_legacy(
    database: Database,
    question: str,
    limit: int = 8,
    minimum_score: float = DEFAULT_MINIMUM_SCORE,
    source_kinds: Optional[Sequence[str]] = None,
    contexts: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Pre-M9 extractive behavior retained for reversible ECS rollout."""
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
        database, retrieved,
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
