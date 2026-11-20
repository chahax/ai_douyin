import json
import pytest

from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, ARK_BASE_URL, ARK_MINI_MODEL
from scripts.run_script_video import prepare,submit,read,write,query_ark,retry_ark_configuration
from test_conversation_direction import setup


def test_ark_first_shot_is_scoped_and_receipt_blocks_duplicate(tmp_path,monkeypatch):
    _,script,_,plan=setup(tmp_path)
    folder=(tmp_path/'run').resolve()
    prepare(folder,script,'用户测试 Mini 首镜',plan,provider='ark_api',test_shot='S01')
    monkeypatch.setattr('scripts.run_script_video.save_ark_report',lambda *a:None)

    class Client(SeedanceClient):
        calls=0
        def create_task(self,payload):
            self.calls+=1
            assert read(folder/'S01.json')['status']=='submit_outcome_unknown'
            assert payload['model']==ARK_MINI_MODEL and payload['resolution']=='480p'
            assert '动作1：' in payload['content'][0]['text']
            return {'id':'cgt-test-first-shot'}

    with Client(SeedanceConfig(api_key='test-secret',base_url=ARK_BASE_URL,model=ARK_MINI_MODEL,provider='ark_api')) as client:
        with pytest.raises(ValueError,match='selected test shot'):submit(folder,'S02',client,[])
        assert client.calls==0
        submit(folder,'S01',client,[])
        with pytest.raises(ValueError,match='Receipt already exists'):submit(folder,'S01',client,[])
        assert client.calls==1
    record=read(folder/'S01.json')
    assert record['provider']=='ark_api' and 'cost_credits' not in record
    assert 'test-secret' not in json.dumps(record)


def test_unknown_ark_outcome_keeps_receipt(tmp_path,monkeypatch):
    _,script,_,plan=setup(tmp_path)
    folder=(tmp_path/'run').resolve()
    prepare(folder,script,'用户测试 Mini 首镜',plan,provider='ark_api',test_shot='S01')
    monkeypatch.setattr('scripts.run_script_video.save_ark_report',lambda *a:None)
    class Failure(SeedanceClient):
        def create_task(self,payload):raise TimeoutError('unknown server outcome')
    with Failure(SeedanceConfig(api_key='test',base_url=ARK_BASE_URL,model=ARK_MINI_MODEL,provider='ark_api')) as client:
        with pytest.raises(TimeoutError):submit(folder,'S01',client,[])
        assert read(folder/'S01.json')['status']=='submit_outcome_unknown'
        with pytest.raises(ValueError,match='Receipt already exists'):submit(folder,'S01',client,[])


def test_limit_recovery_requires_failed_server_confirmation_and_runs_once(tmp_path,monkeypatch):
    from src.web.video_production_dashboard import load_run
    _,script,_,plan=setup(tmp_path)
    folder=(tmp_path/'data/video_generation/run').resolve()
    prepare(folder,script,'首镜测试',plan,provider='ark_api',test_shot='S01')
    monkeypatch.setattr('scripts.run_script_video.save_ark_report',lambda *a:None)
    class Client(SeedanceClient):
        calls=0
        def create_task(self,payload):
            self.calls+=1
            return {'id':f'cgt-test-{self.calls}'}
        def get_task(self,task_id):
            return {'id':task_id,'status':'failed','error':{'code':'SetLimitExceeded'},'usage':None}
    with Client(SeedanceConfig(api_key='test',base_url=ARK_BASE_URL,model=ARK_MINI_MODEL,provider='ark_api')) as client:
        submit(folder,'S01',client,[])
        query_ark(folder,read(folder/'S01.json'),client)
        assert read(folder/'S01.json')['usage']=={}
        assert not load_run(folder/'production.json',tmp_path)['errors']
        with pytest.raises(ValueError,match='user instruction'):
            retry_ark_configuration(folder,'S01',client,'')
        retry_ark_configuration(folder,'S01',client,'用户确认体验额度已调整')
        assert client.calls==2 and len(list((folder/'failed_attempts').glob('S01.limit.*.json')))==1
        query_ark(folder,read(folder/'S01.json'),client)
        with pytest.raises(ValueError,match='already attempted'):
            retry_ark_configuration(folder,'S01',client,'再次操作')
        assert client.calls==2
