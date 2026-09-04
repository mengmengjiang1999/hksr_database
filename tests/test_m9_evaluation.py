import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.models.database import Database
from app.qa.evaluation import (
    corpus_snapshot,
    evaluate_real_questions,
    load_real_question_dataset,
    load_taxonomy,
)
from app.retrieval import build_retrieval_index


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "data/m9/question-taxonomy.json"
QUESTIONS = ROOT / "data/m9/real-questions.json"


class M9EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "test.sqlite3")
        self.database.initialize()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _add_evidence(self) -> None:
        source_id = self.database.upsert_source({
            "provider": "mihoyo_wiki", "external_id": "7484",
            "source_kind": "wiki_character", "parser": "wiki_content",
            "page_url": "https://example.test/7484",
            "api_url": "https://example.test/api/7484",
        })
        text = "姬子资料：阵营 星穹列车。"
        self.database.replace_documents(
            source_id,
            {"title": "姬子", "version": "1", "official_status": "wiki"},
            [{"document_key": "body", "title": "正文", "section_path": "姬子/资料",
              "content_type": "test", "position": 0, "evidence_eligible": True,
              "chunks": [{"chunk_key": "0", "section_path": "姬子/资料", "text": text,
                          "position": 0, "content_sha256": hashlib.sha256(text.encode()).hexdigest()}]}],
        )
        entities = self.root / "entities.json"
        entities.write_text(json.dumps({"entities": [
            {"canonical_name": "姬子", "entity_type": "character", "aliases": []}
        ]}, ensure_ascii=False), encoding="utf-8")
        self.database.rebuild_fts()
        build_retrieval_index(self.database, entities)

    def test_repository_taxonomy_and_real_question_dataset_are_valid(self) -> None:
        taxonomy = load_taxonomy(TAXONOMY)
        dataset = load_real_question_dataset(QUESTIONS, taxonomy)
        self.assertEqual(taxonomy["taxonomy_version"], dataset["taxonomy_version"])
        self.assertGreaterEqual(len(dataset["cases"]), 50)
        self.assertLessEqual(len(dataset["cases"]), 100)
        outcomes = {case["expectation"]["outcome"] for case in dataset["cases"]}
        self.assertEqual(outcomes, {"answerable", "pending_corpus", "ambiguous", "correct_refusal"})

    def test_corpus_snapshot_is_stable_and_changes_with_evidence(self) -> None:
        first = corpus_snapshot(self.database)
        second = corpus_snapshot(self.database)
        self.assertEqual(first, second)
        self._add_evidence()
        changed = corpus_snapshot(self.database)
        self.assertNotEqual(first["fingerprint"], changed["fingerprint"])
        self.assertEqual(changed["counts"]["eligible_evidence"], 1)

    def test_baseline_distinguishes_pass_pending_and_parsing_defect(self) -> None:
        self._add_evidence()
        taxonomy = load_taxonomy(TAXONOMY)
        dataset = {
            "schema_version": 1,
            "dataset_version": "test-v1",
            "taxonomy_version": taxonomy["taxonomy_version"],
            "cases": [],
        }
        for index in range(50):
            if index == 0:
                case = {"id": "pass", "question": "姬子属于哪个阵营？", "intent": "descriptive",
                        "expectation": {"outcome": "answerable", "evidence": [{
                            "provider": "mihoyo_wiki", "external_id": "7484", "contains": "阵营 星穹列车"
                        }]}}
            elif index == 1:
                case = {"id": "parse", "question": "姬子的不存在字段？", "intent": "descriptive",
                        "expectation": {"outcome": "answerable", "evidence": [{
                            "provider": "mihoyo_wiki", "external_id": "7484", "contains": "不存在字段"
                        }]}}
            else:
                case = {"id": "pending-%02d" % index, "question": "待采集问题%d" % index,
                        "intent": "unknown", "expectation": {"outcome": "pending_corpus",
                        "pending_reason": "test", "evidence": [{"provider": "mihoyo_wiki",
                        "external_id": "missing-%d" % index, "contains": "待采集"}]}}
            dataset["cases"].append(case)
        dataset_path = self.root / "questions.json"
        dataset_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
        first = evaluate_real_questions(self.database, dataset_path, TAXONOMY)
        second = evaluate_real_questions(self.database, dataset_path, TAXONOMY)
        self.assertEqual(first, second)
        by_id = {item["id"]: item for item in first["details"]}
        self.assertEqual(by_id["pass"]["observed_classification"], "passed")
        self.assertEqual(by_id["parse"]["observed_classification"], "parsing_defect")
        self.assertTrue(by_id["pending-02"]["correct"])


if __name__ == "__main__":
    unittest.main()
