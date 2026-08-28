#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""check 编排、argparse 入口与 main。（自 generate_catalog.py 机械拆分，逻辑未改）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .authors import *
from .build import *
from .common import *
from .rules import *
from .schema import *
from .signing import *
from .tombstones import *


def check(
    registry: Path,
    *,
    trust_source: str | None = None,
    prev_catalog: str | None = None,
) -> int:
    """CI 门禁：校验 YAML 源合法、与 catalog.json 一致、签名有效（fail-closed）。

    V1：缺失创作者签名的插件打印警告（不失败）；V2 将升级为强制（P3-1）。
    门 4（Phase 1）：license/execution_mode 变更必须伴随版本递增——基线取
    --prev-catalog 或 git 历史中的上一版 catalog.json。
    """
    try:
        catalog = build_catalog(registry)
        _check_consistency(registry, catalog)
        gate4_warnings = _check_version_rules(
            registry, catalog, _load_prev_catalog(registry, prev_catalog)
        )
        warnings = _verify_signatures(registry, catalog, trust_source)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL registry: {exc}")
        return 1
    for warning in gate4_warnings:
        print(f"  ! {warning}")
    for warning in warnings:
        print(f"  ! {warning}")
    plugins = len(catalog["plugins"])
    templates = len(catalog["templates"])
    print(f"OK registry: {plugins} 个插件 + {templates} 个模板清单一致，签名校验完成")
    return 0


def publish_check(
    registry: Path,
    *,
    trust_source: str | None = None,
    prev_catalog: str | None = None,
) -> int:
    """Strict main-branch invariant: every visible item is distributable."""
    try:
        catalog = build_catalog(registry)
        _check_consistency(registry, catalog)
        _check_version_rules(registry, catalog, _load_prev_catalog(registry, prev_catalog))
        _verify_signatures(
            registry,
            catalog,
            trust_source,
            require_maintainer=True,
        )
        _verify_catalog_signature(registry, trust_source)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL publish: {exc}")
        return 1
    print(
        f"OK publish: {len(catalog['plugins'])} 个插件 + "
        f"{len(catalog['templates'])} 个模板均具维护者背书，catalog 签名有效"
    )
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_catalog",
        description="从 plugins/*/plugin.yaml 与 templates/*/template.yaml 聚合生成或校验 catalog.json",
    )
    parser.add_argument("--registry", default=str(REGISTRY_DIR), help="registry 目录（默认本工具所在生态根）")
    parser.add_argument("--publisher", default=None, help="catalog 顶层 publisher（默认取首个插件发布者）")
    parser.add_argument(
        "--trust",
        default=None,
        help="信任根公钥 PEM 路径（默认 keys/plugin_trust.pub.pem）",
    )
    parser.add_argument("--check", action="store_true", help="只校验不写盘（CI 门禁）")
    parser.add_argument(
        "--publish-check",
        action="store_true",
        help="正式发布门禁：强制维护者签名与当前 catalog.json.sig",
    )
    parser.add_argument(
        "--prev-catalog",
        default=None,
        help="门 4 基线：上一版 catalog.json 路径（默认取 git 历史 HEAD^ 版本）",
    )
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = Path(args.registry)
    if not registry.is_dir():
        print(f"FAIL registry 目录不存在: {registry}")
        return 1
    if args.check:
        return check(registry, trust_source=args.trust, prev_catalog=args.prev_catalog)
    if args.publish_check:
        return publish_check(
            registry, trust_source=args.trust, prev_catalog=args.prev_catalog
        )
    try:
        output = generate(registry, publisher_override=args.publisher)
    except (ValueError, OSError) as exc:
        print(f"FAIL 生成 catalog.json: {exc}")
        return 1
    print(f"OK 已生成: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    name for name in list(globals())
    if name not in {'subprocess', 'annotations', 'sys', 'argparse', 'base64', 'timezone', 'yaml', 'datetime', 'Any', 'hashlib', 'Path', 're', 'json'}
]
