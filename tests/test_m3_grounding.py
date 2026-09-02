import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.models.database import Database
from app.qa.grounding import answer_question, ground_draft, validate_claims
from app.retrieval import build_retrieval_index, hybrid_search


def make_chunk(position: int, text: str) -> dict:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "chunk_key": "%s:%04d" % (digest[:12], position),
        "section_path": "资料/正文",
        "text": text,
        "position": position,
        "content_sha256": digest,
    }


class GroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "qa.sqlite3")
        self.database.initialize()
        self._add_source(
            "1", "wiki_character", "三月七资料", "1",
            ["前置上下文。", "三月七始终保有独属于她的纯真。星穹列车继续开拓。", "后续上下文。"],
        )
        self._add_source(
            "2", "official_article", "列车官方说明", None,
            ["另一份官方资料记载，列车成员共同踏上开拓旅途。"],
        )
        self._add_source(
            "3", "wiki_character", "列车新版资料", "2",
            ["新版资料称列车暂时停航。"],
        )
        entity_path = self.root / "entities.json"
        entity_path.write_text(
            json.dumps({"entities": [
                {"canonical_name": "三月七", "entity_type": "character", "aliases": ["小三月"]},
                {"canonical_name": "星穹列车", "entity_type": "faction", "aliases": ["列车"]},
                {"canonical_name": "开拓", "entity_type": "path", "aliases": []},
            ]}, ensure_ascii=False), encoding="utf-8"
        )
        self.database.rebuild_fts()
        build_retrieval_index(self.database, entity_path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _add_source(self, external_id, source_kind, title, version, texts) -> None:
        source_id = self.database.upsert_source({
            "provider": "mihoyo_wiki" if source_kind.startswith("wiki") else "miyoushe",
            "external_id": external_id,
            "source_kind": source_kind,
            "parser": "wiki_content" if source_kind.startswith("wiki") else "miyoushe_post",
            "page_url": "https://example.test/%s" % external_id,
            "api_url": "https://example.test/api/%s" % external_id,
        })
        self.database.replace_documents(
            source_id,
            {"title": title, "version": version, "official_status": "wiki" if source_kind.startswith("wiki") else "verified"},
            [{"document_key": "body", "title": "正文", "section_path": "%s/正文" % title,
              "content_type": "test", "position": 0, "evidence_eligible": True,
              "chunks": [make_chunk(index, text) for index, text in enumerate(texts)]}],
        )

    def test_stable_evidence_id_survives_reparse(self) -> None:
        before = next(row for row in self.database.retrieval_rows() if "纯真" in row["text"])
        source_id = int(before["source_id"])
        self.database.replace_documents(
            source_id,
            {"title": "三月七资料", "version": "1", "official_status": "wiki"},
            [{"document_key": "body", "title": "正文", "section_path": "三月七资料/正文",
              "content_type": "test", "position": 0, "evidence_eligible": True,
              "chunks": [make_chunk(0, "前置上下文。"), make_chunk(1, "三月七始终保有独属于她的纯真。星穹列车继续开拓。"), make_chunk(2, "后续上下文。")]}],
        )
        after = next(row for row in self.database.retrieval_rows() if "纯真" in row["text"])
        self.assertNotEqual(before["chunk_id"], after["chunk_id"])
        self.assertEqual(before["evidence_id"], after["evidence_id"])

    def test_explicit_claim_has_claim_level_citation_and_context(self) -> None:
        retrieved = hybrid_search(self.database, "小三月保持了什么？", limit=5)
        evidence = next(item for item in retrieved if "纯真" in item["text"])
        result = validate_claims(self.database, retrieved, [{
            "text": "三月七始终保有独属于她的纯真。",
            "type": "explicit", "evidence_ids": [evidence["evidence_id"]],
        }])
        self.assertEqual(len(result["accepted"]), 1)
        citation = result["accepted"][0]["citations"][0]
        self.assertEqual(citation["url"], "https://example.test/1")
        self.assertEqual(len(citation["adjacent_context"]), 2)

    def test_unsupported_and_unretrieved_claims_are_rejected(self) -> None:
        retrieved = hybrid_search(self.database, "小三月保持了什么？", limit=1)
        other = next(item for item in self.database.retrieval_rows() if item["external_id"] == "2")
        result = validate_claims(self.database, retrieved, [
            {"text": "三月七来自贝洛伯格。", "type": "explicit",
             "evidence_ids": [retrieved[0]["evidence_id"]]},
            {"text": other["text"], "type": "explicit", "evidence_ids": [other["evidence_id"]]},
        ])
        reasons = [reason for item in result["rejected"] for reason in item["reasons"]]
        self.assertIn("claim_not_directly_supported", reasons)
        self.assertIn("evidence_not_retrieved", reasons)

    def test_inference_requires_two_evidence_items_and_reasoning(self) -> None:
        retrieved = hybrid_search(self.database, "列车如何继续开拓？", limit=8)
        one = retrieved[0]["evidence_id"]
        rejected = validate_claims(self.database, retrieved, [{
            "text": "列车成员延续着开拓旅途。", "type": "inferred",
            "evidence_ids": [one], "reasoning_steps": [],
        }])
        self.assertEqual(len(rejected["accepted"]), 0)
        two = [item["evidence_id"] for item in retrieved if "开拓" in item["text"]][:2]
        accepted = validate_claims(self.database, retrieved, [{
            "text": "列车成员延续着开拓旅途。", "type": "inferred",
            "evidence_ids": two, "reasoning_steps": ["两份官方资料都描述列车与开拓旅途。"],
        }])
        self.assertEqual(accepted["accepted"][0]["support_check"], "structural_only")

    def test_conflict_requires_distinct_supported_alternatives(self) -> None:
        retrieved = hybrid_search(self.database, "列车是否继续前进？", limit=8)
        continuing = next(item for item in retrieved if "继续开拓" in item["text"])
        stopped = next(item for item in retrieved if "暂时停航" in item["text"])
        result = validate_claims(self.database, retrieved, [{
            "text": "关于列车状态，当前资料存在冲突。", "type": "conflicted",
            "evidence_ids": [continuing["evidence_id"], stopped["evidence_id"]],
            "alternatives": [
                {"text": "星穹列车继续开拓", "evidence_id": continuing["evidence_id"]},
                {"text": "列车暂时停航", "evidence_id": stopped["evidence_id"]},
            ],
        }])
        self.assertEqual(len(result["accepted"]), 1)

    def test_answer_is_extractive_and_out_of_corpus_question_is_refused(self) -> None:
        answer = answer_question(self.database, "小三月保持了什么？")
        self.assertEqual(answer["status"], "explicit")
        self.assertTrue(answer["claims"][0]["citations"])
        refused = answer_question(self.database, "卡芙卡出生在哪颗星球？")
        self.assertEqual(refused["status"], "uncertain")
        self.assertEqual(refused["claims"], [])

    def test_ground_draft_drops_all_unsupported_claims(self) -> None:
        result = ground_draft(self.database, "小三月保持了什么？", [{
            "text": "她成为了仙舟将军。", "type": "explicit", "evidence_ids": ["made-up"],
        }])
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["claims"], [])
        self.assertIn("evidence_not_retrieved", result["rejected_claims"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
