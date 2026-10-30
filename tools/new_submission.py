#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a minimal, schema-aligned plugin or template submission skeleton.

P2-9：脚手架产物必须先通过投稿校验器门 1/门 3 纯规则与 schema 字段白名单
自检再落盘——不再发出 ``api_version`` / ``description`` / ``min_core_version``
等被未知字段规则拒绝的遗留键，也不再缺 summary / compatible_core / license 等
必填契约。脚手架只生成源码骨架；创作者签名包由主仓上传器/签名流程产出。

用法：
  python tools/new_submission.py plugin my-fetcher "我的采集器" 1.0.0 \
      --summary "一句话说明" --license MIT
  python tools/new_submission.py template social/market/foo "示例模板" 1.0.0
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Any

REGISTRY = Path(__file__).resolve().parents[1]
if str(REGISTRY / "tools") not in sys.path:
    sys.path.insert(0, str(REGISTRY / "tools"))

import yaml

from catalog_lib.common import (
    ALLOWED_PLUGIN_PERMISSIONS,
    LICENSE_ALLOWLIST,
    OFFICIAL_PLUGIN_TYPES,
    _ENTRY_KEYS,
    _TOP_LEVEL_EXTRA,
)
from validate_submission import (
    PLUGIN_ID_RE,
    TEMPLATE_ID_RE,
    _COMPATIBLE_CORE_RE,
    gate1_declaration_consistency,
    gate3_dependencies_consistency,
)

# 投稿源码侧 plugin.yaml 允许出现的键（覆盖 finalize ``_metadata`` 读取面 +
# 市场 overlay schema 白名单；不允许遗留的 api_version/description/min_core_version）。
_SCAFFOLD_YAML_KEYS = set(_ENTRY_KEYS) | _TOP_LEVEL_EXTRA


def _read_plugin_metadata(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PLUGIN_METADATA" for t in node.targets
        ):
            target = "PLUGIN_METADATA"
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "PLUGIN_METADATA":
            target = "PLUGIN_METADATA"
            value = node.value
        if target == "PLUGIN_METADATA":
            loaded = ast.literal_eval(value)
            if isinstance(loaded, dict):
                return loaded
            raise ValueError("PLUGIN_METADATA 必须是映射")
    raise ValueError("plugin.py 缺少可 AST 读取的 PLUGIN_METADATA")


def _self_check_plugin(
    root: Path, package_id: str, metadata: dict[str, Any], yaml_meta: dict[str, Any]
) -> None:
    source = (root / "plugin.py").read_text(encoding="utf-8")
    # 门 1 / 门 3 纯规则自检（与投稿 CI 同一函数）。
    gate1_declaration_consistency(root, metadata, source)
    gate3_dependencies_consistency(root, metadata, source)
    unknown = set(yaml_meta) - _SCAFFOLD_YAML_KEYS
    if unknown:
        raise ValueError(f"plugin.yaml 含 schema 未知字段: {sorted(unknown)}")
    if str(metadata.get("name")) != str(yaml_meta.get("name")):
        raise ValueError("plugin.py PLUGIN_METADATA.name 与 plugin.yaml.name 不一致")
    if str(metadata.get("version")) != str(yaml_meta.get("version")):
        raise ValueError("plugin.py PLUGIN_METADATA.version 与 plugin.yaml.version 不一致")
    if str(metadata.get("license")) != str(yaml_meta.get("license")):
        raise ValueError("plugin.py PLUGIN_METADATA.license 与 plugin.yaml.license 不一致")
    if str(metadata.get("compatible_core")) != str(yaml_meta.get("compatible_core")):
        raise ValueError("compatible_core 双轨不一致")
    permissions = {str(p).casefold() for p in metadata.get("permissions", [])}
    if permissions - ALLOWED_PLUGIN_PERMISSIONS:
        raise ValueError(f"未知权限: {sorted(permissions - ALLOWED_PLUGIN_PERMISSIONS)}")
    types = {str(t).casefold() for t in metadata.get("plugin_types", [])}
    if types - OFFICIAL_PLUGIN_TYPES:
        raise ValueError(f"未知 plugin_types: {sorted(types - OFFICIAL_PLUGIN_TYPES)}")


def _self_check_template(root: Path, package_id: str, block: dict[str, Any]) -> None:
    required = ("id", "name", "version", "category", "license", "compatible_core")
    missing = [key for key in required if not str(block.get(key) or "").strip()]
    if missing:
        raise ValueError(f"template: 块缺少必填字段 {missing}")
    if not TEMPLATE_ID_RE.fullmatch(package_id):
        raise ValueError(f"非法模板 ID: {package_id!r}")
    if str(block["id"]) != package_id:
        raise ValueError("template.id 与命令行包 ID 不一致")
    if not _COMPATIBLE_CORE_RE.fullmatch(str(block["compatible_core"])):
        raise ValueError(f"compatible_core 非法 semver 区间: {block['compatible_core']!r}")


def _render_plugin(
    package_id: str, name: str, version: str,
    summary: str, license_id: str, root: Path,
) -> None:
    plugin_py = f'''"""{name}：{summary}。

TODO: 完成实现。契约与审核要求见仓库根 CATALOG_SCHEMA.md、CONTRIBUTING.md；
subprocess 隔离下仅经 omnicrawler_sdk 能力代理访问宿主，禁止 import 宿主核心。
"""
from __future__ import annotations

from typing import Any

PLUGIN_METADATA: dict[str, Any] = {{
    "name": {name!r},
    "version": {version!r},
    "license": {license_id!r},
    "plugin_types": ["source"],
    "permissions": [],
    "domains": [],
    "input_files": [],
    "dependencies": [],
    "required_capabilities": {{}},
    "execution_mode": "subprocess",
    "state_schema_version": 1,
    "compatible_core": ">=0.11.2",
    "summary": {summary!r},
}}


def run(context: dict[str, Any]) -> dict[str, Any]:
    """TODO: 实现插件入口；最小权限与依赖只声明实际需要的部分。"""
    return {{"ok": True}}
'''
    plugin_yaml = {
        "id": package_id,
        "name": name,
        "version": version,
        "category": "utility",
        "summary": summary,
        "license": license_id,
        "compatible_core": ">=0.11.2",
        "plugin_types": ["source"],
        "permissions": [],
        "execution_mode": "subprocess",
        "domains": [],
        "input_files": [],
        "dependencies": [],
        "required_capabilities": {},
        "state_schema_version": 1,
        "tags": [],
    }
    (root / "plugin.py").write_text(plugin_py, encoding="utf-8", newline="\n")
    (root / "plugin.yaml").write_text(
        yaml.safe_dump(plugin_yaml, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="\n",
    )
    (root / "listing.md").write_text(f"# {name}\n\n{summary}\n", encoding="utf-8", newline="\n")
    (root / "README.md").write_text(
        f"# {name}\n\n{summary}\n\n## 提交前自检\n\n"
        "1. 阅读 `../../../CATALOG_SCHEMA.md` 与 `../../../CONTRIBUTING.md`；\n"
        "2. 用创作者密钥生成 package.manifest.json 与 detached 签名（主仓上传流程）；\n"
        "3. 运行 `python tools/validate_submission.py` 通过投稿静态校验。\n",
        encoding="utf-8", newline="\n",
    )
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_contract.py").write_text(
        "\"\"\"契约占位：补齐插件行为与最小权限/依赖声明的回归用例。\"\"\"\n",
        encoding="utf-8", newline="\n",
    )
    metadata = _read_plugin_metadata(plugin_py)
    _self_check_plugin(root, package_id, metadata, plugin_yaml)


def _render_template(
    package_id: str, name: str, version: str,
    summary: str, license_id: str, root: Path,
) -> None:
    block = {
        "id": package_id,
        "name": name,
        "version": version,
        "category": "general",
        "publisher": "",
        "author_fingerprint": "",
        "license": license_id,
        "compatible_core": ">=0.11.2",
        "tags": [],
        "verified_at": "",
    }
    document = {
        "project": {"name": package_id, "description": summary},
        "source": {"type": "http", "seeds": []},
        "template": block,
    }
    (root / "template.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8", newline="\n",
    )
    (root / "listing.md").write_text(f"# {name}\n\n{summary}\n", encoding="utf-8", newline="\n")
    (root / "README.md").write_text(
        f"# {name}\n\n{summary}\n\n字段契约见 `../../../CATALOG_SCHEMA.md`。\n",
        encoding="utf-8", newline="\n",
    )
    _self_check_template(root, package_id, block)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建 schema 对齐的投稿脚手架（落盘前自检）")
    parser.add_argument("kind", choices=["plugin", "template"])
    parser.add_argument("package_id")
    parser.add_argument("name")
    parser.add_argument("version")
    parser.add_argument("--summary", default="")
    parser.add_argument("--license", default="MIT", choices=sorted(LICENSE_ALLOWLIST))
    parser.add_argument("--out", default=None, help="自定义输出根目录（默认 submissions/<kind>s/<id>）")
    args = parser.parse_args(argv)

    id_pattern = PLUGIN_ID_RE if args.kind == "plugin" else TEMPLATE_ID_RE
    if not id_pattern.fullmatch(args.package_id):
        print(f"[FAIL] 非法包 ID（{id_pattern.pattern}）: {args.package_id}")
        return 2
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", args.version):
        print(f"[FAIL] 版本必须是 SemVer x.y.z: {args.version}")
        return 2
    if not args.summary.strip():
        print("[FAIL] 必须提供 --summary 一句话说明")
        return 2

    root = Path(args.out) if args.out else (
        REGISTRY / "submissions" / f"{args.kind}s" / args.package_id
    )
    if root.exists():
        print(f"[FAIL] 目录已存在，拒绝覆盖: {root}")
        return 2
    root.mkdir(parents=True)

    try:
        if args.kind == "plugin":
            _render_plugin(
                args.package_id, args.name, args.version,
                args.summary.strip(), args.license, root,
            )
        else:
            _render_template(
                args.package_id, args.name, args.version,
                args.summary.strip(), args.license, root,
            )
    except (ValueError, OSError, yaml.YAMLError) as exc:
        import shutil
        shutil.rmtree(root, ignore_errors=True)
        print(f"[FAIL] 脚手架自检未通过，已回滚: {exc}")
        return 1

    print(f"[OK] 已生成 {args.kind} 骨架（门1/门3 与 schema 自检通过）: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
