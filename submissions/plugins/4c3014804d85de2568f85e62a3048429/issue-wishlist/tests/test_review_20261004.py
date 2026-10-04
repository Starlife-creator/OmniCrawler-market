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


def test_updated_sort_and_persisted_marks(reviewed, monkeypatch):
    stored = memory_sdk(monkeypatch)
    reviewed._state.update(issues=[{"number":1,"title":"older","state":"open","html_url":"https://example.test/1","updated_at":"2026-01-01","created_at":"2026-02-01"},{"number":2,"title":"updated","state":"open","html_url":"https://example.test/2","updated_at":"2026-03-01","created_at":"2026-01-01"}], selected="1")
    items = lambda: next(c for c in reviewed._view()["components"] if c["id"] == "issues")["items"]
    assert items()[0]["id"] == "2"
    reviewed.handle("view.action",{"action":"toggle-favorite"})
    reviewed.handle("view.action",{"action":"toggle-read"})
    assert stored[reviewed.MARK_KEY]["marks"]["1"] == {"favorite":True,"read":True}
    reviewed._state.update(marks={}, marks_loaded=False)
    reviewed.handle("view.describe",{})
    assert reviewed._state["marks"]["1"]["favorite"]
    reviewed.handle("view.action",{"action":"filter-marks","payload":{"value":"favorites"}})
    assert [i["id"] for i in items()] == ["1"]
    reviewed.handle("view.action",{"action":"filter-marks","payload":{"value":"unread"}})
    assert [i["id"] for i in items()] == ["2"]

def test_marks_denial_has_explicit_session_fallback(reviewed, monkeypatch):
    def denied(op,args): raise RuntimeError("capability denied")
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",denied)
    reviewed._mark("7","favorite",True)
    assert reviewed._state["marks"]["7"]["favorite"]
    assert not reviewed._state["persistent_marks"]
    assert any("本次会话" in c.get("text","") for c in reviewed._view()["components"])

def test_marks_capacity_is_bounded(reviewed, monkeypatch):
    memory_sdk(monkeypatch)
    reviewed.MAX_MARKS = 2
    for number in ("1","2","3"): reviewed._mark(number,"read",True)
    assert list(reviewed._state["marks"]) == ["2","3"]

def test_mark_retention_order_survives_host_canonical_json(reviewed, monkeypatch):
    stored = memory_sdk(monkeypatch)
    reviewed.MAX_MARKS = 2
    for number in ("9", "1"): reviewed._mark(number, "read", True)
    stored[reviewed.MARK_KEY] = json.loads(json.dumps(stored[reviewed.MARK_KEY], sort_keys=True))
    reviewed._state.update(marks_loaded=False, marks={})
    reviewed._mark("2", "read", True)
    assert list(reviewed._state["marks"]) == ["1", "2"]
