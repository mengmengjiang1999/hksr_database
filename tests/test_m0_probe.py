import json
import tempfile
import unittest
from pathlib import Path

from app.m0_probe import (
    ProbeError,
    html_to_text,
    load_manifest,
    summarize_miyoushe_post_payload,
    summarize_official_account_payload,
    summarize_wiki_payload,
    summarize_wiki_search_payload,
)


class WikiPayloadTests(unittest.TestCase):
    def test_summarizes_rpg_template(self) -> None:
        payload = {
            "retcode": 0,
            "data": {
                "channel_list": [
                    {"slice": [{"channel_id": 18, "name": "角色"}]}
                ],
                "content": {
                    "id": 10,
                    "title": "测试角色",
                    "summary": "角色资料",
                    "version": 2,
                    "ctime": "2026-01-01 00:00:00",
                    "mtime": "2026-01-02 00:00:00",
                    "tmp_type": "RpgTemplateTypeGoldTemp",
                    "contents": [],
                    "rpg_new_tmp_content": {
                        "base": {"userInfo": {"name": "测试角色"}},
                        "modules": [
                            {
                                "id": "story",
                                "name": "角色故事",
                                "switch": False,
                                "components": [
                                    {
                                        "componentId": "story",
                                        "data": json.dumps(
                                            {"title": "故事一", "content": "一段测试文本"},
                                            ensure_ascii=False,
                                        ),
                                    }
                                ],
                            }
                        ],
                    },
                },
            },
        }

        summary = summarize_wiki_payload(payload)

        self.assertEqual(summary["source_id"], "10")
        self.assertEqual(summary["layout"], "rpg_template")
        self.assertEqual(summary["channels"], ["角色"])
        self.assertEqual(summary["modules"][0]["name"], "角色故事")
        self.assertGreater(summary["text"]["text_character_count"], 0)

    def test_summarizes_html_tabs(self) -> None:
        payload = {
            "retcode": 0,
            "data": {
                "channel_list": [],
                "content": {
                    "id": 20,
                    "title": "测试阅读物",
                    "contents": [
                        {"name": "页签1", "text": "<p>第一段</p><p>第二段</p>"}
                    ],
                    "rpg_new_tmp_content": None,
                },
            },
        }

        summary = summarize_wiki_payload(payload)

        self.assertEqual(summary["layout"], "html_tabs")
        self.assertEqual(summary["modules"][0]["components"], ["html"])
        self.assertGreaterEqual(summary["text"]["text_value_count"], 1)


class MiyoushePayloadTests(unittest.TestCase):
    def _payload(self, official: bool = True) -> dict:
        return {
            "retcode": 0,
            "data": {
                "post": {
                    "post": {
                        "post_id": "30",
                        "subject": "官方资料",
                        "content": "<p>正文</p>",
                        "structured_content": json.dumps(
                            [{"insert": "补充文本"}], ensure_ascii=False
                        ),
                        "post_status": {"is_official": official},
                        "view_type": 5,
                    },
                    "user": {
                        "nickname": "官方账号",
                        "certification": {
                            "label": "崩坏：星穹铁道官方账号" if official else ""
                        },
                    },
                    "forum": {"name": "官方"},
                    "vod_list": [{"id": "video-1", "resolutions": []}],
                }
            },
        }

    def test_requires_verified_official_post(self) -> None:
        with self.assertRaises(ProbeError):
            summarize_miyoushe_post_payload(self._payload(official=False))

    def test_detects_video_and_missing_subtitles(self) -> None:
        summary = summarize_miyoushe_post_payload(self._payload())

        self.assertTrue(summary["official"])
        self.assertEqual(summary["video_ids"], ["video-1"])
        self.assertFalse(summary["has_machine_readable_subtitles"])
        self.assertGreater(summary["text"]["text_character_count"], 0)


class DiscoveryPayloadTests(unittest.TestCase):
    def test_search_distinguishes_wiki_and_articles(self) -> None:
        payload = {
            "retcode": 0,
            "data": {
                "total": 2,
                "list": [
                    {
                        "bbs_url": "https://bbs.mihoyo.com/sr/wiki/content/1/detail",
                        "channels": [{"name": "角色"}],
                    },
                    {
                        "bbs_url": "https://www.miyoushe.com/sr/article/2",
                        "channels": [{"name": "游戏视频"}],
                    },
                ],
            },
        }

        summary = summarize_wiki_search_payload(payload)

        self.assertTrue(summary["has_wiki_results"])
        self.assertTrue(summary["has_article_results"])
        self.assertEqual(summary["channel_counts"], {"游戏视频": 1, "角色": 1})

    def test_official_account_list_counts_certified_posts(self) -> None:
        payload = {
            "retcode": 0,
            "data": {
                "is_last": False,
                "next_offset": "cursor",
                "list": [
                    {
                        "user": {"certification": {"label": "游戏官方账号"}},
                        "vod_list": [{}],
                    }
                ],
            },
        }

        summary = summarize_official_account_payload(payload)

        self.assertEqual(summary["official_result_count"], 1)
        self.assertEqual(summary["video_result_count"], 1)
        self.assertTrue(summary["has_next_page"])


class UtilityTests(unittest.TestCase):
    def test_html_to_text(self) -> None:
        self.assertEqual(html_to_text("<p>甲&amp;乙</p><p>丙</p>"), "甲&乙\n丙")

    def test_manifest_requires_unique_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(
                json.dumps({"targets": [{"key": "same"}, {"key": "same"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ProbeError):
                load_manifest(path)


if __name__ == "__main__":
    unittest.main()
