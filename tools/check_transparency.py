#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""透明日志 CI 复核（P3-11 路径归一 + P2-5 v2 哈希链重放）。

- JSON 合法、路径字段无反斜杠（P3-11）；
- v2 条目 prev_hash 链接续、seq 单调、entry_hash 可复算（P2-5）；
- v1 legacy 条目不参与链计算；v2 链之后混入 v1 条目即报 schema 混存。

退出码：0 通过；1 发现违规。
"""

from __future__ import annotations

import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1]
if str(REGISTRY / "tools") not in sys.path:
    sys.path.insert(0, str(REGISTRY / "tools"))

from catalog_lib.transparency import check_transparency_log, verify_transparency_chain


def main() -> int:
    log = REGISTRY / "signing_transparency.jsonl"
    findings = check_transparency_log(log) + verify_transparency_chain(log)
    if findings:
        print("FAIL transparency log:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("OK transparency log: POSIX 路径、JSON 结构与 v2 哈希链全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
