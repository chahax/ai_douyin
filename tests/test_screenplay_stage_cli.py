"""Offline main-entry checks; synthetic reviews are never production approvals."""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_screenplay_stage as stage
from src.trend_intelligence.script_screenplay import STORY_REVIEW_CHECKS
from story_review_fixture import enrich_story_review
from test_script_outline import workflow
from test_script_screenplay import screenplay, production as legacy_production


def production(story, kind='short'):
    result = legacy_production(story, kind)
    for shot in result['shots']:
        shot['emotion_and_performance'] = '触发：合成冲突；情绪：受阻；语速：偏快；语气：坚定；重音：确认；停顿：无刻意停顿；余波：紧绷'
    return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


@pytest.fixture
def case(tmp_path, monkeypatch, workflow):
    root = tmp_path / 'project'
    prompts = root / 'src/trend_intelligence/prompts'
    prompts.mkdir(parents=True)
    for name in ('script_screenplay.md', 'script_screenplay_production.md', 'script_screenplay_production_revision.md'):
        (prompts / name).write_bytes((stage.ROOT / 'src/trend_intelligence/prompts' / name).read_bytes())
    monkeypatch.setattr(stage, 'ROOT', root)
    monkeypatch.setattr(stage, 'settings', SimpleNamespace(SCRIPT_LLM_MODEL='MiniMax-M3', LLM_MODEL='fallback',
        SCRIPT_LLM_THINKING='disabled', SCRIPT_LLM_TIMEOUT_SECONDS=30, SCRIPT_LLM_MAX_TOKENS=24000))
    folder = root / 'data/pre_video_scripts/_runs/original'
    request = write(folder / 'request.json', workflow)
    sources = json.loads(workflow[1]['content'])['source_evidence']
    full = write(folder / 'source_evidence.full.json', sources)
    feedback = root / 'feedback.md'
    feedback.write_text('核对本轮实际动作，不生成视频。', encoding='utf-8')
    def story(kind='short'):
        value = screenplay(kind)
        if kind == 'short':
            for shot, seconds in zip(value['version']['shots'], [5, 10, 10, 10, 5, 5]):
                shot['duration_seconds'] = seconds
        value['version']['reference_usage'][0]['source_id'] = sources[0]['source_id']
        return value
    def related(kind='short', folder_name='related'):
        path = write(root / 'data/qa' / folder_name / 'screenplay.json', story(kind))
        write(path.with_name('run.json'), {
            'schema': 'script_screenplay_stage_run/v1', 'stage': 'story', 'kind': kind,
            'status': 'candidate_pending_independent_review', 'candidate_sha256': stage.sha(path.read_bytes()),
            'workflow_request_sha256': stage.sha(request.read_bytes()),
            'source_evidence_sha256': stage.sha(full.read_bytes())})
        return path
    def review(path):
        data = json.loads(path.read_bytes())
        rows = data['version']['shots']
        return write(path.with_name('editorial_review.json'), enrich_story_review({
            'schema': 'screenplay_editorial_review/v1', 'decision': 'passed',
            'candidate_sha256': stage.sha(path.read_bytes()),
            'workflow_request_sha256': stage.sha(request.read_bytes()),
            'source_evidence_sha256': stage.sha(full.read_bytes()),
            'checks': {key: True for key in STORY_REVIEW_CHECKS}, 'unresolved_issues': [],
            'shot_reviews': [{'shot_id': s['shot_id'], 'decision': 'passed', 'action_quote': s['action'],
                              'finding': '合成测试，只验证协议。'} for s in rows],
            'result_review': {'shot_id': rows[-1]['shot_id'], 'decision': 'passed',
                             'action_quote': rows[-1]['action'], 'finding': '合成结果协议。'}}, data))
    output = root / 'data/qa/new_stage'
    def argv(*extra):
        monkeypatch.setattr(stage.sys, 'argv', ['run_screenplay_stage.py', '--workflow-request', str(request),
            '--editor-feedback-file', str(feedback), '--output-dir', str(output), '--kind', 'short',
            '--reference-source-id', sources[0]['source_id'], *map(str, extra)])
    argv()
    return SimpleNamespace(root=root, request=request, full=full, feedback=feedback, sources=sources,
        output=output, story=story, related=related, review=review, argv=argv)


def client_for(monkeypatch, response, *, init_error=False):
    calls = []
    class Client:
        provider_name = 'offline_fixture'
        def __init__(self, **kwargs):
            calls.append(('init', kwargs))
            if init_error:
                raise RuntimeError('synthetic initialization failure')
            self.provider = SimpleNamespace(last_response_metadata={'synthetic': True})
        def chat_completion_tracked(self, messages, **kwargs):
            calls.append(('call', copy.deepcopy(messages), kwargs))
            return response
    monkeypatch.setattr(stage, 'LLMClient', Client)
    return calls


def state_for(case, expected_status, calls, expected_calls=0):
    state = json.loads((case.output / 'run.json').read_bytes())
    assert state['status'] == expected_status and state['model_calls'] == expected_calls
    assert len([c for c in calls if c[0] == 'call']) == expected_calls
    start, finish = (datetime.fromisoformat(state[key]) for key in ('started_at_bjt', 'finished_at_bjt'))
    assert start.utcoffset() == finish.utcoffset() == timedelta(hours=8) and finish >= start
    assert state['media_generation'] is False
    return state


@pytest.mark.parametrize('option,kind', [('--companion-screenplay', 'short'), ('--previous-screenplay', 'long')])
def test_wrong_related_version_is_rejected_before_client_initialization(case, monkeypatch, option, kind):
    path = case.related(kind)
    originals = {p: p.read_bytes() for p in (path, path.with_name('run.json'))}
    case.argv(option, path)
    calls = client_for(monkeypatch, json.dumps(case.story()))
    with pytest.raises(ValueError, match='关联稿'):
        stage.main()
    state_for(case, 'preflight_rejected', calls)
    assert calls == [] and all(path.read_bytes() == raw for path, raw in originals.items())


@pytest.mark.parametrize('field,value', [
    ('stage', 'production'), ('status', 'running'), ('schema', 'legacy/v0'),
    ('candidate_sha256', '0' * 64), ('workflow_request_sha256', '0' * 64),
    ('source_evidence_sha256', '0' * 64),
])
def test_related_story_must_match_its_completed_original_run(case, monkeypatch, field, value):
    path = case.related()
    run_path = path.with_name('run.json')
    run = json.loads(run_path.read_bytes())
    run[field] = value
    write(run_path, run)
    case.argv('--previous-screenplay', path)
    calls = client_for(monkeypatch, json.dumps(case.story()))
    with pytest.raises(ValueError, match='关联稿'):
        stage.main()
    state_for(case, 'preflight_rejected', calls)
    assert calls == []


def test_related_kind_label_cannot_hide_wrong_actual_duration(case, monkeypatch):
    path = case.related()
    data = json.loads(path.read_bytes())
    data['version']['shots'][0]['duration_seconds'] += 1
    write(path, data)
    run_path = path.with_name('run.json')
    run = json.loads(run_path.read_bytes())
    run['candidate_sha256'] = stage.sha(path.read_bytes())
    write(run_path, run)
    case.argv('--previous-screenplay', path)
    calls = client_for(monkeypatch, '')
    with pytest.raises(ValueError, match='total duration'):
        stage.main()
    state_for(case, 'preflight_rejected', calls)
    assert calls == []


def test_invalid_approval_is_zero_call_and_leaves_failed_preflight_record(case, monkeypatch):
    path = case.related()
    review = case.review(path)
    data = json.loads(review.read_bytes())
    data['candidate_sha256'] = '0' * 64
    write(review, data)
    case.argv('--stage', 'production', '--screenplay', path, '--story-review', review)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError, match='审核'):
        stage.main()
    state = state_for(case, 'preflight_rejected', calls)
    assert state['error_type'] == 'ValueError' and state['error'] and calls == []
    assert state['inputs']['story_review']['sha256'] == stage.sha(review.read_bytes())
    assert not (case.output / 'compiled_version.json').exists()


@pytest.mark.parametrize('field,earlier', [('decision', '"failed"'), ('dialogue_action_alignment', 'false')])
def test_duplicate_approval_key_is_zero_call_not_last_value_wins(case, monkeypatch, field, earlier):
    path = case.related()
    review = case.review(path)
    raw = review.read_text(encoding='utf-8')
    marker = json.dumps(field) + ': '
    raw = raw.replace(marker, marker + earlier + ', ' + marker, 1)
    review.write_text(raw, encoding='utf-8')
    case.argv('--stage', 'production', '--screenplay', path, '--story-review', review)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        stage.main()
    state_for(case, 'preflight_rejected', calls)
    assert calls == [] and not (case.output / 'compiled_version.json').exists()


def test_duplicate_model_action_is_preserved_and_rejected(case, monkeypatch):
    raw = json.dumps(case.story(), ensure_ascii=False)
    raw = raw.replace('"action": ', '"action": "earlier conflicting action", "action": ', 1)
    calls = client_for(monkeypatch, raw)
    with pytest.raises(ValueError, match='duplicate JSON key'):
        stage.main()
    state_for(case, 'failed', calls, 1)
    assert (case.output / 'model_output.json').read_text(encoding='utf-8') == raw
    assert not (case.output / 'screenplay.json').exists()


@pytest.mark.parametrize('option', ['--companion-screenplay', '--previous-screenplay'])
def test_production_cannot_mix_story_revision_dependencies(case, monkeypatch, option):
    path = case.related()
    case.argv('--stage', 'production', '--screenplay', path, '--story-review', case.review(path), option, path)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError, match='不能混用'):
        stage.main()
    state_for(case, 'preflight_rejected', calls)
    assert calls == []


def test_invalid_model_json_is_preserved_without_candidate_or_retry(case, monkeypatch):
    raw = '{"broken":'
    calls = client_for(monkeypatch, raw)
    with pytest.raises(json.JSONDecodeError):
        stage.main()
    state = state_for(case, 'failed', calls, 1)
    assert (case.output / 'model_output.json').read_text(encoding='utf-8') == raw
    assert state['model_output_sha256'] == stage.sha(raw.encode())
    assert not (case.output / 'screenplay.json').exists() and 'candidate_sha256' not in state


def test_client_initialization_failure_is_not_a_model_call(case, monkeypatch):
    calls = client_for(monkeypatch, '', init_error=True)
    with pytest.raises(RuntimeError, match='initialization'):
        stage.main()
    state_for(case, 'preflight_rejected', calls)


@pytest.mark.parametrize('run_stage', ['story', 'production'])
def test_success_is_pending_with_twenty_source_binding_and_unchanged_inputs(case, monkeypatch, run_stage):
    path = case.related()
    review = case.review(path)
    if run_stage == 'production':
        case.argv('--stage', 'production', '--screenplay', path, '--story-review', review)
        response = production(case.story())
    else:
        companion = case.related('long', 'companion')
        case.argv('--previous-screenplay', path, '--companion-screenplay', companion)
        response = case.story()
    originals = {p: p.read_bytes() for p in (case.request, case.full, path, review, path.with_name('run.json'))}
    calls = client_for(monkeypatch, json.dumps(response, ensure_ascii=False))
    stage.main()
    state = state_for(case, 'candidate_pending_independent_review', calls, 1)
    name = 'screenplay.json' if run_stage == 'story' else 'compiled_version.json'
    assert state['candidate_sha256'] == stage.sha((case.output / name).read_bytes())
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert 'passed' not in state and 'approved' not in state
    assert len(json.loads((case.output / 'source_evidence.full.json').read_bytes())) == 20
    sent = json.loads(calls[-1][1][1]['content'])
    assert len(sent['source_evidence']) == 1 and len(sent['source_overview']) == 20
    assert list(sent)[-1] == 'current_editor_feedback'
    if run_stage == 'story':
        assert state['inputs']['previous_screenplay']['run_sha256'] == stage.sha(path.with_name('run.json').read_bytes())
    else:
        compiled = json.loads((case.output / name).read_bytes())
        assert [s['action'] for s in compiled['shots']] == [s['action'] for s in case.story()['version']['shots']]


def test_existing_output_is_never_overwritten(case, monkeypatch):
    existing = write(case.output / 'run.json', {'status': 'original_existing_run'})
    before = existing.read_bytes()
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(FileExistsError):
        stage.main()
    assert existing.read_bytes() == before and calls == []
