"""SQLite persistence for sources, documents, chunks, and local FTS."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    parser TEXT NOT NULL,
    page_url TEXT NOT NULL,
    api_url TEXT NOT NULL,
    headers_json TEXT NOT NULL DEFAULT '{}',
    expected_title TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    version TEXT,
    remote_created_at TEXT,
    remote_updated_at TEXT,
    official_status TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'discovered',
    raw_path TEXT,
    raw_sha256 TEXT,
    content_sha256 TEXT,
    raw_byte_count INTEGER,
    discovered_at TEXT NOT NULL,
    fetched_at TEXT,
    parsed_at TEXT,
    last_error TEXT,
    UNIQUE(provider, external_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    document_key TEXT NOT NULL,
    title TEXT NOT NULL,
    section_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    position INTEGER NOT NULL,
    evidence_eligible INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_id, document_key)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_key TEXT NOT NULL,
    section_path TEXT NOT NULL,
    speaker TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    position INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(document_id, chunk_key)
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(canonical_name, entity_type)
);

CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'official',
    UNIQUE(entity_id, alias)
);

CREATE TABLE IF NOT EXISTS entity_chunks (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    matched_text TEXT NOT NULL,
    PRIMARY KEY(entity_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    vector_json TEXT NOT NULL,
    norm REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,
    object_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    evidence_level TEXT NOT NULL,
    review_status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    reasoning TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'curated',
    is_stale INTEGER NOT NULL DEFAULT 0,
    UNIQUE(subject_id, predicate, object_id, origin)
);

CREATE TABLE IF NOT EXISTS relation_evidence (
    relation_id INTEGER NOT NULL REFERENCES relations(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(relation_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id, position);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, position);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_entity_chunks_chunk ON entity_chunks(chunk_id);
CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id, review_status);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_id, review_status);
"""

SQLITE_MIGRATIONS = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS collection_runs (
            run_id TEXT PRIMARY KEY,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            report_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS account_checkpoints (
            account_uid TEXT PRIMARY KEY,
            next_cursor TEXT NOT NULL DEFAULT '',
            terminal INTEGER NOT NULL DEFAULT 0,
            observed_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            terminal_at TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_request_budgets (
            budget_date TEXT PRIMARY KEY,
            request_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_dispositions (
            source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
            disposition TEXT NOT NULL,
            reason TEXT NOT NULL,
            classifier_version TEXT NOT NULL,
            verified INTEGER NOT NULL,
            reviewed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fetch_attempts (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES collection_runs(run_id) ON DELETE CASCADE,
            source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
            attempt INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            http_status INTEGER,
            wait_seconds REAL NOT NULL DEFAULT 0,
            error_type TEXT,
            attempted_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS raw_object_manifests (
            source_id INTEGER PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
            raw_sha256 TEXT NOT NULL,
            raw_byte_count INTEGER NOT NULL,
            local_path TEXT NOT NULL,
            object_key TEXT NOT NULL,
            etag TEXT,
            object_version TEXT,
            persisted_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dispositions_state
            ON source_dispositions(disposition, verified);
        CREATE INDEX IF NOT EXISTS idx_fetch_attempts_run
            ON fetch_attempts(run_id, id);
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS wiki_refresh_checkpoints (
            catalog_key TEXT PRIMARY KEY,
            cycle_id TEXT NOT NULL,
            after_source_id INTEGER NOT NULL DEFAULT 0,
            max_source_id INTEGER NOT NULL DEFAULT 0,
            terminal INTEGER NOT NULL DEFAULT 0,
            checked_count INTEGER NOT NULL DEFAULT 0,
            changed_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS narrative_people (
            stable_key TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            schema_version INTEGER NOT NULL,
            UNIQUE(canonical_name)
        );
        CREATE TABLE IF NOT EXISTS playable_forms (
            stable_key TEXT PRIMARY KEY,
            narrative_person_key TEXT NOT NULL
                REFERENCES narrative_people(stable_key) ON DELETE RESTRICT,
            entity_id INTEGER NOT NULL UNIQUE
                REFERENCES entities(id) ON DELETE RESTRICT,
            canonical_name TEXT NOT NULL,
            form_kind TEXT NOT NULL CHECK(form_kind IN ('base', 'alternate')),
            link_status TEXT NOT NULL CHECK(link_status IN ('approved', 'pending', 'rejected')),
            evidence_id TEXT,
            schema_version INTEGER NOT NULL,
            UNIQUE(narrative_person_key, canonical_name)
        );
        CREATE TABLE IF NOT EXISTS identity_names (
            id INTEGER PRIMARY KEY,
            owner_kind TEXT NOT NULL CHECK(owner_kind IN ('person', 'form')),
            owner_key TEXT NOT NULL,
            name TEXT NOT NULL,
            name_type TEXT NOT NULL CHECK(name_type IN (
                'canonical', 'official_alias', 'punctuation_variant', 'player_shorthand'
            )),
            is_official INTEGER NOT NULL CHECK(is_official IN (0, 1)),
            evidence_id TEXT,
            schema_version INTEGER NOT NULL,
            UNIQUE(owner_kind, owner_key, name)
        );
        CREATE INDEX IF NOT EXISTS idx_playable_forms_person
            ON playable_forms(narrative_person_key, link_status);
        CREATE INDEX IF NOT EXISTS idx_identity_names_name
            ON identity_names(name, owner_kind);
        """,
    ),
    (
        4,
        """
        INSERT INTO source_dispositions(
            source_id, disposition, reason, classifier_version, verified, updated_at
        )
        SELECT s.id, 'eligible_evidence', 'pre_m7_verified_wiki_content',
               'm7-v1', 1, COALESCE(s.parsed_at, s.discovered_at)
        FROM sources s
        WHERE s.provider = 'mihoyo_wiki'
          AND s.official_status IN ('verified', 'wiki')
          AND s.status = 'parsed'
          AND NOT EXISTS (
              SELECT 1 FROM source_dispositions d WHERE d.source_id = s.id
          );
        """,
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_evidence_id(
    provider: str, external_id: str, document_key: str, chunk_key: str
) -> str:
    """Build a stable citation identifier without relying on SQLite row IDs."""
    return "%s:%s:%s:%s" % (provider, external_id, document_key, chunk_key)


class Database:
    backend_name = "sqlite"
    mutable = True

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._retrieval_metadata_cache: Optional[Dict[str, Any]] = None
        self._retrieval_metadata_signature: Optional[tuple[tuple[int, int], ...]] = None

    def _storage_signature(self) -> tuple[tuple[int, int], ...]:
        signature = []
        for path in (self.path, Path(str(self.path) + "-wal")):
            try:
                stat = path.stat()
                signature.append((stat.st_mtime_ns, stat.st_size))
            except FileNotFoundError:
                signature.append((0, 0))
        return tuple(signature)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(sources)")
            }
            if "content_sha256" not in columns:
                connection.execute("ALTER TABLE sources ADD COLUMN content_sha256 TEXT")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS hksr_sqlite_migrations (
                       version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                   )"""
            )
            applied = {
                int(row[0]) for row in connection.execute(
                    "SELECT version FROM hksr_sqlite_migrations"
                )
            }
            for version, sql in SQLITE_MIGRATIONS:
                if version not in applied:
                    connection.executescript(sql)
                    connection.execute(
                        "INSERT INTO hksr_sqlite_migrations(version, applied_at) VALUES (?, ?)",
                        (version, utc_now()),
                    )
            fts_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
            ).fetchone()
            if fts_exists:
                try:
                    connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()
                except sqlite3.OperationalError as error:
                    if "no such tokenizer" not in str(error).lower():
                        raise
                    self._reset_fts(connection)

    def replace_entities(self, entities: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
        """Replace the small curated entity catalogue and relink all chunks."""
        self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM entity_chunks")
            connection.execute("DELETE FROM aliases")
            entity_count = 0
            alias_count = 0
            retained_ids = []
            for entity in entities:
                connection.execute(
                    """
                    INSERT INTO entities (canonical_name, entity_type, description) VALUES (?, ?, ?)
                    ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
                        description = excluded.description
                    """,
                    (
                        entity["canonical_name"],
                        entity["entity_type"],
                        entity.get("description", ""),
                    ),
                )
                entity_id = int(connection.execute(
                    "SELECT id FROM entities WHERE canonical_name = ? AND entity_type = ?",
                    (entity["canonical_name"], entity["entity_type"]),
                ).fetchone()["id"])
                retained_ids.append(entity_id)
                entity_count += 1
                names = [(entity["canonical_name"], "canonical")]
                names.extend(
                    (item["text"], item.get("alias_type", "official"))
                    if isinstance(item, Mapping)
                    else (str(item), "official")
                    for item in entity.get("aliases", [])
                )
                seen = set()
                for alias, alias_type in names:
                    if not alias or alias in seen:
                        continue
                    seen.add(alias)
                    connection.execute(
                        "INSERT INTO aliases (entity_id, alias, alias_type) VALUES (?, ?, ?)",
                        (entity_id, alias, alias_type),
                    )
                    alias_count += 1

            if retained_ids:
                identity_entity_ids = [
                    int(row[0]) for row in connection.execute(
                        "SELECT entity_id FROM playable_forms"
                    )
                ]
                retained_ids = sorted(set(retained_ids + identity_entity_ids))
                placeholders = ",".join("?" for _ in retained_ids)
                connection.execute(
                    "DELETE FROM entities WHERE id NOT IN (%s)" % placeholders,
                    retained_ids,
                )
            else:
                identity_entity_ids = [
                    int(row[0]) for row in connection.execute(
                        "SELECT entity_id FROM playable_forms"
                    )
                ]
                if identity_entity_ids:
                    placeholders = ",".join("?" for _ in identity_entity_ids)
                    connection.execute(
                        "DELETE FROM entities WHERE id NOT IN (%s)" % placeholders,
                        identity_entity_ids,
                    )
                else:
                    connection.execute("DELETE FROM entities")

            # Identity-owned names are authoritative for playable forms and must
            # survive a legacy entity-index rebuild.
            identity_names = connection.execute(
                """SELECT pf.entity_id, n.name, n.name_type
                   FROM playable_forms pf JOIN identity_names n
                     ON n.owner_kind='form' AND n.owner_key=pf.stable_key"""
            ).fetchall()
            for name in identity_names:
                connection.execute(
                    """INSERT INTO aliases(entity_id, alias, alias_type) VALUES (?, ?, ?)
                       ON CONFLICT(entity_id, alias) DO UPDATE SET alias_type=excluded.alias_type""",
                    (name["entity_id"], name["name"],
                     "player" if name["name_type"] == "player_shorthand" else name["name_type"]),
                )

            rows = connection.execute(
                """
                SELECT c.id, c.text, c.section_path, s.title AS source_title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = d.source_id
                """
            ).fetchall()
            aliases = connection.execute(
                "SELECT entity_id, alias FROM aliases ORDER BY length(alias) DESC"
            ).fetchall()
            links = set()
            for chunk in rows:
                searchable = "%s %s %s" % (
                    chunk["source_title"], chunk["section_path"], chunk["text"]
                )
                for alias in aliases:
                    value = alias["alias"]
                    if len(value) >= 2 and value in searchable:
                        key = (int(alias["entity_id"]), int(chunk["id"]))
                        if key not in links:
                            connection.execute(
                                "INSERT INTO entity_chunks (entity_id, chunk_id, matched_text) VALUES (?, ?, ?)",
                                (key[0], key[1], value),
                            )
                            links.add(key)
            return {
                "entities": entity_count,
                "aliases": alias_count,
                "chunk_links": len(links),
            }

    def entity_catalog(self) -> List[Dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id, e.canonical_name, e.entity_type, e.description,
                       a.alias, a.alias_type
                FROM entities e LEFT JOIN aliases a ON a.entity_id = e.id
                ORDER BY e.id, a.alias
                """
            ).fetchall()
        output: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            entity = output.setdefault(
                int(row["id"]),
                {
                    "id": int(row["id"]),
                    "canonical_name": row["canonical_name"],
                    "entity_type": row["entity_type"],
                    "description": row["description"],
                    "aliases": [],
                },
            )
            if row["alias"]:
                entity["aliases"].append(
                    {"text": row["alias"], "alias_type": row["alias_type"]}
                )
        return list(output.values())

    def replace_vectors(
        self, vectors: Mapping[int, Mapping[str, float]], metadata: Mapping[str, Any]
    ) -> int:
        return self.replace_vector_stream(vectors.items(), metadata)

    def replace_vector_stream(
        self,
        vectors: Iterable[tuple[int, Mapping[str, float]]],
        metadata: Mapping[str, Any],
    ) -> int:
        """Replace semantic vectors without retaining the full corpus in memory."""
        serialized = (
            (
                chunk_id,
                json.dumps(vector, ensure_ascii=False),
                sum(weight * weight for weight in vector.values()) ** 0.5,
            )
            for chunk_id, vector in vectors
        )
        return self.replace_serialized_vector_stream(serialized, metadata)

    def replace_serialized_vector_stream(
        self,
        vectors: Iterable[tuple[int, str, float]],
        metadata: Mapping[str, Any],
    ) -> int:
        """Replace pre-serialized vectors after their source read transaction closes."""
        self.initialize()
        count = 0
        with self.connect() as connection:
            connection.execute("DELETE FROM chunk_vectors")
            for chunk_id, vector_json, norm in vectors:
                connection.execute(
                    "INSERT INTO chunk_vectors (chunk_id, vector_json, norm) VALUES (?, ?, ?)",
                    (chunk_id, vector_json, norm),
                )
                count += 1
            connection.execute(
                "INSERT OR REPLACE INTO retrieval_metadata (key, value_json) VALUES ('semantic', ?)",
                (json.dumps(metadata, ensure_ascii=False),),
            )
        self._retrieval_metadata_cache = None
        self._retrieval_metadata_signature = None
        return count

    def iter_indexable_chunks(self, batch_size: int = 500) -> Iterator[Dict[str, Any]]:
        """Yield only the text fields required to construct the semantic index."""
        self.initialize()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                SELECT c.id AS chunk_id, c.text, c.section_path, s.title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = d.source_id
                WHERE d.evidence_eligible = 1 AND s.status = 'parsed'
                ORDER BY c.id
                """
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    yield dict(row)

    def retrieval_rows(
        self, chunk_ids: Optional[Sequence[int]] = None
    ) -> List[Dict[str, Any]]:
        self.initialize()
        selected_ids = None
        if chunk_ids is not None:
            selected_ids = list(dict.fromkeys(int(chunk_id) for chunk_id in chunk_ids))
            if not selected_ids:
                return []
        row_filter = ""
        row_parameters: List[Any] = []
        entity_filter = ""
        entity_parameters: List[Any] = []
        if selected_ids is not None:
            placeholders = ",".join("?" for _ in selected_ids)
            row_filter = " AND c.id IN (%s)" % placeholders
            row_parameters.extend(selected_ids)
            entity_filter = " WHERE ec.chunk_id IN (%s)" % placeholders
            entity_parameters.extend(selected_ids)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id AS chunk_id, c.text, c.section_path, c.speaker,
                       c.chunk_key, c.position AS chunk_position,
                       d.id AS document_id, d.document_key,
                       s.id AS source_id, s.provider, s.external_id, s.title, s.page_url,
                       s.source_kind, s.version, s.official_status,
                       v.vector_json, v.norm
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = d.source_id
                LEFT JOIN chunk_vectors v ON v.chunk_id = c.id
                WHERE d.evidence_eligible = 1 AND s.status = 'parsed'
                """ + row_filter,
                row_parameters,
            ).fetchall()
            entity_rows = connection.execute(
                """
                SELECT ec.chunk_id, e.id, e.canonical_name, e.entity_type,
                       ec.matched_text
                FROM entity_chunks ec JOIN entities e ON e.id = ec.entity_id
                """ + entity_filter,
                entity_parameters,
            ).fetchall()
        entities: Dict[int, List[Dict[str, Any]]] = {}
        for row in entity_rows:
            entities.setdefault(int(row["chunk_id"]), []).append(
                {
                    "id": int(row["id"]),
                    "name": row["canonical_name"],
                    "type": row["entity_type"],
                    "matched_text": row["matched_text"],
                }
            )
        output = []
        for row in rows:
            item = dict(row)
            item["vector"] = json.loads(item.pop("vector_json")) if item["vector_json"] else {}
            item["entities"] = entities.get(int(item["chunk_id"]), [])
            item["evidence_id"] = stable_evidence_id(
                item["provider"], item["external_id"], item["document_key"], item["chunk_key"]
            )
            output.append(item)
        return output

    def entity_chunk_ids(
        self, entity_ids: Sequence[int], limit: int = 200,
        source_kinds: Optional[Sequence[str]] = None, version: Optional[str] = None,
    ) -> List[int]:
        selected_ids = list(dict.fromkeys(int(entity_id) for entity_id in entity_ids))
        if not selected_ids or limit <= 0:
            return []
        placeholders = ",".join("?" for _ in selected_ids)
        filters = ["ec.entity_id IN (%s)" % placeholders,
                   "d.evidence_eligible = 1", "s.status = 'parsed'"]
        parameters: List[Any] = list(selected_ids)
        if source_kinds:
            kind_placeholders = ",".join("?" for _ in source_kinds)
            filters.append("s.source_kind IN (%s)" % kind_placeholders)
            parameters.extend(source_kinds)
        if version is not None:
            filters.append("COALESCE(s.version, '') = ?")
            parameters.append(str(version))
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ec.chunk_id, COUNT(*) AS matched_entities
                FROM entity_chunks ec
                JOIN chunks c ON c.id = ec.chunk_id
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = d.source_id
                WHERE %s
                GROUP BY ec.chunk_id
                ORDER BY matched_entities DESC, ec.chunk_id
                LIMIT ?
                """ % " AND ".join(filters),
                [*parameters, int(limit)],
            ).fetchall()
        return [int(row["chunk_id"]) for row in rows]

    def evidence_ids(self) -> set[str]:
        """Return current evidence identifiers without loading texts or vectors."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.provider || ':' || s.external_id || ':' ||
                       d.document_key || ':' || c.chunk_key AS evidence_id
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = d.source_id
                WHERE d.evidence_eligible = 1 AND s.status = 'parsed'
                """
            ).fetchall()
        return {str(row["evidence_id"]) for row in rows}

    def retrieval_rows_by_evidence_ids(
        self, evidence_ids: Sequence[str]
    ) -> List[Dict[str, Any]]:
        """Load only rows addressed by stable evidence identifiers."""
        selected_ids = list(dict.fromkeys(str(item) for item in evidence_ids if str(item)))
        if not selected_ids:
            return []
        chunk_ids: List[int] = []
        with self.connect() as connection:
            for offset in range(0, len(selected_ids), 400):
                batch = selected_ids[offset : offset + 400]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    """
                    SELECT c.id AS chunk_id
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    JOIN sources s ON s.id = d.source_id
                    WHERE d.evidence_eligible = 1 AND s.status = 'parsed'
                      AND s.provider || ':' || s.external_id || ':' ||
                          d.document_key || ':' || c.chunk_key IN (%s)
                    """ % placeholders,
                    batch,
                ).fetchall()
                chunk_ids.extend(int(row["chunk_id"]) for row in rows)
        return self.retrieval_rows(chunk_ids)

    def evidence_context(self, evidence_id: str, window: int = 1) -> Dict[str, Any]:
        """Return one evidence item plus neighbouring chunks in its document."""
        if window < 0:
            raise ValueError("Context window cannot be negative")
        rows = self.retrieval_rows_by_evidence_ids([evidence_id])
        target = rows[0] if rows else None
        if target is None:
            raise KeyError("Unknown evidence id: %s" % evidence_id)
        with self.connect() as connection:
            neighbours = connection.execute(
                """
                SELECT c.chunk_key, c.position, c.text
                FROM chunks c
                WHERE c.document_id = ? AND c.position BETWEEN ? AND ?
                ORDER BY c.position
                """,
                (
                    target["document_id"],
                    max(0, int(target["chunk_position"]) - window),
                    int(target["chunk_position"]) + window,
                ),
            ).fetchall()
        context = []
        for row in neighbours:
            context.append(
                {
                    "evidence_id": stable_evidence_id(
                        target["provider"], target["external_id"],
                        target["document_key"], row["chunk_key"]
                    ),
                    "position": int(row["position"]),
                    "text": row["text"],
                    "is_target": row["chunk_key"] == target["chunk_key"],
                }
            )
        return {
            **{key: value for key, value in target.items() if key not in {"vector", "norm"}},
            "context": context,
        }

    def retrieval_metadata(self) -> Dict[str, Any]:
        self.initialize()
        signature = self._storage_signature()
        if (
            self._retrieval_metadata_cache is not None
            and self._retrieval_metadata_signature == signature
        ):
            return self._retrieval_metadata_cache
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM retrieval_metadata WHERE key = 'semantic'"
            ).fetchone()
        metadata = json.loads(row["value_json"]) if row else {}
        self._retrieval_metadata_cache = metadata
        self._retrieval_metadata_signature = self._storage_signature()
        return metadata

    def upsert_source(self, source: Mapping[str, Any]) -> int:
        return self.upsert_sources([source])[0]

    def upsert_sources(self, sources: Sequence[Mapping[str, Any]]) -> List[int]:
        """Upsert a source batch in one transaction without resetting fetch state."""
        self.initialize()
        now = utc_now()
        source_ids: List[int] = []
        with self.connect() as connection:
            for source in sources:
                connection.execute(
                    """
                    INSERT INTO sources (
                        provider, external_id, source_kind, parser, page_url, api_url,
                        headers_json, expected_title, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, external_id) DO UPDATE SET
                        source_kind = excluded.source_kind,
                        parser = excluded.parser,
                        page_url = excluded.page_url,
                        api_url = excluded.api_url,
                        headers_json = excluded.headers_json,
                        expected_title = excluded.expected_title
                    """,
                    (
                        source["provider"],
                        source["external_id"],
                        source["source_kind"],
                        source["parser"],
                        source["page_url"],
                        source["api_url"],
                        json.dumps(source.get("headers") or {}, ensure_ascii=False),
                        source.get("expected_title", ""),
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT id FROM sources WHERE provider = ? AND external_id = ?",
                    (source["provider"], source["external_id"]),
                ).fetchone()
                source_id = int(row["id"])
                if source.get("official_status"):
                    connection.execute(
                        "UPDATE sources SET official_status = ? WHERE id = ?",
                        (source["official_status"], source_id),
                    )
                source_ids.append(source_id)
        return source_ids

    def collection_checkpoint(self, account_uid: str) -> Dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_checkpoints WHERE account_uid = ?",
                (account_uid,),
            ).fetchone()
        return dict(row) if row else {
            "account_uid": account_uid,
            "next_cursor": "",
            "terminal": 0,
            "observed_count": 0,
            "updated_at": None,
            "terminal_at": None,
        }

    def wiki_refresh_checkpoint(self, catalog_key: str = "game_catalog:17") -> Optional[Dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM wiki_refresh_checkpoints WHERE catalog_key = ?",
                (catalog_key,),
            ).fetchone()
        return dict(row) if row else None

    def start_wiki_refresh(
        self, cycle_id: str, catalog_key: str = "game_catalog:17"
    ) -> Dict[str, Any]:
        """Start a cycle only when no unfinished Wiki refresh already exists."""
        self.initialize()
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM wiki_refresh_checkpoints WHERE catalog_key = ?",
                (catalog_key,),
            ).fetchone()
            if existing is not None and not bool(existing["terminal"]):
                return dict(existing)
            maximum = int(connection.execute(
                """SELECT COALESCE(MAX(id), 0) FROM sources
                   WHERE provider = 'mihoyo_wiki' AND official_status = 'verified'
                     AND status = 'parsed'"""
            ).fetchone()[0])
            terminal = int(maximum == 0)
            connection.execute(
                """INSERT INTO wiki_refresh_checkpoints(
                       catalog_key, cycle_id, after_source_id, max_source_id, terminal,
                       checked_count, changed_count, started_at, updated_at, completed_at
                   ) VALUES (?, ?, 0, ?, ?, 0, 0, ?, ?, ?)
                   ON CONFLICT(catalog_key) DO UPDATE SET
                     cycle_id = excluded.cycle_id,
                     after_source_id = 0,
                     max_source_id = excluded.max_source_id,
                     terminal = excluded.terminal,
                     checked_count = 0,
                     changed_count = 0,
                     started_at = excluded.started_at,
                     updated_at = excluded.updated_at,
                     completed_at = excluded.completed_at""",
                (catalog_key, cycle_id, maximum, terminal, now, now, now if terminal else None),
            )
        return self.wiki_refresh_checkpoint(catalog_key) or {}

    def wiki_refresh_sources(
        self, catalog_key: str = "game_catalog:17", limit: int = 10
    ) -> List[sqlite3.Row]:
        checkpoint = self.wiki_refresh_checkpoint(catalog_key)
        if checkpoint is None or checkpoint["terminal"]:
            return []
        with self.connect() as connection:
            return list(connection.execute(
                """SELECT * FROM sources
                   WHERE provider = 'mihoyo_wiki' AND official_status = 'verified'
                     AND status = 'parsed' AND id > ? AND id <= ?
                   ORDER BY id LIMIT ?""",
                (checkpoint["after_source_id"], checkpoint["max_source_id"], limit),
            ).fetchall())

    def advance_wiki_refresh(
        self, source_id: int, *, changed: bool, catalog_key: str = "game_catalog:17"
    ) -> Dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            checkpoint = connection.execute(
                "SELECT * FROM wiki_refresh_checkpoints WHERE catalog_key = ?",
                (catalog_key,),
            ).fetchone()
            if checkpoint is None or checkpoint["terminal"]:
                raise RuntimeError("Wiki refresh cycle is not active")
            if source_id <= int(checkpoint["after_source_id"]):
                raise ValueError("Wiki refresh source order did not advance")
            terminal = int(source_id >= int(checkpoint["max_source_id"]))
            connection.execute(
                """UPDATE wiki_refresh_checkpoints SET
                     after_source_id = ?, terminal = ?,
                     checked_count = checked_count + 1,
                     changed_count = changed_count + ?, updated_at = ?,
                     completed_at = CASE WHEN ? = 1 THEN ? ELSE NULL END
                   WHERE catalog_key = ?""",
                (source_id, terminal, int(changed), now, terminal, now, catalog_key),
            )
        return self.wiki_refresh_checkpoint(catalog_key) or {}

    def complete_wiki_refresh(self, catalog_key: str = "game_catalog:17") -> Dict[str, Any]:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE wiki_refresh_checkpoints SET
                     after_source_id = max_source_id, terminal = 1,
                     updated_at = ?, completed_at = COALESCE(completed_at, ?)
                   WHERE catalog_key = ? AND terminal = 0""",
                (now, now, catalog_key),
            )
        return self.wiki_refresh_checkpoint(catalog_key) or {}

    def mark_refresh_unchanged(self, source_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sources SET fetched_at = ?, last_error = NULL WHERE id = ?",
                (utc_now(), source_id),
            )

    def mark_refresh_error(self, source_id: int, message: str) -> None:
        """Retain last-known-good parsed evidence after a transient refresh failure."""
        with self.connect() as connection:
            connection.execute(
                "UPDATE sources SET last_error = ? WHERE id = ?",
                (message[:2000], source_id),
            )

    def start_collection_run(self, run_id: str, stage: str) -> None:
        self.initialize()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO collection_runs(run_id, stage, status, started_at)
                   VALUES (?, ?, 'running', ?)""",
                (run_id, stage, utc_now()),
            )

    def finish_collection_run(
        self, run_id: str, status: str, report: Mapping[str, Any]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE collection_runs
                   SET status = ?, finished_at = ?, report_json = ? WHERE run_id = ?""",
                (status, utc_now(), json.dumps(report, ensure_ascii=False), run_id),
            )

    def commit_discovery_page(
        self,
        account_uid: str,
        items: Sequence[Mapping[str, Any]],
        next_cursor: str,
        terminal: bool,
        classifier_version: str,
        *,
        preserve_completed_inventory: bool = False,
    ) -> Dict[str, Any]:
        """Atomically register one listing page and its following cursor."""
        self.initialize()
        inserted = 0
        duplicates = 0
        existing_duplicates = 0
        unverified = 0
        now = utc_now()
        with self.connect() as connection:
            before = {
                (row["provider"], row["external_id"]): int(row["id"])
                for row in connection.execute(
                    "SELECT id, provider, external_id FROM sources WHERE provider = 'miyoushe'"
                )
            }
            page_ids = set()
            for item in items:
                external_id = str(item["external_id"])
                if external_id in page_ids:
                    duplicates += 1
                    continue
                page_ids.add(external_id)
                identity = ("miyoushe", external_id)
                verified = bool(item["verified"])
                connection.execute(
                    """INSERT INTO sources(
                           provider, external_id, source_kind, parser, page_url, api_url,
                           headers_json, expected_title, official_status, discovered_at
                       ) VALUES ('miyoushe', ?, ?, 'miyoushe_post', ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(provider, external_id) DO UPDATE SET
                         source_kind = excluded.source_kind,
                         page_url = excluded.page_url,
                         api_url = excluded.api_url,
                         headers_json = excluded.headers_json,
                         expected_title = excluded.expected_title,
                         official_status = excluded.official_status""",
                    (
                        external_id, item["source_kind"], item["page_url"], item["api_url"],
                        json.dumps(item.get("headers") or {}, ensure_ascii=False),
                        item.get("title", ""), "verified" if verified else "unverified", now,
                    ),
                )
                source_id = int(connection.execute(
                    "SELECT id FROM sources WHERE provider = 'miyoushe' AND external_id = ?",
                    (external_id,),
                ).fetchone()[0])
                if identity in before:
                    duplicates += 1
                    existing_duplicates += 1
                else:
                    inserted += 1
                disposition = "manual_review" if verified else "excluded_unverified"
                reason = "awaiting_body_classification" if verified else "listing_not_officially_verified"
                if not verified:
                    unverified += 1
                connection.execute(
                    """INSERT INTO source_dispositions(
                           source_id, disposition, reason, classifier_version, verified, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(source_id) DO UPDATE SET
                         verified = excluded.verified,
                         disposition = CASE
                           WHEN source_dispositions.reviewed_at IS NOT NULL
                             THEN source_dispositions.disposition
                           WHEN source_dispositions.verified = 1 AND excluded.verified = 1
                             THEN source_dispositions.disposition
                           ELSE excluded.disposition
                         END,
                         reason = CASE
                           WHEN source_dispositions.reviewed_at IS NOT NULL
                             THEN source_dispositions.reason
                           WHEN source_dispositions.verified = 1 AND excluded.verified = 1
                             THEN source_dispositions.reason
                           ELSE excluded.reason
                         END,
                         classifier_version = CASE
                           WHEN source_dispositions.reviewed_at IS NOT NULL
                             THEN source_dispositions.classifier_version
                           WHEN source_dispositions.verified = 1 AND excluded.verified = 1
                             THEN source_dispositions.classifier_version
                           ELSE excluded.classifier_version
                         END,
                         updated_at = excluded.updated_at""",
                    (source_id, disposition, reason, classifier_version, int(verified), now),
                )
            previous = connection.execute(
                "SELECT observed_count, terminal_at FROM account_checkpoints WHERE account_uid = ?",
                (account_uid,),
            ).fetchone()
            observed = max(int(previous[0]) if previous else 0, len(before) + inserted)
            frontier_reached = bool(
                preserve_completed_inventory and existing_duplicates > 0
            )
            effective_terminal = bool(terminal or frontier_reached)
            effective_cursor = "" if frontier_reached else next_cursor
            connection.execute(
                """INSERT INTO account_checkpoints(
                       account_uid, next_cursor, terminal, observed_count, updated_at, terminal_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_uid) DO UPDATE SET
                     next_cursor = excluded.next_cursor,
                     terminal = excluded.terminal,
                     observed_count = max(account_checkpoints.observed_count, excluded.observed_count),
                     updated_at = excluded.updated_at,
                     terminal_at = CASE WHEN excluded.terminal = 1
                                        THEN COALESCE(account_checkpoints.terminal_at, excluded.terminal_at)
                                        ELSE account_checkpoints.terminal_at END""",
                (
                    account_uid, effective_cursor, int(effective_terminal), observed, now,
                    now if effective_terminal and not (previous and previous[1]) else
                    (previous[1] if previous else None),
                ),
            )
        return {
            "registered": inserted,
            "duplicates": duplicates,
            "unverified": unverified,
            "frontier_reached": frontier_reached,
        }

    def reserve_daily_request(self, budget_date: str, limit: int) -> int:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT request_count FROM daily_request_budgets WHERE budget_date = ?",
                (budget_date,),
            ).fetchone()
            count = int(row[0]) if row else 0
            if limit > 0 and count >= limit:
                raise RuntimeError("daily request budget exhausted")
            count += 1
            connection.execute(
                """INSERT INTO daily_request_budgets(budget_date, request_count, updated_at)
                   VALUES (?, ?, ?) ON CONFLICT(budget_date) DO UPDATE SET
                     request_count = excluded.request_count, updated_at = excluded.updated_at""",
                (budget_date, count, utc_now()),
            )
            return count

    def record_fetch_attempt(
        self, run_id: str, source_id: Optional[int], attempt: int, outcome: str,
        wait_seconds: float = 0, http_status: Optional[int] = None,
        error_type: Optional[str] = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO fetch_attempts(
                       run_id, source_id, attempt, outcome, http_status, wait_seconds,
                       error_type, attempted_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, source_id, attempt, outcome, http_status, wait_seconds,
                 error_type, utc_now()),
            )

    def record_raw_manifest(
        self, source_id: int, raw_sha256: str, raw_byte_count: int,
        local_path: Path, object_key: str, etag: Optional[str],
        object_version: Optional[str], content_sha256: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO raw_object_manifests(
                       source_id, raw_sha256, raw_byte_count, local_path, object_key,
                       etag, object_version, persisted_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET
                     raw_sha256 = excluded.raw_sha256,
                     raw_byte_count = excluded.raw_byte_count,
                     local_path = excluded.local_path,
                     object_key = excluded.object_key,
                     etag = excluded.etag,
                     object_version = excluded.object_version,
                     persisted_at = excluded.persisted_at""",
                (source_id, raw_sha256, raw_byte_count, str(local_path), object_key,
                 etag, object_version, now),
            )
            connection.execute(
                """UPDATE sources SET raw_path = ?, raw_sha256 = ?, content_sha256 = ?,
                   raw_byte_count = ?, fetched_at = ?, status = 'fetched', last_error = NULL
                   WHERE id = ?""",
                (str(local_path), raw_sha256, content_sha256, raw_byte_count, now, source_id),
            )

    def set_disposition(
        self, source_id: int, disposition: str, reason: str,
        classifier_version: str, *, reviewed: bool = False,
    ) -> None:
        source = self.get_source(source_id)
        verified = source["official_status"] == "verified"
        if not verified and disposition == "eligible_evidence":
            raise ValueError("unverified items can never become eligible evidence")
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO source_dispositions(
                       source_id, disposition, reason, classifier_version, verified,
                       reviewed_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET
                     disposition = excluded.disposition, reason = excluded.reason,
                     classifier_version = excluded.classifier_version,
                     verified = excluded.verified, reviewed_at = excluded.reviewed_at,
                     updated_at = excluded.updated_at""",
                (source_id, disposition, reason, classifier_version, int(verified),
                 now if reviewed else None, now),
            )

    def disposition_rows(self) -> List[Dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT d.*, s.external_id, s.source_kind, s.status, s.raw_sha256
                   FROM source_dispositions d JOIN sources s ON s.id = d.source_id
                   ORDER BY d.source_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def source_disposition(self, source_id: int) -> Optional[Dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_dispositions WHERE source_id = ?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sources(
        self, statuses: Optional[Sequence[str]] = None, limit: Optional[int] = None
    ) -> List[sqlite3.Row]:
        self.initialize()
        query = "SELECT * FROM sources"
        parameters: List[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += " WHERE status IN (%s)" % placeholders
            parameters.extend(statuses)
        query += " ORDER BY id"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.connect() as connection:
            return list(connection.execute(query, parameters).fetchall())

    def list_parseable_sources(
        self,
        statuses: Sequence[str],
        limit: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> List[sqlite3.Row]:
        """Return evidence-eligible sources, applying filters before the batch limit."""
        self.initialize()
        placeholders = ",".join("?" for _ in statuses)
        query = """SELECT s.* FROM sources s
                   LEFT JOIN source_dispositions d ON d.source_id = s.id
                   WHERE s.status IN (%s)
                     AND (d.disposition IS NULL OR d.disposition = 'eligible_evidence')""" % placeholders
        parameters: List[Any] = list(statuses)
        if provider is not None:
            query += " AND s.provider = ?"
            parameters.append(provider)
        query += " ORDER BY s.id"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with self.connect() as connection:
            return list(connection.execute(query, parameters).fetchall())

    def get_source(self, source_id: int) -> sqlite3.Row:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Unknown source id: %d" % source_id)
        return row

    def source_detail(self, source_id: int) -> Dict[str, Any]:
        source = self.get_source(source_id)
        with self.connect() as connection:
            documents = connection.execute(
                """SELECT id, document_key, title, section_path, content_type, position,
                          evidence_eligible, metadata_json
                   FROM documents WHERE source_id = ? ORDER BY position""",
                (source_id,),
            ).fetchall()
            output = []
            for document in documents:
                item = dict(document)
                item["chunk_count"] = int(connection.execute(
                    "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document["id"],)
                ).fetchone()[0])
                output.append(item)
        allowed = (
            "id", "provider", "external_id", "source_kind", "page_url", "title",
            "version", "remote_created_at", "remote_updated_at", "official_status",
            "status", "fetched_at", "parsed_at", "last_error",
        )
        return {"source": {key: source[key] for key in allowed}, "documents": output}

    def identity_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        self.initialize()
        with self.connect() as connection:
            return {
                "people": [dict(row) for row in connection.execute(
                    "SELECT * FROM narrative_people ORDER BY canonical_name"
                )],
                "forms": [dict(row) for row in connection.execute(
                    """SELECT * FROM playable_forms ORDER BY narrative_person_key,
                       CASE form_kind WHEN 'base' THEN 0 ELSE 1 END, canonical_name"""
                )],
                "names": [dict(row) for row in connection.execute(
                    "SELECT * FROM identity_names ORDER BY owner_kind, owner_key, name_type, name"
                )],
            }

    def relation_audit(self, *, update: bool = False) -> Dict[str, Any]:
        current = self.evidence_ids()
        stale_ids = []
        with self.connect() as connection:
            relations = connection.execute("SELECT id FROM relations ORDER BY id").fetchall()
            for relation in relations:
                evidence = connection.execute(
                    "SELECT evidence_id FROM relation_evidence WHERE relation_id = ?",
                    (relation["id"],),
                ).fetchall()
                stale = not evidence or any(row["evidence_id"] not in current for row in evidence)
                if update:
                    connection.execute(
                        "UPDATE relations SET is_stale = ? WHERE id = ?",
                        (int(stale), relation["id"]),
                    )
                if stale:
                    stale_ids.append(int(relation["id"]))
        return {"relations": len(relations), "stale": len(stale_ids), "stale_ids": stale_ids}

    def relation_rows(
        self, entity_name: Optional[str] = None, *, include_candidates: bool = False
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT r.*, s.canonical_name AS subject_name, s.entity_type AS subject_type,
                   o.canonical_name AS object_name, o.entity_type AS object_type
            FROM relations r
            JOIN entities s ON s.id = r.subject_id
            JOIN entities o ON o.id = r.object_id
            WHERE 1 = 1
        """
        parameters: List[Any] = []
        query += (
            " AND r.review_status IN ('approved', 'pending')"
            if include_candidates else " AND r.review_status = 'approved'"
        )
        if entity_name:
            query += " AND (s.canonical_name = ? OR o.canonical_name = ?)"
            parameters.extend([entity_name, entity_name])
        query += " ORDER BY r.review_status, s.canonical_name, r.predicate, o.canonical_name"
        with self.connect() as connection:
            relations = [dict(row) for row in connection.execute(query, parameters).fetchall()]
            for relation in relations:
                relation["evidence_ids"] = [
                    row["evidence_id"] for row in connection.execute(
                        "SELECT evidence_id FROM relation_evidence WHERE relation_id = ? ORDER BY evidence_id",
                        (relation["id"],),
                    ).fetchall()
                ]
        return relations

    def approved_relation_evidence_ids(self, left: int, right: int) -> set[str]:
        with self.connect() as connection:
            return {
                str(row["evidence_id"]) for row in connection.execute(
                    """SELECT re.evidence_id FROM relations r
                       JOIN relation_evidence re ON re.relation_id=r.id
                       WHERE r.review_status='approved' AND r.is_stale=0
                         AND ((r.subject_id=? AND r.object_id=?) OR
                              (r.subject_id=? AND r.object_id=?))""",
                    (left, right, right, left),
                )
            }

    def corpus_snapshot_rows(self) -> Dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            return {
                "sources": [dict(row) for row in connection.execute(
                    """SELECT provider, external_id, source_kind, status, official_status,
                              COALESCE(version, '') AS version,
                              COALESCE(content_sha256, '') AS content_sha256
                       FROM sources ORDER BY provider, external_id"""
                )],
                "documents": [dict(row) for row in connection.execute(
                    """SELECT s.provider, s.external_id, d.document_key, d.evidence_eligible
                       FROM documents d JOIN sources s ON s.id = d.source_id
                       ORDER BY s.provider, s.external_id, d.document_key"""
                )],
                "chunks": [dict(row) for row in connection.execute(
                    """SELECT s.provider, s.external_id, d.document_key, c.chunk_key,
                              c.content_sha256, d.evidence_eligible, s.status
                       FROM chunks c JOIN documents d ON d.id = c.document_id
                       JOIN sources s ON s.id = d.source_id
                       ORDER BY s.provider, s.external_id, d.document_key, c.chunk_key"""
                )],
                "entities": [dict(row) for row in connection.execute(
                    """SELECT canonical_name, entity_type, description
                       FROM entities ORDER BY entity_type, canonical_name"""
                )],
                "aliases": [dict(row) for row in connection.execute(
                    """SELECT e.canonical_name, e.entity_type, a.alias, a.alias_type
                       FROM aliases a JOIN entities e ON e.id = a.entity_id
                       ORDER BY e.entity_type, e.canonical_name, a.alias"""
                )],
                "relations": [dict(row) for row in connection.execute(
                    """SELECT se.canonical_name AS subject, r.predicate,
                              oe.canonical_name AS object, r.evidence_level,
                              r.review_status, r.is_stale
                       FROM relations r JOIN entities se ON se.id = r.subject_id
                       JOIN entities oe ON oe.id = r.object_id
                       ORDER BY subject, r.predicate, object"""
                )],
                "semantic_vectors": int(connection.execute(
                    "SELECT COUNT(*) FROM chunk_vectors"
                ).fetchone()[0]),
            }

    def source_disposition_rows(self) -> List[Dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT s.provider, s.external_id, sd.disposition, sd.reason,
                          sd.classifier_version, sd.verified
                   FROM source_dispositions sd JOIN sources s ON s.id=sd.source_id
                   ORDER BY s.provider, s.external_id"""
            )]

    def readiness(self) -> Dict[str, Any]:
        return {"backend": self.backend_name, "ready": True, "mutable": self.mutable}

    def record_fetch(
        self,
        source_id: int,
        raw_path: Path,
        raw_sha256: str,
        raw_byte_count: int,
        content_sha256: Optional[str] = None,
    ) -> bool:
        previous = self.get_source(source_id)
        content_hash = content_sha256 or raw_sha256
        changed = previous["content_sha256"] != content_hash
        next_status = "fetched" if changed or previous["status"] == "discovered" else previous["status"]
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sources
                SET raw_path = ?, raw_sha256 = ?, content_sha256 = ?,
                    raw_byte_count = ?, fetched_at = ?,
                    status = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    str(raw_path),
                    raw_sha256,
                    content_hash,
                    raw_byte_count,
                    utc_now(),
                    next_status,
                    source_id,
                ),
            )
        return changed

    def mark_error(self, source_id: int, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sources SET status = 'error', last_error = ? WHERE id = ?",
                (message[:2000], source_id),
            )

    def mark_skipped(self, source_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sources SET status = 'skipped', last_error = NULL WHERE id = ?",
                (source_id,),
            )

    def replace_documents(
        self,
        source_id: int,
        source_metadata: Mapping[str, Any],
        documents: Iterable[Mapping[str, Any]],
    ) -> Dict[str, int]:
        document_count = 0
        chunk_count = 0
        with self.connect() as connection:
            connection.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
            for document in documents:
                cursor = connection.execute(
                    """
                    INSERT INTO documents (
                        source_id, document_key, title, section_path, content_type,
                        position, evidence_eligible, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        document["document_key"],
                        document["title"],
                        document["section_path"],
                        document["content_type"],
                        document["position"],
                        int(document.get("evidence_eligible", True)),
                        json.dumps(document.get("metadata") or {}, ensure_ascii=False),
                    ),
                )
                document_id = int(cursor.lastrowid)
                document_count += 1
                for chunk in document.get("chunks", []):
                    connection.execute(
                        """
                        INSERT INTO chunks (
                            document_id, chunk_key, section_path, speaker, text,
                            position, content_sha256, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            chunk["chunk_key"],
                            chunk["section_path"],
                            chunk.get("speaker", ""),
                            chunk["text"],
                            chunk["position"],
                            chunk["content_sha256"],
                            json.dumps(chunk.get("metadata") or {}, ensure_ascii=False),
                        ),
                    )
                    chunk_count += 1
            connection.execute(
                """
                UPDATE sources
                SET title = ?, version = ?, remote_created_at = ?,
                    remote_updated_at = ?, official_status = ?, status = 'parsed',
                    parsed_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    source_metadata.get("title", ""),
                    source_metadata.get("version"),
                    source_metadata.get("created_at"),
                    source_metadata.get("updated_at"),
                    source_metadata.get("official_status", "unknown"),
                    utc_now(),
                    source_id,
                ),
            )
        return {"documents": document_count, "chunks": chunk_count}

    @staticmethod
    def _remove_unloadable_fts_schema(connection: sqlite3.Connection) -> None:
        """Remove only the derived FTS objects when their tokenizer cannot load."""
        connection.commit()
        schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
        connection.execute("PRAGMA writable_schema = ON")
        try:
            connection.execute(
                "DELETE FROM sqlite_master WHERE name = ? OR name LIKE ?",
                ("chunks_fts", "chunks_fts_%"),
            )
        finally:
            connection.execute("PRAGMA writable_schema = OFF")
        connection.execute("PRAGMA schema_version = %d" % (schema_version + 1))
        connection.commit()
        connection.execute("VACUUM")

    @classmethod
    def _reset_fts(cls, connection: sqlite3.Connection) -> int:
        connection.execute("DROP TRIGGER IF EXISTS chunks_fts_after_insert")
        connection.execute("DROP TRIGGER IF EXISTS chunks_fts_after_update")
        connection.execute("DROP TRIGGER IF EXISTS chunks_fts_after_delete")
        try:
            connection.execute("DROP TABLE IF EXISTS chunks_fts")
        except sqlite3.OperationalError as error:
            if "no such tokenizer" not in str(error).lower():
                raise
            cls._remove_unloadable_fts_schema(connection)
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE chunks_fts USING fts5(
                    text, section_path, speaker,
                    chunk_id UNINDEXED, source_id UNINDEXED,
                    tokenize='trigram'
                )
                """
            )
        except sqlite3.OperationalError:
            connection.execute(
                """
                CREATE VIRTUAL TABLE chunks_fts USING fts5(
                    text, section_path, speaker,
                    chunk_id UNINDEXED, source_id UNINDEXED,
                    tokenize='unicode61'
                )
                """
            )
        connection.execute(
            """
            INSERT INTO chunks_fts (text, section_path, speaker, chunk_id, source_id)
            SELECT c.text, c.section_path, c.speaker, c.id, d.source_id
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.evidence_eligible = 1
            """
        )
        connection.executescript(
            """
                CREATE TRIGGER chunks_fts_after_insert AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts (
                        text, section_path, speaker, chunk_id, source_id
                    )
                    SELECT
                        NEW.text, NEW.section_path, NEW.speaker, NEW.id, d.source_id
                    FROM documents d
                    WHERE d.id = NEW.document_id AND d.evidence_eligible = 1;
                END;

                CREATE TRIGGER chunks_fts_after_update AFTER UPDATE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE chunk_id = OLD.id;
                    INSERT INTO chunks_fts (
                        text, section_path, speaker, chunk_id, source_id
                    )
                    SELECT
                        NEW.text, NEW.section_path, NEW.speaker, NEW.id, d.source_id
                    FROM documents d
                    WHERE d.id = NEW.document_id AND d.evidence_eligible = 1;
                END;

                CREATE TRIGGER chunks_fts_after_delete AFTER DELETE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE chunk_id = OLD.id;
                END;
            """
        )
        row = connection.execute("SELECT COUNT(*) AS count FROM chunks_fts").fetchone()
        return int(row["count"])

    def rebuild_fts(self) -> int:
        self.initialize()
        with self.connect() as connection:
            return self._reset_fts(connection)

    def search(
        self, query: str, limit: int = 10,
        source_kinds: Optional[Sequence[str]] = None, version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        fts_query = '"%s"' % query.replace('"', '""')
        filters = ["s.status = 'parsed'"]
        filter_parameters: List[Any] = []
        if source_kinds:
            placeholders = ",".join("?" for _ in source_kinds)
            filters.append("s.source_kind IN (%s)" % placeholders)
            filter_parameters.extend(source_kinds)
        if version is not None:
            filters.append("COALESCE(s.version, '') = ?")
            filter_parameters.append(str(version))
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
            ).fetchone()
            if exists is None:
                raise RuntimeError("FTS index is missing; run the index command first")
            try:
                rows = connection.execute(
                    """
                    SELECT
                        f.chunk_id, f.source_id, f.section_path, f.speaker, f.text,
                        bm25(chunks_fts) AS score, s.title, s.page_url, s.source_kind
                    FROM chunks_fts f
                    JOIN sources s ON s.id = f.source_id
                    WHERE chunks_fts MATCH ? AND %s
                    ORDER BY score
                    LIMIT ?
                    """ % " AND ".join(filters),
                    (fts_query, *filter_parameters, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # Trigram FTS cannot match terms shorter than three characters.
                # The bounded literal fallback still produces candidate IDs
                # without loading semantic vectors for the whole corpus.
                rows = []
            if not rows:
                literal = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pattern = "%%%s%%" % literal
                rows = connection.execute(
                    """
                    SELECT
                        c.id AS chunk_id, d.source_id, c.section_path, c.speaker, c.text,
                        0.0 AS score, s.title, s.page_url, s.source_kind
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    JOIN sources s ON s.id = d.source_id
                    WHERE d.evidence_eligible = 1
                      AND %s
                      AND (
                          c.text LIKE ? ESCAPE '\\'
                          OR c.section_path LIKE ? ESCAPE '\\'
                          OR COALESCE(c.speaker, '') LIKE ? ESCAPE '\\'
                      )
                    ORDER BY c.id
                    LIMIT ?
                    """ % " AND ".join(filters),
                    (pattern, pattern, pattern, *filter_parameters, limit),
                ).fetchall()
            return [dict(row) for row in rows]

    def statistics(self) -> Dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            source_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM sources GROUP BY status"
            ).fetchall()
            counts = {
                "sources": connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "chunks": connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "eligible_documents": connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE evidence_eligible = 1"
                ).fetchone()[0],
                "entities": connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "aliases": connection.execute("SELECT COUNT(*) FROM aliases").fetchone()[0],
                "entity_chunk_links": connection.execute(
                    "SELECT COUNT(*) FROM entity_chunks"
                ).fetchone()[0],
                "semantic_vectors": connection.execute(
                    "SELECT COUNT(*) FROM chunk_vectors"
                ).fetchone()[0],
                "relations": connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
                "approved_relations": connection.execute(
                    "SELECT COUNT(*) FROM relations WHERE review_status = 'approved' AND is_stale = 0"
                ).fetchone()[0],
                "pending_relations": connection.execute(
                    "SELECT COUNT(*) FROM relations WHERE review_status = 'pending'"
                ).fetchone()[0],
            }
            fts_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
            ).fetchone()
            counts["fts_rows"] = (
                connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
                if fts_exists
                else 0
            )
        return {
            "counts": counts,
            "source_statuses": {row["status"]: row["count"] for row in source_rows},
            "database_path": str(self.path),
        }

    def catalog_metadata(self) -> Dict[str, Any]:
        """Return deterministic, read-only facets for knowledge browsing clients."""
        self.initialize()
        with self.connect() as connection:
            status_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM sources GROUP BY status ORDER BY status
                """
            ).fetchall()
            kind_rows = connection.execute(
                """
                SELECT source_kind AS value, COUNT(*) AS count
                FROM sources
                WHERE status = 'parsed'
                GROUP BY source_kind ORDER BY source_kind
                """
            ).fetchall()
            version_rows = connection.execute(
                """
                SELECT version AS value, COUNT(*) AS count
                FROM sources
                WHERE status = 'parsed' AND version IS NOT NULL AND TRIM(version) != ''
                GROUP BY version ORDER BY version
                """
            ).fetchall()
            counts = {
                "sources": connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "chunks": connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "eligible_documents": connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE evidence_eligible = 1"
                ).fetchone()[0],
            }
        return {
            "counts": counts,
            "source_statuses": {row["status"]: row["count"] for row in status_rows},
            "source_kinds": [dict(row) for row in kind_rows],
            "versions": [dict(row) for row in version_rows],
        }
