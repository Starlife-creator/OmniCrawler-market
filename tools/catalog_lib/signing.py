#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""ed25519 信任根解析、公钥加载、签名验签（含全量签名核验）。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from .common import *


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

def _resolve_trust(registry: Path, trust_source: str | None) -> str:
    """信任根查找链：--trust > keys/plugin_trust.pub.pem（拆库后只认 keys/，P3-3）。"""
    if trust_source:
        return trust_source
    candidate = registry / _KEYS_FALLBACK[0]
    return str(candidate) if candidate.is_file() else ""


def validate_maintainer_private_key(registry: Path, private_pem: bytes) -> None:
    """Fail before publication writes unless the private key matches the trust root."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("维护者私钥必须是 ed25519 私钥")
    trust_source = _resolve_trust(registry, None)
    if not trust_source:
        raise ValueError("未找到市场信任根公钥，拒绝生成正式发布文件")
    trusted_public = _load_public_key(trust_source).public_bytes_raw()
    derived_public = private_key.public_key().public_bytes_raw()
    if derived_public != trusted_public:
        raise ValueError("维护者私钥与市场信任根不匹配，拒绝生成正式发布文件")


def _canonical_manifest(manifest: dict[str, Any]) -> bytes:
    return (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _verify_package_manifest_entry(
    registry: Path,
    entry: dict[str, Any],
    trust: str,
    *,
    require_maintainer: bool,
) -> None:
    rel = entry.get("package_manifest_file")
    if not rel:
        return  # legacy package
    manifest_path = _require_contained(registry, registry, str(rel), "package manifest")
    creator_sig_path = _require_contained(
        registry, registry, str(entry.get("creator_package_signature_file", "")),
        "creator package signature",
    )
    maintainer_rel = entry.get("maintainer_package_signature_file")
    maintainer_sig_path = (
        _require_contained(registry, registry, str(maintainer_rel), "maintainer package signature")
        if maintainer_rel
        else None
    )
    if not manifest_path.is_file() or not creator_sig_path.is_file():
        raise ValueError(f"包 {entry.get('id')} 缺少 manifest 或创作者整包签名")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = _canonical_manifest(manifest)
    if manifest_path.read_bytes() != data:
        raise ValueError(f"包 {entry.get('id')} 的 manifest 不是规范 JSON")
    expected_digest = str(entry.get("package_manifest_sha256", ""))
    actual_digest = hashlib.sha256(data).hexdigest()
    if expected_digest and expected_digest != actual_digest:
        raise ValueError(f"包 {entry.get('id')} 的 manifest sha256 不一致")
    identity_path = _require_contained(
        registry, registry, str(entry.get("creator_identity_file", "")), "creator identity"
    )
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    raw = base64.b64decode(str(identity["public_key"]), validate=True)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(creator_sig_path.read_bytes(), data)
    except Exception as exc:
        raise ValueError(f"包 {entry.get('id')} 创作者整包签名无效") from exc
    package_dir = manifest_path.parent
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError(f"包 {entry.get('id')} manifest files 非法")
    for file_rel, expected in files.items():
        candidate = _require_contained(
            registry, package_dir, str(file_rel), f"包 {entry.get('id')} 文件"
        )
        if not candidate.is_file():
            raise ValueError(f"包 {entry.get('id')} 缺少 manifest 文件 {file_rel}")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if expected != f"sha256:{digest}":
            raise ValueError(f"包 {entry.get('id')} 文件哈希不一致: {file_rel}")
    if require_maintainer and (maintainer_sig_path is None or not maintainer_sig_path.is_file()):
        raise ValueError(f"包 {entry.get('id')} 缺少维护者整包签名")
    if maintainer_sig_path is not None and (
        not maintainer_sig_path.is_file()
        or not _verify_signature(data, maintainer_sig_path.read_bytes(), trust)
    ):
        raise ValueError(f"包 {entry.get('id')} 维护者整包签名无效")

def _verify_signatures(
    registry: Path,
    catalog: dict[str, Any],
    trust_source: str | None,
    *,
    require_maintainer: bool = False,
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
        _verify_package_manifest_entry(
            registry, entry, trust, require_maintainer=require_maintainer
        )
        plugin_path = registry / str(entry["plugin_file"])
        sig = entry.get("signature_file")
        sig_path = registry / str(sig) if sig else None
        has_maintainer_sig = sig_path is not None and sig_path.is_file()
        if require_maintainer and not has_maintainer_sig:
            raise ValueError(
                f"插件 {entry['id']} 尚无维护者分发签名；投稿可接受，正式发布拒绝"
            )
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
        _verify_package_manifest_entry(
            registry, entry, trust, require_maintainer=require_maintainer
        )
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


def _verify_catalog_signature(registry: Path, trust_source: str | None) -> None:
    """Require catalog.json.sig to cover the exact catalog bytes on disk."""
    catalog = registry / "catalog.json"
    signature = registry / "catalog.json.sig"
    if not catalog.is_file() or not signature.is_file():
        raise ValueError("正式发布缺少 catalog.json 或 catalog.json.sig")
    trust = _resolve_trust(registry, trust_source)
    if not trust:
        raise ValueError("正式发布无法找到 catalog 信任根公钥")
    if not _verify_signature(catalog.read_bytes(), signature.read_bytes(), trust):
        raise ValueError("catalog.json.sig 未覆盖当前 catalog.json（正式发布拒绝）")


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
