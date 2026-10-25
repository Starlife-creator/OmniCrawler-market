#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P3-7：catalog 条目 ID→entry 索引字典（市场仓侧）。

主仓刷新时复用缓存、多源聚合后持久化索引属跨仓配套；本模块提供自包含索引构建、
冲突检测与线性兜底解析，供市场工具链与测试复用。
"""

from __future__ import annotations

from typing import Any, Iterable


def build_index(entries: Iterable[dict[str, Any]], *, key: str = "id") -> dict[str, dict[str, Any]]:
    """构建 ``id -> entry`` 索引；同一 ID 重复出现即 fail-closed 拒绝。

    多源聚合去重键为 ``(id, creator_fingerprint)``：同 ID 不同指纹应在构建前由
    聚合层标冲突，不进入本索引静默合并。
    """
    index: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_id = str(entry.get(key, ""))
        if not entry_id:
            raise ValueError("索引条目缺少 id 字段")
        if entry_id in index:
            existing = index[entry_id]
            if existing.get("creator_fingerprint") != entry.get("creator_fingerprint"):
                raise ValueError(
                    f"索引冲突：id {entry_id} 存在不同 creator_fingerprint 的条目"
                )
            continue
        index[entry_id] = entry
    return index


def resolve_entry(
    index: dict[str, dict[str, Any]],
    package_id: str,
    *,
    creator_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """按 ID 解析条目；给定指纹时要求创作者指纹一致，否则返回 None。"""
    entry = index.get(str(package_id))
    if entry is None:
        return None
    if creator_fingerprint and entry.get("creator_fingerprint") != creator_fingerprint:
        return None
    return entry
