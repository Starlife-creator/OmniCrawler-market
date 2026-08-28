#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Require an explicit Signed-off-by trailer on every contribution commit."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    revisions = subprocess.run(
        ["git", "rev-list", f"{args.base}..{args.head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    missing: list[str] = []
    for revision in revisions:
        message = subprocess.run(
            ["git", "show", "-s", "--format=%B", revision],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        if not re.search(r"(?mi)^Signed-off-by:\s+.+\s+<[^>]+>\s*$", message):
            missing.append(revision[:12])
    if missing:
        print(f"FAIL DCO: 以下提交缺少 Signed-off-by: {', '.join(missing)}")
        return 1
    print(f"OK DCO: {len(revisions)} 个投稿提交均由贡献者明确签署")
    return 0


if __name__ == "__main__":
    sys.exit(main())
