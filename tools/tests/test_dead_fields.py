"""P2-1：release_channel / review_depth / gates_evidence 死字段已从 schema 移除。"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog_lib.common import _ENTRY_KEYS
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


@pytest.mark.parametrize("dead_field", ["release_channel", "review_depth", "gates_evidence"])
def test_dead_field_rejected_as_unknown(dead_field: str) -> None:
    manifest = _baseline()
    manifest[dead_field] = "beta"
    with pytest.raises(ValueError, match="未知字段"):
        _entry_from_yaml(manifest, Path("plugins/demo/plugin.yaml"))


def test_dead_fields_absent_from_schema_whitelist() -> None:
    assert "release_channel" not in _ENTRY_KEYS
    assert "review_depth" not in _ENTRY_KEYS
    assert "gates_evidence" not in _ENTRY_KEYS
