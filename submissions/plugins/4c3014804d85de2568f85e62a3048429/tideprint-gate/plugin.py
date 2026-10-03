"""Tideprint Gate: bounded in-run fingerprints and change classification."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLUGIN_METADATA = {
    "name": "tideprint-gate",
    "version": "0.3.0",
    "api_version": 1,
    "description": "以持久指纹建议条件重验证，并输出当前运行的可解释变化分类",
    "plugin_types": ["processor", "hook"],
    "category": "incremental-processing",
    "tags": ["fingerprint", "deduplication", "change-detection", "bounded-state"],
    "permissions": ["state:read", "state:write"],
    "required_capabilities": {
        "state.get": ">=1",
        "state.set": ">=1",
    },
    "state_schema_version": 1,
    "domains": [],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    "min_core_version": "0.11.2",
}

MAX_ENTRIES = 10_000
WHITESPACE = re.compile(rb"\s+")
_state: dict[str, dict[str, Any]] = {}
_persistent_seen: dict[str, dict[str, Any]] = {}
_persistent_counts = {"new": 0, "unchanged": 0, "changed": 0, "bypassed": 0, "invalid": 0}
_counts = {"new": 0, "unchanged": 0, "changed": 0, "bypassed": 0, "invalid": 0}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").casefold()
    try:
        port = parts.port
    except ValueError:
        port = None
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = (
        display_host
        if not port or (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
        else f"{display_host}:{port}"
    )
    path = parts.path or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.casefold(), netloc, path, query, ""))


def fingerprint_body(body: bytes, *, normalize_text: bool = True) -> str:
    value = WHITESPACE.sub(b" ", body).strip() if normalize_text else body
    return hashlib.sha256(value).hexdigest()


def classify(url: str, body: bytes, *, normalize_text: bool = True) -> dict[str, Any]:
    key = normalize_url(url)
    digest = fingerprint_body(body, normalize_text=normalize_text)
    previous = _state.get(key)
    if previous is None:
        status = "new"
    elif previous["sha256"] == digest:
        status = "unchanged"
    else:
        status = "changed"
    if len(_state) >= MAX_ENTRIES and key not in _state:
        oldest = next(iter(_state))
        del _state[oldest]
    _state[key] = {"sha256": digest, "size": len(body)}
    _counts[status] += 1
    return {
        "status": status,
        "normalized_url": key,
        "sha256": digest,
        "previous_sha256": previous["sha256"] if previous else None,
        "size": len(body),
        "previous_size": previous["size"] if previous else None,
        "scope": "current_run_only",
    }


def _reset() -> None:
    _state.clear()
    _persistent_seen.clear()
    for key in _persistent_counts:
        _persistent_counts[key] = 0
    for key in _counts:
        _counts[key] = 0


def _state_key(url: str) -> str:
    normalized = normalize_url(url)
    return "url." + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "hook.before_run":
        _reset()
        return {"status": "ready", "scope": "persistent_host_state"}
    if operation == "hook.after_run":
        summary = {
            "counts": dict(_persistent_counts) if _persistent_seen else dict(_counts),
            "current_run_counts": dict(_counts),
            "persistent_counts": dict(_persistent_counts),
            "tracked_urls": len(_state),
            "scope": "persistent_host_state" if _persistent_seen else "current_run_only",
        }
        _reset()
        return summary
    if operation == "hook.before_fetch":
        import omnicrawler_sdk

        request = dict(payload.get("request") or {})
        url = str(request.get("url") or "")
        if not url or str(request.get("method", "GET")).upper() != "GET":
            return {}
        known = omnicrawler_sdk.call("state.get", {"key": _state_key(url)})
        if not known.get("found"):
            return {}
        return {
            "fetch_advice": {
                "action": "conditional_revalidate",
                "reason": "host state contains a prior content fingerprint",
            }
        }
    if operation == "hook.after_fetch":
        import omnicrawler_sdk

        result = dict(payload.get("result") or {})
        url = str(result.get("final_url") or result.get("url") or (result.get("request") or {}).get("url") or "")
        digest = str(result.get("content_hash") or "")
        status_code = int(result.get("status") or 0)
        if status_code == 304:
            key = normalize_url(url)
            _persistent_seen[key] = {"status": "unchanged", "revalidated": True}
            _persistent_counts["unchanged"] += 1
            return {"persistent_change": dict(_persistent_seen[key])}
        if not url or not re.fullmatch(r"[0-9a-fA-F]{64}", digest) or not 200 <= status_code < 300:
            _persistent_counts["bypassed"] += 1
            return {"persistent_change": {"status": "bypassed", "reason": "unsuccessful_response_or_missing_hash"}}
        digest = digest.lower()
        key = _state_key(url)
        previous = omnicrawler_sdk.call("state.get", {"key": key})
        previous_value = previous.get("value") if previous.get("found") else None
        previous_digest = (
            str(previous_value.get("sha256") or "") if isinstance(previous_value, dict) else ""
        )
        status = "new" if not previous_digest else "unchanged" if previous_digest == digest else "changed"
        omnicrawler_sdk.call(
            "state.set",
            {
                "key": key,
                "value": {
                    "sha256": digest,
                    "normalized_url": normalize_url(url),
                    "status": int(result.get("status") or 0),
                },
            },
        )
        change = {"status": status, "previous_sha256": previous_digest or None, "sha256": digest, "scope": "persistent_host_state"}
        if len(_persistent_seen) >= MAX_ENTRIES and normalize_url(url) not in _persistent_seen:
            del _persistent_seen[next(iter(_persistent_seen))]
        _persistent_seen[normalize_url(url)] = change
        _persistent_counts[status] += 1
        # Remember both ends of redirects so the original seed can revalidate next run.
        original = str((result.get("request") or {}).get("url") or result.get("url") or "")
        if original and _state_key(original) != key:
            omnicrawler_sdk.call("state.set", {"key": _state_key(original), "value": {"sha256": digest, "normalized_url": normalize_url(url), "status": status_code}})
        return {"persistent_change": change}
    if operation.startswith("hook."):
        return {}
    if operation != "processor.process":
        return {}

    result = dict(payload.get("result") or {})
    options = dict(payload.get("options") or {})
    url = str(result.get("final_url") or result.get("url") or (result.get("request") or {}).get("url") or "")
    if options.get("skip_incremental"):
        _counts["bypassed"] += 1
        change = {"status": "bypassed", "normalized_url": normalize_url(url), "scope": "current_run_only"}
    else:
        status_code = int(result.get("status") or 200)
        persistent = _persistent_seen.get(normalize_url(url))
        if persistent:
            change = {**persistent, "normalized_url": normalize_url(url)}
        elif status_code == 304 or not 200 <= status_code < 300:
            _counts["bypassed"] += 1
            change = {"status": "bypassed", "reason": "response_has_no_fresh_body", "scope": "current_run_only"}
        else:
            try:
                if result.get("body_b64") is None:
                    raise ValueError("missing body")
                body = base64.b64decode(str(result["body_b64"]), validate=True)
            except (ValueError, TypeError):
                _counts["invalid"] += 1
                change = {"status": "invalid", "reason": "missing_or_invalid_body", "scope": "current_run_only"}
            else:
                content_type = str(result.get("content_type") or "").lower()
                textual = content_type.startswith("text/") or any(t in content_type for t in ("json", "xml", "javascript"))
                # With no type declaration, preserve original bytes rather than guessing.
                normalize = bool(options.get("normalize_text", True)) and textual
                change = classify(url, body, normalize_text=normalize)
    evidence = hashlib.sha256(json.dumps(change, sort_keys=True).encode()).hexdigest()
    return {
        "records": [
            {
                "source_url": url,
                "record_type": "incremental_change",
                "data": change,
                "evidence": {"method": "tideprint-v1", "decision_sha256": evidence},
            }
        ],
        "requests": [],
        "artifact_path": None,
    }
