"""Secret-safe M10 manifests, quality gates, and offline backend comparison."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.models import ReadStore
from app.qa.evaluation import (
    _canonical_digest,
    corpus_snapshot,
    evaluate_real_questions,
    load_real_question_dataset,
    load_taxonomy,
)
from app.retrieval import MAX_ENTITY_CANDIDATES, MAX_RERANK_CANDIDATES


ACCEPTED_COUNTS = {
    "sources": 7845,
    "documents": 6709,
    "chunks": 20291,
    "eligible_evidence": 20291,
    "semantic_vectors": 20291,
}
ACCEPTED_DISPOSITIONS = {
    "eligible_evidence": 5661,
    "excluded_operational": 11,
    "excluded_unavailable": 2173,
}
HISTORICAL_M9 = {
    "label": "historical_partial_corpus_only",
    "corpus_chunks": 1890,
    "correct": 56,
    "cases": 60,
    "acceptance_eligible": False,
}


def build_manifest(
    store: ReadStore,
    dataset_path: Path,
    taxonomy_path: Path,
    *,
    revision: str = "unknown",
) -> Dict[str, Any]:
    taxonomy = load_taxonomy(taxonomy_path)
    dataset = load_real_question_dataset(dataset_path, taxonomy)
    snapshot = corpus_snapshot(store)
    dispositions = store.source_disposition_rows()
    disposition_counts = Counter(str(row["disposition"]) for row in dispositions)
    unverified = sum(not bool(row["verified"]) for row in dispositions)
    evidence_ids = store.evidence_ids()
    readiness = store.readiness()
    manifest = {
        "schema_version": 1,
        "backend": getattr(store, "backend_name", "unknown"),
        "application_revision": revision,
        "runtime_schema": readiness.get("schema", "sqlite-current"),
        "index_version": "sparse-tfidf-v1",
        "dataset_version": dataset["dataset_version"],
        "dataset_fingerprint": _canonical_digest(dataset),
        "taxonomy_version": taxonomy["taxonomy_version"],
        "taxonomy_fingerprint": _canonical_digest(taxonomy),
        "retrieval": {
            "entity_candidate_limit": MAX_ENTITY_CANDIDATES,
            "rerank_candidate_limit": MAX_RERANK_CANDIDATES,
            "generation_enabled": False,
        },
        "corpus": snapshot,
        "dispositions": dict(sorted(disposition_counts.items())),
        "disposition_rows": len(dispositions),
        "unverified_evidence_sources": unverified,
        "stable_evidence_ids": {
            "count": len(evidence_ids),
            "unique": len(evidence_ids) == snapshot["counts"]["eligible_evidence"],
            "synthetic": sum(item.startswith("synthetic:") for item in evidence_ids),
        },
        "historical_m9_comparison": HISTORICAL_M9,
    }
    manifest["manifest_fingerprint"] = _canonical_digest(manifest)
    manifest["accepted_m7_snapshot"] = manifest_acceptance(manifest)
    return manifest


def manifest_acceptance(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    counts = manifest["corpus"]["counts"]
    count_mismatches = {
        key: {"expected": expected, "observed": int(counts.get(key, -1))}
        for key, expected in ACCEPTED_COUNTS.items()
        if int(counts.get(key, -1)) != expected
    }
    dispositions = manifest["dispositions"]
    disposition_mismatches = {
        key: {"expected": expected, "observed": int(dispositions.get(key, 0))}
        for key, expected in ACCEPTED_DISPOSITIONS.items()
        if int(dispositions.get(key, 0)) != expected
    }
    blockers = []
    if count_mismatches:
        blockers.append("corpus_counts")
    if disposition_mismatches or int(manifest["disposition_rows"]) != ACCEPTED_COUNTS["sources"]:
        blockers.append("source_dispositions")
    if int(manifest["unverified_evidence_sources"]):
        blockers.append("unverified_evidence")
    if not manifest["stable_evidence_ids"]["unique"]:
        blockers.append("duplicate_stable_evidence_id")
    if int(manifest["stable_evidence_ids"]["synthetic"]):
        blockers.append("synthetic_evidence")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "count_mismatches": count_mismatches,
        "disposition_mismatches": disposition_mismatches,
    }


def quality_gates(report: Mapping[str, Any], sqlite_baseline: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    summary = report["summary"]
    top5 = float(summary["top5"]["rate"])
    direct = float(summary["direct_answer"]["rate"])
    citation = float(summary["factual_citation_support"]["rate"])
    refusal = float(summary["refusal"]["rate"])
    baseline_rate = (
        float(sqlite_baseline["summary"]["direct_answer"]["rate"])
        if sqlite_baseline is not None else direct
    )
    checks = {
        "top5_at_least_85_percent": top5 >= 0.85,
        "direct_answer_at_least_90_percent": direct >= 0.90,
        "within_two_points_of_sqlite": direct + 0.02 >= baseline_rate,
        "factual_citations_fully_supported": citation == 1.0,
        "unanswerable_refusal_accuracy": refusal == 1.0,
        "model_generation_disabled": report.get("model_generation_enabled") is False,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run_quality(
    store: ReadStore,
    dataset_path: Path,
    taxonomy_path: Path,
    *,
    limit: int = 8,
    manifest: Optional[Mapping[str, Any]] = None,
    sqlite_baseline: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    report = evaluate_real_questions(store, dataset_path, taxonomy_path, limit=limit)
    report["full_manifest"] = dict(manifest) if manifest is not None else build_manifest(
        store, dataset_path, taxonomy_path
    )
    report["historical_m9_comparison"] = HISTORICAL_M9
    report["quality_gates"] = quality_gates(report, sqlite_baseline)
    return report


def _comparison_view(report: Mapping[str, Any]) -> Dict[str, Any]:
    details = {}
    for item in report["details"]:
        answer = item["direct_answer"]
        details[item["id"]] = {
            "classification": item["observed_classification"],
            "correct": item["correct"],
            "top5_evidence_ids": item["top_evidence_ids"][:5],
            "intent": answer.get("intent"),
            "resolved_entities": [
                (entity.get("canonical_name") or entity.get("name"), entity.get("entity_type") or entity.get("type"))
                for entity in answer.get("resolved_entities") or []
            ],
            "status": answer.get("status"),
            "refused": answer.get("refused"),
            "ambiguity": answer.get("ambiguity"),
            "partial_support": answer.get("partial_support"),
            "citation_ids": answer.get("citation_ids"),
        }
    return details


def compare_reports(sqlite_report: Mapping[str, Any], postgres_report: Mapping[str, Any]) -> Dict[str, Any]:
    left = _comparison_view(sqlite_report)
    right = _comparison_view(postgres_report)
    mismatches = []
    for case_id in sorted(set(left) | set(right)):
        if case_id not in left or case_id not in right:
            mismatches.append({"case_id": case_id, "field": "case", "sqlite": case_id in left, "postgres": case_id in right})
            continue
        for field in left[case_id]:
            if left[case_id][field] != right[case_id][field]:
                mismatches.append({
                    "case_id": case_id,
                    "field": field,
                    "sqlite": left[case_id][field],
                    "postgres": right[case_id][field],
                })
    corpus_equal = (
        sqlite_report["corpus_snapshot"]["fingerprint"]
        == postgres_report["corpus_snapshot"]["fingerprint"]
    )
    return {
        "schema_version": 1,
        "workload": sqlite_report.get("dataset_version"),
        "sqlite_corpus_fingerprint": sqlite_report["corpus_snapshot"]["fingerprint"],
        "postgres_corpus_fingerprint": postgres_report["corpus_snapshot"]["fingerprint"],
        "corpus_equal": corpus_equal,
        "score_policy": "numeric score differences are ignored; normalized downstream fields must match",
        "mismatches": mismatches,
        "passed": corpus_equal and not mismatches,
    }


def write_markdown_report(path: Path, title: str, report: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# %s" % title,
        "",
        "- 结果：%s" % ("通过" if report.get("passed") else "未通过"),
        "- 报告 SHA-256：`%s`" % hashlib.sha256(
            json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "",
        "```json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
