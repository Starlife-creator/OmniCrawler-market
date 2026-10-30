#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""下架墓碑（tombstones.json）加载与合法性校验。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import *
from .paths import PLUGIN_ID_RE, TEMPLATE_ID_RE, template_dir_name_to_id


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
    # P3-6：冲突判定规范化到 catalog ID——模板目录名用 ``--`` 分隔层级，
    # catalog ID 用 ``/``；不做归一会让层级模板墓碑绕过冲突检查（误标在线为下架）。
    existing_plugin_ids = {
        p.name for p in (registry / _PLUGIN_DIR).glob("*") if p.is_dir()
    } if (registry / _PLUGIN_DIR).is_dir() else set()
    existing_template_ids = {
        template_dir_name_to_id(t.name)
        for t in (registry / _TEMPLATES_DIR).glob("*") if t.is_dir()
    } if (registry / _TEMPLATES_DIR).is_dir() else set()
    tombstones: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"tombstone 条目必须是映射: {item!r}")
        for key in ("id", "removed_at", "reason"):
            if not str(item.get(key) or "").strip():
                raise ValueError(f"tombstone 缺少必填字段 {key}: {item!r}")
        tid = str(item["id"])
        if not (PLUGIN_ID_RE.fullmatch(tid) or TEMPLATE_ID_RE.fullmatch(tid)):
            raise ValueError(
                f"tombstone {tid!r} 非法 ID（须匹配插件或模板 catalog ID 形态）"
            )
        if tid in existing_plugin_ids or tid in existing_template_ids:
            raise ValueError(f"tombstone {tid!r} 与现存插件/模板冲突（下架条目不得在线）")
        tomb: dict[str, Any] = {
            "id": tid,
            "removed_at": str(item["removed_at"]),
            "reason": str(item["reason"]),
        }
        # 版本级墓碑（P0-2 配套，对齐主仓 check_revocation 版本匹配）：仅吊销命中版本；
        # 未声明 version/versions 表示整条目下架。
        t_version = item.get("version")
        t_versions = item.get("versions")
        if t_version is not None:
            if not isinstance(t_version, str) or not t_version.strip():
                raise ValueError(f"tombstone {tid!r} 的 version 须为非空字符串")
            tomb["version"] = t_version.strip()
        elif t_versions is not None:
            if not isinstance(t_versions, list) or not all(
                isinstance(v, str) and v.strip() for v in t_versions
            ):
                raise ValueError(f"tombstone {tid!r} 的 versions 须为版本字符串列表")
            tomb["versions"] = [v.strip() for v in t_versions]
        tombstones.append(tomb)
    return tombstones


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
