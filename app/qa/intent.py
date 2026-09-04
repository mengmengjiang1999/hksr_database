"""Deterministic Chinese question intent and entity endpoint planning."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.knowledge.identity import identity_catalog
from app.models.database import Database


INTENTS = {
    "identity", "playable_form", "relation", "acquisition", "temporal",
    "descriptive", "comparison", "unknown",
}


def _surface(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower().replace("•", "·")


def detect_intent(question: str) -> str:
    text = _surface(question).strip()
    if not text:
        return "unknown"
    if any(word in text for word in ("区别", "相比", "比较", "哪个更", "是否一样")):
        return "comparison"
    if any(word in text for word in ("几个可玩", "可玩形态", "形态有哪些", "多少个形态", "sp形态")):
        return "playable_form"
    if any(word in text for word in ("什么关系", "有何关系", "如何看待", "怎么看", "属于谁", "隶属于")):
        return "relation"
    if any(word in text for word in ("怎么获得", "如何获得", "哪里获得", "获取途径", "怎么解锁", "如何解锁", "怎么触发", "如何触发", "开放条件", "要求多少")):
        return "acquisition"
    if any(word in text for word in ("什么时候", "何时", "哪一年", "哪个版本", "实装日期", "开放日期", "先于", "晚于", "之前", "之后")):
        return "temporal"
    if any(word in text for word in ("是谁", "什么身份", "指的是", "同一个人", "是什么人", "叫什么")):
        return "identity"
    if text.endswith(("？", "?")) or any(word in text for word in ("什么", "为什么", "怎样", "如何", "哪里", "哪个", "多少")):
        return "descriptive"
    return "unknown"


def _alias_occurrences(question: str, catalog: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    text = _surface(question)
    occurrences: List[Dict[str, Any]] = []
    for entity in catalog:
        for alias in entity.get("aliases") or []:
            surface = _surface(str(alias["text"]))
            if not surface:
                continue
            start = 0
            while True:
                offset = text.find(surface, start)
                if offset < 0:
                    break
                occurrences.append({
                    "start": offset, "end": offset + len(surface), "surface": alias["text"],
                    "alias_type": alias["alias_type"], "entity_id": int(entity["id"]),
                    "canonical_name": entity["canonical_name"], "entity_type": entity["entity_type"],
                })
                start = offset + 1
    # A shorter name inside a longer exact form is not a separate endpoint. A
    # second occurrence outside that span remains available (姬子和姬子·启行).
    output = []
    for item in occurrences:
        contained = any(
            other["entity_id"] != item["entity_id"]
            and other["start"] <= item["start"] and other["end"] >= item["end"]
            and (other["end"] - other["start"]) > (item["end"] - item["start"])
            for other in occurrences
        )
        if not contained:
            output.append(item)
    output.sort(key=lambda item: (item["start"], -(item["end"] - item["start"]), item["entity_id"]))
    return output


def resolve_query_entities(database: Database, question: str) -> List[Dict[str, Any]]:
    occurrences = _alias_occurrences(question, database.entity_catalog())
    resolved = []
    seen: set[int] = set()
    for item in occurrences:
        if item["entity_id"] in seen:
            continue
        seen.add(item["entity_id"])
        resolved.append(item)
    return resolved


def _identity_ambiguity(database: Database, question: str, intent: str) -> Optional[Dict[str, Any]]:
    if intent not in {"descriptive", "acquisition", "temporal"}:
        return None
    text = _surface(question)
    for person in identity_catalog(database, include_pending=True):
        canonical = _surface(person["canonical_name"])
        if canonical not in text:
            continue
        explicit_forms = [
            form for form in person["playable_forms"]
            if any(_surface(name["name"]) in text and _surface(name["name"]) != canonical
                   for name in form["names"])
        ]
        if not explicit_forms and len(person["playable_forms"]) > 1:
            return {
                "reason": "playable_form_required",
                "narrative_person": person["canonical_name"],
                "candidates": [form["canonical_name"] for form in person["playable_forms"]],
            }
    return None


def build_query_plan(database: Database, question: str) -> Dict[str, Any]:
    intent = detect_intent(question)
    entities = resolve_query_entities(database, question)
    endpoints = entities[:2] if intent in {"relation", "comparison"} else []
    ambiguity = _identity_ambiguity(database, question, intent)
    return {
        "schema_version": 1,
        "intent": intent,
        "entities": entities,
        "relation_endpoints": endpoints,
        "ambiguity": ambiguity,
        "entity_expansion": "person_forms" if intent == "playable_form" else "exact_form_first",
        "source_priority": ["mihoyo_wiki", "miyoushe"],
        "evidence_requirement": (
            "both_endpoints_or_approved_relation" if intent == "relation"
            else "official_support"
        ),
    }
