#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P1-2：离线快照签名校验与新鲜度规则（市场仓侧）。

主仓内置 ``market/`` 捆绑快照随版本打包、内置缺签名时 UI 明示"离线索引不可信"属
跨仓主仓侧配套；本模块提供市场仓自包含的快照导出、签名复核与新鲜度比对纯函数与
规则，供发布工具与 CI 复用。
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .signing import verify_against_roots

# 快照导出时复制的目录与文件清单（与在线分发内容对齐）。
SNAPSHOT_ENTRIES = ("authors", "keys", "plugins", "templates")
SNAPSHOT_FILES = ("catalog.json", "catalog.json.sig")
DEFAULT_MAX_AGE_HOURS = 24 * 30  # 30 天：超过即视为陈旧快照（可调用方覆盖）


def _parse_generated_at(catalog: dict[str, Any]) -> datetime:
    raw = str(catalog.get("generated_at", "")).strip()
    if not raw:
        raise ValueError("catalog 缺少 generated_at 时间戳")
    normalized = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def snapshot_age_hours(catalog: dict[str, Any], *, now: datetime | None = None) -> float:
    """快照相对当前时间的小时数（UTC）。"""
    now = now or datetime.now(UTC)
    generated = _parse_generated_at(catalog)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    return max(0.0, (now - generated).total_seconds() / 3600)


def is_snapshot_fresh(
    catalog: dict[str, Any],
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> tuple[bool, float]:
    """新鲜度比对：返回 ``(fresh, age_hours)``；超龄即陈旧。"""
    age = snapshot_age_hours(catalog, now=now)
    return age <= max_age_hours, age


def verify_snapshot(
    snapshot_dir: Path,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
    require_fresh: bool = False,
) -> tuple[bool, list[str]]:
    """复核离线快照：签名 fail-closed 缺失即拒绝；新鲜度按策略给出陈旧告警/拒绝。

    返回 ``(ok, findings)``。缺 ``catalog.json.sig`` / 签名无效 / catalog 缺失为
    错误级 findings；陈旧仅在 ``require_fresh=True`` 时阻断，否则仅告警。
    """
    findings: list[str] = []
    catalog_path = snapshot_dir / "catalog.json"
    signature_path = snapshot_dir / "catalog.json.sig"
    if not catalog_path.is_file():
        findings.append("快照缺少 catalog.json（离线索引不可信）")
        return False, findings
    if not signature_path.is_file():
        # P1-2：缺签名 fail-closed——缺签名时离线索引不可信，不得静默回退为可信。
        findings.append("快照缺少 catalog.json.sig（fail-closed，拒绝把离线索索引为可信）")
        return False, findings
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ok, root = verify_against_roots(
        snapshot_dir, catalog_path.read_bytes(), signature_path.read_bytes()
    )
    if not ok:
        findings.append("快照 catalog.json.sig 未覆盖当前 catalog.json（签名无效，拒绝离线使用）")
        return False, findings
    try:
        fresh, age = is_snapshot_fresh(catalog, max_age_hours=max_age_hours, now=now)
    except ValueError as exc:
        findings.append(f"快照时间戳非法: {exc}")
        return False, findings
    if not fresh:
        message = f"快照陈旧：已发布 {age:.1f} 小时（阈值 {max_age_hours} 小时）"
        if require_fresh:
            findings.append(message + "（--require-fresh：拒绝使用陈旧快照）")
        else:
            findings.append("warning: " + message + "（可在线刷新；不阻断签名复核）")
    if any(not finding.startswith("warning: ") for finding in findings):
        return False, findings
    return True, findings


def export_snapshot(registry: Path, destination: Path) -> Path:
    """把在线目录打包为自包含离线快照目录（catalog + 签名 + 信任材料 + 载荷目录）。"""
    destination.mkdir(parents=True, exist_ok=True)
    for name in SNAPSHOT_FILES:
        source = registry / name
        if source.is_file():
            shutil.copyfile(source, destination / name)
    for name in SNAPSHOT_ENTRIES:
        source = registry / name
        if source.is_dir():
            shutil.copytree(source, destination / name, dirs_exist_ok=True)
    return destination
