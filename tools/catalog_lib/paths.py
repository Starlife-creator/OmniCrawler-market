#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P2-7：市场仓自包含路径安全与 ID 正则共享实现。

投稿器（validate_submission.py）保持自包含不 import 市场库，故其中保留一份
镜像副本；``check_plugin_schema_policy.py`` 对两侧正则/规则做相等断言锁漂移。
主仓 ``package_importer`` 复用同一套纯函数属跨仓配套（主仓待落地）。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
# 层级模板 ID：段内允许单连字符/下划线，禁止 ``--`` 连续连字符（目录名转义符）。
TEMPLATE_ID_RE = re.compile(
    r"^[a-z](?:[a-z0-9]|_[a-z0-9]|-[a-z0-9])*"
    r"(?:/[a-z](?:[a-z0-9]|_[a-z0-9]|-[a-z0-9])*)*$"
)
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def safe_relative_path(value: str) -> PurePosixPath:
    """严格 POSIX 安全相对路径（对齐主仓 ``_safe_relative_path``）。

    拒绝：空串、反斜杠、绝对路径、Windows 盘符前缀、``..`` 段、``.`` 段。
    段检查基于原始字符串切分（避免 PurePosixPath 归一化吞掉 ``./``）。
    """
    raw = str(value)
    if not raw or "\\" in raw:
        raise ValueError(f"非法相对路径: {value!r}")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"非法相对路径（绝对路径/盘符）: {value!r}")
    parts = raw.split("/")
    if ".." in parts or "." in parts:
        raise ValueError(f"非法相对路径（含上级/当前目录段）: {value!r}")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ValueError(f"非法相对路径: {value!r}")
    return path


def template_dir_name_to_id(name: str) -> str:
    """目录名 ``social--market--x`` ⇒ catalog ID ``social/market/x``（P3-6 冲突归一）。"""
    return name.replace("--", "/")


def template_id_to_dir_name(package_id: str) -> str:
    """catalog ID ``social/market/x`` ⇒ 目录名 ``social--market--x``。"""
    return package_id.replace("/", "--")


__all__ = [
    "PLUGIN_ID_RE",
    "TEMPLATE_ID_RE",
    "USERNAME_RE",
    "DOMAIN_RE",
    "safe_relative_path",
    "template_dir_name_to_id",
    "template_id_to_dir_name",
]
