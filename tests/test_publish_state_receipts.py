import json
from types import SimpleNamespace
import pytest
from src.platform_adapter.models import PublishRequest, PublishResult
import src.platform_adapter.publish_workflow as module


def setup(tmp_path, monkeypatch, authenticated=True):
    monkeypatch.setattr(module, '__file__', str(tmp_path/'src/platform_adapter/publish_workflow.py'))
    video=tmp_path/'test.mp4';video.write_bytes(b'fixture')
    request=PublishRequest(video_path=str(video),title='fixture',extra_metadata={
        'account_key':'A','account_uuid':'A','platform_identity_key':'douyin:A'})
    workflow=module.PublishWorkflow(SimpleNamespace(start=lambda:None,is_authenticated=lambda:authenticated))
    return workflow,request


def events(workflow):
    return [json.loads(line) for line in workflow._journal_path.read_text(encoding='utf-8').splitlines()]


def test_login_failure_has_durable_receipt(tmp_path,monkeypatch):
    workflow,request=setup(tmp_path,monkeypatch,False)
    result=workflow.publish(request)
    assert result.status=='login_required'
    assert events(workflow)[-1]['stage']=='login_required'
    assert not workflow._submission_lock.exists()


def test_upload_timeout_is_not_success(tmp_path,monkeypatch):
    workflow,request=setup(tmp_path,monkeypatch)
    workflow._do_publish=lambda *args,**kwargs:PublishResult(success=False,status='upload_failed',message='timeout')
    assert not workflow.publish(request).success
    assert events(workflow)[-1]['stage']=='upload_failed'


def test_uncertain_submission_remains_locked_and_logged(tmp_path,monkeypatch):
    workflow,request=setup(tmp_path,monkeypatch)
    def uncertain(*args,**kwargs):
        workflow._reserve_submission()
        raise TimeoutError('fixture timeout')
    workflow._do_publish=uncertain
    result=workflow.publish(request)
    assert result.status=='submission_unknown' and not result.success
    assert events(workflow)[-1]['stage']=='submission_unknown'
    assert workflow._submission_lock.exists()
    exc=module.PublishWorkflowError(result)
    assert exc.status=='submission_unknown'
    assert not workflow.publish(request).success
