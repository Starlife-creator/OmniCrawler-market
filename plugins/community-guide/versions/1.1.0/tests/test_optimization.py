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

def test_feedback_entrypoints_are_direct_and_no_stale_discussions(optimized):
    segments=optimized.handle('view.describe',{})['view']['components'][0]['segments']
    links=[s for s in segments if s['type']=='link']
    assert any('报告缺陷' in s['text'] for s in links)
    assert any('功能建议' in s['text'] for s in links)
    assert any('投稿' in s['text'] for s in links)
    assert not any(s['url'].endswith('/discussions') for s in links)
