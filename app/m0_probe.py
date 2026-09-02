"""M0 feasibility probes for official Wiki and Miyoushe sources.

The probe intentionally stores only metadata and extraction statistics. Raw
responses are held in memory so that a feasibility run does not create a local
mirror of the source material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MANIFEST = Path("data/m0/sample-manifest.json")
DEFAULT_REPORT = Path("data/m0/latest-probe-report.json")
DEFAULT_TIMEOUT_SECONDS = 30


class ProbeError(RuntimeError):
    """Raised when a source response does not satisfy the expected contract."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    parser.close()
    return "\n".join(parser.parts)


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _walk_text(value: Any) -> Iterable[str]:
    value = _decode_json(value)
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return
        text = html_to_text(value) if "<" in value and ">" in value else value
        normalized = " ".join(text.split())
        if normalized:
            yield normalized
        return
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_text(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for child in value:
            yield from _walk_text(child)


def _text_statistics(values: Iterable[str]) -> Dict[str, int]:
    text_values = list(values)
    return {
        "text_value_count": len(text_values),
        "text_character_count": sum(len(value) for value in text_values),
    }


def _flatten_channel_names(channel_list: Any) -> List[str]:
    names: List[str] = []
    for group in channel_list or []:
        for channel in group.get("slice", []):
            name = channel.get("name")
            if name and name not in names:
                names.append(name)
    return names


def summarize_wiki_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if payload.get("retcode") != 0:
        raise ProbeError("Wiki API returned a non-zero retcode")
    data = payload.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("content"), Mapping):
        raise ProbeError("Wiki response is missing data.content")

    content = data["content"]
    content_id = content.get("id")
    title = content.get("title")
    if not content_id or not title:
        raise ProbeError("Wiki content is missing an id or title")

    rpg = content.get("rpg_new_tmp_content")
    contents = content.get("contents") or []
    module_summaries: List[Dict[str, Any]] = []
    text_sources: List[Any] = []

    if isinstance(rpg, Mapping):
        layout = "rpg_template"
        for module in rpg.get("modules", []):
            components = module.get("components") or []
            module_summaries.append(
                {
                    "id": str(module.get("id", "")),
                    "name": module.get("name", ""),
                    "hidden": bool(module.get("switch", False)),
                    "components": [item.get("componentId", "") for item in components],
                }
            )
            for component in components:
                text_sources.append(component.get("data", ""))
        text_sources.append(rpg.get("base", {}))
    elif isinstance(contents, list) and contents:
        layout = "html_tabs"
        for tab in contents:
            module_summaries.append(
                {
                    "id": "",
                    "name": tab.get("name", ""),
                    "hidden": False,
                    "components": ["html"],
                }
            )
            text_sources.append(tab.get("text", ""))
    else:
        layout = "empty"

    return {
        "provider": "mihoyo_wiki",
        "source_id": str(content_id),
        "title": title,
        "summary": content.get("summary", ""),
        "version": content.get("version"),
        "created_at": content.get("ctime"),
        "updated_at": content.get("mtime"),
        "template_type": content.get("tmp_type"),
        "layout": layout,
        "channels": _flatten_channel_names(data.get("channel_list")),
        "modules": module_summaries,
        "text": _text_statistics(_walk_text(text_sources)),
    }


def _subtitle_fields(value: Any, prefix: str = "") -> List[str]:
    fields: List[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = "%s.%s" % (prefix, key) if prefix else str(key)
            if re.search(r"subtitle|caption", str(key), re.IGNORECASE):
                fields.append(path)
            fields.extend(_subtitle_fields(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(_subtitle_fields(child, "%s[%d]" % (prefix, index)))
    return fields


def summarize_miyoushe_post_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if payload.get("retcode") != 0:
        raise ProbeError("Miyoushe API returned a non-zero retcode")
    outer = payload.get("data", {}).get("post")
    if not isinstance(outer, Mapping):
        raise ProbeError("Miyoushe response is missing data.post")
    post = outer.get("post")
    user = outer.get("user")
    if not isinstance(post, Mapping) or not isinstance(user, Mapping):
        raise ProbeError("Miyoushe response is missing post or user metadata")

    status = post.get("post_status") or {}
    certification = user.get("certification") or {}
    official = bool(status.get("is_official")) and "官方账号" in certification.get(
        "label", ""
    )
    if not official:
        raise ProbeError("Post is not verified as an official account source")

    content = post.get("content") or ""
    structured_content = _decode_json(post.get("structured_content") or "")
    vod_list = outer.get("vod_list") or []
    subtitle_fields = sorted(set(_subtitle_fields(outer)))

    return {
        "provider": "miyoushe",
        "source_id": str(post.get("post_id", "")),
        "title": post.get("subject", ""),
        "created_at": post.get("created_at"),
        "updated_at": post.get("updated_at"),
        "view_type": post.get("view_type"),
        "official": official,
        "publisher": user.get("nickname", ""),
        "certification": certification.get("label", ""),
        "forum": (outer.get("forum") or {}).get("name", ""),
        "video_count": len(vod_list),
        "video_ids": [str(item.get("id", "")) for item in vod_list],
        "subtitle_fields": subtitle_fields,
        "has_machine_readable_subtitles": bool(subtitle_fields),
        "text": _text_statistics(_walk_text([content, structured_content])),
    }


def summarize_wiki_search_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if payload.get("retcode") != 0:
        raise ProbeError("Wiki search returned a non-zero retcode")
    data = payload.get("data") or {}
    results = data.get("list") or []
    channel_counts: Dict[str, int] = {}
    for result in results:
        for channel in result.get("channels") or []:
            name = channel.get("name", "unknown")
            channel_counts[name] = channel_counts.get(name, 0) + 1
    return {
        "result_count": len(results),
        "reported_total": data.get("total"),
        "channel_counts": dict(sorted(channel_counts.items())),
        "has_wiki_results": any("/wiki/content/" in item.get("bbs_url", "") for item in results),
        "has_article_results": any("/article/" in item.get("bbs_url", "") for item in results),
    }


def summarize_official_account_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if payload.get("retcode") != 0:
        raise ProbeError("Official account list returned a non-zero retcode")
    results = payload.get("data", {}).get("list") or []
    official_count = 0
    video_count = 0
    for result in results:
        certification = result.get("user", {}).get("certification") or {}
        if "官方账号" in certification.get("label", ""):
            official_count += 1
        if result.get("vod_list"):
            video_count += 1
    return {
        "result_count": len(results),
        "official_result_count": official_count,
        "video_result_count": video_count,
        "has_next_page": not bool(payload.get("data", {}).get("is_last", True)),
        "next_offset_present": bool(payload.get("data", {}).get("next_offset")),
    }


@dataclass(frozen=True)
class FetchResult:
    payload: Mapping[str, Any]
    sha256: str
    byte_count: int


def fetch_json(
    url: str,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> FetchResult:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; hksr-m0-feasibility/0.1)",
    }
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        raise ProbeError("HTTP %d for %s" % (error.code, url)) from error
    except URLError as error:
        raise ProbeError("Network error for %s: %s" % (url, error.reason)) from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProbeError("Response is not valid UTF-8 JSON: %s" % url) from error
    return FetchResult(
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
    )


def _probe_target(target: Mapping[str, Any], timeout: int) -> Dict[str, Any]:
    headers = target.get("headers") or {}
    fetched = fetch_json(target["api_url"], headers=headers, timeout=timeout)
    parser = target["parser"]
    if parser == "wiki_content":
        summary = summarize_wiki_payload(fetched.payload)
    elif parser == "miyoushe_post":
        summary = summarize_miyoushe_post_payload(fetched.payload)
    else:
        raise ProbeError("Unknown target parser: %s" % parser)

    expected_title = target.get("expected_title")
    if expected_title and summary.get("title") != expected_title:
        raise ProbeError(
            "Expected title %r, received %r" % (expected_title, summary.get("title"))
        )
    return {
        "key": target["key"],
        "source_kind": target["source_kind"],
        "page_url": target["page_url"],
        "api_url": target["api_url"],
        "status": "pass",
        "response": {"byte_count": fetched.byte_count, "sha256": fetched.sha256},
        "extraction": summary,
    }


def run_live_probe(manifest: Mapping[str, Any], timeout: int) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for target in manifest.get("targets", []):
        try:
            results.append(_probe_target(target, timeout))
        except ProbeError as error:
            results.append(
                {
                    "key": target.get("key"),
                    "source_kind": target.get("source_kind"),
                    "page_url": target.get("page_url"),
                    "api_url": target.get("api_url"),
                    "status": "fail",
                    "error": str(error),
                }
            )

    discovery_results: List[Dict[str, Any]] = []
    for discovery in manifest.get("discovery", []):
        try:
            fetched = fetch_json(
                discovery["api_url"],
                headers=discovery.get("headers") or {},
                timeout=timeout,
            )
            if discovery["parser"] == "wiki_search":
                summary = summarize_wiki_search_payload(fetched.payload)
            elif discovery["parser"] == "official_account":
                summary = summarize_official_account_payload(fetched.payload)
            else:
                raise ProbeError("Unknown discovery parser: %s" % discovery["parser"])
            discovery_results.append(
                {
                    "key": discovery["key"],
                    "status": "pass",
                    "response": {
                        "byte_count": fetched.byte_count,
                        "sha256": fetched.sha256,
                    },
                    "summary": summary,
                }
            )
        except ProbeError as error:
            discovery_results.append(
                {"key": discovery.get("key"), "status": "fail", "error": str(error)}
            )

    passed_targets = sum(item["status"] == "pass" for item in results)
    passed_discovery = sum(item["status"] == "pass" for item in discovery_results)
    target_count = len(results)
    discovery_count = len(discovery_results)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_version": manifest.get("manifest_version"),
        "summary": {
            "target_count": target_count,
            "passed_targets": passed_targets,
            "discovery_count": discovery_count,
            "passed_discovery": passed_discovery,
            "m0_threshold_met": passed_targets >= 4 and passed_discovery == discovery_count,
        },
        "targets": results,
        "discovery": discovery_results,
    }


def load_manifest(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    keys = [item.get("key") for item in manifest.get("targets", [])]
    if not keys or len(keys) != len(set(keys)):
        raise ProbeError("Manifest target keys must be present and unique")
    return manifest


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(arguments.manifest)
        report = run_live_probe(manifest, arguments.timeout)
        write_report(arguments.output, report)
    except (OSError, ProbeError) as error:
        print("M0 probe failed: %s" % error, file=sys.stderr)
        return 2

    summary = report["summary"]
    print(
        "M0 probe: %d/%d targets, %d/%d discovery checks passed"
        % (
            summary["passed_targets"],
            summary["target_count"],
            summary["passed_discovery"],
            summary["discovery_count"],
        )
    )
    print("Report: %s" % arguments.output)
    return 0 if summary["m0_threshold_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
