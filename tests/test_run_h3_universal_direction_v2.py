"""Actual CLI main calls with isolated fake APIs or private mocked transport."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import h3_universal_direction_execution_v1 as v1
from src.content_factory import h3_universal_direction_execution_v2 as v2
from test_h3_universal_direction_execution_v1 import library_env
from test_visual_h3_library_minute_v2 import run
from test_visual_h3_library_continuation_v1 import spec,review
from src.content_factory import visual_h3_library_continuation_v1 as library

PROJECT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('universal_v2_cli',PROJECT/'scripts/run_h3_universal_direction_v2.py')
cli=importlib.util.module_from_spec(s);s.loader.exec_module(cli)


class FakeAPI:
    def __init__(self,run):self.run=run;self.calls=[];self.results=[dict(status='technical_saved')]
    def native_run(self,run,shot):
        assert run.is_absolute() and run==self.run
        return run/'visual_h3_v3'/(run.name+'_'+shot)
    def status(self,run,*args):
        assert run.is_absolute() and run==self.run;self.calls.append(('status',run));return dict(status='running')
    def collect_known(self,run,*args):
        assert run.is_absolute() and run==self.run;self.calls.append(('GET',run));value=self.results.pop(0)
        if isinstance(value,BaseException):raise value
        return value
    def submit(self,*args,**kwargs):raise AssertionError('wait must never submit')
    def prepare_video(self,*args,**kwargs):raise AssertionError('wait must never prepare')


@pytest.fixture
def env(tmp_path,monkeypatch):
    run=(tmp_path/'run').resolve();run.mkdir();policy=tmp_path/'POLICY.json';policy.write_text('{}',encoding='utf-8')
    api=FakeAPI(run);chosen=[]
    def lib1(value,pb):assert value==run;chosen.append('library_v1');return api
    def lib2(value,pb,approval):assert value==run;chosen.append(('library_v2',approval));return api
    def asset(value,pb):assert value==run;chosen.append('asset_v1');return api
    monkeypatch.setattr(v1,'library_for_run',lib1);monkeypatch.setattr(v2,'library_for_run',lib2);monkeypatch.setattr(v1,'asset_for_run',asset)
    state=api.native_run(run,'S03')/'shots/S03/STATE.json';state.parent.mkdir(parents=True)
    state.write_text(json.dumps(dict(id='S03',status='running',prompt_id='original_uuid')),encoding='utf-8')
    def args(action='wait',route='library'):
        result=[action,'--route',route,'--run',str(run.relative_to(PROJECT)),'--policy',str(policy),'--shot','S03']
        if action=='wait':result+=['--prompt-id','original_uuid','--poll-seconds','10','--max-seconds','60']
        return result
    return dict(run=run,policy=policy,api=api,chosen=chosen,state=state,args=args)


def exit_record(env):
    files=list((env['run']/'collectors').glob('cli_v2_*/EXIT.json'));assert len(files)==1
    return files[0],flow.read(files[0])


@pytest.mark.parametrize('route',['library','asset'])
def test_relative_run_reaches_actual_status_caller_as_absolute_path(env,route):
    assert cli.main(env['args']('status',route))==0
    assert env['api'].calls==[('status',env['run'])]
    assert env['chosen']==['library_v1' if route=='library' else 'asset_v1']


def test_explicit_saved_scene_reuse_selects_v2_library_factory(env,tmp_path):
    file=tmp_path/'REUSE.json';file.write_text('{}',encoding='utf-8')
    args=env['args']('status')+['--scene-reuse-approval',str(file)]
    assert cli.main(args)==0 and env['chosen']==[('library_v2',flow.bind(file))]


def test_known_ID_wait_only_collects_and_writes_success_EXIT(env):
    assert cli.main(env['args']())==0
    path,value=exit_record(env)
    assert env['api'].calls==[('GET',env['run'])]
    assert value['result']['status']=='technical_saved' and value['rePOST_performed'] is False
    assert value['exit_code']==0 and (path.parent/'START.json').exists()


def test_fatal_integrity_error_retains_traceback_and_EXIT_without_resubmission(env):
    env['api'].results=[ValueError('graph_original_SHA_changed')]
    assert cli.main(env['args']())==1
    path,value=exit_record(env);error=flow.read(path.parent/'ERROR.json')
    assert value['fatal'] is True and value['exit_code']==1 and value['result']['status']=='collector_fatal_error'
    assert error['type']=='ValueError' and 'graph_original_SHA_changed' in error['traceback']
    assert env['api'].calls==[('GET',env['run'])]


def test_factory_or_policy_integrity_error_also_has_EXIT(env,monkeypatch):
    monkeypatch.setattr(cli,'_api',lambda args:(_ for _ in ()).throw(ValueError('policy_binding_changed')))
    assert cli.main(env['args']())==1
    path,value=exit_record(env)
    assert value['result']['phase']=='factory' and (path.parent/'ERROR.json').exists() and env['api'].calls==[]


@pytest.mark.parametrize('status,uuid,expected',[('outcome_unknown','original_uuid',3),('prepared',None,1)])
def test_unknown_claim_is_preserved_and_never_reposted(env,status,uuid,expected):
    env['state'].write_text(json.dumps(dict(status=status,prompt_id=uuid)),encoding='utf-8')
    claim=env['state'].parent/'CLAIM.json';claim.write_bytes(b'original unknown claim preserved')
    before=flow.bind(claim)
    assert cli.main(env['args']())==expected
    _,value=exit_record(env)
    assert flow.bind(claim)==before and env['api'].calls==[] and value['rePOST_performed'] is False


def test_wrong_original_UUID_is_fatal_and_still_has_EXIT(env):
    env['state'].write_text(json.dumps(dict(status='running',prompt_id='different_uuid')),encoding='utf-8')
    before=flow.bind(env['state'])
    assert cli.main(env['args']())==1
    _,value=exit_record(env)
    assert value['fatal'] is True and flow.bind(env['state'])==before and env['api'].calls==[]


def test_transient_GET_error_is_retained_then_original_ID_can_complete(env,monkeypatch):
    sleeps=[];monkeypatch.setattr(cli.time,'sleep',lambda n:sleeps.append(n))
    env['api'].results=[TimeoutError('controlled GET timeout'),dict(status='technical_saved')]
    assert cli.main(env['args']())==0
    path,value=exit_record(env)
    assert len(list((path.parent/'errors').glob('*.json')))==1 and sleeps==[10]
    assert [x[0] for x in env['api'].calls]==['GET','GET'] and value['fatal'] is False


def test_private_real_prepare_and_unknown_wait_use_abs_run_and_keep_zero_mock_POSTs(library_env):
    run,state=library_env;library.prepare(run,spec(run));review(run)
    policy=flow.freeze(run/'CLI_POLICY.json',deepcopy(__import__('src.content_factory.video_directing_policy_v1',fromlist=['DEFAULT_POLICY']).DEFAULT_POLICY))
    args=['prepare','--route','library','--run',str(run.relative_to(PROJECT)),'--policy',policy['path'],'--shot','S01']
    assert cli.main(args)==0 and state['posts']==0
    native=library.base.native_run(run,'S01');claim=native/'shots/S01/CLAIM.json';claim.write_bytes(b'unknown claim fixture')
    before=flow.bind(claim)
    wait=['wait','--route','library','--run',str(run.relative_to(PROJECT)),'--policy',policy['path'],
        '--shot','S01','--prompt-id','not_returned_uuid','--poll-seconds','10','--max-seconds','60']
    assert cli.main(wait)==1 and state['posts']==0 and flow.bind(claim)==before
    value=flow.read(next((run/'collectors').glob('cli_v2_*/EXIT.json')))
    assert value['fatal'] is True and value['rePOST_performed'] is False
