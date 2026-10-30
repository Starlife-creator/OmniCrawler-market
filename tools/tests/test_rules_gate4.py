"""P1-4 / P2-10：门 4 基线缺失容错、版本倒退、license/execution_mode/权限集合
未升版变更拒绝，以及版本解析歧义容错负样例。"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog_lib.rules import _check_version_rules, _parse_version


def _plugin(pid: str, version: str, **overrides: dict) -> dict:
    base: dict = {
        "id": pid,
        "version": version,
        "license": "MIT",
        "execution_mode": "subprocess",
        "permissions": ["records:read"],
        "domains": [],
        "input_files": [],
        "dependencies": [],
        "required_capabilities": {},
    }
    base.update(overrides)
    return base


def test_missing_baseline_returns_warning_without_failure(tmp_path: Path) -> None:
    catalog = {"plugins": [_plugin("demo", "1.0.0")]}
    warnings = _check_version_rules(tmp_path, catalog, None)
    assert warnings and "基线" in warnings[0]


def test_version_regression_rejected(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("demo", "2.0.0")]}
    catalog = {"plugins": [_plugin("demo", "1.0.0")]}
    with pytest.raises(ValueError, match="版本倒退"):
        _check_version_rules(tmp_path, catalog, prev)


def test_license_change_without_bump_rejected(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("demo", "1.0.0", license="MIT")]}
    catalog = {"plugins": [_plugin("demo", "1.0.0", license="Apache-2.0")]}
    with pytest.raises(ValueError, match="license"):
        _check_version_rules(tmp_path, catalog, prev)


def test_execution_mode_change_without_bump_rejected(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("demo", "1.0.0", execution_mode="subprocess")]}
    catalog = {"plugins": [_plugin("demo", "1.0.0", execution_mode="in_process")]}
    with pytest.raises(ValueError, match="execution_mode"):
        _check_version_rules(tmp_path, catalog, prev)


def test_permission_expansion_without_bump_rejected(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("demo", "1.0.0")]}
    catalog = {"plugins": [
        _plugin("demo", "1.0.0", permissions=["records:read", "secrets:read"])
    ]}
    with pytest.raises(ValueError, match="permissions"):
        _check_version_rules(tmp_path, catalog, prev)


def test_domain_added_without_bump_rejected(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("demo", "1.0.0")]}
    catalog = {"plugins": [_plugin("demo", "1.0.0", domains=["api.example.com"])]}
    with pytest.raises(ValueError, match="domains"):
        _check_version_rules(tmp_path, catalog, prev)


def test_security_change_with_version_bump_passes(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("demo", "1.0.0")]}
    catalog = {"plugins": [
        _plugin("demo", "1.1.0", permissions=["records:read", "secrets:read"])
    ]}
    warnings = _check_version_rules(tmp_path, catalog, prev)
    assert warnings == []


def test_new_plugin_has_no_baseline_comparison(tmp_path: Path) -> None:
    prev = {"plugins": [_plugin("other", "1.0.0")]}
    catalog = {"plugins": [_plugin("demo", "0.1.0")]}
    assert _check_version_rules(tmp_path, catalog, prev) == []


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("1.0", "1.0.0", -1),
        ("1.0.0", "1.0.1", -1),
        ("2.0.0", "1.9.9", 1),
        ("1.0.0-beta", "1.0.0", 0),
        ("1", "1.0", -1),
    ],
)
def test_version_parse_ambiguity_tolerated(left: str, right: str, expected: int) -> None:
    result = (_parse_version(left) > _parse_version(right)) - (
        _parse_version(left) < _parse_version(right)
    )
    assert result == expected
