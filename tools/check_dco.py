#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Require an explicit Signed-off-by trailer on every contribution commit.

★ 机器账号（GitHub 为 App/机器人保留的 `[bot]` 登录后缀）不适用：它们结构上
无法携带 `Signed-off-by`。对机器提交提签署要求只有一个后果——**误报**：
实测（2026-09-28）dependabot 的三个 `chore(ci): bump actions/*` PR
（#26/#27/#28）在触发面修好后立刻拿到校验，却**只因 DCO 这一步**永久卡在
blocked，而它们一个字符都没碰投稿面。

判定有三条，都可独立生效，且**跳过必须可见**（逐条打印原因）：

1. `--author`（PR 发起人登录）是机器账号 ⇒ 整份 PR 不适用。
   实测：dependabot 的提交 `%an` 是**人**（`starlife <zqx579683@outlook.com>`）、
   committer 是 `GitHub`，只有 PR 的 `user.login` 是 `dependabot[bot]`
   ⇒ 机器判据必须取 PR 发起人，不能取提交作者。
2. 单个提交的作者是机器账号 ⇒ 该提交不适用（保住「人类 PR 里夹了一个
   机器提交」这类情况，不让它把整份 PR 拖死）。
3. **合并提交（`parents > 1`）不适用**：它不携带任何**作者改动**（内容全部来自
   已被检查的父提交），而 GitHub 在网页/API 的「Update branch」会**代作者**生成一个
   合并提交 —— 作者**既没写它、也无法给它补 `Signed-off-by`**。
   实测（2026-09-30）：市场仓 #35 用了服务端 `PUT /pulls/35/update-branch` 之后 CI 直接
   `FAIL DCO: 以下提交缺少 Signed-off-by: 16e3915`，而那个提交是 GitHub 造的、**改不了**；
   唯一出路是本地把历史**线性化**再强推——把一次正常的「更新分支」变成返工。
   ⇒ 合并提交与机器账号同理：对它提签署要求**只有一个后果——误报**。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

SIGN_OFF_RE = re.compile(r"(?mi)^Signed-off-by:\s+.+\s+<[^>]+>\s*$")
# `[bot]` 后缀是 GitHub 为 App 保留的登录名后缀，人类账号无法占用。
_BOT_SUFFIX_RE = re.compile(r"\[bot\]$")
#: 列举候选提交时排掉的东西。合并提交不适用签署要求（理由见模块 docstring 第 3 条）。
#: ★ 抽成常量是为了让回归用例能**关掉它并断言转红**（证明这层豁免是承重的，
#:   而不是"恰好绿着好看"）——与 `is_bot_account` 的反向断言同一手法。
REVISION_EXCLUDE_ARGS: tuple[str, ...] = ("--no-merges",)


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
    """列出**需要签署**的候选提交（默认排除合并提交，见 `REVISION_EXCLUDE_ARGS`）。"""
    return subprocess.run(
        ["git", "rev-list", *REVISION_EXCLUDE_ARGS, f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    ).stdout.splitlines()


def merge_revision_count(base: str, head: str, cwd: str | None = None) -> int:
    """本区间内被排除掉的合并提交数（**跳过必须可见**，供调用方打印）。"""
    return int(
        subprocess.run(
            ["git", "rev-list", "--merges", "--count", f"{base}..{head}"],
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        ).stdout.strip()
        or "0"
    )


def review(
    base: str, head: str, *, author: str | None = None, cwd: str | None = None
) -> tuple[list[str], list[str], str | None]:
    """返回 (缺少签署的提交, 按机器账号跳过的提交, 整体豁免原因)。

    只有在没有任何豁免理由时，最后一项才为 None。

    ★ **合并提交不出现在返回值里**（既不在 `missing` 也不在 `skipped`）：它们由
    `_revisions` 排除，个数请用 `merge_revision_count()` 取——调用方**有责任把它打印出来**，
    否则就成了静默放行（本模块的第一原则是「跳过必须可见」）。
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
    merges = merge_revision_count(args.base, args.head)

    # 跳过必须可见：不打印就等于静默放行。
    for revision in skipped:
        print(f"SKIP DCO: {revision[:12]} 作者是机器账号，不适用签署要求")
    if merges:
        print(f"SKIP DCO: {merges} 个合并提交不适用签署要求（合并提交不携带作者改动）")
    if exempt_reason:
        print(f"SKIP DCO: {exempt_reason}")

    if missing:
        print(f"FAIL DCO: 以下提交缺少 Signed-off-by: {', '.join(r[:12] for r in missing)}")
        return 1

    if exempt_reason:
        print("OK DCO: 机器账号提交，无贡献者签署要求")
    else:
        print(f"OK DCO: 人类提交均已签署（跳过 {len(skipped)} 个机器提交、{merges} 个合并提交）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
