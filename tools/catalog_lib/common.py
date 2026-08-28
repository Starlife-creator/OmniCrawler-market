#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""共享常量与基础工具（schema 常量、YAML 加载、路径包含性校验）。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
# B02-020：双轨信任模型——维护者冷密钥背书（signature_file 对信任根）+
# 创作者热密钥签名（creator.sig 对 creator.identity 公钥），两条轨独立验签。

TRUST_MODEL = "dual-rail-ed25519"

TRUST_KEY_REF = "keys/plugin_trust.pub.pem"
# catalog_lib/common.py -> catalog_lib -> tools -> 仓库根（自包含约定）
REGISTRY_DIR = Path(__file__).resolve().parents[2]

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
    # 完整包协议：创作者与维护者签署同一 package manifest。
    "package_manifest_file",
    "creator_package_signature_file",
    "maintainer_package_signature_file",
    "package_manifest_sha256",
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
    "creator_signature_file",
    "creator_identity_file",
    "package_manifest_file",
    "creator_package_signature_file",
    "maintainer_package_signature_file",
    "package_manifest_sha256",
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


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
