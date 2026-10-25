#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Maintainer-only publication of one reviewed creator-signed submission.

The tool never executes submitted code.  It preserves every creator-signed
payload byte, assigns a stable market handle, adds maintainer signatures, then
regenerates and signs the formal catalog.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REGISTRY = Path(__file__).resolve().parents[1]
if str(REGISTRY / "tools") not in sys.path:
    sys.path.insert(0, str(REGISTRY / "tools"))

from catalog_lib.authors import assign_market_handle, load_authors
from catalog_lib.build import generate
from catalog_lib.cli import publish_check
from catalog_lib.contract import compare_overlay_payload
from catalog_lib.identity import CreatorIdentity
from catalog_lib.signing import sign_bytes, validate_maintainer_private_key
from catalog_lib.transparency import (
    REVIEW_DECISIONS,
    build_v2_entry,
    canonicalize_entry,
    last_v2_entry,
)
from validate_submission import validate_one

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$"
)


def _semver_key(value: str) -> tuple[int, int, int, tuple[tuple[int, int | str], ...]]:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise ValueError(f"version must be SemVer (x.y.z[-prerelease]): {value!r}")
    prerelease = match.group(4)
    # A release sorts after all of its prereleases. Numeric identifiers sort
    # before non-numeric identifiers, per SemVer 2.0.0.
    if prerelease is None:
        pre_key: tuple[tuple[int, int | str], ...] = ((2, ""),)
    else:
        pre_key = tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in prerelease.split(".")
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), pre_key


def _literal_metadata(plugin: Path) -> dict[str, Any]:
    tree = ast.parse(plugin.read_text(encoding="utf-8"), filename=str(plugin))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PLUGIN_METADATA"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            return value if isinstance(value, dict) else {}
    return {}


def _public_pem(raw: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    return Ed25519PublicKey.from_public_bytes(raw).public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _copy_creator_package(source: Path, destination: Path, manifest: dict[str, Any]) -> None:
    destination.mkdir(parents=True)
    for rel in sorted(manifest["files"]):
        src = source / Path(*str(rel).split("/"))
        target = destination / Path(*str(rel).split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    for name in ("package.manifest.json", "package.manifest.creator.sig", "creator.sig"):
        src = source / name
        if src.is_file():
            shutil.copyfile(src, destination / name)


def _metadata(
    source: Path, manifest: dict[str, Any], submission: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (市场 overlay 元数据, 创作者签名载荷可比对声明)。

    P2-10：payload_decl 保留载荷原始声明，供 overlay↔载荷漂移双向比对；
    安装期调用同一比对函数属主仓配套（跨仓待落地）。
    """
    kind = str(manifest["package_type"])
    market = submission.get("market_metadata") or {}
    if not isinstance(market, dict):
        market = {}
    if kind == "plugin":
        plugin_meta = _literal_metadata(source / "plugin.py")
        yaml_meta = yaml.safe_load((source / "plugin.yaml").read_text(encoding="utf-8")) \
            if (source / "plugin.yaml").is_file() else {}
        if not isinstance(yaml_meta, dict):
            yaml_meta = {}
        payload_decl: dict[str, Any] = {
            "permissions": list(plugin_meta.get("permissions") or yaml_meta.get("permissions") or []),
            "domains": list(plugin_meta.get("domains") or yaml_meta.get("domains") or []),
            "input_files": list(plugin_meta.get("input_files") or yaml_meta.get("input_files") or []),
            "dependencies": list(plugin_meta.get("dependencies") or yaml_meta.get("dependencies") or []),
            "required_capabilities": dict(
                plugin_meta.get("required_capabilities")
                or yaml_meta.get("required_capabilities")
                or {}
            ),
        }
        metadata: dict[str, Any] = {
            "name": str(market.get("name") or plugin_meta.get("name") or manifest["package_id"]),
            # P2-10：category 是展示分类，不再回退取 plugin_types[0]（扩展点 ≠ 分类）；
            # 未声明时固定归 utility，避免类型名被误读为市场分类。
            "category": str(market.get("category") or "utility"),
            "plugin_types": list(plugin_meta.get("plugin_types") or yaml_meta.get("plugin_types") or ["source"]),
            "summary": str(market.get("summary") or plugin_meta.get("description") or ""),
            "permissions": payload_decl["permissions"],
            "compatible_core": str(yaml_meta.get("compatible_core") or f">={plugin_meta.get('min_core_version') or '0.11.1'}"),
            "license": str(plugin_meta.get("license") or yaml_meta.get("license") or ""),
            "execution_mode": str(plugin_meta.get("execution_mode") or yaml_meta.get("execution_mode") or "subprocess"),
            "domains": payload_decl["domains"],
            "input_files": payload_decl["input_files"],
            "dependencies": payload_decl["dependencies"],
            "required_capabilities": payload_decl["required_capabilities"],
            "state_schema_version": int(
                plugin_meta.get("state_schema_version")
                or yaml_meta.get("state_schema_version")
                or 1
            ),
            "tags": list(plugin_meta.get("tags") or yaml_meta.get("tags") or []),
        }
        return metadata, payload_decl
    template = yaml.safe_load((source / "template.yaml").read_text(encoding="utf-8")) or {}
    block = template.get("template", {}) if isinstance(template, dict) else {}
    if not isinstance(block, dict):
        block = {}
    metadata = {
        "name": str(market.get("name") or block.get("name") or manifest["package_id"]),
        "category": str(market.get("category") or block.get("category") or "general"),
        "summary": str(market.get("summary") or block.get("description") or ""),
        "compatible_core": f">={block.get('min_core_version') or '0.11.1'}",
        "license": str(block.get("license") or ""),
        "tags": list(block.get("tags") or []),
    }
    return metadata, {}


def finalize(args: argparse.Namespace) -> int:
    source = Path(args.submission_dir).resolve()
    submissions_root = REGISTRY / "submissions"
    kind, package_id = validate_one(source, submissions_root)
    manifest_bytes = (source / "package.manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    submission = json.loads((source / "submission.json").read_text(encoding="utf-8"))
    identity = CreatorIdentity.from_dict(
        json.loads((source / "creator.identity").read_text(encoding="utf-8"))
    )
    if args.reviewed_manifest_sha256 != hashlib.sha256(manifest_bytes).hexdigest():
        raise ValueError("维护者确认的审核哈希与当前 package manifest 不一致")
    authors = load_authors(REGISTRY)
    handle = assign_market_handle(authors, identity.key_fingerprint, identity.username)
    market_id = args.market_id or package_id
    if market_id != package_id:
        raise ValueError(
            "market ID 属于创作者签名包身份，维护者不能改写；ID 冲突时请作者用新 ID 重新签名投稿"
        )
    directory_name = market_id if kind == "plugin" else market_id.replace("/", "--")
    destination = REGISTRY / ("plugins" if kind == "plugin" else "templates") / directory_name
    new_version = str(manifest["version"])
    _semver_key(new_version)
    is_update = destination.exists()
    if is_update:
        overlay_path = destination / "market.yaml"
        if not overlay_path.is_file():
            raise ValueError(
                "legacy market entries must be migrated to market.yaml before creator-package updates"
            )
        previous_overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
        if not isinstance(previous_overlay, dict):
            raise ValueError(f"invalid existing market.yaml: {overlay_path}")
        if previous_overlay.get("id") != market_id:
            raise ValueError("existing market ID differs from the signed package ID")
        if previous_overlay.get("author_fingerprint") != identity.key_fingerprint:
            raise PermissionError(
                "package ID is already owned by another creator key; maintainers cannot transfer ownership"
            )
        previous_version = str(previous_overlay.get("version", ""))
        if _semver_key(new_version) <= _semver_key(previous_version):
            raise ValueError(
                f"update version must increase monotonically: {new_version} <= {previous_version}"
            )
        package_destination = destination / "versions" / new_version
        if package_destination.exists():
            raise FileExistsError(f"version already exists and will not be overwritten: {package_destination}")
    else:
        overlay_path = destination / "market.yaml"
        package_destination = destination
    metadata, payload_decl = _metadata(source, manifest, submission)
    if not metadata["summary"] or not metadata["license"]:
        raise ValueError("正式发布需要非空 summary 与 license")
    private_pem = Path(args.maintainer_key).expanduser().read_bytes()
    validate_maintainer_private_key(REGISTRY, private_pem)
    _copy_creator_package(source, package_destination, manifest)
    (package_destination / "package.manifest.maintainer.sig").write_bytes(
        sign_bytes(manifest_bytes, private_pem)
    )
    main_name = "plugin.py" if kind == "plugin" else "template.yaml"
    (package_destination / f"{main_name}.sig").write_bytes(
        sign_bytes((package_destination / main_name).read_bytes(), private_pem)
    )
    public_path = REGISTRY / "keys" / f"{identity.key_fingerprint}.pub.pem"
    public_path.write_bytes(_public_pem(identity.public_key))
    author_path = REGISTRY / "authors" / f"{handle}.yaml"
    if not author_path.exists():
        author_path.write_text(
            yaml.safe_dump(
                {
                    "market_handle": handle,
                    "username": handle,
                    "requested_username": identity.username,
                    "display_name": identity.username,
                    "pubkey_ref": f"../keys/{identity.key_fingerprint}.pub.pem",
                    "fingerprint": identity.key_fingerprint,
                    "roles": ["publisher"],
                    "status": "active",
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
    base = package_destination.relative_to(REGISTRY).as_posix()
    overlay: dict[str, Any] = {
        "id": market_id,
        "name": metadata["name"],
        "version": str(manifest["version"]),
        "publisher": handle,
        "author_fingerprint": identity.key_fingerprint,
        "category": metadata["category"],
        "summary": metadata["summary"],
        "description_file": f"{base}/listing.md",
        "signature_algorithm": "ed25519",
        "compatible_core": metadata["compatible_core"],
        "license": metadata["license"],
        "tags": metadata["tags"],
        "updated_at": datetime.now(UTC).date().isoformat(),
        "creator_signature_file": f"{base}/creator.sig",
        "creator_identity_file": f"{base}/creator.identity",
        "package_manifest_file": f"{base}/package.manifest.json",
        "creator_package_signature_file": f"{base}/package.manifest.creator.sig",
        "maintainer_package_signature_file": f"{base}/package.manifest.maintainer.sig",
        "package_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    if kind == "plugin":
        overlay.update(
            {
                "plugin_file": f"{base}/plugin.py",
                "signature_file": f"{base}/plugin.py.sig",
                "permissions": metadata["permissions"],
                "plugin_types": metadata["plugin_types"],
                "execution_mode": metadata["execution_mode"],
                "domains": metadata["domains"],
                "input_files": metadata["input_files"],
                "dependencies": metadata["dependencies"],
                "required_capabilities": metadata["required_capabilities"],
                "state_schema_version": metadata["state_schema_version"],
            }
        )
    else:
        overlay.update(
            {
                "template_file": f"{base}/template.yaml",
                "signature_file": f"{base}/template.yaml.sig",
            }
        )
    if kind == "plugin":
        # P2-10：overlay 展示声明必须与创作者签名载荷一致；漂移即拒发（安装期
        # 二次双向比对由主仓安装链路配套落地）。
        drift = compare_overlay_payload(overlay, payload_decl)
        if drift:
            raise ValueError(
                "overlay 与创作者签名载荷声明漂移（P2-10）: " + "; ".join(drift)
            )
    overlay_path.write_text(
        yaml.safe_dump(overlay, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    generate(REGISTRY)
    catalog = REGISTRY / "catalog.json"
    (REGISTRY / "catalog.json.sig").write_bytes(sign_bytes(catalog.read_bytes(), private_pem))
    # P2-5 v2 哈希链 + P2-11 审核留痕：链接上一条 v2 条目，固化 manifest 证据哈希、
    # 审核人/结论/备注；公网 Rekor 类公开账本锚定属外部配套。
    prev = last_v2_entry(REGISTRY / "signing_transparency.jsonl")
    log_entry = build_v2_entry(
        prev,
        operation="update-package" if is_update else "finalize-package",
        package_type=kind,
        package_id=market_id,
        version=manifest["version"],
        creator_fingerprint=identity.key_fingerprint,
        evidence_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        package_manifest_file=f"{base}/package.manifest.json",
        reviewer=args.reviewer,
        decision=args.review_decision,
        review_comment=args.review_comment,
        extra={"market_handle": handle},
    )
    with (REGISTRY / "signing_transparency.jsonl").open(
        "a", encoding="utf-8", newline="\n"
    ) as stream:
        # P3-11：路径字段 POSIX 归一后落盘，杜绝新条目再引入反斜杠路径。
        stream.write(
            json.dumps(
                canonicalize_entry(log_entry), ensure_ascii=False, sort_keys=True
            )
            + "\n"
        )
    return publish_check(REGISTRY)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审核后准备正式市场发布（绝不执行投稿代码）")
    parser.add_argument("submission_dir")
    parser.add_argument("--reviewed-manifest-sha256", required=True)
    parser.add_argument("--maintainer-key", required=True)
    parser.add_argument("--market-id", default=None)
    # P2-11：人工审核留痕（审核人标识/结论/备注写入透明日志 v2 条目）。
    parser.add_argument("--reviewer", default=None, help="审核人标识（公钥指纹或 handle）")
    parser.add_argument("--review-comment", default=None, help="审核备注")
    parser.add_argument(
        "--review-decision",
        default="approved",
        choices=sorted(REVIEW_DECISIONS),
        help="人工审核结论",
    )
    args = parser.parse_args(argv)
    try:
        result = finalize(args)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL finalize: {exc}")
        return 1
    if result == 0:
        print("OK finalize: 作者包字节未修改，维护者整包签名与正式 catalog 已完成")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
