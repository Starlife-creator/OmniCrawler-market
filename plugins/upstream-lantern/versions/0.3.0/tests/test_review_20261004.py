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


def test_event_identity_baseline_and_recovery_are_persistent(reviewed, monkeypatch):
    memory_sdk(monkeypatch)
    def observe(conclusion):
        result = fetch(json.dumps({"workflow_runs":[{"id":123,"name":"CI","conclusion":conclusion}]}).encode(),"application/json")
        result["request"]["meta"] = {"lantern_signal":"workflow_runs","repository":"Owner/Repo","track_changes":True,"initial_policy":"baseline"}
        return reviewed.handle("extractor.process",{"result":result})["records"][0]["data"]
    first = observe("failure")
    assert first["initial_baseline"] and not first["attention"]
    repeated = observe("failure")
    assert repeated["event_id"] == first["event_id"] and not repeated["attention"]
    recovered = observe("success")
    assert recovered["event_kind"] == "recovery" and recovered["attention"]
    assert recovered["event_id"] != first["event_id"]
    assert not observe("success")["attention"]

def test_excluded_prerelease_never_updates_state(reviewed, monkeypatch):
    stored = memory_sdk(monkeypatch)
    result = fetch(json.dumps([{"id":1,"tag_name":"v2rc1","prerelease":True}]).encode(),"application/json")
    result["request"]["meta"] = {"lantern_signal":"releases","repository":"Owner/Repo","track_changes":True,"include_prereleases":False}
    assert reviewed.handle("extractor.process",{"result":result})["records"] == []
    assert not stored

def test_new_policy_validated_before_requests(reviewed):
    output = reviewed.handle("source.seed",{"config":{"source":{"params":{"initial_policy":"invalid"}}}})
    assert not output["requests"]

def test_seed_propagates_event_policy_to_real_generated_requests(reviewed):
    output = reviewed.handle("source.seed", {"config":{"seeds":["psf/requests"],"params":{
        "feeds":["releases"],"track_changes":True,"initial_policy":"baseline","include_prereleases":False}}})
    assert not output["errors"] and output["requests"]
    for request in output["requests"]:
        assert request["meta"]["initial_policy"] == "baseline"
        assert request["meta"]["include_prereleases"] is False

def test_default_policy_migrates_old_observation_without_alert_burst(reviewed, monkeypatch):
    stored = memory_sdk(monkeypatch)
    result = fetch(json.dumps([{"id":1,"tag_name":"v1"}]).encode(),"application/json")
    result["request"]["meta"] = {"lantern_signal":"releases","repository":"Owner/Repo","track_changes":True}
    data = {"signal":"releases","subject":"Owner/Repo","id":"1","title":"v1","url":"","tag_name":"v1"}
    old_digest = hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    old_key = "lantern." + hashlib.sha256(b"releases:Owner/Repo:1").hexdigest()
    stored[old_key] = old_digest
    observed = reviewed.handle("extractor.process",{"result":result})["records"][0]["data"]
    assert observed["change"] == "unchanged" and not observed["attention"]
