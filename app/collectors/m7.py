"""Slow, resumable Miyoushe collection for the private ECS runtime."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Protocol, Sequence
from urllib.parse import urlencode

from app.collectors.pipeline import content_fingerprint
from app.models.database import Database


CLASSIFIER_VERSION = "m7-v1"
DISPOSITIONS = {
    "eligible_evidence",
    "excluded_operational",
    "missing_official_text",
    "manual_review",
    "excluded_unavailable",
    "excluded_unverified",
}
OPERATIONAL_TERMS = (
    "活动公告", "维护公告", "版本更新", "获奖名单", "社区活动", "签到福利", "抽奖",
)
SENSITIVE_REPORT_KEYS = {
    "account_uid",
    "access_key", "access_key_id", "access_key_secret", "authorization", "cookie",
    "endpoint", "host", "hostname", "password", "raw", "raw_body", "resource_id",
    "security_token", "secret", "token",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _budget_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class CollectionPolicy:
    discovery_pages: int = 2
    fetch_posts: int = 10
    minimum_delay: float = 15.0
    maximum_delay: float = 30.0
    daily_budget: int = 60
    attempts: int = 3
    failure_threshold: int = 3

    def __post_init__(self) -> None:
        if self.discovery_pages <= 0 or self.fetch_posts <= 0:
            raise ValueError("batch caps must be positive")
        if self.minimum_delay < 0 or self.maximum_delay < self.minimum_delay:
            raise ValueError("invalid delay bounds")
        if self.daily_budget < 0 or self.attempts <= 0 or self.failure_threshold <= 0:
            raise ValueError("budgets must be positive")


@dataclass(frozen=True)
class RemoteResponse:
    payload: Mapping[str, Any]
    status: int = 200


class RemoteFailure(RuntimeError):
    def __init__(self, message: str, *, status: Optional[int] = None,
                 retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class RawUploader(Protocol):
    def upload(self, object_key: str, body: bytes) -> Mapping[str, Optional[str]]:
        ...


def _retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def fetch_remote_json(url: str, headers: Mapping[str, str], timeout: int) -> RemoteResponse:
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise RemoteFailure("response JSON must be an object")
            return RemoteResponse(payload=payload, status=int(response.status))
    except urllib.error.HTTPError as error:
        raise RemoteFailure(
            "remote HTTP failure", status=int(error.code),
            retry_after=_retry_after(error.headers.get("Retry-After")),
        ) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RemoteFailure(type(error).__name__) from None


@contextmanager
def exclusive_lock(path: Path, *, blocking: bool = False) -> Iterator[None]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            operation = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            fcntl.flock(handle.fileno(), operation)
        except BlockingIOError:
            raise RuntimeError("another M7 collection run holds the lock") from None
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def sanitize_report(value: Any, key: str = "") -> Any:
    normalized = key.lower().replace("-", "_")
    if normalized in SENSITIVE_REPORT_KEYS or any(
        normalized.endswith("_" + item) for item in SENSITIVE_REPORT_KEYS
    ):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): sanitize_report(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_report(item) for item in value]
    if isinstance(value, str) and (
        "postgresql://" in value.lower() or "postgres://" in value.lower()
        or "oss-" in value.lower() and ".aliyuncs.com" in value.lower()
    ):
        return "[redacted]"
    return value


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_report(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class RequestController:
    def __init__(
        self, database: Database, run_id: str, policy: CollectionPolicy,
        *, sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
        budget_date: Callable[[], str] = _budget_date,
    ) -> None:
        self.database = database
        self.run_id = run_id
        self.policy = policy
        self.sleep = sleep
        self.jitter = jitter
        self.budget_date = budget_date
        self.request_count = 0
        self.retry_count = 0
        self.consecutive_failures = 0
        self.waits: list[float] = []

    def request(
        self, fetcher: Callable[[str, Mapping[str, str], int], RemoteResponse],
        url: str, headers: Mapping[str, str], timeout: int,
        *, source_id: Optional[int] = None,
    ) -> RemoteResponse:
        for attempt in range(1, self.policy.attempts + 1):
            wait = 0.0
            if self.request_count:
                wait = float(self.jitter(self.policy.minimum_delay, self.policy.maximum_delay))
                self.waits.append(wait)
                self.sleep(wait)
            self.database.reserve_daily_request(self.budget_date(), self.policy.daily_budget)
            self.request_count += 1
            try:
                response = fetcher(url, headers, timeout)
                self.consecutive_failures = 0
                self.database.record_fetch_attempt(
                    self.run_id, source_id, attempt, "success", wait, response.status,
                )
                return response
            except RemoteFailure as error:
                self.consecutive_failures += 1
                self.database.record_fetch_attempt(
                    self.run_id, source_id, attempt, "failure", wait, error.status,
                    type(error).__name__,
                )
                if self.consecutive_failures >= self.policy.failure_threshold:
                    raise RuntimeError("circuit breaker opened after consecutive failures") from error
                if attempt >= self.policy.attempts:
                    raise
                self.retry_count += 1
                backoff = float(2 ** (attempt - 1))
                retry_wait = max(backoff, error.retry_after or 0.0)
                if retry_wait:
                    self.waits.append(retry_wait)
                    self.sleep(retry_wait)
        raise AssertionError("unreachable")


def _listing_item(item: Mapping[str, Any], headers: Mapping[str, str]) -> Dict[str, Any]:
    post = item.get("post")
    user = item.get("user")
    if not isinstance(post, Mapping) or not isinstance(user, Mapping):
        raise ValueError("listing item is missing post or user object")
    external_id = str(post.get("post_id") or "")
    if not external_id:
        raise ValueError("listing item is missing post_id")
    certification = user.get("certification") or {}
    status = post.get("post_status") or {}
    if not isinstance(certification, Mapping) or not isinstance(status, Mapping):
        raise ValueError("listing verification fields are malformed")
    verified = "官方账号" in str(certification.get("label") or "") and bool(status.get("is_official"))
    return {
        "external_id": external_id,
        "verified": verified,
        "source_kind": "official_video" if item.get("vod_list") else "official_article",
        "page_url": "https://www.miyoushe.com/sr/article/" + external_id,
        "api_url": "https://bbs-api.miyoushe.com/post/wapi/getPostFull?gids=6&post_id=" + external_id + "&read=1",
        "headers": dict(headers),
        "title": str(post.get("subject") or ""),
    }


def classify_payload(payload: Mapping[str, Any], source_kind: str) -> tuple[str, str]:
    outer = payload.get("data", {}).get("post", {})
    if not isinstance(outer, Mapping):
        return "manual_review", "malformed_post_body"
    post = outer.get("post") or {}
    user = outer.get("user") or {}
    if not isinstance(post, Mapping) or not isinstance(user, Mapping):
        return "manual_review", "malformed_post_body"
    certification = user.get("certification") or {}
    status = post.get("post_status") or {}
    verified = (
        isinstance(certification, Mapping)
        and "官方账号" in str(certification.get("label") or "")
        and isinstance(status, Mapping) and bool(status.get("is_official"))
    )
    if not verified:
        return "excluded_unverified", "body_not_officially_verified"
    title = str(post.get("subject") or "")
    content = str(post.get("content") or "").strip()
    if any(term in title for term in OPERATIONAL_TERMS):
        return "excluded_operational", "operational_title_rule"
    if not content:
        if source_kind == "official_video" or outer.get("vod_list"):
            return "missing_official_text", "video_has_no_official_text"
        return "manual_review", "empty_official_article"
    return "eligible_evidence", "verified_official_text"


class OssRamRoleUploader:
    """OSS uploader whose credentials come only from the ECS RAM role provider."""

    STATIC_KEY_VARIABLES = (
        "ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET",
    )

    def __init__(self, bucket: str, endpoint: str, role_name: str = "") -> None:
        present = [name for name in self.STATIC_KEY_VARIABLES if os.environ.get(name)]
        if present:
            raise ValueError("static AccessKey configuration is refused")
        if not bucket or not endpoint:
            raise ValueError("OSS bucket and endpoint are required")
        self.bucket_name = bucket
        self.endpoint = endpoint
        self.role_name = role_name

    def upload(self, object_key: str, body: bytes) -> Mapping[str, Optional[str]]:
        try:
            import oss2
        except ImportError as error:
            raise RuntimeError("install the M7 OSS dependencies with .[oss]") from error

        metadata_root = "http://100.100.100.200/latest"

        def metadata(path: str, token: str) -> bytes:
            request = urllib.request.Request(
                metadata_root + path,
                headers={"X-aliyun-ecs-metadata-token": token},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.read()

        token_request = urllib.request.Request(
            metadata_root + "/api/token",
            headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(token_request, timeout=5) as response:
                token = response.read().decode("utf-8")
            role_name = self.role_name or metadata(
                "/meta-data/ram/security-credentials/", token
            ).decode("utf-8").strip()
        except (OSError, UnicodeDecodeError) as error:
            raise RuntimeError("ECS RAM role metadata is unavailable") from error
        if not role_name:
            raise RuntimeError("ECS RAM role is not attached")

        class Provider(oss2.CredentialsProvider):
            def get_credentials(provider_self):  # type: ignore[no-untyped-def]
                try:
                    raw = metadata(
                        "/meta-data/ram/security-credentials/"
                        + urllib.parse.quote(role_name, safe=""),
                        token,
                    )
                    credential = json.loads(raw.decode("utf-8"))
                    if credential.get("Code") != "Success":
                        raise ValueError("metadata credential response was not successful")
                    return oss2.credentials.Credentials(
                        credential["AccessKeyId"], credential["AccessKeySecret"],
                        credential["SecurityToken"],
                    )
                except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RuntimeError("ECS RAM role credentials are unavailable") from error

        auth = oss2.ProviderAuth(Provider())
        try:
            result = oss2.Bucket(
                auth, self.endpoint, self.bucket_name
            ).put_object(object_key, body)
        except Exception:
            raise RuntimeError("OSS upload was denied or failed") from None
        return {
            "etag": getattr(result, "etag", None),
            "version_id": getattr(result, "versionid", None),
        }


class M7Collector:
    HEADERS = {
        "Origin": "https://www.miyoushe.com",
        "Referer": "https://www.miyoushe.com/",
        "User-Agent": "hksr-database/0.1 (+private evidence collection)",
    }

    def __init__(
        self, database: Database, *, policy: CollectionPolicy = CollectionPolicy(),
        fetcher: Callable[[str, Mapping[str, str], int], RemoteResponse] = fetch_remote_json,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
        budget_date: Callable[[], str] = _budget_date,
    ) -> None:
        self.database = database
        self.policy = policy
        self.fetcher = fetcher
        self.sleep = sleep
        self.jitter = jitter
        self.budget_date = budget_date

    def _run_id(self, stage: str) -> str:
        return "m7-%s-%s-%s" % (
            stage, datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8]
        )

    def discover(self, uid: str, *, timeout: int = 30) -> Dict[str, Any]:
        run_id = self._run_id("discover")
        self.database.start_collection_run(run_id, "discovery")
        controller = RequestController(
            self.database, run_id, self.policy, sleep=self.sleep,
            jitter=self.jitter, budget_date=self.budget_date,
        )
        checkpoint = self.database.collection_checkpoint(uid)
        cursor = "" if checkpoint["terminal"] else str(checkpoint["next_cursor"] or "")
        report: Dict[str, Any] = {
            "schema_version": 1, "run_id": run_id, "stage": "discovery",
            "started_at": utc_now(), "page_cap": self.policy.discovery_pages,
            "daily_budget": self.policy.daily_budget or "unlimited",
            "pages": 0, "results": 0, "registered": 0, "duplicates": 0,
            "unverified": 0, "resumed_cursor": bool(cursor), "terminal": False,
        }
        try:
            for _ in range(self.policy.discovery_pages):
                parameters = {"size": 20, "uid": uid}
                if cursor:
                    parameters["offset"] = cursor
                url = "https://bbs-api.miyoushe.com/painter/wapi/userPostList?" + urlencode(parameters)
                response = controller.request(self.fetcher, url, self.HEADERS, timeout)
                payload = response.payload
                if payload.get("retcode") != 0 or not isinstance(payload.get("data"), Mapping):
                    raise ValueError("official account response contract changed")
                data = payload["data"]
                raw_items = data.get("list")
                if not isinstance(raw_items, list):
                    raise ValueError("official account list is malformed")
                items = [_listing_item(item, self.HEADERS) for item in raw_items]
                terminal = bool(data.get("is_last"))
                next_cursor = str(data.get("next_offset") or "")
                if not terminal and not next_cursor:
                    raise ValueError("non-terminal page is missing next_offset")
                counts = self.database.commit_discovery_page(
                    uid, items, next_cursor, terminal, CLASSIFIER_VERSION,
                )
                report["pages"] += 1
                report["results"] += len(items)
                for key in ("registered", "duplicates", "unverified"):
                    report[key] += counts[key]
                cursor = next_cursor
                report["terminal"] = terminal
                if terminal:
                    break
            report["checkpoint"] = "terminal" if report["terminal"] else "bounded_pause"
            report["requests"] = controller.request_count
            report["retries"] = controller.retry_count
            report["wait_seconds"] = controller.waits
            report["finished_at"] = utc_now()
            self.database.finish_collection_run(run_id, "completed", report)
            return sanitize_report(report)
        except BaseException as error:
            report.update({
                "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                "error_type": type(error).__name__, "requests": controller.request_count,
                "retries": controller.retry_count, "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, report["status"], report)
            raise

    def fetch(
        self, raw_root: Path, uploader: RawUploader, *, timeout: int = 30,
        object_prefix: str = "m7/raw",
    ) -> Dict[str, Any]:
        run_id = self._run_id("fetch")
        self.database.start_collection_run(run_id, "fetch")
        controller = RequestController(
            self.database, run_id, self.policy, sleep=self.sleep,
            jitter=self.jitter, budget_date=self.budget_date,
        )
        sources = [
            row for row in self.database.list_sources(
                statuses=["discovered", "error"], limit=None
            ) if row["provider"] == "miyoushe" and row["official_status"] == "verified"
        ][: self.policy.fetch_posts]
        report: Dict[str, Any] = {
            "schema_version": 1, "run_id": run_id, "stage": "fetch",
            "started_at": utc_now(), "post_cap": self.policy.fetch_posts,
            "daily_budget": self.policy.daily_budget or "unlimited",
            "attempted": 0, "persisted": 0, "skipped": 0, "failed": 0,
            "remote_retcodes": {}, "dispositions": {},
        }
        try:
            for source in sources:
                report["attempted"] += 1
                source_id = int(source["id"])
                try:
                    response = controller.request(
                        self.fetcher, source["api_url"],
                        json.loads(source["headers_json"] or "{}"), timeout,
                        source_id=source_id,
                    )
                    retcode = response.payload.get("retcode")
                    if retcode != 0:
                        retcode_key = str(retcode)[:32]
                        disposition = "excluded_unavailable"
                        reason = "remote_nonzero_retcode_" + retcode_key
                        self.database.set_disposition(
                            source_id, disposition, reason, CLASSIFIER_VERSION,
                        )
                        self.database.mark_skipped(source_id)
                        report["skipped"] += 1
                        report["remote_retcodes"][retcode_key] = (
                            report["remote_retcodes"].get(retcode_key, 0) + 1
                        )
                        report["dispositions"][disposition] = (
                            report["dispositions"].get(disposition, 0) + 1
                        )
                        continue
                    canonical = json.dumps(
                        response.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                    digest = hashlib.sha256(canonical).hexdigest()
                    local_path = Path(raw_root) / "miyoushe" / (source["external_id"] + ".json")
                    local_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    temporary = local_path.with_suffix(".json.tmp")
                    temporary.write_bytes(canonical)
                    os.chmod(temporary, 0o600)
                    temporary.replace(local_path)
                    object_key = "%s/miyoushe/%s/%s.json" % (
                        object_prefix.strip("/"), source["external_id"], digest
                    )
                    uploaded = uploader.upload(object_key, canonical)
                    if not uploaded:
                        raise RuntimeError("OSS persistence returned no result")
                    self.database.record_raw_manifest(
                        source_id, digest, len(canonical), local_path, object_key,
                        uploaded.get("etag"), uploaded.get("version_id"),
                        content_fingerprint(source["parser"], response.payload),
                    )
                    disposition, reason = classify_payload(response.payload, source["source_kind"])
                    self.database.set_disposition(
                        source_id, disposition, reason, CLASSIFIER_VERSION,
                    )
                    report["persisted"] += 1
                    report["dispositions"][disposition] = report["dispositions"].get(disposition, 0) + 1
                except (OSError, RemoteFailure, RuntimeError, ValueError) as error:
                    self.database.mark_error(source_id, type(error).__name__)
                    report["failed"] += 1
                    if "circuit breaker" in str(error) or "daily request budget" in str(error):
                        raise
            report.update({
                "requests": controller.request_count, "retries": controller.retry_count,
                "wait_seconds": controller.waits, "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, "completed", report)
            return sanitize_report(report)
        except BaseException as error:
            report.update({
                "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                "error_type": type(error).__name__, "requests": controller.request_count,
                "retries": controller.retry_count, "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, report["status"], report)
            raise

    def fetch_wiki(
        self, raw_root: Path, uploader: RawUploader, *, timeout: int = 30,
        object_prefix: str = "m7/raw",
    ) -> Dict[str, Any]:
        """Fetch one bounded batch from the verified Wiki catalog access list."""
        run_id = self._run_id("wiki-fetch")
        self.database.start_collection_run(run_id, "wiki_fetch")
        controller = RequestController(
            self.database, run_id, self.policy, sleep=self.sleep,
            jitter=self.jitter, budget_date=self.budget_date,
        )
        sources = [
            row for row in self.database.list_sources(
                statuses=["discovered", "error"], limit=None
            ) if row["provider"] == "mihoyo_wiki" and row["official_status"] == "verified"
        ][: self.policy.fetch_posts]
        report: Dict[str, Any] = {
            "schema_version": 1, "run_id": run_id, "stage": "wiki_fetch",
            "started_at": utc_now(), "content_cap": self.policy.fetch_posts,
            "daily_budget": self.policy.daily_budget or "unlimited",
            "attempted": 0, "persisted": 0, "skipped": 0, "failed": 0,
            "remote_retcodes": {}, "dispositions": {},
        }
        try:
            for source in sources:
                report["attempted"] += 1
                source_id = int(source["id"])
                try:
                    response = controller.request(
                        self.fetcher, source["api_url"],
                        json.loads(source["headers_json"] or "{}"), timeout,
                        source_id=source_id,
                    )
                    retcode = response.payload.get("retcode")
                    if retcode != 0:
                        retcode_key = str(retcode)[:32]
                        disposition = "excluded_unavailable"
                        reason = "remote_nonzero_retcode_" + retcode_key
                        self.database.set_disposition(
                            source_id, disposition, reason, CLASSIFIER_VERSION,
                        )
                        self.database.mark_skipped(source_id)
                        report["skipped"] += 1
                        report["remote_retcodes"][retcode_key] = (
                            report["remote_retcodes"].get(retcode_key, 0) + 1
                        )
                        report["dispositions"][disposition] = (
                            report["dispositions"].get(disposition, 0) + 1
                        )
                        continue
                    data = response.payload.get("data")
                    if not isinstance(data, Mapping) or not isinstance(
                        data.get("content"), Mapping
                    ):
                        raise ValueError("Wiki detail response is malformed")
                    canonical = json.dumps(
                        response.payload, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    digest = hashlib.sha256(canonical).hexdigest()
                    local_path = (
                        Path(raw_root) / "mihoyo_wiki" /
                        (source["external_id"] + ".json")
                    )
                    local_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    temporary = local_path.with_suffix(".json.tmp")
                    temporary.write_bytes(canonical)
                    os.chmod(temporary, 0o600)
                    temporary.replace(local_path)
                    object_key = "%s/mihoyo_wiki/%s/%s.json" % (
                        object_prefix.strip("/"), source["external_id"], digest
                    )
                    uploaded = uploader.upload(object_key, canonical)
                    if not uploaded:
                        raise RuntimeError("OSS persistence returned no result")
                    self.database.record_raw_manifest(
                        source_id, digest, len(canonical), local_path, object_key,
                        uploaded.get("etag"), uploaded.get("version_id"),
                        content_fingerprint(source["parser"], response.payload),
                    )
                    disposition = "eligible_evidence"
                    self.database.set_disposition(
                        source_id, disposition, "official_wiki_catalog_content",
                        CLASSIFIER_VERSION,
                    )
                    report["persisted"] += 1
                    report["dispositions"][disposition] = (
                        report["dispositions"].get(disposition, 0) + 1
                    )
                except (OSError, RemoteFailure, RuntimeError, ValueError) as error:
                    self.database.mark_error(source_id, type(error).__name__)
                    report["failed"] += 1
                    if "circuit breaker" in str(error) or "daily request budget" in str(error):
                        raise
            report.update({
                "requests": controller.request_count, "retries": controller.retry_count,
                "wait_seconds": controller.waits, "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, "completed", report)
            return sanitize_report(report)
        except BaseException as error:
            report.update({
                "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                "error_type": type(error).__name__, "requests": controller.request_count,
                "retries": controller.retry_count, "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, report["status"], report)
            raise

    def refresh_wiki(
        self, raw_root: Path, uploader: RawUploader, *, timeout: int = 30,
        object_prefix: str = "m7/raw", catalog_key: str = "game_catalog:17",
        start_new_cycle: bool = False,
    ) -> Dict[str, Any]:
        """Recheck one bounded, resumable batch of already parsed Wiki pages."""
        run_id = self._run_id("wiki-refresh")
        self.database.start_collection_run(run_id, "wiki_refresh")
        if start_new_cycle:
            checkpoint = self.database.start_wiki_refresh(run_id, catalog_key)
        else:
            checkpoint = self.database.wiki_refresh_checkpoint(catalog_key)
            if checkpoint is None:
                self.database.finish_collection_run(
                    run_id, "failed", {"error_type": "MissingRefreshCycle"}
                )
                raise RuntimeError("start a Wiki refresh cycle before resuming it")
        controller = RequestController(
            self.database, run_id, self.policy, sleep=self.sleep,
            jitter=self.jitter, budget_date=self.budget_date,
        )
        report: Dict[str, Any] = {
            "schema_version": 1, "run_id": run_id, "stage": "wiki_refresh",
            "started_at": utc_now(), "content_cap": self.policy.fetch_posts,
            "daily_budget": self.policy.daily_budget or "unlimited",
            "cycle_id": checkpoint.get("cycle_id"), "attempted": 0,
            "changed": 0, "unchanged": 0, "skipped": 0, "failed": 0,
            "remote_retcodes": {},
        }
        try:
            if checkpoint.get("terminal"):
                report["terminal"] = True
            else:
                sources = self.database.wiki_refresh_sources(
                    catalog_key, self.policy.fetch_posts
                )
                if not sources:
                    checkpoint = self.database.complete_wiki_refresh(catalog_key)
                for source in sources:
                    report["attempted"] += 1
                    source_id = int(source["id"])
                    try:
                        response = controller.request(
                            self.fetcher, source["api_url"],
                            json.loads(source["headers_json"] or "{}"), timeout,
                            source_id=source_id,
                        )
                        retcode = response.payload.get("retcode")
                        if retcode != 0:
                            retcode_key = str(retcode)[:32]
                            self.database.set_disposition(
                                source_id, "excluded_unavailable",
                                "remote_nonzero_retcode_" + retcode_key,
                                CLASSIFIER_VERSION,
                            )
                            self.database.mark_skipped(source_id)
                            checkpoint = self.database.advance_wiki_refresh(
                                source_id, changed=True, catalog_key=catalog_key
                            )
                            report["skipped"] += 1
                            report["changed"] += 1
                            report["remote_retcodes"][retcode_key] = (
                                report["remote_retcodes"].get(retcode_key, 0) + 1
                            )
                            continue
                        data = response.payload.get("data")
                        if not isinstance(data, Mapping) or not isinstance(
                            data.get("content"), Mapping
                        ):
                            raise ValueError("Wiki detail response is malformed")
                        canonical = json.dumps(
                            response.payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        content_hash = content_fingerprint(
                            source["parser"], response.payload
                        )
                        if source["content_sha256"] == content_hash:
                            self.database.mark_refresh_unchanged(source_id)
                            checkpoint = self.database.advance_wiki_refresh(
                                source_id, changed=False, catalog_key=catalog_key
                            )
                            report["unchanged"] += 1
                            continue
                        digest = hashlib.sha256(canonical).hexdigest()
                        local_path = (
                            Path(raw_root) / "mihoyo_wiki" /
                            (source["external_id"] + ".json")
                        )
                        local_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        temporary = local_path.with_suffix(".json.tmp")
                        temporary.write_bytes(canonical)
                        os.chmod(temporary, 0o600)
                        temporary.replace(local_path)
                        object_key = "%s/mihoyo_wiki/%s/%s.json" % (
                            object_prefix.strip("/"), source["external_id"], digest
                        )
                        uploaded = uploader.upload(object_key, canonical)
                        if not uploaded:
                            raise RuntimeError("OSS persistence returned no result")
                        self.database.record_raw_manifest(
                            source_id, digest, len(canonical), local_path, object_key,
                            uploaded.get("etag"), uploaded.get("version_id"), content_hash,
                        )
                        self.database.set_disposition(
                            source_id, "eligible_evidence",
                            "official_wiki_catalog_content", CLASSIFIER_VERSION,
                        )
                        checkpoint = self.database.advance_wiki_refresh(
                            source_id, changed=True, catalog_key=catalog_key
                        )
                        report["changed"] += 1
                    except (OSError, RemoteFailure, RuntimeError, ValueError) as error:
                        self.database.mark_refresh_error(source_id, type(error).__name__)
                        report["failed"] += 1
                        raise
                report["terminal"] = bool(checkpoint.get("terminal"))
            report.update({
                "requests": controller.request_count, "retries": controller.retry_count,
                "wait_seconds": controller.waits,
                "checkpoint": {
                    "checked_count": checkpoint.get("checked_count", 0),
                    "changed_count": checkpoint.get("changed_count", 0),
                    "terminal": bool(checkpoint.get("terminal")),
                },
                "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, "completed", report)
            return sanitize_report(report)
        except BaseException as error:
            report.update({
                "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                "error_type": type(error).__name__, "requests": controller.request_count,
                "retries": controller.retry_count, "finished_at": utc_now(),
            })
            self.database.finish_collection_run(run_id, report["status"], report)
            raise


def review_disposition(
    database: Database, external_id: str, disposition: str, reason: str
) -> Dict[str, Any]:
    if disposition not in DISPOSITIONS - {"excluded_unverified"}:
        raise ValueError("unsupported review disposition")
    rows = [
        row for row in database.list_sources() if row["provider"] == "miyoushe"
        and row["external_id"] == external_id
    ]
    if not rows:
        raise KeyError("unknown Miyoushe post id")
    source = rows[0]
    database.set_disposition(
        int(source["id"]), disposition, reason, CLASSIFIER_VERSION, reviewed=True,
    )
    return {"external_id": external_id, "disposition": disposition, "reviewed": True}


def build_collection_report(database: Database) -> Dict[str, Any]:
    rows = database.disposition_rows()
    totals: Dict[str, int] = {}
    for row in rows:
        totals[row["disposition"]] = totals.get(row["disposition"], 0) + 1
    checkpoints = []
    runs = []
    manifests = []
    with database.connect() as connection:
        checkpoints = [dict(row) for row in connection.execute(
            """SELECT terminal, observed_count, updated_at, terminal_at
               FROM account_checkpoints ORDER BY account_uid"""
        )]
        runs = [dict(row) for row in connection.execute(
            """SELECT run_id, stage, status, started_at, finished_at
               FROM collection_runs ORDER BY started_at"""
        )]
        manifests = [dict(row) for row in connection.execute(
            """SELECT raw_sha256, raw_byte_count, persisted_at
               FROM raw_object_manifests ORDER BY source_id"""
        )]
    return sanitize_report({
        "schema_version": 1, "generated_at": utc_now(), "inventory": len(rows),
        "dispositions": totals, "checkpoints": checkpoints, "runs": runs,
        "raw_objects": manifests,
        "unresolved": sum(1 for row in rows if row["disposition"] == "manual_review"),
        "unverified_evidence": sum(
            1 for row in rows if not row["verified"] and row["disposition"] == "eligible_evidence"
        ),
    })
