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


@pytest.mark.parametrize("result,expected", [({"final_url":"https://example.test/final","request":{"url":"https://example.test/seed"}},"https://example.test/final"), ({"url":"https://example.test/old"},"https://example.test/old"), ({"request":{"url":"https://example.test/seed"}},"https://example.test/seed")])
def test_actual_host_source_contract(reviewed, result, expected):
    result["body_b64"] = base64.b64encode(("<article><p>Evidence is traceable. " * 20 + "</p></article>").encode()).decode()
    output = reviewed.handle("extractor.process", {"result": result})
    assert output["records"][0]["source_url"] == expected

def test_unstructured_length_cannot_imply_high_quality(reviewed):
    output = reviewed.extract_html("<div>" + "nonsense " * 500 + "</div>")
    assert output["confidence"] <= 0.45 and output["quality"] != "high"
    assert output["diagnostics"]["score_kind"] == "heuristic_quality_not_probability"

def test_optional_empty_diagnostic_uses_record_contract(reviewed):
    result = fetch(b"<nav><a href='/'>Home</a></nav>", "text/html")
    assert reviewed.handle("extractor.process", {"result": result})["records"] == []
    output = reviewed.handle("extractor.process", {"result": result, "options": {"emit_diagnostics": True}})
    assert output["records"][0]["record_type"] == "extraction_diagnostic"

@pytest.mark.parametrize("mode", ["precision", "balanced", "recall"])
def test_labelled_article_and_noise_corpus(reviewed, mode):
    samples = json.loads((Path(__file__).parent / "fixtures/quality_samples.json").read_text(encoding="utf-8"))
    assert samples
    for sample in samples:
        result = reviewed.extract_html(sample["html"], mode=mode)
        assert result["text"] == sample["gold"], sample["name"]
        if not sample["high_quality_allowed"]:
            assert result["confidence"] < 0.75
