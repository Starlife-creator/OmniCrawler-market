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

def test_media_works_without_html_capabilities(optimized):
    required = optimized.PLUGIN_METADATA['required_capabilities']
    assert 'render.html.live.start' not in required and 'render.html.snapshot' not in required


def test_failed_configuration_never_publishes_new_background(optimized, monkeypatch):
    optimized._state.update(handle='grant', items=[{'id': 'a.png', 'label': 'A', 'subtitle': '', 'supported': True}], active=False, selected_id='')
    calls = []
    def call(op, args):
        calls.append(op)
        if op == 'surface.background.configure': raise RuntimeError('denied')
        return {}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    optimized.handle('view.action', {'action': 'play-resource', 'payload': {'item_id': 'a.png'}})
    assert not optimized._state['active']
    assert 'surface.background.set' not in calls


def test_search_and_page_navigation(optimized):
    optimized._state['items'] = [{'id': f'{i}.png', 'label': f'Image {i}', 'subtitle': '', 'supported': True} for i in range(120)]
    def items(): return next(c for c in optimized._view()['components'] if c['id'] == 'wallpaper-list')['items']
    assert len(items()) == 50 and items()[0]['id'] == '0.png'
    optimized.handle('view.action', {'action': 'next-page'})
    assert items()[0]['id'] == '50.png'
    optimized.handle('view.action', {'action': 'search-resources', 'payload': {'value': 'Image 119'}})
    assert len(items()) == 1 and items()[0]['id'] == '119.png'


def test_live_failure_falls_back_to_snapshot(optimized, monkeypatch):
    optimized._state.update(handle='grant', html_mode='live', items=[{'id': 'a.html', 'label': 'A', 'subtitle': '', 'supported': True}])
    calls=[]
    def call(op,args):
        calls.append(op)
        if op == 'render.html.live.start': raise RuntimeError('unsupported')
        if op == 'render.html.snapshot': return {'handle': 'snapshot'}
        return {}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    result = optimized.handle('view.action', {'action': 'play-resource', 'payload': {'item_id': 'a.html'}})
    assert 'render.html.snapshot' in calls and optimized._state['active']
    assert '静态快照' in result['message']
