import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import uuid
import pytest

@pytest.fixture
def reviewed(monkeypatch):
    name = Path(__file__).resolve().parents[1].name
    override = os.environ.get("PLUGIN_OPTIMIZATION_ORIGINALS")
    root = Path(override) / name if override else Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root))
    sdk = types.ModuleType("omnicrawler_sdk")
    sdk.call = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "omnicrawler_sdk", sdk)
    spec = importlib.util.spec_from_file_location("reviewed_" + uuid.uuid4().hex, root / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    yield module
    if hasattr(module, "_close_http_clients"):
        module._close_http_clients()

def memory_sdk(monkeypatch):
    stored = {}
    def call(op, args):
        if op == "state.get": return {"found": args["key"] in stored, "value": stored.get(args["key"])}
        if op == "state.set": stored[args["key"]] = json.loads(json.dumps(args["value"])); return {"saved": True}
        raise AssertionError(op)
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"], "call", call)
    return stored

def fetch(body, content_type="text/plain"):
    return {"request": {"url": "https://example.test/seed"}, "final_url": "https://example.test/final",
            "status": 200, "content_type": content_type, "body_b64": base64.b64encode(body).decode(),
            "content_hash": hashlib.sha256(body).hexdigest()}


@pytest.mark.parametrize("failure",["surface.background.configure","surface.background.set"])
def test_failed_live_switch_has_no_unowned_live_task(reviewed, monkeypatch, failure):
    reviewed._state.update(handle="grant",html_mode="live",items=[{"id":"a.html","label":"A","subtitle":"","supported":True}])
    calls=[]
    def call(op,args):
        calls.append(op)
        if op == failure: raise RuntimeError("injected")
        if op == "render.html.live.start": return {"handle":"live"}
        return {}
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
    reviewed.handle("view.action",{"action":"play-resource","payload":{"item_id":"a.html"}})
    if failure.endswith("configure"):
        assert "render.html.live.start" not in calls
    else:
        assert "render.html.live.stop" in calls and "surface.background.clear" in calls
    assert not reviewed._state["active"]

def test_thumbnail_snapshot_cache_and_refresh_invalidation(reviewed, monkeypatch):
    reviewed._state.update(handle="grant",items=[{"id":"a.html","label":"A","subtitle":"","supported":True}])
    renders=[]
    def call(op,args):
        if op == "render.html.snapshot": renders.append(args); return {"handle":"thumb"}
        if op == "resources.enumerate": return {"items": [{"relative":"a.html","kind":"file"}]}
        return {}
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
    for _ in range(2): reviewed.handle("view.action",{"action":"preview-resource","payload":{"value":"a.html"}})
    assert len(renders) == 1 and renders[0]["width"] == 320
    assert renders[0]["scripted"] is False
    reviewed.handle("view.action",{"action":"refresh-source"})
    reviewed.handle("view.action",{"action":"preview-resource","payload":{"value":"a.html"}})
    assert len(renders) == 2

def test_preferences_use_profile_not_grant_and_restore(reviewed, monkeypatch):
    memory_sdk(monkeypatch)
    reviewed._state.update(handle="old-grant",selected_id="a.png",source_identity="work",dim=27)
    key = reviewed._preference_key("a.png")
    reviewed._save_preferences()
    reviewed._state.update(handle="new-grant",dim=0)
    assert reviewed._preference_key("a.png") == key
    reviewed._load_preferences("a.png")
    assert reviewed._state["dim"] == 27
    reviewed._state["source_identity"] = "home"
    assert reviewed._preference_key("a.png") != key

def test_preferences_capacity_and_denied_state_keep_session_choices(reviewed, monkeypatch):
    def denied(op,args): raise RuntimeError("denied")
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",denied)
    reviewed.MAX_PREFERENCES = 2
    for name in ("a.png", "b.png", "c.png"):
        reviewed._state.update(selected_id=name,dim=21)
        reviewed._save_preferences()
    assert len(reviewed._preferences) == 2
    reviewed._state["dim"] = 0
    reviewed._load_preferences("c.png")
    assert reviewed._state["dim"] == 21 and not reviewed._state["persistent_preferences"]

@pytest.mark.parametrize("failure", ["surface.background.configure", "surface.background.set"])
def test_real_host_worker_preserved_or_stopped_after_failed_switch(reviewed, monkeypatch, failure):
    from omnicrawler.plugins.plugin_render import RenderBroker
    class Runtime:
        def stream(self, html, *, stop, on_frame, **kwargs):
            on_frame(b"test-frame")
            stop.wait(5)
    class Resources:
        def read(self, *args, **kwargs): return b"<html>local</html>"
    broker = RenderBroker(runtime=Runtime())
    resources = Resources()
    try:
        old = broker.start_html_live(resources, "grant", "old.html")["handle"]
        reviewed._state.update(handle="grant", html_mode="live", active=True, selected_id="old.html", now_playing="Old",
                               items=[{"id":"new.html","label":"New","subtitle":"","supported":True}])
        def call(op,args):
            if op == failure: raise RuntimeError("injected failure")
            if op == "state.get": return {"found":False}
            if op == "render.html.live.start": return broker.start_html_live(resources,args["handle"],args["relative"])
            if op == "render.html.live.stop": broker.stop_live(); return {"active":False}
            return {}
        monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
        reviewed.handle("view.action",{"action":"play-resource","payload":{"item_id":"new.html"}})
        if failure.endswith("configure"):
            assert broker.is_live(old) and reviewed._state["active"]
            assert reviewed._state["now_playing"] == "Old"
        else:
            assert broker._live_thread is None and not reviewed._state["active"]
    finally:
        broker.close()

def test_switch_from_live_to_static_detaches_old_surface_before_publish(reviewed, monkeypatch):
    reviewed._state.update(handle="grant",active=True,live_active=True,selected_id="old.html",
                           items=[{"id":"new.png","label":"New","subtitle":"","supported":True}])
    calls=[]
    def call(op,args): calls.append(op); return {}
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
    reviewed.handle("view.action",{"action":"play-resource","payload":{"item_id":"new.png"}})
    assert calls.index("surface.background.clear") < calls.index("surface.background.set")
    assert reviewed._state["active"] and not reviewed._state["live_active"]
