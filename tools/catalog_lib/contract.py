#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""市场仓侧纯函数契约层：元数据漂移比对、运行文件分类、依赖指纹（P2-10/P3-10/P2-6）。

- P2-10：overlay 与创作者签名载荷的可比对字段双向一致性；安装期调用属主仓配套。
- P3-10：运行必需文件 vs 测试/文档/许可等非运行时文件分类；主仓下载清单过滤待配套。
- P2-6：声明依赖的规范化指纹（离线漏洞基线/联网 CVE 扫描属外部环境配套，不在本模块）。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

# --- P3-10 运行必需文件分类 ---------------------------------------------------
NON_RUNTIME_DIR_PARTS = {"tests", "test", "docs", "examples", "example"}
_NON_RUNTIME_NAME_RE = re.compile(
    r"^(readme|license|licence|changelog|notice|contributing|security|"
    r"authors?|manifest|notes?|changes?)(\..*)?$",
    re.IGNORECASE,
)


def is_runtime_file(rel: str) -> bool:
    """声明路径是否属于安装运行时必需文件。

    tests/docs/examples 目录与 README/LICENSE/CHANGELOG/NOTES 等辅助材料归为
    非运行时；主仓下载清单过滤为跨仓配套（P3-10 主仓侧待落地）。
    """
    parts = [part for part in str(rel).split("/") if part]
    if not parts:
        return False
    if any(part in NON_RUNTIME_DIR_PARTS for part in parts[:-1]):
        return False
    name = parts[-1]
    if _NON_RUNTIME_NAME_RE.match(name):
        return False
    if name.endswith((".md", ".rst", ".txt")) and name not in {"listing.md"}:
        # listing.md 是市场展示描述文件，overlay 显式引用；其余说明文档非运行时。
        return False
    return True


def classify_files(files: Iterable[str]) -> tuple[list[str], list[str]]:
    """返回 (runtime_files, non_runtime_files)，保持输入顺序。"""
    runtime: list[str] = []
    non_runtime: list[str] = []
    for rel in files:
        (runtime if is_runtime_file(rel) else non_runtime).append(str(rel))
    return runtime, non_runtime


# --- P2-10 overlay ↔ 载荷可比对字段 -------------------------------------------
COMPARABLE_FIELDS = (
    "permissions",
    "domains",
    "input_files",
    "dependencies",
    "required_capabilities",
)


def _norm_str_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(item).strip().casefold() for item in values if str(item).strip()}


def _dep_name_set(dependencies: Any) -> set[str]:
    if not isinstance(dependencies, list):
        return set()
    names: set[str] = set()
    for dep in dependencies:
        if isinstance(dep, dict) and dep.get("name"):
            names.add(str(dep["name"]).strip().casefold())
    return names


def _capability_set(capabilities: Any) -> set[str]:
    if not isinstance(capabilities, dict):
        return set()
    return {str(name).strip() for name in capabilities if str(name).strip()}


def compare_overlay_payload(overlay: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """比对 overlay 与创作者签名载荷的可比对字段，返回漂移描述列表（空 = 一致）。

    载荷侧字段取自 ``PLUGIN_METADATA`` / 投稿 ``plugin.yaml``；overlay 是市场展示层。
    安装期双向拒装/告警由主仓安装链路调用（跨仓主仓侧待配套）。
    """
    drift: list[str] = []
    field_compare = {
        "permissions": (_norm_str_set(overlay.get("permissions")), _norm_str_set(payload.get("permissions"))),
        "domains": (_norm_str_set(overlay.get("domains")), _norm_str_set(payload.get("domains"))),
        "input_files": (_norm_str_set(overlay.get("input_files")), _norm_str_set(payload.get("input_files"))),
        "dependencies": (_dep_name_set(overlay.get("dependencies")), _dep_name_set(payload.get("dependencies"))),
        "required_capabilities": (
            _capability_set(overlay.get("required_capabilities")),
            _capability_set(payload.get("required_capabilities")),
        ),
    }
    for field, (overlay_set, payload_set) in field_compare.items():
        only_overlay = sorted(overlay_set - payload_set)
        only_payload = sorted(payload_set - overlay_set)
        if only_overlay:
            drift.append(f"overlay 声明了载荷未声明的 {field}: {only_overlay}")
        if only_payload:
            drift.append(f"载荷声明了 overlay 未展示的 {field}: {only_payload}")
    return drift


def security_field_expansion(prev: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """门 4 扩权检测：新条目相对上一版扩大的安全相关字段集合。

    permissions/domains/input_files/dependencies/required_capabilities 任一集合
    只增不减也算扩权；集合内容替换（增删并存）同样纳入变更清单。
    """
    expansions: list[str] = []
    set_compare = {
        "permissions": (_norm_str_set(prev.get("permissions")), _norm_str_set(new.get("permissions"))),
        "domains": (_norm_str_set(prev.get("domains")), _norm_str_set(new.get("domains"))),
        "input_files": (_norm_str_set(prev.get("input_files")), _norm_str_set(new.get("input_files"))),
        "dependencies": (_dep_name_set(prev.get("dependencies")), _dep_name_set(new.get("dependencies"))),
        "required_capabilities": (
            _capability_set(prev.get("required_capabilities")),
            _capability_set(new.get("required_capabilities")),
        ),
    }
    for field, (old_set, new_set) in set_compare.items():
        if new_set != old_set:
            added = sorted(new_set - old_set)
            removed = sorted(old_set - new_set)
            detail = f"新增 {added}" if added else ""
            if removed:
                detail += f"；移除 {removed}" if detail else f"移除 {removed}"
            expansions.append(f"{field}（{detail.strip('；')}）")
    return expansions


# --- P2-6 依赖规范化指纹 -------------------------------------------------------
def dependency_fingerprint(dependencies: list[dict[str, Any]]) -> str:
    """声明依赖集合的规范化 SHA-256 指纹（排序后 canonical JSON）。

    用于发布清单固化依赖声明；离线漏洞基线与联网 CVE 扫描属外部环境配套
    （P2-6 主仓/CI 侧待落地），本函数不做漏洞判定。
    """
    normalized: list[dict[str, Any]] = []
    for dep in dependencies:
        if not isinstance(dep, dict):
            continue
        normalized.append(
            {
                "name": str(dep.get("name", "")).strip().casefold(),
                "version": str(dep.get("version", "")).strip(),
                "license": str(dep.get("license", "")).strip(),
            }
        )
    normalized.sort(key=lambda item: item["name"])
    canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
