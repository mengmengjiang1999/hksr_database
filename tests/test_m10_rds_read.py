import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.api.main import build_read_store
from app.cloud.validation import _chunk_retrieval_metadata
from app.cli import build_parser
from app.m10 import compare_reports, manifest_acceptance, quality_gates
from app.models import Database, PostgresReadStore, SQLiteReadStore
from app.models.read_store import _decode_chunked_metadata


class BackendSelectionTests(unittest.TestCase):
    def test_backend_selection_is_explicit_and_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "read.sqlite3"
            with mock.patch.dict(os.environ, {"HKSR_READ_BACKEND": "sqlite"}, clear=False):
                store = build_read_store(path)
            self.assertIsInstance(store, Database)
            with mock.patch.dict(os.environ, {"HKSR_READ_BACKEND": "invalid"}, clear=False):
                with self.assertRaisesRegex(ValueError, "sqlite.*postgres"):
                    build_read_store(path)
            with mock.patch.dict(os.environ, {"HKSR_READ_BACKEND": "postgres"}, clear=False):
                os.environ.pop("HKSR_POSTGRES_DSN", None)
                with self.assertRaisesRegex(ValueError, "HKSR_POSTGRES_DSN"):
                    build_read_store(path)

    def test_cli_m10_commands_have_no_dsn_argument(self) -> None:
        parser = build_parser()
        self.assertNotIn("--dsn", parser.format_help())
        self.assertEqual(parser.parse_args(["m10-manifest"]).backend, "sqlite")
        self.assertEqual(parser.parse_args(["m10-evaluate", "--backend", "postgres"]).backend,
                         "postgres")
        self.assertEqual(parser.parse_args(["m10-shadow"]).limit, 8)

    def test_sqlite_read_facade_preserves_results_but_rejects_mutable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "contract.sqlite3")
            database.initialize()
            facade = SQLiteReadStore(database)
            self.assertEqual(facade.statistics()["counts"], database.statistics()["counts"])
            self.assertEqual(facade.entity_catalog(), database.entity_catalog())
            self.assertFalse(facade.mutable)


class PoolContractTests(unittest.TestCase):
    def test_pool_is_zero_minimum_bounded_and_read_only(self) -> None:
        captured = {}

        class Pool:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def close(self):
                captured["closed"] = True

        with mock.patch("app.models.read_store._require_pool", return_value=Pool):
            store = PostgresReadStore("postgresql://user:secret@example.test/hksr")
        self.assertEqual(captured["min_size"], 0)
        self.assertEqual(captured["max_size"], 2)
        self.assertEqual(captured["timeout"], 5.0)
        self.assertIn("default_transaction_read_only=on", captured["kwargs"]["options"])
        self.assertNotIn("postgresql://", repr(store))
        store.close()
        self.assertTrue(captured["closed"])

    def test_user_facing_read_modules_do_not_open_sqlite_connections(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "app/api/main.py", "app/retrieval.py", "app/qa/evaluation.py",
            "app/qa/grounding.py", "app/qa/intent.py",
        ):
            text = root.joinpath(relative).read_text(encoding="utf-8")
            self.assertNotIn(".connect()", text, relative)
            self.assertNotIn("import sqlite3", text, relative)

    def test_runtime_migration_contains_parity_objects_and_indexes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sql = root.joinpath("migrations/postgres/005_m10_read_runtime.sql").read_text(
            encoding="utf-8"
        ).lower()
        for required in (
            "source_dispositions", "chunk_vectors", "retrieval_metadata",
            "narrative_people", "playable_forms", "identity_names", "sqlite_id",
            "aliases_alias_idx", "entity_chunks_entity_idx",
        ):
            self.assertIn(required, sql)
        self.assertNotIn("postgresql://", sql)

    def test_large_retrieval_metadata_is_chunked_and_verified(self) -> None:
        value = {
            "schema_version": 1,
            "idf": {str(index): index / 10 for index in range(50000)},
        }
        descriptor, payloads = _chunk_retrieval_metadata(json.dumps(value))
        rows = [
            {"ordinal": index, "payload": payload}
            for index, payload in enumerate(payloads)
        ]
        self.assertEqual(_decode_chunked_metadata(descriptor, rows), value)
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.assertEqual(descriptor["raw_sha256"], hashlib.sha256(canonical).hexdigest())
        damaged = copy.deepcopy(rows)
        damaged[-1]["payload"] = bytes(damaged[-1]["payload"][:-1]) + b"x"
        with self.assertRaisesRegex(RuntimeError, "corrupt|length|checksum"):
            _decode_chunked_metadata(descriptor, damaged)

    def test_chunked_metadata_migration_has_foreign_key_and_primary_key(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sql = root.joinpath(
            "migrations/postgres/006_m10_chunked_retrieval_metadata.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("references hksr.retrieval_metadata", sql)
        self.assertIn("primary key (metadata_key, ordinal)", sql)


class AcceptanceReportTests(unittest.TestCase):
    def test_manifest_gates_exact_counts_dispositions_and_evidence(self) -> None:
        manifest = {
            "corpus": {"counts": {
                "sources": 7845, "documents": 6709, "chunks": 20291,
                "eligible_evidence": 20291, "semantic_vectors": 20291,
            }},
            "dispositions": {
                "eligible_evidence": 5661, "excluded_operational": 11,
                "excluded_unavailable": 2173,
            },
            "disposition_rows": 7845,
            "unverified_evidence_sources": 0,
            "stable_evidence_ids": {"unique": True, "synthetic": 0},
        }
        self.assertTrue(manifest_acceptance(manifest)["passed"])
        manifest["corpus"]["counts"]["chunks"] -= 1
        self.assertFalse(manifest_acceptance(manifest)["passed"])

    def test_shadow_ignores_scores_but_blocks_behavior_mismatch(self) -> None:
        report = {
            "dataset_version": "fixed-v1",
            "corpus_snapshot": {"fingerprint": "same"},
            "details": [{
                "id": "q1", "observed_classification": "passed", "correct": True,
                "top_evidence_ids": ["e1"],
                "direct_answer": {
                    "intent": "descriptive", "resolved_entities": [], "status": "explicit",
                    "refused": False, "ambiguity": None, "partial_support": None,
                    "citation_ids": ["e1"],
                },
            }],
        }
        self.assertTrue(compare_reports(report, copy.deepcopy(report))["passed"])
        changed = copy.deepcopy(report)
        changed["details"][0]["direct_answer"]["citation_ids"] = ["e2"]
        comparison = compare_reports(report, changed)
        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["mismatches"][0]["field"], "citation_ids")

    def test_quality_thresholds_are_hard_gates(self) -> None:
        report = {"model_generation_enabled": False, "summary": {
            "top5": {"rate": 0.85}, "direct_answer": {"rate": 0.90},
            "factual_citation_support": {"rate": 1.0}, "refusal": {"rate": 1.0},
        }}
        self.assertTrue(quality_gates(report)["passed"])
        report["summary"]["factual_citation_support"]["rate"] = 0.99
        self.assertFalse(quality_gates(report)["passed"])


if __name__ == "__main__":
    unittest.main()
