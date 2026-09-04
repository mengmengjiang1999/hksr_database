"""Command line interface for the local M1 data pipeline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from app.capacity import build_capacity_report
from app.cloud import (
    CloudDatabaseConfig,
    apply_migrations,
    build_acceptance_report,
    build_database_audit,
    build_environment_report,
    cleanup_fixture,
    import_official_sqlite,
    load_fixture,
    probe_extensions,
    run_benchmark,
    read_json_report,
    write_acceptance_reports,
    write_json_report,
)
from app.collectors import (
    CollectionPolicy,
    M7Collector,
    OssRamRoleUploader,
    build_collection_report,
    discover_manifest,
    discover_official_account,
    discover_wiki_catalog,
    discover_wiki_search,
    fetch_sources,
    parse_sources,
    exclusive_lock,
    review_disposition,
    write_report as write_m7_report,
)
from app.models.database import Database
from app.knowledge import (
    audit_identity_catalog,
    audit_relations,
    build_relations,
    identity_catalog,
    list_relations,
    replace_identity_catalog,
    review_relation,
)
from app.qa import answer_question, evaluate_answers, evaluate_real_questions
from app.retrieval import build_retrieval_index, evaluate_retrieval, hybrid_search, intent_search


DEFAULT_DATABASE = Path("data/database/hksr.sqlite3")
DEFAULT_RAW_ROOT = Path("data/raw")
DEFAULT_MANIFEST = Path("data/m0/sample-manifest.json")
DEFAULT_ENTITIES = Path("data/m2/entities.json")
DEFAULT_EVALUATION = Path("data/m2/evaluation.json")
DEFAULT_QA_EVALUATION = Path("data/m3/evaluation.json")
DEFAULT_RELATIONS = Path("data/m4/relations.json")
DEFAULT_CAPACITY_ASSUMPTIONS = Path("data/m6a/capacity-assumptions.json")
DEFAULT_M6B_PROCUREMENT = Path("data/m6b/procurement-observation.json")
DEFAULT_M6B_EXTENSIONS = Path("data/m6b/dms-extension-observation.json")
DEFAULT_M6B_OPERATOR = Path("data/m6b/operator-evidence.json")
DEFAULT_M6B_IMPORT_REPORTS = (
    Path("data/m6b/runs/real-import-first.json"),
    Path("data/m6b/runs/real-import-second.json"),
)
DEFAULT_M7_RAW_ROOT = Path("data/m7/spool")
DEFAULT_M7_LOCK = Path("data/m7/collector.lock")
DEFAULT_M9_TAXONOMY = Path("data/m9/question-taxonomy.json")
DEFAULT_M9_EVALUATION = Path("data/m9/real-questions.json")
DEFAULT_M9_IDENTITIES = Path("data/m9/identities.json")


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="Register manifest targets")
    discover.add_argument("--manifest", type=Path)
    discover.add_argument("--wiki-query")
    discover.add_argument("--official-account-uid")
    discover.add_argument("--pages", type=int, default=1)
    discover.add_argument("--page-size", type=int, default=20)
    discover.add_argument("--timeout", type=int, default=30)

    fetch = subparsers.add_parser("fetch", help="Fetch discovered sources")
    fetch.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    fetch.add_argument("--force", action="store_true")
    fetch.add_argument("--limit", type=int)
    fetch.add_argument("--timeout", type=int, default=30)

    parse = subparsers.add_parser("parse", help="Parse fetched source responses")
    parse.add_argument("--force", action="store_true")
    parse.add_argument("--limit", type=int)
    parse.add_argument("--provider")

    index = subparsers.add_parser("index", help="Rebuild FTS, entity and semantic indexes")
    index.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES)
    subparsers.add_parser("status", help="Show local pipeline statistics")

    search = subparsers.add_parser("search", help="Search indexed evidence chunks")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")
    search.add_argument("--source-kind", action="append")
    search.add_argument("--version")
    search.add_argument("--context", action="append", choices=(
        "in_game", "official_supplement", "promotional", "preview", "development", "unknown"
    ))

    intent_search_parser = subparsers.add_parser(
        "intent-search", help="Search with deterministic intent and relation safety gates"
    )
    intent_search_parser.add_argument("query")
    intent_search_parser.add_argument("--limit", type=int, default=10)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate evidence retrieval")
    evaluate.add_argument("--dataset", type=Path, default=DEFAULT_EVALUATION)
    evaluate.add_argument("--mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")

    ask = subparsers.add_parser("ask", help="Return an evidence-grounded extractive answer")
    ask.add_argument("question")
    ask.add_argument("--limit", type=int, default=8)
    ask.add_argument("--minimum-score", type=float, default=0.18)
    ask.add_argument("--source-kind", action="append")
    ask.add_argument("--context", action="append", choices=(
        "in_game", "official_supplement", "promotional", "preview", "development", "unknown"
    ))

    evaluate_qa = subparsers.add_parser("evaluate-qa", help="Evaluate grounded answers")
    evaluate_qa.add_argument("--dataset", type=Path, default=DEFAULT_QA_EVALUATION)

    m9_baseline = subparsers.add_parser(
        "m9-baseline", help="Evaluate versioned real questions against a corpus snapshot"
    )
    m9_baseline.add_argument("--dataset", type=Path, default=DEFAULT_M9_EVALUATION)
    m9_baseline.add_argument("--taxonomy", type=Path, default=DEFAULT_M9_TAXONOMY)
    m9_baseline.add_argument("--limit", type=int, default=8)
    m9_baseline.add_argument("--output", type=Path)

    m9_identities = subparsers.add_parser(
        "m9-build-identities", help="Apply the versioned narrative identity catalogue"
    )
    m9_identities.add_argument("--catalog", type=Path, default=DEFAULT_M9_IDENTITIES)
    subparsers.add_parser("m9-audit-identities", help="Audit narrative identity integrity")
    list_identities = subparsers.add_parser(
        "m9-identities", help="List narrative people and playable forms"
    )
    list_identities.add_argument("--include-pending", action="store_true")

    build_relation_parser = subparsers.add_parser(
        "build-relations", help="Import curated relations and generate candidates"
    )
    build_relation_parser.add_argument("--catalog", type=Path, default=DEFAULT_RELATIONS)

    relation_parser = subparsers.add_parser("relations", help="List evidence-backed relations")
    relation_parser.add_argument("entity", nargs="?")
    relation_parser.add_argument("--include-candidates", action="store_true")

    subparsers.add_parser("audit-relations", help="Find relations with stale evidence")

    review = subparsers.add_parser("review-relation", help="Update a relation review decision")
    review.add_argument("relation_id", type=int)
    review.add_argument("status", choices=("approved", "pending", "rejected"))
    review.add_argument("--predicate")
    review.add_argument("--evidence-level", choices=("explicit", "inferred", "candidate"))
    review.add_argument("--reasoning")

    initialize = subparsers.add_parser("initialize", help="Build all local indexes and relations")
    initialize.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES)
    initialize.add_argument("--relations", type=Path, default=DEFAULT_RELATIONS)

    serve = subparsers.add_parser("serve", help="Run the local knowledge application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    capacity = subparsers.add_parser(
        "capacity-report", help="Measure local storage and project cloud capacity"
    )
    capacity.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    capacity.add_argument(
        "--assumptions", type=Path, default=DEFAULT_CAPACITY_ASSUMPTIONS
    )

    cloud_discover = subparsers.add_parser(
        "cloud-discover", help="Inspect PostgreSQL without exposing its DSN"
    )
    cloud_discover.add_argument("--output", type=Path)

    cloud_extensions = subparsers.add_parser(
        "cloud-extensions", help="Probe required PostgreSQL extensions"
    )
    cloud_extensions.add_argument("--allow-mutation", action="store_true")
    cloud_extensions.add_argument("--output", type=Path)

    cloud_migrate = subparsers.add_parser(
        "cloud-migrate", help="Apply versioned PostgreSQL migrations"
    )
    cloud_migrate.add_argument("--allow-mutation", action="store_true")

    cloud_import = subparsers.add_parser(
        "cloud-import-sqlite",
        help="Import the current official SQLite corpus into PostgreSQL",
    )
    cloud_import.add_argument("--batch-id", required=True)
    cloud_import.add_argument("--allow-mutation", action="store_true")
    cloud_import.add_argument("--output", type=Path)

    cloud_load = subparsers.add_parser(
        "cloud-load-fixture", help="Load an isolated synthetic scale fixture"
    )
    cloud_load.add_argument("--run-id", required=True)
    cloud_load.add_argument("--chunks", type=int, default=100_000)
    cloud_load.add_argument("--dimensions", type=int, default=1024)
    cloud_load.add_argument("--allow-mutation", action="store_true")

    cloud_benchmark = subparsers.add_parser(
        "cloud-benchmark", help="Measure exact/HNSW recall and query latency"
    )
    cloud_benchmark.add_argument("--run-id", required=True)
    cloud_benchmark.add_argument("--queries", type=int, default=20)
    cloud_benchmark.add_argument("--concurrency", type=int, default=10)
    cloud_benchmark.add_argument("--output", type=Path)

    cloud_cleanup = subparsers.add_parser(
        "cloud-cleanup", help="Delete one explicitly named synthetic run"
    )
    cloud_cleanup.add_argument("--run-id", required=True)
    cloud_cleanup.add_argument("--allow-mutation", action="store_true")

    cloud_audit = subparsers.add_parser(
        "cloud-audit", help="Read the final PostgreSQL row counts and synthetic state"
    )
    cloud_audit.add_argument("--output", type=Path)

    cloud_acceptance = subparsers.add_parser(
        "cloud-acceptance-report", help="Combine M6B measurements and operator evidence"
    )
    cloud_acceptance.add_argument("--procurement", type=Path, default=DEFAULT_M6B_PROCUREMENT)
    cloud_acceptance.add_argument("--extensions", type=Path, default=DEFAULT_M6B_EXTENSIONS)
    cloud_acceptance.add_argument("--operator-evidence", type=Path, default=DEFAULT_M6B_OPERATOR)
    cloud_acceptance.add_argument(
        "--import-report", type=Path, action="append", dest="import_reports"
    )
    cloud_acceptance.add_argument("--database-audit", type=Path)
    cloud_acceptance.add_argument(
        "--output-json", type=Path, default=Path("data/m6b/acceptance-report.json")
    )
    cloud_acceptance.add_argument(
        "--output-markdown", type=Path, default=Path("docs/m6b-acceptance-report.md")
    )

    m7_discover = subparsers.add_parser(
        "m7-discover", help="Run one bounded official-account metadata batch"
    )
    m7_discover.add_argument("--uid", required=True)
    m7_discover.add_argument("--pages", type=int, default=2)
    m7_discover.add_argument("--allow-cap-override", action="store_true")
    m7_discover.add_argument("--daily-budget", type=int, default=60)
    m7_discover.add_argument("--minimum-delay", type=float, default=15)
    m7_discover.add_argument("--maximum-delay", type=float, default=30)
    m7_discover.add_argument("--timeout", type=int, default=30)
    m7_discover.add_argument("--lock", type=Path, default=DEFAULT_M7_LOCK)
    m7_discover.add_argument("--output", type=Path)

    m7_fetch = subparsers.add_parser(
        "m7-fetch", help="Fetch and persist one bounded official-post batch"
    )
    m7_fetch.add_argument("--limit", type=int, default=10)
    m7_fetch.add_argument("--allow-cap-override", action="store_true")
    m7_fetch.add_argument("--daily-budget", type=int, default=60)
    m7_fetch.add_argument("--minimum-delay", type=float, default=15)
    m7_fetch.add_argument("--maximum-delay", type=float, default=30)
    m7_fetch.add_argument("--timeout", type=int, default=30)
    m7_fetch.add_argument("--raw-root", type=Path, default=DEFAULT_M7_RAW_ROOT)
    m7_fetch.add_argument("--oss-bucket", default=os.environ.get("HKSR_M7_OSS_BUCKET", ""))
    m7_fetch.add_argument("--oss-endpoint", default=os.environ.get("HKSR_M7_OSS_ENDPOINT", ""))
    m7_fetch.add_argument("--ram-role", default=os.environ.get("HKSR_M7_RAM_ROLE", ""))
    m7_fetch.add_argument("--oss-prefix", default="m7/raw")
    m7_fetch.add_argument("--lock", type=Path, default=DEFAULT_M7_LOCK)
    m7_fetch.add_argument("--output", type=Path)

    m7_wiki_discover = subparsers.add_parser(
        "m7-wiki-discover", help="Register the complete Wiki game-catalog access list"
    )
    m7_wiki_discover.add_argument("--channel-id", type=int, default=17)
    m7_wiki_discover.add_argument("--timeout", type=int, default=180)
    m7_wiki_discover.add_argument("--lock", type=Path, default=DEFAULT_M7_LOCK)
    m7_wiki_discover.add_argument("--output", type=Path)

    m7_wiki_fetch = subparsers.add_parser(
        "m7-wiki-fetch", help="Fetch and persist one bounded Wiki catalog batch"
    )
    m7_wiki_fetch.add_argument("--limit", type=int, default=10)
    m7_wiki_fetch.add_argument("--allow-cap-override", action="store_true")
    m7_wiki_fetch.add_argument("--daily-budget", type=int, default=60)
    m7_wiki_fetch.add_argument("--minimum-delay", type=float, default=15)
    m7_wiki_fetch.add_argument("--maximum-delay", type=float, default=30)
    m7_wiki_fetch.add_argument("--timeout", type=int, default=30)
    m7_wiki_fetch.add_argument("--raw-root", type=Path, default=DEFAULT_M7_RAW_ROOT)
    m7_wiki_fetch.add_argument("--oss-bucket", default=os.environ.get("HKSR_M7_OSS_BUCKET", ""))
    m7_wiki_fetch.add_argument("--oss-endpoint", default=os.environ.get("HKSR_M7_OSS_ENDPOINT", ""))
    m7_wiki_fetch.add_argument("--ram-role", default=os.environ.get("HKSR_M7_RAM_ROLE", ""))
    m7_wiki_fetch.add_argument("--oss-prefix", default="m7/raw")
    m7_wiki_fetch.add_argument("--lock", type=Path, default=DEFAULT_M7_LOCK)
    m7_wiki_fetch.add_argument("--output", type=Path)

    m7_wiki_refresh = subparsers.add_parser(
        "m7-wiki-refresh", help="Recheck one bounded batch of parsed Wiki content"
    )
    m7_wiki_refresh.add_argument("--limit", type=int, default=10)
    m7_wiki_refresh.add_argument("--allow-cap-override", action="store_true")
    m7_wiki_refresh.add_argument("--daily-budget", type=int, default=60)
    m7_wiki_refresh.add_argument("--minimum-delay", type=float, default=15)
    m7_wiki_refresh.add_argument("--maximum-delay", type=float, default=30)
    m7_wiki_refresh.add_argument("--timeout", type=int, default=30)
    m7_wiki_refresh.add_argument("--raw-root", type=Path, default=DEFAULT_M7_RAW_ROOT)
    m7_wiki_refresh.add_argument("--oss-bucket", default=os.environ.get("HKSR_M7_OSS_BUCKET", ""))
    m7_wiki_refresh.add_argument("--oss-endpoint", default=os.environ.get("HKSR_M7_OSS_ENDPOINT", ""))
    m7_wiki_refresh.add_argument("--ram-role", default=os.environ.get("HKSR_M7_RAM_ROLE", ""))
    m7_wiki_refresh.add_argument("--oss-prefix", default="m7/raw")
    m7_wiki_refresh.add_argument("--catalog-key", default="game_catalog:17")
    m7_wiki_refresh.add_argument("--start-new-cycle", action="store_true")
    m7_wiki_refresh.add_argument("--lock", type=Path, default=DEFAULT_M7_LOCK)
    m7_wiki_refresh.add_argument("--output", type=Path)

    m7_review = subparsers.add_parser(
        "m7-review", help="Record a reviewed content disposition without refetching"
    )
    m7_review.add_argument("external_id")
    m7_review.add_argument(
        "disposition", choices=("eligible_evidence", "excluded_operational",
                                "missing_official_text", "manual_review")
    )
    m7_review.add_argument("--reason", required=True)

    m7_report = subparsers.add_parser("m7-report", help="Build a sanitized M7 report")
    m7_report.add_argument("--output", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    database = Database(arguments.database)
    database.initialize()

    if arguments.command == "discover":
        result = {}
        if arguments.manifest:
            result["manifest"] = discover_manifest(database, arguments.manifest)
        if arguments.wiki_query:
            result["wiki_search"] = discover_wiki_search(
                database,
                arguments.wiki_query,
                pages=arguments.pages,
                page_size=arguments.page_size,
                timeout=arguments.timeout,
            )
        if arguments.official_account_uid:
            result["official_account"] = discover_official_account(
                database,
                arguments.official_account_uid,
                pages=arguments.pages,
                page_size=arguments.page_size,
                timeout=arguments.timeout,
            )
        if not result:
            result["manifest"] = discover_manifest(database, DEFAULT_MANIFEST)
    elif arguments.command == "fetch":
        result = fetch_sources(
            database,
            arguments.raw_root,
            force=arguments.force,
            limit=arguments.limit,
            timeout=arguments.timeout,
        )
    elif arguments.command == "parse":
        result = parse_sources(
            database,
            force=arguments.force,
            limit=arguments.limit,
            provider=arguments.provider,
        )
    elif arguments.command == "index":
        result = {
            "fts_rows": database.rebuild_fts(),
            "retrieval": build_retrieval_index(database, arguments.entities),
        }
    elif arguments.command == "status":
        result = database.statistics()
    elif arguments.command == "search":
        result = {
            "query": arguments.query,
            "mode": arguments.mode,
            "results": hybrid_search(
                database,
                arguments.query,
                arguments.limit,
                source_kinds=arguments.source_kind,
                version=arguments.version,
                contexts=arguments.context,
                mode=arguments.mode,
            ),
        }
    elif arguments.command == "intent-search":
        result = intent_search(database, arguments.query, arguments.limit)
    elif arguments.command == "evaluate":
        result = evaluate_retrieval(database, arguments.dataset, arguments.mode)
    elif arguments.command == "ask":
        result = answer_question(
            database,
            arguments.question,
            limit=arguments.limit,
            minimum_score=arguments.minimum_score,
            source_kinds=arguments.source_kind,
            contexts=arguments.context,
        )
    elif arguments.command == "evaluate-qa":
        result = evaluate_answers(database, arguments.dataset)
    elif arguments.command == "m9-baseline":
        result = evaluate_real_questions(
            database, arguments.dataset, arguments.taxonomy, limit=arguments.limit
        )
        if arguments.output:
            write_json_report(arguments.output, result)
    elif arguments.command == "m9-build-identities":
        result = replace_identity_catalog(database, arguments.catalog)
    elif arguments.command == "m9-audit-identities":
        result = audit_identity_catalog(database)
    elif arguments.command == "m9-identities":
        result = {"people": identity_catalog(database, include_pending=arguments.include_pending)}
    elif arguments.command == "build-relations":
        result = build_relations(database, arguments.catalog)
    elif arguments.command == "relations":
        result = {
            "entity": arguments.entity,
            "relations": list_relations(
                database, arguments.entity, include_candidates=arguments.include_candidates
            ),
        }
    elif arguments.command == "audit-relations":
        result = audit_relations(database)
    elif arguments.command == "review-relation":
        result = review_relation(
            database, arguments.relation_id, arguments.status,
            predicate=arguments.predicate, evidence_level=arguments.evidence_level,
            reasoning=arguments.reasoning,
        )
    elif arguments.command == "initialize":
        result = {
            "fts_rows": database.rebuild_fts(),
            "retrieval": build_retrieval_index(database, arguments.entities),
            "relations": build_relations(database, arguments.relations),
        }
    elif arguments.command == "serve":
        try:
            import uvicorn
            from app.api.main import create_app
        except ImportError as error:
            raise SystemExit(
                "Web dependencies are missing; install the project dependencies first"
            ) from error
        uvicorn.run(
            create_app(database_path=arguments.database),
            host=arguments.host,
            port=arguments.port,
        )
        return 0
    elif arguments.command == "capacity-report":
        result = build_capacity_report(
            arguments.database, arguments.raw_root, arguments.assumptions
        )
    elif arguments.command == "m7-discover":
        if arguments.pages > 2 and not arguments.allow_cap_override:
            raise ValueError("raising the two-page cap requires --allow-cap-override")
        policy = CollectionPolicy(
            discovery_pages=arguments.pages, daily_budget=arguments.daily_budget,
            minimum_delay=arguments.minimum_delay, maximum_delay=arguments.maximum_delay,
        )
        with exclusive_lock(arguments.lock):
            result = M7Collector(database, policy=policy).discover(
                arguments.uid, timeout=arguments.timeout
            )
        if arguments.output:
            write_m7_report(arguments.output, result)
    elif arguments.command == "m7-fetch":
        if arguments.limit > 10 and not arguments.allow_cap_override:
            raise ValueError("raising the ten-post cap requires --allow-cap-override")
        policy = CollectionPolicy(
            fetch_posts=arguments.limit, daily_budget=arguments.daily_budget,
            minimum_delay=arguments.minimum_delay, maximum_delay=arguments.maximum_delay,
        )
        uploader = OssRamRoleUploader(
            arguments.oss_bucket, arguments.oss_endpoint, arguments.ram_role
        )
        with exclusive_lock(arguments.lock):
            result = M7Collector(database, policy=policy).fetch(
                arguments.raw_root, uploader, timeout=arguments.timeout,
                object_prefix=arguments.oss_prefix,
            )
        if arguments.output:
            write_m7_report(arguments.output, result)
    elif arguments.command == "m7-wiki-discover":
        with exclusive_lock(arguments.lock, blocking=True):
            result = discover_wiki_catalog(
                database, channel_id=arguments.channel_id, timeout=arguments.timeout
            )
        if arguments.output:
            write_m7_report(arguments.output, result)
    elif arguments.command == "m7-wiki-fetch":
        if arguments.limit > 10 and not arguments.allow_cap_override:
            raise ValueError("raising the ten-content cap requires --allow-cap-override")
        policy = CollectionPolicy(
            fetch_posts=arguments.limit, daily_budget=arguments.daily_budget,
            minimum_delay=arguments.minimum_delay, maximum_delay=arguments.maximum_delay,
        )
        uploader = OssRamRoleUploader(
            arguments.oss_bucket, arguments.oss_endpoint, arguments.ram_role
        )
        with exclusive_lock(arguments.lock):
            result = M7Collector(database, policy=policy).fetch_wiki(
                arguments.raw_root, uploader, timeout=arguments.timeout,
                object_prefix=arguments.oss_prefix,
            )
        if arguments.output:
            write_m7_report(arguments.output, result)
    elif arguments.command == "m7-wiki-refresh":
        if arguments.limit > 10 and not arguments.allow_cap_override:
            raise ValueError("raising the ten-content cap requires --allow-cap-override")
        policy = CollectionPolicy(
            fetch_posts=arguments.limit, daily_budget=arguments.daily_budget,
            minimum_delay=arguments.minimum_delay, maximum_delay=arguments.maximum_delay,
        )
        uploader = OssRamRoleUploader(
            arguments.oss_bucket, arguments.oss_endpoint, arguments.ram_role
        )
        with exclusive_lock(arguments.lock):
            result = M7Collector(database, policy=policy).refresh_wiki(
                arguments.raw_root, uploader, timeout=arguments.timeout,
                object_prefix=arguments.oss_prefix,
                catalog_key=arguments.catalog_key,
                start_new_cycle=arguments.start_new_cycle,
            )
        if arguments.output:
            write_m7_report(arguments.output, result)
    elif arguments.command == "m7-review":
        result = review_disposition(
            database, arguments.external_id, arguments.disposition, arguments.reason
        )
    elif arguments.command == "m7-report":
        result = build_collection_report(database)
        if arguments.output:
            write_m7_report(arguments.output, result)
    elif arguments.command == "cloud-acceptance-report":
        imports = arguments.import_reports or list(DEFAULT_M6B_IMPORT_REPORTS)
        audit = read_json_report(arguments.database_audit) if arguments.database_audit else None
        result = build_acceptance_report(
            procurement=read_json_report(arguments.procurement),
            extension_observation=read_json_report(arguments.extensions),
            operator_evidence=read_json_report(arguments.operator_evidence),
            import_reports=[read_json_report(path) for path in imports],
            database_audit=audit,
        )
        write_acceptance_reports(
            arguments.output_json, arguments.output_markdown, result
        )
    elif arguments.command.startswith("cloud-"):
        config = CloudDatabaseConfig.from_environment()
        if arguments.command == "cloud-discover":
            result = build_environment_report(config)
        elif arguments.command == "cloud-extensions":
            result = probe_extensions(config, allow_mutation=arguments.allow_mutation)
        elif arguments.command == "cloud-migrate":
            result = apply_migrations(config, allow_mutation=arguments.allow_mutation)
        elif arguments.command == "cloud-import-sqlite":
            result = import_official_sqlite(
                config,
                sqlite_path=arguments.database,
                batch_id=arguments.batch_id,
                allow_mutation=arguments.allow_mutation,
            )
        elif arguments.command == "cloud-load-fixture":
            result = load_fixture(
                config,
                run_id=arguments.run_id,
                count=arguments.chunks,
                dimensions=arguments.dimensions,
                allow_mutation=arguments.allow_mutation,
            )
        elif arguments.command == "cloud-benchmark":
            result = run_benchmark(
                config,
                run_id=arguments.run_id,
                query_count=arguments.queries,
                concurrency=arguments.concurrency,
            )
        elif arguments.command == "cloud-cleanup":
            result = cleanup_fixture(
                config,
                run_id=arguments.run_id,
                allow_mutation=arguments.allow_mutation,
            )
        elif arguments.command == "cloud-audit":
            result = build_database_audit(config)
        else:
            raise AssertionError("Unhandled cloud command")
        output = getattr(arguments, "output", None)
        if output:
            write_json_report(output, result)
    else:
        raise AssertionError("Unhandled command")
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
