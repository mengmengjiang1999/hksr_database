import tempfile
import unittest
from pathlib import Path

from app.cloud.runtime_role import (
    META_READ_TABLES, READ_TABLES, _atomic_secret, runtime_dsn, validate_role_name,
)


class RuntimeRoleTests(unittest.TestCase):
    def test_role_name_is_strictly_bounded(self) -> None:
        self.assertEqual(validate_role_name("hksr_runtime"), "hksr_runtime")
        for value in ("HKSR", "bad-role", "9runtime", "a" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_role_name(value)

    def test_runtime_read_contract_has_expected_tables(self) -> None:
        self.assertEqual(len(READ_TABLES), len(set(READ_TABLES)))
        for table_name in (
            "sources", "documents", "chunks", "entities", "relations",
            "retrieval_metadata_chunks", "import_batches",
        ):
            self.assertIn(table_name, READ_TABLES)
        self.assertEqual(META_READ_TABLES, ("schema_migrations",))

    def test_application_launcher_uses_runtime_dsn_not_admin_dsn(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = root.joinpath("deploy/run-hksr-app.sh").read_text(encoding="utf-8")
        self.assertIn(".config/hksr/rds-runtime.dsn", launcher)
        self.assertNotIn(".config/hksr/rds.dsn", launcher)

    def test_public_validation_schema_access_is_explicitly_revoked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module = root.joinpath("app/cloud/runtime_role.py").read_text(encoding="utf-8")
        self.assertIn(
            "REVOKE ALL ON SCHEMA hksr_validation FROM PUBLIC", module
        )

    def test_secret_file_is_atomic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private" / "runtime.dsn"
            _atomic_secret(path, "private-runtime-value")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 1)

    def test_runtime_dsn_remains_url_and_replaces_admin_credentials(self) -> None:
        value = runtime_dsn(
            "postgresql://admin:old@example.test:5432/hksr?sslmode=require",
            "hksr_runtime",
            "new:/?#[]@ password",
        )
        self.assertTrue(value.startswith("postgresql://hksr_runtime:"))
        self.assertIn("@example.test:5432/hksr?sslmode=require", value)
        self.assertNotIn("admin", value)
        self.assertNotIn("old", value)
        self.assertNotIn(" password", value)

    def test_runtime_dsn_rejects_keyword_conninfo(self) -> None:
        with self.assertRaises(ValueError):
            runtime_dsn("host=example.test dbname=hksr", "hksr_runtime", "secret")


if __name__ == "__main__":
    unittest.main()
