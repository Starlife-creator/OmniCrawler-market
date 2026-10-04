import json
import os
from pathlib import Path
import subprocess
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

@pytest.mark.parametrize('config',[{'max_pdf_bytes':'bad'}, {'institution':[]}, {'level':True}, {'oa_precheck_concurrency':0}, {'delay_min':'bad'}])
def test_invalid_config_returns_errors_before_tuning(optimized, config):
    result=optimized.handle('source.seed',{'config':config})
    assert result['errors'] and not result['requests']


def test_atomic_state_failure_keeps_previous_value(optimized, monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'],'call',lambda *a: (_ for _ in ()).throw(RuntimeError('no sdk')))
    optimized._set_state_dir(tmp_path)
    optimized._state_set('record','old')
    monkeypatch.setattr(optimized.os,'replace',lambda *a: (_ for _ in ()).throw(OSError('interrupted')))
    optimized._state_set('record','new')
    assert optimized._state_get('record')['value']=='old'
    assert not list((tmp_path/'.apd_state').glob('*.tmp'))


def test_cross_process_lock_exclusion_and_crash_release(optimized,tmp_path):
    root=Path(optimized.__file__).parent
    child = "import sys;sys.path.insert(0,sys.argv[1]);import plugin;from pathlib import Path;l=plugin._DistributedLock({},Path(sys.argv[2]));print(l.acquire('10.1/same'),flush=True);sys.stdin.readline()"
    proc=subprocess.Popen([sys.executable,'-B','-c',child,str(root),str(tmp_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    try:
        assert proc.stdout.readline().strip()=='True'
        lock=optimized._DistributedLock({},tmp_path)
        assert not lock.acquire('10.1/same')
        proc.kill();proc.wait(timeout=10)
        assert lock.acquire('10.1/same')
        lock.release('10.1/same')
    finally:
        if proc.poll() is None: proc.kill();proc.wait(timeout=10)
        proc.stdin.close();proc.stdout.close()


def test_proxy_clients_retire_after_last_active_stream(optimized,monkeypatch):
    class FakeClient:
        def __init__(self,**kwargs): self.is_closed=False
        def close(self): self.is_closed=True
        def stream(self,*args,**kwargs):
            from contextlib import nullcontext
            return nullcontext('response')
    monkeypatch.setattr(optimized.httpx,'Client',FakeClient)
    monkeypatch.setattr(optimized,'_get_next_proxy',lambda cfg: cfg.get('proxy',''))
    optimized._set_download_config({'proxy':'http://a'})
    with optimized._client_stream('GET','https://example.test'):
        old=optimized._HTTP_CLIENT
        optimized._set_download_config({'proxy':'http://b'})
        optimized._get_http_client()
        assert not old.is_closed
    assert old.is_closed and optimized._RETIRED_HTTP_CLIENTS==[]
    optimized._close_http_clients()
    assert optimized._HTTP_CLIENT is None


def test_cancel_preserves_finished_state_and_skips_download(optimized,monkeypatch,tmp_path):
    values={}
    def call(op,args):
        if op=='state.set':values[args['key']]=args['value'];return {}
        if op=='state.get':return {'found':args['key'] in values,'value':values.get(args['key'])}
        return {}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'],'call',call)
    optimized._mark_done({},'10.1/finished',{'doi':'10.1/finished'})
    optimized.handle('view.action',{'action':'cancel-downloads'})
    # A separate processor session has no view session's in-memory event.
    optimized._CANCEL_EVENT.clear()
    monkeypatch.setattr(optimized,'_process_download',lambda *a: (_ for _ in ()).throw(AssertionError('cancelled download started')))
    result=optimized._process({'paper':{'doi':'10.1/new'},'workspace':str(tmp_path)})
    assert result['errors'][0]['error_class']=='cancelled'
    assert '10.1/finished' in json.loads(optimized._state_get(optimized._done_key({}))['value'])


def test_parallel_finished_index_retains_all_dois(optimized, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import time

    values = {}
    def call(op, args):
        if op == 'state.set':
            values[args['key']] = args['value']
            return {}
        if op == 'state.get':
            previous = values.get(args['key'])
            time.sleep(0.002)
            return {'found': previous is not None, 'value': previous}
        return {}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    optimized._set_state_dir(tmp_path)
    dois = [f'10.1007/parallel-{i}' for i in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda doi: optimized._mark_done({}, doi), dois))
    assert set(json.loads(values[optimized._done_key({})])) == set(dois)


def test_streamed_input_has_bounded_queue_and_resume(optimized, monkeypatch, tmp_path):
    values = {}
    def call(op, args):
        if op == 'state.set':
            values[args['key']] = args['value']
        if op == 'state.get':
            return {'found': args['key'] in values, 'value': values.get(args['key'])}
        return {}
    monkeypatch.setattr(sys.modules['omnicrawler_sdk'], 'call', call)
    (tmp_path / 'papers.csv').write_text('DOI,Title\n' + ''.join(
        f'10.1007/sample-{i},Paper {i}\n' for i in range(1200)), encoding='utf-8')
    config = {'level': 1, 'max_per_session': 20}
    output = optimized._seed({'workspace': str(tmp_path), 'file_path': 'papers.csv', 'config': config})
    assert not output['errors'] and output['meta']['total_rows'] == 1200
    assert len(output['requests']) == 20
    assert any('max_per_session' in warning for warning in output['warnings'])
    for request in output['requests']:
        optimized._mark_done(config, request['meta']['paper']['doi'])
    resumed = optimized._seed({'workspace': str(tmp_path), 'file_path': 'papers.csv', 'config': config})
    assert resumed['requests'][0]['meta']['paper']['doi'] == '10.1007/sample-20'
