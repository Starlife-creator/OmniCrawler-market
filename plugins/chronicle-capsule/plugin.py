"""Chronicle Capsule: bounded WARC export through opaque host streams."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
import uuid
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

PLUGIN_METADATA = {
    "name": "chronicle-capsule",
    "version": "0.2.0",
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
    return "\r\n".join(headers).encode("ascii") + payload + b"\r\n\r\n"


def _warc_record(record: dict[str, Any], timestamp: str) -> bytes:
    safe = redact(record)
    payload = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    target = record.get("source_url") or f"urn:omnicrawler:record:{record.get('record_id', 'unknown')}"
    return _warc_payload(
        str(target), payload, timestamp, media_type="application/json; charset=utf-8"
    )


def build_archive(
    records: list[dict[str, Any]], *, created_at: str | None = None
) -> tuple[bytes, dict[str, Any]]:
    """Small in-memory helper retained for tests and private-folder use."""

    timestamp = created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    raw = b"".join(_warc_record(record, timestamp) for record in records)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError("归档未压缩载荷超过 25 MiB 安全上限")
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as stream:
        stream.write(raw)
    archive = output.getvalue()
    return archive, {
        "format": "WARC/1.1",
        "records": len(records),
        "uncompressed_bytes": len(raw),
        "archive_bytes": len(archive),
        "sha256": hashlib.sha256(archive).hexdigest(),
        "redaction": "sensitive-key-recursive-v1",
    }


def _pages(sdk: Any, operation: str, key: str, limit: int) -> Iterator[dict[str, Any]]:
    cursor = None
    remaining = limit
    while remaining > 0:
        request = {"limit": min(250, remaining)}
        if cursor:
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
            content = base64.b64decode(str(result.get("content_b64") or ""), validate=True)
        except (ValueError, TypeError):
            stats["missing_payloads"] += 1
            continue
        if result.get("truncated"):
            stats["truncated_payloads"] += 1
        yield _warc_payload(
            target,
            content,
            timestamp,
            media_type=str(response.get("content_type") or "application/octet-stream"),
            record_type="response",
        )


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation != "exporter.export":
        return {}
    import omnicrawler_sdk

    options = dict(payload.get("options") or {})
    mode = str(options.get("mode", "privacy")).casefold()
    if mode not in {"privacy", "metadata", "preservation"}:
        mode = "privacy"
    limit = max(1, min(int(options.get("max_records", 1000)), MAX_RECORDS))
    name = str(options.get("name") or f"chronicle-capsule-{mode}.warc.gz")
    if not name.endswith(".warc.gz") or "/" in name or "\\" in name:
        name = f"chronicle-capsule-{mode}.warc.gz"
    opened = omnicrawler_sdk.call(
        "artifact.stream.open", {"name": name, "media_type": "application/warc+gzip"}
    )
    handle_id = str(opened["handle"])
    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=31)
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
            _write_chunk(omnicrawler_sdk, handle_id, compressor.compress(warc_record))
        _write_chunk(omnicrawler_sdk, handle_id, compressor.flush())
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
            "redaction": "sensitive-key-recursive-v1" if mode != "preservation" else "none",
        },
    }
