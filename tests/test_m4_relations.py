import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.knowledge.relations import audit_relations, build_relations, list_relations, review_relation
from app.models.database import Database
from app.retrieval import build_retrieval_index


def chunk(position, text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {"chunk_key": "%s:%04d" % (digest[:12], position), "section_path": "测试/正文",
            "text": text, "position": position, "content_sha256": digest}


class RelationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "relations.sqlite3")
        self.database.initialize()
        source_id = self.database.upsert_source({
            "provider": "mihoyo_wiki", "external_id": "10", "source_kind": "wiki_quest",
            "parser": "wiki_content", "page_url": "https://example.test/10",
            "api_url": "https://example.test/api/10",
        })
        self.database.replace_documents(source_id, {"title": "测试任务", "version": "1", "official_status": "wiki"}, [{
            "document_key": "body", "title": "正文", "section_path": "测试任务/正文",
            "content_type": "test", "position": 0, "evidence_eligible": True,
            "chunks": [chunk(0, "角色甲属于列车阵营。"), chunk(1, "角色甲参加了测试任务。角色乙也在场。")],
        }])
        source_id_2 = self.database.upsert_source({
            "provider": "miyoushe", "external_id": "20", "source_kind": "official_article",
            "parser": "miyoushe_post", "page_url": "https://example.test/20",
            "api_url": "https://example.test/api/20",
        })
        self.database.replace_documents(source_id_2, {"title": "补充资料", "official_status": "verified"}, [{
            "document_key": "body", "title": "正文", "section_path": "补充资料/正文",
            "content_type": "test", "position": 0, "evidence_eligible": True,
            "chunks": [chunk(0, "角色甲与角色乙再次共同执行任务。")],
        }])
        self.entity_path = self.root / "entities.json"
        self.entity_path.write_text(json.dumps({"entities": [
            {"canonical_name": "角色甲", "entity_type": "character", "aliases": []},
            {"canonical_name": "角色乙", "entity_type": "character", "aliases": []},
            {"canonical_name": "列车", "entity_type": "faction", "aliases": []},
        ]}, ensure_ascii=False), encoding="utf-8")
        self.database.rebuild_fts()
        build_retrieval_index(self.database, self.entity_path)
        self.catalogue = self.root / "relations.json"
        self.catalogue.write_text(json.dumps({"relations": [
            {"subject": "角色甲", "predicate": "affiliated_with", "object": "列车",
             "evidence_level": "explicit", "review_status": "approved",
             "evidence": [{"external_id": "10", "evidence_contains": "角色甲属于列车阵营"}]},
            {"subject": "角色甲", "predicate": "associated_with", "object": "角色乙",
             "evidence_level": "inferred", "review_status": "approved", "reasoning": "两份资料均记录共同活动。",
             "evidence": [{"external_id": "10", "evidence_contains": "角色乙也在场"},
                          {"external_id": "20", "evidence_contains": "再次共同执行任务"}]},
            {"subject": "角色乙", "predicate": "affiliated_with", "object": "列车",
             "evidence_level": "explicit", "review_status": "approved",
             "evidence": [{"external_id": "10", "evidence_contains": "角色甲属于列车阵营"}]}
        ]}, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_curated_relations_validate_endpoints_and_inference(self) -> None:
        result = build_relations(self.database, self.catalogue)
        self.assertEqual(result["curated_imported"], 2)
        self.assertEqual(result["curated_rejected"], 1)
        self.assertIn("explicit_evidence_missing_relation_endpoint", result["rejections"][0]["reasons"])

    def test_default_query_hides_cooccurrence_candidates(self) -> None:
        result = build_relations(self.database, self.catalogue)
        public = list_relations(self.database, "角色甲")
        with_candidates = list_relations(self.database, "角色甲", include_candidates=True)
        self.assertEqual(len(public), 2)
        self.assertGreater(len(with_candidates), len(public))
        self.assertTrue(all(item["review_status"] == "approved" for item in public))
        self.assertEqual(result["audit"]["stale"], 0)

    def test_relation_cards_include_direction_and_official_citations(self) -> None:
        build_relations(self.database, self.catalogue)
        relation = next(item for item in list_relations(self.database, "列车") if item["predicate"] == "affiliated_with")
        self.assertEqual(relation["direction"], "incoming")
        self.assertEqual(relation["citations"][0]["url"], "https://example.test/10")
        self.assertIn("evidence_id", relation["citations"][0])

    def test_stale_evidence_is_audited_and_hidden(self) -> None:
        build_relations(self.database, self.catalogue)
        relation = next(item for item in list_relations(self.database, "列车") if item["predicate"] == "affiliated_with")
        with self.database.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE text LIKE '%属于列车阵营%'")
        audit = audit_relations(self.database)
        self.assertIn(relation["id"], audit["stale_ids"])
        self.assertEqual(list_relations(self.database, "列车"), [])

    def test_entity_index_rebuild_preserves_curated_relations(self) -> None:
        build_relations(self.database, self.catalogue)
        before = len(list_relations(self.database))
        build_retrieval_index(self.database, self.entity_path)
        after = len(list_relations(self.database))
        self.assertEqual(before, after)

    def test_candidate_cannot_be_approved_without_semantic_review(self) -> None:
        build_relations(self.database, self.catalogue)
        candidate = next(item for item in list_relations(self.database, include_candidates=True)
                         if item["review_status"] == "pending")
        with self.assertRaises(ValueError):
            review_relation(self.database, candidate["id"], "approved")
        result = review_relation(self.database, candidate["id"], "rejected")
        self.assertEqual(result["review_status"], "rejected")


if __name__ == "__main__":
    unittest.main()
