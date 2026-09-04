from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

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
        "handle": "", "items": [], "selected_id": "", "opacity": 100,
        "panel_opacity": 88, "dim": 15, "blur": 4, "fit": "cover",
        "scope": "workspace", "preset": "balanced", "paused": False,
        "html_mode": "snapshot", "filter": "all", "active": False, "now_playing": "",
    })


def test_metadata_uses_isolated_declarative_contract() -> None:
    assert plugin.PLUGIN_METADATA["version"] == "0.4.0"
    assert plugin.PLUGIN_METADATA["plugin_types"] == ["resource_provider", "view"]
    assert plugin.PLUGIN_METADATA["execution_mode"] == "subprocess"
    assert "surfaces:background" in plugin.PLUGIN_METADATA["permissions"]
    assert not plugin.PLUGIN_METADATA["domains"]
    assert plugin.PLUGIN_METADATA["required_capabilities"]["surface.background.set"] == ">=2"


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
    assert response["message"] == "发现 2 个资源，其中 2 个可尝试呈现"
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


def test_background_controls_use_host_v2_surface_vocabulary() -> None:
    view = plugin.handle("view.describe", {})["view"]
    component_ids = {item["id"] for item in view["components"]}
    assert {"preset", "scope", "panel-opacity", "blur", "pause"} <= component_ids

    response = plugin.handle("view.action", {
        "action": "configure-preset", "payload": {"value": "immersive"},
    })
    assert plugin._state["panel_opacity"] == 74
    assert plugin._state["dim"] == 8
    assert ("surface.background.configure", {"preset": "immersive"}) in CALLS
    assert response["view"]["view_id"] == "lumen-drift.main"


def test_next_previous_and_pause_control_selected_resource() -> None:
    plugin._state["handle"] = "resource:test"
    plugin._state["items"] = [
        {"id": "one.png", "label": "One", "subtitle": "image", "supported": True},
        {"id": "two.png", "label": "Two", "subtitle": "image", "supported": True},
    ]
    plugin.handle("view.action", {"action": "next-resource", "payload": {}})
    assert plugin._state["selected_id"] == "one.png"
    plugin.handle("view.action", {"action": "next-resource", "payload": {}})
    assert plugin._state["selected_id"] == "two.png"
    plugin.handle("view.action", {"action": "previous-resource", "payload": {}})
    assert plugin._state["selected_id"] == "one.png"
    plugin.handle("view.action", {"action": "toggle-pause", "payload": {}})
    assert plugin._state["paused"] is True
    assert ("surface.background.configure", {"paused": True}) in CALLS


@pytest.mark.parametrize("value", ["../escape.png", "/absolute.png", "C:/x.png", "a/../x.png", "a//x.png", "", None])
def test_rejects_unsafe_relative_paths(value):
    assert plugin._relative(value) == ""


@pytest.mark.parametrize("value", [-1, 101, True, "50", 1.5, None])
def test_invalid_slider_never_reaches_host(value):
    response = plugin.handle("view.action", {"action": "configure-opacity", "payload": {"value": value}})
    assert "message" in response
    assert plugin._state["opacity"] == 100
    assert CALLS == []


def test_host_failure_keeps_configuration_and_hides_private_path(monkeypatch):
    def denied(*args, **kwargs):
        raise RuntimeError("private C:/Users/example/wallpaper.png")

    monkeypatch.setattr(plugin.omnicrawler_sdk, "call", denied)
    response = plugin.handle("view.action", {"action": "configure-opacity", "payload": {"value": 50}})
    assert plugin._state["opacity"] == 100
    assert "private" not in str(response)
    assert "C:/" not in str(response)


def test_failed_source_switch_keeps_old_inventory(monkeypatch):
    plugin._state.update({"handle": "old", "items": [{"id": "old.png", "label": "Old", "subtitle": "", "supported": True}]})

    def denied(*args, **kwargs):
        raise RuntimeError("expired grant")

    monkeypatch.setattr(plugin.omnicrawler_sdk, "call", denied)
    plugin.handle("view.action", {"action": "source-selected", "payload": {"resource_handle": "new"}})
    assert plugin._state["handle"] == "old"
    assert plugin._state["items"][0]["id"] == "old.png"


def test_unreadable_project_does_not_hide_loose_media(monkeypatch):
    def broker(operation, payload):
        if operation == "resources.read":
            raise RuntimeError("metadata unreadable")
        return _capability(operation, payload)

    monkeypatch.setattr(plugin.omnicrawler_sdk, "call", broker)
    assert {item["id"] for item in plugin._scan("resource:test")} == {"123/index.html", "loose.png"}


def test_filter_navigation_only_plays_matching_resources():
    plugin._state.update({"handle": "resource:test", "items": [
        {"id": "one.png", "label": "One", "subtitle": "", "supported": True},
        {"id": "two.mp4", "label": "Two", "subtitle": "", "supported": True},
    ]})
    plugin.handle("view.action", {"action": "filter-resources", "payload": {"value": "video"}})
    plugin.handle("view.action", {"action": "next-resource"})
    assert plugin._state["selected_id"] == "two.mp4"
    assert len(plugin._visible_items()) == 1


def test_clear_resets_playback_without_dropping_directory():
    plugin._state.update({"handle": "keep", "active": True, "paused": True, "now_playing": "Old", "selected_id": "old.png"})
    response = plugin.handle("view.action", {"action": "clear-background"})
    assert plugin._state["handle"] == "keep"
    assert not plugin._state["active"]
    assert not plugin._state["paused"]
    assert plugin._state["selected_id"] == ""
    assert "插件仍保持启用" in response["message"]


def test_refresh_requires_an_authorized_source():
    response = plugin.handle("view.action", {"action": "refresh-source"})
    assert "授权" in response["message"]
    assert not CALLS


def test_failed_play_does_not_claim_success(monkeypatch):
    plugin._state["items"] = [{"id": "one.png", "label": "One", "subtitle": "", "supported": True}]

    def denied(*args, **kwargs):
        raise RuntimeError("not supported")

    monkeypatch.setattr(plugin.omnicrawler_sdk, "call", denied)
    plugin.handle("view.action", {"action": "play-resource", "payload": {"item_id": "one.png"}})
    assert not plugin._state["active"]
    assert plugin._state["selected_id"] == ""
