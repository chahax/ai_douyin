from src.content_factory.video_provider_failure import classify_failure
import pytest


def test_output_policy_failure_is_not_a_visual_review_or_free_retry():
    result = classify_failure({'id': 'task', 'status': 'failed', 'usage': None,
        'error': {'code': 'OutputVideoSensitiveContentDetected.PolicyViolation',
                  'message': 'output video may be related to copyright restrictions'}})
    assert result['stage'] == 'output_video'
    assert result['next_action'] == 'provider_review_required'
    assert result['billing_status'] == 'unknown'
    assert result['cause_confirmed'] is False
    assert result['counts_as_visual_review_failure'] is False
    assert result['automatic_retry_allowed'] is False
    assert result['continuation_allowed'] is False


def test_audio_input_and_unknown_are_not_diagnosed_as_video_copyright():
    for code, stage in [('OutputAudioSensitiveContentDetected', 'output_audio'),
                        ('InputImageSensitiveContentDetected', 'input'),
                        ('SetLimitExceeded', 'unknown')]:
        result = classify_failure({'status': 'failed', 'error': {'code': code}})
        assert result['stage'] == stage
        assert not result['cause_confirmed']
    assert classify_failure({'status': 'running'}) is None
    assert classify_failure({'status': 'succeeded'}) is None


def test_policy_gate_stops_submission_before_any_provider_call(tmp_path, monkeypatch):
    from scripts import run_script_video as runner
    monkeypatch.setattr(runner, 'locked', lambda folder: (
        {'generation_gate': 'provider_review_required'}, {}))
    with pytest.raises(ValueError, match='requires provider review'):
        runner.submit(tmp_path, 'S03', object(), [])
