import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.knowledge import build_relations
from app.models.database import Database
from app.retrieval import build_retrieval_index


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database_path = self.root / "api.sqlite3"
        database = Database(self.database_path)
        database.initialize()
        self.source_id = database.upsert_source({
            "provider": "mihoyo_wiki", "external_id": "1", "source_kind": "wiki_character",
            "parser": "wiki_content", "page_url": "https://example.test/wiki/1",
            "api_url": "https://example.test/api/1",
        })
        text = "三月七属于星穹列车，她始终保有独属于自己的纯真。"
        digest = hashlib.sha256(text.encode()).hexdigest()
        database.replace_documents(self.source_id, {"title": "三月七资料", "version": "1", "official_status": "wiki"}, [{
            "document_key": "body", "title": "正文", "section_path": "三月七资料/正文",
            "content_type": "test", "position": 0, "evidence_eligible": True,
            "chunks": [{"chunk_key": digest[:12] + ":0000", "section_path": "三月七资料/正文",
                        "text": text, "position": 0, "content_sha256": digest}],
        }])
        self.entities = self.root / "entities.json"
        self.entities.write_text(json.dumps({"entities": [
            {"canonical_name": "三月七", "entity_type": "character", "aliases": ["小三月"]},
            {"canonical_name": "星穹列车", "entity_type": "faction", "aliases": ["列车"]},
        ]}, ensure_ascii=False), encoding="utf-8")
        database.rebuild_fts()
        build_retrieval_index(database, self.entities)
        self.relations = self.root / "relations.json"
        self.relations.write_text(json.dumps({"relations": [{
            "subject": "三月七", "predicate": "affiliated_with", "object": "星穹列车",
            "evidence_level": "explicit", "review_status": "approved",
            "evidence": [{"external_id": "1", "evidence_contains": "三月七属于星穹列车"}],
        }]}, ensure_ascii=False), encoding="utf-8")
        build_relations(database, self.relations)
        self.web = self.root / "web"
        self.web.mkdir()
        self.web.joinpath("index.html").write_text("<!doctype html><title>星穹档案室</title>", encoding="utf-8")
        self.client = TestClient(create_app(
            database_path=self.database_path, raw_root=self.root / "raw",
            entity_path=self.entities, relation_path=self.relations, web_root=self.web,
        ))

    def tearDown(self) -> None:
        self.client.close()
        self.directory.cleanup()

    def test_home_health_and_openapi_are_available(self) -> None:
        self.assertIn("星穹档案室", self.client.get("/").text)
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_product_page_contains_evidence_and_relation_surfaces(self) -> None:
        page = Path(__file__).resolve().parents[1].joinpath("web/index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("逐条", page) if "逐条" in page else self.assertIn("citationHTML", page)
        self.assertIn("相邻上下文", page)
        self.assertIn("已审核关联", page)
        self.assertIn("隶属或关联于", page)
        self.assertIn("查看数据库状态", page)

    def test_ask_returns_grounded_claim_and_approved_relations(self) -> None:
        response = self.client.post("/api/ask", json={"question": "小三月保持了什么？"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "explicit")
        self.assertTrue(payload["claims"][0]["citations"])
        relations = [relation for group in payload["related_entities"] for relation in group["relations"]]
        self.assertTrue(relations)
        self.assertTrue(all(item["review_status"] == "approved" for item in relations))

    def test_request_validation_and_missing_resources(self) -> None:
        self.assertEqual(self.client.post("/api/ask", json={"question": ""}).status_code, 422)
        self.assertEqual(self.client.get("/api/search", params={"q": ""}).status_code, 422)
        self.assertEqual(self.client.get("/api/sources/9999").status_code, 404)
        self.assertEqual(self.client.get("/api/entities/9999").status_code, 404)

    def test_search_source_and_entity_browsing(self) -> None:
        search = self.client.get("/api/search", params={"q": "三月七"}).json()
        self.assertIn("纯真", search["results"][0]["text"])
        source = self.client.get("/api/sources/%d" % self.source_id).json()
        self.assertEqual(source["source"]["external_id"], "1")
        entity_id = Database(self.database_path).entity_catalog()[0]["id"]
        entity = self.client.get("/api/entities/%d" % entity_id).json()
        self.assertEqual(entity["entity"]["canonical_name"], "三月七")

    def test_status_is_read_only_and_hides_pending_relations(self) -> None:
        database = Database(self.database_path)
        before = database.statistics()
        status = self.client.get("/api/admin/status")
        after = database.statistics()
        self.assertEqual(status.status_code, 200)
        self.assertEqual(before, after)
        relations = self.client.get("/api/relations").json()["relations"]
        self.assertTrue(relations)
        self.assertTrue(all(item["review_status"] == "approved" for item in relations))

    def test_sync_is_explicit_and_can_run_without_network_fetch(self) -> None:
        response = self.client.post("/api/admin/sync", json={"fetch": False})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertNotIn("fetch", payload["stages"])
        self.assertIn("retrieval", payload["stages"])
        self.assertIn("relations", payload["stages"])


if __name__ == "__main__":
    unittest.main()
