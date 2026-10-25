#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""plugin.yaml / template.yaml → catalog 条目的构建与字段契约。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import *
from .core_version import SemVer, parse_compatible_core


def _validate_compatible_core(entry_id: str, declared: Any, source: Path) -> None:
    """P1-5：compatible_core semver 区间格式校验（schema/投稿/发现页共用同一解析器）。"""
    try:
        parse_compatible_core(str(declared))
    except ValueError as exc:
        raise ValueError(
            f"插件/模板 {entry_id} 的 compatible_core 非法: {exc}: {source}"
        ) from exc


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
    permissions = entry.get("permissions")
    if not isinstance(permissions, list) or not all(
        isinstance(item, str) and item.strip() for item in permissions
    ):
        raise ValueError(f"插件 {entry['id']} 的 permissions 必须是字符串列表")
    unknown_permissions = {item.strip().casefold() for item in permissions} - ALLOWED_PLUGIN_PERMISSIONS
    if unknown_permissions:
        raise ValueError(f"插件 {entry['id']} 声明未知权限: {sorted(unknown_permissions)}")
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
    plugin_types = entry.get("plugin_types")
    if plugin_types is not None:
        if not isinstance(plugin_types, list) or not plugin_types or not all(
            isinstance(item, str) and item.strip() for item in plugin_types
        ):
            raise ValueError(f"插件 {entry['id']} 的 plugin_types 必须是非空字符串列表")
        normalized = list(dict.fromkeys(item.strip().casefold() for item in plugin_types))
        unknown = set(normalized) - OFFICIAL_PLUGIN_TYPES
        if unknown:
            raise ValueError(f"插件 {entry['id']} 声明未知运行扩展点: {sorted(unknown)}")
        if "ui" in normalized:
            raise ValueError(
                f"插件 {entry['id']} 声明原生 ui；市场仅接受契约 2 subprocess 数据扩展，"
                "ui 只能作为受信任本地插件分发"
            )
        entry["plugin_types"] = normalized
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
    required_capabilities = entry.get("required_capabilities")
    if required_capabilities is not None:
        if not isinstance(required_capabilities, dict) or not all(
            isinstance(name, str)
            and name.strip()
            and re.fullmatch(r"(?:>=)?[1-9][0-9]*", str(requirement).strip())
            for name, requirement in required_capabilities.items()
        ):
            raise ValueError(
                f"插件 {entry['id']} 的 required_capabilities 必须是能力名到正整数/'>=正整数'的映射"
            )
        # P2-3：能力名必须存在于宿主契约白名单（镜像主仓 CAPABILITY_VERSIONS 键集合），
        # 避免未知能力名在市场 CI 绿、子进程启动前才被拒。
        unknown_caps = {
            str(name).strip() for name in required_capabilities
        } - ALLOWED_CAPABILITIES
        if unknown_caps:
            raise ValueError(
                f"插件 {entry['id']} 声明宿主不支持的能力: {sorted(unknown_caps)}"
            )
    state_schema_version = entry.get("state_schema_version")
    if state_schema_version is not None and (
        not isinstance(state_schema_version, int) or state_schema_version < 1
    ):
        raise ValueError(f"插件 {entry['id']} 的 state_schema_version 必须是正整数")
    # P1-5：compatible_core semver 区间格式统一由 core_version 解析器校验。
    _validate_compatible_core(entry["id"], entry.get("compatible_core"), source)
    # P0-2：条目级吊销/弃用状态结构校验（与目录顶层 tombstones 并列第二来源）。
    revoked = entry.get("revoked")
    if revoked is not None and not (
        isinstance(revoked, str) and revoked.strip()
        or isinstance(revoked, dict)
    ):
        raise ValueError(f"插件 {entry['id']} 的 revoked 须为非空字符串或映射")
    revoked_versions = entry.get("revoked_versions")
    if revoked_versions is not None:
        if not isinstance(revoked_versions, list) or not all(
            isinstance(v, str) and v.strip() for v in revoked_versions
        ):
            raise ValueError(f"插件 {entry['id']} 的 revoked_versions 须为版本字符串列表")
    deprecated = entry.get("deprecated")
    if deprecated is not None and not (
        isinstance(deprecated, str) and deprecated.strip()
        or isinstance(deprecated, dict)
    ):
        raise ValueError(f"插件 {entry['id']} 的 deprecated 须为非空字符串或映射")
    # P2-2：source_base 仅允许 http/https 同源基址（egress 策略由安装侧二次约束）。
    source_base = entry.get("source_base")
    if source_base is not None:
        base_str = str(source_base).strip()
        if not re.fullmatch(r"https?://[^\s/]+(?:/[^\s]*)?", base_str):
            raise ValueError(f"插件 {entry['id']} 的 source_base 须为 http(s) URL: {source_base!r}")
        entry["source_base"] = base_str.rstrip("/")
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
    # P1-5：min_core_version 单段版本号与派生 compatible_core 区间格式校验。
    if block.get("min_core_version"):
        SemVer.parse(str(block["min_core_version"]))
    compatible_core = f">={block.get('min_core_version') or '1.0.0'}"
    _validate_compatible_core(template_id, compatible_core, path)
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
        "compatible_core": compatible_core,
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


def _entry_from_template_market(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a market-owned overlay without rewriting creator-signed template.yaml."""
    raw = _load_yaml(path)
    required = {
        "id", "name", "version", "publisher", "author_fingerprint", "category",
        "summary", "template_file", "signature_file", "signature_algorithm",
        "compatible_core", "license",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"模板 market.yaml 缺少必填字段 {missing}: {path}")
    unknown = set(raw) - set(_TEMPLATE_ENTRY_KEYS) - {"author_fingerprint"}
    if unknown:
        raise ValueError(f"模板 market.yaml 包含未知字段 {sorted(unknown)}: {path}")
    template_id = str(raw["id"])
    if not re.match(_TEMPLATE_ID_RE_PREFIX, template_id):
        raise ValueError(f"非法模板 ID: {template_id}")
    # P1-5：compatible_core semver 区间格式校验。
    _validate_compatible_core(template_id, raw.get("compatible_core"), path)
    entry = {key: raw[key] for key in _TEMPLATE_ENTRY_KEYS if key in raw}
    return entry, {
        "id": template_id,
        "publisher": str(raw["publisher"]),
        "author_fingerprint": str(raw["author_fingerprint"]),
    }


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
