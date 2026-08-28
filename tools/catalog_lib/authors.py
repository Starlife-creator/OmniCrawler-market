#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""作者记录加载、指纹校验、创作者轨检查、显示名规范。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .common import *
from .signing import *


_HANDLE_RE = re.compile(r"^[a-z0-9_-]{2,32}$")


def normalize_requested_handle(value: str) -> str:
    """Normalize a local requested username into the market ASCII namespace."""
    handle = value.strip().lower()
    if not _HANDLE_RE.fullmatch(handle):
        raise ValueError(f"期望市场用户名非法（仅小写 ASCII 字母/数字/_-，2-32 位）: {value!r}")
    return handle


def assign_market_handle(
    authors: dict[str, dict[str, Any]], fingerprint: str, requested_username: str
) -> str:
    """Return the stable existing handle or allocate base/-01/-02 deterministically."""
    for handle, record in authors.items():
        if str(record.get("_fingerprint") or record.get("fingerprint") or "") == fingerprint:
            return handle
    base = normalize_requested_handle(requested_username)
    if base not in authors:
        return base
    index = 1
    while f"{base}-{index:02d}" in authors:
        index += 1
    return f"{base}-{index:02d}"


def load_authors(registry: Path) -> dict[str, dict[str, Any]]:
    """读取 authors/ 目录：market_handle -> author 记录（含 pubkey 指纹）。

    B02-012：同 username 静默覆盖改为 fail-closed；并检查同一公钥指纹被
    多个 username 登记（防止冒名顶替放大空间）。
    """
    authors_dir = registry / _AUTHORS_DIR
    authors: dict[str, dict[str, Any]] = {}
    if not authors_dir.is_dir():
        return authors
    for yaml_file in sorted(authors_dir.glob("*.yaml")):
        record = _load_yaml(yaml_file)
        handle = str(record.get("market_handle") or record.get("username") or "")
        if not handle:
            raise ValueError(f"作者清单缺少 market_handle/username: {yaml_file}")
        normalize_requested_handle(handle)
        if yaml_file.stem != handle:
            raise ValueError(f"作者文件名必须等于 market_handle: {yaml_file.stem!r} != {handle!r}")
        if handle in authors:
            raise ValueError(
                f"重复 market_handle（禁止静默覆盖）: {handle}（{yaml_file} 与已有记录冲突）"
            )
        record["market_handle"] = handle
        record.setdefault("requested_username", str(record.get("username") or handle))
        pubkey_ref = record.get("pubkey_ref")
        fingerprint = record.get("fingerprint")
        if pubkey_ref:
            pem = _require_contained(
                registry, authors_dir, str(pubkey_ref), f"作者 {handle} 的 pubkey_ref"
            )
            if not pem.is_file():
                raise ValueError(f"作者 {handle} 的 pubkey_ref 不存在: {pubkey_ref}")
            actual = _raw_fingerprint(pem)
            if fingerprint and str(fingerprint) != actual:
                raise ValueError(f"作者 {handle} 声明指纹 {fingerprint} 与公钥实际指纹 {actual} 不一致")
            record["_fingerprint"] = actual
            record["_pubkey_path"] = pem
        elif fingerprint:
            record["_fingerprint"] = str(fingerprint)
        authors[handle] = record
    # 同公钥多 username 检查（B02-012）：指纹是绝对唯一标识
    by_fingerprint: dict[str, str] = {}
    for handle, record in sorted(authors.items()):
        fp = str(record.get("_fingerprint", ""))
        if not fp:
            continue
        if fp in by_fingerprint:
            raise ValueError(
                f"同一公钥指纹被多个 username 登记（B02-012）: "
                f"{by_fingerprint[fp]} 与 {handle} 共享指纹 {fp}"
            )
        by_fingerprint[fp] = handle
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
        if found.get("market_handle") != publisher:
            raise ValueError(
                f"插件 {manifest.get('id')} 的 publisher '{publisher}' 与作者 "
                f"'{found.get('market_handle')}' 不一致（author_fingerprint 属于后者）"
            )
        return
    if record.get("_fingerprint") != fingerprint:
        raise ValueError(
            f"插件 {manifest.get('id')} 的 author_fingerprint {fingerprint} "
            f"与作者 {record.get('market_handle')} 实际指纹不一致"
        )

def _check_creator_rail(
    registry: Path,
    entry: dict[str, Any],
    expected_fingerprint: str | None = None,
) -> None:
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
    if expected_fingerprint and derived != expected_fingerprint:
        raise ValueError(
            f"插件 {entry.get('id', '?')} 的 creator.identity 指纹 {derived} "
            f"与作者目录/清单指纹 {expected_fingerprint} 不一致"
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


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
