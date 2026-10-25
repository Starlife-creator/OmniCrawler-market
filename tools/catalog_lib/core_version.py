#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""P1-5：市场仓侧统一 semver 口径与核心版本兼容区间纯函数。

- 投稿 schema、构建清单、发现页预览共用同一套解析/区间/判定函数，避免三处各写一套正则；
- 主仓 subprocess 启动前的 ``compatible_core`` 预校验属于跨仓配套（主仓待落地），
  本模块只提供可被两侧复用的纯逻辑与负样例。

支持的约束写法（与主仓 plugin_packaging 产出的 ``>=x.y.z`` 基线兼容）：
``>=a.b.c``、``>=a.b.c,<d.e.f``、``<=d.e.f``、``==a.b.c``、``^a.b.c``、``~a.b.c``、
裸 ``a.b.c``（等价 ==）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
_CONSTRAINT_RE = re.compile(
    r"^(>=|<=|==|~=|~|\^|>|<)?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$"
)


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int
    pre: str = ""

    @classmethod
    def parse(cls, text: str) -> "SemVer":
        match = _VERSION_RE.fullmatch(str(text).strip())
        if not match:
            raise ValueError(f"非法 semver 版本号: {text!r}（期望 major.minor.patch）")
        major, minor, patch, pre = match.groups()
        return cls(int(major), int(minor), int(patch), pre or "")

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.pre}" if self.pre else base


@dataclass(frozen=True)
class CoreRange:
    """核心版本兼容区间；``upper`` 为排他上界，``upper_inclusive`` 为真时含上界。"""

    lower: SemVer | None
    upper: SemVer | None
    upper_inclusive: bool = False

    def contains(self, version: SemVer) -> bool:
        if self.lower is not None and version < self.lower:
            return False
        if self.upper is not None:
            if self.upper_inclusive:
                if version > self.upper:
                    return False
            elif version >= self.upper:
                return False
        return True


def _parse_single(text: str) -> tuple[str, SemVer]:
    match = _CONSTRAINT_RE.fullmatch(str(text).strip())
    if not match:
        raise ValueError(f"非法核心版本约束片段: {text!r}")
    comparator, version = match.groups()
    return comparator or "==", SemVer.parse(version)


def parse_compatible_core(declared: str) -> CoreRange:
    """解析 ``compatible_core`` 约束为 ``CoreRange``；格式非法即抛 ValueError。"""
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("compatible_core 不能为空")
    parts = [part.strip() for part in declared.split(",") if part.strip()]
    if not parts:
        raise ValueError("compatible_core 不能为空")
    lower: SemVer | None = None
    upper: SemVer | None = None
    upper_inclusive = False
    for part in parts:
        comparator, version = _parse_single(part)
        if comparator in (">=", ">"):
            if lower is None or version > lower:
                lower = version
        elif comparator in ("<=", "<"):
            if upper is None or version < upper:
                upper = version
                upper_inclusive = comparator == "<="
        elif comparator in ("==", "~="):
            lower = version if lower is None else max(lower, version)
            upper = version if upper is None else min(upper, version)
            upper_inclusive = True
        elif comparator == "^":
            # semver caret：1.2.3 ⇒ [1.2.3, 2.0.0)；0.2.3 ⇒ [0.2.3, 0.3.0)；0.0.3 ⇒ [0.0.3, 0.1.0)
            lower = version
            if version.major > 0:
                upper = SemVer(version.major + 1, 0, 0)
            elif version.minor > 0:
                upper = SemVer(0, version.minor + 1, 0)
            else:
                upper = SemVer(0, 0, version.patch + 1)
            upper_inclusive = False
        elif comparator == "~":
            # semver tilde：~1.2.3 ⇒ [1.2.3, 1.3.0)；~1.2 ⇒ [1.2.0, 1.3.0)
            lower = version
            upper = SemVer(version.major, version.minor + 1, 0)
            upper_inclusive = False
        else:
            raise ValueError(f"未支持的核心版本比较符: {comparator!r}")
    if lower is not None and upper is not None:
        if upper_inclusive and lower > upper:
            raise ValueError(f"compatible_core 区间矛盾: {declared!r}")
        if not upper_inclusive and lower >= upper:
            raise ValueError(f"compatible_core 区间矛盾: {declared!r}")
    return CoreRange(lower=lower, upper=upper, upper_inclusive=upper_inclusive)


def core_version_satisfies(declared: str, current: str) -> bool:
    """当前核心版本是否满足 ``compatible_core`` 约束（纯函数，供主仓安装期复用）。"""
    return parse_compatible_core(declared).contains(SemVer.parse(current))


def compatible_core_bounds(declared: str) -> tuple[str | None, str | None]:
    """导出 ``(min_core_version, max_core_version)`` 供清单/发现页预览；无上界返回 None。"""
    range_ = parse_compatible_core(declared)
    lower = str(range_.lower) if range_.lower is not None else None
    upper = str(range_.upper) if range_.upper is not None else None
    return lower, upper
