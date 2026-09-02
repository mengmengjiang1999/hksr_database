"""Normalize Wiki and Miyoushe payloads into documents and chunks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.m0_probe import ProbeError, html_to_text, summarize_miyoushe_post_payload


MAX_CHUNK_CHARACTERS = 500
CHUNK_OVERLAP_CHARACTERS = 80
EXCLUDED_SECTION_PATTERN = re.compile(
    r"推荐|攻略|解析|考据|画廊|配队|遗器|光锥|评论|二创"
)
NON_TEXT_KEYS = {
    "id",
    "itemId",
    "tab_id",
    "record_id",
    "originIdx",
    "text_map_type",
    "source_type",
    "textMapMeta",
    "imageMeta",
    "audioUrl",
    "audio_name",
    "url",
    "icon",
    "image",
    "figurePath",
    "path",
    "status",
    "version",
}


@dataclass(frozen=True)
class ParsedSource:
    metadata: Mapping[str, Any]
    documents: Sequence[Mapping[str, Any]]


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


def _walk_strings(value: Any) -> Iterable[str]:
    value = _decode_json(value)
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return
        if re.search(r"\.(png|jpe?g|webp|gif|wav|mp3|mp4)$", value, re.IGNORECASE):
            return
        if re.fullmatch(r"\d{10,}(?:_\d+)?", value) or value.startswith("RpgTextMap"):
            return
        value = value.replace("\\n", "\n").replace("\\t", "\t")
        text = html_to_text(value) if "<" in value and ">" in value else value
        normalized = "\n".join(
            " ".join(line.split()) for line in text.splitlines() if line.strip()
        )
        if normalized:
            yield normalized
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in NON_TEXT_KEYS:
                continue
            yield from _walk_strings(child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for child in value:
            yield from _walk_strings(child)


def _deduplicate(values: Iterable[str]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def split_chunks(text: str, max_characters: int = MAX_CHUNK_CHARACTERS) -> List[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if not paragraphs:
        return []
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces: List[str] = []
        remaining = paragraph
        while len(remaining) > max_characters:
            boundary = max(
                remaining.rfind(mark, 0, max_characters)
                for mark in ("。", "！", "？", "；", "，")
            )
            if boundary < max_characters // 2:
                boundary = max_characters
            else:
                boundary += 1
            pieces.append(remaining[:boundary].strip())
            remaining = remaining[max(0, boundary - CHUNK_OVERLAP_CHARACTERS) :].strip()
        if remaining:
            pieces.append(remaining)

        for piece in pieces:
            candidate = "%s\n%s" % (current, piece) if current else piece
            if len(candidate) <= max_characters:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def extract_speakers(text: str) -> List[str]:
    """Extract explicit ``speaker：dialogue`` labels without inventing speakers."""
    output: List[str] = []
    seen = set()
    for line in text.splitlines():
        match = re.match(r"^([^：\n]{1,20})：", line.strip())
        if not match:
            continue
        speaker = match.group(1).strip("「」【】()（） ")
        if (
            speaker in {"解锁条件", "适用角色", "任务名", "任务地区", "任务类型", "任务描述"}
            or len(speaker) > 12
            or re.search(r"[！？!?。；;]", speaker)
        ):
            continue
        if speaker and speaker not in seen:
            seen.add(speaker)
            output.append(speaker)
    return output


def _make_chunks(
    text: str, section_path: str, extract_dialogue_speakers: bool = False
) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for position, chunk_text in enumerate(split_chunks(text)):
        digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        speakers = extract_speakers(chunk_text) if extract_dialogue_speakers else []
        chunks.append(
            {
                "chunk_key": "%s:%04d" % (digest[:12], position),
                "section_path": section_path,
                "speaker": "、".join(speakers),
                "text": chunk_text,
                "position": position,
                "content_sha256": digest,
                "metadata": {"speakers": speakers},
            }
        )
    return chunks


def _wiki_metadata(content: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "title": content.get("title", ""),
        "version": str(content.get("version")) if content.get("version") is not None else None,
        "created_at": content.get("ctime"),
        "updated_at": content.get("mtime"),
        "official_status": "wiki",
    }


def _parse_wiki(payload: Mapping[str, Any], source_kind: str) -> ParsedSource:
    if payload.get("retcode") != 0:
        raise ProbeError("Wiki API returned a non-zero retcode")
    content = payload.get("data", {}).get("content")
    if not isinstance(content, Mapping):
        raise ProbeError("Wiki response is missing data.content")
    title = content.get("title")
    if not title:
        raise ProbeError("Wiki content has no title")

    documents: List[Dict[str, Any]] = []
    rpg = content.get("rpg_new_tmp_content")
    if isinstance(rpg, Mapping):
        for position, module in enumerate(rpg.get("modules") or []):
            if module.get("switch") is True:
                continue
            section_name = module.get("name") or "未命名模块"
            eligible = not bool(EXCLUDED_SECTION_PATTERN.search(section_name))
            components = module.get("components") or []
            values: List[Any] = [component.get("data", "") for component in components]
            text = "\n".join(_deduplicate(_walk_strings(values)))
            section_path = "%s/%s" % (title, section_name)
            documents.append(
                {
                    "document_key": "module:%s" % (module.get("id") or position),
                    "title": section_name,
                    "section_path": section_path,
                    "content_type": "wiki_rpg_module",
                    "position": position,
                    "evidence_eligible": eligible,
                    "metadata": {
                        "source_kind": source_kind,
                        "component_ids": [
                            component.get("componentId", "") for component in components
                        ],
                    },
                    "chunks": _make_chunks(text, section_path) if eligible else [],
                }
            )
    else:
        for position, tab in enumerate(content.get("contents") or []):
            section_name = tab.get("name") or "页签%d" % (position + 1)
            text = html_to_text(tab.get("text") or "")
            section_path = "%s/%s" % (title, section_name)
            documents.append(
                {
                    "document_key": "tab:%04d" % position,
                    "title": section_name,
                    "section_path": section_path,
                    "content_type": "wiki_html_tab",
                    "position": position,
                    "evidence_eligible": True,
                    "metadata": {"source_kind": source_kind},
                    "chunks": _make_chunks(
                        text,
                        section_path,
                        extract_dialogue_speakers=source_kind == "wiki_quest",
                    ),
                }
            )

    if not documents:
        raise ProbeError("Wiki content produced no documents")
    return ParsedSource(metadata=_wiki_metadata(content), documents=documents)


def _parse_miyoushe(payload: Mapping[str, Any], source_kind: str) -> ParsedSource:
    summary = summarize_miyoushe_post_payload(payload)
    outer = payload["data"]["post"]
    post = outer["post"]
    text = html_to_text(post.get("content") or "")
    if not text:
        text = "\n".join(_deduplicate(_walk_strings(post.get("structured_content") or "")))
    section_path = "%s/正文" % summary["title"]
    document = {
        "document_key": "body",
        "title": "正文",
        "section_path": section_path,
        "content_type": "official_video_post" if summary["video_count"] else "official_article",
        "position": 0,
        "evidence_eligible": True,
        "metadata": {
            "source_kind": source_kind,
            "publisher": summary["publisher"],
            "certification": summary["certification"],
            "video_ids": summary["video_ids"],
            "has_machine_readable_subtitles": summary[
                "has_machine_readable_subtitles"
            ],
        },
        "chunks": _make_chunks(text, section_path),
    }
    return ParsedSource(
        metadata={
            "title": summary["title"],
            "version": None,
            "created_at": summary["created_at"],
            "updated_at": summary["updated_at"],
            "official_status": "verified",
        },
        documents=[document],
    )


def parse_source_payload(
    parser: str, payload: Mapping[str, Any], source_kind: str
) -> ParsedSource:
    if parser == "wiki_content":
        return _parse_wiki(payload, source_kind)
    if parser == "miyoushe_post":
        return _parse_miyoushe(payload, source_kind)
    raise ProbeError("Unknown parser: %s" % parser)
