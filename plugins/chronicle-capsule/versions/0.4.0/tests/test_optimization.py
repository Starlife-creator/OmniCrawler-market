import base64
import gzip
import hashlib
import io
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

def test_privacy_redacts_urls_and_secret_patterns(optimized):
    data, info = optimized.build_archive([{'source_url': 'https://user:pass@example.test/?token=secret123', 'data': {'text': 'Bearer secret123', 'password': 'secret123'}}])
    raw = gzip.decompress(data)
    assert b'secret123' not in raw
    assert b'user:pass' not in raw
    assert b'REDACTED' in raw


@pytest.mark.parametrize('mode', ['privacy', 'metadata', 'preservation'])
def test_export_interoperable_members_and_truncation(optimized, monkeypatch, mode):
    deps = Path(__file__).resolve().parents[3] / 'user-test-runs' / 'plugin-optimization-20261003' / 'qa-deps'
    if deps.exists(): monkeypatch.syspath_prepend(str(deps))
    ArchiveIterator = pytest.importorskip("warcio.archiveiterator").ArchiveIterator
    chunks = []
    def call(op, args):
        if op == 'artifact.stream.open': return {'handle': 'test'}
        if op == 'artifact.stream.write': chunks.append(base64.b64decode(args['content_b64'])); return {}
        if op == 'artifact.stream.commit': return {'name': 'test.warc.gz'}
        if op == 'records.page': return {'records': [{'source_url': 'https://example.test/a', 'data': {'x': 'a'}}, {'source_url': 'https://example.test/b', 'data': {'x': 'b'}}]}
        if op == 'responses.page': return {'responses': [{'response_ref': 'a', 'url': 'https://example.test/a', 'content_type': 'text/plain'}, {'response_ref': 'b', 'url': 'https://example.test/b', 'content_type': 'text/plain'}]}
        if op == 'responses.payload': return {'content_b64': base64.b64encode(b'hello').decode(), 'truncated': args['response_ref'] == 'a'}
        if op == 'view.progress': return {}
        raise AssertionError(op)
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    output = optimized.handle('exporter.export', {'options': {'mode': mode, 'max_records': 2}})
    archive = b''.join(chunks)
    count = 0
    ids = []
    index = None
    for record in ArchiveIterator(io.BytesIO(archive), check_digests=True):
        content = record.content_stream().read()
        if record.rec_type == 'metadata':
            import json
            index = json.loads(content)
            continue
        assert record.rec_type == 'resource'
        ids.append(record.rec_headers.get_header('WARC-Record-ID'))
        assert content
        if mode == 'preservation' and count == 0:
            assert record.rec_headers.get_header('WARC-Truncated') == 'length'
        count += 1
    assert count == 2
    assert index and [e['record_id'] for e in index['entries']] == ids
    assert output['summary']['system_records'] == 1
    assert output['summary']['sha256'] == hashlib.sha256(archive).hexdigest()
    assert output['summary']['truncated_payloads'] == (1 if mode == 'preservation' else 0)


def test_oversize_archive_aborts_without_commit(optimized, monkeypatch):
    calls = []
    optimized.MAX_ARCHIVE_BYTES = 100
    def call(op, args):
        calls.append(op)
        if op == 'artifact.stream.open': return {'handle': 'test'}
        if op == 'records.page': return {'records': [{'data': {'text': 'x' * 200}}]}
        return {}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    with pytest.raises(ValueError): optimized.handle('exporter.export', {})
    assert 'artifact.stream.abort' in calls
    assert 'artifact.stream.commit' not in calls
