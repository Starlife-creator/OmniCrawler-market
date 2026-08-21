#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# 本工具代码以 MIT License 授权（见 tools/LICENSE）。
"""从 ``plugins/*/plugin.yaml`` 聚合生成 ``catalog.json``（git-as-registry）。

目录结构即索引：每个插件一个 YAML 清单（唯一元数据源），``catalog.json`` 是
由本工具生成的**派生物**，随仓库提交，应用端（``market_client`` / GUI 市场面板 /
``tools/market.py``）继续只读 ``catalog.json``，**零改动**。

本工具位于本仓库 ``tools/`` 下，**随生态目录自包含**：只依赖 PyYAML 与
cryptography（ed25519 验签内联实现，不 import 应用包）。把整个生态目录复制到
独立仓库后，本工具原样可用——拆库 = 复制 + 改应用 ``catalog_url``。

用法：
  python tools/generate_catalog.py [--publisher NAME]
      扫描 ``plugins/*/plugin.yaml``，重写 ``catalog.json``。
  python tools/generate_catalog.py --check
      只校验不写盘（CI 门禁）。校验项：
        1. catalog.json 与 YAML 源完全一致（``generated_at`` 除外）；
        2. 每个 plugin.yaml 必填字段齐全、id 合法、引用文件存在；
        3. ``author_fingerprint`` 是**创作者公钥指纹**（与 templates/README.md
           规范一致），须在 ``authors/`` 有记录且与 ``publisher`` 同名作者一致；
        4. 签名文件可用信任根公钥验签（``--trust`` > ``keys/``；
           cryptography 不可用时跳过并警告）。
  校验失败退出码 1，否则 0。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# 本工具所在目录 = tools/，其父级即生态目录根（自包含约定）
REGISTRY_DIR = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = 1
# B02-020：双轨信任模型——维护者冷密钥背书（signature_file 对信任根）+
# 创作者热密钥签名（creator.sig 对 creator.identity 公钥），两条轨独立验签。
TRUST_MODEL = "dual-rail-ed25519"
TRUST_KEY_REF = "keys/plugin_trust.pub.pem"
# 信任根只认 keys/：拆库后主仓库不再是兄弟目录，「主仓库 configs/ 回退」
# 的相对路径会解析到工作区外（P3-3），此前只是被 keys/ 存在而掩盖。
_KEYS_FALLBACK = ("keys/plugin_trust.pub.pem",)

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
    "creator_signature_file",
    "creator_identity_file",
    # Phase 1 第 2 条（B1 schema 扩展）：执行模式与网络域白名单入 catalog
    "execution_mode",
    "domains",
    # 注：B1 方案字段名 files（files:read 路径白名单）与本仓既有的 files
    # （scan_plugin 扫描允许列表，生产已用）同名冲突——第 82 轮落地时消歧为
    # input_files（方案 B1/术语表已同步更名）；files 保留为扫描期元数据
    # （_TOP_LEVEL_EXTRA，不进 catalog）。
    "input_files",
    "release_channel",
    "dependencies",
    "review_depth",
    "gates_evidence",
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
    # 门 2（Phase 1）：license 必填——删除隐式回退后显式声明是唯一合法路径
    "license",
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
# 允许出现在 plugin.yaml 但**不进入 catalog.json 条目**的键：
# author_fingerprint（跨轨校验用）、files（scan_plugin 允许列表，纯扫描期元数据）。
# 注：B1 的 files:read 路径白名单字段落地时更名为 input_files（第 82 轮消歧），
# 避免与本键冲突。
_TOP_LEVEL_EXTRA = {"author_fingerprint", "files"}

# 门 2（许可合规，Phase 1）：插件代码许可 SPDX 白名单（方案 A2）。
# 拒绝清单（命中即 CI 红）：GPL-2.0-only / GPL-2.0-or-later / CC-BY-NC-* /
# LicenseRef-* / 自定义标识——强 copyleft（GPL-2.0 系）在整体分发场景反向
# 传染宿主；NC 条款与开源生态冲突；非 SPDX 标识不可机器校验。
# 模板不适用本白名单（license 为数据/服务条款自由文本，A2 模板例外）。
LICENSE_ALLOWLIST = {
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "Unlicense",
}


def _raw_fingerprint(pem_path: Path) -> str:
    """作者公钥指纹 = SHA-256(ed25519 公钥原始 32 字节) 前 16 字节 hex。

    **与运行时（omnicrawler.plugins.identity.derive_fingerprint）完全同源**：
    从 PEM 解析出密钥对象后取 ``public_bytes_raw()`` —— 输入是密钥的规范
    字节表示，与文本编码、行尾（CRLF/LF）、base64 折行完全无关，跨平台
    跨语言可复现。

    历史上这里是「SHA-256(PEM 文本字节, CRLF 归一化)」（_pem_fingerprint），
    已于 2026-08 统一中废弃：需要靠行尾归一化才能稳定的哈希输入本身就是
    设计缺陷；且双轨造成两套互不认证的信任命名空间（运行时只信客户端轨、
    本 CI 只信 PEM 轨，两边永不互查）。
    """
    key = _load_public_key(str(pem_path))
    return hashlib.sha256(key.public_bytes_raw()).hexdigest()[:32]


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
    """ed25519 验签（与应用端 omnicrawler.plugins.signing 语义一致，fail-closed）。"""
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


def _require_contained(registry: Path, base: Path, rel: str, label: str) -> Path:
    """B02-014：文件引用解析后必须仍在 registry 内（允许 ``..`` 但不越界）。

    现有生产数据依赖 ``authors/../keys/x.pem`` 这种跨目录写法，所以不做
    字面禁止 ``..``，只做最终落点的包含性判定。
    """
    resolved = (base / rel).resolve()
    if not resolved.is_relative_to(registry.resolve()):
        raise ValueError(f"{label} 解析后逃出 registry 根: {resolved}")
    return resolved


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


def load_authors(registry: Path) -> dict[str, dict[str, Any]]:
    """读取 authors/ 目录：username -> author 记录（含 pubkey 指纹）。

    B02-012：同 username 静默覆盖改为 fail-closed；并检查同一公钥指纹被
    多个 username 登记（防止冒名顶替放大空间）。
    """
    authors_dir = registry / _AUTHORS_DIR
    authors: dict[str, dict[str, Any]] = {}
    if not authors_dir.is_dir():
        return authors
    for yaml_file in sorted(authors_dir.glob("*.yaml")):
        record = _load_yaml(yaml_file)
        username = str(record.get("username", ""))
        if not username:
            raise ValueError(f"作者清单缺少 username: {yaml_file}")
        if username in authors:
            raise ValueError(
                f"重复 username（禁止静默覆盖，B02-012）: {username}（{yaml_file} 与已有记录冲突）"
            )
        pubkey_ref = record.get("pubkey_ref")
        fingerprint = record.get("fingerprint")
        if pubkey_ref:
            pem = _require_contained(
                registry, authors_dir, str(pubkey_ref), f"作者 {username} 的 pubkey_ref"
            )
            if not pem.is_file():
                raise ValueError(f"作者 {username} 的 pubkey_ref 不存在: {pubkey_ref}")
            actual = _raw_fingerprint(pem)
            if fingerprint and str(fingerprint) != actual:
                raise ValueError(f"作者 {username} 声明指纹 {fingerprint} 与公钥实际指纹 {actual} 不一致")
            record["_fingerprint"] = actual
            record["_pubkey_path"] = pem
        elif fingerprint:
            record["_fingerprint"] = str(fingerprint)
        authors[username] = record
    # 同公钥多 username 检查（B02-012）：指纹是绝对唯一标识
    by_fingerprint: dict[str, str] = {}
    for username, record in sorted(authors.items()):
        fp = str(record.get("_fingerprint", ""))
        if not fp:
            continue
        if fp in by_fingerprint:
            raise ValueError(
                f"同一公钥指纹被多个 username 登记（B02-012）: "
                f"{by_fingerprint[fp]} 与 {username} 共享指纹 {fp}"
            )
        by_fingerprint[fp] = username
    return authors


def _check_author(manifest: dict[str, Any], authors: dict[str, dict[str, Any]]) -> None:
    fingerprint = str(manifest.get("author_fingerprint", ""))
    publisher = str(manifest.get("publisher", ""))
    if not fingerprint:
        raise ValueError(f"插件 {manifest.get('id', '?')} 缺少 author_fingerprint")
    record = authors.get(publisher)
    if record is None:
        # B02-011：publisher 名未在 authors/ 登记时，按指纹找到唯一作者后
        # 必须要求 publisher 与作者 username 严格一致（fail-closed），
        # 杜绝「填不存在的 publisher 名 + 任意登记指纹」绕过严格比对。
        found = next(
            (author for author in authors.values() if author.get("_fingerprint") == fingerprint),
            None,
        )
        if found is None:
            raise ValueError(
                f"插件 {manifest.get('id')} 的 author_fingerprint {fingerprint} 在 authors/ 无对应记录"
            )
        if found.get("username") != publisher:
            raise ValueError(
                f"插件 {manifest.get('id')} 的 publisher '{publisher}' 与作者 "
                f"'{found.get('username')}' 不一致（author_fingerprint 属于后者，B02-011）"
            )
        return
    if record.get("_fingerprint") != fingerprint:
        raise ValueError(
            f"插件 {manifest.get('id')} 的 author_fingerprint {fingerprint} "
            f"与作者 {record.get('username')} 实际指纹不一致"
        )


def _check_creator_rail(registry: Path, entry: dict[str, Any]) -> None:
    """创作者轨完整性校验（方案 B：与维护者轨独立，不做跨轨相等）。

    ``author_fingerprint`` 是**创作者公钥指纹**（B02-013 对齐 templates/README.md
    规范，由 _check_author 校验）；``creator.identity`` 属于创作者轨本身——
    维护者用信任根冷密钥背书（plugin.py.sig / template.yaml.sig）是独立身份。
    此处只做创作者轨自身的完整性：
    1. ``creator.identity`` 文件存在且为合法 JSON；
    2. 公钥现场推导指纹与 identity 自称指纹一致（防身份冒充/篡改）。
    ``creator.sig`` 对 ``creator.identity`` 公钥的实际验签在 _verify_signatures。
    """
    if not entry.get("creator_identity_file"):
        return  # 无创作者轨（纯维护者签名）时无需检查
    ident_path = _require_contained(
        registry, registry, str(entry["creator_identity_file"]),
        f"{entry.get('id', '?')} 的 creator_identity_file",
    )
    if not ident_path.is_file():
        raise ValueError(f"插件 {entry.get('id', '?')} 声明了 creator_identity_file 但文件不存在")
    try:
        creator = json.loads(ident_path.read_text(encoding="utf-8"))
        raw = base64.b64decode(str(creator["public_key"]), validate=True)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"插件 {entry.get('id', '?')} 的 creator.identity 非法: {exc}") from exc
    derived = hashlib.sha256(raw).hexdigest()[:32]
    declared = str(creator.get("key_fingerprint", "")).strip().lower()
    if not declared:
        # B02-022：key_fingerprint 列为 .identity 必填，缺失不得静默跳过一致性校验。
        raise ValueError(
            f"插件 {entry.get('id', '?')} 的 creator.identity 缺少 key_fingerprint（必填）"
        )
    if declared != derived:
        raise ValueError(
            f"插件 {entry.get('id', '?')} 的 creator.identity 自称指纹 {declared} "
            f"与公钥实际指纹 {derived} 不一致（疑似身份冒充或文件被篡改）"
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
        groups.setdefault(base.casefold(), []).append(suffix or "")
    for base, suffixes in sorted(groups.items()):
        # B02-021：分组键 casefold——Foo 与 foo 视为同名，防大小写变体绕过后缀约束
        plain = [item for item in suffixes if item == ""]
        numbered = sorted(item for item in suffixes if item != "")
        if len(plain) > 1:
            raise ValueError(
                f"显示名 {base!r} 有 {len(plain)} 个无后缀用户（先注册者保持原名，后续须用后缀 -01、-02…）"
            )
        if numbered and numbered != [f"{index:02d}" for index in range(1, len(numbered) + 1)]:
            raise ValueError(f"显示名 {base!r} 的后缀不连续（应为 -01、-02…，实际 {numbered}）")


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


def _resolve_trust(registry: Path, trust_source: str | None) -> str:
    """信任根查找链：--trust > keys/plugin_trust.pub.pem（拆库后只认 keys/，P3-3）。"""
    if trust_source:
        return trust_source
    candidate = registry / _KEYS_FALLBACK[0]
    return str(candidate) if candidate.is_file() else ""


def _verify_signatures(
    registry: Path,
    catalog: dict[str, Any],
    trust_source: str | None,
) -> list[str]:
    """验签插件与模板（**fail-closed**：缺依赖/缺信任根即失败，绝不跳过）。

    修复前缺 cryptography 或缺信任根时只警告并返回 0（审查报告 S7）——
    等于签名门禁在关键环境下"看起来开着、实际是空的"。

    返回 V1 警告列表：存量插件大概率无 creator 签名，V1 阶段仅警告不失败；
    V2 将升级为强制（P3-1）。
    """
    warnings: list[str] = []
    try:
        import cryptography  # noqa: F401
    except ImportError as exc:
        raise ValueError(
            "cryptography 不可用，无法进行签名校验。"
            "为保证市场签名门禁不失效，CI 必须安装 cryptography。"
        ) from exc
    trust = _resolve_trust(registry, trust_source)
    if not trust:
        raise ValueError(
            f"未找到信任根公钥（查找链: {', '.join(_KEYS_FALLBACK)}），"
            "无法校验维护者签名，CI 拒绝通过。"
        )
    for entry in catalog.get("plugins", []):
        plugin_path = registry / str(entry["plugin_file"])
        sig = entry.get("signature_file")
        sig_path = registry / str(sig) if sig else None
        has_maintainer_sig = sig_path is not None and sig_path.is_file()
        # 多重信任模型（方案 B）：两条轨各自独立验签、互不替代——
        # 维护者轨验 plugin.py.sig 对 trust 根；创作者轨验 creator.sig 对
        # creator.identity 公钥。声明哪条就验哪条；两者可同时存在（创作者
        # 签名 + 维护者背书），if/elif 互斥是错误语义。
        if has_maintainer_sig:
            ok = _verify_signature(plugin_path.read_bytes(), sig_path.read_bytes(), trust)
            if not ok:
                raise ValueError(f"插件 {entry['id']} 维护者签名校验失败（fail-closed）")
        if entry.get("creator_signature_file") and entry.get("creator_identity_file"):
            # 创作者轨独立验签：creator.sig 对 creator.identity 公钥
            c_sig = registry / str(entry["creator_signature_file"])
            c_id = registry / str(entry["creator_identity_file"])
            if not c_sig.is_file():
                raise ValueError(
                    f"插件 {entry['id']} 声明了 creator_signature_file 但文件不存在"
                )
            creator = json.loads(c_id.read_text(encoding="utf-8"))
            raw = base64.b64decode(str(creator["public_key"]), validate=True)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            public_key = Ed25519PublicKey.from_public_bytes(raw)
            try:
                public_key.verify(c_sig.read_bytes(), plugin_path.read_bytes())
            except Exception:  # noqa: BLE001 - 验签失败即视为不可信
                raise ValueError(f"插件 {entry['id']} 创作者签名校验失败（fail-closed）")
        if not has_maintainer_sig and not (
            entry.get("creator_signature_file") and entry.get("creator_identity_file")
        ):
            # build_catalog 已要求至少一条签名轨，此兜底不应触发
            raise ValueError(f"插件 {entry['id']} 缺少可验证的签名文件")
        # V1：创作者签名缺失 → 仅警告（V2 将强制要求补齐）
        if not (entry.get("creator_signature_file") and entry.get("creator_identity_file")):
            warnings.append(
                f"插件 {entry['id']} 缺少创作者签名（V1 警告；V2 将要求必须补签）"
            )
    for entry in catalog.get("templates", []):
        template_path = registry / str(entry["template_file"])
        sig_path = registry / str(entry["signature_file"])
        ok = _verify_signature(template_path.read_bytes(), sig_path.read_bytes(), trust)
        if not ok:
            raise ValueError(f"模板 {entry['id']} 签名校验失败（fail-closed）")
        # B02-002：模板创作者轨独立验签——creator.sig 对 creator.identity 公钥
        if entry.get("creator_signature_file") and entry.get("creator_identity_file"):
            c_sig = registry / str(entry["creator_signature_file"])
            c_id = registry / str(entry["creator_identity_file"])
            if not c_sig.is_file():
                raise ValueError(
                    f"模板 {entry['id']} 声明了 creator_signature_file 但文件不存在"
                )
            creator = json.loads(c_id.read_text(encoding="utf-8"))
            raw = base64.b64decode(str(creator["public_key"]), validate=True)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            public_key = Ed25519PublicKey.from_public_bytes(raw)
            try:
                public_key.verify(c_sig.read_bytes(), template_path.read_bytes())
            except Exception:  # noqa: BLE001 - 验签失败即视为不可信
                raise ValueError(f"模板 {entry['id']} 创作者签名校验失败（fail-closed）")
    return warnings


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


def _check_consistency(registry: Path, catalog: dict[str, Any]) -> None:
    existing_path = registry / "catalog.json"
    if not existing_path.is_file():
        raise ValueError(f"catalog.json 缺失（先运行生成器）: {existing_path}")
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    # generated_at 是时间戳；publisher 是生成参数（--publisher 覆盖时顶层不同，
    # 与源无关，排除以免 --check 误失败，P3-4）
    parametric = {"generated_at", "publisher"}
    expected = {key: value for key, value in catalog.items() if key not in parametric}
    actual = {key: value for key, value in existing.items() if key not in parametric}
    if expected != actual:
        raise ValueError(
            "catalog.json 与 plugin.yaml 源不一致（请运行 tools/generate_catalog.py 重新生成）"
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
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
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


def check(
    registry: Path,
    *,
    trust_source: str | None = None,
    prev_catalog: str | None = None,
) -> int:
    """CI 门禁：校验 YAML 源合法、与 catalog.json 一致、签名有效（fail-closed）。

    V1：缺失创作者签名的插件打印警告（不失败）；V2 将升级为强制（P3-1）。
    门 4（Phase 1）：license/execution_mode 变更必须伴随版本递增——基线取
    --prev-catalog 或 git 历史中的上一版 catalog.json。
    """
    try:
        catalog = build_catalog(registry)
        _check_consistency(registry, catalog)
        gate4_warnings = _check_version_rules(
            registry, catalog, _load_prev_catalog(registry, prev_catalog)
        )
        warnings = _verify_signatures(registry, catalog, trust_source)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL registry: {exc}")
        return 1
    for warning in gate4_warnings:
        print(f"  ! {warning}")
    for warning in warnings:
        print(f"  ! {warning}")
    plugins = len(catalog["plugins"])
    templates = len(catalog["templates"])
    print(f"OK registry: {plugins} 个插件 + {templates} 个模板清单一致，签名校验完成")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_catalog",
        description="从 plugins/*/plugin.yaml 与 templates/*/template.yaml 聚合生成或校验 catalog.json",
    )
    parser.add_argument("--registry", default=str(REGISTRY_DIR), help="registry 目录（默认本工具所在生态根）")
    parser.add_argument("--publisher", default=None, help="catalog 顶层 publisher（默认取首个插件发布者）")
    parser.add_argument(
        "--trust",
        default=None,
        help="信任根公钥 PEM 路径（默认 keys/plugin_trust.pub.pem）",
    )
    parser.add_argument("--check", action="store_true", help="只校验不写盘（CI 门禁）")
    parser.add_argument(
        "--prev-catalog",
        default=None,
        help="门 4 基线：上一版 catalog.json 路径（默认取 git 历史 HEAD^ 版本）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = Path(args.registry)
    if not registry.is_dir():
        print(f"FAIL registry 目录不存在: {registry}")
        return 1
    if args.check:
        return check(registry, trust_source=args.trust, prev_catalog=args.prev_catalog)
    try:
        output = generate(registry, publisher_override=args.publisher)
    except (ValueError, OSError) as exc:
        print(f"FAIL 生成 catalog.json: {exc}")
        return 1
    print(f"OK 已生成: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
