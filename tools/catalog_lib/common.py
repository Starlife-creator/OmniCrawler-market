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

# 「官方认证作者」名单（维护者 2026-09-22 拍板）：条目的 publisher 命中本名单即「官方」徽章。
# ★ 列表结构为后续扩展预留（新增官方作者只需在此追加）；名单随 catalog 签名发布，
#   客户端据此判定作者身份——与「已审核」（流程状态）是两个独立维度（M5）。
OFFICIAL_PUBLISHERS: tuple[str, ...] = ("starlife",)

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
    "plugin_types",
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
    "required_capabilities",
    "state_schema_version",
    # P2-1：release_channel / review_depth / gates_evidence 为生产者-消费者两侧均未
    # 落地的死字段，从 schema 白名单移除（最小破坏路径：移除未消费字段并清引用；
    # 已签名历史包内残留字节属哈希锚定载荷，按字节不可变红线不回改）。
    "dependencies",
    # 完整包协议：创作者与维护者签署同一 package manifest。
    "package_manifest_file",
    "creator_package_signature_file",
    "maintainer_package_signature_file",
    "package_manifest_sha256",
    # P0-2：条目级吊销/弃用状态（与目录顶层 tombstones 并列的第二来源，安装端
    # check_revocation 同时消费两类来源）；revoked_versions 为版本级吊销列表。
    "revoked",
    "revoked_versions",
    "deprecated",
    # P2-2：条目自有仓库基址（主仓 market_client 已支持 source_base，市场 schema
    # 此前误拒；索引只背书不搬运时，清单与包从该基址取）。
    "source_base",
    # P3-9：目录层可静态预展示/预校验的可选契约字段。config_schema /
    # resource_limits 属运行时载荷读取，不进目录条目（见 CATALOG_SCHEMA.md 说明）。
    "api_version",
    "min_core_version",
    "max_core_version",
    "source_url",
    "fallback",
    "optional_dependencies",
    "contract_shape",
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
    "revoked",
    "revoked_versions",
    "deprecated",
]

_ID_RE_PREFIX = "^[a-z][a-z0-9_-]{1,63}$"
# 模板 ID 允许层级命名（如 generic/single-page），与内置模板目录一致

_TEMPLATE_ID_RE_PREFIX = (
    "^[a-z](?:[a-z0-9]|_[a-z0-9]|-[a-z0-9])*"
    "(?:/[a-z](?:[a-z0-9]|_[a-z0-9]|-[a-z0-9])*)*$"
)
# 允许出现在 market.yaml overlay 但**不进入 catalog.json 条目**的键：
# author_fingerprint（跨轨校验用）、files（scan_plugin 允许列表，纯扫描期元数据）。
# 注：B1 的 files:read 路径白名单字段落地时更名为 input_files（第 82 轮消歧），
# 避免与本键冲突。

_TOP_LEVEL_EXTRA = {"author_fingerprint", "files"}

# 门 2（许可合规）：插件代码许可 SPDX 白名单 —— ★ **口径由主仓拍板**。
# 本仓因**跨仓无法 import** 而保留一份副本；两侧由主仓
# `tests/unit/plugin/test_plugin_audit.py` 的**双向相等**断言锁死
# （任一侧漂移即红，不再有「单侧放宽」的空间）。
# ★ 2026-09-22 维护者拍板（方向 B「收紧」）：剔除 AGPL-3.0-* / GPL-3.0-*，
# 补 ISC / MPL-2.0 / 0BSD ⇒ 与主仓 `plugin_audit.LICENSE_ALLOWLIST` **同集合**。
# 理由：**主仓** quality 工作流的 `check_market_content.py`（跨仓工具，本仓不存在
# 同名脚本）会校验本仓 catalog 的 license 字段，两侧口径不一致会让「本地绿 = CI 绿」失效。
# 仍拒绝（命中即 CI 红）：AGPL-3.0-* / GPL-3.0-* / GPL-2.0-only / GPL-2.0-or-later /
# CC-BY-NC-* / LicenseRef-* / 自定义标识——强 copyleft 会引入与本项目 Apache-2.0
# 冲突的分发义务；NC 条款与开源生态冲突；非 SPDX 标识不可机器校验。
# 模板不适用本白名单（license 为数据/服务条款自由文本）。

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

OFFICIAL_PLUGIN_TYPES = {
    "source", "fetcher", "processor", "exporter", "auth_provider",
    "parser", "extractor", "transformer", "hook", "ui",
    "resource_provider", "view",
}

ALLOWED_PLUGIN_PERMISSIONS = {
    "records:read", "records:write", "artifacts:read", "artifacts:write",
    "responses:read", "responses:payload", "network:scoped", "temp:write",
    "files:read", "secrets:read", "state:read", "state:write",
    "resources:read", "surfaces:background", "render:local", "render:scripted",
}

# P2-3：宿主能力名白名单（镜像主仓 plugin_broker_contracts.CAPABILITY_VERSIONS 的键
# 集合；市场侧只校验「能力名存在于宿主契约」，版本上下限由主仓运行期裁决）。两侧由
# 跨仓断言锁名集合，任一漂移即红。
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

def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"清单必须是映射（mapping）: {path}")
    return data

def _require_contained(registry: Path, base: Path, rel: str, label: str) -> Path:
    """B02-014：文件引用解析后必须仍在 registry 内。

    P3-4 收紧：先拒绝绝对路径、反斜杠分隔与当前目录 ``.`` 段（与主仓
    ``_safe_relative_path`` 对齐宽度）；历史生产数据依赖 ``authors/../keys/x.pem``
    跨目录写法，``..`` 段暂保留但仍做最终落点包含性断言（存量迁移列入后续）。
    """
    rel_str = str(rel)
    if "\\" in rel_str:
        raise ValueError(f"{label} 使用反斜杠路径分隔符（须为 POSIX 相对路径）: {rel_str}")
    parts = rel_str.split("/")
    if Path(rel_str).is_absolute() or parts and parts[0] in ("", "/"):
        raise ValueError(f"{label} 不允许绝对路径: {rel_str}")
    if "." in parts:
        raise ValueError(f"{label} 包含当前目录段 '.': {rel_str}")
    resolved = (base / rel_str).resolve()
    if not resolved.is_relative_to(registry.resolve()):
        raise ValueError(f"{label} 解析后逃出 registry 根: {resolved}")
    return resolved


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
