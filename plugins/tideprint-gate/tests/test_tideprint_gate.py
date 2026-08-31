from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tideprint_gate", ROOT / "plugin.py")
assert SPEC and SPEC.loader
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


def test_url_normalization_is_stable() -> None:
    assert plugin.normalize_url("HTTPS://Example.COM:443/a?z=2&a=1#x") == "https://example.com/a?a=1&z=2"
    assert plugin.normalize_url("https://example.test:bad/path") == "https://example.test/path"
    assert plugin.normalize_url("http://[::1]:80/a") == "http://[::1]/a"


def test_classifies_new_unchanged_and_changed() -> None:
    plugin._reset()
    assert plugin.classify("https://example.test/a", b"hello   world")["status"] == "new"
    assert plugin.classify("https://example.test/a#fragment", b"hello world")["status"] == "unchanged"
    changed = plugin.classify("https://example.test/a", b"different")
    assert changed["status"] == "changed"
    assert changed["previous_sha256"]


def test_processor_and_hook_contract() -> None:
    plugin.handle("hook.before_run", {})
    body = base64.b64encode(b"content").decode()
    result = plugin.handle("processor.process", {"result": {"url": "https://example.test", "body_b64": body}})
    assert result["records"][0]["data"]["status"] == "new"
    assert result["requests"] == []
    summary = plugin.handle("hook.after_run", {})
    assert summary["counts"]["new"] == 1
    assert summary["scope"] == "persistent_host_state"


def test_hooks_use_host_state_and_return_advice(monkeypatch) -> None:
    values = {}

    class SDK:
        @staticmethod
        def call(operation, payload):
            if operation == "state.get":
                return {"found": payload["key"] in values, "value": values.get(payload["key"])}
            if operation == "state.set":
                values[payload["key"]] = payload["value"]
                return {"saved": True}
            raise AssertionError(operation)

    monkeypatch.setitem(sys.modules, "omnicrawler_sdk", SDK)
    request = {"request": {"url": "https://example.test/a", "method": "GET"}}
    assert plugin.handle("hook.before_fetch", request) == {}
    plugin.handle(
        "hook.after_fetch",
        {
            "result": {
                "final_url": "https://example.test/a",
                "content_hash": "a" * 64,
                "status": 200,
            }
        },
    )
    advice = plugin.handle("hook.before_fetch", request)
    assert advice["fetch_advice"]["action"] == "conditional_revalidate"
