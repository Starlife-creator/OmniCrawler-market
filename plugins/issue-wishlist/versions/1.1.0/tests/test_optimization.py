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

def test_failed_refresh_keeps_successful_list_and_time(optimized, monkeypatch):
    optimized._state.update(issues=[{'number': 1, 'title': 'Old', 'state': 'open', 'html_url': 'https://github.com/Starlife-creator/omnicrawler/issues/1'}], fetched=True, updated_at='old')
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', lambda *args: {'status': 429, 'body_b64': ''})
    optimized.handle('view.action', {'action': 'refresh'})
    assert optimized._state['issues'], 'Failed refresh discarded the last successful list'
    assert optimized._state['issues'][0]['title'] == 'Old'
    assert optimized._state['updated_at'] == 'old'
    assert '429' in optimized._state['error']


def test_refresh_has_bounded_pagination_and_throttle(optimized, monkeypatch):
    calls = []
    def call(op, args):
        calls.append(args['url'])
        page = int(args['url'].rsplit('page=', 1)[1])
        items = [{'number': page * 100 + i, 'title': 'Feature', 'labels': [{'name': 'enhancement'}]} for i in range(1, 31)] if page == 1 else []
        return {'status': 200, 'body_b64': base64.b64encode(json.dumps(items).encode()).decode()}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    optimized.handle('view.action', {'action': 'refresh'})
    assert len(calls) == 2 and optimized._state['complete']
    optimized.handle('view.action', {'action': 'refresh'})
    assert len(calls) == 2
    opened = optimized.handle('view.action', {'action': 'open-issue', 'payload': {'item_id': '101'}})
    assert any(c['id'] == 'selected-issue' and c['segments'][0]['type'] == 'link' for c in opened['view']['components'])
    optimized.handle('view.action', {'action': 'search', 'payload': {'value': 'no match'}})
    assert not next(c for c in optimized._view()['components'] if c['id'] == 'issues')['items']
