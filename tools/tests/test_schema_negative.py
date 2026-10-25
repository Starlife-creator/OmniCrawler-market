"""P1-4：schema 负样例补充——未知权限、能力版本形态、非正整数 state schema、
域名畸形、类型非列表、未知扩展点、许可缺失等拒绝路径。"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog_lib.schema import _entry_from_yaml


def _baseline() -> dict:
    return {
        "id": "demo-processor",
        "name": "Demo",
        "version": "1.0.0",
        "publisher": "starlife",
        "category": "source",
        "summary": "demo",
        "description_file": "plugins/demo/listing.md",
        "plugin_file": "plugins/demo/plugin.py",
        "signature_file": "plugins/demo/plugin.py.sig",
        "signature_algorithm": "ed25519",
        "permissions": ["records:read"],
        "compatible_core": ">=1.0.0",
        "license": "MIT",
        "plugin_types": ["processor"],
    }


def _reject(manifest: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _entry_from_yaml(manifest, Path("plugins/demo/market.yaml"))


def test_unknown_permission_rejected() -> None:
    manifest = _baseline()
    manifest["permissions"] = ["evil:read"]
    _reject(manifest, "未知权限")


def test_permissions_must_be_list() -> None:
    manifest = _baseline()
    manifest["permissions"] = "records:read"
    _reject(manifest, "permissions 必须是字符串列表")


def test_capability_version_shape_malformed_rejected() -> None:
    manifest = _baseline()
    manifest["required_capabilities"] = {"network.fetch": ">=zero"}
    _reject(manifest, "required_capabilities")


def test_unknown_capability_name_rejected() -> None:
    manifest = _baseline()
    manifest["required_capabilities"] = {"system.unknown": "1"}
    _reject(manifest, "宿主不支持的能力")


@pytest.mark.parametrize("bad_value", [0, -1, "2", 1.5])
def test_state_schema_version_must_be_positive_integer(bad_value: object) -> None:
    manifest = _baseline()
    manifest["state_schema_version"] = bad_value
    _reject(manifest, "state_schema_version")


def test_domains_must_be_string_list() -> None:
    manifest = _baseline()
    manifest["domains"] = "api.example.com"
    _reject(manifest, "domains 必须是域名非空字符串列表")


def test_plugin_types_must_be_nonempty_list() -> None:
    manifest = _baseline()
    manifest["plugin_types"] = []
    _reject(manifest, "plugin_types 必须是非空字符串列表")


def test_unknown_plugin_type_rejected() -> None:
    manifest = _baseline()
    manifest["plugin_types"] = ["rocket"]
    _reject(manifest, "未知运行扩展点")


def test_missing_license_rejected() -> None:
    manifest = _baseline()
    del manifest["license"]
    _reject(manifest, "缺少必填字段")


def test_license_not_in_spdx_allowlist_rejected() -> None:
    manifest = _baseline()
    manifest["license"] = "GPL-3.0-only"
    _reject(manifest, "SPDX 白名单")


def test_unknown_field_rejected() -> None:
    manifest = _baseline()
    manifest["release_channel"] = "beta"
    _reject(manifest, "未知字段")


def test_execution_mode_must_be_known_enum() -> None:
    manifest = _baseline()
    manifest["execution_mode"] = "kernel"
    _reject(manifest, "execution_mode 非法")
