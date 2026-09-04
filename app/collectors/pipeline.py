"""M1 discovery, fetch, and parse pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from app.m0_probe import ProbeError, fetch_json
from app.models.database import Database
from app.parsers import parse_source_payload


WIKI_CATALOG_URL = (
    "https://act-api-takumi-static.mihoyo.com/common/blackboard/"
    "sr_wiki/v1/home/content/list"
)
WIKI_PAGE_URL = (
    "https://bbs.mihoyo.com/sr/wiki/content/{content_id}/detail"
    "?bbs_presentation_style=no_header"
)
WIKI_DETAIL_URL = (
    "https://act-api-takumi-static.mihoyo.com/common/blackboard/"
    "sr_wiki/v1/content/info?app_sn=sr_wiki&content_id={content_id}"
)
WIKI_EDITORIAL_CHANNELS = {"攻略"}
WIKI_CHANNEL_SOURCE_KINDS = {
    "角色": "wiki_character",
    "黄金裔": "wiki_character",
    "黄金裔WIKI": "wiki_character",
    "光锥": "wiki_light_cone",
    "遗器": "wiki_relic",
    "敌对物种": "wiki_enemy",
    "家具": "wiki_furniture",
    "成就攻略": "wiki_achievement",
    "任务": "wiki_quest",
    "装扮": "wiki_outfit",
    "养成材料": "wiki_material",
    "其他材料": "wiki_material",
    "消耗品": "wiki_consumable",
    "任务道具": "wiki_quest_item",
    "贵重物": "wiki_valuable",
    "逐光捡金": "wiki_endgame",
    "模拟宇宙": "wiki_simulated_universe",
    "模拟宇宙·事件图鉴": "wiki_simulated_universe",
    "活动": "wiki_event",
    "阅读物": "wiki_readable",
    "特殊道具": "wiki_special_item",
    "商店": "wiki_shop",
    "委托": "wiki_assignment",
    "战利品收集": "wiki_collectible",
    "负世泰坦": "wiki_enemy",
    "梦境护照": "wiki_dreamscape_pass",
    "狸狸社刊": "wiki_periodical",
}
WIKI_CHANNEL_PRIORITY = {
    name: position for position, name in enumerate(WIKI_CHANNEL_SOURCE_KINDS)
}


def _source_identity(target: Mapping[str, Any]) -> Dict[str, str]:
    query = parse_qs(urlparse(target["api_url"]).query)
    if target["parser"] == "wiki_content":
        provider = "mihoyo_wiki"
        external_id = (query.get("content_id") or [""])[0]
    elif target["parser"] == "miyoushe_post":
        provider = "miyoushe"
        external_id = (query.get("post_id") or [""])[0]
    else:
        raise ProbeError("Unknown parser in manifest: %s" % target["parser"])
    if not external_id:
        raise ProbeError("Target API URL is missing its external id")
    return {"provider": provider, "external_id": external_id}


def discover_manifest(database: Database, manifest_path: Path) -> Dict[str, int]:
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    discovered = 0
    source_ids = set()
    for target in manifest.get("targets", []):
        identity = _source_identity(target)
        source_id = database.upsert_source(
            {
                **identity,
                "source_kind": target["source_kind"],
                "parser": target["parser"],
                "page_url": target["page_url"],
                "api_url": target["api_url"],
                "headers": target.get("headers") or {},
                "expected_title": target.get("expected_title", ""),
            }
        )
        source_ids.add(source_id)
        discovered += 1
    return {"manifest_targets": discovered, "unique_sources": len(source_ids)}


def _wiki_source_kind(channels: List[Mapping[str, Any]]) -> str:
    names = {channel.get("name") for channel in channels}
    if "角色" in names:
        return "wiki_character"
    if "阅读物" in names:
        return "wiki_readable"
    if "任务" in names:
        return "wiki_quest"
    return "wiki_content"


def discover_wiki_search(
    database: Database,
    query: str,
    pages: int = 1,
    page_size: int = 20,
    timeout: int = 30,
) -> Dict[str, int]:
    registered_ids = set()
    result = {"pages": 0, "results": 0, "registered": 0, "skipped_articles": 0}
    for page in range(1, pages + 1):
        api_url = (
            "https://act-api-takumi.mihoyo.com/common/blackboard/sr_wiki/"
            "v1/search/content?"
            + urlencode(
                {
                    "app_sn": "sr_wiki",
                    "keyword": query,
                    "page": page,
                    "page_size": page_size,
                }
            )
        )
        fetched = fetch_json(api_url, timeout=timeout)
        if fetched.payload.get("retcode") != 0:
            raise ProbeError("Wiki search returned a non-zero retcode")
        items = fetched.payload.get("data", {}).get("list") or []
        result["pages"] += 1
        result["results"] += len(items)
        for item in items:
            page_url = item.get("bbs_url", "")
            match = re.search(r"/wiki/content/(\d+)/detail", page_url)
            if match is None:
                if "/article/" in page_url:
                    result["skipped_articles"] += 1
                continue
            external_id = match.group(1)
            source_id = database.upsert_source(
                {
                    "provider": "mihoyo_wiki",
                    "external_id": external_id,
                    "source_kind": _wiki_source_kind(item.get("channels") or []),
                    "parser": "wiki_content",
                    "page_url": page_url,
                    "api_url": (
                        "https://act-api-takumi-static.mihoyo.com/common/blackboard/"
                        "sr_wiki/v1/content/info?app_sn=sr_wiki&content_id=" + external_id
                    ),
                    "headers": {},
                    "expected_title": item.get("title", ""),
                }
            )
            registered_ids.add(source_id)
        if len(items) < page_size:
            break
    result["registered"] = len(registered_ids)
    return result


def discover_wiki_catalog(
    database: Database,
    channel_id: int = 17,
    timeout: int = 180,
) -> Dict[str, Any]:
    """Register every unique Wiki game-catalog content ID from one directory response."""
    api_url = WIKI_CATALOG_URL + "?" + urlencode(
        {"app_sn": "sr_wiki", "channel_id": channel_id}
    )
    fetched = fetch_json(api_url, timeout=timeout)
    payload = fetched.payload
    if payload.get("retcode") != 0 or not isinstance(payload.get("data"), Mapping):
        raise ProbeError("Wiki catalog returned a non-zero retcode or malformed data")
    roots = payload["data"].get("list")
    if not isinstance(roots, list):
        raise ProbeError("Wiki catalog root list is malformed")
    root = next((item for item in roots if item.get("id") == channel_id), None)
    if not isinstance(root, Mapping) or not isinstance(root.get("children"), list):
        raise ProbeError("Wiki game-catalog root is missing or malformed")

    by_content: Dict[str, Dict[str, Any]] = {}
    channel_counts: Dict[str, int] = {}
    task_types: Dict[str, int] = {}
    task_untyped = 0
    excluded_channels: List[str] = []
    directory_items = 0
    skipped_missing_id = 0
    for channel in root["children"]:
        if not isinstance(channel, Mapping):
            raise ProbeError("Wiki catalog channel is malformed")
        name = str(channel.get("name") or "")
        if name in WIKI_EDITORIAL_CHANNELS:
            excluded_channels.append(name)
            continue
        items = channel.get("list") or []
        if not isinstance(items, list):
            raise ProbeError("Wiki catalog channel list is malformed")
        channel_counts[name] = len(items)
        directory_items += len(items)
        for item in items:
            if not isinstance(item, Mapping) or not item.get("content_id"):
                skipped_missing_id += 1
                continue
            external_id = str(item["content_id"])
            if name == "任务":
                item_types: List[str] = []
                try:
                    extension = json.loads(str(item.get("ext") or "{}"))
                    filters = json.loads(
                        extension.get("c_25", {})
                        .get("filter", {})
                        .get("text", "[]")
                    )
                    item_types = [
                        value.split("/", 1)[1]
                        for value in filters
                        if isinstance(value, str) and value.startswith("类型/")
                    ]
                except (TypeError, ValueError, json.JSONDecodeError):
                    item_types = []
                if item_types:
                    for item_type in item_types:
                        task_types[item_type] = task_types.get(item_type, 0) + 1
                else:
                    task_untyped += 1
            entry = by_content.setdefault(
                external_id,
                {"title": str(item.get("title") or ""), "channels": []},
            )
            entry["channels"].append(name)

    existing = {
        str(row["external_id"])
        for row in database.list_sources()
        if row["provider"] == "mihoyo_wiki"
    }
    targets = []
    for external_id, entry in sorted(by_content.items(), key=lambda value: int(value[0])):
        primary_channel = min(
            entry["channels"],
            key=lambda name: (WIKI_CHANNEL_PRIORITY.get(name, 10_000), name),
        )
        targets.append(
            {
                "provider": "mihoyo_wiki",
                "external_id": external_id,
                "source_kind": WIKI_CHANNEL_SOURCE_KINDS.get(
                    primary_channel, "wiki_content"
                ),
                "parser": "wiki_content",
                "page_url": WIKI_PAGE_URL.format(content_id=external_id),
                "api_url": WIKI_DETAIL_URL.format(content_id=external_id),
                "headers": {},
                "expected_title": entry["title"],
                "official_status": "verified",
            }
        )
    database.upsert_sources(targets)
    duplicate_ids = sum(1 for entry in by_content.values() if len(entry["channels"]) > 1)
    return {
        "channel_id": channel_id,
        "channels": channel_counts,
        "task_types": dict(sorted(task_types.items())),
        "task_untyped": task_untyped,
        "directory_items": directory_items,
        "unique_sources": len(targets),
        "new_sources": len(set(by_content) - existing),
        "existing_sources": len(set(by_content) & existing),
        "duplicate_ids": duplicate_ids,
        "duplicate_occurrences": directory_items - len(targets) - skipped_missing_id,
        "skipped_missing_id": skipped_missing_id,
        "excluded_channels": sorted(excluded_channels),
    }


def discover_official_account(
    database: Database,
    uid: str,
    pages: int = 1,
    page_size: int = 20,
    timeout: int = 30,
) -> Dict[str, int]:
    registered_ids = set()
    result = {"pages": 0, "results": 0, "registered": 0, "skipped_unverified": 0}
    offset = ""
    headers = {
        "Origin": "https://www.miyoushe.com",
        "Referer": "https://www.miyoushe.com/",
    }
    for _ in range(pages):
        parameters = {"size": page_size, "uid": uid}
        if offset:
            parameters["offset"] = offset
        api_url = (
            "https://bbs-api.miyoushe.com/painter/wapi/userPostList?"
            + urlencode(parameters)
        )
        fetched = fetch_json(api_url, headers=headers, timeout=timeout)
        if fetched.payload.get("retcode") != 0:
            raise ProbeError("Official account list returned a non-zero retcode")
        data = fetched.payload.get("data", {})
        items = data.get("list") or []
        result["pages"] += 1
        result["results"] += len(items)
        for item in items:
            post = item.get("post") or {}
            user = item.get("user") or {}
            certification = user.get("certification") or {}
            status = post.get("post_status") or {}
            if "官方账号" not in certification.get("label", "") or not status.get(
                "is_official"
            ):
                result["skipped_unverified"] += 1
                continue
            post_id = str(post.get("post_id", ""))
            if not post_id:
                continue
            source_id = database.upsert_source(
                {
                    "provider": "miyoushe",
                    "external_id": post_id,
                    "source_kind": "official_video"
                    if item.get("vod_list")
                    else "official_article",
                    "parser": "miyoushe_post",
                    "page_url": "https://www.miyoushe.com/sr/article/" + post_id,
                    "api_url": (
                        "https://bbs-api.miyoushe.com/post/wapi/getPostFull?"
                        "gids=6&post_id=%s&read=1" % post_id
                    ),
                    "headers": headers,
                    "expected_title": post.get("subject", ""),
                }
            )
            registered_ids.add(source_id)
        if data.get("is_last"):
            break
        offset = str(data.get("next_offset") or "")
        if not offset:
            break
    result["registered"] = len(registered_ids)
    return result


def _raw_path(raw_root: Path, provider: str, external_id: str) -> Path:
    return raw_root / provider / (external_id + ".json")


def content_fingerprint(parser: str, payload: Mapping[str, Any]) -> str:
    if parser == "wiki_content":
        stable: Any = payload.get("data", {}).get("content")
    elif parser == "miyoushe_post":
        outer = payload.get("data", {}).get("post", {})
        post = outer.get("post", {})
        user = outer.get("user", {})
        stable = {
            "post": {
                key: post.get(key)
                for key in (
                    "post_id",
                    "subject",
                    "content",
                    "created_at",
                    "updated_at",
                    "view_type",
                    "post_status",
                    "is_deleted",
                )
            },
            "user": {
                "uid": user.get("uid"),
                "nickname": user.get("nickname"),
                "certification": user.get("certification"),
            },
            "forum": outer.get("forum"),
            "videos": [
                {
                    "id": item.get("id"),
                    "duration": item.get("duration"),
                    "transcoding_status": item.get("transcoding_status"),
                    "review_status": item.get("review_status"),
                }
                for item in outer.get("vod_list") or []
            ],
        }
    else:
        raise ProbeError("Unknown parser for content fingerprint: %s" % parser)
    canonical = json.dumps(
        stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def fetch_sources(
    database: Database,
    raw_root: Path,
    force: bool = False,
    limit: Optional[int] = None,
    timeout: int = 30,
) -> Dict[str, int]:
    statuses = None if force else ["discovered", "fetched", "parsed", "error"]
    sources = database.list_sources(statuses=statuses, limit=limit)
    result = {"attempted": 0, "fetched": 0, "changed": 0, "unchanged": 0, "failed": 0}
    for source in sources:
        result["attempted"] += 1
        try:
            fetched = fetch_json(
                source["api_url"],
                headers=json.loads(source["headers_json"] or "{}"),
                timeout=timeout,
            )
            expected = source["expected_title"]
            if expected:
                if source["parser"] == "wiki_content":
                    actual = fetched.payload.get("data", {}).get("content", {}).get("title")
                else:
                    actual = (
                        fetched.payload.get("data", {})
                        .get("post", {})
                        .get("post", {})
                        .get("subject")
                    )
                if actual != expected:
                    raise ProbeError(
                        "Expected title %r, received %r" % (expected, actual)
                    )

            path = _raw_path(raw_root, source["provider"], source["external_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            canonical = json.dumps(
                fetched.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            temporary = path.with_suffix(".json.tmp")
            temporary.write_bytes(canonical)
            temporary.replace(path)
            canonical_sha256 = hashlib.sha256(canonical).hexdigest()
            semantic_sha256 = content_fingerprint(source["parser"], fetched.payload)
            changed = database.record_fetch(
                int(source["id"]),
                path,
                canonical_sha256,
                len(canonical),
                content_sha256=semantic_sha256,
            )
            result["fetched"] += 1
            result["changed" if changed else "unchanged"] += 1
        except (OSError, ProbeError) as error:
            database.mark_error(int(source["id"]), str(error))
            result["failed"] += 1
    return result


def parse_sources(
    database: Database,
    force: bool = False,
    limit: Optional[int] = None,
    provider: Optional[str] = None,
) -> Dict[str, int]:
    statuses = ["fetched", "parsed"] if force else ["fetched"]
    sources = database.list_parseable_sources(
        statuses=statuses, limit=limit, provider=provider
    )
    result = {
        "attempted": 0, "parsed": 0, "documents": 0, "chunks": 0,
        "failed": 0, "skipped_ineligible": 0,
    }
    for source in sources:
        result["attempted"] += 1
        try:
            raw_path = source["raw_path"]
            if not raw_path:
                raise ProbeError("Source has no raw response path")
            with Path(raw_path).open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            parsed = parse_source_payload(source["parser"], payload, source["source_kind"])
            counts = database.replace_documents(
                int(source["id"]), parsed.metadata, parsed.documents
            )
            result["parsed"] += 1
            result["documents"] += counts["documents"]
            result["chunks"] += counts["chunks"]
        except (OSError, json.JSONDecodeError, ProbeError) as error:
            database.mark_error(int(source["id"]), str(error))
            result["failed"] += 1
    return result
