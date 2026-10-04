import base64
import hashlib
import importlib.util
import io
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


def test_missing_body_does_not_hide_exhausted_input_limit(reviewed, monkeypatch):
    chunks = []
    def call(op,args):
        if op == "artifact.stream.open": return {"handle":"archive"}
        if op == "responses.page": return {"responses":[{"url":"https://example.test/missing"},{"response_ref":"ok","url":"https://example.test/ok"}],"next_cursor":"more"}
        if op == "responses.payload": return {"content_b64":base64.b64encode(b"ok").decode()}
        if op == "artifact.stream.write": chunks.append(base64.b64decode(args["content_b64"])); return {}
        if op in {"artifact.stream.commit","artifact.stream.abort","view.progress"}: return {}
        raise AssertionError(op)
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
    summary = reviewed.handle("exporter.export",{"options":{"mode":"preservation","max_records":2}})["summary"]
    assert summary["record_limit_reached"] and summary["input_truncated"]
    assert summary["scanned_inputs"] == summary["records"] + summary["missing_payloads"] == 2
    assert summary["records"] == 1 and summary["system_records"] == 1
    from warcio.archiveiterator import ArchiveIterator
    records = list(ArchiveIterator(io.BytesIO(b"".join(chunks))))
    assert [r.rec_type for r in records] == ["resource","metadata"]

def test_privacy_index_does_not_reintroduce_url_credentials(reviewed, monkeypatch):
    chunks = []
    def call(op,args):
        if op == "artifact.stream.open": return {"handle":"archive"}
        if op == "records.page": return {"records":[{"source_url":"https://u:pass@example.test/x?token=PRIVATE","data":{"token":"PRIVATE"}}]}
        if op == "artifact.stream.write": chunks.append(base64.b64decode(args["content_b64"])); return {}
        return {}
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
    reviewed.handle("exporter.export",{})
    import gzip
    raw = gzip.decompress(b"".join(chunks))
    assert b"PRIVATE" not in raw and b"u:pass" not in raw
    assert b"urn:omnicrawler:chronicle:index" in raw

def test_index_budget_overflow_aborts_already_written_business_record(reviewed, monkeypatch):
    record = {"source_url":"https://example.test/x","data":{"text":"evidence"}}
    reviewed.MAX_ARCHIVE_BYTES = len(reviewed._warc_record(record, "2026-10-04T00:00:00Z")) + 100
    calls=[]
    def call(op,args):
        calls.append(op)
        if op == "artifact.stream.open": return {"handle":"archive"}
        if op == "records.page": return {"records":[record]}
        return {}
    monkeypatch.setattr(sys.modules["omnicrawler_sdk"],"call",call)
    with pytest.raises(ValueError): reviewed.handle("exporter.export",{})
    assert "artifact.stream.write" in calls and "artifact.stream.abort" in calls
    assert "artifact.stream.commit" not in calls
