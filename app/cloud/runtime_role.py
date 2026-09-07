"""Provision and verify the dedicated PostgreSQL application read role."""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional


DEFAULT_ROLE = "hksr_runtime"
ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
READ_TABLES = (
    "aliases",
    "chunk_vectors",
    "chunks",
    "documents",
    "entities",
    "entity_chunks",
    "identity_names",
    "import_batches",
    "narrative_people",
    "playable_forms",
    "relation_evidence",
    "relations",
    "retrieval_metadata",
    "retrieval_metadata_chunks",
    "source_dispositions",
    "sources",
)
META_READ_TABLES = ("schema_migrations",)


def validate_role_name(role: str) -> str:
    if not ROLE_PATTERN.fullmatch(role):
        raise ValueError("Runtime role must be a lowercase PostgreSQL identifier")
    return role


def _require_psycopg() -> Any:
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("Cloud support is not installed; install the cloud extra") from error
    return psycopg


def _atomic_secret(path: Path, value: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value.rstrip("\n") + "\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def provision_runtime_role(
    admin_dsn: str,
    runtime_path: Path,
    *,
    role: str = DEFAULT_ROLE,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or rotate the read role and atomically store its private DSN."""
    role = validate_role_name(role)
    password = password or secrets.token_urlsafe(36)
    psycopg = _require_psycopg()
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    connection_info = conninfo_to_dict(admin_dsn)
    database_name = connection_info.get("dbname")
    if not database_name:
        raise ValueError("Administrator DSN must select a database")
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
        ).fetchone()
        identifier = sql.Identifier(role)
        password_literal = sql.Literal(password)
        if exists:
            connection.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION").format(
                    identifier, password_literal
                )
            )
        else:
            connection.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION").format(
                    identifier, password_literal
                )
            )
        connection.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only=on").format(identifier))
        connection.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='15s'").format(identifier))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database_name), identifier
            )
        )
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA hksr FROM {}").format(identifier))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA hksr TO {}").format(identifier))
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA hksr_meta FROM {}").format(identifier))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA hksr_meta TO {}").format(identifier))
        connection.execute(
            sql.SQL("GRANT SELECT ON {} TO {}").format(
                sql.SQL(", ").join(
                    sql.Identifier("hksr", table_name) for table_name in READ_TABLES
                ),
                identifier,
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON {} TO {}").format(
                sql.SQL(", ").join(
                    sql.Identifier("hksr_meta", table_name)
                    for table_name in META_READ_TABLES
                ),
                identifier,
            )
        )

    runtime_dsn = make_conninfo(admin_dsn, user=role, password=password)
    _atomic_secret(Path(runtime_path), runtime_dsn)
    return {
        "role": role,
        "runtime_dsn_path": str(runtime_path),
        "runtime_dsn_mode": oct(Path(runtime_path).stat().st_mode & 0o777),
        "granted_tables": ["hksr.%s" % item for item in READ_TABLES]
        + ["hksr_meta.%s" % item for item in META_READ_TABLES],
        "secret_recorded": False,
    }


def _probe(runtime_dsn: str, statement: str, parameters: Iterable[Any] = ()) -> Dict[str, Any]:
    psycopg = _require_psycopg()
    try:
        with psycopg.connect(runtime_dsn, autocommit=True) as connection:
            connection.execute(statement, tuple(parameters))
        return {"allowed": True, "sqlstate": None}
    except psycopg.Error as error:
        return {"allowed": False, "sqlstate": error.sqlstate}


def verify_runtime_privileges(runtime_dsn: str) -> Dict[str, Any]:
    """Run secret-safe allowed/denied probes using the actual runtime credential."""
    psycopg = _require_psycopg()
    with psycopg.connect(runtime_dsn, autocommit=True) as connection:
        row = connection.execute(
            """SELECT current_user, current_setting('transaction_read_only'),
                      r.rolsuper, r.rolcreatedb, r.rolcreaterole
               FROM pg_roles r WHERE r.rolname=current_user"""
        ).fetchone()
    identity = {
        "role": str(row[0]),
        "transaction_read_only": str(row[1]),
        "superuser": bool(row[2]),
        "can_create_databases": bool(row[3]),
        "can_create_roles": bool(row[4]),
    }
    reads = {
        "hksr.%s" % table_name: _probe(
            runtime_dsn, "SELECT count(*) FROM hksr.%s" % table_name
        )
        for table_name in READ_TABLES
    }
    reads.update({
        "hksr_meta.%s" % table_name: _probe(
            runtime_dsn, "SELECT count(*) FROM hksr_meta.%s" % table_name
        )
        for table_name in META_READ_TABLES
    })
    denied = {
        "evidence_insert": _probe(
            runtime_dsn,
            "INSERT INTO hksr.sources(provider, external_id, title, source_kind, status) "
            "VALUES ('runtime-probe','runtime-probe','runtime-probe','official_article','failed') RETURNING id",
        ),
        "evidence_update": _probe(runtime_dsn, "UPDATE hksr.sources SET title=title WHERE false RETURNING id"),
        "evidence_delete": _probe(runtime_dsn, "DELETE FROM hksr.sources WHERE false RETURNING id"),
        "schema_create": _probe(runtime_dsn, "CREATE TABLE hksr.runtime_probe_forbidden(id integer)"),
        "role_create": _probe(runtime_dsn, "CREATE ROLE hksr_runtime_probe_forbidden"),
        "unrelated_schema": _probe(runtime_dsn, "SELECT count(*) FROM hksr_validation.runs"),
    }
    passed = bool(
        identity["transaction_read_only"] == "on"
        and not identity["superuser"]
        and not identity["can_create_databases"]
        and not identity["can_create_roles"]
        and all(item["allowed"] for item in reads.values())
        and all(not item["allowed"] for item in denied.values())
    )
    return {"passed": passed, "identity": identity, "required_reads": reads, "denied_operations": denied}


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
