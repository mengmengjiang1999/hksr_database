"""Backend-neutral read stores for the private knowledge application."""

from __future__ import annotations

import gzip
import hashlib
import json
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Mapping, Optional, Protocol, Sequence


class ReadStore(Protocol):
    backend_name: str
    mutable: bool

    def initialize(self) -> None: ...
    def readiness(self) -> Dict[str, Any]: ...
    def source_detail(self, source_id: int) -> Dict[str, Any]: ...
    def entity_catalog(self) -> List[Dict[str, Any]]: ...
    def retrieval_metadata(self) -> Dict[str, Any]: ...
    def search(
        self, query: str, limit: int = 10,
        source_kinds: Optional[Sequence[str]] = None, version: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...
    def entity_chunk_ids(
        self, entity_ids: Sequence[int], limit: int = 200,
        source_kinds: Optional[Sequence[str]] = None, version: Optional[str] = None,
    ) -> List[int]: ...
    def retrieval_rows(self, chunk_ids: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]: ...
    def retrieval_rows_by_evidence_ids(self, evidence_ids: Sequence[str]) -> List[Dict[str, Any]]: ...
    def evidence_ids(self) -> set[str]: ...
    def evidence_match_rows(self) -> List[Dict[str, Any]]: ...
    def evidence_context(self, evidence_id: str, window: int = 1) -> Dict[str, Any]: ...
    def statistics(self) -> Dict[str, Any]: ...
    def catalog_metadata(self) -> Dict[str, Any]: ...
    def identity_rows(self) -> Dict[str, List[Dict[str, Any]]]: ...
    def relation_audit(self, *, update: bool = False) -> Dict[str, Any]: ...
    def relation_rows(
        self, entity_name: Optional[str] = None, *, include_candidates: bool = False
    ) -> List[Dict[str, Any]]: ...
    def approved_relation_evidence_ids(self, left: int, right: int) -> set[str]: ...
    def corpus_snapshot_rows(self) -> Dict[str, Any]: ...
    def source_disposition_rows(self) -> List[Dict[str, Any]]: ...
    def list_sources(
        self, statuses: Optional[Sequence[str]] = None, limit: Optional[int] = None
    ) -> List[Mapping[str, Any]]: ...


class ReadStoreUnavailable(RuntimeError):
    """Sanitized retryable backend failure safe for API responses."""


def _decode_chunked_metadata(
    descriptor: Mapping[str, Any], payload_rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    expected_count = int(descriptor.get("chunk_count", -1))
    if expected_count < 1 or len(payload_rows) != expected_count:
        raise RuntimeError("PostgreSQL retrieval metadata is incomplete")
    if [int(row["ordinal"]) for row in payload_rows] != list(range(expected_count)):
        raise RuntimeError("PostgreSQL retrieval metadata chunks are not contiguous")
    compressed = b"".join(bytes(row["payload"]) for row in payload_rows)
    try:
        raw = gzip.decompress(compressed)
    except (EOFError, OSError) as error:
        raise RuntimeError("PostgreSQL retrieval metadata is corrupt") from error
    if len(raw) != int(descriptor.get("raw_bytes", -1)):
        raise RuntimeError("PostgreSQL retrieval metadata length does not match")
    if hashlib.sha256(raw).hexdigest() != descriptor.get("raw_sha256"):
        raise RuntimeError("PostgreSQL retrieval metadata checksum does not match")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("PostgreSQL retrieval metadata must be an object")
    return value


def _require_pool() -> Any:
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as error:
        raise RuntimeError(
            "Cloud read support is not installed; run: python -m pip install -e '.[cloud]'"
        ) from error
    return ConnectionPool


class PostgresReadStore:
    """Read-only PostgreSQL implementation of the application data contract."""

    backend_name = "postgres"
    mutable = False

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 0,
        max_size: int = 2,
        acquire_timeout: float = 5.0,
        connect_timeout: int = 10,
        statement_timeout_ms: int = 15000,
    ) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        if min_size < 0 or max_size < 1 or min_size > max_size:
            raise ValueError("Invalid PostgreSQL pool bounds")
        if acquire_timeout <= 0 or connect_timeout <= 0 or statement_timeout_ms <= 0:
            raise ValueError("PostgreSQL timeouts must be positive")
        from psycopg.rows import dict_row

        ConnectionPool = _require_pool()
        self._acquire_timeout = acquire_timeout
        self._retrieval_metadata_cache: Optional[Dict[str, Any]] = None
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=acquire_timeout,
            max_idle=60.0,
            max_lifetime=1800.0,
            kwargs={
                "connect_timeout": connect_timeout,
                "row_factory": dict_row,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
                "options": (
                    "-c default_transaction_read_only=on "
                    "-c statement_timeout=%d" % statement_timeout_ms
                ),
            },
            open=True,
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        try:
            with self._pool.connection(timeout=self._acquire_timeout) as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    yield connection
        except Exception as error:
            from psycopg import Error as PsycopgError
            from psycopg_pool import PoolTimeout

            if isinstance(error, (PsycopgError, PoolTimeout)):
                raise ReadStoreUnavailable(
                    "PostgreSQL read is temporarily unavailable"
                ) from None
            raise

    def close(self) -> None:
        self._retrieval_metadata_cache = None
        self._pool.close()

    def initialize(self) -> None:
        readiness = self.readiness()
        if not readiness["ready"]:
            raise RuntimeError("PostgreSQL read schema is not ready")

    def readiness(self) -> Dict[str, Any]:
        try:
            with self._connection() as connection:
                migration = connection.execute(
                    """SELECT EXISTS(
                           SELECT 1 FROM hksr_meta.schema_migrations
                           WHERE name = '006_m10_chunked_retrieval_metadata.sql'
                       ) AND EXISTS(
                           SELECT 1 FROM hksr.retrieval_metadata m
                           WHERE m.key = 'semantic'
                             AND m.value->>'storage' = 'gzip_chunks_v1'
                             AND (m.value->>'chunk_count')::integer = (
                                 SELECT count(*) FROM hksr.retrieval_metadata_chunks c
                                 WHERE c.metadata_key = m.key
                             )
                       ) AS ready"""
                ).fetchone()
                latest = connection.execute(
                    """SELECT source_fingerprint FROM hksr.import_batches
                       ORDER BY imported_at DESC, batch_id DESC LIMIT 1"""
                ).fetchone()
            stats = self._pool.get_stats()
            return {
                "backend": self.backend_name,
                "ready": bool(migration and migration["ready"]),
                "mutable": self.mutable,
                "schema": "006_m10_chunked_retrieval_metadata.sql"
                if migration and migration["ready"] else None,
                "corpus_fingerprint": latest["source_fingerprint"] if latest else None,
                "pool": {
                    "size": int(stats.get("pool_size", 0)),
                    "available": int(stats.get("pool_available", 0)),
                    "waiting": int(stats.get("requests_waiting", 0)),
                },
            }
        except Exception:
            return {
                "backend": self.backend_name,
                "ready": False,
                "mutable": self.mutable,
                "error": "database_unavailable",
            }

    @staticmethod
    def _source(row: Mapping[str, Any]) -> Dict[str, Any]:
        metadata = row.get("metadata") or {}
        return {
            "id": int(row["id"]),
            "provider": row["provider"],
            "external_id": row["external_id"],
            "source_kind": row["source_kind"],
            "parser": metadata.get("parser", ""),
            "page_url": row["page_url"],
            "api_url": "",
            "headers_json": "{}",
            "expected_title": metadata.get("expected_title", ""),
            "title": row["title"],
            "version": row["version"],
            "remote_created_at": metadata.get("remote_created_at"),
            "remote_updated_at": metadata.get("remote_updated_at"),
            "official_status": row["official_status"],
            "status": row["status"],
            "raw_path": None,
            "raw_sha256": metadata.get("raw_sha256"),
            "content_sha256": row["content_sha256"],
            "raw_byte_count": metadata.get("raw_byte_count"),
            "discovered_at": str(row["discovered_at"]),
            "fetched_at": str(row["fetched_at"]) if row["fetched_at"] else None,
            "parsed_at": str(row["parsed_at"]) if row["parsed_at"] else None,
            "last_error": None,
        }

    def get_source(self, source_id: int) -> Dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT COALESCE(sqlite_id, id) AS id, provider, external_id,
                          source_kind, page_url, title, version, official_status,
                          status, content_sha256, metadata, discovered_at, fetched_at, parsed_at
                   FROM hksr.sources WHERE COALESCE(sqlite_id, id) = %s""",
                (source_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown source id: %d" % source_id)
        return self._source(row)

    def list_sources(
        self, statuses: Optional[Sequence[str]] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = """SELECT COALESCE(sqlite_id, id) AS id, provider, external_id,
                          source_kind, page_url, title, version, official_status,
                          status, content_sha256, metadata, discovered_at, fetched_at, parsed_at
                   FROM hksr.sources"""
        parameters: List[Any] = []
        if statuses:
            query += " WHERE status = ANY(%s)"
            parameters.append(list(statuses))
        query += " ORDER BY COALESCE(sqlite_id, id)"
        if limit is not None:
            query += " LIMIT %s"
            parameters.append(int(limit))
        with self._connection() as connection:
            return [self._source(row) for row in connection.execute(query, parameters).fetchall()]

    def source_detail(self, source_id: int) -> Dict[str, Any]:
        source = self.get_source(source_id)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(d.sqlite_id, d.id) AS id, d.document_key, d.title,
                          d.section_path, d.content_type, d.position, d.evidence_eligible,
                          d.metadata, count(c.id) AS chunk_count
                   FROM hksr.documents d LEFT JOIN hksr.chunks c ON c.document_id = d.id
                   JOIN hksr.sources s ON s.id = d.source_id
                   WHERE COALESCE(s.sqlite_id, s.id) = %s
                   GROUP BY d.id ORDER BY d.position""",
                (source_id,),
            ).fetchall()
        documents = []
        for row in rows:
            item = dict(row)
            item["id"] = int(item["id"])
            item["evidence_eligible"] = int(bool(item["evidence_eligible"]))
            item["metadata_json"] = json.dumps(item.pop("metadata") or {}, ensure_ascii=False)
            item["chunk_count"] = int(item["chunk_count"])
            documents.append(item)
        allowed = (
            "id", "provider", "external_id", "source_kind", "page_url", "title",
            "version", "remote_created_at", "remote_updated_at", "official_status",
            "status", "fetched_at", "parsed_at", "last_error",
        )
        return {"source": {key: source[key] for key in allowed}, "documents": documents}

    def entity_catalog(self) -> List[Dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(e.sqlite_id, e.id) AS id, e.canonical_name,
                          e.entity_type, e.description, a.alias, a.alias_type
                   FROM hksr.entities e LEFT JOIN hksr.aliases a ON a.entity_id=e.id
                   ORDER BY COALESCE(e.sqlite_id, e.id), a.alias"""
            ).fetchall()
        output: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            entity_id = int(row["id"])
            entity = output.setdefault(entity_id, {
                "id": entity_id,
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"],
                "description": row["description"],
                "aliases": [],
            })
            if row["alias"]:
                entity["aliases"].append({
                    "text": row["alias"], "alias_type": row["alias_type"]
                })
        return list(output.values())

    def retrieval_metadata(self) -> Dict[str, Any]:
        if self._retrieval_metadata_cache is not None:
            return self._retrieval_metadata_cache
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM hksr.retrieval_metadata WHERE key='semantic'"
            ).fetchone()
            if not row:
                return {}
            descriptor = dict(row["value"])
            if descriptor.get("storage") != "gzip_chunks_v1":
                self._retrieval_metadata_cache = descriptor
                return descriptor
            payload_rows = connection.execute(
                """SELECT ordinal, payload FROM hksr.retrieval_metadata_chunks
                   WHERE metadata_key='semantic' ORDER BY ordinal"""
            ).fetchall()
        metadata = _decode_chunked_metadata(descriptor, payload_rows)
        self._retrieval_metadata_cache = metadata
        return metadata

    def search(
        self, query: str, limit: int = 10,
        source_kinds: Optional[Sequence[str]] = None, version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        literal = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%%%s%%" % literal
        filters = ["d.evidence_eligible", "s.status='parsed'"]
        parameters: List[Any] = [pattern, pattern, pattern]
        if source_kinds:
            filters.append("s.source_kind = ANY(%s)")
            parameters.append(list(source_kinds))
        if version is not None:
            filters.append("COALESCE(s.version, '') = %s")
            parameters.append(str(version))
        parameters.append(int(limit))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(c.sqlite_id, c.id) AS chunk_id,
                          COALESCE(d.sqlite_id, d.id) AS document_id,
                          COALESCE(s.sqlite_id, s.id) AS source_id,
                          c.section_path, c.speaker, c.text, 0.0 AS score,
                          s.title, s.page_url, s.source_kind
                   FROM hksr.chunks c
                   JOIN hksr.documents d ON d.id=c.document_id
                   JOIN hksr.sources s ON s.id=d.source_id
                   WHERE (c.text ILIKE %s ESCAPE '\\' OR c.section_path ILIKE %s ESCAPE '\\'
                          OR COALESCE(c.speaker, '') ILIKE %s ESCAPE '\\') AND """
                + " AND ".join(filters)
                + " ORDER BY ((length(lower(c.text))-length(replace(lower(c.text),lower(%s),''))) / greatest(length(%s),1)) DESC, c.evidence_id LIMIT %s",
                [*parameters[:-1], query, query, parameters[-1]],
            ).fetchall()
        return [dict(row) for row in rows]

    def entity_chunk_ids(
        self, entity_ids: Sequence[int], limit: int = 200,
        source_kinds: Optional[Sequence[str]] = None, version: Optional[str] = None,
    ) -> List[int]:
        selected = list(dict.fromkeys(int(item) for item in entity_ids))
        if not selected or limit <= 0:
            return []
        filters = ["COALESCE(e.sqlite_id, e.id) = ANY(%s)",
                   "d.evidence_eligible", "s.status='parsed'"]
        parameters: List[Any] = [selected]
        if source_kinds:
            filters.append("s.source_kind = ANY(%s)")
            parameters.append(list(source_kinds))
        if version is not None:
            filters.append("COALESCE(s.version, '') = %s")
            parameters.append(str(version))
        parameters.append(int(limit))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(c.sqlite_id, c.id) AS chunk_id,
                          count(*) AS matched_entities
                   FROM hksr.entity_chunks ec
                   JOIN hksr.entities e ON e.id=ec.entity_id
                   JOIN hksr.chunks c ON c.id=ec.chunk_id
                   JOIN hksr.documents d ON d.id=c.document_id
                   JOIN hksr.sources s ON s.id=d.source_id
                   WHERE """ + " AND ".join(filters) +
                """ GROUP BY c.id, s.source_kind
                    ORDER BY matched_entities DESC,
                             CASE
                               WHEN s.source_kind = 'wiki_character' THEN 0
                               WHEN s.source_kind = 'wiki_quest' THEN 1
                               WHEN s.source_kind LIKE 'wiki_%%' THEN 2
                               WHEN s.source_kind = 'official_article' THEN 3
                               WHEN s.source_kind = 'official_video' THEN 4
                               ELSE 5
                             END,
                             c.evidence_id LIMIT %s""",
                parameters,
            ).fetchall()
        return [int(row["chunk_id"]) for row in rows]

    def retrieval_rows(
        self, chunk_ids: Optional[Sequence[int]] = None
    ) -> List[Dict[str, Any]]:
        selected = None if chunk_ids is None else list(dict.fromkeys(int(item) for item in chunk_ids))
        if selected == []:
            return []
        where = ""
        parameters: List[Any] = []
        if selected is not None:
            where = " AND COALESCE(c.sqlite_id, c.id) = ANY(%s)"
            parameters.append(selected)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(c.sqlite_id, c.id) AS chunk_id, c.text, c.section_path,
                          c.speaker, c.chunk_key, c.position AS chunk_position,
                          COALESCE(d.sqlite_id, d.id) AS document_id, d.document_key,
                          COALESCE(s.sqlite_id, s.id) AS source_id, s.provider, s.external_id,
                          s.title, s.page_url, s.source_kind, s.version, s.official_status,
                          v.vector_json, v.norm, c.evidence_id
                   FROM hksr.chunks c
                   JOIN hksr.documents d ON d.id=c.document_id
                   JOIN hksr.sources s ON s.id=d.source_id
                   LEFT JOIN hksr.chunk_vectors v ON v.chunk_id=c.id
                   WHERE d.evidence_eligible AND s.status='parsed'""" + where +
                " ORDER BY c.evidence_id",
                parameters,
            ).fetchall()
            entity_rows = connection.execute(
                """SELECT COALESCE(c.sqlite_id, c.id) AS chunk_id,
                          COALESCE(e.sqlite_id, e.id) AS id, e.canonical_name,
                          e.entity_type, ec.matched_text
                   FROM hksr.entity_chunks ec JOIN hksr.entities e ON e.id=ec.entity_id
                   JOIN hksr.chunks c ON c.id=ec.chunk_id""" +
                (" WHERE COALESCE(c.sqlite_id, c.id) = ANY(%s)" if selected is not None else "") +
                " ORDER BY c.evidence_id, COALESCE(e.sqlite_id, e.id)",
                parameters,
            ).fetchall()
        entities: Dict[int, List[Dict[str, Any]]] = {}
        for row in entity_rows:
            entities.setdefault(int(row["chunk_id"]), []).append({
                "id": int(row["id"]), "name": row["canonical_name"],
                "type": row["entity_type"], "matched_text": row["matched_text"],
            })
        output = []
        for row in rows:
            item = dict(row)
            item["chunk_id"] = int(item["chunk_id"])
            item["document_id"] = int(item["document_id"])
            item["source_id"] = int(item["source_id"])
            vector = item.pop("vector_json")
            item["vector"] = dict(vector) if vector else {}
            item["norm"] = float(item["norm"] or 0.0)
            item["entities"] = entities.get(item["chunk_id"], [])
            output.append(item)
        return output

    def retrieval_rows_by_evidence_ids(self, evidence_ids: Sequence[str]) -> List[Dict[str, Any]]:
        selected = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
        if not selected:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT COALESCE(sqlite_id, id) AS chunk_id FROM hksr.chunks WHERE evidence_id = ANY(%s)",
                (selected,),
            ).fetchall()
        return self.retrieval_rows([int(row["chunk_id"]) for row in rows])

    def evidence_ids(self) -> set[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT c.evidence_id FROM hksr.chunks c
                   JOIN hksr.documents d ON d.id=c.document_id
                   JOIN hksr.sources s ON s.id=d.source_id
                   WHERE d.evidence_eligible AND s.status='parsed'"""
            ).fetchall()
        return {str(row["evidence_id"]) for row in rows}

    def evidence_match_rows(self) -> List[Dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.provider, s.external_id, c.evidence_id, c.text
                   FROM hksr.chunks c JOIN hksr.documents d ON d.id=c.document_id
                   JOIN hksr.sources s ON s.id=d.source_id
                   WHERE d.evidence_eligible AND s.status='parsed'
                   ORDER BY c.evidence_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def evidence_context(self, evidence_id: str, window: int = 1) -> Dict[str, Any]:
        if window < 0:
            raise ValueError("Context window cannot be negative")
        rows = self.retrieval_rows_by_evidence_ids([evidence_id])
        if not rows:
            raise KeyError("Unknown evidence id: %s" % evidence_id)
        target = rows[0]
        with self._connection() as connection:
            neighbours = connection.execute(
                """SELECT c.evidence_id, c.chunk_key, c.position, c.text
                   FROM hksr.chunks c JOIN hksr.documents d ON d.id=c.document_id
                   WHERE COALESCE(d.sqlite_id, d.id)=%s AND c.position BETWEEN %s AND %s
                   ORDER BY c.position""",
                (
                    target["document_id"],
                    max(0, int(target["chunk_position"]) - window),
                    int(target["chunk_position"]) + window,
                ),
            ).fetchall()
        context = [{
            "evidence_id": row["evidence_id"], "position": int(row["position"]),
            "text": row["text"], "is_target": row["chunk_key"] == target["chunk_key"],
        } for row in neighbours]
        return {
            **{key: value for key, value in target.items() if key not in {"vector", "norm"}},
            "context": context,
        }

    def statistics(self) -> Dict[str, Any]:
        count_queries = {
            "sources": "SELECT count(*) AS count FROM hksr.sources",
            "documents": "SELECT count(*) AS count FROM hksr.documents",
            "chunks": "SELECT count(*) AS count FROM hksr.chunks",
            "eligible_documents": "SELECT count(*) AS count FROM hksr.documents WHERE evidence_eligible",
            "entities": "SELECT count(*) AS count FROM hksr.entities",
            "aliases": "SELECT count(*) AS count FROM hksr.aliases",
            "entity_chunk_links": "SELECT count(*) AS count FROM hksr.entity_chunks",
            "semantic_vectors": "SELECT count(*) AS count FROM hksr.chunk_vectors",
            "relations": "SELECT count(*) AS count FROM hksr.relations",
            "approved_relations": "SELECT count(*) AS count FROM hksr.relations WHERE review_status='approved' AND NOT is_stale",
            "pending_relations": "SELECT count(*) AS count FROM hksr.relations WHERE review_status='pending'",
            "fts_rows": """SELECT count(*) AS count FROM hksr.chunks c
                            JOIN hksr.documents d ON d.id=c.document_id
                            JOIN hksr.sources s ON s.id=d.source_id
                            WHERE d.evidence_eligible AND s.status='parsed'""",
        }
        with self._connection() as connection:
            counts = {
                key: int(connection.execute(query).fetchone()["count"])
                for key, query in count_queries.items()
            }
            statuses = connection.execute(
                "SELECT status, count(*) AS count FROM hksr.sources GROUP BY status ORDER BY status"
            ).fetchall()
        return {
            "counts": counts,
            "source_statuses": {row["status"]: int(row["count"]) for row in statuses},
            "database_path": "postgresql:[redacted]",
            "backend": self.backend_name,
        }

    def catalog_metadata(self) -> Dict[str, Any]:
        with self._connection() as connection:
            statuses = connection.execute(
                "SELECT status, count(*) AS count FROM hksr.sources GROUP BY status ORDER BY status"
            ).fetchall()
            kinds = connection.execute(
                """SELECT source_kind AS value, count(*) AS count FROM hksr.sources
                   WHERE status='parsed' GROUP BY source_kind ORDER BY source_kind"""
            ).fetchall()
            versions = connection.execute(
                """SELECT version AS value, count(*) AS count FROM hksr.sources
                   WHERE status='parsed' AND version IS NOT NULL AND btrim(version) != ''
                   GROUP BY version ORDER BY version"""
            ).fetchall()
            counts = connection.execute(
                """SELECT (SELECT count(*) FROM hksr.sources) AS sources,
                          (SELECT count(*) FROM hksr.documents) AS documents,
                          (SELECT count(*) FROM hksr.chunks) AS chunks,
                          (SELECT count(*) FROM hksr.documents WHERE evidence_eligible)
                            AS eligible_documents"""
            ).fetchone()
        return {
            "counts": {key: int(value) for key, value in counts.items()},
            "source_statuses": {row["status"]: int(row["count"]) for row in statuses},
            "source_kinds": [{"value": row["value"], "count": int(row["count"])} for row in kinds],
            "versions": [{"value": row["value"], "count": int(row["count"])} for row in versions],
        }

    def identity_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        with self._connection() as connection:
            people = connection.execute(
                "SELECT * FROM hksr.narrative_people ORDER BY canonical_name"
            ).fetchall()
            forms = connection.execute(
                """SELECT pf.stable_key, pf.narrative_person_key,
                          COALESCE(e.sqlite_id, e.id) AS entity_id, pf.canonical_name,
                          pf.form_kind, pf.link_status, pf.evidence_id, pf.schema_version
                   FROM hksr.playable_forms pf JOIN hksr.entities e ON e.id=pf.entity_id
                   ORDER BY pf.narrative_person_key,
                     CASE pf.form_kind WHEN 'base' THEN 0 ELSE 1 END, pf.canonical_name"""
            ).fetchall()
            names = connection.execute(
                """SELECT owner_kind, owner_key, name, name_type, is_official,
                          evidence_id, schema_version FROM hksr.identity_names
                   ORDER BY owner_kind, owner_key, name_type, name"""
            ).fetchall()
        return {
            "people": [dict(row) for row in people],
            "forms": [dict(row) for row in forms],
            "names": [dict(row) for row in names],
        }

    def relation_audit(self, *, update: bool = False) -> Dict[str, Any]:
        if update:
            raise PermissionError("Relation audit updates are disabled for PostgreSQL reads")
        current = self.evidence_ids()
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(r.sqlite_id, r.id) AS id, re.evidence_id
                   FROM hksr.relations r LEFT JOIN hksr.relation_evidence re ON re.relation_id=r.id
                   ORDER BY COALESCE(r.sqlite_id, r.id), re.evidence_id"""
            ).fetchall()
        evidence_by_relation: Dict[int, List[str]] = {}
        for row in rows:
            evidence_by_relation.setdefault(int(row["id"]), [])
            if row["evidence_id"]:
                evidence_by_relation[int(row["id"])].append(str(row["evidence_id"]))
        stale = [
            relation_id for relation_id, evidence in evidence_by_relation.items()
            if not evidence or any(item not in current for item in evidence)
        ]
        return {"relations": len(evidence_by_relation), "stale": len(stale), "stale_ids": stale}

    def relation_rows(
        self, entity_name: Optional[str] = None, *, include_candidates: bool = False
    ) -> List[Dict[str, Any]]:
        conditions = [
            "r.review_status IN ('approved','pending')" if include_candidates
            else "r.review_status='approved'"
        ]
        parameters: List[Any] = []
        if entity_name:
            conditions.append("(se.canonical_name=%s OR oe.canonical_name=%s)")
            parameters.extend([entity_name, entity_name])
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT COALESCE(r.sqlite_id, r.id) AS id,
                          COALESCE(se.sqlite_id, se.id) AS subject_id, r.predicate,
                          COALESCE(oe.sqlite_id, oe.id) AS object_id, r.evidence_level,
                          r.review_status, r.confidence, r.reasoning, r.origin, r.is_stale,
                          se.canonical_name AS subject_name, se.entity_type AS subject_type,
                          oe.canonical_name AS object_name, oe.entity_type AS object_type,
                          array_remove(array_agg(re.evidence_id ORDER BY re.evidence_id), NULL)
                            AS evidence_ids
                   FROM hksr.relations r
                   JOIN hksr.entities se ON se.id=r.subject_id
                   JOIN hksr.entities oe ON oe.id=r.object_id
                   LEFT JOIN hksr.relation_evidence re ON re.relation_id=r.id
                   WHERE """ + " AND ".join(conditions) +
                " GROUP BY r.id, se.id, oe.id ORDER BY r.review_status, se.canonical_name, r.predicate, oe.canonical_name",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def approved_relation_evidence_ids(self, left: int, right: int) -> set[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT re.evidence_id FROM hksr.relations r
                   JOIN hksr.entities se ON se.id=r.subject_id
                   JOIN hksr.entities oe ON oe.id=r.object_id
                   JOIN hksr.relation_evidence re ON re.relation_id=r.id
                   WHERE r.review_status='approved' AND NOT r.is_stale
                     AND ((COALESCE(se.sqlite_id,se.id)=%s AND COALESCE(oe.sqlite_id,oe.id)=%s)
                       OR (COALESCE(se.sqlite_id,se.id)=%s AND COALESCE(oe.sqlite_id,oe.id)=%s))""",
                (left, right, right, left),
            ).fetchall()
        return {str(row["evidence_id"]) for row in rows}

    def corpus_snapshot_rows(self) -> Dict[str, Any]:
        queries = {
            "sources": """SELECT provider, external_id, source_kind, status, official_status,
                                  COALESCE(version,'') AS version,
                                  COALESCE(content_sha256,'') AS content_sha256
                           FROM hksr.sources ORDER BY provider, external_id""",
            "documents": """SELECT s.provider, s.external_id, d.document_key,
                                    d.evidence_eligible::integer AS evidence_eligible
                               FROM hksr.documents d
                               JOIN hksr.sources s ON s.id=d.source_id
                               ORDER BY s.provider, s.external_id, d.document_key""",
            "chunks": """SELECT s.provider, s.external_id, d.document_key, c.chunk_key,
                                 c.content_sha256,
                                 d.evidence_eligible::integer AS evidence_eligible, s.status
                          FROM hksr.chunks c JOIN hksr.documents d ON d.id=c.document_id
                          JOIN hksr.sources s ON s.id=d.source_id
                          ORDER BY s.provider, s.external_id, d.document_key, c.chunk_key""",
            "entities": """SELECT canonical_name, entity_type, description
                            FROM hksr.entities ORDER BY entity_type, canonical_name""",
            "aliases": """SELECT e.canonical_name, e.entity_type, a.alias, a.alias_type
                           FROM hksr.aliases a JOIN hksr.entities e ON e.id=a.entity_id
                           ORDER BY e.entity_type, e.canonical_name, a.alias""",
            "relations": """SELECT se.canonical_name AS subject, r.predicate,
                             oe.canonical_name AS object, r.evidence_level,
                             r.review_status, r.is_stale::integer AS is_stale
                             FROM hksr.relations r
                             JOIN hksr.entities se ON se.id=r.subject_id
                             JOIN hksr.entities oe ON oe.id=r.object_id
                             ORDER BY subject, r.predicate, object""",
        }
        with self._connection() as connection:
            output = {
                key: [dict(row) for row in connection.execute(query).fetchall()]
                for key, query in queries.items()
            }
            output["semantic_vectors"] = int(connection.execute(
                "SELECT count(*) AS count FROM hksr.chunk_vectors"
            ).fetchone()["count"])
        return output

    def source_disposition_rows(self) -> List[Dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.provider, s.external_id, sd.disposition, sd.reason,
                          sd.classifier_version, sd.verified
                   FROM hksr.source_dispositions sd
                   JOIN hksr.sources s ON s.id=sd.source_id
                   ORDER BY s.provider, s.external_id"""
            ).fetchall()
        return [dict(row) for row in rows]


class SQLiteReadStore:
    """Behavior-preserving read facade over the mutable SQLite database."""

    backend_name = "sqlite"
    mutable = False

    def __init__(self, database: Any) -> None:
        self._database = database

    def __getattr__(self, name: str) -> Any:
        return getattr(self._database, name)

    def initialize(self) -> None:
        self._database.initialize()

    def readiness(self) -> Dict[str, Any]:
        readiness = self._database.readiness()
        return {**readiness, "mutable": self.mutable}
