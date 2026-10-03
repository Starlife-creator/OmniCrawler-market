import base64
import json
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

def test_jsonld_graph_and_nested_metadata(optimized):
    value = {"@graph": [{"@type": "NewsArticle", "headline": "Graph headline", "author": {"name": "Ada"}, "datePublished": "2026-10-03"}]}
    source = '<script type="application/ld+json">' + json.dumps(value) + '</script><p>' + 'Useful content. ' * 15 + '</p>'
    result = optimized.extract_html(source)
    assert result["title"] == "Graph headline"
    assert result["author"] == "Ada"


def test_parent_noise_excluded_even_when_long(optimized):
    source = '<div class="related"><p>' + 'Related advertisements. ' * 200 + '</p></div><article><p>' + 'Real article. ' * 20 + '</p></article>'
    result = optimized.extract_html(source)
    assert 'Related advertisements' not in result['text']
    assert 'Real article' in result['text']


def test_declared_charset_and_cjk_count(optimized):
    text = '这是中文正文。' * 30
    body = base64.b64encode(('<p>' + text + '</p>').encode('gbk')).decode()
    result = optimized.handle('extractor.process', {'result': {'body_b64': body, 'content_type': 'text/html; charset=gbk'}})
    data = result['records'][0]['data']
    assert text in data['text']
    assert data['word_count'] == 6 * 30


def test_list_code_markdown_and_void_ancestry(optimized):
    result = optimized.extract_html('<meta name="author" content="Ada"><article><li>' + 'A meaningful list item. ' * 5 + '</li><pre>' + 'example code line\n' * 8 + '</pre></article>')
    assert '- A meaningful' in result['markdown']
    assert '```' in result['markdown']
