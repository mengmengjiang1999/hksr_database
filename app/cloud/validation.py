"""Reproducible, secret-safe validation for PostgreSQL and pgvector.

The module imports psycopg lazily so the local SQLite product and its test suite
do not require cloud dependencies. Every mutating entry point requires an
explicit boolean and synthetic cleanup requires an exact validation run ID.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit


DSN_ENVIRONMENT_VARIABLE = "HKSR_POSTGRES_DSN"
REQUIRED_EXTENSIONS = ("vector", "pg_jieba", "zhparser", "pg_bigm")
RUN_ID_PATTERN = re.compile(r"^m6b-[a-z0-9][a-z0-9-]{2,59}$")
REAL_BATCH_ID_PATTERN = re.compile(r"^m(?:6b|7)-real-[a-z0-9][a-z0-9-]{2,59}$")
MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations" / "postgres"
M6A_REPORT_PATH = Path(__file__).resolve().parents[2] / "data" / "m6a" / "validation-report.json"
M6B_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "m6b"
PROHIBITED_OUTPUT_KEYS = {
    "dsn", "endpoint", "host", "hostname", "instance_id", "resource_id",
    "access_key", "accesskey", "password", "secret", "token", "username", "user",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_psycopg() -> Any:
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "Cloud support is not installed; run: python -m pip install -e '.[cloud]'"
        ) from error
    return psycopg


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must match m6b-[a-z0-9][a-z0-9-]{2,59}")
    return run_id


def validate_real_batch_id(batch_id: str) -> str:
    if not REAL_BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ValueError(
            "batch_id must match m6b-real-* or m7-real-*"
        )
    return batch_id


def _redacted_dsn(dsn: str) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", dsn):
        raise ValueError(
            "HKSR_POSTGRES_DSN contains an invalid percent escape; "
            "URL-encode a literal percent sign as %25"
        )
    parsed = urlsplit(dsn)
    scheme = parsed.scheme.split("+")[0]
    if scheme not in {"postgres", "postgresql"}:
        raise ValueError("HKSR_POSTGRES_DSN must use postgres:// or postgresql://")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("HKSR_POSTGRES_DSN must include a host and database")
    return "%s://***:***@***/***" % scheme


@dataclass(frozen=True)
class CloudDatabaseConfig:
    """Runtime-only connection configuration; repr never includes the DSN."""

    dsn: str

    @classmethod
    def from_environment(
        cls, environment: Optional[Mapping[str, str]] = None
    ) -> "CloudDatabaseConfig":
        values = os.environ if environment is None else environment
        dsn = values.get(DSN_ENVIRONMENT_VARIABLE, "").strip()
        if not dsn:
            raise ValueError("%s is required" % DSN_ENVIRONMENT_VARIABLE)
        _redacted_dsn(dsn)
        return cls(dsn=dsn)

    @property
    def redacted(self) -> str:
        return _redacted_dsn(self.dsn)

    def __repr__(self) -> str:
        return "CloudDatabaseConfig(dsn=%r)" % self.redacted


def _connect(config: CloudDatabaseConfig, *, autocommit: bool = False) -> Any:
    psycopg = _require_psycopg()
    try:
        return psycopg.connect(config.dsn, autocommit=autocommit, connect_timeout=15)
    except psycopg.Error:
        raise RuntimeError(
            "PostgreSQL connection failed; verify the private endpoint, port, "
            "database account, password encoding, VPC, and whitelist"
        ) from None


def sanitize_output(value: Any, key: str = "") -> Any:
    """Redact secret-shaped fields and reject accidental DSN-shaped strings."""
    normalized_key = key.lower().replace("-", "_")
    sensitive_key = normalized_key in PROHIBITED_OUTPUT_KEYS or any(
        normalized_key.endswith("_" + item) for item in PROHIBITED_OUTPUT_KEYS
    )
    if sensitive_key:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): sanitize_output(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_output(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_output(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if "postgres://" in lowered or "postgresql://" in lowered:
            return "[redacted]"
    return value


def migration_files(root: Path = MIGRATIONS_ROOT) -> List[Path]:
    return sorted(Path(root).glob("[0-9][0-9][0-9]_*.sql"))


def migration_plan(applied: Iterable[str], root: Path = MIGRATIONS_ROOT) -> List[Path]:
    completed = set(applied)
    return [path for path in migration_files(root) if path.name not in completed]


def apply_migrations(config: CloudDatabaseConfig, *, allow_mutation: bool) -> Dict[str, Any]:
    if not allow_mutation:
        raise PermissionError("Migrations require allow_mutation=True")
    files = migration_files()
    applied_now: List[str] = []
    with _connect(config) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS hksr_meta")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS hksr_meta.schema_migrations (
                   name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
               )"""
        )
        rows = connection.execute(
            "SELECT name FROM hksr_meta.schema_migrations ORDER BY name"
        ).fetchall()
        pending = migration_plan(row[0] for row in rows)
        for path in pending:
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO hksr_meta.schema_migrations(name) VALUES (%s)", (path.name,)
            )
            applied_now.append(path.name)
    return {"applied": applied_now, "total_known": len(files), "status": "ok"}


def _extension_rows(connection: Any) -> Dict[str, Dict[str, Optional[str]]]:
    rows = connection.execute(
        """SELECT a.name, a.default_version, e.extversion
           FROM pg_available_extensions a
           LEFT JOIN pg_extension e ON e.extname = a.name
           WHERE a.name = ANY(%s)
           ORDER BY a.name""",
        (list(REQUIRED_EXTENSIONS),),
    ).fetchall()
    result = {
        name: {"available_version": None, "installed_version": None}
        for name in REQUIRED_EXTENSIONS
    }
    for name, available_version, installed_version in rows:
        result[name] = {
            "available_version": available_version,
            "installed_version": installed_version,
        }
    return result


def build_environment_report(config: CloudDatabaseConfig) -> Dict[str, Any]:
    with _connect(config) as connection:
        version, version_num, ssl_setting, preload = connection.execute(
            """SELECT current_setting('server_version'),
                      current_setting('server_version_num'),
                      current_setting('ssl'),
                      current_setting('shared_preload_libraries')"""
        ).fetchone()
        tls = bool(connection.execute(
            "SELECT COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false)"
        ).fetchone()[0])
        role_row = connection.execute(
            """SELECT r.rolsuper, r.rolcreaterole, r.rolcreatedb
               FROM pg_roles r WHERE r.rolname = current_user"""
        ).fetchone()
        relations = connection.execute(
            """SELECT n.nspname, c.relname, pg_total_relation_size(c.oid)
               FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname IN ('hksr', 'hksr_validation')
                 AND c.relkind IN ('r', 'm')
               ORDER BY n.nspname, c.relname"""
        ).fetchall()
        report = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "connection": {"configured": True, "tls": tls},
            "database": {
                "engine": "PostgreSQL",
                "server_version": version,
                "server_version_num": version_num,
                "ssl_setting": ssl_setting,
                "shared_preload_libraries": sorted(filter(None, preload.split(","))),
            },
            "extensions": _extension_rows(connection),
            "runtime_role": {
                "superuser": bool(role_row[0]),
                "can_create_roles": bool(role_row[1]),
                "can_create_databases": bool(role_row[2]),
            },
            "relations": [
                {"schema": row[0], "relation": row[1], "total_bytes": int(row[2])}
                for row in relations
            ],
        }
    return sanitize_output(report)


def _functional_probe(connection: Any, name: str) -> str:
    if name == "vector":
        value = connection.execute(
            "SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector"
        ).fetchone()[0]
        return "ok" if float(value) == 1.0 else "unexpected_result"
    if name == "pg_bigm":
        connection.execute("SELECT show_bigm('阿格莱雅')").fetchone()
        return "ok"
    if name == "pg_jieba":
        connection.execute("SELECT to_tsvector('jiebacfg', '阿格莱雅')").fetchone()
        return "ok"
    if name == "zhparser":
        connection.execute(
            "CREATE TEXT SEARCH CONFIGURATION pg_temp.hksr_zhcfg (PARSER = zhparser)"
        )
        connection.execute("SELECT to_tsvector('pg_temp.hksr_zhcfg', '阿格莱雅')").fetchone()
        return "ok"
    raise ValueError("Unsupported extension probe")


def probe_extensions(
    config: CloudDatabaseConfig, *, allow_mutation: bool = False
) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    with _connect(config, autocommit=True) as connection:
        available = _extension_rows(connection)
        for name in REQUIRED_EXTENSIONS:
            versions = available[name]
            if not versions["available_version"]:
                results[name] = {**versions, "status": "unavailable"}
                continue
            if not allow_mutation and not versions["installed_version"]:
                results[name] = {**versions, "status": "available_not_installed"}
                continue
            try:
                if allow_mutation:
                    connection.execute('CREATE EXTENSION IF NOT EXISTS "%s"' % name)
                functional = _functional_probe(connection, name)
                installed = connection.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = %s", (name,)
                ).fetchone()
                results[name] = {
                    **versions,
                    "installed_version": installed[0] if installed else None,
                    "status": functional,
                }
            except Exception as error:
                message = str(error).splitlines()[0][:240]
                results[name] = {
                    **versions,
                    "status": "configuration_required" if "preload" in message.lower() else "error",
                    "error_type": type(error).__name__,
                    "message": message,
                }
    return sanitize_output({"generated_at": utc_now(), "extensions": results})


def deterministic_vector(ordinal: int, dimensions: int = 1024) -> List[float]:
    if ordinal < 0 or dimensions < 2:
        raise ValueError("ordinal must be non-negative and dimensions at least 2")
    first = ordinal % dimensions
    second = (ordinal * 31 + 17) % dimensions
    if second == first:
        second = (second + 1) % dimensions
    vector = [0.0] * dimensions
    vector[first] = 0.8
    vector[second] = 0.6
    return vector


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join("%.6g" % value for value in vector) + "]"


def fixture_rows(
    run_id: str, count: int, dimensions: int = 1024
) -> Iterator[Tuple[str, int, str, str, str]]:
    validate_run_id(run_id)
    if count <= 0 or count > 1_000_000:
        raise ValueError("count must be between 1 and 1,000,000")
    for ordinal in range(count):
        evidence_id = "synthetic:%s:%08d" % (run_id, ordinal)
        text = "M6B 合成验证片段 %08d 分组 %04d；不得作为官方证据。" % (
            ordinal, ordinal % 1000,
        )
        yield run_id, ordinal, evidence_id, text, vector_literal(
            deterministic_vector(ordinal, dimensions)
        )


def stable_postgres_evidence_id(
    provider: str, external_id: str, document_key: str, chunk_key: str
) -> str:
    return "%s:%s:%s:%s" % (provider, external_id, document_key, chunk_key)


SQLITE_IMPORT_TABLES = (
    "sources", "documents", "chunks", "entities", "aliases", "entity_chunks",
    "chunk_vectors", "retrieval_metadata", "relations", "relation_evidence",
)


def read_official_sqlite_snapshot(path: Path) -> Dict[str, Any]:
    """Read the local evidence database without modifying it."""
    source_path = Path(path)
    if not source_path.is_file():
        raise FileNotFoundError("SQLite evidence database does not exist")
    uri = source_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        available = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = [table for table in SQLITE_IMPORT_TABLES if table not in available]
        if missing:
            raise ValueError("SQLite evidence database is missing required tables")
        chunk_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(chunks)")
        }
        if "synthetic" in chunk_columns:
            synthetic = int(connection.execute(
                "SELECT count(*) FROM chunks WHERE synthetic != 0"
            ).fetchone()[0])
            if synthetic:
                raise ValueError("Refusing to import synthetic SQLite chunks")
        tables: Dict[str, List[Dict[str, Any]]] = {}
        for table in SQLITE_IMPORT_TABLES:
            rows = connection.execute("SELECT * FROM %s ORDER BY rowid" % table).fetchall()
            tables[table] = [dict(row) for row in rows]
    finally:
        connection.close()

    source_by_id = {int(row["id"]): row for row in tables["sources"]}
    document_by_id = {int(row["id"]): row for row in tables["documents"]}
    evidence_ids = []
    eligible_chunks = 0
    for chunk in tables["chunks"]:
        document = document_by_id[int(chunk["document_id"])]
        source = source_by_id[int(document["source_id"])]
        evidence_id = stable_postgres_evidence_id(
            str(source["provider"]), str(source["external_id"]),
            str(document["document_key"]), str(chunk["chunk_key"]),
        )
        if evidence_id.startswith("synthetic:"):
            raise ValueError("Refusing to import a synthetic evidence identifier")
        evidence_ids.append(evidence_id)
        if bool(document["evidence_eligible"]) and source["status"] == "parsed":
            eligible_chunks += 1
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("SQLite snapshot contains duplicate stable evidence identifiers")

    canonical = json.dumps(
        tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    counts = {table: len(rows) for table, rows in tables.items()}
    counts["official_evidence"] = eligible_chunks
    return {
        "tables": tables,
        "counts": counts,
        "evidence_ids": evidence_ids,
        "source_fingerprint": hashlib.sha256(canonical).hexdigest(),
    }


def _validated_json_text(value: Any, *, field: str) -> str:
    raw = value if value not in (None, "") else "{}"
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as error:
        raise ValueError("Invalid JSON in SQLite field %s" % field) from error
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


class _TransactionBatcher:
    """Bound PostgreSQL transaction size for idempotent snapshot upserts."""

    def __init__(self, connection: Any, commit_interval: int) -> None:
        if commit_interval <= 0:
            raise ValueError("commit_interval must be a positive integer")
        self.connection = connection
        self.commit_interval = commit_interval
        self.pending_writes = 0
        self.commits = 0

    def record_write(self) -> None:
        self.pending_writes += 1
        if self.pending_writes >= self.commit_interval:
            self.flush()

    def flush(self) -> None:
        if not self.pending_writes:
            return
        self.connection.commit()
        self.pending_writes = 0
        self.commits += 1


def import_official_sqlite(
    config: CloudDatabaseConfig,
    *,
    sqlite_path: Path,
    batch_id: str,
    allow_mutation: bool,
    commit_interval: int = 500,
) -> Dict[str, Any]:
    """Upsert one real, official SQLite snapshot into the PostgreSQL schema."""
    validate_real_batch_id(batch_id)
    if not allow_mutation:
        raise PermissionError("Real evidence import requires allow_mutation=True")
    if commit_interval <= 0:
        raise ValueError("commit_interval must be a positive integer")
    snapshot = read_official_sqlite_snapshot(sqlite_path)
    tables = snapshot["tables"]
    source_ids: Dict[int, int] = {}
    document_ids: Dict[int, int] = {}
    chunk_ids: Dict[int, int] = {}
    entity_ids: Dict[int, int] = {}
    relation_ids: Dict[int, int] = {}
    started = time.perf_counter()

    with _connect(config) as connection:
        batcher = _TransactionBatcher(connection, commit_interval)
        existing_batch = connection.execute(
            "SELECT source_fingerprint FROM hksr.import_batches WHERE batch_id = %s",
            (batch_id,),
        ).fetchone()
        if existing_batch and existing_batch[0] != snapshot["source_fingerprint"]:
            raise ValueError("batch_id already refers to a different SQLite snapshot")

        # These link tables are rebuilt from the authoritative SQLite snapshot.
        # Clearing them inside the transaction prevents removed aliases or links
        # from surviving an otherwise idempotent incremental reconciliation.
        connection.execute("DELETE FROM hksr.relation_evidence")
        connection.execute("DELETE FROM hksr.entity_chunks")
        connection.execute("DELETE FROM hksr.aliases")
        connection.commit()
        batcher.commits += 1

        for row in tables["sources"]:
            metadata = json.dumps({
                "parser": row.get("parser", ""),
                "expected_title": row.get("expected_title", ""),
                "remote_created_at": row.get("remote_created_at"),
                "remote_updated_at": row.get("remote_updated_at"),
                "raw_sha256": row.get("raw_sha256"),
                "raw_byte_count": row.get("raw_byte_count"),
            }, ensure_ascii=False, sort_keys=True)
            postgres_id = connection.execute(
                """INSERT INTO hksr.sources
                       (provider, external_id, source_kind, page_url, title, version,
                        official_status, status, content_sha256, metadata,
                        discovered_at, fetched_at, parsed_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                   ON CONFLICT (provider, external_id) DO UPDATE SET
                     source_kind = EXCLUDED.source_kind,
                     page_url = EXCLUDED.page_url,
                     title = EXCLUDED.title,
                     version = EXCLUDED.version,
                     official_status = EXCLUDED.official_status,
                     status = EXCLUDED.status,
                     content_sha256 = EXCLUDED.content_sha256,
                     metadata = EXCLUDED.metadata,
                     discovered_at = EXCLUDED.discovered_at,
                     fetched_at = EXCLUDED.fetched_at,
                     parsed_at = EXCLUDED.parsed_at
                   RETURNING id""",
                (
                    row["provider"], row["external_id"], row["source_kind"],
                    row["page_url"], row["title"], row["version"],
                    row["official_status"], row["status"], row.get("content_sha256"),
                    metadata, row["discovered_at"], row["fetched_at"], row["parsed_at"],
                ),
            ).fetchone()[0]
            source_ids[int(row["id"])] = int(postgres_id)
            batcher.record_write()
        batcher.flush()

        for row in tables["documents"]:
            postgres_id = connection.execute(
                """INSERT INTO hksr.documents
                       (source_id, document_key, title, section_path, content_type,
                        position, evidence_eligible, metadata)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   ON CONFLICT (source_id, document_key) DO UPDATE SET
                     title = EXCLUDED.title,
                     section_path = EXCLUDED.section_path,
                     content_type = EXCLUDED.content_type,
                     position = EXCLUDED.position,
                     evidence_eligible = EXCLUDED.evidence_eligible,
                     metadata = EXCLUDED.metadata
                   RETURNING id""",
                (
                    source_ids[int(row["source_id"])], row["document_key"], row["title"],
                    row["section_path"], row["content_type"], row["position"],
                    bool(row["evidence_eligible"]),
                    _validated_json_text(row["metadata_json"], field="documents.metadata_json"),
                ),
            ).fetchone()[0]
            document_ids[int(row["id"])] = int(postgres_id)
            batcher.record_write()
        batcher.flush()

        source_by_id = {int(row["id"]): row for row in tables["sources"]}
        document_by_id = {int(row["id"]): row for row in tables["documents"]}
        for row in tables["chunks"]:
            document = document_by_id[int(row["document_id"])]
            source = source_by_id[int(document["source_id"])]
            evidence_id = stable_postgres_evidence_id(
                source["provider"], source["external_id"],
                document["document_key"], row["chunk_key"],
            )
            postgres_id = connection.execute(
                """INSERT INTO hksr.chunks
                       (document_id, chunk_key, evidence_id, section_path, speaker,
                        text, position, content_sha256, metadata, embedding, synthetic)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NULL,false)
                   ON CONFLICT (document_id, chunk_key) DO UPDATE SET
                     evidence_id = EXCLUDED.evidence_id,
                     section_path = EXCLUDED.section_path,
                     speaker = EXCLUDED.speaker,
                     text = EXCLUDED.text,
                     position = EXCLUDED.position,
                     embedding = CASE
                       WHEN chunks.content_sha256 = EXCLUDED.content_sha256
                       THEN chunks.embedding ELSE NULL END,
                     content_sha256 = EXCLUDED.content_sha256,
                     metadata = EXCLUDED.metadata,
                     synthetic = false
                   RETURNING id""",
                (
                    document_ids[int(row["document_id"])], row["chunk_key"], evidence_id,
                    row["section_path"], row["speaker"], row["text"], row["position"],
                    row["content_sha256"],
                    _validated_json_text(row["metadata_json"], field="chunks.metadata_json"),
                ),
            ).fetchone()[0]
            chunk_ids[int(row["id"])] = int(postgres_id)
            batcher.record_write()
        batcher.flush()

        for row in tables["entities"]:
            postgres_id = connection.execute(
                """INSERT INTO hksr.entities
                       (canonical_name, entity_type, description)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (canonical_name, entity_type) DO UPDATE SET
                     description = EXCLUDED.description
                   RETURNING id""",
                (row["canonical_name"], row["entity_type"], row["description"]),
            ).fetchone()[0]
            entity_ids[int(row["id"])] = int(postgres_id)
            batcher.record_write()
        batcher.flush()

        for row in tables["aliases"]:
            connection.execute(
                """INSERT INTO hksr.aliases(entity_id, alias, alias_type)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (entity_id, alias) DO UPDATE SET
                     alias_type = EXCLUDED.alias_type""",
                (entity_ids[int(row["entity_id"])], row["alias"], row["alias_type"]),
            )
            batcher.record_write()
        batcher.flush()

        for row in tables["entity_chunks"]:
            connection.execute(
                """INSERT INTO hksr.entity_chunks(entity_id, chunk_id, matched_text)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (entity_id, chunk_id) DO UPDATE SET
                     matched_text = EXCLUDED.matched_text""",
                (
                    entity_ids[int(row["entity_id"])], chunk_ids[int(row["chunk_id"])],
                    row["matched_text"],
                ),
            )
            batcher.record_write()
        batcher.flush()

        for row in tables["relations"]:
            postgres_id = connection.execute(
                """INSERT INTO hksr.relations
                       (subject_id, predicate, object_id, evidence_level, review_status,
                        confidence, reasoning, origin, is_stale)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (subject_id, predicate, object_id, origin) DO UPDATE SET
                     evidence_level = EXCLUDED.evidence_level,
                     review_status = EXCLUDED.review_status,
                     confidence = EXCLUDED.confidence,
                     reasoning = EXCLUDED.reasoning,
                     is_stale = EXCLUDED.is_stale
                   RETURNING id""",
                (
                    entity_ids[int(row["subject_id"])], row["predicate"],
                    entity_ids[int(row["object_id"])], row["evidence_level"],
                    row["review_status"], row["confidence"], row["reasoning"],
                    row["origin"], bool(row["is_stale"]),
                ),
            ).fetchone()[0]
            relation_ids[int(row["id"])] = int(postgres_id)
            batcher.record_write()
        batcher.flush()

        valid_evidence_ids = set(snapshot["evidence_ids"])
        for row in tables["relation_evidence"]:
            if row["evidence_id"] not in valid_evidence_ids:
                raise ValueError("Relation evidence points outside the SQLite snapshot")
            connection.execute(
                """INSERT INTO hksr.relation_evidence(relation_id, evidence_id, note)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (relation_id, evidence_id) DO UPDATE SET
                     note = EXCLUDED.note""",
                (
                    relation_ids[int(row["relation_id"])], row["evidence_id"], row["note"],
                ),
            )
            batcher.record_write()
        batcher.flush()

        for row in tables["retrieval_metadata"]:
            connection.execute(
                """INSERT INTO hksr.ingestion_state(state_key, value)
                   VALUES (%s,%s::jsonb)
                   ON CONFLICT (state_key) DO UPDATE SET
                     value = EXCLUDED.value, updated_at = now()""",
                (
                    "sqlite_retrieval_" + str(row["key"]),
                    _validated_json_text(
                        row["value_json"], field="retrieval_metadata.value_json"
                    ),
                ),
            )
            batcher.record_write()
        batcher.flush()

        expected = {
            key: int(snapshot["counts"][key]) for key in (
                "sources", "documents", "chunks", "entities", "aliases",
                "entity_chunks", "relations", "relation_evidence", "official_evidence",
            )
        }
        expected_wiki_by_kind: Dict[str, int] = {}
        for row in tables["sources"]:
            if row["provider"] == "mihoyo_wiki":
                kind = str(row["source_kind"])
                expected_wiki_by_kind[kind] = expected_wiki_by_kind.get(kind, 0) + 1

        def prune_missing(table: str, identifiers: Iterable[int]) -> None:
            retained = list(identifiers)
            if retained:
                connection.execute(
                    "DELETE FROM hksr.%s WHERE NOT (id = ANY(%%s))" % table,
                    (retained,),
                )
            else:
                connection.execute("DELETE FROM hksr.%s" % table)

        # Remove superseded rows only after their replacements and evidence links
        # are present. Pruning, count validation, and the acceptance marker remain
        # one transaction; preceding idempotent batches are safe to replay.
        prune_missing("relations", relation_ids.values())
        prune_missing("chunks", chunk_ids.values())
        prune_missing("documents", document_ids.values())
        prune_missing("entities", entity_ids.values())
        prune_missing("sources", source_ids.values())

        observed = {
            table: int(connection.execute(
                "SELECT count(*) FROM hksr.%s" % table
            ).fetchone()[0])
            for table in (
                "sources", "documents", "chunks", "entities", "aliases",
                "entity_chunks", "relations", "relation_evidence", "official_evidence",
            )
        }
        counts_match = expected == observed
        if not counts_match:
            raise ValueError("PostgreSQL counts do not match the pruned SQLite snapshot")
        observed_wiki_by_kind = {
            str(kind): int(count) for kind, count in connection.execute(
                """SELECT source_kind, count(*) FROM hksr.sources
                   WHERE provider = 'mihoyo_wiki'
                   GROUP BY source_kind ORDER BY source_kind"""
            ).fetchall()
        }
        wiki_catalog = {
            "expected_unique_content_ids": sum(expected_wiki_by_kind.values()),
            "observed_unique_content_ids": sum(observed_wiki_by_kind.values()),
            "expected_by_source_kind": dict(sorted(expected_wiki_by_kind.items())),
            "observed_by_source_kind": dict(sorted(observed_wiki_by_kind.items())),
            "counts_match": expected_wiki_by_kind == observed_wiki_by_kind,
        }
        if not wiki_catalog["counts_match"]:
            raise ValueError("PostgreSQL Wiki category counts do not match SQLite")
        connection.execute(
            """INSERT INTO hksr.import_batches
                   (batch_id, source_fingerprint, counts)
               VALUES (%s,%s,%s::jsonb)
               ON CONFLICT (batch_id) DO UPDATE SET
                 counts = EXCLUDED.counts, imported_at = now()""",
            (batch_id, snapshot["source_fingerprint"], json.dumps(observed, sort_keys=True)),
        )

    return {
        "batch_id": batch_id,
        "source_fingerprint": snapshot["source_fingerprint"],
        "expected_counts": expected,
        "observed_counts": observed,
        "counts_match": counts_match,
        "stable_evidence_ids_unique": True,
        "dense_embeddings_imported": 0,
        "local_sparse_vectors_deferred": int(snapshot["counts"]["chunk_vectors"]),
        "synthetic_rows_imported": 0,
        "repeated_batch": bool(existing_batch),
        "commit_interval": commit_interval,
        "transaction_commits": batcher.commits + 1,
        "wiki_catalog": wiki_catalog,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _m6a_estimate(path: Path = M6A_REPORT_PATH, chunks: int = 100_000) -> Optional[int]:
    if not Path(path).exists():
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    for scenario in payload.get("capacity_scenarios", []):
        if int(scenario.get("chunks", 0)) == chunks:
            return int(scenario["float32_postgres_planning_bytes"])
    return None


def _validation_relation_sizes(connection: Any) -> Dict[str, int]:
    rows = connection.execute(
        """SELECT c.relname, pg_total_relation_size(c.oid)
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'hksr_validation' AND c.relkind IN ('r', 'm')
           ORDER BY c.relname"""
    ).fetchall()
    return {str(name): int(size) for name, size in rows}


def load_fixture(
    config: CloudDatabaseConfig,
    *,
    run_id: str,
    count: int = 100_000,
    dimensions: int = 1024,
    allow_mutation: bool,
) -> Dict[str, Any]:
    validate_run_id(run_id)
    if not allow_mutation:
        raise PermissionError("Fixture loading requires allow_mutation=True")
    if dimensions != 1024:
        raise ValueError("The M6B validation schema requires exactly 1024 dimensions")
    started = time.perf_counter()
    index_duration = 0.0
    with _connect(config) as connection:
        existing = connection.execute(
            "SELECT chunk_count, dimensions FROM hksr_validation.runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if existing and (int(existing[0]), int(existing[1])) != (count, dimensions):
            raise ValueError("run_id already exists with different fixture parameters")
        connection.execute(
            """INSERT INTO hksr_validation.runs(run_id, chunk_count, dimensions)
               VALUES (%s, %s, %s) ON CONFLICT (run_id) DO NOTHING""",
            (run_id, count, dimensions),
        )
        if not existing:
            with connection.cursor().copy(
                """COPY hksr_validation.chunks
                   (run_id, ordinal, evidence_id, text, embedding)
                   FROM STDIN"""
            ) as copy:
                for row in fixture_rows(run_id, count, dimensions):
                    copy.write_row(row)
        inserted = int(connection.execute(
            "SELECT count(*) FROM hksr_validation.chunks WHERE run_id = %s", (run_id,)
        ).fetchone()[0])
        stable_before, original_text = connection.execute(
            """SELECT evidence_id, text FROM hksr_validation.chunks
               WHERE run_id = %s ORDER BY ordinal LIMIT 1""",
            (run_id,),
        ).fetchone()
        connection.execute(
            """UPDATE hksr_validation.chunks SET text = text || ' 增量更新验证'
               WHERE run_id = %s AND ordinal = 0""",
            (run_id,),
        )
        stable_after = connection.execute(
            """SELECT evidence_id FROM hksr_validation.chunks
               WHERE run_id = %s AND ordinal = 0""",
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            """UPDATE hksr_validation.chunks SET text = %s
               WHERE run_id = %s AND ordinal = 0""",
            (original_text, run_id),
        )
        index_started = time.perf_counter()
        connection.execute(
            """CREATE INDEX IF NOT EXISTS validation_chunks_embedding_hnsw_idx
               ON hksr_validation.chunks USING hnsw (embedding vector_cosine_ops)"""
        )
        index_duration = time.perf_counter() - index_started
        relation_sizes = _validation_relation_sizes(connection)
    observed_bytes = sum(relation_sizes.values())
    expected_bytes = _m6a_estimate(chunks=count)
    deviation = None
    if expected_bytes:
        deviation = (observed_bytes - expected_bytes) / float(expected_bytes)
    return {
        "run_id": run_id,
        "chunks": inserted,
        "dimensions": dimensions,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "index_build_seconds": round(index_duration, 3),
        "relation_sizes_bytes": relation_sizes,
        "observed_total_relation_bytes": observed_bytes,
        "m6a_estimated_bytes": expected_bytes,
        "m6a_deviation_ratio": round(deviation, 6) if deviation is not None else None,
        "m6a_deviation_within_50_percent": abs(deviation) <= 0.5 if deviation is not None else None,
        "stable_update": {
            "unchanged_evidence_id_retained": stable_before == stable_after,
            "test_row_restored": True,
        },
        "synthetic": True,
    }


def recall_at_k(expected: Sequence[Sequence[Any]], actual: Sequence[Sequence[Any]], k: int) -> float:
    if k <= 0 or len(expected) != len(actual) or not expected:
        raise ValueError("Expected and actual query results must be non-empty and aligned")
    recalls = []
    for exact, approximate in zip(expected, actual):
        target = set(exact[:k])
        found = set(approximate[:k])
        recalls.append(len(target & found) / float(k))
    return sum(recalls) / len(recalls)


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values or not 0 <= fraction <= 1:
        raise ValueError("percentile needs values and a fraction from 0 to 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _query_ids(connection: Any, run_id: str, query: str, *, exact: bool) -> List[str]:
    connection.execute("SET LOCAL enable_indexscan = %s" % ("off" if exact else "on"))
    rows = connection.execute(
        """SELECT evidence_id FROM hksr_validation.chunks
           WHERE run_id = %s ORDER BY embedding <=> %s::vector LIMIT 10""",
        (run_id, query),
    ).fetchall()
    return [row[0] for row in rows]


def _hybrid_query(connection: Any, run_id: str, vector: str, text: str) -> List[str]:
    rows = connection.execute(
        """WITH semantic AS (
               SELECT evidence_id, 0.8 * (1.0 - (embedding <=> %s::vector)) AS score
               FROM hksr_validation.chunks
               WHERE run_id = %s
               ORDER BY embedding <=> %s::vector
               LIMIT 50
           ), lexical AS (
               SELECT evidence_id,
                      0.2 * ts_rank_cd(search_vector, plainto_tsquery('simple', %s)) AS score
               FROM hksr_validation.chunks
               WHERE run_id = %s
                 AND search_vector @@ plainto_tsquery('simple', %s)
               ORDER BY score DESC
               LIMIT 50
           ), candidates AS (
               SELECT * FROM semantic UNION ALL SELECT * FROM lexical
           )
           SELECT evidence_id FROM candidates
           GROUP BY evidence_id ORDER BY sum(score) DESC, evidence_id LIMIT 10""",
        (vector, run_id, vector, text, run_id, text),
    ).fetchall()
    return [row[0] for row in rows]


def run_benchmark(
    config: CloudDatabaseConfig,
    *,
    run_id: str,
    query_count: int = 20,
    concurrency: int = 10,
) -> Dict[str, Any]:
    validate_run_id(run_id)
    if query_count <= 0 or concurrency <= 0:
        raise ValueError("query_count and concurrency must be positive")
    queries = [
        (
            vector_literal(deterministic_vector(index * 997)),
            "分组 %04d" % ((index * 997) % 1000),
        )
        for index in range(query_count)
    ]
    exact_results: List[List[str]] = []
    approximate_results: List[List[str]] = []
    with _connect(config) as connection:
        for query, _text in queries:
            with connection.transaction():
                exact_results.append(_query_ids(connection, run_id, query, exact=True))
            with connection.transaction():
                approximate_results.append(_query_ids(connection, run_id, query, exact=False))

    def timed_query(query: Tuple[str, str]) -> float:
        started = time.perf_counter()
        with _connect(config) as connection:
            _hybrid_query(connection, run_id, query[0], query[1])
        return (time.perf_counter() - started) * 1000.0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        latencies = list(executor.map(timed_query, queries))
    recall = recall_at_k(exact_results, approximate_results, 10)
    return {
        "run_id": run_id,
        "query_count": query_count,
        "concurrency": concurrency,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
            "mean": round(statistics.fmean(latencies), 3),
        },
        "recall_at_10": round(recall, 6),
        "acceptance": {"p95_at_most_300ms": percentile(latencies, 0.95) <= 300, "recall_at_least_0_90": recall >= 0.90},
    }


def cleanup_fixture(
    config: CloudDatabaseConfig, *, run_id: str, allow_mutation: bool
) -> Dict[str, Any]:
    validate_run_id(run_id)
    if not allow_mutation:
        raise PermissionError("Fixture cleanup requires allow_mutation=True")
    with _connect(config) as connection:
        before = int(connection.execute(
            "SELECT count(*) FROM hksr_validation.chunks WHERE run_id = %s", (run_id,)
        ).fetchone()[0])
        connection.execute("DELETE FROM hksr_validation.runs WHERE run_id = %s", (run_id,))
        after = int(connection.execute(
            "SELECT count(*) FROM hksr_validation.chunks WHERE run_id = %s", (run_id,)
        ).fetchone()[0])
    return {"run_id": run_id, "deleted_chunks": before - after, "remaining_chunks": after}


def build_database_audit(config: CloudDatabaseConfig) -> Dict[str, Any]:
    """Read the final PostgreSQL state without changing cloud data."""
    with _connect(config) as connection:
        validation_table = connection.execute(
            "SELECT to_regclass('hksr_validation.chunks') IS NOT NULL"
        ).fetchone()[0]
        synthetic_rows = 0
        if validation_table:
            synthetic_rows = int(connection.execute(
                "SELECT count(*) FROM hksr_validation.chunks"
            ).fetchone()[0])
        official_counts = {
            table: int(connection.execute(
                "SELECT count(*) FROM hksr.%s" % table
            ).fetchone()[0])
            for table in (
                "sources", "documents", "chunks", "entities", "aliases",
                "entity_chunks", "relations", "relation_evidence", "official_evidence",
            )
        }
        import_batches = int(connection.execute(
            "SELECT count(*) FROM hksr.import_batches"
        ).fetchone()[0])
    return sanitize_output({
        "schema_version": 1,
        "generated_at": utc_now(),
        "synthetic_rows": synthetic_rows,
        "official_counts": official_counts,
        "import_batches": import_batches,
    })


def read_json_report(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("M6B report inputs must contain a JSON object")
    return payload


def _restore_result(
    value: Mapping[str, Any], source_key: str, restored_key: str
) -> Tuple[bool, Optional[float]]:
    source_hash = value.get(source_key)
    restored_hash = value.get(restored_key)
    hashes_match = bool(
        isinstance(source_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", source_hash)
        and source_hash == restored_hash
    )
    duration = None
    try:
        started = datetime.fromisoformat(str(value["started_at"]))
        completed = datetime.fromisoformat(str(value["completed_at"]))
        duration = round((completed - started).total_seconds(), 3)
    except (KeyError, TypeError, ValueError):
        pass
    return bool(value.get("completed") and hashes_match and duration is not None and duration >= 0), duration


def build_acceptance_report(
    *,
    procurement: Mapping[str, Any],
    extension_observation: Mapping[str, Any],
    operator_evidence: Mapping[str, Any],
    import_reports: Sequence[Mapping[str, Any]],
    database_audit: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Combine automatic measurements and operator evidence into explicit gates."""
    database = procurement.get("database", {})
    functional = extension_observation.get("functional_probes", {})
    rds = operator_evidence.get("rds", {})
    oss = operator_evidence.get("oss", {})
    application_runner = operator_evidence.get("application_runner", {})
    rds_restore, rds_duration = _restore_result(
        rds.get("backup_restore", {}), "test_artifact_sha256", "restored_artifact_sha256"
    )
    oss_restore, oss_duration = _restore_result(
        oss.get("historical_restore", {}), "test_object_sha256", "restored_object_sha256"
    )
    imports_ok = bool(
        len(import_reports) >= 2
        and import_reports[0].get("repeated_batch") is False
        and import_reports[-1].get("repeated_batch") is True
        and import_reports[0].get("source_fingerprint")
        == import_reports[-1].get("source_fingerprint")
        and all(
            item.get("counts_match") is True
            and item.get("stable_evidence_ids_unique") is True
            and int(item.get("synthetic_rows_imported", -1)) == 0
            for item in import_reports
        )
    )
    extensions_ok = bool(
        functional.get("vector", {}).get("status") in {"passed", "ok"}
        and all(
            functional.get(name, {}).get("status")
            in {"passed", "passed_with_relevance_caveat", "ok"}
            for name in ("pg_bigm", "pg_jieba", "zhparser")
        )
    )
    audit = database_audit or {}
    gates = {
        "postgresql_18_and_extensions": bool(
            int(database.get("major_version", 0)) == 18 and extensions_ok
        ),
        "private_least_privilege_execution": bool(
            rds.get("private_connectivity_verified")
            and rds.get("runtime_role_read_only_verified")
            and rds.get("prohibited_operations_failed")
        ),
        "idempotent_official_import": imports_ok,
        "no_synthetic_rows_remaining": bool(
            database_audit is not None and int(audit.get("synthetic_rows", -1)) == 0
        ),
        "cloud_application_smoke_test": bool(
            application_runner.get("deployed")
            and application_runner.get("health_check_passed")
            and application_runner.get("private_database_read_passed")
            and application_runner.get("automatic_restart_verified")
        ),
        "rcu_cap_and_automatic_pause": bool(
            int(rds.get("maximum_rcu", 0)) <= 4
            and int(database.get("maximum_rcu", 0)) <= 4
            and database.get("automatic_pause")
        ),
        "temporary_resources_released": operator_evidence.get(
            "temporary_resources_remaining"
        ) == [],
        "procurement_price_observed": bool(procurement.get("public_list_price")),
    }
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "automatic_measurements": {
            "database_audit": audit if database_audit is not None else None,
            "official_imports": list(import_reports),
        },
        "operator_attested_evidence": {
            "procurement": procurement,
            "extensions": extension_observation,
            "recovery_and_cleanup": operator_evidence,
        },
        "restore_durations_seconds": {
            "oss": oss_duration,
            "rds": rds_duration,
        },
        "deferred_checks": {
            "oss_historical_version_restore": not oss_restore,
            "rds_backup_restore": not rds_restore,
        },
        "acceptance_gates": gates,
        "ready_to_archive": all(gates.values()),
    }
    return sanitize_output(report)


def render_acceptance_markdown(report: Mapping[str, Any]) -> str:
    gates = report.get("acceptance_gates", {})
    lines = [
        "# M6B 云数据库验收结果",
        "",
        "> 生成时间：%s" % report.get("generated_at", "unknown"),
        "> 归档状态：%s" % ("可以归档" if report.get("ready_to_archive") else "尚未通过全部门槛"),
        "",
        "## 验收门槛",
        "",
        "| 门槛 | 状态 |",
        "| --- | --- |",
    ]
    for name, passed in gates.items():
        lines.append("| `%s` | %s |" % (name, "通过" if passed else "待完成"))
    lines.extend([
        "",
        "## 延后项目",
        "",
        "- OSS 历史版本恢复演练：不属于本阶段门槛",
        "- RDS 备份恢复演练：不属于本阶段门槛",
        "",
        "自动测量与人工确认的原始脱敏证据见同名 JSON 报告。",
        "",
    ])
    return "\n".join(lines)


def write_acceptance_reports(json_path: Path, markdown_path: Path, report: Mapping[str, Any]) -> None:
    write_json_report(json_path, report)
    Path(markdown_path).parent.mkdir(parents=True, exist_ok=True)
    Path(markdown_path).write_text(render_acceptance_markdown(report), encoding="utf-8")


def write_json_report(path: Path, report: Mapping[str, Any]) -> None:
    safe = sanitize_output(report)
    encoded = json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    lowered = encoded.lower()
    if "postgres://" in lowered or "postgresql://" in lowered:
        raise ValueError("Refusing to write a report containing a PostgreSQL DSN")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(encoded, encoding="utf-8")


def content_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
