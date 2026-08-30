#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Keep internal pull requests from running duplicate push and PR validation."""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    required = (
        "  push:\n    branches: [main]",
        "  pull_request:",
    )
    missing = [fragment for fragment in required if fragment not in workflow]
    if missing:
        print(f"FAIL workflow policy: missing {missing!r}")
        return 1
    print("OK workflow policy: feature branches validate through pull_request only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
