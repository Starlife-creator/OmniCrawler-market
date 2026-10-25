#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""CI 工作流策略断言（P2-12 / P3-5 / 触发面）。

- 特性分支只经 pull_request 触发校验（既有规则）；
- 所有第三方 action 必须钉 40 字符 commit SHA，禁止浮动 `@main`/`@v*`/分支名；
- 跨仓 checkout 的 `ref:` 必须钉固定 SHA，禁止 `main`/`master`/分支漂移；
- 运行时依赖（cryptography / PyYAML）必须精确 `==` 钉版，禁止区间漂移。
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"^\s*uses:\s*([^@#\s]+)@([^\s#]+)")
REF_RE = re.compile(r"^\s*ref:\s*([^\s#]+)")
FLOATING_REFS = {"main", "master", "develop", "trunk", "head"}
PINNED_DEPS = ("cryptography", "PyYAML")


def _check_uses(lines: list[str], findings: list[str], source: str) -> None:
    for lineno, line in enumerate(lines, 1):
        match = USES_RE.match(line)
        if not match:
            continue
        action, ref = match.group(1), match.group(2)
        if action.startswith("./"):
            continue
        if not SHA_RE.match(ref):
            findings.append(f"{source}:{lineno} action 未钉 SHA: {action}@{ref}")


def _check_external_checkout_ref(lines: list[str], findings: list[str], source: str) -> None:
    for lineno, line in enumerate(lines, 1):
        match = REF_RE.match(line)
        if not match:
            continue
        ref = match.group(1).strip('"').strip("'")
        if ref in FLOATING_REFS or ref.startswith("refs/heads/"):
            findings.append(f"{source}:{lineno} 跨仓 checkout 浮动分支 ref: {ref}")
        elif not SHA_RE.match(ref):
            findings.append(f"{source}:{lineno} checkout ref 非固定 SHA: {ref}")


def _check_dependency_pins(lines: list[str], findings: list[str], source: str) -> None:
    for lineno, line in enumerate(lines, 1):
        if "pip install" not in line:
            continue
        for dep in PINNED_DEPS:
            pattern = re.compile(rf"{re.escape(dep)}\s*(==|>=|~=|<|>)")
            match = pattern.search(line)
            if not match:
                continue
            if match.group(1) != "==":
                findings.append(
                    f"{source}:{lineno} {dep} 未精确钉版（区间 {match.group(1)}）"
                )


def main() -> int:
    findings: list[str] = []
    validate = (WORKFLOWS / "validate.yml").read_text(encoding="utf-8")
    required = ("  push:\n    branches: [main]", "  pull_request:")
    missing = [fragment for fragment in required if fragment not in validate]
    if missing:
        findings.append(f"validate.yml 缺少触发面片段: {missing!r}")

    for path in sorted(WORKFLOWS.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        _check_uses(lines, findings, path.name)
        _check_external_checkout_ref(lines, findings, path.name)
        _check_dependency_pins(lines, findings, path.name)

    if findings:
        print("FAIL workflow policy:")
        for item in findings:
            print(f"  - {item}")
        return 1
    print("OK workflow policy: 触发面、action/checkout SHA 钉版与依赖精确钉版全部合规")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
