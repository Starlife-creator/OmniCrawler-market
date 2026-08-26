#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""plugin.yaml / template.yaml → catalog 条目的构建与字段契约。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import *


def _entry_from_yaml(manifest: dict[str, Any], source: Path) -> dict[str, Any]:
    """把 plugin.yaml 转换为 catalog.json 条目（只透传 schema 字段）。"""
    missing = [key for key in _REQUIRED_KEYS if key not in manifest]
    if missing:
        raise ValueError(f"清单缺少必填字段 {missing}: {source}")
    unknown = set(manifest) - set(_ENTRY_KEYS) - _TOP_LEVEL_EXTRA
    if unknown:
        raise ValueError(f"清单包含未知字段 {sorted(unknown)}: {source}")
    entry = {key: manifest[key] for key in _ENTRY_KEYS if key in manifest}
    # 门 2（Phase 1）：license 必填 + SPDX 白名单——删除原 OmniCrawler-MIT
    # 隐式回退（未声明不再静默落为默认条款，直接拒）。
    license_id = str(entry["license"]).strip()
    if not license_id:
        raise ValueError(f"插件 {entry['id']} 的 license 为空（必填）: {source}")
    if license_id not in LICENSE_ALLOWLIST:
        raise ValueError(
            f"插件 {entry['id']} 的许可 {license_id!r} 不在 SPDX 白名单内（门 2，A2）: "
            f"{sorted(LICENSE_ALLOWLIST)}"
        )
    if not re.match(_ID_RE_PREFIX, str(entry["id"])):
        raise ValueError(f"非法插件 ID（须匹配 {_ID_RE_PREFIX}）: {entry['id']}")
    # Phase 1 第 2 条（B1）：execution_mode 缺省 subprocess（未声明按 subprocess，
    # 无兼容语义）；显式声明须为合法枚举。in_process 是特权申请（3.2 批准矩阵
    # 运行期裁决，catalog 侧只记录声明）。
    declared_mode = entry.get("execution_mode")
    if declared_mode is None:
        entry["execution_mode"] = "subprocess"
    elif str(declared_mode) not in ("in_process", "subprocess"):
        raise ValueError(
            f"插件 {entry['id']} 的 execution_mode 非法: {declared_mode!r}"
            f"（仅 in_process | subprocess）"
        )
    # domains：network 权限的域名白名单（schema 层仅校验类型/格式，
    # "有 network 权限必须有 domains" 的一致性属门 1，scan_plugin Phase 2）
    domains = entry.get("domains")
    if domains is not None:
        if not isinstance(domains, list) or not all(
            isinstance(d, str) and d.strip() for d in domains
        ):
            raise ValueError(f"插件 {entry['id']} 的 domains 必须是域名非空字符串列表")
    # dependencies：[{name, version, license}]（第 67 轮必填语义在主仓门 3 校验，
    # catalog 侧仅透传；未声明时缺省空列表）
    deps = entry.get("dependencies")
    if deps is not None:
        if not isinstance(deps, list):
            raise ValueError(f"插件 {entry['id']} 的 dependencies 必须是列表")
        for dep in deps:
            if not isinstance(dep, dict) or not dep.get("name"):
                raise ValueError(
                    f"插件 {entry['id']} 的 dependencies 条目非法: {dep!r}"
                    f"（须为含 name 的映射）"
                )
    return entry

def _entry_from_template_yaml(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """把 templates/<id>/template.yaml 转换为 catalog 模板条目。

    模板的 market 元数据放在 ``template:`` 块的 ``publisher`` /
    ``author_fingerprint`` 字段（内置模板不需要；市场模板必须声明）。
    返回 (条目, market 元数据块)。
    """
    raw = _load_yaml(path)
    if "project" not in raw or "source" not in raw:
        raise ValueError(f"不是采集模板（缺少 project/source）: {path}")
    block = raw.get("template", {})
    if not isinstance(block, dict) or not block:
        raise ValueError(f"模板缺少 template: 元数据块: {path}")
    for field in ("id", "name", "version", "category", "publisher", "author_fingerprint"):
        if not block.get(field):
            raise ValueError(f"模板 template: 块缺少必填字段 {field}: {path}")
    market = {
        "publisher": str(block["publisher"]),
        "author_fingerprint": str(block["author_fingerprint"]),
    }
    template_id = str(block["id"])
    if not re.match(_TEMPLATE_ID_RE_PREFIX, template_id):
        raise ValueError(f"非法模板 ID（须匹配 {_TEMPLATE_ID_RE_PREFIX}）: {template_id}")
    template_dir = path.parent
    listing = template_dir / "listing.md"
    # 门 2（Phase 1）：删除 OmniCrawler-MIT 隐式回退——模板 license 为数据/
    # 服务条款自由文本（A2 模板例外，不走 SPDX 白名单），但必须显式声明。
    template_license = str(block.get("license") or "").strip()
    if not template_license:
        raise ValueError(
            f"模板 {template_id} 缺少 license 声明（必填；数据/服务条款自由文本）: {path}"
        )
    entry: dict[str, Any] = {
        "id": template_id,
        "name": str(block["name"]),
        "version": str(block["version"]),
        "publisher": str(block["publisher"]),
        "category": str(block["category"]),
        "summary": str(block.get("description") or ""),
        "template_file": f"{_TEMPLATES_DIR}/{template_dir.name}/template.yaml",
        "signature_file": f"{_TEMPLATES_DIR}/{template_dir.name}/template.yaml.sig",
        "signature_algorithm": "ed25519",
        "compatible_core": f">={block.get('min_core_version') or '1.0.0'}",
        "license": template_license,
        "tags": list(block.get("tags") or []),
        "updated_at": str(block.get("verified_at") or ""),
    }
    # B02-002：模板创作者轨接入——creator.sig + creator.identity 随模板目录发布，
    # catalog 条目声明两字段，校验与验签链路与插件创作者轨对齐。
    if (template_dir / "creator.sig").is_file() and (template_dir / "creator.identity").is_file():
        entry["creator_signature_file"] = (
            f"{_TEMPLATES_DIR}/{template_dir.name}/creator.sig"
        )
        entry["creator_identity_file"] = (
            f"{_TEMPLATES_DIR}/{template_dir.name}/creator.identity"
        )
    if listing.is_file():
        entry["description_file"] = f"{_TEMPLATES_DIR}/{template_dir.name}/listing.md"
    for key in ("homepage",):
        if block.get(key):
            entry[key] = str(block[key])
    return entry, market


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
