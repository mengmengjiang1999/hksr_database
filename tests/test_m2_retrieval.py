import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.models.database import Database
from app.retrieval import build_retrieval_index, evaluate_retrieval, hybrid_search


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "test.sqlite3")
        self.database.initialize()
        self.database.upsert_source(
            {
                "provider": "mihoyo_wiki", "external_id": "1",
                "source_kind": "wiki_character", "parser": "wiki_content",
                "page_url": "https://example.test/1", "api_url": "https://example.test/api/1",
            }
        )
        source_id = int(self.database.list_sources()[0]["id"])
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE sources SET status='parsed', title='三月七资料', version='1', official_status='wiki' WHERE id=?",
                (source_id,),
            )
        texts = [
            "三月七始终保有独属于她的纯真，也陪伴开拓者继续旅行。",
            "星穹列车穿行于银河，列车成员共同踏上开拓旅途。",
            "这里是一段完全无关的养成材料说明。",
        ]
        chunks = []
        for position, text in enumerate(texts):
            chunks.append(
                {
                    "chunk_key": str(position), "section_path": "三月七资料/角色故事",
                    "text": text, "position": position,
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
        self.database.replace_documents(
            source_id,
            {"title": "三月七资料", "version": "1", "official_status": "wiki"},
            [{"document_key": "story", "title": "角色故事",
              "section_path": "三月七资料/角色故事", "content_type": "wiki_rpg_module",
              "position": 0, "evidence_eligible": True, "chunks": chunks}],
        )
        self.entities = self.root / "entities.json"
        self.entities.write_text(
            json.dumps({"entities": [
                {"canonical_name": "三月七", "entity_type": "character",
                 "aliases": [{"text": "小三月", "alias_type": "official"},
                             {"text": "三月", "alias_type": "player"}]},
                {"canonical_name": "星穹列车", "entity_type": "faction", "aliases": ["列车"]},
            ]}, ensure_ascii=False), encoding="utf-8"
        )
        self.database.rebuild_fts()
        build_retrieval_index(self.database, self.entities)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_alias_and_semantic_search_find_evidence(self) -> None:
        results = hybrid_search(self.database, "小三月有什么一直没有失去？", limit=2)
        self.assertIn("纯真", results[0]["text"])
        self.assertEqual(results[0]["matched_query_entities"][0]["name"], "三月七")
        self.assertIn("semantic", results[0]["score_components"])

    def test_exact_entity_speaker_is_an_explicit_ranking_signal(self) -> None:
        with self.database.connect() as connection:
            connection.execute("UPDATE chunks SET speaker='三月七' WHERE position=0")
        results = hybrid_search(self.database, "三月七怎样看待自己的经历？", limit=3)
        spoken = next(item for item in results if item["speaker"] == "三月七")
        self.assertEqual(spoken["score_components"]["speaker"], 1.0)

    def test_filters_are_applied_before_ranking(self) -> None:
        self.assertTrue(hybrid_search(self.database, "列车", contexts=["in_game"]))
        self.assertEqual(hybrid_search(self.database, "列车", contexts=["promotional"]), [])
        self.assertEqual(hybrid_search(self.database, "列车", version="999"), [])

    def test_entity_links_and_vectors_are_idempotent(self) -> None:
        first = self.database.statistics()["counts"]
        build_retrieval_index(self.database, self.entities)
        second = self.database.statistics()["counts"]
        self.assertEqual(first["entities"], second["entities"])
        self.assertEqual(first["entity_chunk_links"], second["entity_chunk_links"])
        self.assertEqual(first["semantic_vectors"], second["semantic_vectors"])

    def test_index_build_does_not_load_existing_vectors_or_all_rows(self) -> None:
        with mock.patch.object(
            self.database,
            "retrieval_rows",
            side_effect=AssertionError("index build loaded materialized retrieval rows"),
        ):
            result = build_retrieval_index(self.database, self.entities)
        self.assertEqual(result["vectors"], 3)

    def test_hybrid_search_loads_only_bounded_candidates(self) -> None:
        with mock.patch.object(
            self.database, "retrieval_rows", wraps=self.database.retrieval_rows
        ) as retrieval_rows:
            results = hybrid_search(self.database, "小三月有什么一直没有失去？", limit=2)
        self.assertTrue(results)
        candidate_ids = retrieval_rows.call_args.args[0]
        self.assertIsNotNone(candidate_ids)
        self.assertTrue(candidate_ids)
        self.assertLessEqual(len(candidate_ids), 500)

    def test_retrieval_metadata_is_cached_until_index_replacement(self) -> None:
        expected = self.database.retrieval_metadata()
        with mock.patch("app.models.database.json.loads", side_effect=AssertionError):
            self.assertIs(self.database.retrieval_metadata(), expected)
        build_retrieval_index(self.database, self.entities)
        self.assertEqual(self.database.retrieval_metadata()["document_count"], 3)

    def test_evaluator_reports_top_k(self) -> None:
        dataset = self.root / "evaluation.json"
        dataset.write_text(json.dumps({"cases": [
            {"id": "one", "question": "小三月失去了纯真吗", "expected_source_id": "1",
             "evidence_contains": "独属于她的纯真"}
        ]}, ensure_ascii=False), encoding="utf-8")
        report = evaluate_retrieval(self.database, dataset)
        self.assertEqual(report["top1_accuracy"], 1.0)
        self.assertEqual(report["top5_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
