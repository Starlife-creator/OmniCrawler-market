#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Static-only validator for creator-signed plugin/template submissions.

This script intentionally never imports or executes submitted Python code.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import yaml

MANIFEST = "package.manifest.json"
CREATOR_SIG = "package.manifest.creator.sig"
GENERATED = {MANIFEST, CREATOR_SIG, "package.manifest.maintainer.sig", "creator.sig", "submission.json"}
IGNORED = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:/[a-z0-9_-]+)*$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)


def _plugin_metadata(tree: ast.AST) -> dict[str, Any]:
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "PLUGIN_METADATA" for target in targets):
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError) as exc:
                raise ValueError("PLUGIN_METADATA must be a static literal") from exc
            if not isinstance(value, dict):
                raise ValueError("PLUGIN_METADATA must be a mapping")
            return value
    raise ValueError("plugin.py is missing static PLUGIN_METADATA")


def _validate_plugin_payload(root: Path, package_id: str, version: str) -> None:
    try:
        tree = ast.parse((root / "plugin.py").read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeError) as exc:
        raise ValueError(f"{root}: plugin.py cannot be parsed statically: {exc}") from exc
    metadata = _plugin_metadata(tree)
    if not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
        raise ValueError(f"{root}: PLUGIN_METADATA.name must be a non-empty string")
    if str(metadata.get("version", "")) != version:
        raise ValueError(f"{root}: PLUGIN_METADATA.version differs from signed version")
    permissions = metadata.get("permissions", [])
    if not isinstance(permissions, list) or not all(
        isinstance(item, str) and item.strip() for item in permissions
    ):
        raise ValueError(f"{root}: permissions must be a string array")
    if metadata.get("execution_mode", "subprocess") not in ("subprocess", "in_process"):
        raise ValueError(f"{root}: invalid execution_mode")


def _validate_template_payload(root: Path, package_id: str, version: str) -> None:
    try:
        document = yaml.safe_load((root / "template.yaml").read_text(encoding="utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{root}: template.yaml cannot be parsed safely: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("template"), dict):
        raise TypeError(f"{root}: template.yaml is missing the template mapping")
    metadata = document["template"]
    if metadata.get("id") != package_id:
        raise ValueError(f"{root}: template.id differs from signed package_id")
    if str(metadata.get("version", "")) != version:
        raise ValueError(f"{root}: template.version differs from signed version")
    domains = metadata.get("domains", [])
    if not isinstance(domains, list) or not all(
        isinstance(domain, str)
        and DOMAIN_RE.fullmatch(domain)
        and domain.lower() == domain
        for domain in domains
    ):
        raise ValueError(f"{root}: template.domains must contain lowercase hostnames only")
    source = document.get("source") if isinstance(document.get("source"), dict) else {}
    seeds = source.get("seeds", []) if isinstance(source, dict) else []
    for seed in seeds if isinstance(seeds, list) else []:
        url = seed.get("url") if isinstance(seed, dict) else seed
        if not isinstance(url, str) or "{{" in url:
            continue
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            raise ValueError(f"{root}: invalid template seed URL: {url!r}")
        if not any(host == domain or host.endswith("." + domain) for domain in domains):
            raise ValueError(f"{root}: seed host {host!r} is not declared in template.domains")


def canonical(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def safe_rel(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"非法相对路径: {value!r}")
    return path


def payload_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root)
        if any(part in IGNORED for part in rel_path.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"不允许符号链接: {rel_path}")
        if path.is_file() and path.name not in GENERATED:
            rel = rel_path.as_posix()
            safe_rel(rel)
            result[rel] = path
    return result


def validate_one(root: Path, submissions_root: Path) -> tuple[str, str]:
    manifest_path = root / MANIFEST
    sig_path = root / CREATOR_SIG
    identity_path = root / "creator.identity"
    submission_path = root / "submission.json"
    for required in (manifest_path, sig_path, identity_path, submission_path):
        if not required.is_file():
            raise ValueError(f"{root}: 缺少 {required.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError(f"{root}: 不支持的 package manifest schema")
    data = canonical(manifest)
    if manifest_path.read_bytes() != data:
        raise ValueError(f"{root}: manifest 不是规范 JSON")
    kind = str(manifest.get("package_type", ""))
    package_id = str(manifest.get("package_id", ""))
    expected_kind = "plugin" if root.relative_to(submissions_root).parts[0] == "plugins" else "template"
    if kind != expected_kind:
        raise ValueError(f"{root}: package_type 与投稿目录不一致")
    pattern = PLUGIN_ID_RE if kind == "plugin" else TEMPLATE_ID_RE
    if not pattern.fullmatch(package_id):
        raise ValueError(f"{root}: 非法 package_id {package_id!r}")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    username = str(identity.get("username", ""))
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(f"{root}: requested username 非法")
    public = base64.b64decode(str(identity["public_key"]), validate=True)
    if len(public) != 32:
        raise ValueError(f"{root}: creator.identity 不是 ed25519 公钥")
    fingerprint = hashlib.sha256(public).hexdigest()[:32]
    if identity.get("key_fingerprint") not in (None, "", fingerprint):
        raise ValueError(f"{root}: creator.identity 自称指纹与公钥不一致")
    if manifest.get("creator_fingerprint") != fingerprint:
        raise ValueError(f"{root}: manifest 创作者指纹不一致")
    if manifest.get("requested_username") != username:
        raise ValueError(f"{root}: requested_username 不一致")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(public).verify(sig_path.read_bytes(), data)
    except Exception as exc:
        raise ValueError(f"{root}: 创作者签名无效") from exc
    declared = manifest.get("files")
    if not isinstance(declared, dict) or not declared:
        raise ValueError(f"{root}: files 必须是非空映射")
    actual = payload_files(root)
    if set(declared) != set(actual):
        raise ValueError(
            f"{root}: 文件集合不一致，缺少={sorted(set(declared)-set(actual))}，"
            f"未声明={sorted(set(actual)-set(declared))}"
        )
    for rel, expected in declared.items():
        safe = safe_rel(str(rel))
        digest = hashlib.sha256((root / Path(*safe.parts)).read_bytes()).hexdigest()
        if expected != f"sha256:{digest}":
            raise ValueError(f"{root}: 文件哈希不一致 {rel}")
    required_payload = "plugin.py" if kind == "plugin" else "template.yaml"
    if required_payload not in declared:
        raise ValueError(f"{root}: 缺少 {required_payload}")
    if kind == "plugin":
        try:
            ast.parse((root / "plugin.py").read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError) as exc:
            raise ValueError(f"{root}: plugin.py 无法静态解析: {exc}") from exc
    version = str(manifest.get("version", ""))
    if not version:
        raise ValueError(f"{root}: manifest is missing version")
    if kind == "plugin":
        _validate_plugin_payload(root, package_id, version)
    else:
        _validate_template_payload(root, package_id, version)

    # This scanner reads file bytes and safe-loads YAML; submitted Python is
    # never imported or executed in the contribution workflow.
    from scan_plugin import scan_plugin_dir

    # Entropy alone is too noisy for source and canonical JSON. Token patterns,
    # secret fields and sensitive filenames remain fail-closed.
    if scan_plugin_dir(root, entropy_threshold=8.1):
        raise ValueError(f"{root}: credential/private-key static scan failed")

    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    if submission.get("creator_fingerprint") != fingerprint:
        raise ValueError(f"{root}: submission fingerprint 不一致")
    if submission.get("package_manifest_sha256") != hashlib.sha256(data).hexdigest():
        raise ValueError(f"{root}: submission package hash 不一致")
    relative = root.relative_to(submissions_root)
    if len(relative.parts) < 3 or relative.parts[1] != fingerprint:
        raise ValueError(f"{root}: 投稿目录必须按 creator fingerprint 分区")
    path_id = "/".join(relative.parts[2:])
    if path_id != package_id:
        raise ValueError(f"{root}: 投稿目录 ID {path_id!r} 与 package_id 不一致")
    return kind, package_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="静态验证创作者签名投稿（绝不执行插件）")
    parser.add_argument("--registry", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    submissions = Path(args.registry).resolve() / "submissions"
    if not submissions.is_dir():
        print("OK submissions: 暂无投稿")
        return 0
    roots = sorted(path.parent for path in submissions.rglob("submission.json"))
    try:
        validated = [validate_one(root, submissions) for root in roots]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL submission: {exc}")
        return 1
    print(f"OK submissions: {len(validated)} 个创作者签名包静态验证通过（未执行投稿代码）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
