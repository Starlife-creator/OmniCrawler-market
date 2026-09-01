from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CALLS: list[tuple[str, dict]] = []


def _capability(operation: str, payload: dict | None = None) -> dict:
    body = dict(payload or {})
    CALLS.append((operation, body))
    if operation == "resources.enumerate":
        return {"items": [
            {"relative": "123/project.json", "kind": "file"},
            {"relative": "123/index.html", "kind": "file"},
            {"relative": "loose.png", "kind": "file"},
            {"relative": "scene/scene.pkg", "kind": "file"},
        ]}
    if operation == "resources.read":
        project = {"title": "Aurora Clock", "type": "web", "file": "index.html"}
        return {"content_b64": base64.b64encode(json.dumps(project).encode()).decode()}
    if operation in {"render.html.snapshot", "render.html.live.start"}:
        return {"handle": "render:test"}
    return {"active": True}


sdk = types.ModuleType("omnicrawler_sdk")
sdk.call = _capability
sys.modules["omnicrawler_sdk"] = sdk
SPEC = importlib.util.spec_from_file_location("lumen_drift_plugin", PLUGIN_ROOT / "plugin.py")
assert SPEC is not None and SPEC.loader is not None
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


def setup_function() -> None:
    CALLS.clear()
    plugin._state.update({
        "handle": "", "items": [], "opacity": 24, "dim": 30,
        "fit": "cover", "html_mode": "snapshot",
    })


def test_metadata_uses_isolated_declarative_contract() -> None:
    assert plugin.PLUGIN_METADATA["version"] == "0.3.0"
    assert plugin.PLUGIN_METADATA["plugin_types"] == ["resource_provider", "view"]
    assert plugin.PLUGIN_METADATA["execution_mode"] == "subprocess"
    assert "surfaces:background" in plugin.PLUGIN_METADATA["permissions"]
    assert not plugin.PLUGIN_METADATA["domains"]


def test_view_offers_explicit_auto_discovery_and_manual_picker() -> None:
    view = plugin.handle("view.describe", {})["view"]
    auto = next(item for item in view["components"] if item["id"] == "wallpaper-engine-folder")
    manual = next(item for item in view["components"] if item["id"] == "manual-folder")
    assert auto["discovery_kind"] == "steam_workshop"
    assert auto["discovery_id"] == "431960"
    assert "discovery_kind" not in manual


def test_scan_recognizes_wallpaper_project_and_loose_media() -> None:
    response = plugin.handle("view.action", {
        "action": "source-selected", "payload": {"resource_handle": "resource:test"},
    })
    labels = [item["label"] for item in plugin._state["items"]]
    assert labels == ["Aurora Clock", "loose.png"]
    assert response["message"] == "发现 2 个可用资源"
    assert all("resource:test" not in str(item) for item in response["view"]["components"])


def test_html_is_static_by_default_and_uses_opaque_render_result() -> None:
    plugin._state["handle"] = "resource:test"
    plugin._state["items"] = [{
        "id": "123/index.html", "label": "Aurora Clock", "subtitle": "web", "supported": True,
    }]
    plugin.handle("view.action", {
        "action": "play-resource", "payload": {"item_id": "123/index.html"},
    })
    render = next(payload for name, payload in CALLS if name == "render.html.snapshot")
    surface = next(payload for name, payload in CALLS if name == "surface.background.set")
    assert render["scripted"] is False
    assert surface == {"render_handle": "render:test"}


def test_live_render_requires_explicit_user_selection() -> None:
    plugin.handle("view.action", {
        "action": "configure-html-mode", "payload": {"value": "live"},
    })
    assert plugin._state["html_mode"] == "live"
    plugin._state["handle"] = "resource:test"
    plugin._state["items"] = [{
        "id": "123/index.html", "label": "Aurora", "subtitle": "web", "supported": True,
    }]
    plugin.handle("view.action", {
        "action": "play-resource", "payload": {"item_id": "123/index.html"},
    })
    assert any(name == "render.html.live.start" for name, _payload in CALLS)
