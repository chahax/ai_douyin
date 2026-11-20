import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_script_video import prepare, submit, locked, read, retry_failed, write
from script_pair_fixture import pair_payload
from test_script_pair import parse
from dataclasses import asdict
from src.web.video_production_dashboard import load_run, workflow_steps


def setup_run(tmp_path):
    folder = tmp_path/'data/video_generation/run'
    script_path = tmp_path/'script.json'
    script_path.write_text(json.dumps(asdict(parse(pair_payload())[0])),encoding='utf-8')
    script_path.with_suffix('.md').write_text('test storyboard')
    script_path.with_suffix('.audit.json').write_text('{}')
    prepare(folder,script_path,'explicit test authorization')
    return folder


class Client:
    config = SimpleNamespace(model_version='seedance2.5')
    calls = 0

    def user_credit(self):
        return {'total_credit':100}

    def build_video_arguments(self, prompt, **kwargs):
        return [prompt]

    def submit_video(self, args):
        self.calls += 1
        return {'submit_id':'id-1','gen_status':'querying','credit_count':12}


def test_receipt_prevents_repeat_paid_submission(tmp_path):
    folder = setup_run(tmp_path)
    client = Client()
    submit(folder,'S01',client,[])
    with pytest.raises(ValueError,match='Receipt already exists'):
        submit(folder,'S01',client,[])
    assert client.calls == 1
    record = read(folder/'S01.json')
    assert record['cost_credits']==12 and record['submit_id']=='id-1'
    run = load_run(folder/'production.json',tmp_path)
    assert not run['errors']
    assert workflow_steps(run)[2] == ('提交','1/6 有回执')


def test_unknown_submission_keeps_receipt_and_blocks_retry(tmp_path):
    folder=setup_run(tmp_path)
    class Failure(Client):
        def submit_video(self,args):
            assert (folder/'S01.json').exists()
            raise TimeoutError('unknown server outcome')
    client=Failure()
    with pytest.raises(TimeoutError):
        submit(folder,'S01',client,[])
    assert read(folder/'S01.json')['status']=='submit_outcome_unknown'
    with pytest.raises(ValueError,match='Receipt already exists'):
        submit(folder,'S01',client,[])


def test_changed_script_cannot_be_submitted(tmp_path):
    folder=setup_run(tmp_path)
    (folder/'locked_script.json').write_text('{}')
    with pytest.raises(ValueError,match='Locked script changed'):
        locked(folder)


def test_recovery_requires_confirmed_failure_and_preserves_original(tmp_path):
    folder=setup_run(tmp_path)
    class Recovery(Client):
        def query_result(self,task_id):
            return {'submit_id':task_id,'gen_status':'fail'}
    client=Recovery()
    submit(folder,'S01',client,[])
    with pytest.raises(ValueError,match='explicitly failed'):
        retry_failed(folder,'S01',client)
    record=read(folder/'S01.json')
    record.update(status='failed',cost_credits=0)
    write(folder/'S01.json',record)
    retry_failed(folder,'S01',client)
    assert len(list((folder/'failed_attempts').glob('S01.*.json')))==1
    assert read(folder/'S01.json')['status']=='running'
