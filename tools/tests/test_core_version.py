"""P1-5 市场仓侧 semver 口径统一：解析、区间、兼容判定与边界导出负样例。"""
from __future__ import annotations

import pytest

from catalog_lib.core_version import (
    CoreRange,
    SemVer,
    compatible_core_bounds,
    core_version_satisfies,
    parse_compatible_core,
)


# --- 解析 --------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["0.11.2", "1.0.0", "2.3.4-rc.1", "10.20.30"],
)
def test_semver_parse_valid(text: str) -> None:
    version = SemVer.parse(text)
    assert str(version) == text.split("-")[0] if "-" not in text else text


@pytest.mark.parametrize("bad", ["1", "1.2", "v1.2.3", "1.2.x", "latest", ""])
def test_semver_parse_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        SemVer.parse(bad)


# --- 区间解析与兼容判定 --------------------------------------------------------
def test_gte_lower_bound_accepted() -> None:
    assert core_version_satisfies(">=0.11.2", "0.11.2")
    assert core_version_satisfies(">=0.11.2", "1.0.0")
    assert not core_version_satisfies(">=0.11.2", "0.11.1")


def test_exclusive_upper_bound_rejected() -> None:
    assert core_version_satisfies(">=1.2.0,<2.0.0", "1.9.9")
    assert not core_version_satisfies(">=1.2.0,<2.0.0", "2.0.0")


def test_inclusive_upper_bound_accepted() -> None:
    assert core_version_satisfies(">=1.2.0,<=1.2.3", "1.2.3")
    assert not core_version_satisfies(">=1.2.0,<=1.2.3", "1.2.4")


def test_caret_range_semantics() -> None:
    assert core_version_satisfies("^1.2.3", "1.2.3")
    assert core_version_satisfies("^1.2.3", "1.9.9")
    assert not core_version_satisfies("^1.2.3", "2.0.0")
    # 0.x 版本 caret 收紧到 minor
    assert core_version_satisfies("^0.2.3", "0.2.9")
    assert not core_version_satisfies("^0.2.3", "0.3.0")


def test_tilde_range_semantics() -> None:
    assert core_version_satisfies("~1.2.3", "1.2.9")
    assert not core_version_satisfies("~1.2.3", "1.3.0")


def test_exact_version_range() -> None:
    assert core_version_satisfies("==1.2.3", "1.2.3")
    assert not core_version_satisfies("==1.2.3", "1.2.4")
    assert core_version_satisfies("1.2.3", "1.2.3")


@pytest.mark.parametrize(
    "bad",
    ["latest", ">=foo", "1.2.x", "^abc", ">=2.0.0,<1.0.0", ">=1.0.0,<=0.9.0"],
)
def test_compatible_core_invalid_format_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_compatible_core(bad)


def test_bounds_exported() -> None:
    assert compatible_core_bounds(">=0.11.2") == ("0.11.2", None)
    assert compatible_core_bounds(">=1.2.0,<2.0.0") == ("1.2.0", "2.0.0")
    assert compatible_core_bounds("==1.2.3") == ("1.2.3", "1.2.3")


def test_range_contains_ordering() -> None:
    range_ = CoreRange(lower=SemVer.parse("1.2.0"), upper=SemVer.parse("2.0.0"))
    assert range_.contains(SemVer.parse("1.2.0"))
    assert not range_.contains(SemVer.parse("0.9.0"))
