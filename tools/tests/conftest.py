"""市场工具链用例的共用夹具。"""
from __future__ import annotations

from pathlib import Path

import pytest


def _can_make_symlink(probe_dir: Path) -> bool:
    target = probe_dir / "probe-target"
    target.write_text("x", encoding="utf-8")
    try:
        (probe_dir / "probe-link").symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    return True


@pytest.fixture
def require_symlink(tmp_path: Path) -> None:
    """本平台无法创建符号链接时跳过用例。

    Windows 未开开发者模式时 `symlink_to` 抛 WinError 1314（客户端没有所需的特权），
    这是权限限制而不是被测代码的缺陷；用运行时探测而不是 `sys.platform` 判断，
    开着开发者模式的 Windows 仍会真正跑这条负样例。
    """
    if not _can_make_symlink(tmp_path):
        pytest.skip("本平台不允许创建符号链接（Windows 需开发者模式或管理员权限）")
