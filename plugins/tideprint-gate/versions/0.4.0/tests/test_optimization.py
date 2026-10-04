import base64
import os
from pathlib import Path
import sys
import types
import uuid

import pytest


@pytest.fixture
def optimized(monkeypatch):
    name = Path(__file__).resolve().parents[1].name
    override = os.environ.get("PLUGIN_OPTIMIZATION_ORIGINALS")
    root = Path(override) / name if override else Path(__file__).resolve().parents[1]
    sdk = types.ModuleType("omnicrawler_sdk")
    sdk.call = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "omnicrawler_sdk", sdk)
    module = types.ModuleType("optimized_" + uuid.uuid4().hex)
    module.__file__ = str(root / "plugin.py")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile((root / "plugin.py").read_text(encoding="utf-8"), module.__file__, "exec"), module.__dict__)
    yield module
    if hasattr(module, "_close_http_clients"):
        module._close_http_clients()

def test_invalid_body_does_not_mutate_fingerprint_state(optimized):
    result = optimized.handle('processor.process', {'result': {'url': 'https://example.test', 'body_b64': '!broken!'}})
    assert result['records'][0]['data']['status'] == 'invalid'
    assert optimized._state == {}


def test_binary_body_whitespace_preserved(optimized):
    def process(body):
        return optimized.handle('processor.process', {'result': {'url': 'https://example.test', 'body_b64': base64.b64encode(body).decode(), 'content_type': 'application/octet-stream'}})['records'][0]['data']['status']
    assert process(b'\x00  \x01') == 'new'
    assert process(b'\x00 \x01') == 'changed'


def test_error_response_never_overwrites_previous_state(optimized, monkeypatch):
    writes = []
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', lambda op, args: writes.append((op, args)) or {})
    optimized.handle('hook.after_fetch', {'result': {'final_url': 'https://example.test', 'status': 500, 'content_hash': 'a' * 64}})
    assert not any(op == 'state.set' for op, args in writes)


def test_persistent_classification_and_summary_agree(optimized, monkeypatch):
    stored = {}
    def call(op, args):
        if op == 'state.get': return {'found': args['key'] in stored, 'value': stored.get(args['key'])}
        if op == 'state.set': stored[args['key']] = args['value']; return {'saved': True}
        raise AssertionError(op)
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    result = {'request': {'url': 'https://example.test/old'}, 'final_url': 'https://example.test/new', 'status': 200, 'content_hash': 'a' * 64, 'body_b64': base64.b64encode(b'text').decode()}
    optimized.handle('hook.after_fetch', {'result': result})
    first = optimized.handle('processor.process', {'result': result})
    assert first['records'][0]['data']['status'] == 'new'
    optimized.handle('hook.after_fetch', {'result': result})
    output = optimized.handle('processor.process', {'result': result})
    assert output['records'][0]['data']['status'] == 'unchanged'
    summary = optimized.handle('hook.after_run', {})
    assert summary['counts']['new'] == 1 and summary['counts']['unchanged'] == 1
    assert optimized.handle('hook.before_fetch', {'request': {'url': 'https://example.test/old'}})['fetch_advice']['action'] == 'conditional_revalidate'


def test_304_keeps_valid_digest(optimized, monkeypatch):
    writes = []
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', lambda op, args: writes.append(op) or {})
    result = optimized.handle('hook.after_fetch', {'result': {'url': 'https://example.test', 'status': 304}})
    assert result['persistent_change']['status'] == 'unchanged'
    assert 'state.set' not in writes
