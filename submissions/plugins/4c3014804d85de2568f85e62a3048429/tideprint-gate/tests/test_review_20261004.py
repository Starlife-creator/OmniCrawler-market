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


def test_hook_and_processor_share_semantic_policy_across_runs(reviewed, monkeypatch):
    memory_sdk(monkeypatch)
    statuses = []
    for body in (b"hello  world", b"hello world"):
        result = fetch(body)
        reviewed.handle("hook.before_run", {})
        reviewed.handle("hook.after_fetch", {"result": result})
        statuses.append(reviewed.handle("processor.process", {"result": result})["records"][0]["data"]["status"])
        reviewed.handle("hook.after_run", {})
    assert statuses == ["new", "unchanged"]

def test_json_ignore_and_explicit_array_sort_are_bounded_and_isolated(reviewed, monkeypatch):
    stored = memory_sdk(monkeypatch)
    options = {"json_ignore_fields": ["/time"], "json_sort_arrays": ["/tags"]}
    def process(value, opts=options):
        return reviewed.handle("processor.process", {"result": fetch(json.dumps(value).encode(), "application/json"), "options": opts})["records"][0]["data"]
    assert process({"time":1,"price":10,"tags":["a","b"]})["status"] == "new"
    assert process({"time":2,"price":10,"tags":["b","a"]})["status"] == "unchanged"
    assert process({"time":2,"price":11,"tags":["b","a"]})["status"] == "changed"
    assert process({"time":2,"price":11,"tags":["b","a"]}, {})["status"] == "new"
    before = dict(stored)
    assert process({"price": 12}, {"json_ignore_fields": ["/x"] * 51})["status"] == "invalid"
    assert stored == before

def test_json_string_whitespace_is_significant(reviewed, monkeypatch):
    memory_sdk(monkeypatch)
    def process(body):
        return reviewed.handle("processor.process", {"result": fetch(body, "application/json")})["records"][0]["data"]["status"]
    assert process(b'{"value":"hello  world"}') == "new"
    assert process(b'{"value":"hello world"}') == "changed"
