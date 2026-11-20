"""Only the explicit completed-S06 archive gap; no network or media submissions."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
ADAPTER=ROOT/'data/video_generation/h3_assistant_screenplay_full_20261016/resume_20261018/resume_runner.py'
spec=importlib.util.spec_from_file_location('h3_resume_20261018',ADAPTER)
resume=importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


@pytest.fixture
def original():
    frozen=resume.resume_admission(require_review=False)
    plan=resume.base.read(frozen['original_batch_plan']['path'])
    predecessor=resume.base.saved_row(frozen['completed_prefix'][-1]['receipt']['path'])
    return frozen,plan,predecessor


class EmptyClient:
    def __init__(self):self.gets=[]
    def get(self,path):
        self.gets.append(path)
        return {}


def test_exact_empty_s06_accepts_successful_frozen_originals(original):
    frozen,plan,predecessor=original
    client=EmptyClient()
    evidence=resume.archive_aware_check(client,predecessor,plan,resume=frozen)
    assert client.gets==['/history/'+resume.S06_ID]
    assert evidence['verification_mode']=='archived_original_after_service_restart'
    assert evidence['live_history_response']=={} and evidence['live_history_task_found'] is False
    assert evidence['archived_original_success_verified'] is True
    assert [row['segment_id'] for row in evidence['completed_prefix']]==[f'S{i:02d}' for i in range(1,7)]
    assert evidence['service_history_injected'] is False


def test_changed_tail_or_failed_archive_refused(original,monkeypatch):
    frozen,plan,predecessor=original
    actual_sha=resume.base.sha
    tail=Path(predecessor['last_frame']).resolve()
    with monkeypatch.context() as patch:
        patch.setattr(resume.base,'sha',lambda path:'changed' if Path(path).resolve()==tail else actual_sha(path))
        with pytest.raises(ValueError):resume.archive_aware_check(EmptyClient(),predecessor,plan,resume=frozen)
    actual_read=resume.base.read
    history=Path(frozen['completed_prefix'][-1]['history']['path']).resolve()
    def read_failed(path):
        result=actual_read(path)
        if Path(path).resolve()==history:
            result=copy.deepcopy(result)
            result[resume.S06_ID]['status']['status_str']='error'
        return result
    monkeypatch.setattr(resume.base,'read',read_failed)
    with pytest.raises(ValueError,match='archive is not'):
        resume.archive_aware_check(EmptyClient(),predecessor,plan,resume=frozen)


def test_other_id_nonempty_or_unknown_response_never_fallback(original):
    frozen,plan,predecessor=original
    wrong=dict(predecessor,prompt_id='another-id')
    with pytest.raises(ValueError,match='restricted'):
        resume.archive_aware_check(EmptyClient(),wrong,plan,resume=frozen)
    class Client:
        def __init__(self,value):self.value=value
        def get(self,path):return self.value
    for value in (None,[],{'unrelated-id':{}}):
        with pytest.raises(ValueError):resume.archive_aware_check(Client(value),predecessor,plan,resume=frozen)
    class NetworkFailure:
        def get(self,path):raise TimeoutError('offline GET failed')
    with pytest.raises(TimeoutError):resume.archive_aware_check(NetworkFailure(),predecessor,plan,resume=frozen)


def test_live_id_uses_unchanged_original_check(original,monkeypatch):
    frozen,plan,predecessor=original
    calls=[]
    def original_check(client,pred,current_plan):
        calls.append((client,pred,current_plan));return {'unchanged_original_result':True}
    monkeypatch.setattr(resume,'ORIGINAL_CHECK',original_check)
    class Client:
        def get(self,path):return {resume.S06_ID:{'status':{'status_str':'error'}}}
    client=Client()
    assert resume.archive_aware_check(client,predecessor,plan,resume=frozen)=={'unchanged_original_result':True}
    assert calls==[(client,predecessor,plan)]
