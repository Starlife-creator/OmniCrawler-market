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

def test_adaptive_pagination_reserves_budget_and_stops_on_empty(optimized):
    plan = optimized.handle('source.seed', {'config': {'seeds': ['psf/requests'], 'params': {'feeds': ['releases'], 'pages': 3, 'max_requests': 3, 'per_page': 2, 'adaptive_pagination': True}}})
    assert len(plan['requests']) == 1 and plan['summary']['planned_requests'] == 3
    request = plan['requests'][0]
    def extract(items, request):
        return optimized.handle('extractor.process', {'result': {'request': request, 'final_url': request['url'], 'status': 200, 'body_b64': base64.b64encode(json.dumps(items).encode()).decode()}})
    first = extract([{'id': 1, 'tag_name': 'v1'}, {'id': 2, 'tag_name': 'v2'}], request)
    assert len(first['requests']) == 1 and first['requests'][0]['meta']['page'] == 2
    empty = extract([], first['requests'][0])
    assert empty['requests'] == [] and empty['summary']['complete']


def test_workflow_change_tracking_and_errors(optimized, monkeypatch):
    values={}
    def call(op,args):
        if op == 'state.get': return {'found': args['key'] in values, 'value': values.get(args['key'])}
        if op == 'state.set': values[args['key']] = args['value']; return {}
        raise AssertionError(op)
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    request={'url':'https://api.github.com/repos/psf/requests/actions/runs','meta':{'lantern_signal':'workflow_runs','repository':'psf/requests','track_changes':True}}
    payload={'result':{'request':request,'status':200,'body_b64':base64.b64encode(json.dumps({'workflow_runs':[{'id':12,'name':'CI','status':'completed','conclusion':'failure'}]}).encode()).decode()}}
    first=optimized.handle('extractor.process',payload)['records'][0]['data']
    second=optimized.handle('extractor.process',payload)['records'][0]['data']
    assert first['change']=='new' and first['attention']
    assert second['change']=='unchanged' and not second['attention']
    payload['result']['status']=429
    error=optimized.handle('extractor.process',payload)['records'][0]
    assert error['record_type']=='upstream_error' and not error['data']['complete']


def test_invalid_adaptive_option_and_budget_rejected(optimized):
    for params in ({'adaptive_pagination':'yes'}, {'feeds':['releases'],'pages':5,'max_requests':1,'adaptive_pagination':True}):
        result=optimized.handle('source.seed',{'config':{'seeds':['psf/requests'],'params':params}})
        assert result['errors'] and not result['requests']
