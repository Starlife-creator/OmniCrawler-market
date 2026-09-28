#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Require an explicit Signed-off-by trailer on every contribution commit.

★ 机器账号（GitHub 为 App/机器人保留的 `[bot]` 登录后缀）不适用：它们结构上
无法携带 `Signed-off-by`。对机器提交提签署要求只有一个后果——**误报**：
实测（2026-09-28）dependabot 的三个 `chore(ci): bump actions/*` PR
（#26/#27/#28）在触发面修好后立刻拿到校验，却**只因 DCO 这一步**永久卡在
blocked，而它们一个字符都没碰投稿面。

判定有两条，都可独立生效，且**跳过必须可见**（逐条打印原因）：

1. `--author`（PR 发起人登录）是机器账号 ⇒ 整份 PR 不适用。
   实测：dependabot 的提交 `%an` 是**人**（`starlife <zqx579683@outlook.com>`）、
   committer 是 `GitHub`，只有 PR 的 `user.login` 是 `dependabot[bot]`
   ⇒ 机器判据必须取 PR 发起人，不能取提交作者。
2. 单个提交的作者是机器账号 ⇒ 该提交不适用（保住「人类 PR 里夹了一个
   机器提交」这类情况，不让它把整份 PR 拖死）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

SIGN_OFF_RE = re.compile(r"(?mi)^Signed-off-by:\s+.+\s+<[^>]+>\s*$")
# `[bot]` 后缀是 GitHub 为 App 保留的登录名后缀，人类账号无法占用。
_BOT_SUFFIX_RE = re.compile(r"\[bot\]$")


def is_bot_account(identity: str | None) -> bool:
    """判断账号标识是否是机器账号；容忍 `name <email>` 形态。"""
    text = (identity or "").strip()
    if not text:
        return False
    name = text.split("<", 1)[0].strip()
    return bool(_BOT_SUFFIX_RE.search(name))


def _field(revision: str, field: str, cwd: str | None) -> str:
    return subprocess.run(
        ["git", "show", "-s", f"--format={field}", revision],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    ).stdout


def _revisions(base: str, head: str, cwd: str | None) -> list[str]:
    return subprocess.run(
        ["git", "rev-list", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    ).stdout.splitlines()


def review(
    base: str, head: str, *, author: str | None = None, cwd: str | None = None
) -> tuple[list[str], list[str], str | None]:
    """返回 (缺少签署的提交, 按机器账号跳过的提交, 整体豁免原因)。

    只有在没有任何豁免理由时，最后一项才为 None。
    """
    revisions = _revisions(base, head, cwd)
    if is_bot_account(author):
        return [], revisions, f"PR 发起人 {author} 是机器账号，贡献者签署要求不适用"
    missing: list[str] = []
    skipped: list[str] = []
    for revision in revisions:
        commit_author = _field(revision, "%an <%ae>", cwd)
        if is_bot_account(commit_author):
            skipped.append(revision)
        elif not SIGN_OFF_RE.search(_field(revision, "%B", cwd)):
            missing.append(revision)
    return missing, skipped, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument(
        "--author",
        default=None,
        help="PR 发起人登录名（github.event.pull_request.user.login）",
    )
    args = parser.parse_args(argv)

    missing, skipped, exempt_reason = review(args.base, args.head, author=args.author)

    # 跳过必须可见：不打印就等于静默放行。
    for revision in skipped:
        print(f"SKIP DCO: {revision[:12]} 作者是机器账号，不适用签署要求")
    if exempt_reason:
        print(f"SKIP DCO: {exempt_reason}")

    if missing:
        print(f"FAIL DCO: 以下提交缺少 Signed-off-by: {', '.join(r[:12] for r in missing)}")
        return 1

    if exempt_reason:
        print("OK DCO: 机器账号提交，无贡献者签署要求")
    else:
        print(f"OK DCO: 人类提交均已签署（跳过 {len(skipped)} 个机器提交）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
