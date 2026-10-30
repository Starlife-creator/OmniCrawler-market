#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P1-2 离线快照工具：导出自包含快照、复核签名与新鲜度（市场仓侧）。

用法：
  python tools/snapshot_catalog.py export --dest /tmp/market-snapshot
  python tools/snapshot_catalog.py verify --snapshot /tmp/market-snapshot \
      [--max-age-hours 720] [--require-fresh]

缺 catalog.json.sig 或签名无效即 fail-closed 拒绝；陈旧默认告警，--require-fresh 阻断。
主仓内置 market/ 捆绑快照打包流程属跨仓主仓侧配套。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1]
if str(REGISTRY / "tools") not in sys.path:
    sys.path.insert(0, str(REGISTRY / "tools"))

from catalog_lib.snapshot import DEFAULT_MAX_AGE_HOURS, export_snapshot, verify_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线快照导出与签名/新鲜度复核")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="从在线目录导出自包含离线快照")
    export.add_argument("--dest", required=True, help="快照输出目录")

    verify = sub.add_parser("verify", help="复核快照签名与新鲜度")
    verify.add_argument("--snapshot", required=True, help="快照目录")
    verify.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    verify.add_argument(
        "--require-fresh", action="store_true", help="陈旧快照直接阻断（默认仅告警）"
    )

    args = parser.parse_args(argv)
    if args.command == "export":
        dest = export_snapshot(REGISTRY, Path(args.dest))
        print(f"[OK] 离线快照已导出: {dest}")
        return 0

    ok, findings = verify_snapshot(
        Path(args.snapshot),
        max_age_hours=args.max_age_hours,
        require_fresh=args.require_fresh,
    )
    for finding in findings:
        print(f"[{'WARN' if finding.startswith('warning: ') else 'FAIL'}] {finding[9:] if finding.startswith('warning: ') else finding}")
    if ok:
        print(f"[OK] 快照签名有效（{len(findings)} 条告警）")
        return 0
    print("[FAIL] 快照复核未通过（fail-closed，离线索引不可信）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
