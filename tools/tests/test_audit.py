"""P3-8：统一审计事件结构校验、必填字段与写入失败告警（不静默吞错）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog_lib.audit import (
    AUDIT_EVENT_TYPES,
    AuditEventError,
    AuditWriteError,
    append_audit_event,
    new_event,
    validate_event,
)


def _event(**overrides: dict) -> dict:
    base = dict(
        event_type="install",
        plugin_id="demo-processor",
        creator_fingerprint="f" * 32,
        version="1.0.0",
        manifest_sha256="a" * 64,
        decision="accepted",
        source="market_client",
        timestamp="2026-10-25T00:00:00+00:00",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("event_type", sorted(AUDIT_EVENT_TYPES))
def test_supported_event_types_accepted(event_type: str) -> None:
    event = new_event(
        event_type,
        plugin_id="p",
        creator_fingerprint="f" * 32,
        version="1.0.0",
        manifest_sha256="a" * 64,
        decision="accepted",
        source="gui",
    )
    assert event["event_type"] == event_type


def test_unsupported_event_type_rejected() -> None:
    with pytest.raises(AuditEventError, match="非法审计事件类型"):
        new_event(
            "hijack",
            plugin_id="p",
            creator_fingerprint="f" * 32,
            version="1.0.0",
            manifest_sha256="a" * 64,
            decision="accepted",
            source="gui",
        )


def test_missing_required_field_rejected() -> None:
    event = _event()
    del event["plugin_id"]
    with pytest.raises(AuditEventError, match="plugin_id"):
        validate_event(event)


def test_event_appended_to_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    append_audit_event(log, new_event(
        "uninstall", plugin_id="p", creator_fingerprint="f" * 32,
        version="1.0.0", manifest_sha256="a" * 64,
        decision="removed", source="market_client",
    ))
    append_audit_event(log, new_event(
        "revoke", plugin_id="q", creator_fingerprint="f" * 32,
        version="2.0.0", manifest_sha256="b" * 64,
        decision="revoked", source="admin",
    ))
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_write_failure_raises_audit_write_error(tmp_path: Path) -> None:
    # 只读目录下打开追加流应抛 AuditWriteError，而非静默吞错。
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o444)
    try:
        with pytest.raises(AuditWriteError):
            append_audit_event(
                readonly / "events.jsonl",
                new_event(
                    "failure", plugin_id="p", creator_fingerprint="f" * 32,
                    version="1.0.0", manifest_sha256="a" * 64,
                    decision="failed", source="cli",
                ),
            )
    finally:
        readonly.chmod(0o755)
