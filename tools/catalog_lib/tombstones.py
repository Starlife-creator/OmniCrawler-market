#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""下架墓碑（tombstones.json）加载与合法性校验。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import *


def _load_tombstones(registry: Path) -> list[dict[str, Any]]:
    """A5 tombstone：已下架插件/模板的墓碑条目（保留审计连续性）。

    ``tombstones.json`` 为仓库根的可选文件，形如：
    ``[{"id": "some_plugin", "removed_at": "2026-08-20", "reason": "恶意吊销"}]``。
    校验：id/removed_at/reason 必填；与现存 plugin/template 目录冲突 → 拒（防
    误把在线插件标为下架）。tombstone 不进入 plugins/templates 数组，单独成块，
    应用端（market_client）据此在吊销检查时给出"已下架"提示而非静默缺失。
    """
    path = registry / "tombstones.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"tombstones.json 非法 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("tombstones.json 顶层必须是数组")
    existing_plugin_ids = {p.name for p in (registry / _PLUGIN_DIR).glob("*") if p.is_dir()} if (registry / _PLUGIN_DIR).is_dir() else set()
    existing_template_ids = {t.name for t in (registry / _TEMPLATES_DIR).glob("*") if t.is_dir()} if (registry / _TEMPLATES_DIR).is_dir() else set()
    tombstones: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"tombstone 条目必须是映射: {item!r}")
        for key in ("id", "removed_at", "reason"):
            if not str(item.get(key) or "").strip():
                raise ValueError(f"tombstone 缺少必填字段 {key}: {item!r}")
        tid = str(item["id"])
        if tid in existing_plugin_ids or tid in existing_template_ids:
            raise ValueError(f"tombstone {tid!r} 与现存插件/模板目录冲突（下架条目不得在线）")
        tombstones.append({
            "id": tid,
            "removed_at": str(item["removed_at"]),
            "reason": str(item["reason"]),
        })
    return tombstones


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
