import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from app.capacity import build_capacity_report
from app.cli import main
from app.models.database import Database


class CapacityReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database_path = self.root / "capacity.sqlite3"
        self.raw_root = self.root / "raw"
        self.assumptions_path = self.root / "assumptions.json"
        database = Database(self.database_path)
        database.initialize()
        self.kinds = ("wiki_character", "wiki_quest", "wiki_readable", "official_video")
        for index, kind in enumerate(self.kinds):
            provider = "provider%d" % index
            external_id = "source%d" % index
            source_id = database.upsert_source({
                "provider": provider, "external_id": external_id, "source_kind": kind,
                "parser": "wiki_content", "page_url": "https://example.test/%d" % index,
                "api_url": "https://example.test/api/%d" % index,
            })
            text = "星穹铁道"
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            database.replace_documents(source_id, {
                "title": kind, "version": "1", "official_status": "wiki",
            }, [{
                "document_key": "body", "title": kind, "section_path": kind + "/正文",
                "content_type": "test", "position": 0, "evidence_eligible": True,
                "chunks": [{
                    "chunk_key": digest[:12] + ":0000", "section_path": kind + "/正文",
                    "text": text, "position": 0, "content_sha256": digest,
                }],
            }])
            path = self.raw_root / provider / (external_id + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"1234")
        self.assumptions = {
            "schema_version": 1,
            "scope": [
                {"name": kind, "target_count": 2, "sample_source_kind": kind}
                for kind in self.kinds
            ],
            "chunk_scenarios": [10, 100],
            "vector_dimensions": 2,
            "hnsw_index_multiplier": 1.5,
            "relational_text_multiplier": 3.0,
            "operational_headroom_multiplier": 1.3,
            "object_snapshot_safety_multiplier": 5.0,
            "retained_source_versions": 12,
        }
        self.assumptions_path.write_text(
            json.dumps(self.assumptions), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_measured_values_and_scope_projection_are_separate(self) -> None:
        report = build_capacity_report(
            self.database_path, self.raw_root, self.assumptions_path,
            generated_at="2026-09-02T00:00:00+08:00",
        )
        self.assertEqual(report["measured"]["counts"]["sources"], 4)
        self.assertEqual(report["measured"]["counts"]["chunks"], 4)
        self.assertEqual(report["measured"]["counts"]["characters"], 16)
        self.assertEqual(report["measured"]["counts"]["text_utf8_bytes"], 48)
        self.assertEqual(report["measured"]["raw_objects"], {"files": 4, "bytes": 16})
        self.assertEqual(report["projection"]["direct_totals"]["sources"], 8)
        self.assertEqual(report["projection"]["direct_totals"]["chunks"], 8)
        self.assertEqual(report["projection"]["direct_totals"]["raw_bytes"], 32)
        self.assertFalse(report["projection"]["missing_samples"])

    def test_dense_vector_scenario_formulas_are_reproducible(self) -> None:
        scenario = build_capacity_report(
            self.database_path, self.raw_root, self.assumptions_path
        )["capacity_scenarios"][0]
        self.assertEqual(scenario["chunks"], 10)
        self.assertEqual(scenario["float32_vector_body_bytes"], 160)
        self.assertEqual(scenario["float32_hnsw_planning_bytes"], 240)
        self.assertEqual(scenario["halfvec_vector_body_bytes"], 120)
        self.assertEqual(scenario["halfvec_hnsw_planning_bytes"], 180)
        self.assertGreater(scenario["float32_postgres_planning_bytes"], 400)

    def test_cli_emits_machine_readable_report_without_network(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main([
                "--database", str(self.database_path), "capacity-report",
                "--raw-root", str(self.raw_root),
                "--assumptions", str(self.assumptions_path),
            ])
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["decision"]["region_scope"], "mainland_china")
        self.assertEqual(payload["capacity_scenarios"][1]["chunks"], 100)


if __name__ == "__main__":
    unittest.main()
