#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""投稿脚手架（§十 P1）：为第三方作者生成一份可起步的插件源目录。

生成物（<output>/）：plugin.yaml（与在线插件同规格的骨架）、plugin.py（含
PLUGIN_METADATA 的存根）、listing.md（功能说明骨架）、README.md（下一步指引）。
生成后请按 CONTRIBUTING.md 与 docs/PLUGIN_CONTRACT.md 实现，再走 creator-sign 投稿。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_PLUGIN_YAML = """\
id: {id}
name: {name}
version: {version}
api_version: 1
description: {description}
plugin_types: [{plugin_types}]
category: {category}
tags: []
permissions: []
required_capabilities: {{}}
domains: []
input_files: []
dependencies: []
license: {license}
execution_mode: subprocess
min_core_version: 0.12.0
"""

_PLUGIN_PY = '''\
"""{name} —— 由投稿脚手架生成的存根，请实现真实逻辑。"""

# ★ 字段必须与 plugin.yaml 保持一致（审核时会做一致性校验）。
PLUGIN_METADATA = {{
    "name": "{name}",
    "version": "{version}",
    "api_version": 1,
    "plugin_types": {plugin_types!r},
    "permissions": [],
    "required_capabilities": {{}},
    "execution_mode": "subprocess",
}}

# ★ 请按 docs/PLUGIN_CONTRACT.md 实现插件入口与声明一致性
#   （execution_mode=subprocess 不得 import omnicrawler 核心）。
'''

_LISTING_MD = """\
# {name}

{description}

## 功能

（在此描述插件功能与用法）
"""

_README_MD = """\
# 投稿目录：{id}

下一步（详见 CONTRIBUTING.md 与 docs/PLUGIN_CONTRACT.md）：

1. 实现 `plugin.py`（本存根只有 PLUGIN_METADATA，入口逻辑需按契约补齐）；
2. 核对 `plugin.yaml` 与 `plugin.py` 的 `PLUGIN_METADATA` 声明一致；
3. 用主仓 CLI 做创作者签名并打包（`creator-sign`），得到可私下分享的签名包；
4. 自主选择是否投稿市场（投稿会经过静态验证与维护者复审）。
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成插件投稿骨架目录")
    parser.add_argument("--id", required=True, help="插件 ID（小写字母/数字/连字符）")
    parser.add_argument("--name", required=True, help="显示名")
    parser.add_argument("--publisher", required=True, help="发布者（与作者登记一致）")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--description", required=True, help="一句话描述")
    parser.add_argument("--plugin-types", default="resource_provider")
    parser.add_argument("--category", default="utility")
    parser.add_argument("--license", default="MIT")
    parser.add_argument("--output", default=None, help="输出目录（默认 submissions/<id>）")
    args = parser.parse_args(argv)

    if not _ID_RE.match(args.id):
        print(f"[FAIL] 非法插件 ID（须匹配 {_ID_RE.pattern}）: {args.id}")
        return 2
    out = Path(args.output) if args.output else Path("submissions") / args.id
    if out.exists():
        print(f"[FAIL] 目录已存在: {out}")
        return 2
    out.mkdir(parents=True)

    fmt = {
        "id": args.id,
        "name": args.name,
        "version": args.version,
        "description": args.description,
        "plugin_types": args.plugin_types,
        "category": args.category,
        "license": args.license,
    }
    (out / "plugin.yaml").write_text(_PLUGIN_YAML.format(**fmt), encoding="utf-8")
    (out / "plugin.py").write_text(_PLUGIN_PY.format(**fmt), encoding="utf-8")
    (out / "listing.md").write_text(_LISTING_MD.format(**fmt), encoding="utf-8")
    (out / "README.md").write_text(_README_MD.format(**fmt), encoding="utf-8")
    print(f"[OK] 骨架已生成：{out.resolve()}")
    print("下一步：实现 plugin.py → creator-sign 签名打包 → 按 CONTRIBUTING.md 投稿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
