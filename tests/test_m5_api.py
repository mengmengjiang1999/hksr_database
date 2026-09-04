import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.knowledge import build_relations
from app.models.database import Database
from app.qa import GenerationService
from app.retrieval import build_retrieval_index


class ApiFakeAdapter:
    name = "api-fake"

    def __init__(self, response):
        self.response = response

    def generate(self, evidence_packet, **kwargs):
        return self.response


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

    def test_catalog_is_read_only_and_exposes_deterministic_facets(self) -> None:
        database = Database(self.database_path)
        before = database.statistics()
        response = self.client.get("/api/catalog")
        after = database.statistics()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        payload = response.json()
        self.assertEqual(payload["source_statuses"], {"parsed": 1})
        self.assertEqual(payload["source_kinds"], [{"value": "wiki_character", "count": 1}])
        self.assertEqual(payload["versions"], [{"value": "1", "count": 1}])
        self.assertEqual(payload["contexts"], [{"value": "in_game", "count": 1}])

    def test_product_page_contains_evidence_and_relation_surfaces(self) -> None:
        page = Path(__file__).resolve().parents[1].joinpath("web/index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("逐条", page) if "逐条" in page else self.assertIn("citationHTML", page)
        self.assertIn("相邻上下文", page)
        self.assertIn("已审核关联", page)
        self.assertIn("隶属或关联于", page)
        self.assertIn("资料概览", page)

    def test_product_page_contains_navigation_search_and_coverage_states(self) -> None:
        page = Path(__file__).resolve().parents[1].joinpath("web/index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('href="#ask"', page)
        self.assertIn('href="#search"', page)
        self.assertIn('href="#coverage"', page)
        self.assertIn("/api/catalog", page)
        self.assertIn("source_kind", page)
        self.assertIn("当前资料中没有匹配证据", page)
        self.assertIn("资料仍在增长", page)
        self.assertIn("相邻上下文", page)
        self.assertIn("已审核关联", page)
        self.assertIn("@media(max-width:640px)", page)
        self.assertIn("玩家常用称呼（非官方名称）", page)
        self.assertIn("use_generation", page)
        self.assertIn("partial_support", page)
        self.assertIn("需要明确形态", page)

    def test_ask_returns_grounded_claim_and_approved_relations(self) -> None:
        response = self.client.post("/api/ask", json={"question": "小三月保持了什么？"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "explicit")
        self.assertTrue(payload["claims"][0]["citations"])
        self.assertIn(payload["intent"], {"descriptive", "identity"})
        self.assertIn("resolved_entities", payload)
        self.assertIn("ambiguity", payload)
        self.assertIn("partial_support", payload)
        self.assertEqual(payload["generation_outcome"], "not_requested")
        self.assertIn("answer_strategy", payload)
        relations = [relation for group in payload["related_entities"] for relation in group["relations"]]
        self.assertTrue(relations)
        self.assertTrue(all(item["review_status"] == "approved" for item in relations))

    def test_optional_generation_success_and_fallback_are_api_compatible(self) -> None:
        evidence = Database(self.database_path).retrieval_rows()[0]
        valid = {"answer": "三月七始终保有独属于自己的纯真。", "claims": [{
            "text": "三月七始终保有独属于自己的纯真。", "type": "explicit",
            "supports": [{"evidence_id": evidence["evidence_id"], "span": "独属于自己的纯真"}],
        }]}
        self.client.app.state.generation_service = GenerationService(ApiFakeAdapter(valid))
        generated = self.client.post("/api/ask", json={
            "question": "小三月保持了什么？", "use_generation": True
        }).json()
        self.assertEqual(generated["generation_outcome"], "validated")
        self.assertEqual(generated["answer_strategy"], "constrained_generation")
        self.client.app.state.generation_service = GenerationService(ApiFakeAdapter({}))
        fallback = self.client.post("/api/ask", json={
            "question": "小三月保持了什么？", "use_generation": True
        }).json()
        self.assertEqual(fallback["generation_outcome"], "invalid_schema")
        self.assertTrue(fallback["generation_fallback"])

    def test_identity_browse_endpoint_and_legacy_request_remain_available(self) -> None:
        self.assertEqual(self.client.get("/api/identities").status_code, 200)
        legacy = self.client.post("/api/ask", json={"question": "小三月保持了什么？"})
        self.assertEqual(legacy.status_code, 200)
        self.assertTrue(legacy.json()["claims"])

    def test_request_validation_and_missing_resources(self) -> None:
        self.assertEqual(self.client.post("/api/ask", json={"question": ""}).status_code, 422)
        self.assertEqual(self.client.get("/api/search", params={"q": ""}).status_code, 422)
        self.assertEqual(self.client.get("/api/sources/9999").status_code, 404)
        self.assertEqual(self.client.get("/api/entities/9999").status_code, 404)

    def test_search_source_and_entity_browsing(self) -> None:
        search = self.client.get("/api/search", params={"q": "三月七"}).json()
        self.assertIn("纯真", search["results"][0]["text"])
        self.assertEqual(search["results"][0]["source_id"], self.source_id)
        filtered = self.client.get(
            "/api/search",
            params={"q": "三月七", "source_kind": "wiki_character", "context": "in_game", "version": "1"},
        ).json()
        self.assertEqual(len(filtered["results"]), 1)
        source = self.client.get("/api/sources/%d" % self.source_id).json()
        self.assertEqual(source["source"]["external_id"], "1")
        self.assertEqual(source["source"]["id"], search["results"][0]["source_id"])
        self.assertEqual(source["source"]["page_url"], search["results"][0]["page_url"])
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
