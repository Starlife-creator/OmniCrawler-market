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

实现布局（FINAL 长期债 #3）：逻辑按域拆分至 ``tools/catalog_lib/``
（common/schema/authors/tombstones/signing/build/rules/cli 八模块），
本文件为薄壳入口并 re-export 公共 API，对外行为零变化。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 自包含引导：把 tools/ 加入 sys.path，使 `import catalog_lib` 在
# 直接执行本脚本时可用（与旧单体实现等价）。
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from catalog_lib import *
from catalog_lib.cli import build_parser, check, main  # noqa: F401

# 兼容旧引用点：REGISTRY_DIR 曾定义于本文件（tools/ → 仓库根）
REGISTRY_DIR = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(main())
