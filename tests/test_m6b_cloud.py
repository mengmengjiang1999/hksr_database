import json
import tempfile
import unittest
from pathlib import Path

from app.cli import build_parser
from app.cloud.validation import (
    CloudDatabaseConfig,
    _TransactionBatcher,
    _m6a_estimate,
    build_acceptance_report,
    deterministic_vector,
    fixture_rows,
    migration_files,
    migration_plan,
    percentile,
    read_official_sqlite_snapshot,
    recall_at_k,
    sanitize_output,
    stable_postgres_evidence_id,
    validate_real_batch_id,
    validate_run_id,
    vector_literal,
    write_json_report,
    render_acceptance_markdown,
)
from app.models.database import Database, stable_evidence_id


class CloudConfigurationTests(unittest.TestCase):
    def test_dsn_is_environment_only_and_repr_is_redacted(self) -> None:
        with self.assertRaises(ValueError):
            CloudDatabaseConfig.from_environment({})
        config = CloudDatabaseConfig.from_environment({
            "HKSR_POSTGRES_DSN": "postgresql://alice:secret@db.example.test/hksr"
        })
        rendered = repr(config)
        self.assertNotIn("alice", rendered)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("db.example", rendered)
        self.assertEqual(config.redacted, "postgresql://***:***@***/***")

        with self.assertRaisesRegex(ValueError, "invalid percent escape"):
            CloudDatabaseConfig.from_environment({
                "HKSR_POSTGRES_DSN": "postgresql://app:bad%value@db.internal/hksr"
            })

    def test_sanitizer_removes_sensitive_fields_and_dsn_values(self) -> None:
        safe = sanitize_output({
            "server_version": "18.0",
            "instance_id": "pgm-secret",
            "nested": {"endpoint": "db.example", "note": "postgresql://a:b@c/d"},
        })
        self.assertEqual(safe["server_version"], "18.0")
        self.assertEqual(safe["instance_id"], "[redacted]")
        self.assertEqual(safe["nested"]["endpoint"], "[redacted]")
        self.assertEqual(safe["nested"]["note"], "[redacted]")

    def test_sanitizer_preserves_non_secret_superuser_boolean(self) -> None:
        safe = sanitize_output({"superuser": False, "username": "alice"})
        self.assertIs(safe["superuser"], False)
        self.assertEqual(safe["username"], "[redacted]")

    def test_report_writer_never_persists_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_json_report(path, {"password": "secret", "ok": True})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"ok": True, "password": "[redacted]"})

    def test_acceptance_report_requires_cloud_application_and_cleanup_gates(self) -> None:
        digest = "a" * 64
        procurement = {
            "database": {
                "major_version": 18,
                "maximum_rcu": 4,
                "automatic_pause": True,
            },
            "public_list_price": {"rcu_cny_per_hour": 0.333},
        }
        extensions = {"functional_probes": {
            "vector": {"status": "passed"},
            "pg_bigm": {"status": "passed"},
            "pg_jieba": {"status": "passed_with_relevance_caveat"},
            "zhparser": {"status": "passed"},
        }}
        operator = {
            "application_runner": {
                "deployed": True,
                "health_check_passed": True,
                "private_database_read_passed": True,
                "automatic_restart_verified": True,
                "service_manager": "systemd",
            },
            "rds": {
                "private_connectivity_verified": True,
                "runtime_role_read_only_verified": True,
                "prohibited_operations_failed": True,
                "maximum_rcu": 4,
                "automatic_pause_restored": True,
                "backup_restore": {
                    "completed": True,
                    "started_at": "2026-09-03T01:00:00+08:00",
                    "completed_at": "2026-09-03T01:05:00+08:00",
                    "test_artifact_sha256": digest,
                    "restored_artifact_sha256": digest,
                },
            },
            "oss": {
                "private_access": True,
                "versioning_enabled": True,
                "historical_restore": {
                    "completed": True,
                    "started_at": "2026-09-03T02:00:00+08:00",
                    "completed_at": "2026-09-03T02:00:04+08:00",
                    "test_object_sha256": digest,
                    "restored_object_sha256": digest,
                },
            },
            "temporary_resources_remaining": [],
        }
        imports = [
            {
                "source_fingerprint": digest,
                "counts_match": True,
                "stable_evidence_ids_unique": True,
                "synthetic_rows_imported": 0,
                "repeated_batch": False,
            },
            {
                "source_fingerprint": digest,
                "counts_match": True,
                "stable_evidence_ids_unique": True,
                "synthetic_rows_imported": 0,
                "repeated_batch": True,
            },
        ]
        pending = build_acceptance_report(
            procurement=procurement,
            extension_observation=extensions,
            operator_evidence=operator,
            import_reports=imports,
        )
        self.assertFalse(pending["ready_to_archive"])
        self.assertFalse(pending["acceptance_gates"]["no_synthetic_rows_remaining"])

        complete = build_acceptance_report(
            procurement=procurement,
            extension_observation=extensions,
            operator_evidence=operator,
            import_reports=imports,
            database_audit={"synthetic_rows": 0},
        )
        self.assertTrue(complete["ready_to_archive"])
        self.assertTrue(complete["acceptance_gates"]["cloud_application_smoke_test"])
        self.assertNotIn("oss_historical_version_restore", complete["acceptance_gates"])
        self.assertNotIn("rds_backup_restore", complete["acceptance_gates"])
        self.assertEqual(complete["restore_durations_seconds"], {"oss": 4.0, "rds": 300.0})
        markdown = render_acceptance_markdown(complete)
        self.assertIn("可以归档", markdown)
        self.assertIn("不属于本阶段门槛", markdown)
        self.assertNotIn(digest, markdown)


class MigrationAndFixtureTests(unittest.TestCase):
    def test_transaction_batcher_bounds_commits_and_flushes_remainder(self) -> None:
        class Connection:
            def __init__(self) -> None:
                self.commits = 0

            def commit(self) -> None:
                self.commits += 1

        connection = Connection()
        batcher = _TransactionBatcher(connection, 2)
        batcher.record_write()
        self.assertEqual(connection.commits, 0)
        batcher.record_write()
        self.assertEqual(connection.commits, 1)
        batcher.record_write()
        batcher.flush()
        batcher.flush()
        self.assertEqual(connection.commits, 2)
        self.assertEqual(batcher.commits, 2)

        replacement = Connection()
        batcher.record_write()
        with self.assertRaisesRegex(RuntimeError, "flush pending writes"):
            batcher.replace_connection(replacement)
        batcher.flush()
        batcher.replace_connection(replacement)
        batcher.record_write()
        batcher.flush()
        self.assertEqual(replacement.commits, 1)
        self.assertEqual(batcher.connection_rotations, 1)

        with self.assertRaisesRegex(ValueError, "positive integer"):
            _TransactionBatcher(connection, 0)

    def test_migrations_are_versioned_idempotent_and_scoped(self) -> None:
        files = migration_files()
        self.assertEqual(
            [path.name for path in files],
            ["001_core.sql", "002_validation.sql", "003_real_evidence_import.sql",
             "004_m7_import_batches.sql", "005_m10_read_runtime.sql"],
        )
        self.assertEqual(
            [path.name for path in migration_plan(["001_core.sql"])],
            ["002_validation.sql", "003_real_evidence_import.sql",
             "004_m7_import_batches.sql", "005_m10_read_runtime.sql"],
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in files).lower()
        self.assertIn("create table if not exists", combined)
        self.assertIn("hksr_validation", combined)
        self.assertIn("synthetic = true", combined)
        self.assertIn("synthetic = false", combined)
        self.assertNotIn("drop schema", combined)
        self.assertNotIn("drop database", combined)

    def test_fixture_is_deterministic_and_validation_only(self) -> None:
        rows = list(fixture_rows("m6b-test-run", 2, 4))
        self.assertEqual(rows, list(fixture_rows("m6b-test-run", 2, 4)))
        self.assertEqual(rows[0][0:3], ("m6b-test-run", 0, "synthetic:m6b-test-run:00000000"))
        self.assertIn("不得作为官方证据", rows[0][3])
        self.assertEqual(vector_literal(deterministic_vector(0, 4)), "[0.8,0.6,0,0]")
        self.assertAlmostEqual(sum(value * value for value in deterministic_vector(5, 8)), 1.0)

    def test_run_ids_and_stable_evidence_ids_are_guarded(self) -> None:
        self.assertEqual(validate_run_id("m6b-scale-100k"), "m6b-scale-100k")
        for invalid in ("production", "m6b-../all", "m6b-x", "M6B-test"):
            with self.assertRaises(ValueError):
                validate_run_id(invalid)
        first = stable_postgres_evidence_id("wiki", "1", "body", "a")
        second = stable_postgres_evidence_id("wiki", "1", "body", "a")
        changed = stable_postgres_evidence_id("wiki", "1", "body", "b")
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertEqual(
            validate_real_batch_id("m6b-real-initial-20260903"),
            "m6b-real-initial-20260903",
        )
        self.assertEqual(
            validate_real_batch_id("m7-real-wiki-20260904"),
            "m7-real-wiki-20260904",
        )
        for invalid in ("m6b-test", "m6b-real-x", "M6B-real-import", "m6b-real-../all"):
            with self.assertRaises(ValueError):
                validate_real_batch_id(invalid)

    def test_official_sqlite_snapshot_is_stable_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.sqlite3"
            database = Database(path)
            database.initialize()
            with database.connect() as connection:
                connection.execute(
                    """INSERT INTO sources
                       (id, provider, external_id, source_kind, parser, page_url, api_url,
                        title, official_status, status, discovered_at, fetched_at, parsed_at)
                       VALUES (1,'miyoushe','42','post','json','https://example.test/p/42',
                               'https://example.test/api/42','官方标题','verified','parsed',
                               '2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00',
                               '2026-01-01T00:00:02+00:00')"""
                )
                connection.execute(
                    """INSERT INTO documents
                       (id,source_id,document_key,title,section_path,content_type,position,
                        evidence_eligible,metadata_json)
                       VALUES (1,1,'body','正文','正文','text',0,1,'{}')"""
                )
                connection.execute(
                    """INSERT INTO chunks
                       (id,document_id,chunk_key,section_path,speaker,text,position,
                        content_sha256,metadata_json)
                       VALUES (1,1,'abc:0000','正文','','证据文本',0,'sha','{}')"""
                )
                connection.execute(
                    "INSERT INTO entities VALUES (1,'阿格莱雅','character','')"
                )
                connection.execute(
                    "INSERT INTO aliases VALUES (1,1,'阿格莱雅','official')"
                )
                connection.execute(
                    "INSERT INTO entity_chunks VALUES (1,1,'阿格莱雅')"
                )
                connection.execute(
                    "INSERT INTO chunk_vectors VALUES (1,'{\"证据\": 1.0}',1.0)"
                )
                connection.execute(
                    "INSERT INTO retrieval_metadata VALUES ('vectorizer','{\"version\": 1}')"
                )
                connection.execute(
                    """INSERT INTO relations VALUES
                       (1,1,'mentions',1,'explicit','approved',1.0,'','curated',0)"""
                )
                evidence_id = stable_evidence_id("miyoushe", "42", "body", "abc:0000")
                connection.execute(
                    "INSERT INTO relation_evidence VALUES (1,?,'')", (evidence_id,)
                )

            first = read_official_sqlite_snapshot(path)
            with database.connect() as connection:
                connection.execute(
                    "UPDATE chunk_vectors SET vector_json = ? WHERE chunk_id = 1",
                    ('{"本地缓存": 2.0}',),
                )
                connection.execute(
                    "UPDATE retrieval_metadata SET value_json = ? WHERE key = 'vectorizer'",
                    ('{"version": 2}',),
                )
            second = read_official_sqlite_snapshot(path)
            self.assertNotEqual(first["source_fingerprint"], second["source_fingerprint"])
            self.assertEqual(first["counts"]["sources"], 1)
            self.assertEqual(first["counts"]["official_evidence"], 1)
            self.assertEqual(first["counts"]["chunk_vectors"], 1)
            self.assertEqual(first["counts"]["retrieval_metadata"], 1)
            self.assertIn("chunk_vectors", first["tables"])
            self.assertIn("retrieval_metadata", first["tables"])
            self.assertEqual(first["evidence_ids"], [evidence_id])

    def test_m6a_estimate_is_loaded_by_chunk_scenario(self) -> None:
        self.assertEqual(_m6a_estimate(chunks=100_000), 1_791_935_854)
        self.assertIsNone(_m6a_estimate(chunks=123))


class RetrievalMetricTests(unittest.TestCase):
    def test_recall_and_percentiles_are_reproducible(self) -> None:
        exact = [[1, 2, 3], [4, 5, 6]]
        approximate = [[1, 2, 9], [4, 8, 9]]
        self.assertAlmostEqual(recall_at_k(exact, approximate, 3), 0.5)
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 0.95), 3.85)

    def test_cli_exposes_cloud_commands_without_a_dsn_argument(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertNotIn("--dsn", help_text)
        parsed = parser.parse_args(["cloud-load-fixture", "--run-id", "m6b-test-run"])
        self.assertEqual(parsed.chunks, 100_000)
        self.assertEqual(parsed.dimensions, 1024)
        self.assertFalse(parsed.allow_mutation)
        imported = parser.parse_args([
            "cloud-import-sqlite", "--batch-id", "m6b-real-initial-20260903"
        ])
        self.assertEqual(imported.database, Path("data/database/hksr.sqlite3"))
        self.assertEqual(imported.commit_interval, 500)
        self.assertFalse(imported.allow_mutation)
        acceptance = parser.parse_args(["cloud-acceptance-report"])
        self.assertFalse(hasattr(acceptance, "dsn"))
        self.assertEqual(acceptance.output_json, Path("data/m6b/acceptance-report.json"))


if __name__ == "__main__":
    unittest.main()
    read_official_sqlite_snapshot,
