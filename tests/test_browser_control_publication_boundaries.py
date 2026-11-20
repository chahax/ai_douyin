"""Queue admission cannot claim platform success or start a second browser."""
from types import SimpleNamespace
import pytest

from src.platform_adapter.douyin_adapter import DouyinAdapter
from src.platform_adapter.models import PublishRequest


@pytest.fixture
def controlled(monkeypatch):
    from src.operations_accounts import browser_control_runtime as control
    from src.services import artifact_account
    monkeypatch.setattr(artifact_account, 'artifact_account', lambda x: {'account_uuid': '', 'account_conflict': False})
    monkeypatch.setattr(control, 'enabled', lambda: True)
    monkeypatch.setattr(control, 'active_context', lambda: None)
    monkeypatch.setattr(control, 'is_managed_account', lambda key: False)
    captured = []
    def enqueue(*args, **kwargs):
        captured.append((args, kwargs))
        return {'command_id': 'frozen-job', 'status': 'queued'}
    monkeypatch.setattr(control, 'queue_publish_request', enqueue)
    context = SimpleNamespace(account_key='account01', account_uuid='fixture:one')
    adapter = DouyinAdapter(session=SimpleNamespace(), runtime_context=context)
    monkeypatch.setattr(adapter, '_require_runtime_identity', lambda **kw: pytest.fail('Client must not open a browser'))
    return adapter, captured


def test_external_publish_only_queues_and_does_not_claim_platform_submission(controlled):
    adapter, captured = controlled
    result = adapter.publish_video(PublishRequest(video_path='fixture.mp4', title='fixture',
        extra_metadata={'authorization_reference': 'explicit_fixture_user_statement'}))
    assert result.success and result.status == 'queued'
    assert not result.post_id and not result.publish_url
    assert len(captured) == 1 and captured[0][1]['authorization'] == 'explicit_fixture_user_statement'


def test_cross_account_video_is_rejected_before_queue(controlled):
    adapter, captured = controlled
    result = adapter.publish_video(PublishRequest(video_path='fixture.mp4', title='fixture',
        extra_metadata={'account_uuid': 'fixture:other', 'authorization_reference': 'fixture'}))
    assert result.status == 'account_mismatch' and captured == []


def test_no_authorization_is_not_fabricated_to_admit_queue(controlled):
    adapter, captured = controlled
    result = adapter.publish_video(PublishRequest(video_path='fixture.mp4', title='fixture'))
    assert result.status == 'authorization_required' and captured == []


def test_queued_delivery_does_not_reserve_a_platform_submission_claim(tmp_path, monkeypatch):
    from src.content_factory import creative_delivery as delivery
    from src.operations_accounts import browser_control_runtime as control
    fake = {'account_key':'account01', 'account_uuid':'fixture:one', 'title':'fixture',
            'description':'fiction', 'fictional_story':True, 'video':{'path':'fixture.mp4'},
            'review':{'path':'fixture-review.json'}}
    monkeypatch.setattr(delivery, 'validate_delivery', lambda path, adapter: fake)
    monkeypatch.setattr(control, 'enabled', lambda: True)
    monkeypatch.setattr(control, 'is_managed_account', lambda key: False)
    monkeypatch.setattr(control, 'queue_publish_request', lambda *a, **kw: {'command_id':'same-job'})
    result = delivery.publish_delivery(tmp_path/'delivery.json', SimpleNamespace())
    assert result['status'] == 'queued' and result['platform_submission_started'] is False
    assert not (tmp_path/'submission.json').exists()
    assert (tmp_path/'publish_queue_receipt.json').exists()
