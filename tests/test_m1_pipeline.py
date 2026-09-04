import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.collectors.pipeline import (
    content_fingerprint,
    discover_manifest,
    discover_official_account,
    discover_wiki_catalog,
    discover_wiki_search,
    fetch_sources,
    parse_sources,
)
from app.m0_probe import FetchResult, ProbeError
from app.models.database import Database
from app.parsers.content import extract_speakers, parse_source_payload, split_chunks


def wiki_payload(title: str = "测试角色", story: str = "第一段故事") -> dict:
    return {
        "retcode": 0,
        "data": {
            "channel_list": [],
            "content": {
                "id": 1,
                "title": title,
                "summary": "角色资料",
                "version": 3,
                "ctime": "2026-01-01 00:00:00",
                "mtime": "2026-01-02 00:00:00",
                "tmp_type": "RpgTemplateTypeGoldTemp",
                "contents": [],
                "rpg_new_tmp_content": {
                    "base": {},
                    "modules": [
                        {
                            "id": "story",
                            "name": "角色故事",
                            "switch": False,
                            "components": [
                                {
                                    "componentId": "story",
                                    "data": json.dumps(
                                        {"name": "故事一", "content": story},
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        },
                        {
                            "id": "guide",
                            "name": "配队推荐",
                            "switch": False,
                            "components": [
                                {
                                    "componentId": "guide",
                                    "data": json.dumps(
                                        {"content": "不应进入证据索引"},
                                        ensure_ascii=False,
                                    ),
                                }
                            ],
                        },
                    ],
                },
            },
        },
    }


def official_post_payload() -> dict:
    return {
        "retcode": 0,
        "data": {
            "post": {
                "post": {
                    "post_id": "2",
                    "subject": "官方剧情说明",
                    "content": "<p>一段官方说明文本。</p>",
                    "structured_content": "[]",
                    "created_at": 1,
                    "updated_at": 2,
                    "view_type": 1,
                    "post_status": {"is_official": True},
                },
                "user": {
                    "nickname": "官方账号",
                    "certification": {"label": "游戏官方账号"},
                },
                "forum": {"name": "官方"},
                "vod_list": [],
            }
        },
    }


class ParserTests(unittest.TestCase):
    def test_excludes_editorial_module_from_chunks(self) -> None:
        parsed = parse_source_payload("wiki_content", wiki_payload(), "wiki_character")

        self.assertEqual(len(parsed.documents), 2)
        self.assertTrue(parsed.documents[0]["evidence_eligible"])
        self.assertGreater(len(parsed.documents[0]["chunks"]), 0)
        self.assertFalse(parsed.documents[1]["evidence_eligible"])
        self.assertEqual(parsed.documents[1]["chunks"], [])

    def test_official_post_is_normalized(self) -> None:
        parsed = parse_source_payload(
            "miyoushe_post", official_post_payload(), "official_article"
        )

        self.assertEqual(parsed.metadata["official_status"], "verified")
        self.assertEqual(parsed.documents[0]["content_type"], "official_article")
        self.assertIn("官方说明", parsed.documents[0]["chunks"][0]["text"])

    def test_long_text_is_split_with_bounded_chunks(self) -> None:
        chunks = split_chunks("段落。" * 400, max_characters=120)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))

    def test_internal_template_metadata_is_not_indexed(self) -> None:
        payload = wiki_payload(story="正文\\n第二行")
        component = payload["data"]["content"]["rpg_new_tmp_content"]["modules"][0][
            "components"
        ][0]
        component["data"] = json.dumps(
            {
                "id": "1784125346374_2",
                "source_type": "RpgTextMapSourceTypeItem",
                "content": "正文\\n第二行",
            },
            ensure_ascii=False,
        )

        parsed = parse_source_payload("wiki_content", payload, "wiki_character")
        text = "\n".join(chunk["text"] for chunk in parsed.documents[0]["chunks"])

        self.assertIn("正文\n第二行", text)
        self.assertNotIn("1784125346374", text)
        self.assertNotIn("RpgTextMap", text)

    def test_extracts_only_explicit_dialogue_speakers(self) -> None:
        self.assertEqual(
            extract_speakers("真珠：请坐。\n开拓者：发生了什么？\n没有说话人标签。\n真珠：继续。"),
            ["真珠", "开拓者"],
        )


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "database.sqlite3")
        self.database.initialize()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _manifest(self) -> Path:
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "targets": [
                        {
                            "key": "wiki_1",
                            "source_kind": "wiki_character",
                            "parser": "wiki_content",
                            "expected_title": "测试角色",
                            "page_url": "https://example.test/wiki/1",
                            "api_url": "https://example.test/api?content_id=1",
                        },
                        {
                            "key": "post_2",
                            "source_kind": "official_article",
                            "parser": "miyoushe_post",
                            "expected_title": "官方剧情说明",
                            "page_url": "https://example.test/article/2",
                            "api_url": "https://example.test/post?post_id=2",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def _write_raw(self, source_id: int, payload: dict) -> None:
        path = self.root / ("source-%d.json" % source_id)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        path.write_bytes(raw)
        self.database.record_fetch(source_id, path, "hash-%d" % source_id, len(raw))

    def test_discovery_is_idempotent(self) -> None:
        first = discover_manifest(self.database, self._manifest())
        second = discover_manifest(self.database, self._manifest())

        self.assertEqual(first["unique_sources"], 2)
        self.assertEqual(second["unique_sources"], 2)
        self.assertEqual(self.database.statistics()["counts"]["sources"], 2)

    def test_wiki_search_registers_only_wiki_content(self) -> None:
        payload = {
            "retcode": 0,
            "data": {
                "list": [
                    {
                        "title": "角色甲",
                        "bbs_url": "https://bbs.mihoyo.com/sr/wiki/content/10/detail",
                        "channels": [{"name": "角色"}],
                    },
                    {
                        "title": "玩家文章",
                        "bbs_url": "https://www.miyoushe.com/sr/article/20",
                        "channels": [{"name": "攻略"}],
                    },
                ]
            },
        }
        fetched = FetchResult(payload=payload, sha256="hash", byte_count=1)

        with patch("app.collectors.pipeline.fetch_json", return_value=fetched):
            result = discover_wiki_search(self.database, "角色甲")

        self.assertEqual(result["registered"], 1)
        self.assertEqual(result["skipped_articles"], 1)
        source = self.database.list_sources()[0]
        self.assertEqual(source["source_kind"], "wiki_character")
        self.assertEqual(source["external_id"], "10")

    def test_wiki_catalog_registers_in_game_channels_and_deduplicates_ids(self) -> None:
        payload = {
            "retcode": 0,
            "data": {
                "list": [
                    {
                        "id": 17,
                        "name": "游戏图鉴",
                        "children": [
                            {
                                "id": 18,
                                "name": "角色",
                                "list": [
                                    {"content_id": 10, "title": "角色甲"},
                                    {"content_id": 11, "title": "黄金裔乙"},
                                ],
                            },
                            {
                                "id": 193,
                                "name": "黄金裔",
                                "list": [{"content_id": 11, "title": "黄金裔乙"}],
                            },
                            {
                                "id": 173,
                                "name": "成就攻略",
                                "list": [{"content_id": 12, "title": "成就丙"}],
                            },
                            {
                                "id": 25,
                                "name": "任务",
                                "list": [
                                    {
                                        "content_id": 13,
                                        "title": "支线丁",
                                        "ext": json.dumps(
                                            {
                                                "c_25": {
                                                    "filter": {
                                                        "text": json.dumps(
                                                            ["类型/冒险任务"],
                                                            ensure_ascii=False,
                                                        )
                                                    }
                                                }
                                            },
                                            ensure_ascii=False,
                                        ),
                                    }
                                ],
                            },
                            {
                                "id": 999,
                                "name": "攻略",
                                "list": [{"content_id": 14, "title": "配队攻略"}],
                            },
                        ],
                    }
                ]
            },
        }
        fetched = FetchResult(payload=payload, sha256="hash", byte_count=1)

        with patch("app.collectors.pipeline.fetch_json", return_value=fetched):
            first = discover_wiki_catalog(self.database)
            second = discover_wiki_catalog(self.database)

        self.assertEqual(first["directory_items"], 5)
        self.assertEqual(first["unique_sources"], 4)
        self.assertEqual(first["new_sources"], 4)
        self.assertEqual(first["duplicate_ids"], 1)
        self.assertEqual(first["duplicate_occurrences"], 1)
        self.assertEqual(first["excluded_channels"], ["攻略"])
        self.assertEqual(first["task_types"], {"冒险任务": 1})
        self.assertEqual(first["task_untyped"], 0)
        self.assertEqual(second["new_sources"], 0)
        self.assertEqual(second["existing_sources"], 4)
        sources = {row["external_id"]: row for row in self.database.list_sources()}
        self.assertEqual(set(sources), {"10", "11", "12", "13"})
        self.assertEqual(sources["11"]["source_kind"], "wiki_character")
        self.assertEqual(sources["12"]["source_kind"], "wiki_achievement")
        self.assertEqual(sources["13"]["source_kind"], "wiki_quest")
        self.assertEqual(sources["10"]["official_status"], "verified")
        self.assertIn("content/10/detail", sources["10"]["page_url"])

        with self.database.connect() as connection:
            connection.execute(
                "UPDATE sources SET status = 'parsed' WHERE external_id = '10'"
            )
        with patch("app.collectors.pipeline.fetch_json", return_value=fetched):
            discover_wiki_catalog(self.database)
        self.assertEqual(
            {row["external_id"]: row for row in self.database.list_sources()}["10"]["status"],
            "parsed",
        )

    def test_wiki_catalog_rejects_malformed_directory(self) -> None:
        fetched = FetchResult(
            payload={"retcode": 0, "data": {"list": [{"id": 17}]}},
            sha256="hash",
            byte_count=1,
        )

        with patch("app.collectors.pipeline.fetch_json", return_value=fetched):
            with self.assertRaisesRegex(ProbeError, "root is missing or malformed"):
                discover_wiki_catalog(self.database)

    def test_official_account_discovery_skips_unverified_posts(self) -> None:
        verified = {
            "post": {
                "post_id": "30",
                "subject": "官方视频",
                "post_status": {"is_official": True},
            },
            "user": {"certification": {"label": "游戏官方账号"}},
            "vod_list": [{"id": "video"}],
        }
        unverified = {
            "post": {
                "post_id": "31",
                "subject": "普通文章",
                "post_status": {"is_official": False},
            },
            "user": {"certification": {"label": ""}},
            "vod_list": [],
        }
        payload = {
            "retcode": 0,
            "data": {"list": [verified, unverified], "is_last": True},
        }
        fetched = FetchResult(payload=payload, sha256="hash", byte_count=1)

        with patch("app.collectors.pipeline.fetch_json", return_value=fetched):
            result = discover_official_account(self.database, "official-uid")

        self.assertEqual(result["registered"], 1)
        self.assertEqual(result["skipped_unverified"], 1)
        source = self.database.list_sources()[0]
        self.assertEqual(source["source_kind"], "official_video")

    def test_fetch_rechecks_parsed_sources_without_forcing_reparse(self) -> None:
        discover_manifest(self.database, self._manifest())
        source = self.database.list_sources(limit=1)[0]
        canonical = json.dumps(
            wiki_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        path = self.root / "existing.json"
        path.write_bytes(canonical)
        canonical_sha256 = hashlib.sha256(canonical).hexdigest()
        semantic_sha256 = content_fingerprint("wiki_content", wiki_payload())
        self.database.record_fetch(
            int(source["id"]),
            path,
            canonical_sha256,
            len(canonical),
            content_sha256=semantic_sha256,
        )
        parse_sources(self.database)
        fetched = FetchResult(
            payload=wiki_payload(),
            sha256="unused-raw-hash",
            byte_count=len(canonical),
        )

        with patch("app.collectors.pipeline.fetch_json", return_value=fetched):
            result = fetch_sources(self.database, self.root / "raw", limit=1)

        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(self.database.get_source(int(source["id"]))["status"], "parsed")

    def test_post_fingerprint_ignores_volatile_stats_and_signed_urls(self) -> None:
        first = official_post_payload()
        first["data"]["post"]["stat"] = {"view_num": 1}
        first["data"]["post"]["vod_list"] = [
            {
                "id": "video-1",
                "duration": 100,
                "transcoding_status": 2,
                "review_status": 1,
                "resolutions": [{"url": "https://video.test/a?auth_key=first"}],
            }
        ]
        first["data"]["post"]["post"]["structured_content"] = json.dumps(
            [{"insert": {"vod": {"url": "https://video.test/a?auth_key=first"}}}]
        )
        second = json.loads(json.dumps(first))
        second["data"]["post"]["stat"]["view_num"] = 999
        second["data"]["post"]["vod_list"][0]["resolutions"][0][
            "url"
        ] = "https://video.test/a?auth_key=second"
        second["data"]["post"]["post"]["structured_content"] = json.dumps(
            [{"insert": {"vod": {"url": "https://video.test/a?auth_key=second"}}}]
        )

        self.assertEqual(
            content_fingerprint("miyoushe_post", first),
            content_fingerprint("miyoushe_post", second),
        )

    def test_parse_replace_and_index_are_idempotent(self) -> None:
        discover_manifest(self.database, self._manifest())
        sources = self.database.list_sources()
        self._write_raw(int(sources[0]["id"]), wiki_payload())
        self._write_raw(int(sources[1]["id"]), official_post_payload())

        first = parse_sources(self.database)
        first_index_count = self.database.rebuild_fts()
        first_stats = self.database.statistics()["counts"]
        second = parse_sources(self.database, force=True)
        second_index_count = self.database.rebuild_fts()
        second_stats = self.database.statistics()["counts"]

        self.assertEqual(first["parsed"], 2)
        self.assertEqual(second["parsed"], 2)
        self.assertEqual(first_stats["documents"], second_stats["documents"])
        self.assertEqual(first_stats["chunks"], second_stats["chunks"])
        self.assertEqual(first_index_count, second_index_count)

    def test_changed_raw_payload_replaces_existing_chunks(self) -> None:
        discover_manifest(self.database, self._manifest())
        source = self.database.list_sources(limit=1)[0]
        source_id = int(source["id"])
        self._write_raw(source_id, wiki_payload(story="旧文本"))
        parse_sources(self.database)
        self.database.rebuild_fts()
        self.assertEqual(len(self.database.search("旧文本")), 1)

        path = Path(self.database.get_source(source_id)["raw_path"])
        path.write_text(
            json.dumps(wiki_payload(story="全新文本"), ensure_ascii=False),
            encoding="utf-8",
        )
        self.database.record_fetch(source_id, path, "changed-hash", path.stat().st_size)
        parse_sources(self.database)

        self.assertEqual(self.database.search("旧文本"), [])
        self.assertEqual(len(self.database.search("全新文本")), 1)

    def test_unloadable_fts_schema_can_be_rebuilt_without_losing_content(self) -> None:
        with self.database.connect() as connection:
            connection.execute("PRAGMA writable_schema = ON")
            writable_schema = bool(connection.execute("PRAGMA writable_schema").fetchone()[0])
            connection.execute("PRAGMA writable_schema = OFF")
        if not writable_schema:
            self.skipTest("this SQLite build disables writable_schema compatibility repair")

        discover_manifest(self.database, self._manifest())
        source = self.database.list_sources(limit=1)[0]
        self._write_raw(int(source["id"]), wiki_payload(story="兼容索引文本"))
        parse_sources(self.database)
        self.database.rebuild_fts()
        counts_before = self.database.statistics()["counts"]

        with self.database.connect() as connection:
            self.database._remove_unloadable_fts_schema(connection)
        with self.database.connect() as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name LIKE 'chunks_fts%' LIMIT 1"
            ).fetchone())
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

        self.database.rebuild_fts()
        self.assertEqual(self.database.statistics()["counts"], counts_before)
        self.assertEqual(len(self.database.search("兼容索引文本")), 1)

    def test_search_returns_source_traceability(self) -> None:
        discover_manifest(self.database, self._manifest())
        source = self.database.list_sources(limit=1)[0]
        self._write_raw(int(source["id"]), wiki_payload(story="可追溯的官方文本"))
        parse_sources(self.database)
        self.database.rebuild_fts()

        result = self.database.search("可追溯", limit=1)[0]

        self.assertEqual(result["source_kind"], "wiki_character")
        self.assertEqual(result["page_url"], "https://example.test/wiki/1")
        self.assertIn("角色故事", result["section_path"])

    def test_search_treats_player_punctuation_as_literal_text(self) -> None:
        self.database.rebuild_fts()

        self.assertEqual(self.database.search('不存在 "引号"'), [])
        self.assertEqual(self.database.search("不存在%通配符"), [])
        self.assertEqual(self.database.search("不存在_通配符"), [])
        self.assertEqual(self.database.search("   "), [])


if __name__ == "__main__":
    unittest.main()
