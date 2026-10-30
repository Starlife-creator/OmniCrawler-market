"""P3-9：目录层可选静态契约字段透传与格式校验；运行时字段不得进入目录条目。"""
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


def test_optional_static_fields_passthrough() -> None:
    manifest = _baseline()
    manifest.update({
        "api_version": "1.2.3",
        "min_core_version": "0.11.2",
        "max_core_version": "0.15.0",
        "source_url": "https://example.com/demo",
        "fallback": "records:read",
        "optional_dependencies": [{"name": "openpyxl", "version": "3.1", "license": "MIT"}],
        "contract_shape": "records-processor",
    })
    entry = _entry_from_yaml(manifest, Path("plugins/demo/plugin.yaml"))
    assert entry["api_version"] == "1.2.3"
    assert entry["min_core_version"] == "0.11.2"
    assert entry["max_core_version"] == "0.15.0"
    assert entry["source_url"] == "https://example.com/demo"


def test_min_core_greater_than_max_rejected() -> None:
    manifest = _baseline()
    manifest.update({"min_core_version": "2.0.0", "max_core_version": "1.0.0"})
    with pytest.raises(ValueError, match="min_core_version 大于 max_core_version"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


def test_bad_source_url_rejected() -> None:
    manifest = _baseline()
    manifest["source_url"] = "ftp://example.com/x"
    with pytest.raises(ValueError, match="source_url"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


def test_optional_dependency_entry_missing_name_rejected() -> None:
    manifest = _baseline()
    manifest["optional_dependencies"] = [{"version": "1.0.0"}]
    with pytest.raises(ValueError, match="optional_dependencies"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


@pytest.mark.parametrize("runtime_only_field", ["config_schema", "resource_limits"])
def test_runtime_only_fields_not_allowed_in_catalog(runtime_only_field: str) -> None:
    manifest = _baseline()
    manifest[runtime_only_field] = {"type": "object"}
    with pytest.raises(ValueError, match="未知字段"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


def test_bad_api_version_rejected() -> None:
    manifest = _baseline()
    manifest["api_version"] = "latest"
    with pytest.raises(ValueError, match="非法 semver"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))
