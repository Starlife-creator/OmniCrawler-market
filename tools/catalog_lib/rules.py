#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""一致性核对、上一版目录加载、版本门规则。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import *


def _check_consistency(registry: Path, catalog: dict[str, Any]) -> None:
    existing_path = registry / "catalog.json"
    if not existing_path.is_file():
        raise ValueError(f"catalog.json 缺失（先运行生成器）: {existing_path}")
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    # generated_at 是时间戳；sequence 由 generated_at 推导（G3 防重放，--check
    # 重新生成必然不同）；publisher 是生成参数（--publisher 覆盖时顶层不同，
    # 与源无关，排除以免 --check 误失败，P3-4）
    parametric = {"generated_at", "sequence", "publisher"}
    expected = {key: value for key, value in catalog.items() if key not in parametric}
    actual = {key: value for key, value in existing.items() if key not in parametric}
    if expected != actual:
        # 报告具体漂移键（G1 后 sha256 漂移是最常见信号——内容篡改的哈希防线）
        drifted = sorted(
            {key for key in expected if expected.get(key) != actual.get(key)}
            | {key for key in actual if expected.get(key) != actual.get(key)}
        )
        raise ValueError(
            "catalog.json 与 plugin.yaml 源不一致（请运行 tools/generate_catalog.py 重新生成）；"
            f"漂移字段: {drifted}"
        )

def _load_prev_catalog(registry: Path, explicit: str | None) -> dict[str, Any] | None:
    """门 4 的"上一版 catalog 快照"来源（Phase 1）。

    优先级：--prev-catalog 显式路径 > git 历史（HEAD 的上一个 catalog.json）。
    git-as-registry 下 catalog.json 随仓库提交，上一版快照即 git 历史中的版本。
    无可用基线（新仓库/非 git 环境）返回 None —— 门 4 属变更检测门禁，
    基线不可得时跳过并警告（不 fail：它校验的是"变更伴随升版"，无旧版可参照
    时语义不适用；与内容合法性门禁的 fail-closed 语义区分）。
    """
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ValueError(f"--prev-catalog 指定的文件不存在: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
    # best-effort：git show HEAD^:catalog.json（合并提交/PR 场景 HEAD^ 为基线侧）
    try:
        import subprocess

        result = subprocess.run(
            ["git", "show", "HEAD^:catalog.json"],
            cwd=str(registry),
            capture_output=True,
            encoding="utf-8",          # P2-5：显式 UTF-8，避免 Windows locale(GBK) 解码崩
            errors="replace",          # 非 UTF-8 字节降级替换，绝不抛异常
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

def _parse_version(version: str) -> tuple[int, ...]:
    """宽松 semver 解析：取数字段比较，非数字段按 0 处理（防版本比较崩溃）。"""
    parts: list[int] = []
    for chunk in str(version).strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)

def _check_version_rules(
    registry: Path, catalog: dict[str, Any], prev_catalog: dict[str, Any] | None
) -> list[str]:
    """门 4（变更规则，Phase 1，方案 A5）：license/execution_mode 变更必须
    伴随版本递增 + 重新走发布门禁与签名；版本不允许倒退。

    比对对象：新 catalog 的插件条目 vs 上一版快照的同 id 条目。
    返回警告列表（基线缺失时）。
    """
    if prev_catalog is None:
        return ["门 4：无上一版 catalog 基线（新仓库或非 git 环境），变更规则检查跳过"]
    prev_plugins = {
        str(entry.get("id")): entry for entry in prev_catalog.get("plugins", [])
    }
    warnings: list[str] = []
    for entry in catalog.get("plugins", []):
        pid = str(entry["id"])
        prev = prev_plugins.get(pid)
        if prev is None:
            continue  # 新插件，无变更可言
        new_version = str(entry.get("version", ""))
        old_version = str(prev.get("version", ""))
        if _parse_version(new_version) < _parse_version(old_version):
            raise ValueError(
                f"插件 {pid} 版本倒退（{old_version} → {new_version}）：门 4 禁止降版"
            )
        changed: list[str] = []
        if str(entry.get("license", "")) != str(prev.get("license", "")):
            changed.append("license")
        # execution_mode 比对前做 schema 迁移归一化：旧 catalog 无此字段时
        # 等价于缺省 subprocess（Phase 1 语义），不算字段变更（防 schema
        # 迁移首跑被门 4 误报为"变更未升版"）
        new_mode = str(entry.get("execution_mode") or "subprocess")
        old_mode = str(prev.get("execution_mode") or "subprocess")
        if new_mode != old_mode:
            changed.append("execution_mode")
        if changed and _parse_version(new_version) <= _parse_version(old_version):
            raise ValueError(
                f"插件 {pid} 字段 {changed} 变更但版本未递增"
                f"（{old_version} → {new_version}）：门 4 要求 license/execution_mode "
                f"变更必须升版并重新走发布门禁与签名（A5）"
            )
    return warnings


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
