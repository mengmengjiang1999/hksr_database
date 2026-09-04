import hashlib
import tempfile
import unittest
from pathlib import Path

from app.knowledge.identity import replace_identity_catalog
from app.models.database import Database
from app.qa.intent import build_query_plan, detect_intent, resolve_query_entities
from app.qa.grounding import answer_question
from app.retrieval import build_retrieval_index, hybrid_search, intent_search


ROOT = Path(__file__).resolve().parents[1]


class IntentDetectionTests(unittest.TestCase):
    def test_all_m9_intents_are_deterministic(self) -> None:
        examples = {
            "identity": "绯英是谁？",
            "playable_form": "姬子有几个可玩形态？",
            "relation": "姬子和星穹列车是什么关系？",
            "acquisition": "一页寄语怎么获得？",
            "temporal": "这个活动什么时候开放？",
            "descriptive": "姬子的定位是什么？",
            "comparison": "两个形态有什么区别？",
            "unknown": "随便聊聊",
        }
        self.assertEqual({key: detect_intent(value) for key, value in examples.items()},
                         {key: key for key in examples})


class M9IntentRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "test.sqlite3")
        self.database.initialize()
        wiki_id = self._add_source(
            "mihoyo_wiki", "7484", "wiki_character", "姬子•启行",
            [("module:11", "e7eb585da54b:0000", "角色信息",
              "姬子•启行属于星穹列车，是可操控机甲的输出型角色。"),
             ("module:19", "f38ee6fadbbf:0000", "角色故事",
              "别担心，姬子。姬子与星穹列车的同伴一起启程远航。"),
             ("module:20", "acquisition:0000", "获取方式",
              "启行纪念品\n获取方式：完成同行任务后获取。"),
             ("module:21", "release:0000", "角色信息",
              "姬子•启行\n实装日期\n2026/07/15")],
        )
        self._add_source(
            "miyoushe", "99", "official_article", "官方补充",
            [("body", "0", "正文", "姬子•启行属于星穹列车，是可操控机甲的输出型角色。")],
        )
        self.entities = self.root / "entities.json"
        self.entities.write_text(
            '{"entities":['
            '{"canonical_name":"姬子","entity_type":"character","aliases":[]},'
            '{"canonical_name":"星穹列车","entity_type":"faction","aliases":["列车"]},'
            '{"canonical_name":"阿格莱雅","entity_type":"character","aliases":[]}'
            ']}', encoding="utf-8"
        )
        self.database.rebuild_fts()
        build_retrieval_index(self.database, self.entities)
        replace_identity_catalog(self.database, ROOT / "data/m9/identities.json")
        build_retrieval_index(self.database, self.entities)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _add_source(self, provider, external_id, source_kind, title, chunks):
        source_id = self.database.upsert_source({
            "provider": provider, "external_id": external_id, "source_kind": source_kind,
            "parser": "wiki_content" if provider == "mihoyo_wiki" else "miyoushe_post",
            "page_url": "https://example.test/%s" % external_id,
            "api_url": "https://example.test/api/%s" % external_id,
        })
        documents = []
        for position, (document_key, chunk_key, section, text) in enumerate(chunks):
            documents.append({
                "document_key": document_key, "title": section,
                "section_path": "%s/%s" % (title, section), "content_type": "test",
                "position": position, "evidence_eligible": True,
                "chunks": [{"chunk_key": chunk_key, "section_path": "%s/%s" % (title, section),
                            "text": text, "position": 0,
                            "content_sha256": hashlib.sha256(text.encode()).hexdigest()}],
            })
        self.database.replace_documents(
            source_id, {"title": title, "version": "1",
                        "official_status": "wiki" if provider == "mihoyo_wiki" else "verified"},
            documents,
        )
        return source_id

    def test_punctuation_exact_form_and_two_endpoints_are_preserved(self) -> None:
        dotted = resolve_query_entities(self.database, "姬子·启行的定位是什么？")
        self.assertEqual(dotted[0]["canonical_name"], "姬子·启行")
        bulleted = resolve_query_entities(self.database, "姬子•启行的定位是什么？")
        self.assertEqual(bulleted[0]["canonical_name"], "姬子·启行")
        endpoints = build_query_plan(self.database, "姬子和姬子·启行是什么关系？")["relation_endpoints"]
        self.assertEqual([item["canonical_name"] for item in endpoints], ["姬子", "姬子·启行"])

    def test_bare_person_form_question_is_explicitly_ambiguous(self) -> None:
        result = intent_search(self.database, "姬子的技能是什么？")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["answerable_results"], [])
        self.assertEqual(result["query_plan"]["ambiguity"]["candidates"], ["姬子", "姬子·启行"])

    def test_relation_gate_requires_both_endpoints_or_approved_relation(self) -> None:
        supported = intent_search(self.database, "姬子和星穹列车是什么关系？", limit=5)
        self.assertEqual(supported["status"], "ready")
        self.assertTrue(supported["answerable_results"])
        unsupported = intent_search(self.database, "姬子和阿格莱雅是什么关系？", limit=5)
        self.assertEqual(unsupported["status"], "insufficient_relation_evidence")
        self.assertEqual(unsupported["answerable_results"], [])

    def test_wiki_is_primary_and_diversification_is_diagnostic(self) -> None:
        results = hybrid_search(self.database, "姬子启行属于哪个阵营？", limit=4)
        self.assertEqual(results[0]["provider"], "mihoyo_wiki")
        self.assertIn("source_diversity_penalty", results[0]["retrieval_diagnostics"])
        self.assertIn("diversity_penalty", results[0]["score_components"])

    def test_direct_templates_answer_forms_identity_acquisition_and_time(self) -> None:
        forms = answer_question(self.database, "姬子有几个可玩形态？")
        self.assertEqual(forms["answer_strategy"], "playable_form_template")
        self.assertIn("姬子·启行", forms["answer"])
        identity = answer_question(self.database, "姬子和姬子·启行是什么关系？")
        self.assertEqual(identity["answer_strategy"], "identity_relation_template")
        self.assertIn("同一人物", identity["answer"])
        acquisition = answer_question(self.database, "姬子·启行的纪念品怎么获得？")
        self.assertEqual(acquisition["answer_strategy"], "acquisition_template")
        self.assertIn("获取", acquisition["answer"])
        temporal = answer_question(self.database, "姬子·启行什么时候实装？")
        self.assertEqual(temporal["answer_strategy"], "temporal_template")
        self.assertIn("2026/07/15", temporal["answer"])
        for result in (forms, identity, acquisition, temporal):
            self.assertTrue(result["claims"])
            self.assertTrue(result["claims"][0]["citations"])

    def test_partial_answer_and_ambiguity_do_not_invent_missing_part(self) -> None:
        ambiguous = answer_question(self.database, "姬子的技能是什么？")
        self.assertEqual(ambiguous["status"], "uncertain")
        self.assertEqual(ambiguous["answer_strategy"], "ambiguity")
        partial = answer_question(self.database, "姬子有几个可玩形态以及她出生在哪里？")
        self.assertEqual(partial["status"], "partial")
        self.assertTrue(partial["partial_support"]["is_partial"])
        self.assertEqual(partial["partial_support"]["unsupported_parts"], ["她出生在哪里？"])


if __name__ == "__main__":
    unittest.main()
