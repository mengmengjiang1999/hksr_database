"""Optional constrained answer generation with deterministic validation and fallback."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from app.models.database import Database
from app.qa.grounding import _citation
from app.retrieval import intent_search, normalize_text


PROMPT_VERSION = "m9-grounded-answer-v1"
RESPONSE_SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 12.0


class ModelAdapter(Protocol):
    name: str

    def generate(
        self, evidence_packet: Mapping[str, Any], *, prompt: str,
        response_schema: Mapping[str, Any], timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


def response_schema() -> Dict[str, Any]:
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "required": ["answer", "claims"],
        "claim_required": ["text", "type", "supports"],
        "claim_types": ["explicit", "inferred", "conflicted"],
        "support_required": ["evidence_id", "span"],
    }


def build_evidence_packet(
    database: Database, question: str, *, limit: int = 8,
) -> Dict[str, Any]:
    search = intent_search(database, question, limit=limit)
    rows = search["answerable_results"]
    return {
        "schema_version": 1,
        "question": question,
        "intent": search["query_plan"]["intent"],
        "resolved_entities": [
            {"canonical_name": item["canonical_name"], "entity_type": item["entity_type"]}
            for item in search["query_plan"]["entities"]
        ],
        "evidence": [
            {"evidence_id": row["evidence_id"], "text": row["text"],
             "source_title": row["title"], "source_kind": row["source_kind"],
             "url": row["page_url"], "section_path": row["section_path"],
             "version": row["version"]}
            for row in rows
        ],
        "retrieval_status": search["status"],
    }


def render_prompt(packet: Mapping[str, Any]) -> str:
    return (
        "你只能使用 evidence 中的文本回答 question。每条事实声明必须给出 evidence_id "
        "以及逐字存在于对应证据中的 span。不能补充模型记忆；证据不足就返回空 claims。"
        "推断必须绑定至少两条证据并给出 reasoning_steps；冲突必须保留双方说法。"
        "输出必须符合给定 JSON schema。prompt_version=%s" % PROMPT_VERSION
    )


def validate_generated_response(
    packet: Mapping[str, Any], response: Mapping[str, Any]
) -> Dict[str, Any]:
    if not isinstance(response, Mapping):
        return {"accepted": [], "rejected": [{"reasons": ["invalid_schema"]}]}
    if response.get("policy_rejected"):
        return {"accepted": [], "rejected": [{"reasons": ["policy_rejection"]}]}
    if not isinstance(response.get("answer"), str) or not isinstance(response.get("claims"), list):
        return {"accepted": [], "rejected": [{"reasons": ["invalid_schema"]}]}
    evidence = {str(item["evidence_id"]): item for item in packet.get("evidence") or []}
    accepted = []
    rejected = []
    for index, claim in enumerate(response["claims"]):
        reasons: List[str] = []
        if not isinstance(claim, Mapping):
            rejected.append({"index": index, "reasons": ["invalid_schema"]})
            continue
        text = str(claim.get("text", "")).strip()
        claim_type = str(claim.get("type", ""))
        supports = claim.get("supports")
        if not text or claim_type not in {"explicit", "inferred", "conflicted"}:
            reasons.append("invalid_schema")
        if not isinstance(supports, list) or not supports:
            reasons.append("support_required")
            supports = []
        validated_supports = []
        for support in supports:
            if not isinstance(support, Mapping):
                reasons.append("invalid_support")
                continue
            evidence_id = str(support.get("evidence_id", ""))
            span = str(support.get("span", ""))
            row = evidence.get(evidence_id)
            if row is None:
                reasons.append("evidence_not_in_packet")
            elif not span or span not in row["text"]:
                reasons.append("support_span_not_exact")
            else:
                validated_supports.append({"evidence_id": evidence_id, "span": span})
        unique_evidence = {item["evidence_id"] for item in validated_supports}
        if claim_type == "explicit" and validated_supports:
            claim_text = normalize_text(text)
            overlap_supported = any(
                normalize_text(item["span"]) in claim_text
                or _character_bigram_overlap(claim_text, normalize_text(item["span"])) >= 0.15
                for item in validated_supports
            )
            if not overlap_supported:
                reasons.append("claim_not_supported_by_span")
        reasoning = [str(item).strip() for item in claim.get("reasoning_steps") or [] if str(item).strip()]
        if claim_type == "inferred" and (len(unique_evidence) < 2 or not reasoning):
            reasons.append("invalid_inference")
        if claim_type == "conflicted":
            alternatives = claim.get("alternatives")
            if len(unique_evidence) < 2 or not isinstance(alternatives, list) or len(alternatives) < 2:
                reasons.append("invalid_conflict")
            else:
                for alternative in alternatives:
                    if not isinstance(alternative, Mapping):
                        reasons.append("invalid_conflict")
                        continue
                    evidence_id = str(alternative.get("evidence_id", ""))
                    span = str(alternative.get("span", ""))
                    if evidence_id not in unique_evidence or not any(
                        item["evidence_id"] == evidence_id and item["span"] == span
                        for item in validated_supports
                    ):
                        reasons.append("invalid_conflict_alternative")
        if reasons:
            rejected.append({"index": index, "text": text, "reasons": sorted(set(reasons))})
        else:
            accepted.append({"text": text, "type": claim_type, "supports": validated_supports,
                             "reasoning_steps": reasoning,
                             "alternatives": list(claim.get("alternatives") or [])})
    return {"accepted": accepted, "rejected": rejected}


def _character_bigram_overlap(left: str, right: str) -> float:
    def grams(value: str) -> set[str]:
        return {value[index:index + 2] for index in range(max(0, len(value) - 1))}
    left_grams, right_grams = grams(left), grams(right)
    if not left_grams or not right_grams:
        return float(bool(left and right and (left in right or right in left)))
    return len(left_grams & right_grams) / len(right_grams)


class GenerationService:
    def __init__(
        self, adapter: Optional[ModelAdapter] = None, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cache_size: int = 128,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if cache_size < 0 or cache_size > 10_000:
            raise ValueError("cache_size must be between 0 and 10000")
        self.adapter = adapter
        self.timeout_seconds = timeout_seconds
        self.cache_size = cache_size
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._outcomes: Counter[str] = Counter()
        self._requests = 0
        self._latency_ms = 0.0
        self._input_tokens = 0
        self._output_tokens = 0

    def _cache_key(self, packet: Mapping[str, Any]) -> str:
        value = {"prompt_version": PROMPT_VERSION, "packet": packet}
        return hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()

    def telemetry(self) -> Dict[str, Any]:
        return {
            "schema_version": 1, "requests": self._requests,
            "outcomes": dict(sorted(self._outcomes.items())),
            "total_latency_ms": round(self._latency_ms, 3),
            "input_tokens": self._input_tokens, "output_tokens": self._output_tokens,
            "cache_entries": len(self._cache), "cache_limit": self.cache_size,
        }

    def answer(
        self, database: Database, question: str, deterministic: Mapping[str, Any], *, limit: int = 8,
    ) -> Dict[str, Any]:
        packet = build_evidence_packet(database, question, limit=limit)
        fallback = dict(deterministic)
        if self.adapter is None:
            return self._fallback(fallback, "disabled")
        if not packet["evidence"] or packet["retrieval_status"] != "ready":
            return self._fallback(fallback, "insufficient_evidence")
        key = self._cache_key(packet)
        if key in self._cache:
            cached = dict(self._cache[key])
            self._cache.move_to_end(key)
            cached["generation_outcome"] = "cache_hit"
            return cached
        self._requests += 1
        started = time.monotonic()
        try:
            response = self.adapter.generate(
                packet, prompt=render_prompt(packet), response_schema=response_schema(),
                timeout_seconds=self.timeout_seconds,
            )
        except TimeoutError:
            self._latency_ms += (time.monotonic() - started) * 1000
            return self._fallback(fallback, "timeout")
        except Exception:
            self._latency_ms += (time.monotonic() - started) * 1000
            return self._fallback(fallback, "provider_error")
        self._latency_ms += (time.monotonic() - started) * 1000
        usage = response.get("usage") if isinstance(response, Mapping) else None
        if isinstance(usage, Mapping):
            self._input_tokens += max(0, int(usage.get("input_tokens", 0)))
            self._output_tokens += max(0, int(usage.get("output_tokens", 0)))
        validation = validate_generated_response(packet, response)
        reasons = {reason for item in validation["rejected"] for reason in item["reasons"]}
        if "policy_rejection" in reasons:
            return self._fallback(fallback, "policy_rejection")
        if "invalid_schema" in reasons and not validation["accepted"]:
            return self._fallback(fallback, "invalid_schema")
        if not validation["accepted"]:
            return self._fallback(fallback, "empty_validation")
        evidence_ids = list(dict.fromkeys(
            item["evidence_id"]
            for claim in validation["accepted"]
            for item in claim["supports"]
        ))
        rows = {
            row["evidence_id"]: row
            for row in database.retrieval_rows_by_evidence_ids(evidence_ids)
        }
        claims = []
        for claim in validation["accepted"]:
            evidence_ids = list(dict.fromkeys(item["evidence_id"] for item in claim["supports"]))
            claims.append({
                "text": claim["text"], "type": claim["type"], "evidence_ids": evidence_ids,
                "reasoning_steps": claim["reasoning_steps"], "alternatives": claim["alternatives"],
                "support_check": "exact_generated_spans",
                "support_spans": claim["supports"],
                "citations": [_citation(database, rows[item]) for item in evidence_ids],
            })
        result = dict(fallback)
        result.update({
            "status": "inferred" if any(item["type"] == "inferred" for item in claims) else "explicit",
            "answer": "\n".join(item["text"] for item in claims), "claims": claims,
            "rejected_claims": validation["rejected"], "answer_strategy": "constrained_generation",
            "generation_outcome": "validated", "generation_fallback": False,
            "generation_prompt_version": PROMPT_VERSION,
        })
        self._outcomes["validated"] += 1
        if self.cache_size:
            self._cache[key] = dict(result)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return result

    def _fallback(self, result: Dict[str, Any], outcome: str) -> Dict[str, Any]:
        self._outcomes[outcome] += 1
        result.update({"generation_outcome": outcome, "generation_fallback": True,
                       "generation_prompt_version": PROMPT_VERSION})
        return result
