"""Local entity-aware semantic and hybrid evidence retrieval for M2."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from app.models.database import Database


SOURCE_WEIGHTS = {
    "wiki_quest": 1.0,
    "wiki_readable": 1.0,
    "wiki_character": 0.98,
    "official_article": 0.9,
    "official_video": 0.85,
}

CONTEXT_BY_SOURCE_KIND = {
    "wiki_quest": "in_game",
    "wiki_readable": "in_game",
    "wiki_character": "in_game",
    "official_article": "official_supplement",
    "official_video": "promotional",
}

QUESTION_WORDS = (
    "请问", "根据官方资料", "根据游戏文本", "是什么", "为什么", "怎么样",
    "怎样", "如何", "哪些", "哪个", "哪里", "何时", "是否", "有关",
    "关于", "介绍一下", "说明", "什么", "谁", "的", "了", "吗", "呢",
)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return "".join(character for character in value if character.isalnum())


def semantic_terms(value: str) -> Counter[str]:
    normalized = normalize_text(value)
    terms: Counter[str] = Counter()
    for size in (2, 3, 4):
        for offset in range(max(0, len(normalized) - size + 1)):
            terms["c%d:%s" % (size, normalized[offset : offset + size])] += 1
    for word in re.findall(r"[a-z0-9]{2,}", value.lower()):
        terms["w:%s" % word] += 2
    return terms


def _tfidf(counts: Mapping[str, int], idf: Mapping[str, float]) -> Dict[str, float]:
    return {
        term: (1.0 + math.log(count)) * idf.get(term, 1.0)
        for term, count in counts.items()
    }


def _cosine(left: Mapping[str, float], right: Mapping[str, float], right_norm: float) -> float:
    if not left or not right or right_norm <= 0:
        return 0.0
    left_norm = math.sqrt(sum(weight * weight for weight in left.values()))
    if left_norm <= 0:
        return 0.0
    dot = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    return dot / (left_norm * right_norm)


def load_entity_file(path: Path) -> Sequence[Mapping[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entities = payload.get("entities")
    if not isinstance(entities, list):
        raise ValueError("Entity file must contain an entities list")
    return entities


def build_retrieval_index(database: Database, entity_path: Path) -> Dict[str, int]:
    entity_result = database.replace_entities(load_entity_file(entity_path))
    rows = database.retrieval_rows()
    document_frequency: Counter[str] = Counter()
    term_counts: Dict[int, Counter[str]] = {}
    for row in rows:
        counts = semantic_terms(
            "%s %s %s" % (row["title"], row["section_path"], row["text"])
        )
        term_counts[int(row["chunk_id"])] = counts
        document_frequency.update(counts.keys())
    document_count = len(rows)
    idf = {
        term: math.log((document_count + 1) / (frequency + 1)) + 1.0
        for term, frequency in document_frequency.items()
    }
    vectors = {
        chunk_id: _tfidf(counts, idf) for chunk_id, counts in term_counts.items()
    }
    vector_count = database.replace_vectors(
        vectors,
        {"schema_version": 1, "document_count": document_count, "idf": idf},
    )
    return {**entity_result, "vectors": vector_count}


def _query_entities(query: str, catalog: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    normalized = normalize_text(query)
    matched = []
    for entity in catalog:
        aliases = [item["text"] for item in entity["aliases"]]
        if any(normalize_text(alias) in normalized for alias in aliases if alias):
            matched.append(entity)
    return matched


def _lexical_terms(query: str, entities: Sequence[Mapping[str, Any]]) -> List[str]:
    terms: List[str] = []
    for entity in entities:
        terms.extend(item["text"] for item in entity["aliases"] if item["text"])
    cleaned = query
    for word in QUESTION_WORDS:
        cleaned = cleaned.replace(word, " ")
    terms.extend(re.findall(r"[\u3400-\u9fffA-Za-z0-9·•「」]{2,}", cleaned))
    normalized_query = normalize_text(query)
    # Character n-grams make Chinese questions useful to lexical retrieval even
    # when they contain no spaces. Longer terms still receive a larger weight.
    for size in (2, 3, 4):
        if len(normalized_query) >= size:
            terms.extend(
                normalized_query[offset : offset + size]
                for offset in range(len(normalized_query) - size + 1)
            )
    output = []
    seen = set()
    for term in sorted(terms, key=len, reverse=True):
        normalized = normalize_text(term)
        if len(normalized) >= 2 and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def hybrid_search(
    database: Database,
    query: str,
    limit: int = 10,
    source_kinds: Optional[Sequence[str]] = None,
    version: Optional[str] = None,
    contexts: Optional[Sequence[str]] = None,
    mode: str = "hybrid",
) -> List[Dict[str, Any]]:
    if not query.strip():
        return []
    if mode not in {"hybrid", "lexical", "semantic"}:
        raise ValueError("Unknown retrieval mode: %s" % mode)
    metadata = database.retrieval_metadata()
    if not metadata:
        raise RuntimeError("Semantic index is missing; run the index command first")
    idf = metadata.get("idf", {})
    catalog = database.entity_catalog()
    matched_entities = _query_entities(query, catalog)
    matched_entity_ids: Set[int] = {int(item["id"]) for item in matched_entities}
    expanded_query = query + " " + " ".join(
        alias["text"]
        for entity in matched_entities
        for alias in entity["aliases"]
        if alias["alias_type"] != "player"
    )
    query_vector = _tfidf(semantic_terms(expanded_query), idf)
    lexical_terms = _lexical_terms(query, matched_entities)
    lexical_denominator = float(sum(len(term) ** 2 for term in lexical_terms)) or 1.0
    fts_scores: Dict[int, float] = {}
    for term in [item for item in lexical_terms if len(item) >= 3][:12]:
        try:
            fts_results = database.search(term, limit=100)
        except sqlite3.OperationalError:
            continue
        for rank, result in enumerate(fts_results, start=1):
            chunk_id = int(result["chunk_id"])
            fts_scores[chunk_id] = fts_scores.get(chunk_id, 0.0) + 1.0 / (20.0 + rank)
    maximum_fts = max(fts_scores.values(), default=0.0)

    candidates = []
    for row in database.retrieval_rows():
        context = CONTEXT_BY_SOURCE_KIND.get(row["source_kind"], "unknown")
        if source_kinds and row["source_kind"] not in source_kinds:
            continue
        if version is not None and str(row["version"] or "") != str(version):
            continue
        if contexts and context not in contexts:
            continue

        haystack = normalize_text(
            "%s %s %s %s"
            % (row["title"], row["section_path"], row["speaker"], row["text"])
        )
        coverage = sum(
            len(term) ** 2
            for term in lexical_terms
            if term in haystack
        ) / lexical_denominator
        fts = fts_scores.get(int(row["chunk_id"]), 0.0) / maximum_fts if maximum_fts else 0.0
        lexical = 0.7 * coverage + 0.3 * fts
        semantic = _cosine(query_vector, row["vector"], float(row["norm"] or 0))
        row_entity_ids = {int(item["id"]) for item in row["entities"]}
        entity = (
            len(row_entity_ids & matched_entity_ids) / len(matched_entity_ids)
            if matched_entity_ids
            else 0.0
        )
        section = 1.0 if any(
            normalize_text(item["canonical_name"]) in normalize_text(row["section_path"])
            for item in matched_entities
        ) else 0.0
        candidates.append(
            {
                **{key: value for key, value in row.items() if key not in {"vector", "norm"}},
                "context_type": context,
                "matched_query_entities": [
                    {"name": item["canonical_name"], "type": item["entity_type"]}
                    for item in matched_entities
                    if int(item["id"]) in row_entity_ids
                ],
                "_lexical": lexical,
                "_semantic": semantic,
                "_entity": entity,
                "_section": section,
            }
        )

    for item in candidates:
        lexical = item.pop("_lexical")
        semantic = item.pop("_semantic")
        entity = item.pop("_entity")
        section = item.pop("_section")
        source = SOURCE_WEIGHTS.get(item["source_kind"], 0.8)
        if mode == "lexical":
            score = lexical
        elif mode == "semantic":
            score = semantic
        else:
            score = 0.15 * lexical + 0.55 * semantic + 0.20 * entity + 0.05 * section + 0.05 * source
        item["score"] = round(score, 6)
        item["score_components"] = {
            "lexical": round(lexical, 6),
            "semantic": round(semantic, 6),
            "entity": round(entity, 6),
            "section": round(section, 6),
            "source_quality": round(source, 6),
        }
    candidates.sort(key=lambda item: (-item["score"], int(item["chunk_id"])))
    return candidates[:limit]


def evaluate_retrieval(
    database: Database, dataset_path: Path, mode: str = "hybrid"
) -> Dict[str, Any]:
    payload = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    details = []
    top1 = 0
    top5 = 0
    answerable_count = 0
    no_answer_correct = 0
    for case in cases:
        results = hybrid_search(database, case["question"], limit=5, mode=mode)
        if case.get("unanswerable"):
            correct = not results or results[0]["score"] < float(case.get("max_score", 0.25))
            no_answer_correct += int(correct)
            details.append({"id": case["id"], "unanswerable": True, "correct": correct,
                            "top_score": results[0]["score"] if results else 0.0})
            continue
        answerable_count += 1
        expected_source = str(case["expected_source_id"])
        evidence = normalize_text(case["evidence_contains"])
        hits = [
            index for index, result in enumerate(results)
            if str(result["external_id"]) == expected_source
            and evidence in normalize_text(result["text"])
        ]
        rank = hits[0] + 1 if hits else None
        top1 += int(rank == 1)
        top5 += int(rank is not None and rank <= 5)
        details.append({"id": case["id"], "rank": rank,
                        "top_chunk_id": results[0]["chunk_id"] if results else None})
    no_answer_count = len(cases) - answerable_count
    return {
        "schema_version": 1,
        "mode": mode,
        "cases": len(cases),
        "answerable_cases": answerable_count,
        "unanswerable_cases": no_answer_count,
        "top1_accuracy": round(top1 / answerable_count, 4) if answerable_count else 0.0,
        "top5_recall": round(top5 / answerable_count, 4) if answerable_count else 0.0,
        "unanswerable_accuracy": round(no_answer_correct / no_answer_count, 4) if no_answer_count else None,
        "details": details,
    }
