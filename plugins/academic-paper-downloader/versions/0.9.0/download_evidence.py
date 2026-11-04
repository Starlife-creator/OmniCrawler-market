"""Pure identity/provenance helpers; no network or credential access."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


def normalize_doi(value: str) -> str:
    value = str(value).strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    value = unquote(value).strip().casefold()
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else ""


def public_source_url(value: str) -> str:
    """Discard userinfo, all query/fragment values and local file paths."""
    try:
        parts = urlsplit(str(value))
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        host = parts.hostname
        if ":" in host:
            host = "[" + host + "]"
        if parts.port:
            host += ":" + str(parts.port)
        # Some download APIs put authentication in path components.
        path = re.sub(r"(?i)(/(?:token|secret|password|api[_-]?key)/)[^/]+", r"\1[REDACTED]", parts.path)
        return urlunsplit((parts.scheme, host, path, "", ""))[:2000]
    except ValueError:
        return ""


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_evidence(record: dict, source_url: str = "", duration_ms: int = 0) -> dict:
    return {"schema_version": 1, "doi": normalize_doi(record.get("doi", "")),
            "channel": record.get("download_source", "unknown"), "source_url": public_source_url(source_url),
            "file_size": record.get("file_size", 0), "sha256": record.get("sha256", ""),
            "validation_level": record.get("pdf_meta", {}).get("validation_level", "unknown"),
            "verification": record.get("verification", "unverified"), "duration_ms": max(0, int(duration_ms))}
