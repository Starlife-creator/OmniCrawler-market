#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# 本工具代码以 MIT License 授权（见 tools/LICENSE）。
"""catalog 签名工具（G1 第 25 轮；第 31 轮发布动作）。

catalog.json 由当前信任根冷签（catalog.json.sig）——客户端先验签 catalog
再信任其 sha256 清单，消除"篡改 catalog 改写 sha256 清单"的攻击面。

签名是运营者**本地半自动动作**：私钥离线持有，不进入 CI 环境；CI 只验
签名存在性与指纹。

用法：
  python tools/sign_catalog.py --maintainer-key /cold/path/plugin_signing_private.pem
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用维护者冷私钥签名 catalog.json")
    parser.add_argument("--maintainer-key", required=True, help="维护者冷私钥 PEM 路径（绝不入仓）")
    args = parser.parse_args(argv)

    private_path = Path(args.maintainer_key).expanduser()
    if not private_path.is_file():
        print(f"[FAIL] 私钥不存在: {private_path}")
        return 2

    catalog = _REGISTRY / "catalog.json"
    if not catalog.is_file():
        print("[FAIL] catalog.json 不存在（先运行 generate_catalog.py）")
        return 2

    # 自引导：复用主仓 signing 模块（Ed25519）
    main_src = _REGISTRY.parent / "OmniCrawler" / "src"
    if main_src.is_dir() and str(main_src) not in sys.path:
        sys.path.insert(0, str(main_src))
    from omnicrawler.plugins.signing import sign_file, verify_plugin

    sig_path = sign_file(catalog, private_path.read_bytes())
    print(f"[签名] 已写入 {sig_path.name}")

    # 验签回读（用市场仓信任根公钥）
    trust_pub = _REGISTRY / "keys" / "plugin_trust.pub.pem"
    ok, reason = verify_plugin(str(catalog), str(trust_pub))
    if not ok:
        print(f"[FAIL] 验签失败: {reason}")
        return 1
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    print(f"[验签] OK（catalog sha256={digest[:16]}…，签名覆盖含 sequence 防重放字段）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
