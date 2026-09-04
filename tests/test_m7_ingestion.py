import json
import os
import tempfile
import unittest
from pathlib import Path

from app.cli import build_parser
from app.collectors.m7 import (
    CLASSIFIER_VERSION,
    CollectionPolicy,
    M7Collector,
    OssRamRoleUploader,
    RemoteFailure,
    RemoteResponse,
    RequestController,
    build_collection_report,
    classify_payload,
    exclusive_lock,
    review_disposition,
    sanitize_report,
)
from app.cloud.validation import validate_real_batch_id
from app.models.database import Database


def listing(post_id, *, last, next_offset="", verified=True, video=False):
    return {
        "retcode": 0,
        "data": {
            "list": [{
                "post": {
                    "post_id": str(post_id), "subject": "剧情说明 " + str(post_id),
                    "post_status": {"is_official": verified},
                },
                "user": {"certification": {"label": "游戏官方账号" if verified else ""}},
                "vod_list": [{"id": "v"}] if video else [],
            }],
            "is_last": last,
            "next_offset": next_offset,
        },
    }


def body(post_id="1", *, content="官方剧情正文", title="剧情说明", verified=True, video=False):
    return {
        "retcode": 0,
        "data": {"post": {
            "post": {
                "post_id": str(post_id), "subject": title, "content": content,
                "created_at": 1, "updated_at": 2, "view_type": 1,
                "post_status": {"is_official": verified}, "is_deleted": False,
            },
            "user": {"certification": {"label": "游戏官方账号" if verified else ""}},
            "forum": {"name": "官方"},
            "vod_list": [{"id": "v"}] if video else [],
        }},
    }


def wiki_body(content_id="100", title="角色甲"):
    return {
        "retcode": 0,
        "data": {
            "channel_list": [{"id": 18, "name": "角色"}],
            "content": {
                "id": int(content_id),
                "title": title,
                "summary": "游戏内资料",
                "version": 1,
                "contents": [],
            },
        },
    }


class MemoryUploader:
    def __init__(self, fail=False):
        self.fail = fail
        self.objects = {}

    def upload(self, object_key, payload):
        if self.fail:
            raise RuntimeError("upload failed")
        self.objects[object_key] = payload
        return {"etag": "safe-etag", "version_id": "safe-version"}


class M7TestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database = Database(self.root / "hksr.sqlite3")
        self.database.initialize()

    def tearDown(self):
        self.directory.cleanup()

    def collector(self, responses, **policy):
        queue = list(responses)

        def fetcher(url, headers, timeout):
            value = queue.pop(0)
            if isinstance(value, BaseException):
                raise value
            return RemoteResponse(value)

        return M7Collector(
            self.database,
            policy=CollectionPolicy(minimum_delay=15, maximum_delay=30, **policy),
            fetcher=fetcher,
            sleep=lambda seconds: None,
            jitter=lambda low, high: 22.5,
            budget_date=lambda: "2026-09-03",
        )

    def test_migrations_are_versioned_and_idempotent(self):
        self.database.initialize()
        with self.database.connect() as connection:
            versions = connection.execute(
                "SELECT version FROM hksr_sqlite_migrations ORDER BY version"
            ).fetchall()
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertEqual([row[0] for row in versions], [1, 2])
        self.assertTrue({
            "collection_runs", "account_checkpoints", "daily_request_budgets",
            "source_dispositions", "fetch_attempts", "raw_object_manifests",
            "wiki_refresh_checkpoints",
        }.issubset(tables))

    def test_cursor_resumes_across_runs_and_terminal_is_upstream_driven(self):
        first = self.collector([listing(1, last=False, next_offset="cursor-2")], discovery_pages=1)
        report1 = first.discover("official")
        seen_urls = []

        def resumed(url, headers, timeout):
            seen_urls.append(url)
            return RemoteResponse(listing(2, last=True))

        second = M7Collector(
            self.database, policy=CollectionPolicy(discovery_pages=1), fetcher=resumed,
            sleep=lambda seconds: None, budget_date=lambda: "2026-09-03",
        )
        report2 = second.discover("official")
        self.assertEqual(report1["checkpoint"], "bounded_pause")
        self.assertIn("offset=cursor-2", seen_urls[0])
        self.assertTrue(report2["terminal"])
        self.assertEqual(self.database.collection_checkpoint("official")["observed_count"], 2)

    def test_duplicate_ids_and_new_incremental_posts_are_stable(self):
        payload = listing(1, last=True)
        payload["data"]["list"].append(payload["data"]["list"][0])
        first = self.collector([payload], discovery_pages=1).discover("official")
        second = self.collector([listing(2, last=True)], discovery_pages=1).discover("official")
        self.assertEqual(first["registered"], 1)
        self.assertEqual(first["duplicates"], 1)
        self.assertEqual(second["registered"], 1)
        self.assertEqual(len(self.database.list_sources()), 2)

    def test_malformed_response_does_not_advance_checkpoint(self):
        collector = self.collector([{"retcode": 0, "data": {"list": {}, "is_last": True}}])
        with self.assertRaisesRegex(ValueError, "list is malformed"):
            collector.discover("official")
        self.assertEqual(self.database.collection_checkpoint("official")["observed_count"], 0)

    def test_default_caps_are_exposed_without_activation_or_host_flags(self):
        parser = build_parser()
        discover = parser.parse_args(["m7-discover", "--uid", "1"])
        fetch = parser.parse_args(["m7-fetch", "--oss-bucket", "b", "--oss-endpoint", "e"])
        wiki_fetch = parser.parse_args([
            "m7-wiki-fetch", "--oss-bucket", "b", "--oss-endpoint", "e"
        ])
        parse = parser.parse_args(["parse", "--provider", "mihoyo_wiki"])
        wiki_refresh = parser.parse_args([
            "m7-wiki-refresh", "--oss-bucket", "b", "--oss-endpoint", "e"
        ])
        self.assertEqual(discover.pages, 2)
        self.assertEqual(fetch.limit, 10)
        self.assertEqual(wiki_fetch.limit, 10)
        self.assertEqual(parse.provider, "mihoyo_wiki")
        self.assertEqual(wiki_refresh.limit, 10)
        self.assertEqual(discover.daily_budget, 60)
        self.assertEqual(fetch.daily_budget, 60)
        self.assertEqual(wiki_fetch.daily_budget, 60)
        self.assertEqual(wiki_refresh.daily_budget, 60)
        approved = parser.parse_args([
            "m7-fetch", "--oss-bucket", "b", "--oss-endpoint", "e",
            "--daily-budget", "300",
        ])
        self.assertEqual(approved.daily_budget, 300)
        unlimited = parser.parse_args([
            "m7-fetch", "--oss-bucket", "b", "--oss-endpoint", "e",
            "--daily-budget", "0",
        ])
        self.assertEqual(unlimited.daily_budget, 0)
        help_text = parser.format_help().lower()
        self.assertNotIn("activation", help_text)
        self.assertNotIn("host-marker", help_text)

    def test_pacing_daily_budget_retry_and_circuit_breaker(self):
        run_id = "m7-test-run"
        self.database.start_collection_run(run_id, "test")
        sleeps = []
        controller = RequestController(
            self.database, run_id,
            CollectionPolicy(minimum_delay=15, maximum_delay=30, daily_budget=2,
                             attempts=3, failure_threshold=3),
            sleep=sleeps.append, jitter=lambda low, high: 20,
            budget_date=lambda: "2026-09-03",
        )
        calls = [RemoteFailure("rate", status=429, retry_after=17), RemoteResponse({})]

        def retrying(url, headers, timeout):
            value = calls.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        controller.request(retrying, "https://example.test", {}, 1)
        self.assertIn(17, sleeps)
        self.assertIn(20, sleeps)
        with self.assertRaisesRegex(RuntimeError, "daily request budget"):
            controller.request(lambda *args: RemoteResponse({}), "x", {}, 1)

        unlimited_run = "m7-unlimited"
        self.database.start_collection_run(unlimited_run, "test")
        unlimited = RequestController(
            self.database, unlimited_run,
            CollectionPolicy(minimum_delay=0, maximum_delay=0, daily_budget=0),
            sleep=lambda seconds: None, budget_date=lambda: "2026-09-05",
        )
        for _ in range(4):
            unlimited.request(lambda *args: RemoteResponse({}), "x", {}, 1)
        self.assertEqual(unlimited.request_count, 4)
        with self.database.connect() as connection:
            count = connection.execute(
                "SELECT request_count FROM daily_request_budgets WHERE budget_date = ?",
                ("2026-09-05",),
            ).fetchone()[0]
        self.assertEqual(count, 4)

        other = self.database
        other.start_collection_run("m7-circuit", "test")
        breaker = RequestController(
            other, "m7-circuit", CollectionPolicy(minimum_delay=0, maximum_delay=0),
            sleep=lambda seconds: None, budget_date=lambda: "2026-09-04",
        )
        with self.assertRaisesRegex(RuntimeError, "circuit breaker"):
            breaker.request(
                lambda *args: (_ for _ in ()).throw(RemoteFailure("down")), "x", {}, 1
            )
        self.assertEqual(breaker.request_count, 3)

    def test_fetch_requires_upload_before_fetched_state_and_uses_hash_key(self):
        self.collector([listing(1, last=True)], discovery_pages=1).discover("official")
        uploader = MemoryUploader()
        report = self.collector([body()], fetch_posts=10).fetch(self.root / "spool", uploader)
        source = self.database.list_sources()[0]
        self.assertEqual(source["status"], "fetched")
        self.assertEqual(report["persisted"], 1)
        self.assertEqual(len(uploader.objects), 1)
        key = next(iter(uploader.objects))
        self.assertRegex(key, r"^m7/raw/miyoushe/1/[0-9a-f]{64}\.json$")
        self.assertEqual(os.stat(source["raw_path"]).st_mode & 0o777, 0o600)

        self.collector([listing(2, last=True)], discovery_pages=1).discover("other")
        failed = self.collector([body("2")]).fetch(self.root / "spool", MemoryUploader(fail=True))
        failed_source = [row for row in self.database.list_sources() if row["external_id"] == "2"][0]
        self.assertEqual(failed["failed"], 1)
        self.assertEqual(failed_source["status"], "error")

    def test_nonzero_remote_retcode_is_skipped_without_upload_or_retry(self):
        self.collector([listing(7, last=True)], discovery_pages=1).discover("official")
        uploader = MemoryUploader()
        report = self.collector([{"retcode": 1008, "message": "unavailable"}]).fetch(
            self.root / "spool", uploader
        )

        source = self.database.list_sources()[0]
        disposition = self.database.source_disposition(int(source["id"]))
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["persisted"], 0)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["remote_retcodes"], {"1008": 1})
        self.assertEqual(source["status"], "skipped")
        self.assertEqual(disposition["disposition"], "excluded_unavailable")
        self.assertEqual(uploader.objects, {})

        repeated = self.collector([]).fetch(self.root / "spool", uploader)
        self.assertEqual(repeated["attempted"], 0)

    def test_wiki_fetch_is_paced_persisted_and_marked_eligible(self):
        source_id = self.database.upsert_source(
            {
                "provider": "mihoyo_wiki",
                "external_id": "100",
                "source_kind": "wiki_character",
                "parser": "wiki_content",
                "page_url": "https://bbs.mihoyo.com/sr/wiki/content/100/detail",
                "api_url": "https://example.test/wiki/100",
                "headers": {},
                "expected_title": "角色甲",
                "official_status": "verified",
            }
        )
        uploader = MemoryUploader()
        report = self.collector([wiki_body()], fetch_posts=10).fetch_wiki(
            self.root / "spool", uploader
        )

        source = self.database.get_source(source_id)
        disposition = self.database.source_disposition(source_id)
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["persisted"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(source["status"], "fetched")
        self.assertEqual(disposition["disposition"], "eligible_evidence")
        key = next(iter(uploader.objects))
        self.assertRegex(key, r"^m7/raw/mihoyo_wiki/100/[0-9a-f]{64}\.json$")
        self.assertEqual(os.stat(source["raw_path"]).st_mode & 0o777, 0o600)

    def test_wiki_nonzero_retcode_is_permanently_skipped(self):
        source_id = self.database.upsert_source(
            {
                "provider": "mihoyo_wiki",
                "external_id": "101",
                "source_kind": "wiki_readable",
                "parser": "wiki_content",
                "page_url": "https://bbs.mihoyo.com/sr/wiki/content/101/detail",
                "api_url": "https://example.test/wiki/101",
                "headers": {},
                "expected_title": "阅读物",
                "official_status": "verified",
            }
        )
        uploader = MemoryUploader()
        report = self.collector([{"retcode": -1}], fetch_posts=10).fetch_wiki(
            self.root / "spool", uploader
        )

        self.assertEqual(report["skipped"], 1)
        self.assertEqual(self.database.get_source(source_id)["status"], "skipped")
        self.assertEqual(
            self.database.source_disposition(source_id)["disposition"],
            "excluded_unavailable",
        )
        self.assertEqual(uploader.objects, {})

    def test_wiki_refresh_resumes_and_only_persists_changed_content(self):
        source_ids = []
        for external_id in ("100", "101"):
            source_ids.append(self.database.upsert_source({
                "provider": "mihoyo_wiki", "external_id": external_id,
                "source_kind": "wiki_character", "parser": "wiki_content",
                "page_url": "https://example.test/wiki/" + external_id,
                "api_url": "https://example.test/api/" + external_id,
                "headers": {}, "expected_title": "角色" + external_id,
                "official_status": "verified",
            }))
        self.collector(
            [wiki_body("100", "角色甲"), wiki_body("101", "角色乙")],
            fetch_posts=10,
        ).fetch_wiki(self.root / "spool", MemoryUploader())
        with self.database.connect() as connection:
            connection.execute("UPDATE sources SET status = 'parsed'")

        unchanged_uploader = MemoryUploader()
        first = self.collector(
            [wiki_body("100", "角色甲")], fetch_posts=1
        ).refresh_wiki(
            self.root / "spool", unchanged_uploader, start_new_cycle=True
        )
        self.assertEqual(first["unchanged"], 1)
        self.assertEqual(first["changed"], 0)
        self.assertFalse(first["terminal"])
        self.assertEqual(unchanged_uploader.objects, {})
        self.assertEqual(self.database.get_source(source_ids[0])["status"], "parsed")

        changed_uploader = MemoryUploader()
        second = self.collector(
            [wiki_body("101", "角色乙·新版")], fetch_posts=1
        ).refresh_wiki(self.root / "spool", changed_uploader)
        checkpoint = self.database.wiki_refresh_checkpoint()
        self.assertEqual(second["changed"], 1)
        self.assertTrue(second["terminal"])
        self.assertTrue(checkpoint["terminal"])
        self.assertEqual(checkpoint["checked_count"], 2)
        self.assertEqual(checkpoint["changed_count"], 1)
        self.assertEqual(self.database.get_source(source_ids[1])["status"], "fetched")
        self.assertEqual(len(changed_uploader.objects), 1)

    def test_wiki_refresh_failure_keeps_last_known_good_evidence(self):
        source_id = self.database.upsert_source({
            "provider": "mihoyo_wiki", "external_id": "100",
            "source_kind": "wiki_character", "parser": "wiki_content",
            "page_url": "https://example.test/wiki/100",
            "api_url": "https://example.test/api/100", "headers": {},
            "expected_title": "角色甲", "official_status": "verified",
        })
        self.collector([wiki_body()], fetch_posts=1).fetch_wiki(
            self.root / "spool", MemoryUploader()
        )
        with self.database.connect() as connection:
            connection.execute("UPDATE sources SET status = 'parsed' WHERE id = ?", (source_id,))
        with self.assertRaisesRegex(RuntimeError, "circuit breaker"):
            self.collector(
                [RemoteFailure("temporary")] * 3, fetch_posts=1
            ).refresh_wiki(
                self.root / "spool", MemoryUploader(), start_new_cycle=True
            )
        source = self.database.get_source(source_id)
        self.assertEqual(source["status"], "parsed")
        self.assertEqual(source["last_error"], "RuntimeError")
        self.assertEqual(self.database.wiki_refresh_checkpoint()["checked_count"], 0)

    def test_oss_uploader_refuses_static_access_keys(self):
        previous = os.environ.get("OSS_ACCESS_KEY_ID")
        os.environ["OSS_ACCESS_KEY_ID"] = "must-not-be-used"
        try:
            with self.assertRaisesRegex(ValueError, "static AccessKey"):
                OssRamRoleUploader("bucket", "endpoint")
        finally:
            if previous is None:
                os.environ.pop("OSS_ACCESS_KEY_ID", None)
            else:
                os.environ["OSS_ACCESS_KEY_ID"] = previous

    def test_classification_and_review_never_promote_unverified(self):
        self.assertEqual(classify_payload(body(), "official_article")[0], "eligible_evidence")
        self.assertEqual(
            classify_payload(body(content="", video=True), "official_video")[0],
            "missing_official_text",
        )
        self.assertEqual(
            classify_payload(body(title="维护公告"), "official_article")[0],
            "excluded_operational",
        )
        self.collector([listing(9, last=True, verified=False)], discovery_pages=1).discover("official")
        with self.assertRaisesRegex(ValueError, "never become eligible"):
            review_disposition(self.database, "9", "eligible_evidence", "unsafe")

    def test_review_reclassifies_without_network_or_refetch(self):
        self.collector([listing(1, last=True)], discovery_pages=1).discover("official")
        source = self.database.list_sources()[0]
        before = source["fetched_at"]
        reviewed = review_disposition(
            self.database, "1", "excluded_operational", "human_reviewed_category"
        )
        self.assertTrue(reviewed["reviewed"])
        self.assertEqual(self.database.get_source(int(source["id"]))["fetched_at"], before)

    def test_lock_interruption_redaction_and_report_schema(self):
        lock = self.root / "collector.lock"
        with exclusive_lock(lock):
            with self.assertRaisesRegex(RuntimeError, "holds the lock"):
                with exclusive_lock(lock):
                    pass
        sanitized = sanitize_report({
            "cookie": "secret", "nested": {"endpoint": "private"},
            "note": "postgresql://user:pass@host/db", "count": 2,
        })
        self.assertEqual(sanitized["cookie"], "[redacted]")
        self.assertEqual(sanitized["nested"]["endpoint"], "[redacted]")
        self.assertEqual(sanitized["note"], "[redacted]")
        report = build_collection_report(self.database)
        self.assertEqual(report["schema_version"], 1)
        self.assertIn("dispositions", report)
        self.assertIn("unverified_evidence", report)
        self.assertNotIn("account_uid", json.dumps(report))
        self.assertNotIn("object_key", json.dumps(report))

    def test_m7_real_batch_ids_are_unique_and_guarded(self):
        self.assertEqual(validate_real_batch_id("m7-real-pilot-20260903"), "m7-real-pilot-20260903")
        with self.assertRaises(ValueError):
            validate_real_batch_id("m7-test")


if __name__ == "__main__":
    unittest.main()
