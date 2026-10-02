"""Offline prompt-revision entry checks; synthetic clients create no approval."""
import copy
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts import revise_opening_frame_plan as cli
from scripts import run_script_video as runner
from src.content_factory.ark_opening_frame import PLAN_SCHEMA
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceConfig
from test_reviewed_storyboard_direction import staged


@pytest.fixture
def case(staged, tmp_path, monkeypatch):
    script, source, proof = staged
    for index, character in enumerate(script['characters']):
        character.update(identity=f'合成身份{index}', appearance=f'当前冻结外观{index}',
                         wardrobe=f'当前冻结服装{index}')
    runner.write(source, script)
    proof['script_json_sha256'] = runner.sha(source)
    monkeypatch.setattr('src.trend_intelligence.saved_script_review.require_current_saved_script_review',
                        lambda path: copy.deepcopy(proof))
    config = SeedanceConfig(api_key='synthetic-key-only', base_url=ARK_BASE_URL,
                            model=ARK_MINI_MODEL, provider='ark_api')
    monkeypatch.setattr(SeedanceConfig, 'from_env', classmethod(lambda cls, *a, **kw: config))
    monkeypatch.setattr(cli, 'settings', SimpleNamespace(SCRIPT_LLM_MODEL='MiniMax-M3', LLM_MODEL='fallback'))
    folder = tmp_path / 'run'
    manifest = runner.prepare(folder, source, 'Synthetic test only', provider='ark_api')
    previous = folder / 'previous_plan.json'
    runner.write(previous, {'schema': PLAN_SCHEMA, 'shot_id': 'S01',
                           'script_sha256': manifest['script_sha256'],
                           'direction_sha256': manifest['direction_sha256'],
                           'prompt': '压缩后的旧提示，未包含实际外观和首态。'})
    feedback = folder / 'feedback.md'
    feedback.write_text('合成测试反馈。', encoding='utf-8')
    output = folder / 'revision'
    monkeypatch.setattr(cli.sys, 'argv', ['revise_opening_frame_plan.py', '--run-dir', str(folder),
        '--previous-plan', str(previous), '--feedback', str(feedback), '--output-dir', str(output)])
    return SimpleNamespace(folder=folder, previous=previous, feedback=feedback,
                           output=output, script=script, source=source)


def fake_client(monkeypatch, raw, *, error=None, metadata=None, init_error=None, provider='synthetic'):
    calls = []
    class Client:
        provider_name = provider
        def __init__(self, **kwargs):
            calls.append(('init', kwargs))
            if init_error:
                raise init_error('Synthetic client initialization failure')
            self.provider = SimpleNamespace(last_response_metadata=metadata or {'synthetic': True})
        def chat_completion_tracked(self, messages, **kwargs):
            calls.append(('call', copy.deepcopy(messages), kwargs))
            if error:
                raise error('Synthetic response outcome unknown')
            return raw
    monkeypatch.setattr(cli, 'LLMClient', Client)
    return calls


def test_revision_reads_current_frozen_opening_and_preserves_all_prior_files(case, monkeypatch):
    before = {path: path.read_bytes() for path in case.folder.rglob('*') if path.is_file()}
    calls = fake_client(monkeypatch, '{"prompt":"新的合成静态构图描述。"}')
    cli.main()
    assert len([row for row in calls if row[0] == 'call']) == 1
    assert calls[0][1]['max_retries'] == 0
    assert calls[0][1]['extra_body']['thinking']['type'] == 'disabled'
    assert calls[1][2]['use_cache'] is False
    payload = json.loads(calls[1][1][1]['content'])
    opening = payload['frozen_opening']
    assert opening['script_sha256'] == runner.sha(case.folder / 'locked_script.json')
    for key in ('scene', 'blocking', 'camera', 'lighting', 'start_frame',
                'shot_size', 'camera_angle', 'camera_movement', 'participants'):
        assert opening['shot'][key] == case.script['shots'][0][key]
    assert 'end_frame' not in opening['shot'] and 'action' not in opening['shot']
    assert opening['characters'] == case.script['characters']
    assert 'frozen_opening' in calls[1][1][0]['content']
    candidate = runner.read(case.output / 'opening_frame_plan.json')
    previous = runner.read(case.previous)
    assert {key: candidate[key] for key in previous if key != 'prompt'} == {
        key: previous[key] for key in previous if key != 'prompt'}
    assert candidate['provenance']['text_review'] == candidate['provenance']['media_review'] == 'pending'
    run = runner.read(case.output / 'run.json')
    assert run['status'] == 'candidate_pending_independent_review' and run['model_calls'] == 1
    assert datetime.fromisoformat(run['finished_at']) >= datetime.fromisoformat(run['started_at'])
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert runner.read(case.output / 'request.json') == calls[1][1]


@pytest.mark.parametrize('raw', ['{invalid', '', '{"prompt":""}', '{"prompt":"x","action":"new"}',
                                  '{"prompt":"first","prompt":"second"}', 'null', '["prompt"]'])
def test_bad_model_output_is_saved_failed_without_candidate_or_retry(case, monkeypatch, raw):
    metadata = {'finish_reason': 'stop', 'response_id': 'synthetic-response'}
    calls = fake_client(monkeypatch, raw, metadata=metadata)
    with pytest.raises((ValueError, TypeError)):
        cli.main()
    run = runner.read(case.output / 'run.json')
    assert run['status'] == 'failed_model_output' and run['model_calls'] == 1
    assert run['error_type'] and datetime.fromisoformat(run['finished_at'])
    assert runner.read(case.output / 'model_output.json') == raw
    assert runner.read(case.output / 'response_metadata.json') == metadata
    assert run['output_sha256'] == runner.sha(case.output / 'model_output.json')
    assert not (case.output / 'opening_frame_plan.json').exists()
    assert len([row for row in calls if row[0] == 'call']) == 1


@pytest.mark.parametrize('raises', [False, True])
def test_unknown_network_result_keeps_unknown_completed_record_and_does_not_retry(case, monkeypatch, raises):
    metadata = {'error_type': 'APIConnectionError'}
    calls = fake_client(monkeypatch, None, error=ConnectionError if raises else None, metadata=metadata)
    with pytest.raises((ConnectionError, TypeError)):
        cli.main()
    run = runner.read(case.output / 'run.json')
    assert run['status'] == 'outcome_unknown' and run['model_calls'] == 1
    assert run['provider_error_type'] == 'APIConnectionError'
    assert datetime.fromisoformat(run['finished_at'])
    assert runner.read(case.output / 'response_metadata.json') == metadata
    if not raises:
        assert runner.read(case.output / 'model_output.json') is None
    assert not (case.output / 'opening_frame_plan.json').exists()
    assert len([row for row in calls if row[0] == 'call']) == 1
    with pytest.raises(FileExistsError):
        cli.main()
    assert len([row for row in calls if row[0] == 'call']) == 1


def test_known_length_response_without_content_is_failed_output(case, monkeypatch):
    fake_client(monkeypatch, None, metadata={'response_id': 'synthetic', 'finish_reason': 'length'})
    with pytest.raises(TypeError):
        cli.main()
    run = runner.read(case.output / 'run.json')
    assert run['status'] == 'failed_model_output' and run['model_calls'] == 1
    assert not (case.output / 'opening_frame_plan.json').exists()


@pytest.mark.parametrize('mode', ['init_error', 'mock'])
def test_preflight_client_failure_is_recorded_without_model_call(case, monkeypatch, mode):
    calls = fake_client(monkeypatch, '{}', init_error=RuntimeError if mode == 'init_error' else None,
                        provider='mock' if mode == 'mock' else 'synthetic')
    with pytest.raises((RuntimeError, ValueError)):
        cli.main()
    run = runner.read(case.output / 'run.json')
    assert run['status'] == 'preflight_rejected' and run['model_calls'] == 0
    assert run['error_type'] and datetime.fromisoformat(run['finished_at'])
    assert len([row for row in calls if row[0] == 'call']) == 0
    assert not (case.output / 'opening_frame_plan.json').exists()
