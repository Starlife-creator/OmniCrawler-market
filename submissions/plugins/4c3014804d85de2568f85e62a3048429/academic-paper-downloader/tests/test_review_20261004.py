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


def test_download_identity_hash_and_url_evidence_are_safe(reviewed, tmp_path):
    assert reviewed.normalize_doi("https://doi.org/10.1000/ABC") == reviewed.normalize_doi("doi:10.1000/abc") == "10.1000/abc"
    assert reviewed.public_source_url("https://user:pass@example.test/pdf?token=PRIVATE&x=1#secret") == "https://example.test/pdf"
    assert reviewed.public_source_url("C:/private/download.pdf") == ""
    path = tmp_path / "evidence.pdf"
    path.write_bytes(b"test bytes")
    assert reviewed.file_digest(path) == hashlib.sha256(b"test bytes").hexdigest()
    record = {"doi":"10.1000/ABC","sha256":reviewed.file_digest(path),"pdf_meta":{"validation_level":"header_only"},"verification":"header_only"}
    assert reviewed.build_evidence(record,"https://example.test/pdf?token=PRIVATE")["validation_level"] == "header_only"

def test_corrupt_pdf_header_is_not_structure_success(reviewed, tmp_path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not a PDF structure\n%%EOF")
    # Both available parsers must reject structure before any header fallback.
    pytest.importorskip("pypdf")
    valid, meta = reviewed._inspect_pdf(path)
    assert not valid
    assert meta["validation_level"] == "structure_invalid"

def test_weak_validation_policy_rejects_nonboolean(reviewed):
    assert reviewed._validate_config({"allow_weak_pdf_validation":"yes"})

def test_header_only_grade_and_strict_policy(reviewed, monkeypatch, tmp_path):
    import builtins
    original_import = builtins.__import__
    def without_parsers(name, *args, **kwargs):
        if name in {"pdfplumber", "pypdf"}: raise ImportError("unavailable parser")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_parsers)
    path = tmp_path / "header.pdf"
    path.write_bytes(b"%PDF-1.4\nheader only")
    assert reviewed._inspect_pdf(path) == (True, {"validation_level":"header_only"})
    reviewed._set_download_config({"allow_weak_pdf_validation": False})
    monkeypatch.setattr(reviewed, "_rename_with_metadata", lambda paper, path: path)
    assert reviewed._save_pdf({"doi":"10.1000/test", "title":"Test"}, path.read_bytes(), tmp_path, "test") is None
    assert not list((tmp_path / "papers").glob("*.pdf"))

def test_save_checks_size_before_writing_or_moving(reviewed, tmp_path):
    reviewed._MAX_PDF_BYTES = 8
    source = tmp_path / "large.pdf"
    source.write_bytes(b"%PDF-1.4\n" + b"x" * 20)
    workspace = tmp_path / "output"
    assert reviewed._save_pdf({}, source, workspace, "test") is None
    assert source.exists() and not workspace.exists()
    assert reviewed._save_pdf({}, b"x" * 9, workspace, "test") is None
    assert not workspace.exists()
