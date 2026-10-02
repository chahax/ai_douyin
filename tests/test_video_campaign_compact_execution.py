"""Offline cross-gate regressions: no real media decisions or paid calls."""
import copy

import pytest

from scripts import run_script_video as runner
from src.content_factory import video_campaign as campaign
from src.content_factory.seedance_client import SeedanceClient
from test_ark_opening_frame import prepared
from test_compact_execution import case, staged, review


@pytest.fixture
def retry_case(case):
    path = case['folder'].parent / 'campaign.json'
    failed = [{'id': f'attempt_{number:03}', 'run_dir': str(case['folder'].parent / f'old_{number}'),
               'series_id': 'series_001', 'shot': 'S01', 'status': 'failed',
               'script_sha256': f'old-script-{number}', 'prompt_sha256': f'old-prompt-{number}'}
              for number in range(1, 8)]
    failed[-1].update(script_sha256=case['manifest']['script_sha256'],
                      prompt_sha256=case['plan']['original_prompt_sha256'])
    campaign.write(path, {'schema': 'sequential_video_campaign/v1', 'max_failed_outputs': 10,
        'authorization': 'Synthetic fixture only', 'provider': 'ark_api', 'model': case['config'].model,
        'shots': case['manifest']['shots'], 'attempts': failed, 'failed_outputs': 7,
        'status': 'awaiting_upstream_revision', 'current_series_id': 'series_001',
        'series': [{'id': 'series_001', 'runs': [str(case['folder'])]}]})
    manifest = runner.read(case['folder'] / 'production.json')
    manifest.update(campaign_path=str(path), campaign_series_id='series_001')
    runner.write(case['folder'] / 'production.json', manifest)
    case.update(campaign=path, manifest=manifest)
    review(case)
    runner.submit(case['folder'], 'S01', SeedanceClient(case['config']), [], first_frame=case['image'],
                  execution_plan=case['plan_path'], execution_review=case['review_path'], preview=True)
    case['record'] = runner.read(case['folder'] / 'S01.workflow.preview.json')
    return case


def reserve(case, record=None):
    return campaign.reserve(case['folder'], case['manifest'], record or case['record'])


def test_real_plan_review_image_and_payload_allow_same_script_without_erasing_seven_failures(retry_case, monkeypatch):
    item = retry_case
    before = campaign.read(item['campaign'])
    calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda self, payload: calls.append(payload) or {'id': 'synthetic-only'})
    runner.submit(item['folder'], 'S01', SeedanceClient(item['config']), [], first_frame=item['image'],
                  execution_plan=item['plan_path'], execution_review=item['review_path'])
    saved = runner.read(item['folder'] / 'S01.json')
    after = campaign.read(item['campaign'])
    assert len(calls) == 1 and calls[0] == saved['request'] == item['record']['request']
    assert after['failed_outputs'] == 7 and after['max_failed_outputs'] == 10
    assert after['attempts'][:-1] == before['attempts']
    attempt = after['attempts'][-1]
    assert attempt['status'] == 'awaiting_generation_or_review' and attempt['series_id'] == 'series_001'
    assert attempt['upstream_revision'] == saved['upstream_revision']
    assert attempt['upstream_revision']['previous_failed_attempt_id'] == 'attempt_007'
    assert attempt['upstream_revision']['source_script_unchanged'] is True
    assert attempt['upstream_revision']['plan_sha256'] == runner.sha(item['plan_path'])
    assert attempt['upstream_revision']['review_sha256'] == runner.sha(item['review_path'])
    with pytest.raises(ValueError, match='already exists'):
        runner.submit(item['folder'], 'S01', SeedanceClient(item['config']), [], first_frame=item['image'],
                      execution_plan=item['plan_path'], execution_review=item['review_path'])
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['flag_only', 'missing_review', 'plan_bytes', 'review_bytes',
    'image_bytes', 'record_prompt', 'record_image_sha', 'payload_text', 'payload_image', 'payload_model',
    'payload_duration', 'payload_resolution', 'payload_audio', 'payload_tail', 'payload_ratio'])
def test_same_script_exception_rejects_forged_or_stale_execution_before_reservation(retry_case, change):
    item = retry_case
    record = copy.deepcopy(item['record'])
    if change == 'flag_only':
        record['execution_prompt'] = {'schema': 'compact_execution_binding/v1', 'approved': True}
    elif change == 'missing_review':
        item['review_path'].unlink()
    elif change == 'plan_bytes':
        item['plan_path'].write_bytes(item['plan_path'].read_bytes() + b'\n')
    elif change == 'review_bytes':
        item['review_path'].write_bytes(item['review_path'].read_bytes() + b'\n')
    elif change == 'image_bytes':
        item['image'].write_bytes(item['image'].read_bytes() + b'\n')
    elif change == 'record_prompt':
        record['prompt'] += ' Added action.'
    elif change == 'record_image_sha':
        record['first_frame_sha256'] = '0' * 64
    elif change == 'payload_text':
        record['request']['content'][0]['text'] += ' Added action.'
    elif change == 'payload_image':
        record['request']['content'][1]['image_url']['url'] = 'https://synthetic.invalid/other.png'
    else:
        key, value = {'payload_model': ('model', 'other-model'), 'payload_duration': ('duration', 15),
            'payload_resolution': ('resolution', '720p'), 'payload_audio': ('generate_audio', False),
            'payload_tail': ('return_last_frame', False), 'payload_ratio': ('ratio', '16:9')}[change]
        record['request'][key] = value
    before = item['campaign'].read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        reserve(item, record)
    assert item['campaign'].read_bytes() == before


@pytest.mark.parametrize('change', ['unknown', 'unreviewed', 'ten_failures', 'hold', 'other_series'])
def test_valid_compact_plan_cannot_release_outstanding_work_or_reset_campaign_guards(retry_case, change):
    item = retry_case
    data = campaign.read(item['campaign'])
    if change in {'unknown', 'unreviewed'}:
        data['attempts'].append({'id': 'synthetic_pending', 'shot': 'S01', 'series_id': 'series_001',
            'status': 'awaiting_generation_or_review' if change == 'unknown' else 'awaiting_review'})
    elif change == 'ten_failures':
        data['failed_outputs'] = 10
    elif change == 'hold':
        data['holds'] = ['synthetic prerequisite']
    else:
        data['current_series_id'] = 'series_002'
        data['series'].append({'id': 'series_002', 'runs': []})
    campaign.write(item['campaign'], data)
    before = item['campaign'].read_bytes()
    with pytest.raises(ValueError):
        reserve(item)
    assert item['campaign'].read_bytes() == before


def test_identical_compact_prompt_cannot_be_respent_by_rehashing_review_or_new_run_flag(retry_case):
    item = retry_case
    data = campaign.read(item['campaign'])
    data['attempts'][-1]['prompt_sha256'] = item['record']['prompt_sha256']
    campaign.write(item['campaign'], data)
    before = item['campaign'].read_bytes()
    with pytest.raises(ValueError, match='upstream script'):
        reserve(item)
    assert item['campaign'].read_bytes() == before
