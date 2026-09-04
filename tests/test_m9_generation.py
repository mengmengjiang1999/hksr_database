import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.models.database import Database
from app.qa.generation import GenerationService, build_evidence_packet, validate_generated_response
from app.qa.grounding import answer_question
from app.retrieval import build_retrieval_index


class FakeAdapter:
    name = "fake"

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0
        self.last_packet = None

    def generate(self, evidence_packet, **kwargs):
        self.calls += 1
        self.last_packet = evidence_packet
        if self.error:
            raise self.error
        return self.response


class M9GenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.database = Database(root / "test.sqlite3")
        self.database.initialize()
        source_id = self.database.upsert_source({
            "provider": "mihoyo_wiki", "external_id": "1", "source_kind": "wiki_character",
            "parser": "wiki_content", "page_url": "https://example.test/1",
            "api_url": "https://example.test/api/1",
        })
        texts = ["三月七始终保有独属于她的纯真。", "三月七与星穹列车的同伴继续开拓旅途。"]
        self.database.replace_documents(
            source_id, {"title": "三月七", "version": "1", "official_status": "wiki"},
            [{"document_key": "story", "title": "故事", "section_path": "三月七/故事",
              "content_type": "test", "position": 0, "evidence_eligible": True,
              "chunks": [{"chunk_key": str(index), "section_path": "三月七/故事",
                          "text": text, "position": index,
                          "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
                         for index, text in enumerate(texts)]}],
        )
        entities = root / "entities.json"
        entities.write_text(json.dumps({"entities": [
            {"canonical_name": "三月七", "entity_type": "character", "aliases": []},
            {"canonical_name": "星穹列车", "entity_type": "faction", "aliases": ["列车"]},
        ]}, ensure_ascii=False), encoding="utf-8")
        self.database.rebuild_fts()
        build_retrieval_index(self.database, entities)
        self.question = "三月七保留了什么？"
        self.deterministic = answer_question(self.database, self.question)
        self.packet = build_evidence_packet(self.database, self.question)
        self.evidence_id = self.packet["evidence"][0]["evidence_id"]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _valid_response(self):
        return {"answer": "三月七依然保有纯真。", "claims": [{
            "text": "三月七依然保有纯真。", "type": "explicit",
            "supports": [{"evidence_id": self.evidence_id, "span": "独属于她的纯真"}],
        }], "usage": {"input_tokens": 100, "output_tokens": 20}}

    def test_validated_generation_uses_only_packet_and_exact_spans(self) -> None:
        adapter = FakeAdapter(self._valid_response())
        service = GenerationService(adapter)
        result = service.answer(self.database, self.question, self.deterministic)
        self.assertEqual(result["generation_outcome"], "validated")
        self.assertEqual(result["answer_strategy"], "constrained_generation")
        self.assertEqual(result["claims"][0]["support_check"], "exact_generated_spans")
        self.assertTrue(result["claims"][0]["citations"])
        self.assertEqual(adapter.last_packet, self.packet)
        self.assertNotIn("credentials", adapter.last_packet)

    def test_validator_rejects_unretrieved_span_and_bad_inference(self) -> None:
        invalid = validate_generated_response(self.packet, {"answer": "x", "claims": [{
            "text": "x", "type": "explicit",
            "supports": [{"evidence_id": "outside", "span": "模型记忆"}],
        }]})
        self.assertIn("evidence_not_in_packet", invalid["rejected"][0]["reasons"])
        one_evidence = validate_generated_response(self.packet, {"answer": "x", "claims": [{
            "text": "x", "type": "inferred", "reasoning_steps": [],
            "supports": [{"evidence_id": self.evidence_id, "span": "纯真"}],
        }]})
        self.assertIn("invalid_inference", one_evidence["rejected"][0]["reasons"])
        unsupported = validate_generated_response(self.packet, {"answer": "x", "claims": [{
            "text": "景元来自仙舟罗浮。", "type": "explicit",
            "supports": [{"evidence_id": self.evidence_id, "span": "独属于她的纯真"}],
        }]})
        self.assertIn("claim_not_supported_by_span", unsupported["rejected"][0]["reasons"])

    def test_all_failure_modes_fall_back_to_deterministic_answer(self) -> None:
        cases = {
            "disabled": GenerationService(None),
            "timeout": GenerationService(FakeAdapter(error=TimeoutError())),
            "provider_error": GenerationService(FakeAdapter(error=RuntimeError("secret"))),
            "invalid_schema": GenerationService(FakeAdapter({})),
            "empty_validation": GenerationService(FakeAdapter({"answer": "x", "claims": [{
                "text": "x", "type": "explicit",
                "supports": [{"evidence_id": self.evidence_id, "span": "不存在"}],
            }]})),
            "policy_rejection": GenerationService(FakeAdapter({
                "policy_rejected": True, "answer": "", "claims": []
            })),
        }
        for expected, service in cases.items():
            with self.subTest(expected=expected):
                result = service.answer(self.database, self.question, self.deterministic)
                self.assertEqual(result["generation_outcome"], expected)
                self.assertTrue(result["generation_fallback"])
                self.assertEqual(result["answer"], self.deterministic["answer"])

    def test_only_validated_results_are_cached_and_telemetry_is_secret_free(self) -> None:
        adapter = FakeAdapter(self._valid_response())
        service = GenerationService(adapter, cache_size=1)
        first = service.answer(self.database, self.question, self.deterministic)
        second = service.answer(self.database, self.question, self.deterministic)
        self.assertEqual(first["generation_outcome"], "validated")
        self.assertEqual(second["generation_outcome"], "cache_hit")
        self.assertEqual(adapter.calls, 1)
        telemetry = service.telemetry()
        self.assertEqual(telemetry["input_tokens"], 100)
        self.assertEqual(telemetry["output_tokens"], 20)
        rendered = json.dumps(telemetry)
        self.assertNotIn(self.question, rendered)
        self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()
