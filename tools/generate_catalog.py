#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# 本工具代码以 MIT License 授权（见 tools/LICENSE）。
"""从 ``registry/plugins/*/plugin.yaml`` 聚合生成 ``catalog.json``（git-as-registry）。

目录结构即索引：每个插件一个 YAML 清单（唯一元数据源），``catalog.json`` 是
由本工具生成的**派生物**，随仓库提交，应用端（``market_client`` / GUI 市场面板 /
``tools/market.py``）继续只读 ``catalog.json``，**零改动**。

本工具位于 ``registry/tools/`` 下，**随生态目录自包含**：只依赖 PyYAML 与
cryptography（ed25519 验签内联实现，不 import 应用包）。把整个 ``registry/``
子树复制到独立仓库后，本工具原样可用——拆库 = 复制 + 改应用 ``catalog_url``。

用法：
  python registry/tools/generate_catalog.py [--registry registry] [--publisher NAME]
      扫描 ``registry/plugins/*/plugin.yaml``，重写 ``registry/catalog.json``。
  python registry/tools/generate_catalog.py --check [--registry registry]
      只校验不写盘（CI 门禁）。校验项：
        1. catalog.json 与 YAML 源完全一致（``generated_at`` 除外）；
        2. 每个 plugin.yaml 必填字段齐全、id 合法、引用文件存在；
        3. ``author_fingerprint`` 在 ``authors/`` 有记录，且与 ``pubkey_ref``
           指向公钥的实际指纹一致；
        4. 签名文件可用信任根公钥验签（``--trust`` > ``registry/keys/`` >
           主仓库 ``configs/`` 回退；cryptography 不可用时跳过并警告）。
  校验失败退出码 1，否则 0。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# 本工具所在目录 = registry/tools/，其父级即生态目录根（自包含约定）
REGISTRY_DIR = Path(__file__).resolve().parents[1]
# 主仓库根（仅用于回退查找信任根公钥；拆库独立后此路径失效，走 keys/ 或 --trust）
REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = 1
TRUST_MODEL = "single-root-ed25519"
TRUST_KEY_REF = "keys/plugin_trust.pub.pem"
_KEYS_FALLBACK = ("keys/plugin_trust.pub.pem", "../../configs/plugin_trust.pub.pem")

_PLUGIN_DIR = "plugins"
_AUTHORS_DIR = "authors"
_TEMPLATES_DIR = "templates"
_ENTRY_KEYS = [
    "id",
    "name",
    "version",
    "publisher",
    "category",
    "summary",
    "description_file",
    "plugin_file",
    "signature_file",
    "signature_algorithm",
    "permissions",
    "compatible_core",
    "license",
    "tags",
    "updated_at",
    "homepage",
]
_REQUIRED_KEYS = [
    "id",
    "name",
    "version",
    "publisher",
    "category",
    "summary",
    "description_file",
    "plugin_file",
    "signature_file",
    "signature_algorithm",
    "permissions",
    "compatible_core",
]
_TEMPLATE_ENTRY_KEYS = [
    "id",
    "name",
    "version",
    "publisher",
    "category",
    "summary",
    "description_file",
    "template_file",
    "signature_file",
    "signature_algorithm",
    "compatible_core",
    "license",
    "tags",
    "updated_at",
    "homepage",
]
_ID_RE_PREFIX = "^[a-z][a-z0-9_-]{1,63}$"
# 模板 ID 允许层级命名（如 generic/single-page），与内置模板目录一致
_TEMPLATE_ID_RE_PREFIX = "^[a-z][a-z0-9_-]*(/[a-z0-9_-]+)*$"
_TOP_LEVEL_EXTRA = {"author_fingerprint"}


def _pem_fingerprint(pem_path: Path) -> str:
    """作者公钥指纹：SHA-256(PEM 文件字节) 前 16 字节 hex（生态唯一标识）。"""
    return hashlib.sha256(pem_path.read_bytes()).hexdigest()[:32]


def _load_public_key(trust_source: str) -> Any:
    """从 PEM 路径或 PEM 文本加载 ed25519 公钥（自包含实现，不依赖应用包）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    candidate = trust_source.strip()
    maybe = Path(candidate)
    if maybe.is_file():
        candidate = maybe.read_text(encoding="utf-8").strip()
    key = serialization.load_pem_public_key(candidate.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("信任根公钥必须是 ed25519 公钥")
    return key


def _verify_signature(data: bytes, signature: bytes, trust_source: str) -> bool:
    """ed25519 验签（与应用端 omnicrawl.plugins.signing 语义一致，fail-closed）。"""
    try:
        _load_public_key(trust_source).verify(signature, data)
    except Exception:  # noqa: BLE001 - 验签失败即视为不可信
        return False
    return True


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"清单必须是映射（mapping）: {path}")
    return data


def _entry_from_yaml(manifest: dict[str, Any], source: Path) -> dict[str, Any]:
    """把 plugin.yaml 转换为 catalog.json 条目（只透传 schema 字段）。"""
    missing = [key for key in _REQUIRED_KEYS if key not in manifest]
    if missing:
        raise ValueError(f"清单缺少必填字段 {missing}: {source}")
    unknown = set(manifest) - set(_ENTRY_KEYS) - _TOP_LEVEL_EXTRA
    if unknown:
        raise ValueError(f"清单包含未知字段 {sorted(unknown)}: {source}")
    entry = {key: manifest[key] for key in _ENTRY_KEYS if key in manifest}
    if not re.match(_ID_RE_PREFIX, str(entry["id"])):
        raise ValueError(f"非法插件 ID（须匹配 {_ID_RE_PREFIX}）: {entry['id']}")
    return entry


def _entry_from_template_yaml(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """把 registry/templates/<id>/template.yaml 转换为 catalog 模板条目。

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
        "license": str(block.get("license") or "OmniCrawler-MIT"),
        "tags": list(block.get("tags") or []),
        "updated_at": str(block.get("verified_at") or ""),
    }
    if listing.is_file():
        entry["description_file"] = f"{_TEMPLATES_DIR}/{template_dir.name}/listing.md"
    for key in ("homepage",):
        if block.get(key):
            entry[key] = str(block[key])
    return entry, market


def load_authors(registry: Path) -> dict[str, dict[str, Any]]:
    """读取 authors/ 目录：username -> author 记录（含 pubkey 指纹）。"""
    authors_dir = registry / _AUTHORS_DIR
    authors: dict[str, dict[str, Any]] = {}
    if not authors_dir.is_dir():
        return authors
    for yaml_file in sorted(authors_dir.glob("*.yaml")):
        record = _load_yaml(yaml_file)
        username = str(record.get("username", ""))
        if not username:
            raise ValueError(f"作者清单缺少 username: {yaml_file}")
        pubkey_ref = record.get("pubkey_ref")
        fingerprint = record.get("fingerprint")
        if pubkey_ref:
            pem = (authors_dir / str(pubkey_ref)).resolve()
            if not pem.is_file():
                raise ValueError(f"作者 {username} 的 pubkey_ref 不存在: {pubkey_ref}")
            actual = _pem_fingerprint(pem)
            if fingerprint and str(fingerprint) != actual:
                raise ValueError(f"作者 {username} 声明指纹 {fingerprint} 与公钥实际指纹 {actual} 不一致")
            record["_fingerprint"] = actual
            record["_pubkey_path"] = pem
        elif fingerprint:
            record["_fingerprint"] = str(fingerprint)
        authors[username] = record
    return authors


def _check_author(manifest: dict[str, Any], authors: dict[str, dict[str, Any]]) -> None:
    fingerprint = str(manifest.get("author_fingerprint", ""))
    if not fingerprint:
        raise ValueError(f"插件 {manifest.get('id', '?')} 缺少 author_fingerprint")
    record = authors.get(str(manifest.get("publisher", "")))
    if record is None:
        found = next(
            (author for author in authors.values() if author.get("_fingerprint") == fingerprint),
            None,
        )
        if found is None:
            raise ValueError(
                f"插件 {manifest.get('id')} 的 author_fingerprint {fingerprint} 在 authors/ 无对应记录"
            )
        return
    if record.get("_fingerprint") != fingerprint:
        raise ValueError(
            f"插件 {manifest.get('id')} 的 author_fingerprint {fingerprint} "
            f"与作者 {record.get('username')} 实际指纹不一致"
        )


def _check_display_name_suffixes(authors: dict[str, dict[str, Any]]) -> None:
    """显示名冲突校验（对齐 Helios 规则）：同名用户必须带连续 -01、-02… 后缀。

    git-as-registry 模式下 username 天然唯一（文件名 = username），display_name
    可重复；先注册者保留原名，后续同名用户显示名 = {原名}-{N+1:02d}。
    """
    groups: dict[str, list[str]] = {}
    for record in authors.values():
        display_name = str(record.get("display_name", record.get("username", "")))
        base = display_name
        suffix: str | None = None
        head, _, tail = display_name.rpartition("-")
        if head and tail.isdigit():
            base, suffix = head, tail
        groups.setdefault(base, []).append(suffix or "")
    for base, suffixes in sorted(groups.items()):
        plain = [item for item in suffixes if item == ""]
        numbered = sorted(item for item in suffixes if item != "")
        if len(plain) > 1:
            raise ValueError(
                f"显示名 {base!r} 有 {len(plain)} 个无后缀用户（先注册者保持原名，后续须用后缀 -01、-02…）"
            )
        if numbered and numbered != [f"{index:02d}" for index in range(1, len(numbered) + 1)]:
            raise ValueError(f"显示名 {base!r} 的后缀不连续（应为 -01、-02…，实际 {numbered}）")


def build_catalog(registry: Path, *, publisher_override: str | None = None) -> dict[str, Any]:
    plugins_dir = registry / _PLUGIN_DIR
    if not plugins_dir.is_dir():
        raise ValueError(f"registry 缺少 {_PLUGIN_DIR}/ 目录: {plugins_dir}")

    entries: list[dict[str, Any]] = []
    publishers: list[str] = []
    for manifest_path in sorted(plugins_dir.glob("*/plugin.yaml")):
        manifest = _load_yaml(manifest_path)
        entry = _entry_from_yaml(manifest, manifest_path)
        entries.append(entry)
        publisher = str(entry.get("publisher", ""))
        if publisher and publisher not in publishers:
            publishers.append(publisher)

    template_entries: list[dict[str, Any]] = []
    template_markets: dict[str, dict[str, Any]] = {}
    templates_dir = registry / _TEMPLATES_DIR
    if templates_dir.is_dir():
        for template_yaml in sorted(templates_dir.glob("*/template.yaml")):
            entry, market = _entry_from_template_yaml(template_yaml)
            template_entries.append(entry)
            template_markets[str(entry["id"])] = market
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
        for key in ("description_file", "plugin_file", "signature_file"):
            rel = entry.get(key)
            if rel and not (registry / str(rel)).is_file():
                raise ValueError(f"插件 {entry['id']} 的 {key} 不存在: {rel}")
    for entry in template_entries:
        for key in ("template_file", "signature_file", "description_file"):
            rel = entry.get(key)
            if rel and not (registry / str(rel)).is_file():
                raise ValueError(f"模板 {entry['id']} 的 {key} 不存在: {rel}")

    entries.sort(key=lambda item: str(item["id"]))
    template_entries.sort(key=lambda item: str(item["id"]))
    publisher = publisher_override or (publishers[0] if publishers else "unknown")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher": publisher,
        "trust_model": TRUST_MODEL,
        "trust_public_key_ref": TRUST_KEY_REF,
        "plugins": entries,
        "templates": template_entries,
    }


def _resolve_trust(registry: Path, trust_source: str | None) -> str:
    """信任根查找链：--trust > registry/keys/ > 主仓库 configs/（回退）。"""
    if trust_source:
        return trust_source
    candidates = [
        registry / _KEYS_FALLBACK[0],
        Path(__file__).resolve().parents[2] / _KEYS_FALLBACK[1],
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def _verify_signatures(
    registry: Path,
    catalog: dict[str, Any],
    trust_source: str | None,
) -> list[str]:
    """验签插件与模板；cryptography 不可用或信任根缺失时降级为警告。"""
    warnings: list[str] = []
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return ["cryptography 不可用，跳过签名校验（仅一致性校验）"]
    trust = _resolve_trust(registry, trust_source)
    if not trust:
        return [f"未找到信任根公钥（查找链: {', '.join(_KEYS_FALLBACK)}），跳过签名校验"]
    for entry in catalog.get("plugins", []):
        plugin_path = registry / str(entry["plugin_file"])
        sig_path = registry / str(entry["signature_file"])
        ok = _verify_signature(plugin_path.read_bytes(), sig_path.read_bytes(), trust)
        if not ok:
            raise ValueError(f"插件 {entry['id']} 签名校验失败（fail-closed）")
    for entry in catalog.get("templates", []):
        template_path = registry / str(entry["template_file"])
        sig_path = registry / str(entry["signature_file"])
        ok = _verify_signature(template_path.read_bytes(), sig_path.read_bytes(), trust)
        if not ok:
            raise ValueError(f"模板 {entry['id']} 签名校验失败（fail-closed）")
    return warnings


def generate(registry: Path, *, publisher_override: str | None = None) -> Path:
    catalog = build_catalog(registry, publisher_override=publisher_override)
    output = registry / "catalog.json"
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def _check_consistency(registry: Path, catalog: dict[str, Any]) -> None:
    existing_path = registry / "catalog.json"
    if not existing_path.is_file():
        raise ValueError(f"catalog.json 缺失（先运行生成器）: {existing_path}")
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    expected = {key: value for key, value in catalog.items() if key != "generated_at"}
    actual = {key: value for key, value in existing.items() if key != "generated_at"}
    if expected != actual:
        raise ValueError(
            "catalog.json 与 plugin.yaml 源不一致（请运行 registry/tools/generate_catalog.py 重新生成）"
        )


def check(registry: Path, *, trust_source: str | None = None) -> int:
    """CI 门禁：校验 YAML 源合法、与 catalog.json 一致、签名有效。"""
    try:
        catalog = build_catalog(registry)
        _check_consistency(registry, catalog)
        warnings = _verify_signatures(registry, catalog, trust_source)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL registry: {exc}")
        return 1
    for warning in warnings:
        print(f"WARN {warning}")
    plugins = len(catalog["plugins"])
    templates = len(catalog["templates"])
    print(
        f"OK registry: {plugins} 个插件 + {templates} 个模板清单一致，"
        f"签名校验{'完成' if not warnings else '跳过'}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_catalog",
        description="从 registry/plugins/*/plugin.yaml 与 registry/templates/*/template.yaml 聚合生成或校验 catalog.json",
    )
    parser.add_argument("--registry", default=str(REGISTRY_DIR), help="registry 目录（默认本工具所在生态根）")
    parser.add_argument("--publisher", default=None, help="catalog 顶层 publisher（默认取首个插件发布者）")
    parser.add_argument(
        "--trust",
        default=None,
        help="信任根公钥 PEM 路径（默认查找链: registry/keys/ → 主仓库 configs/）",
    )
    parser.add_argument("--check", action="store_true", help="只校验不写盘（CI 门禁）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = Path(args.registry)
    if not registry.is_dir():
        print(f"FAIL registry 目录不存在: {registry}")
        return 1
    if args.check:
        return check(registry, trust_source=args.trust)
    try:
        output = generate(registry, publisher_override=args.publisher)
    except (ValueError, OSError) as exc:
        print(f"FAIL 生成 catalog.json: {exc}")
        return 1
    print(f"OK 已生成: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
