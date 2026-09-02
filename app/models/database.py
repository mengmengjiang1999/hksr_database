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

CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id, position);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id, position);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_entity_chunks_chunk ON entity_chunks(chunk_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

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

    def replace_entities(self, entities: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
        """Replace the small curated entity catalogue and relink all chunks."""
        self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM entities")
            entity_count = 0
            alias_count = 0
            for entity in entities:
                cursor = connection.execute(
                    "INSERT INTO entities (canonical_name, entity_type, description) VALUES (?, ?, ?)",
                    (
                        entity["canonical_name"],
                        entity["entity_type"],
                        entity.get("description", ""),
                    ),
                )
                entity_id = int(cursor.lastrowid)
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
                ORDER BY e.id, a.id
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
        self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM chunk_vectors")
            for chunk_id, vector in vectors.items():
                norm = sum(weight * weight for weight in vector.values()) ** 0.5
                connection.execute(
                    "INSERT INTO chunk_vectors (chunk_id, vector_json, norm) VALUES (?, ?, ?)",
                    (chunk_id, json.dumps(vector, ensure_ascii=False), norm),
                )
            connection.execute(
                "INSERT OR REPLACE INTO retrieval_metadata (key, value_json) VALUES ('semantic', ?)",
                (json.dumps(metadata, ensure_ascii=False),),
            )
        return len(vectors)

    def retrieval_rows(self) -> List[Dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id AS chunk_id, c.text, c.section_path, c.speaker,
                       s.id AS source_id, s.external_id, s.title, s.page_url,
                       s.source_kind, s.version, s.official_status,
                       v.vector_json, v.norm
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                JOIN sources s ON s.id = d.source_id
                LEFT JOIN chunk_vectors v ON v.chunk_id = c.id
                WHERE d.evidence_eligible = 1 AND s.status = 'parsed'
                """
            ).fetchall()
            entity_rows = connection.execute(
                """
                SELECT ec.chunk_id, e.id, e.canonical_name, e.entity_type,
                       ec.matched_text
                FROM entity_chunks ec JOIN entities e ON e.id = ec.entity_id
                """
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
            output.append(item)
        return output

    def retrieval_metadata(self) -> Dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM retrieval_metadata WHERE key = 'semantic'"
            ).fetchone()
        return json.loads(row["value_json"]) if row else {}

    def upsert_source(self, source: Mapping[str, Any]) -> int:
        self.initialize()
        now = utc_now()
        with self.connect() as connection:
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
            return int(row["id"])

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

    def get_source(self, source_id: int) -> sqlite3.Row:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Unknown source id: %d" % source_id)
        return row

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

    def rebuild_fts(self) -> int:
        self.initialize()
        with self.connect() as connection:
            connection.execute("DROP TRIGGER IF EXISTS chunks_fts_after_insert")
            connection.execute("DROP TRIGGER IF EXISTS chunks_fts_after_update")
            connection.execute("DROP TRIGGER IF EXISTS chunks_fts_after_delete")
            connection.execute("DROP TABLE IF EXISTS chunks_fts")
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

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        fts_query = '"%s"' % query.replace('"', '""')
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
            ).fetchone()
            if exists is None:
                raise RuntimeError("FTS index is missing; run the index command first")
            rows = connection.execute(
                """
                SELECT
                    f.chunk_id, f.source_id, f.section_path, f.speaker, f.text,
                    bm25(chunks_fts) AS score, s.title, s.page_url, s.source_kind
                FROM chunks_fts f
                JOIN sources s ON s.id = f.source_id
                WHERE chunks_fts MATCH ? AND s.status = 'parsed'
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, limit),
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
