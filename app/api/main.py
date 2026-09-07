"""HTTP API and local single-page application for the knowledge base."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.collectors import fetch_sources, parse_sources
from app.cloud import CloudDatabaseConfig
from app.knowledge import audit_relations, build_relations, identity_catalog, list_relations
from app.models import Database, PostgresReadStore, ReadStore, ReadStoreUnavailable
from app.qa import GenerationService, answer_question, answer_question_legacy, resolve_query_entities
from app.retrieval import build_retrieval_index, hybrid_search, source_context


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = PROJECT_ROOT / "data/database/hksr.sqlite3"
DEFAULT_RAW_ROOT = PROJECT_ROOT / "data/raw"
DEFAULT_ENTITIES = PROJECT_ROOT / "data/m2/entities.json"
DEFAULT_RELATIONS = PROJECT_ROOT / "data/m4/relations.json"
DEFAULT_WEB_ROOT = PROJECT_ROOT / "web"
BACKEND_ENVIRONMENT_VARIABLE = "HKSR_READ_BACKEND"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=50)
    minimum_score: float = Field(default=0.18, ge=0.0, le=1.0)
    source_kinds: Optional[List[str]] = None
    contexts: Optional[List[str]] = None
    use_generation: bool = False


class SyncRequest(BaseModel):
    fetch: bool = True
    force_fetch: bool = False
    force_parse: bool = False
    limit: Optional[int] = Field(default=None, ge=1)
    timeout: int = Field(default=30, ge=1, le=300)


def build_read_store(database_path: Path = DEFAULT_DATABASE) -> ReadStore:
    backend = os.environ.get(BACKEND_ENVIRONMENT_VARIABLE, "sqlite").strip().lower()
    if backend == "sqlite":
        return Database(Path(database_path))
    if backend == "postgres":
        try:
            pool_max = int(os.environ.get("HKSR_POSTGRES_POOL_MAX", "2"))
            acquire_timeout = float(os.environ.get("HKSR_POSTGRES_ACQUIRE_TIMEOUT", "5"))
            connect_timeout = int(os.environ.get("HKSR_POSTGRES_CONNECT_TIMEOUT", "10"))
            statement_timeout = int(os.environ.get("HKSR_POSTGRES_STATEMENT_TIMEOUT_MS", "15000"))
        except ValueError as error:
            raise ValueError("PostgreSQL pool and timeout settings must be numeric") from error
        return PostgresReadStore(
            CloudDatabaseConfig.from_environment().dsn,
            max_size=pool_max,
            acquire_timeout=acquire_timeout,
            connect_timeout=connect_timeout,
            statement_timeout_ms=statement_timeout,
        )
    raise ValueError("HKSR_READ_BACKEND must be 'sqlite' or 'postgres'")


def _source_detail(database: ReadStore, source_id: int) -> Dict[str, Any]:
    try:
        return database.source_detail(source_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _entity_detail(database: ReadStore, entity_id: int) -> Dict[str, Any]:
    entity = next((item for item in database.entity_catalog() if int(item["id"]) == entity_id), None)
    if entity is None:
        raise HTTPException(status_code=404, detail="Unknown entity id: %d" % entity_id)
    return {"entity": entity, "relations": list_relations(database, entity["canonical_name"])}


def _question_entities(database: ReadStore, question: str) -> List[Dict[str, Any]]:
    output = []
    resolved_ids = {item["entity_id"] for item in resolve_query_entities(database, question)}
    for entity in database.entity_catalog():
        if int(entity["id"]) in resolved_ids:
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
    generation_service: Optional[GenerationService] = None,
    entity_qa_enabled: Optional[bool] = None,
    read_store: Optional[ReadStore] = None,
) -> FastAPI:
    database = read_store or build_read_store(Path(database_path))
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
    app.state.generation_service = generation_service or GenerationService(None)
    app.state.entity_qa_enabled = (
        entity_qa_enabled if entity_qa_enabled is not None
        else os.environ.get("HKSR_M9_ENTITY_QA_ENABLED", "1").strip().lower()
             not in {"0", "false", "no", "off"}
    )
    try:
        retrieval_concurrency = max(
            1, int(os.environ.get("HKSR_RETRIEVAL_CONCURRENCY", "1"))
        )
    except ValueError:
        retrieval_concurrency = 1
    app.state.retrieval_concurrency = retrieval_concurrency
    app.state.retrieval_slots = threading.BoundedSemaphore(retrieval_concurrency)

    @app.exception_handler(ReadStoreUnavailable)
    def unavailable(_request: Any, _error: ReadStoreUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "数据库暂时不可用，请稍后重试"},
            headers={"Retry-After": "2"},
        )

    @app.on_event("shutdown")
    def close_read_store() -> None:
        close = getattr(database, "close", None)
        if close is not None:
            close()

    def acquire_retrieval_slot() -> None:
        if not app.state.retrieval_slots.acquire(blocking=False):
            raise HTTPException(
                status_code=503,
                detail="检索服务正忙，请稍后重试",
                headers={"Retry-After": "2"},
            )

    def release_retrieval_slot() -> None:
        app.state.retrieval_slots.release()

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        path = app.state.web_root / "index.html"
        if not path.exists():
            raise HTTPException(status_code=503, detail="Local web interface is missing")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        readiness = database.readiness()
        return {"status": "ok" if readiness["ready"] else "unavailable",
                "local_only_default": True, "database": readiness,
                "generation_enabled": app.state.generation_service.adapter is not None,
                "entity_qa_enabled": app.state.entity_qa_enabled}

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
        acquire_retrieval_slot()
        try:
            answerer = answer_question if app.state.entity_qa_enabled else answer_question_legacy
            result = answerer(
                database, request.question.strip(), limit=request.limit,
                minimum_score=request.minimum_score, source_kinds=request.source_kinds,
                contexts=request.contexts,
            )
            if request.use_generation and app.state.entity_qa_enabled:
                result = app.state.generation_service.answer(
                    database, request.question.strip(), result, limit=request.limit
                )
            else:
                result.update({"generation_outcome": "not_requested", "generation_fallback": True})
            if not app.state.entity_qa_enabled:
                result.update({"intent": "legacy", "resolved_entities": [], "ambiguity": None,
                               "partial_support": {"is_partial": False, "supported_parts": [],
                                                   "unsupported_parts": []},
                               "answer_strategy": "legacy_extractive"})
            result["related_entities"] = _question_entities(database, request.question)
            return result
        finally:
            release_retrieval_slot()

    @app.get("/api/identities")
    def identities(include_pending: bool = False) -> Dict[str, Any]:
        return {"people": identity_catalog(database, include_pending=include_pending)}

    @app.get("/api/search")
    def search(
        q: str = Query(min_length=1, max_length=1000),
        limit: int = Query(default=10, ge=1, le=50),
        source_kind: Optional[List[str]] = Query(default=None),
        context: Optional[List[str]] = Query(default=None),
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        acquire_retrieval_slot()
        try:
            return {"query": q, "results": hybrid_search(
                database, q, limit=limit, source_kinds=source_kind,
                contexts=context, version=version,
            )}
        finally:
            release_retrieval_slot()

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
            "generation_telemetry": app.state.generation_service.telemetry(),
        }

    @app.post("/api/admin/sync")
    def admin_sync(request: SyncRequest) -> Dict[str, Any]:
        stages: Dict[str, Any] = {}
        try:
            if not getattr(database, "mutable", False):
                raise PermissionError("Administrative sync is disabled for the read-only backend")
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
