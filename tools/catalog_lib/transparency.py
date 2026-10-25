#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P3-11：签名透明日志 POSIX 路径归一、历史迁移与 CI 校验。

- 新条目写入前经 ``canonicalize_entry`` 归一（反斜杠 → ``/``）；
- ``migrate_transparency_log`` 一次性把历史 Windows 路径改写为 POSIX；
- ``check_transparency_log`` 供 CI 复核：JSON 合法、路径字段无反斜杠。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 日志中承载相对路径的字段（新增路径字段须在此登记）。
PATH_FIELDS = (
    "plugin",
    "package_manifest_file",
    "creator_identity_file",
    "creator_signature_file",
    "maintainer_signature_file",
)


def canonicalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """把路径字段中的反斜杠统一替换为 POSIX 正斜杠；其余字段原样保留。"""
    out = dict(entry)
    for field in PATH_FIELDS:
        value = out.get(field)
        if isinstance(value, str):
            out[field] = value.replace("\\", "/")
    return out


def migrate_transparency_log(path: Path) -> int:
    """就地迁移历史日志：返回被改写的条目数（路径归一化）。"""
    if not path.is_file():
        return 0
    original_lines = path.read_text(encoding="utf-8").splitlines()
    rewritten: list[str] = []
    changed = 0
    for line in original_lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        canonical = canonicalize_entry(entry)
        if canonical != entry:
            changed += 1
        rewritten.append(json.dumps(canonical, ensure_ascii=False, sort_keys=True) + "\n")
    path.write_text("".join(rewritten), encoding="utf-8", newline="\n")
    return changed


def check_transparency_log(path: Path) -> list[str]:
    """返回日志违规清单（空列表即通过）：JSON 非法、路径字段含反斜杠。"""
    findings: list[str] = []
    if not path.is_file():
        return findings
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(f"第 {lineno} 行 JSON 非法: {exc}")
            continue
        if not isinstance(entry, dict):
            findings.append(f"第 {lineno} 行不是映射")
            continue
        for field in PATH_FIELDS:
            value = entry.get(field)
            if isinstance(value, str) and "\\" in value:
                findings.append(f"第 {lineno} 行 {field} 含反斜杠路径: {value}")
    return findings


__all__ = ["PATH_FIELDS", "canonicalize_entry", "migrate_transparency_log", "check_transparency_log"]
