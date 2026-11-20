import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.platform_adapter import fanqie_promotion_observer_v1 as observer
from src.platform_adapter import fanqie_promotion_observation_diagnostic_v1 as m

SUBJECT = dict(resource_id='fanqie:fixture', binding_version='v1',
    platform_identity_key='uid:12345', environment_key='env1',
    owner_id='owner1', generation=1, task_id='task1')
ENDPOINT='/api/promotion/list/v1'


def binding(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def request(tmp_path, **changes):
    return binding(tmp_path/'REQUEST.json',dict(schema=m.REQUEST_SCHEMA,
        **{k:SUBJECT[k] for k in m.SCOPE},endpoint_paths=[ENDPOINT],
        wait_ms=100,purpose=m.PURPOSE,**changes))


class WorkerPage:
    def __init__(self):
        self.url=observer.ORIGIN+'/page/promotion-list?tab_type=2&token=never-save'
        self.main_frame=object();self.listeners={}

    def evaluate(self, js):
        assert js==observer.RESOURCE_JS
        return [{'origin':observer.ORIGIN,'path':ENDPOINT,'initiator_type':'fetch'}]

    def on(self, event, callback):self.listeners[event]=callback
    def remove_listener(self, event, callback):del self.listeners[event]


class RPC:
    def __init__(self):
        self.worker=WorkerPage();self.observers={};self.calls=[];self.reloads=[]
        self.waits=[];self.failure=None;self.capture=True;self.wrong_snapshot=False
        self.on_wait=None

    @property
    def url(self):return self.worker.url

    def fanqie_promotion_observer(self, mode, **kwargs):
        self.calls.append(mode)
        result=observer.worker_action(self.worker,self.observers,'actual-tab',mode=mode,**kwargs)
        if mode=='snapshot' and self.wrong_snapshot:result['worker_page_id']='other-tab'
        return result

    def goto(self, url, **kwargs):
        assert url==self.worker.url
        self.reloads.append(kwargs)
        if self.failure:raise self.failure
        if self.capture:
            data=json.dumps({'data':{'book_promotion_word_list':[{'word_id':194}]}}).encode()
            response=SimpleNamespace(url=observer.ORIGIN+ENDPOINT+'?token=never-save',status=200,
                request=SimpleNamespace(frame=self.worker.main_frame,resource_type='xhr',method='GET'),
                header_value=lambda k:{'content-type':'application/json','content-length':str(len(data))}[k],
                body=lambda:data)
            response.request.url=response.url
            response.request.response=lambda:response
            response.request.sizes=lambda:{'responseBodySize':len(data)}
            self.worker.listeners['requestfinished'](response.request)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        if self.on_wait:self.on_wait()


def execute(tmp_path, rpc=None, *, req=None, guard=None, folder='run'):
    rpc=rpc or RPC();req=req or request(tmp_path)
    wrapped=SimpleNamespace(page=rpc,url=rpc.url)
    return m.run_observation(wrapped,subject=SUBJECT,observer_request=req,
        guard=guard or (lambda:None),output_directory=tmp_path/folder)


def test_full_passive_route_uses_one_same_page_reload_and_preserves_unknown_structure(tmp_path):
    rpc=RPC();guards=[];result=execute(tmp_path,rpc,guard=lambda:guards.append(1))
    assert result['status']=='observed' and result['captures']==1
    assert rpc.calls==['resources','arm','snapshot','stop']
    assert rpc.reloads==[{'wait_until':'domcontentloaded','timeout':5000}]
    assert rpc.waits==[100] and len(guards)==6
    assert result['observer_stop_confirmed'] and not rpc.observers
    assert result['promotion_contract_verified'] is False
    saved=json.loads(Path(result['evidence']['observation']['path']).read_bytes())
    assert saved['captures'][0]['metadata']['records']==[]
    assert any('word_id' in row['path'] for row in saved['captures'][0]['metadata']['structure'])
    assert all('never-save' not in p.read_text(encoding='utf-8') for p in (tmp_path/'run').iterdir())


def test_queue_preflight_requires_only_exact_actual_resource_scope_not_fake_owner(tmp_path):
    req=request(tmp_path);scope={k:SUBJECT[k] for k in m.SCOPE}
    assert m.validate_request_scope(req,scope)['purpose']==m.PURPOSE
    with pytest.raises(ValueError):
        m.validate_request_scope(req,dict(scope,owner_id='invented'))
    with pytest.raises(ValueError):
        m.validate_request_scope(req,dict(scope,binding_version='other'))


def test_completed_cache_is_pure_read_with_deep_evidence_revalidation(tmp_path):
    rpc=RPC();req=request(tmp_path);first=execute(tmp_path,rpc,req=req)
    calls=list(rpc.calls);again=execute(tmp_path,rpc,req=req)
    assert first==again and rpc.calls==calls and len(rpc.reloads)==1
    Path(first['evidence']['observation']['path']).write_text('{}')
    with pytest.raises(ValueError,match='binding_changed'):
        execute(tmp_path,rpc,req=req)
    assert rpc.calls==calls


def test_no_response_is_incomplete_not_a_platform_missing_concept_claim(tmp_path):
    rpc=RPC();rpc.capture=False;result=execute(tmp_path,rpc)
    assert result['status']=='incomplete' and result['captures']==0
    assert result['promotion_contract_verified'] is False and result['observer_stop_confirmed']


def test_unobserved_path_stops_before_arm_or_reload(tmp_path):
    req=request(tmp_path);value=json.loads(Path(req['path']).read_bytes())
    value['endpoint_paths']=['/api/guessed/path'];req=binding(Path(req['path']),value)
    rpc=RPC();result=execute(tmp_path,rpc,req=req)
    assert result['status']=='error' and rpc.calls==['resources'] and rpc.reloads==[]


@pytest.mark.parametrize('change',[{'wait_ms':5001},{'resource_id':'wrong-resource'},
    {'purpose':'submit_promotion'}])
def test_invalid_request_scope_or_non_readonly_purpose_refused_before_any_action(tmp_path,change):
    req=request(tmp_path);value=json.loads(Path(req['path']).read_bytes());value.update(change)
    req=binding(Path(req['path']),value);rpc=RPC()
    with pytest.raises(ValueError):execute(tmp_path,rpc,req=req)
    assert not rpc.calls and not (tmp_path/'run').exists()


def test_navigation_timeout_stops_once_saves_sanitized_error_and_does_not_retry(tmp_path):
    rpc=RPC();rpc.failure=TimeoutError('https://x/?token=do-not-save')
    req=request(tmp_path);result=execute(tmp_path,rpc,req=req)
    assert result['status']=='error' and result['observer_stop_confirmed']
    assert rpc.calls==['resources','arm','stop'] and len(rpc.reloads)==1
    assert 'do-not-save' not in json.dumps(result)
    execute(tmp_path,rpc,req=req);assert len(rpc.reloads)==1


def test_fenced_owner_cannot_continue_or_issue_unguarded_cleanup(tmp_path):
    rpc=RPC();count=[0]
    def guard():
        count[0]+=1
        if count[0]>=3:raise RuntimeError('owner fenced')
    result=execute(tmp_path,rpc,guard=guard)
    assert result['status']=='error' and result['observer_stop_confirmed'] is False
    assert rpc.calls==['resources','arm'] and rpc.reloads==[]


def test_wrong_snapshot_page_cannot_be_saved_as_success(tmp_path):
    rpc=RPC();rpc.wrong_snapshot=True;result=execute(tmp_path,rpc)
    assert result['status']=='error' and result['captures']==0
    assert result['observer_stop_confirmed'] and 'observation' not in result['evidence']


def test_interrupted_start_is_not_replayed(tmp_path):
    rpc=RPC();rpc.failure=KeyboardInterrupt();req=request(tmp_path)
    with pytest.raises(KeyboardInterrupt):execute(tmp_path,rpc,req=req)
    assert (tmp_path/'run'/'START.json').exists() and not (tmp_path/'run'/'RESULT.json').exists()
    calls=list(rpc.calls);result=execute(tmp_path,rpc,req=req)
    assert result['status']=='outcome_unknown' and result['automatic_retry'] is False
    assert rpc.calls==calls and len(rpc.reloads)==1


def test_request_change_during_wait_cannot_yield_observed_receipt(tmp_path):
    rpc=RPC();req=request(tmp_path)
    rpc.on_wait=lambda:Path(req['path']).write_text('{}')
    result=execute(tmp_path,rpc,req=req)
    assert result['status']=='error' and 'observation' not in result['evidence']
    assert not result['observer_stop_confirmed']
