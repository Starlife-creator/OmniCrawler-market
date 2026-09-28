#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""DCO 门禁的轻量回归，不依赖第三方测试框架。

两个方向都必须钉住，缺一即「护栏只绿不红」：

* 机器账号没有签署**不该**红 —— 否则 dependabot 的依赖升级 PR 会永久卡在
  blocked（实测 #26/#27/#28：只差 DCO 这一步）；
* 人类提交没有签署**必须**红 —— 否则豁免会泄漏成「谁都不用签」。

并且验证**豁免是承重的**：把机器账号判定关掉后，原来绿的用例必须转红。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import check_dco


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=alice",
            "-c",
            "user.email=alice@example.com",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _commit(root: Path, message: str, *, sign_off: bool) -> str:
    (root / "f.txt").write_text(message, encoding="utf-8")
    _git(root, "add", "f.txt")
    body = message
    if sign_off:
        body = f"{message}\n\nSigned-off-by: Alice <alice@example.com>"
    _git(root, "commit", "-m", body)
    return _git(root, "rev-parse", "HEAD")


def main() -> int:
    # ① 机器账号判定本身：既不能漏判，也不能把普通名字误判成机器人。
    for login in ("dependabot[bot]", "github-actions[bot]", "dependabot[bot] <x@y.z>"):
        assert check_dco.is_bot_account(login), f"漏判机器账号: {login}"
    for login in ("robot", "bots", "bot", "starlife", "alice <a@b.com>", "", None):
        assert not check_dco.is_bot_account(login), f"误判人类账号: {login!r}"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _git(root, "init")
        base = _commit(root, "base", sign_off=True)
        unsigned = _commit(root, "human unsigned", sign_off=False)

        # ② 人类未签署 ⇒ 必须判红。
        missing, skipped, reason = check_dco.review(base, unsigned, author="alice", cwd=root)
        assert missing == [unsigned], f"人类未签署未被判红: {missing!r}"
        assert skipped == [] and reason is None

        # ③ 机器账号发起 ⇒ 不该判红，但跳过原因必须可见。
        missing, skipped, reason = check_dco.review(
            base, unsigned, author="dependabot[bot]", cwd=root
        )
        assert missing == [], f"机器账号仍被判红: {missing!r}"
        assert skipped == [unsigned] and reason, "豁免未可见（静默放行）"

        # ④ ★ 反向：关掉机器账号判定后，③ 必须转红 —— 证明豁免承重。
        original = check_dco.is_bot_account
        check_dco.is_bot_account = lambda *a, **k: False  # type: ignore[assignment]
        try:
            missing, _, _ = check_dco.review(
                base, unsigned, author="dependabot[bot]", cwd=root
            )
            assert missing == [unsigned], "关掉豁免后本应转红，说明豁免没有起作用"
        finally:
            check_dco.is_bot_account = original

        # ⑤ 已签署的提交，在两种身份下都必须过。
        signed = _commit(root, "human signed", sign_off=True)
        for author in ("alice", "dependabot[bot]"):
            missing, _, _ = check_dco.review(unsigned, signed, author=author, cwd=root)
            assert missing == [], f"{author} 下已签署提交被判红: {missing!r}"

    print("OK DCO regression: 机器账号不适用签署；人类未签署仍判红；关掉豁免即转红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
