#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""目录聚合生成 build_catalog 与落盘 generate。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .authors import *
from .common import *
from .schema import *
from .signing import *
from .tombstones import *


def build_catalog(registry: Path, *, publisher_override: str | None = None) -> dict[str, Any]:
    plugins_dir = registry / _PLUGIN_DIR
    if not plugins_dir.is_dir():
        raise ValueError(f"registry 缺少 {_PLUGIN_DIR}/ 目录: {plugins_dir}")

    entries: list[dict[str, Any]] = []
    publishers: list[str] = []
    seen_plugin_ids: set[str] = set()
    for manifest_path in sorted(plugins_dir.glob("*/plugin.yaml")):
        manifest = _load_yaml(manifest_path)
        entry = _entry_from_yaml(manifest, manifest_path)
        pid = str(entry["id"])
        # B02-015：重复插件 ID 静默后者覆盖 → fail-closed 显式报错（对齐模板 G7）
        if pid in seen_plugin_ids:
            raise ValueError(f"重复插件 ID（禁止静默覆盖）: {pid}（{manifest_path}）")
        seen_plugin_ids.add(pid)
        entries.append(entry)
        publisher = str(entry.get("publisher", ""))
        if publisher and publisher not in publishers:
            publishers.append(publisher)

    template_entries: list[dict[str, Any]] = []
    template_markets: dict[str, dict[str, Any]] = {}
    seen_template_ids: set[str] = set()
    templates_dir = registry / _TEMPLATES_DIR
    if templates_dir.is_dir():
        for template_yaml in sorted(templates_dir.glob("*/template.yaml")):
            entry, market = _entry_from_template_yaml(template_yaml)
            tid = str(entry["id"])
            # G7：重复模板 ID 静默后者覆盖 → 改为 fail-closed 显式报错
            if tid in seen_template_ids:
                raise ValueError(f"重复模板 ID（禁止静默覆盖）: {tid}（{template_yaml}）")
            seen_template_ids.add(tid)
            template_entries.append(entry)
            template_markets[tid] = market
            publisher = str(entry.get("publisher", ""))
            if publisher and publisher not in publishers:
                publishers.append(publisher)

    authors = load_authors(registry)
    _check_display_name_suffixes(authors)
    manifests: dict[str, dict[str, Any]] = {}
    for manifest_path in sorted(plugins_dir.glob("*/plugin.yaml")):
        manifest = _load_yaml(manifest_path)
        manifests[str(manifest.get("id", ""))] = manifest
    for manifest in manifests.values():
        _check_author(manifest, authors)
    for market in template_markets.values():
        _check_author(market, authors)

    for entry in entries:
        _check_creator_rail(registry, entry)
        for key in ("description_file", "plugin_file"):
            rel = entry.get(key)
            if rel:
                resolved = _require_contained(registry, registry, str(rel), f"插件 {entry['id']} 的 {key}")
                if not resolved.is_file():
                    raise ValueError(f"插件 {entry['id']} 的 {key} 不存在: {rel}")
        # 签名轨完整性：维护者签名（signature_file）与创作者签名
        # （creator_signature_file + creator_identity_file）至少一条完备。
        # 修复前 GUI 上传包声明 signature_file 却不出产该文件（审查报告 S50），
        # 此处把"声明但缺失"显式判为待补签状态而非静默错误。
        sig = entry.get("signature_file")
        has_sig = bool(sig) and (registry / str(sig)).is_file()
        c_sig = entry.get("creator_signature_file")
        c_id = entry.get("creator_identity_file")
        has_creator_rail = (
            bool(c_sig)
            and bool(c_id)
            and (registry / str(c_sig)).is_file()
            and (registry / str(c_id)).is_file()
        )
        if not has_sig and not has_creator_rail:
            raise ValueError(
                f"插件 {entry['id']} 缺少完整签名轨：需要 plugin.py.sig（维护者补签）"
                f"或 creator.sig + creator.identity（创作者签名）"
            )
        # G1（time-of-check 后门防线）：固化 plugin.py 当前内容 sha256——恶意
        # 作者在 CI 绿后改内容，客户端下载校验即发现。写入 versions 映射，
        # 历史版本哈希随发布历史累积（git-as-registry 单目录布局下当前版本
        # 哈希由最新 tag 门禁生成）。
        plugin_rel = entry.get("plugin_file")
        if plugin_rel:
            plugin_path = registry / str(plugin_rel)
            if plugin_path.is_file():
                digest = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
                versions = entry.setdefault("versions", {})
                versions[str(entry["version"])] = {"sha256": digest}
    for entry in template_entries:
        _check_creator_rail(registry, entry)
        for key in ("template_file", "signature_file", "description_file", "creator_signature_file", "creator_identity_file"):
            rel = entry.get(key)
            if rel:
                resolved = _require_contained(registry, registry, str(rel), f"模板 {entry['id']} 的 {key}")
                if not resolved.is_file():
                    raise ValueError(f"模板 {entry['id']} 的 {key} 不存在: {rel}")

    entries.sort(key=lambda item: str(item["id"]))
    template_entries.sort(key=lambda item: str(item["id"]))
    publisher = publisher_override or (publishers[0] if publishers else "unknown")
    generated_at = datetime.now(timezone.utc)
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        # G3（catalog 防重放）：单调序列号 + 发布时间戳（均被签名覆盖）。
        # 客户端拒绝序列号/时间旧于本地缓存的 catalog（decision:
        # catalog_stale_rejected）——吊销不可被旧版 catalog 重放隐藏。
        "sequence": int(generated_at.timestamp()),
        "publisher": publisher,
        "trust_model": TRUST_MODEL,
        "trust_public_key_ref": TRUST_KEY_REF,
        "plugins": entries,
        "templates": template_entries,
    }
    tombstones = _load_tombstones(registry)
    if tombstones:
        catalog["tombstones"] = tombstones
    return catalog

def generate(registry: Path, *, publisher_override: str | None = None) -> Path:
    catalog = build_catalog(registry, publisher_override=publisher_override)
    # B02-024：生成路径同样验签（fail-closed 一致）。build_catalog 已保证签名文件
    # 存在（插件至少一条轨、模板强制维护者签名），此处只会在签名无效/信任根缺失时
    # 失败，防止本地生成签名无效的 catalog.json 被提交、等到 CI 才暴露。
    _verify_signatures(registry, catalog, None)
    output = registry / "catalog.json"
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
