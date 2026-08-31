from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lumen_drift_plugin", PLUGIN_ROOT / "plugin.py")
assert SPEC is not None and SPEC.loader is not None
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


def test_metadata_uses_declarative_background_only() -> None:
    assert plugin.PLUGIN_METADATA["version"] == "0.2.0"
    assert plugin.PLUGIN_METADATA["plugin_types"] == ["ui"]
    assert plugin.PLUGIN_METADATA["execution_mode"] == "in_process"
    assert plugin.PLUGIN_METADATA["permissions"] == ["ui:background"]
    assert plugin.PLUGIN_METADATA["dependencies"] == []
    assert not plugin.PLUGIN_METADATA["domains"]


def test_registers_data_only_background_declaration() -> None:
    calls = []

    class Registry:
        def register_background(self, *args, **kwargs) -> None:
            calls.append((args, kwargs))

    plugin.register(Registry())
    assert calls == [
        (
            ("lumen-drift.ambient", "Lumen Drift · 流光漂移"),
            {"default_opacity": 0.24, "default_dim": 0.30},
        )
    ]
