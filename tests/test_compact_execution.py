"""Synthetic execution-plan gates. No actual image, voice or video approval."""
import copy
import json
from datetime import datetime, timezone

import httpx
import pytest

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening, compact_execution as compact
from src.content_factory.seedance_client import SeedanceClient
from test_ark_opening_frame import prepared, submit, bind_synthetic_review, CREATED
from test_reviewed_storyboard_direction import staged as base_staged


@pytest.fixture
def staged(tmp_path):
    script, source, proof = base_staged.__wrapped__(tmp_path)
    for shot in script['shots']:
        shot['subtitle'] = shot['dialogue']
    script['shots'][0]['start_frame'] = '甲左乙右；P1（甲方合同）：甲面前；P2（乙方合同）：乙面前；P3（黑笔）：桌中。'
    script['shots'][0]['action'] = '角色甲左手推P1，右手越过P3上方指向P1；角色乙双手不动。'
    script['shots'][0]['end_frame'] = '角色甲指向P1，角色乙看P1；P1（甲方合同）：桌中；P2（乙方合同）：乙面前；P3（黑笔）：桌中。'
    script['shots'][1]['start_frame'] = script['shots'][0]['end_frame']
    runner.write(source, script)
    proof['script_json_sha256'] = runner.sha(source)
    return script, source, proof


@pytest.fixture
def case(prepared, monkeypatch):
    submit(prepared)  # HTTP mock only, original synthetic image receipt.
    image = prepared['attempt'] / opening.IMAGE_NAME
    bind_synthetic_review(prepared, 'S01', image)
    monkeypatch.setattr(opening, '_now', lambda: datetime.fromtimestamp(CREATED + 60, timezone.utc))
    path = prepared['folder'] / 'compact/plan.json'
    plan = compact.prepare_compact_execution(prepared['folder'], image, path, prepared['config'])
    return {**prepared, 'image': image, 'plan_path': path, 'plan': plan,
            'review_path': path.with_name('independent_review.json')}


def review(case):
    plan = case['plan']
    report = {'schema': compact.REVIEW_SCHEMA, 'decision': 'passed',
        'plan_path': str(case['plan_path'].resolve()), 'plan_sha256': runner.sha(case['plan_path']),
        'prompt_sha256': plan['prompt_sha256'], 'script_sha256': plan['source']['script_sha256'],
        'direction_sha256': plan['source']['direction_sha256'],
        'first_frame_sha256': plan['source']['first_frame']['sha256'],
        'reviewed_at': '2026-09-11T00:01:00+08:00',
        'checks': {key: True for key in compact.REVIEW_CHECKS},
        'notes': 'Synthetic gate test only, not actual text or media certification.'}
    runner.write(case['review_path'], report)
    return report


def verify(case):
    return compact.require_compact_execution(case['folder'], case['image'], case['plan_path'],
                                             case['review_path'], case['config'])


def test_projection_preserves_source_text_and_has_one_dialogue_no_model_subtitles(case):
    plan = case['plan']; shot = case['script']['shots'][0]
    assert plan['text_review'] == plan['media_review'] == 'pending' and plan['model_calls'] == 0
    assert plan['prompt'].count(shot['dialogue']) == 1
    assert '不生成字幕、水印或额外画面标题' in plan['prompt']
    assert '保留首图合同已有印刷文字；后期按唯一对白统一字幕。' in plan['prompt']
    assert plan['subtitle_source']['text'] == shot['subtitle'] == shot['dialogue']
    assert plan['subtitle_source']['model_burn_in'] is False
    for key in ('action', 'emotion_and_performance', 'audio', 'end_frame'):
        assert plan['source_fields'][key]['value'] == shot[key]
        rendered = opening.render_opening_prompt(shot[key], shot['start_frame'])[0]
        assert rendered in plan['prompt']
    assert 'P1' not in plan['prompt'] and '甲方合同' in plan['prompt']
    assert '剪辑衔接' not in plan['prompt'] and '连续性要求' not in plan['prompt']
    assert plan['original_prompt'] == runner.compile_default_first_frame_prompt(case['script'], shot, case['direction'])
    assert runner.read(case['folder'] / 'locked_script.json') == case['script']


def test_prepare_never_overwrites_previous_plan(case):
    before = case['plan_path'].read_bytes()
    with pytest.raises(ValueError):
        compact.prepare_compact_execution(case['folder'], case['image'], case['plan_path'], case['config'])
    assert case['plan_path'].read_bytes() == before


def test_review_is_separate_and_missing_review_blocks_video_api(case, monkeypatch):
    calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *args: calls.append(args))
    with pytest.raises(FileNotFoundError):
        runner.submit(case['folder'], 'S01', SeedanceClient(case['config']), [], first_frame=case['image'],
                      execution_plan=case['plan_path'], execution_review=case['review_path'])
    assert calls == [] and not (case['folder'] / 'S01.json').exists()


@pytest.mark.parametrize('field,value', [('decision', 'failed'), ('plan_sha256', '0' * 64),
    ('prompt_sha256', '0' * 64), ('first_frame_sha256', '0' * 64), ('script_sha256', '0' * 64),
    ('direction_sha256', '0' * 64), ('notes', ''), ('checks', {})])
def test_stale_or_incomplete_independent_review_is_rejected(case, field, value):
    report = review(case); report[field] = value
    runner.write(case['review_path'], report)
    with pytest.raises(ValueError):
        verify(case)


@pytest.mark.parametrize('field', ['prompt', 'subtitle_source', 'source_fields', 'render_recipe'])
def test_rehashed_plan_tampering_cannot_pass_source_replay(case, field):
    plan = copy.deepcopy(case['plan'])
    if field == 'prompt':
        plan[field] += '新增对白和动作。'
        plan['prompt_sha256'] = opening._sha(plan[field].encode())
    elif field == 'subtitle_source':
        plan[field]['text'] = '不相同的字幕。'
    elif field == 'source_fields':
        plan[field]['action']['value'] = '伪造源动作。'
    else:
        plan[field]['prop_names']['P3'] = '另一物件'
    runner.write(case['plan_path'], plan); case['plan'] = plan
    review(case)  # Rehashed synthetic report cannot turn changed source into a pass.
    with pytest.raises(ValueError, match='reproduce'):
        verify(case)


def test_image_review_bytes_are_part_of_the_binding(case):
    review(case)
    path = case['folder'] / 'frame_reviews/S01.json'
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='reproduce'):
        verify(case)


def test_source_review_rechecked_after_compact_plan_preparation(case, monkeypatch):
    review(case)
    monkeypatch.setattr(runner, 'require_project_script_review', lambda *args: {'current_passed': False})
    with pytest.raises(ValueError, match='current passed'):
        verify(case)


def test_preview_is_exact_compact_request_and_default_stays_original(case):
    review(case); client = SeedanceClient(case['config'])
    runner.submit(case['folder'], 'S01', client, [], first_frame=case['image'], preview=True,
                  execution_plan=case['plan_path'], execution_review=case['review_path'])
    record = runner.read(case['folder'] / 'S01.workflow.preview.json')
    assert record['prompt'] == case['plan']['prompt']
    assert record['request']['content'][0]['text'] == case['plan']['prompt']
    assert record['request']['generate_audio'] is True and record['request']['return_last_frame'] is True
    assert record['model_subtitles'] is False and record['subtitle_source'] == case['plan']['subtitle_source']
    assert record['execution_prompt']['original_prompt_sha256'] == case['plan']['original_prompt_sha256']
    runner.submit(case['folder'], 'S01', client, [], first_frame=case['image'], preview=True)
    ordinary = runner.read(case['folder'] / 'S01.workflow.preview.json')
    assert ordinary['prompt'] == case['plan']['original_prompt']
    assert 'execution_prompt' not in ordinary and 'model_subtitles' not in ordinary


def test_valid_actual_submission_keeps_review_and_subtitle_trace_and_is_not_retried(case, monkeypatch):
    review(case); calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda self, payload: calls.append(payload) or {'id': 'synthetic-task'})
    client = SeedanceClient(case['config'])
    runner.submit(case['folder'], 'S01', client, [], first_frame=case['image'],
                  execution_plan=case['plan_path'], execution_review=case['review_path'])
    record = runner.read(case['folder'] / 'S01.json')
    assert len(calls) == 1 and calls[0] == record['request']
    assert record['prompt_sha256'] == case['plan']['prompt_sha256']
    assert record['execution_prompt']['review_sha256'] == runner.sha(case['review_path'])
    assert record['subtitle_source']['text'] == case['script']['shots'][0]['dialogue']
    with pytest.raises(ValueError, match='already exists'):
        runner.submit(case['folder'], 'S01', client, [], first_frame=case['image'],
                      execution_plan=case['plan_path'], execution_review=case['review_path'])
    assert len(calls) == 1


@pytest.mark.parametrize('shot,frame,refs,plan,review_file', [
    ('S02', True, [], True, True), ('S01', False, [], True, True),
    ('S01', True, ['unused'], True, True), ('S01', True, [], True, False),
])
def test_opt_in_scope_rejected_before_any_provider_call(case, shot, frame, refs, plan, review_file):
    class Client:
        def __getattr__(self, name):
            raise AssertionError('Provider accessed before scope validation: ' + name)
    with pytest.raises(ValueError):
        runner.submit(case['folder'], shot, Client(), refs, first_frame=case['image'] if frame else None,
                      execution_plan=case['plan_path'] if plan else None,
                      execution_review=case['review_path'] if review_file else None)


@pytest.mark.parametrize('change', [{'subtitle': '不同字幕'}, {'shot_id': 'S02'}, {'dialogue_mode': 'device'}])
def test_renderer_rejects_unsupported_source_instead_of_silently_rewriting(case, change):
    shot = {**case['script']['shots'][0], **change}
    with pytest.raises(ValueError):
        compact.render_compact_prompt(shot, '9:16')
