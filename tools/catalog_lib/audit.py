#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P3-8：统一审计事件结构（市场仓侧）。

事件类型：install / uninstall / revoke / failure。事件字段包含 plugin_id、
creator_fingerprint、version、manifest_sha256、决策码、来源与时间戳。
写入失败不再静默吞错——抛出 ``AuditWriteError`` 由调用方上报 warning。

主仓 CLI / market_client / GUI 三入口同源发事件为跨仓配套（主仓侧待落地）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

AUDIT_EVENT_TYPES = {"install", "uninstall", "revoke", "failure"}
REQUIRED_EVENT_FIELDS = (
    "event_type",
    "plugin_id",
    "creator_fingerprint",
    "version",
    "manifest_sha256",
    "decision",
    "source",
    "timestamp",
)


class AuditEventError(ValueError):
    """审计事件结构非法。"""


class AuditWriteError(OSError):
    """审计日志写入失败（best-effort 不再静默丢弃，须由调用方告警）。"""


def new_event(
    event_type: str,
    *,
    plugin_id: str,
    creator_fingerprint: str,
    version: str,
    manifest_sha256: str,
    decision: str,
    source: str,
    detail: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if event_type not in AUDIT_EVENT_TYPES:
        raise AuditEventError(f"非法审计事件类型: {event_type!r}（{sorted(AUDIT_EVENT_TYPES)}）")
    event: dict[str, Any] = {
        "event_type": event_type,
        "plugin_id": plugin_id,
        "creator_fingerprint": creator_fingerprint,
        "version": version,
        "manifest_sha256": manifest_sha256,
        "decision": decision,
        "source": source,
        "timestamp": timestamp or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if detail:
        event["detail"] = detail
    validate_event(event)
    return event


def validate_event(event: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_EVENT_FIELDS if not str(event.get(field) or "").strip()]
    if missing:
        raise AuditEventError(f"审计事件缺少必填字段 {missing}: {event}")
    if event["event_type"] not in AUDIT_EVENT_TYPES:
        raise AuditEventError(f"非法审计事件类型: {event['event_type']!r}")


def append_audit_event(log_path: Path, event: dict[str, Any]) -> None:
    """把一条审计事件追加到 JSONL 日志；写入失败抛 AuditWriteError 供上层告警。"""
    validate_event(event)
    try:
        stream: TextIO = log_path.open("a", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise AuditWriteError(f"审计日志无法打开 {log_path}: {exc}") from exc
    try:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
    except OSError as exc:
        raise AuditWriteError(f"审计日志写入失败 {log_path}: {exc}") from exc
    finally:
        stream.close()
