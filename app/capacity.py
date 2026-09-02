"""Reproducible local measurements and cloud capacity projections."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.models.database import Database


def _directory_metrics(root: Path) -> Dict[str, int]:
    files = [path for path in Path(root).rglob("*") if path.is_file()] if root.exists() else []
    return {"files": len(files), "bytes": sum(path.stat().st_size for path in files)}


def _source_metrics(database: Database, raw_root: Path) -> Dict[str, Dict[str, int]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT s.provider, s.external_id, s.source_kind,
                   COUNT(DISTINCT d.id) AS documents,
                   COUNT(c.id) AS chunks,
                   COALESCE(SUM(length(c.text)), 0) AS characters,
                   COALESCE(SUM(length(CAST(c.text AS BLOB))), 0) AS text_utf8_bytes
            FROM sources s
            LEFT JOIN documents d ON d.source_id = s.id
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY s.id ORDER BY s.id
            """
        ).fetchall()
    output: Dict[str, Dict[str, int]] = {}
    for row in rows:
        kind = str(row["source_kind"])
        item = output.setdefault(kind, {
            "sources": 0, "documents": 0, "chunks": 0, "characters": 0,
            "text_utf8_bytes": 0, "raw_bytes": 0,
        })
        item["sources"] += 1
        for key in ("documents", "chunks", "characters", "text_utf8_bytes"):
            item[key] += int(row[key])
        raw_path = Path(raw_root) / str(row["provider"]) / (str(row["external_id"]) + ".json")
        if raw_path.exists():
            item["raw_bytes"] += raw_path.stat().st_size
    return output


def _sqlite_metrics(database: Database) -> Dict[str, int]:
    with database.connect() as connection:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        vector_row = connection.execute(
            """
            SELECT COUNT(*) AS vectors,
                   COALESCE(SUM(length(CAST(vector_json AS BLOB))), 0) AS vector_json_bytes
            FROM chunk_vectors
            """
        ).fetchone()
    return {
        "file_bytes": database.path.stat().st_size if database.path.exists() else 0,
        "page_size": page_size,
        "page_count": page_count,
        "allocated_bytes": page_size * page_count,
        "prototype_sparse_vectors": int(vector_row["vectors"]),
        "prototype_sparse_vector_json_bytes": int(vector_row["vector_json_bytes"]),
    }


def _project_scope(
    source_metrics: Mapping[str, Mapping[str, int]], assumptions: Mapping[str, Any]
) -> Dict[str, Any]:
    by_category: Dict[str, Any] = {}
    missing_samples = []
    totals = {"sources": 0, "raw_bytes": 0, "characters": 0, "text_utf8_bytes": 0, "chunks": 0}
    for category in assumptions["scope"]:
        name = str(category["name"])
        kind = str(category["sample_source_kind"])
        target = int(category["target_count"])
        totals["sources"] += target
        measured = source_metrics.get(kind)
        if not measured or int(measured["sources"]) == 0:
            missing_samples.append(name)
            by_category[name] = {"target_count": target, "sample_source_kind": kind, "status": "missing_sample"}
            continue
        sample_count = int(measured["sources"])
        averages = {
            key: float(measured[key]) / sample_count
            for key in ("raw_bytes", "characters", "text_utf8_bytes", "chunks")
        }
        projected = {key: int(math.ceil(value * target)) for key, value in averages.items()}
        for key, value in projected.items():
            totals[key] += value
        by_category[name] = {
            "target_count": target,
            "sample_source_kind": kind,
            "sample_sources": sample_count,
            "sample_averages": averages,
            "direct_projection": projected,
            "status": "low_confidence_projection",
        }
    return {"by_category": by_category, "direct_totals": totals, "missing_samples": missing_samples}


def _capacity_scenarios(measured: Mapping[str, Any], assumptions: Mapping[str, Any]) -> list:
    vector_dimensions = int(assumptions["vector_dimensions"])
    hnsw_multiplier = float(assumptions["hnsw_index_multiplier"])
    relational_multiplier = float(assumptions["relational_text_multiplier"])
    headroom = float(assumptions["operational_headroom_multiplier"])
    chunks = max(1, int(measured["counts"]["chunks"]))
    average_chunk_bytes = float(measured["counts"]["text_utf8_bytes"]) / chunks
    output = []
    for chunk_count in assumptions["chunk_scenarios"]:
        chunk_count = int(chunk_count)
        text_and_metadata = chunk_count * average_chunk_bytes * relational_multiplier
        float_vector_body = chunk_count * (4 * vector_dimensions + 8)
        half_vector_body = chunk_count * (2 * vector_dimensions + 8)
        output.append({
            "chunks": chunk_count,
            "estimated_text_and_relational_bytes": int(math.ceil(text_and_metadata)),
            "float32_vector_body_bytes": float_vector_body,
            "float32_hnsw_planning_bytes": int(math.ceil(float_vector_body * hnsw_multiplier)),
            "float32_postgres_planning_bytes": int(math.ceil(
                (text_and_metadata + float_vector_body * (1 + hnsw_multiplier)) * headroom
            )),
            "halfvec_vector_body_bytes": half_vector_body,
            "halfvec_hnsw_planning_bytes": int(math.ceil(half_vector_body * hnsw_multiplier)),
            "halfvec_postgres_planning_bytes": int(math.ceil(
                (text_and_metadata + half_vector_body * (1 + hnsw_multiplier)) * headroom
            )),
        })
    return output


def build_capacity_report(
    database_path: Path,
    raw_root: Path,
    assumptions_path: Path,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Measure local data and project explicitly configured cloud scenarios."""
    assumptions = json.loads(Path(assumptions_path).read_text(encoding="utf-8"))
    database = Database(Path(database_path))
    database.initialize()
    source_metrics = _source_metrics(database, Path(raw_root))
    with database.connect() as connection:
        counts_row = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM sources) AS sources,
              (SELECT COUNT(*) FROM documents) AS documents,
              (SELECT COUNT(*) FROM chunks) AS chunks,
              (SELECT COALESCE(SUM(length(text)), 0) FROM chunks) AS characters,
              (SELECT COALESCE(SUM(length(CAST(text AS BLOB))), 0) FROM chunks) AS text_utf8_bytes,
              (SELECT COUNT(*) FROM entities) AS entities,
              (SELECT COUNT(*) FROM relations) AS relations
            """
        ).fetchone()
    measured = {
        "counts": {key: int(counts_row[key]) for key in counts_row.keys()},
        "raw_objects": _directory_metrics(Path(raw_root)),
        "sqlite": _sqlite_metrics(database),
        "by_source_kind": source_metrics,
    }
    projection = _project_scope(source_metrics, assumptions)
    direct_raw = int(projection["direct_totals"]["raw_bytes"])
    object_safety = float(assumptions["object_snapshot_safety_multiplier"])
    retained_versions = int(assumptions["retained_source_versions"])
    projection["object_storage"] = {
        "direct_current_snapshot_bytes": direct_raw,
        "planning_current_snapshot_bytes": int(math.ceil(direct_raw * object_safety)),
        "retained_source_versions": retained_versions,
        "planning_retained_bytes": int(math.ceil(direct_raw * object_safety * retained_versions)),
        "includes_video_binaries": False,
    }
    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(timezone.utc).astimezone().isoformat(),
        "evidence_labels": {
            "measured": "local_files_and_sql",
            "directory_counts": "official_directory_observation",
            "projection": "formula_based_low_confidence",
            "cloud_price": "procurement_date_quote_required",
        },
        "measured": measured,
        "assumptions": assumptions,
        "projection": projection,
        "capacity_scenarios": _capacity_scenarios(measured, assumptions),
        "decision": {
            "region_scope": "mainland_china",
            "baseline": ["private_oss", "rds_postgresql", "pgvector", "private_application_runtime"],
            "separate_vector_service_default": False,
            "architecture_review_chunk_threshold": 1000000,
        },
    }
