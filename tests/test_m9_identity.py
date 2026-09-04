import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.knowledge.identity import (
    audit_identity_catalog,
    identity_catalog,
    load_identity_catalog,
    replace_identity_catalog,
    resolve_identity_name,
)
from app.retrieval import build_retrieval_index, hybrid_search
from app.models.database import Database, stable_evidence_id


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/m9/identities.json"


class M9IdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "test.sqlite3")
        self.database.initialize()
        source_id = self.database.upsert_source({
            "provider": "mihoyo_wiki", "external_id": "7484",
            "source_kind": "wiki_character", "parser": "wiki_content",
            "page_url": "https://example.test/7484", "api_url": "https://example.test/api/7484",
        })
        texts = [
            ("module:11", "e7eb585da54b:0000", "角色信息", "姬子•启行，阵营 星穹列车。"),
            ("module:19", "f38ee6fadbbf:0000", "角色故事", "别担心，姬子。女孩想要启程远航。"),
        ]
        documents = []
        for position, (document_key, chunk_key, title, text) in enumerate(texts):
            documents.append({
                "document_key": document_key, "title": title,
                "section_path": "姬子•启行/%s" % title, "content_type": "test",
                "position": position, "evidence_eligible": True,
                "chunks": [{"chunk_key": chunk_key, "section_path": "姬子•启行/%s" % title,
                            "text": text, "position": 0,
                            "content_sha256": hashlib.sha256(text.encode()).hexdigest()}],
            })
        self.database.replace_documents(
            source_id, {"title": "姬子•启行", "version": "1", "official_status": "wiki"}, documents
        )
        self.database.replace_entities([
            {"canonical_name": "姬子", "entity_type": "character",
             "aliases": ["姬子·启行", "姬子•启行"]},
            {"canonical_name": "星穹列车", "entity_type": "faction", "aliases": ["列车"]},
        ])
        entities = {item["canonical_name"]: item for item in self.database.entity_catalog()}
        evidence_id = stable_evidence_id(
            "mihoyo_wiki", "7484", "module:11", "e7eb585da54b:0000"
        )
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO relations(subject_id,predicate,object_id,evidence_level,
                     review_status,confidence,reasoning,origin,is_stale)
                   VALUES (?, 'member_of', ?, 'explicit', 'approved', 1, '', 'curated', 0)""",
                (entities["姬子"]["id"], entities["星穹列车"]["id"]),
            )
            relation_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.execute(
                "INSERT INTO relation_evidence(relation_id,evidence_id) VALUES (?,?)",
                (relation_id, evidence_id),
            )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_himeko_is_one_person_with_two_distinct_forms(self) -> None:
        result = replace_identity_catalog(self.database, CATALOG)
        self.assertEqual(result["audit"]["errors"], [])
        self.assertEqual(result["audit"]["people"], 1)
        self.assertEqual(result["audit"]["forms"], 2)
        all_people = identity_catalog(self.database, include_pending=True)
        self.assertEqual([item["canonical_name"] for item in all_people[0]["playable_forms"]],
                         ["姬子", "姬子·启行"])
        visible = identity_catalog(self.database)
        self.assertEqual([item["canonical_name"] for item in visible[0]["playable_forms"]],
                         ["姬子", "姬子·启行"])

    def test_split_preserves_base_id_relation_and_evidence(self) -> None:
        before = {item["canonical_name"]: item for item in self.database.entity_catalog()}
        base_id = before["姬子"]["id"]
        with self.database.connect() as connection:
            relation_before = tuple(connection.execute(
                "SELECT subject_id, object_id FROM relations WHERE review_status='approved'"
            ).fetchone())
        replace_identity_catalog(self.database, CATALOG)
        after = self.database.entity_catalog()
        by_key = {(item["canonical_name"], item["entity_type"]): item for item in after}
        self.assertEqual(by_key[("姬子", "character")]["id"], base_id)
        self.assertNotEqual(by_key[("姬子·启行", "playable_form")]["id"], base_id)
        self.assertNotIn("姬子·启行", [item["text"] for item in by_key[("姬子", "character")]["aliases"]])
        self.assertIn("姬子SP", [item["text"] for item in by_key[("姬子·启行", "playable_form")]["aliases"]])
        with self.database.connect() as connection:
            relation_after = tuple(connection.execute(
                "SELECT subject_id, object_id FROM relations WHERE review_status='approved'"
            ).fetchone())
            evidence_count = int(connection.execute("SELECT COUNT(*) FROM relation_evidence").fetchone()[0])
        self.assertEqual(relation_before, relation_after)
        self.assertEqual(evidence_count, 1)

    def test_player_shorthand_is_never_official(self) -> None:
        replace_identity_catalog(self.database, CATALOG)
        names = identity_catalog(self.database, include_pending=True)[0]["playable_forms"][1]["names"]
        sp = [item for item in names if item["name"].lower() == "姬子sp"]
        self.assertTrue(sp)
        self.assertTrue(all(item["name_type"] == "player_shorthand" for item in sp))
        self.assertTrue(all(not bool(item["is_official"]) for item in sp))

    def test_stale_official_name_rolls_back_without_partial_people(self) -> None:
        payload = load_identity_catalog(CATALOG)
        payload["people"][0]["names"][0]["evidence_id"] = "missing:evidence"
        bad = self.root / "bad.json"
        bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale evidence"):
            replace_identity_catalog(self.database, bad)
        self.assertEqual(audit_identity_catalog(self.database)["people"], 0)

    def test_index_rebuild_keeps_forms_distinct_and_expansion_is_explicit(self) -> None:
        replace_identity_catalog(self.database, CATALOG)
        legacy = self.root / "entities.json"
        legacy.write_text(json.dumps({"entities": [
            {"canonical_name": "姬子", "entity_type": "character", "aliases": []}
        ]}, ensure_ascii=False), encoding="utf-8")
        self.database.rebuild_fts()
        build_retrieval_index(self.database, legacy)
        entities = {(item["canonical_name"], item["entity_type"]): item
                    for item in self.database.entity_catalog()}
        self.assertIn(("姬子", "character"), entities)
        self.assertIn(("姬子·启行", "playable_form"), entities)
        results = hybrid_search(self.database, "姬子·启行", limit=2)
        matched = {item["name"] for item in results[0]["matched_query_entities"]}
        self.assertIn("姬子·启行", matched)

        exact = resolve_identity_name(self.database, "姬子•启行")
        self.assertEqual(exact["playable_form"]["canonical_name"], "姬子·启行")
        self.assertEqual(exact["expanded_forms"], [])
        expanded = resolve_identity_name(self.database, "姬子SP", expand_person=True)
        self.assertFalse(expanded["is_official"])
        self.assertEqual(expanded["name_type"], "player_shorthand")
        self.assertEqual([item["canonical_name"] for item in expanded["expanded_forms"]],
                         ["姬子", "姬子·启行"])


if __name__ == "__main__":
    unittest.main()
