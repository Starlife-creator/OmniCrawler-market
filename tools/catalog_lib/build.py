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


def _entry_from_component_recipe(recipe_path: Path) -> dict[str, Any]:
    """把 ``components/<id>/recipe.json`` 转成 catalog 组件条目。

    与插件/模板条目的差别：**这里不托管字节**，所以没有 package 文件、
    没有包哈希；有的是 recipe 自身的摘要（客户端据此判断"装的是不是
    审查过的那份声明"）与上游构件清单。
    """
    import hashlib
    import json

    directory = recipe_path.parent
    try:
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"组件 recipe 无法解析 {recipe_path}: {exc}") from exc
    if not isinstance(recipe, dict):
        raise ValueError(f"组件 recipe 必须是 JSON 对象: {recipe_path}")

    component_id = str(directory.name)
    for key in ("name", "version", "platforms", "architectures", "artifacts", "entry"):
        if key not in recipe:
            raise ValueError(f"组件 {component_id} 的 recipe 缺少 {key}")

    artifacts = recipe.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError(f"组件 {component_id} 的 recipe 需要至少一个 artifact")
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise ValueError(f"组件 {component_id} 的 artifact #{index} 必须是对象")
        # 没有 sha256 就无法校验来源——与宿主侧同一条纪律，逐条强制。
        digest = artifact.get("sha256")
        if not (isinstance(digest, str) and len(digest) == 64):
            raise ValueError(
                f"组件 {component_id} 的 artifact #{index} 缺少合法 sha256"
            )

    # recipe 摘要：稳定排序后哈希，客户端据此核对
    canonical = json.dumps(recipe, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    recipe_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    relative = recipe_path.relative_to(recipe_path.parents[2])
    entry: dict[str, Any] = {
        "id": component_id,
        "name": str(recipe.get("description") or component_id),
        "version": str(recipe["version"]),
        "publisher": _component_publisher(directory),
        "recipe_file": str(relative).replace("\\", "/"),
        "recipe_digest": recipe_digest,
        "platforms": list(recipe["platforms"]),
        "architectures": list(recipe["architectures"]),
        # ABI 声明必须进 catalog：重型 C 扩展与解释器版本强耦合，
        # 客户端据此在**下载前**就判断"这台机器装不了"，而不是拉到一半才失败。
        "python_abi": list(recipe.get("python_abi") or []),
        "entry": dict(recipe["entry"]),
        "artifacts": [
            {
                "url": str(item["url"]),
                "sha256": str(item["sha256"]),
                "size": item.get("size"),
            }
            for item in artifacts
        ],
        # 声明总大小：让客户端在**下载前**展示"要拉多少"，而不是装到一半才发现
        "declared_total_bytes": sum(int(item.get("size") or 0) for item in artifacts),
    }
    listing = directory / "listing.md"
    if listing.is_file():
        entry["description_file"] = str(
            listing.relative_to(recipe_path.parents[2])
        ).replace("\\", "/")

    # 签名轨：**与插件/模板用同一组契约键名**，不另造一套。
    # 早先这里只找 `recipe.json.sig`（单文件签名轨），而 `creator-sign`
    # 实际产出的是整包清单签名 `package.manifest.creator.sig` ——
    # 结果 `recipe_signature_file` 恒为 None，签名在 catalog 里不可见（实测）。
    for key, filename in (
        ("package_manifest_file", "package.manifest.json"),
        ("creator_package_signature_file", "package.manifest.creator.sig"),
        ("creator_identity_file", "creator.identity"),
        # 兼容轨：单文件签名（旧版本工具可能产出），存在就一并记录
        ("creator_signature_file", "creator.sig"),
    ):
        candidate = directory / filename
        if candidate.is_file():
            entry[key] = str(
                candidate.relative_to(recipe_path.parents[2])
            ).replace("\\", "/")
    return entry


def _component_publisher(directory: Path) -> str:
    """组件发布者：优先读 ``creator.identity``，缺失则记 ``unknown``。"""
    import json

    identity = directory / "creator.identity"
    if identity.is_file():
        try:
            data = json.loads(identity.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "unknown"
        if isinstance(data, dict):
            username = str(data.get("username") or data.get("name") or "").strip()
            if username:
                return username
    return "unknown"

def _existing_sequence(registry: Path) -> int:
    """读取持久化 catalog.json 的单调序列号；缺失/损坏/非法时回落 0（P3-2）。"""
    path = registry / "catalog.json"
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            value = existing.get("sequence")
            if isinstance(value, int) and value > 0:
                return value
        except json.JSONDecodeError:
            pass
    return 0


def build_catalog(
    registry: Path,
    *,
    publisher_override: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    plugins_dir = registry / _PLUGIN_DIR
    if not plugins_dir.is_dir():
        raise ValueError(f"registry 缺少 {_PLUGIN_DIR}/ 目录: {plugins_dir}")

    entries: list[dict[str, Any]] = []
    publishers: list[str] = []
    seen_plugin_ids: set[str] = set()
    modern_plugin_dirs = {path.parent.resolve() for path in plugins_dir.glob("*/market.yaml")}
    plugin_manifests = sorted(plugins_dir.glob("*/market.yaml")) + sorted(
        path for path in plugins_dir.glob("*/plugin.yaml") if path.parent.resolve() not in modern_plugin_dirs
    )
    for manifest_path in plugin_manifests:
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

    # 组件 recipe（第三分支）。**空目录不报错**——向后兼容：没有 components/
    # 的旧 registry 仍能生成 catalog，只是该列表为空。
    component_entries: list[dict[str, Any]] = []
    components_dir = registry / _COMPONENTS_DIR
    if components_dir.is_dir():
        seen_component_ids: set[str] = set()
        for recipe_path in sorted(components_dir.glob("*/recipe.json")):
            entry = _entry_from_component_recipe(recipe_path)
            cid = str(entry["id"])
            if cid in seen_component_ids:
                raise ValueError(f"组件 ID 重复: {cid}")
            seen_component_ids.add(cid)
            component_entries.append(entry)
        component_entries.sort(key=lambda item: str(item["id"]))
    template_entries: list[dict[str, Any]] = []
    template_markets: dict[str, dict[str, Any]] = {}
    seen_template_ids: set[str] = set()
    templates_dir = registry / _TEMPLATES_DIR
    if templates_dir.is_dir():
        modern_template_dirs = {path.parent.resolve() for path in templates_dir.rglob("market.yaml")}
        template_sources = [(path, True) for path in sorted(templates_dir.rglob("market.yaml"))]
        template_sources.extend(
            (path, False)
            for path in sorted(templates_dir.glob("*/template.yaml"))
            if path.parent.resolve() not in modern_template_dirs
        )
        for template_yaml, modern in template_sources:
            entry, market = (
                _entry_from_template_market(template_yaml)
                if modern
                else _entry_from_template_yaml(template_yaml)
            )
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
    for manifest_path in plugin_manifests:
        manifest = _load_yaml(manifest_path)
        manifests[str(manifest.get("id", ""))] = manifest
    for manifest in manifests.values():
        _check_author(manifest, authors)
    for market in template_markets.values():
        _check_author(market, authors)

    for entry in entries:
        expected = str(manifests.get(str(entry.get("id")), {}).get("author_fingerprint", ""))
        _check_creator_rail(registry, entry, expected or None)
        # ★ 2026-09-30：把**创作者公钥指纹**写进条目。
        #   客户端多源聚合（`market_client.aggregate_catalogs`）的去重键是
        #   `(id, creator_fingerprint)`；条目缺这个字段就退化成 `(id, "")`
        #   ⇒ 同一个 id 由**不同创作者**发布时不会被标 `_conflict`，而会被当成同一条
        #   按 priority 静默择一（单源时无感，多源/联邦索引时才暴露）。
        #   取值来源＝清单的 `author_fingerprint`（`market.yaml`），它与客户端
        #   `identity.derive_fingerprint` **同一算法**：SHA-256(ed25519 原始 32 字节) 前 16 字节 hex。
        #   注：`_TOP_LEVEL_EXTRA` 里的 `author_fingerprint` 是**输入侧**键名且不入 catalog，
        #   写进条目的是**契约名** `creator_fingerprint`（与主仓多索引用例、客户端读取一致）。
        if expected:
            entry["creator_fingerprint"] = expected
        for key in (
            "description_file", "plugin_file", "package_manifest_file",
            "creator_package_signature_file", "maintainer_package_signature_file",
        ):
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
        expected = str(template_markets.get(str(entry.get("id")), {}).get("author_fingerprint", ""))
        _check_creator_rail(registry, entry, expected or None)
        # 与插件条目同理（客户端对 templates 用**同一套**去重键）：
        if expected:
            entry["creator_fingerprint"] = expected
        for key in (
            "template_file", "signature_file", "description_file", "creator_signature_file",
            "creator_identity_file", "package_manifest_file",
            "creator_package_signature_file", "maintainer_package_signature_file",
        ):
            rel = entry.get(key)
            if rel:
                resolved = _require_contained(registry, registry, str(rel), f"模板 {entry['id']} 的 {key}")
                if not resolved.is_file():
                    raise ValueError(f"模板 {entry['id']} 的 {key} 不存在: {rel}")

    entries.sort(key=lambda item: str(item["id"]))
    template_entries.sort(key=lambda item: str(item["id"]))
    publisher = publisher_override or (publishers[0] if publishers else "unknown")
    generated_at = datetime.now(timezone.utc)
    # P3-2：sequence 为持久单调计数器（落盘自增），不再由时间戳推导——同秒连续
    # 发布序号仍递增不相等；--check 模式显式传入磁盘既有序号以保持一致性比对。
    sequence_value = sequence if sequence is not None else _existing_sequence(registry) + 1
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        # G3（catalog 防重放）：单调序列号 + 发布时间戳（均被签名覆盖）。
        # 客户端拒绝序列号/时间旧于本地缓存的 catalog（decision:
        # catalog_stale_rejected）——吊销不可被旧版 catalog 重放隐藏。
        "sequence": sequence_value,
        "publisher": publisher,
        "trust_model": TRUST_MODEL,
        "official_publishers": list(OFFICIAL_PUBLISHERS),
        "trust_public_key_ref": TRUST_KEY_REF,
        "plugins": entries,
        "templates": template_entries,
        "components": component_entries,
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
        newline="\n",
    )
    return output


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
