"""HTTP API and local single-page application for the knowledge base."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.collectors import fetch_sources, parse_sources
from app.knowledge import audit_relations, build_relations, list_relations
from app.models.database import Database
from app.qa import answer_question
from app.retrieval import build_retrieval_index, hybrid_search, normalize_text, source_context


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = PROJECT_ROOT / "data/database/hksr.sqlite3"
DEFAULT_RAW_ROOT = PROJECT_ROOT / "data/raw"
DEFAULT_ENTITIES = PROJECT_ROOT / "data/m2/entities.json"
DEFAULT_RELATIONS = PROJECT_ROOT / "data/m4/relations.json"
DEFAULT_WEB_ROOT = PROJECT_ROOT / "web"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=50)
    minimum_score: float = Field(default=0.18, ge=0.0, le=1.0)
    source_kinds: Optional[List[str]] = None
    contexts: Optional[List[str]] = None


class SyncRequest(BaseModel):
    fetch: bool = True
    force_fetch: bool = False
    force_parse: bool = False
    limit: Optional[int] = Field(default=None, ge=1)
    timeout: int = Field(default=30, ge=1, le=300)


def _source_detail(database: Database, source_id: int) -> Dict[str, Any]:
    try:
        source = database.get_source(source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    with database.connect() as connection:
        documents = connection.execute(
            """
            SELECT id, document_key, title, section_path, content_type, position,
                   evidence_eligible, metadata_json
            FROM documents WHERE source_id = ? ORDER BY position
            """,
            (source_id,),
        ).fetchall()
        document_items = []
        for document in documents:
            item = dict(document)
            item["chunk_count"] = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document["id"],)
            ).fetchone()[0]
            document_items.append(item)
    allowed = (
        "id", "provider", "external_id", "source_kind", "page_url", "title",
        "version", "remote_created_at", "remote_updated_at", "official_status",
        "status", "fetched_at", "parsed_at", "last_error",
    )
    return {"source": {key: source[key] for key in allowed}, "documents": document_items}


def _entity_detail(database: Database, entity_id: int) -> Dict[str, Any]:
    entity = next((item for item in database.entity_catalog() if int(item["id"]) == entity_id), None)
    if entity is None:
        raise HTTPException(status_code=404, detail="Unknown entity id: %d" % entity_id)
    return {"entity": entity, "relations": list_relations(database, entity["canonical_name"])}


def _question_entities(database: Database, question: str) -> List[Dict[str, Any]]:
    normalized = normalize_text(question)
    output = []
    for entity in database.entity_catalog():
        aliases = [item["text"] for item in entity["aliases"]]
        if any(normalize_text(alias) in normalized for alias in aliases if alias):
            output.append({
                "entity": entity,
                "relations": list_relations(database, entity["canonical_name"]),
            })
    return output


def create_app(
    database_path: Path = DEFAULT_DATABASE,
    raw_root: Path = DEFAULT_RAW_ROOT,
    entity_path: Path = DEFAULT_ENTITIES,
    relation_path: Path = DEFAULT_RELATIONS,
    web_root: Path = DEFAULT_WEB_ROOT,
) -> FastAPI:
    database = Database(Path(database_path))
    database.initialize()
    app = FastAPI(
        title="崩坏：星穹铁道剧情与设定知识库",
        version="0.1.0",
        description="Local evidence-grounded knowledge API",
    )
    app.state.database = database
    app.state.raw_root = Path(raw_root)
    app.state.entity_path = Path(entity_path)
    app.state.relation_path = Path(relation_path)
    app.state.web_root = Path(web_root)

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        path = app.state.web_root / "index.html"
        if not path.exists():
            raise HTTPException(status_code=503, detail="Local web interface is missing")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "local_only_default": True}

    @app.get("/api/catalog")
    def catalog() -> Dict[str, Any]:
        metadata = database.catalog_metadata()
        contexts: Dict[str, int] = {}
        for item in metadata["source_kinds"]:
            context = source_context(item["value"])
            contexts[context] = contexts.get(context, 0) + int(item["count"])
        metadata["contexts"] = [
            {"value": value, "count": contexts[value]} for value in sorted(contexts)
        ]
        return metadata

    @app.post("/api/ask")
    def ask(request: AskRequest) -> Dict[str, Any]:
        result = answer_question(
            database, request.question.strip(), limit=request.limit,
            minimum_score=request.minimum_score, source_kinds=request.source_kinds,
            contexts=request.contexts,
        )
        result["related_entities"] = _question_entities(database, request.question)
        return result

    @app.get("/api/search")
    def search(
        q: str = Query(min_length=1, max_length=1000),
        limit: int = Query(default=10, ge=1, le=50),
        source_kind: Optional[List[str]] = Query(default=None),
        context: Optional[List[str]] = Query(default=None),
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {"query": q, "results": hybrid_search(
            database, q, limit=limit, source_kinds=source_kind,
            contexts=context, version=version,
        )}

    @app.get("/api/sources/{source_id}")
    def source(source_id: int) -> Dict[str, Any]:
        return _source_detail(database, source_id)

    @app.get("/api/entities/{entity_id}")
    def entity(entity_id: int) -> Dict[str, Any]:
        return _entity_detail(database, entity_id)

    @app.get("/api/relations")
    def relations(entity_name: Optional[str] = None) -> Dict[str, Any]:
        return {"entity": entity_name, "relations": list_relations(database, entity_name)}

    @app.get("/api/admin/status")
    def admin_status() -> Dict[str, Any]:
        return {
            **database.statistics(),
            "relation_audit": audit_relations(database, update=False),
        }

    @app.post("/api/admin/sync")
    def admin_sync(request: SyncRequest) -> Dict[str, Any]:
        stages: Dict[str, Any] = {}
        try:
            if request.fetch:
                stages["fetch"] = fetch_sources(
                    database, app.state.raw_root, force=request.force_fetch,
                    limit=request.limit, timeout=request.timeout,
                )
            stages["parse"] = parse_sources(
                database, force=request.force_parse, limit=request.limit
            )
            stages["fts"] = {"rows": database.rebuild_fts()}
            stages["retrieval"] = build_retrieval_index(database, app.state.entity_path)
            stages["relations"] = build_relations(database, app.state.relation_path)
        except Exception as error:
            return {
                "success": False, "stages": stages,
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        return {"success": True, "stages": stages, "status": database.statistics()}

    return app


app = create_app()
