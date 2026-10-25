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
TEMPLATE_ID_RE = re.compile(
    r"^[a-z](?:[a-z0-9]|_[a-z0-9]|-[a-z0-9])*"
    r"(?:/[a-z](?:[a-z0-9]|_[a-z0-9]|-[a-z0-9])*)*$"
)
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)

# P1-1 门 2（载荷/依赖许可）：SPDX 白名单副本，与 catalog_lib.common.LICENSE_ALLOWLIST 同集合，
# 由 check_plugin_schema_policy 类策略断言锁对齐；投稿器保持自包含不 import 市场库。
LICENSE_ALLOWLIST = {
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "CC0-1.0",
    "ISC",
    "MIT",
    "MPL-2.0",
    "Unlicense",
}

# P2-6 门 3：依赖版本约束格式（semver 区间），兼容 >=x.y[.z],<x.y[.z] / ==x.y.z / ^x.y.z /
# ~x.y.z / 裸版本号；minor-only（x.y）与 major.minor.patch 均接受。
_SEMVER_PART = (
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:\.(?:0|[1-9]\d*))?(?:-[0-9A-Za-z.-]+)?"
)
_DEP_CONSTRAINT_RE = re.compile(
    rf"^(?:>=|<=|==|~=|~|\^|>|<)?{_SEMVER_PART}"
    rf"(?:\s*,\s*(?:>=|<=|==|~=|~|\^|>|<)?{_SEMVER_PART})*$"
)

# P1-1 门 1：subprocess 隔离边界——宿主核心前缀与被禁权限前缀（镜像主仓 plugin_audit）。
_HOST_CORE_PREFIXES = ("omnicrawler.",)
_SUBPROCESS_FORBIDDEN_PERMISSION_PREFIXES = ("ui:", "hook")

# P1-5：compatible_core semver 区间格式（与 catalog_lib.core_version.parse_compatible_core
# 同一口径；投稿器保持自包含不 import 市场库，格式正则在此镜像，语义判定由共享模块提供）。
_SEMVER_VERSION = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
_COMPATIBLE_CORE_RE = re.compile(
    rf"^(>=|<=|==|~=|~|\^|>|<)?{_SEMVER_VERSION}"
    rf"(?:\s*,\s*(>=|<=|==|~=|~|\^|>|<)?{_SEMVER_VERSION})*$"
)
ALLOWED_PLUGIN_PERMISSIONS = {
    "records:read", "records:write", "artifacts:read", "artifacts:write",
    "responses:read", "responses:payload", "network:scoped", "temp:write",
    "files:read", "secrets:read", "state:read", "state:write",
    "resources:read", "surfaces:background", "render:local", "render:scripted",
}

# P2-3：宿主能力名白名单副本（与 catalog_lib.common.ALLOWED_CAPABILITIES 同集合，
# 由 check_plugin_schema_policy 类策略断言锁对齐；投稿器保持自包含不 import 市场库）。
ALLOWED_CAPABILITIES = {
    "system.info",
    "records.read", "records.page", "records.write",
    "responses.page", "responses.payload",
    "state.get", "state.set", "state.delete", "state.migrate",
    "artifacts.read",
    "artifact.stream.open", "artifact.stream.write", "artifact.stream.commit",
    "artifact.stream.abort",
    "network.fetch", "temp.open", "files.read",
    "resources.describe", "resources.enumerate", "resources.read",
    "render.html.snapshot", "render.html.live.start", "render.html.live.stop",
    "surface.background.set", "surface.background.configure",
    "surface.background.clear", "surface.background.capabilities",
    "secrets.get", "view.richtext", "view.progress",
}


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


def _extract_imports(source: str) -> set[str]:
    """AST 提取顶层模块名集合（import x / from x.y import z → 'x'），镜像主仓门 1/门 3。"""
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def gate1_declaration_consistency(root: Path, metadata: dict[str, Any], source: str) -> None:
    """门 1（P1-1 下沉投稿 CI）：权限⇒域名/输入文件配对、subprocess 隔离边界、载荷许可。

    - network:scoped 必须声明非空 domains（小写主机名形态校验）；
    - files:read 必须声明非空 input_files 路径白名单（POSIX 安全相对路径）；
    - subprocess 禁止 import 宿主核心（omnicrawler / omnicrawler.*，omnicrawler_sdk 除外）；
    - subprocess 禁止声明 ui:* / 旧式 hook 权限；
    - PLUGIN_METADATA.license 若声明，必须在 SPDX 白名单内。
    规则与主仓 plugin_audit.gate_declaration_consistency 同源；违规即 error 阻断。
    """
    permissions = {str(p).casefold() for p in metadata.get("permissions", [])}
    execution_mode = str(metadata.get("execution_mode", "subprocess") or "subprocess")

    domains = metadata.get("domains", [])
    if "network:scoped" in permissions:
        if not isinstance(domains, list) or not domains:
            raise ValueError(f"{root}: network:scoped 权限必须声明非空 domains 白名单（门 1）")
        for domain in domains:
            if (
                not isinstance(domain, str)
                or not DOMAIN_RE.fullmatch(domain)
                or domain != domain.lower()
            ):
                raise ValueError(f"{root}: domains 含非法小写主机名: {domain!r}（门 1）")

    input_files = metadata.get("input_files", [])
    if "files:read" in permissions:
        if not isinstance(input_files, list) or not input_files:
            raise ValueError(f"{root}: files:read 权限必须声明非空 input_files 白名单（门 1）")
        for rel in input_files:
            if not isinstance(rel, str) or not rel.strip():
                raise ValueError(f"{root}: input_files 条目必须为非空字符串（门 1）")
            safe_rel(rel)

    if execution_mode == "subprocess":
        imports = _extract_imports(source)
        host_imports = {
            name for name in imports
            if name == "omnicrawler" or name.startswith(_HOST_CORE_PREFIXES)
        }
        if host_imports:
            raise ValueError(
                f"{root}: subprocess 插件禁止 import 宿主核心: {sorted(host_imports)}"
                "（门 1；隔离边界，请改用 omnicrawler_sdk 能力代理）"
            )
        forbidden = {
            p for p in permissions
            if any(p.startswith(prefix) for prefix in _SUBPROCESS_FORBIDDEN_PERMISSION_PREFIXES)
        }
        if forbidden:
            raise ValueError(
                f"{root}: subprocess 插件不得声明 ui:/hook 权限: {sorted(forbidden)}"
                "（门 1；hook 应声明为 plugin_types，ui 需 in_process）"
            )

    license_id = metadata.get("license")
    if license_id is not None:
        license_id = str(license_id).strip()
        if license_id not in LICENSE_ALLOWLIST:
            raise ValueError(
                f"{root}: 载荷 license {license_id!r} 不在 SPDX 白名单内（门 2）: "
                f"{sorted(LICENSE_ALLOWLIST)}"
            )


def gate3_dependencies_consistency(root: Path, metadata: dict[str, Any], source: str) -> None:
    """门 3（P1-1 下沉投稿 CI）：dependencies 声明↔实测导入图双向一致 + 依赖许可/版本区间。

    - dependencies 必填（零依赖显式 []）；每条 {name, version, license}；
    - 依赖 license 须在 SPDX 白名单；版本约束须为合法 semver 区间格式；
    - 实测第三方导入（非标准库、非宿主、非 SDK、非同包本地模块）必须全部声明，
      声明的依赖必须全部出现在实测导入图中。
    规则与主仓 plugin_audit.gate_dependencies_consistency 同源；违规即 error 阻断。
    """
    declared = metadata.get("dependencies")
    if declared is None:
        raise ValueError(f"{root}: PLUGIN_METADATA.dependencies 未声明（零依赖请显式填 []）（门 3）")
    if not isinstance(declared, list):
        raise ValueError(f"{root}: dependencies 必须是列表 [{name, version, license}]（门 3）")

    declared_names: dict[str, dict[str, Any]] = {}
    for dep in declared:
        if not isinstance(dep, dict):
            raise ValueError(f"{root}: dependencies 条目非法: {dep!r}（门 3）")
        name = str(dep.get("name", "")).strip()
        if not name:
            raise ValueError(f"{root}: 依赖缺 name（门 3）")
        license_id = str(dep.get("license", "")).strip()
        if not license_id:
            raise ValueError(f"{root}: 依赖 {name} 缺 license（门 3）")
        if license_id not in LICENSE_ALLOWLIST:
            raise ValueError(
                f"{root}: 依赖 {name} 许可 {license_id!r} 不在 SPDX 白名单（门 3）"
            )
        version = str(dep.get("version", "")).strip()
        if not version or not _DEP_CONSTRAINT_RE.fullmatch(version):
            raise ValueError(
                f"{root}: 依赖 {name} 版本约束格式非法: {version!r}（门 3；semver 区间）"
            )
        declared_names[name] = dep

    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    local_modules = {path.stem for path in root.glob("*.py")}
    third_party = {
        name for name in _extract_imports(source)
        if name not in stdlib
        and name != "omnicrawler"
        and not name.startswith("omnicrawler_sdk")
        and name not in local_modules
    }
    for name in sorted(declared_names):
        if name not in third_party:
            raise ValueError(
                f"{root}: 声明的依赖 {name} 未在实测导入图中出现（门 3 声明↔实现互证失败）"
            )
    for name in sorted(third_party):
        if name not in declared_names:
            raise ValueError(
                f"{root}: 实测导入 {name} 未在 dependencies 声明（门 3；未声明即拒）"
            )


def _validate_plugin_payload(root: Path, package_id: str, version: str) -> None:
    source = (root / "plugin.py").read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
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
    unknown_permissions = {item.strip().casefold() for item in permissions} - ALLOWED_PLUGIN_PERMISSIONS
    if unknown_permissions:
        raise ValueError(f"{root}: unknown permissions: {sorted(unknown_permissions)}")
    required_capabilities = metadata.get("required_capabilities", {})
    if not isinstance(required_capabilities, dict) or not all(
        isinstance(name, str)
        and name.strip()
        and re.fullmatch(r"(?:>=)?[1-9][0-9]*", str(requirement).strip())
        for name, requirement in required_capabilities.items()
    ):
        raise ValueError(f"{root}: invalid required_capabilities")
    # P2-3：能力名必须在宿主契约白名单内，避免未知能力名投稿 CI 绿、运行期才被拒。
    unknown_caps = {
        str(name).strip() for name in required_capabilities
    } - ALLOWED_CAPABILITIES
    if unknown_caps:
        raise ValueError(f"{root}: unknown required_capabilities: {sorted(unknown_caps)}")
    state_schema_version = metadata.get("state_schema_version", 1)
    if not isinstance(state_schema_version, int) or state_schema_version < 1:
        raise ValueError(f"{root}: state_schema_version must be a positive integer")
    if metadata.get("execution_mode", "subprocess") not in ("subprocess", "in_process"):
        raise ValueError(f"{root}: invalid execution_mode")
    # P1-5：compatible_core semver 区间格式校验（口径与 catalog_lib.core_version 对齐）。
    compatible_core = metadata.get("compatible_core")
    if compatible_core is not None:
        if not isinstance(compatible_core, str) or not _COMPATIBLE_CORE_RE.fullmatch(
            compatible_core.strip()
        ):
            raise ValueError(
                f"{root}: compatible_core 非法 semver 区间: {compatible_core!r}"
            )
    # 旧契约 2 投稿未声明 plugin_types 时按历史 source 语义迁移；一旦显式
    # 声明，就必须是合法非空列表，不能用空列表绕过类型门禁。
    plugin_types = metadata.get("plugin_types", ["source"])
    official_types = {
        "source", "fetcher", "processor", "exporter", "auth_provider",
        "parser", "extractor", "transformer", "hook", "ui",
        "resource_provider", "view",
    }
    if not isinstance(plugin_types, list) or not plugin_types or not all(
        isinstance(item, str) and item.strip() for item in plugin_types
    ):
        raise ValueError(f"{root}: plugin_types must be a non-empty string array")
    unknown_types = {item.strip().casefold() for item in plugin_types} - official_types
    if unknown_types:
        raise ValueError(f"{root}: unknown plugin_types: {sorted(unknown_types)}")
    if any(item.strip().casefold() == "ui" for item in plugin_types):
        raise ValueError(f"{root}: native ui plugins are local-only and cannot enter the market")

    # P1-1：门 1（权限配对 / subprocess 隔离 / 载荷许可）与门 3（依赖↔导入图双向）
    # 在投稿 CI 即 fail-closed 阻断，不等安装/加载关口。
    gate1_declaration_consistency(root, metadata, source)
    gate3_dependencies_consistency(root, metadata, source)


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
    # P2-7：与 catalog_lib.paths.safe_relative_path 同一规则（自包含镜像副本，
    # 策略脚本锁正则/行为对齐）。段检查基于原始字符串切分，避免归一化吞掉 ./ 。
    raw = str(value)
    if not raw or "\\" in raw:
        raise ValueError(f"非法相对路径: {value!r}")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"非法相对路径（绝对路径/盘符）: {value!r}")
    parts = raw.split("/")
    if ".." in parts or "." in parts:
        raise ValueError(f"非法相对路径（含上级/当前目录段）: {value!r}")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ValueError(f"非法相对路径: {value!r}")
    return path


# P3-10：运行必需文件分类（与 catalog_lib.contract 同一规则的自包含镜像；
# 策略/测试锁双侧一致）。tests/docs/examples 与 README/LICENSE/CHANGELOG 等辅助
# 材料归为非运行时；主仓下载清单过滤属跨仓配套。
_NON_RUNTIME_DIR_PARTS = {"tests", "test", "docs", "examples", "example"}
_NON_RUNTIME_NAME_RE = re.compile(
    r"^(readme|license|licence|changelog|notice|contributing|security|"
    r"authors?|manifest|notes?|changes?)(\..*)?$",
    re.IGNORECASE,
)


def is_runtime_file(rel: str) -> bool:
    parts = [part for part in str(rel).split("/") if part]
    if not parts:
        return False
    if any(part in _NON_RUNTIME_DIR_PARTS for part in parts[:-1]):
        return False
    name = parts[-1]
    if _NON_RUNTIME_NAME_RE.match(name):
        return False
    if name.endswith((".md", ".rst", ".txt")) and name != "listing.md":
        return False
    return True


def non_runtime_files(declared: dict[str, Any]) -> list[str]:
    """P3-10：manifest 中归为非运行时的文件相对路径列表（仅提示，不阻断）。"""
    return [str(rel) for rel in declared if not is_runtime_file(str(rel))]


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

    # scan_plugin_dir 的熵检查只分析凭据型连续 token；令牌模式、敏感字段、
    # 敏感文件名与默认熵阈值均和正式目录 CI 使用同一套 fail-closed 规则。
    if scan_plugin_dir(root):
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
    validated: list[tuple[str, str]] = []
    warnings: list[str] = []
    try:
        for root in roots:
            validated.append(validate_one(root, submissions))
            manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
            declared = manifest.get("files", {})
            for rel in non_runtime_files(declared if isinstance(declared, dict) else {}):
                warnings.append(
                    f"{root.relative_to(submissions)}: 非运行时文件随包声明 "
                    f"（主仓下载清单过滤待配套）: {rel}"
                )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL submission: {exc}")
        return 1
    for warning in warnings:
        print(f"  ! {warning}")
    print(
        f"OK submissions: {len(validated)} 个创作者签名包静态验证通过"
        f"（未执行投稿代码；{len(warnings)} 条非运行时文件提示）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
