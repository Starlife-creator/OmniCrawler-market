"""Chronicle Capsule: bounded WARC export through opaque host streams."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode

PLUGIN_METADATA = {
    "name": "chronicle-capsule",
    "version": "0.3.0",
    "api_version": 1,
    "description": "以隐私、元数据或原始保全模式生成有界 WARC 1.1 归档",
    "plugin_types": ["exporter"],
    "category": "archiving",
    "tags": ["warc", "evidence", "offline", "sha256", "streaming"],
    "permissions": ["records:read", "responses:read", "responses:payload", "artifacts:write"],
    "required_capabilities": {
        "records.page": ">=1",
        "responses.page": ">=1",
        "responses.payload": ">=1",
        "artifact.stream.open": ">=1",
        "artifact.stream.write": ">=1",
        "artifact.stream.commit": ">=1",
        "artifact.stream.abort": ">=1",
    },
    "domains": [],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    "min_core_version": "0.11.2",
}

SENSITIVE_KEY = re.compile(r"(?:authorization|cookie|token|secret|password|api[_-]?key)", re.I)
MAX_RECORDS = 5000
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+", re.I)
VALUE_SECRET = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]+=*|((?:token|password|secret|api[_-]?key)\s*[=:]\s*)[^\s&,;]+")


def redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"}:
            return value
        host = parts.hostname or ""
        if ":" in host:
            host = "[" + host + "]"
        if parts.port:
            host += ":" + str(parts.port)
        query = [(k, "[REDACTED]" if SENSITIVE_KEY.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
        return urlunsplit((parts.scheme, host, parts.path, urlencode(query), "[REDACTED]" if parts.fragment else ""))
    except ValueError:
        return "[REDACTED INVALID URL]"


def redact_text(value: str) -> str:
    value = URL_PATTERN.sub(lambda m: redact_url(m.group(0)), value)
    return VALUE_SECRET.sub(lambda m: (m.group(1) or m.group(2)) + "[REDACTED]", value)
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
WRITE_CHUNK_BYTES = 512 * 1024


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _target_uri(value: Any) -> str:
    cleaned = str(value).replace("\r", "").replace("\n", "").strip()
    return quote(cleaned or "urn:omnicrawler:record:unknown", safe=":/?&=;%+#@[]!$'()*,-._~")


def _warc_payload(
    target: str,
    payload: bytes,
    timestamp: str,
    *,
    media_type: str = "application/octet-stream",
    record_type: str = "resource",
    truncated: bool = False,
) -> bytes:
    digest = hashlib.sha256(payload).hexdigest()
    safe_media_type = media_type.replace("\r", "").replace("\n", "")[:200]
    headers = [
        "WARC/1.1",
        f"WARC-Type: {record_type}",
        f"WARC-Record-ID: <urn:uuid:{uuid.uuid4()}>",
        f"WARC-Target-URI: {_target_uri(target)}",
        f"WARC-Date: {timestamp}",
        f"WARC-Payload-Digest: sha256:{digest}",
        f"Content-Type: {safe_media_type or 'application/octet-stream'}",
        f"Content-Length: {len(payload)}",
        "",
        "",
    ]
    if truncated:
        headers.insert(-2, "WARC-Truncated: length")
    return "\r\n".join(headers).encode("ascii") + payload + b"\r\n\r\n"


def _warc_record(record: dict[str, Any], timestamp: str) -> bytes:
    safe = redact(record)
    payload = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    target = safe.get("source_url") or f"urn:omnicrawler:record:{record.get('record_id', 'unknown')}"
    return _warc_payload(
        str(target), payload, timestamp, media_type="application/json; charset=utf-8"
    )


def build_archive(
    records: list[dict[str, Any]], *, created_at: str | None = None
) -> tuple[bytes, dict[str, Any]]:
    """Small in-memory helper retained for tests and private-folder use."""

    timestamp = created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    chunks = [_warc_record(record, timestamp) for record in records]
    raw_size = sum(map(len, chunks))
    if raw_size > MAX_ARCHIVE_BYTES:
        raise ValueError("归档未压缩载荷超过 25 MiB 安全上限")
    archive = b"".join(gzip.compress(chunk, compresslevel=6, mtime=0) for chunk in chunks)
    return archive, {
        "format": "WARC/1.1",
        "records": len(records),
        "uncompressed_bytes": raw_size,
        "archive_bytes": len(archive),
        "sha256": hashlib.sha256(archive).hexdigest(),
        "redaction": "sensitive-key-url-and-pattern-v2",
    }


def _pages(sdk: Any, operation: str, key: str, limit: int) -> Iterator[dict[str, Any]]:
    cursor = None
    remaining = limit
    seen_cursors = set()
    while remaining > 0:
        request = {"limit": min(250, remaining)}
        if cursor:
            if cursor in seen_cursors:
                raise ValueError("分页游标重复，归档已中止")
            seen_cursors.add(cursor)
            request["cursor"] = cursor
        page = sdk.call(operation, request)
        items = list(page.get(key) or [])
        for item in items[:remaining]:
            if isinstance(item, dict):
                yield item
                remaining -= 1
        cursor = page.get("next_cursor")
        if not cursor or not items:
            return


def _write_chunk(sdk: Any, handle: str, content: bytes) -> None:
    for start in range(0, len(content), WRITE_CHUNK_BYTES):
        chunk = content[start : start + WRITE_CHUNK_BYTES]
        sdk.call(
            "artifact.stream.write",
            {"handle": handle, "content_b64": base64.b64encode(chunk).decode("ascii")},
        )


def _iter_warc_records(
    sdk: Any,
    mode: str,
    limit: int,
    timestamp: str,
    stats: dict[str, int],
) -> Iterator[bytes]:
    if mode == "privacy":
        for record in _pages(sdk, "records.page", "records", limit):
            yield _warc_record(record, timestamp)
        return
    for response in _pages(sdk, "responses.page", "responses", limit):
        target = str(response.get("final_url") or response.get("url") or "")
        if mode == "metadata":
            target = redact_url(target)
            content = json.dumps(
                redact(response), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            yield _warc_payload(
                target, content, timestamp, media_type="application/json; charset=utf-8"
            )
            continue
        response_ref = response.get("response_ref")
        if not response_ref:
            stats["missing_payloads"] += 1
            continue
        remaining = MAX_ARCHIVE_BYTES - stats["uncompressed_bytes"]
        result = sdk.call(
            "responses.payload",
            {"response_ref": response_ref, "maximum_bytes": max(1, min(remaining, 16 * 1024 * 1024))},
        )
        try:
            if "content_b64" not in result:
                raise ValueError("missing payload")
            content = base64.b64decode(str(result["content_b64"]), validate=True)
        except (ValueError, TypeError):
            stats["missing_payloads"] += 1
            continue
        if result.get("truncated"):
            stats["truncated_payloads"] += 1
        yield _warc_payload(
            target,
            content,
            timestamp,
            # Payload capability exposes body only, not an HTTP status/header block.
            # A resource record is interoperable without inventing an HTTP response.
            media_type=str(response.get("content_type") or "application/octet-stream"),
            record_type="resource",
            truncated=bool(result.get("truncated")),
        )


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation != "exporter.export":
        return {}
    import omnicrawler_sdk

    options = dict(payload.get("options") or {})
    mode = str(options.get("mode", "privacy")).casefold()
    if mode not in {"privacy", "metadata", "preservation"}:
        mode = "privacy"
    try:
        if isinstance(options.get("max_records"), bool):
            raise ValueError("boolean limit")
        limit = max(1, min(int(options.get("max_records", 1000)), MAX_RECORDS))
    except (TypeError, ValueError):
        raise ValueError("max_records 必须是整数") from None
    name = str(options.get("name") or f"chronicle-capsule-{mode}.warc.gz")
    if not name.endswith(".warc.gz") or "/" in name or "\\" in name:
        name = f"chronicle-capsule-{mode}.warc.gz"
    opened = omnicrawler_sdk.call(
        "artifact.stream.open", {"name": name, "media_type": "application/warc+gzip"}
    )
    handle_id = str(opened["handle"])
    digest = hashlib.sha256()
    archive_bytes = 0
    stats = {
        "records": 0,
        "uncompressed_bytes": 0,
        "missing_payloads": 0,
        "truncated_payloads": 0,
    }
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        for warc_record in _iter_warc_records(omnicrawler_sdk, mode, limit, timestamp, stats):
            stats["uncompressed_bytes"] += len(warc_record)
            if stats["uncompressed_bytes"] > MAX_ARCHIVE_BYTES:
                raise ValueError("归档未压缩载荷超过 25 MiB 安全上限")
            stats["records"] += 1
            # One gzip member per WARC record supports independent seeking/readers.
            compressed = gzip.compress(warc_record, compresslevel=6, mtime=0)
            digest.update(compressed)
            archive_bytes += len(compressed)
            _write_chunk(omnicrawler_sdk, handle_id, compressed)
            if stats["records"] % 25 == 0 or stats["records"] == limit:
                try:
                    omnicrawler_sdk.call("view.progress", {"done": stats["records"], "total": limit})
                except Exception:
                    pass
        artifact = omnicrawler_sdk.call("artifact.stream.commit", {"handle": handle_id})
    except Exception:
        try:
            omnicrawler_sdk.call("artifact.stream.abort", {"handle": handle_id})
        except Exception:
            pass
        raise
    return {
        "artifact": artifact,
        "summary": {
            **stats,
            "format": "WARC/1.1",
            "mode": mode,
            "archive_bytes": archive_bytes,
            "sha256": digest.hexdigest(),
            "max_records": limit,
            "record_limit_reached": stats["records"] == limit,
            "maximum_uncompressed_bytes": MAX_ARCHIVE_BYTES,
            "payload_representation": "body-only-resource" if mode == "preservation" else "redacted-json",
            "complete_payloads": stats["records"] - stats["truncated_payloads"],
            "redaction_scope": "字段名、URL 凭据与敏感查询参数、Bearer 及常见密钥模式；不保证识别所有正文秘密" if mode != "preservation" else "无脱敏",
            "redaction": "sensitive-key-url-and-pattern-v2" if mode != "preservation" else "none",
        },
    }
