"""Known native director recovery keeps v8 evidence and its existing capacity."""
from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from src.content_factory import novel_agent_pipeline_v8 as parent
from src.content_factory import novel_agent_pipeline_v9 as pipe

_helpers = runpy.run_path(str(Path(__file__).with_name('test_novel_agent_pipeline_v8.py')))
fx = _helpers['fx']
plan = _helpers['plan']
review = _helpers['review']
success_values = _helpers['success_values']


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def invalid_plan():
    value = plan()
    value['segments'][0]['performance'][0]['reaction'] = ''
    overlapping = deepcopy(value['segments'][0]['beats'][0])
    overlapping['beat_id'] = 'B02'
    value['segments'][0]['beats'].append(overlapping)
    second = deepcopy(plan()['segments'][0])
    second['segment_id'] = 'S02'
    value['segments'].append(second)
    value['event_coverage'][0]['segment_ids'].append('S02')
    return value


@pytest.fixture
def environment(tmp_path, monkeypatch):
    canonical = tmp_path / 'canonical'
    monkeypatch.setattr(parent, 'CANONICAL_REGISTRY', canonical)
    monkeypatch.setattr(pipe, 'CANONICAL_REGISTRY', canonical)
    monkeypatch.setattr(pipe.core, '_legacy_blocks', lambda *a, **kw: [])
    source = tmp_path / 'source.txt'
    source.write_text('An original person answers someone at the door.', encoding='utf-8')
    return tmp_path, source, canonical


def stop_parent(environment, native_value=None, *, finish='stop', unknown=False):
    tmp_path, source, _ = environment
    run = tmp_path / 'parent-v8'
    parent.prepare(run, source_path=source, title='Known native test', source_kind='original',
                   brief={'max_duration_seconds': 15})
    clients = fx.FakeClients([*success_values()[:2], fx.result(
        invalid_plan() if native_value is None else native_value, finish=finish, unknown=unknown)])
    with pytest.raises((ValueError, RuntimeError)):
        parent.execute(run, clients=clients)
    assert len(clients.calls) == 3
    return run


def test_complete_known_failure_gets_only_remaining_full_candidate(environment):
    old = stop_parent(environment)
    before = snapshot(old)
    child = environment[0] / 'child'
    view = pipe.prepare_known_director_continuation(child, parent_run=old)
    assert view['calls_started'] == 0 and view['combined_calls_started'] == 3
    assert view['known_reported_tokens'] == 0 and view['combined_known_reported_tokens'] == 300
    assert pipe.preview(child)['remaining_calls'] == 17
    assert pipe.preview(child)['remaining_known_tokens'] == 499700
    assert view['stage'] == 'director_full'
    analysis = pipe.core._read(child / 'KNOWN_PARENT_ANALYSIS.json')
    codes = {row['code'] for row in analysis['diagnosis']['errors']}
    assert 'SIDECAR_FORMAT' in {row['code'] for row in analysis['original_failure']}
    assert 'DIRECTOR_BEAT_TIME' in codes
    assert 'DIRECTOR_TOTAL_DURATION' in codes
    clients = fx.FakeClients([fx.result(plan()), fx.result(review(), 'director')])
    result = pipe.execute(child, clients=clients)
    assert result['status'] == 'text_ready_for_production', result['blockers']
    assert result['calls_started'] == 2 and result['combined_calls_started'] == 5
    assert result['state']['quality_director_revisions_used'] == 1
    materials = json.loads(clients.calls[0]['messages'][-1]['content'])
    assert materials['revision_feedback']['native_director_text'] == pipe.core._read(old / 'RESPONSE_003.json')['response_text']
    assert materials['revision_feedback']['content_contract_errors'] == analysis['diagnosis']['errors']
    assert snapshot(old) == before
    assert pipe.execute(child, clients=fx.FakeClients([]))['calls_started'] == 2
    with pytest.raises(RuntimeError, match='唯一'):
        pipe.prepare_known_director_continuation(environment[0] / 'fork', parent_run=old)


def test_last_director_failure_exhausts_original_stage_not_new_directory(environment):
    old = stop_parent(environment)
    child = environment[0] / 'child'
    pipe.prepare_known_director_continuation(child, parent_run=old)
    clients = fx.FakeClients([fx.result(invalid_plan())])
    result = pipe.execute(child, clients=clients)
    assert result['status'] == 'director_revision_exhausted'
    assert result['calls_started'] == 1 and result['state']['quality_director_revisions_used'] == 1
    assert not (child / 'PRODUCTION_HANDOFF.json').exists()
    assert pipe.execute(child, clients=fx.FakeClients([]))['calls_started'] == 1


def test_provably_missing_array_closer_adopts_original_native_then_reviews(environment):
    text = json.dumps(plan(), ensure_ascii=False)
    marker = '"Face and eyes readable in medium close-up."}]}]'
    assert marker in text
    damaged = text.replace(marker, '"Face and eyes readable in medium close-up."}}]', 1)
    old = stop_parent(environment, damaged)
    child = environment[0] / 'child'
    view = pipe.prepare_known_director_continuation(child, parent_run=old)
    assert view['stage'] == 'director_review' and view['calls_started'] == 0
    clients = fx.FakeClients([fx.result(review(), 'director')])
    result = pipe.execute(child, clients=clients)
    assert result['status'] == 'text_ready_for_production', result['blockers']
    assert result['calls_started'] == 1 and result['state']['quality_director_revisions_used'] == 0
    assert clients.calls[0]['role'] == 'director'
    assert pipe.core._read(old / 'RESPONSE_003.json')['response_text'] == damaged


def test_ambiguous_native_syntax_stops_without_dispatch(environment):
    old = stop_parent(environment, '{"world_framework": "unterminated native content')
    child = environment[0] / 'child'
    view = pipe.prepare_known_director_continuation(child, parent_run=old)
    assert view['status'] == 'needs_attention' and view['calls_started'] == 0
    assert not list(child.glob('REQUEST_*.json'))
    assert pipe.execute(child, clients=fx.FakeClients([]))['calls_started'] == 0


@pytest.mark.parametrize('finish,unknown', [('length', False), ('stop', True)])
def test_unknown_or_truncated_parent_cannot_enter_known_result_continuation(environment, finish, unknown):
    old = stop_parent(environment, finish=finish, unknown=unknown)
    child = environment[0] / 'child'
    with pytest.raises(ValueError):
        pipe.prepare_known_director_continuation(child, parent_run=old)
    assert not child.exists()
    assert not (environment[2] / '_known_director_continuations').exists()


def test_parent_native_tamper_blocks_existing_continuation_before_dispatch(environment):
    old = stop_parent(environment)
    child = environment[0] / 'child'
    pipe.prepare_known_director_continuation(child, parent_run=old)
    native_path = old / 'RESPONSE_003.json'
    native_path.write_bytes(native_path.read_bytes() + b' ')
    clients = fx.FakeClients([])
    with pytest.raises(ValueError):
        pipe.execute(child, clients=clients)
    assert not clients.calls


@pytest.mark.parametrize('point', ['claim', 'KNOWN_PARENT_ANALYSIS.json', 'BINDING.json', 'STATE_00001.json'])
def test_interrupted_known_preparation_resumes_exact_owner_without_calls(environment, monkeypatch, point):
    old = stop_parent(environment)
    child = environment[0] / 'child'
    original = pipe.core._write
    fired = False
    def fail(path, value):
        nonlocal fired
        original(path, value)
        path = Path(path)
        matches = '_known_director_continuations' in path.parts if point == 'claim' else path == child / point
        if matches and not fired:
            fired = True
            raise OSError('Injected local preparation failure')
    monkeypatch.setattr(pipe.core, '_write', fail)
    with pytest.raises(OSError):
        pipe.prepare_known_director_continuation(child, parent_run=old)
    monkeypatch.setattr(pipe.core, '_write', original)
    view = pipe.prepare_known_director_continuation(child, parent_run=old)
    assert view['stage'] == 'director_full' and view['calls_started'] == 0
    assert not list(child.glob('REQUEST_*.json'))


def test_v8_quality_claim_blocks_restarting_v7_in_new_version(tmp_path, monkeypatch):
    old_v7 = _helpers['completed_parent'].__wrapped__(tmp_path, monkeypatch)
    canonical = tmp_path / 'canonical'
    monkeypatch.setattr(pipe, 'CANONICAL_REGISTRY', canonical)
    old_v8 = tmp_path / 'v8-quality'
    parent.prepare_quality_revision(old_v8, parent_run=old_v7)
    client = fx.FakeClients([*success_values()[:2], fx.result(invalid_plan())])
    with pytest.raises(ValueError):
        parent.execute(old_v8, clients=client)
    before = snapshot(canonical)
    run = tmp_path / 'v9-new-quality'
    with pytest.raises(RuntimeError, match='其他版本'):
        pipe.prepare_quality_revision(run, parent_run=old_v7)
    assert not run.exists() and snapshot(canonical) == before
    child = tmp_path / 'v9-known'
    view = pipe.prepare_known_director_continuation(child, parent_run=old_v8)
    assert view['combined_calls_started'] == 8 and view['combined_known_reported_tokens'] == 800
    assert view['state']['director_revisions_used'] == 1
    assert view['state']['quality_director_revisions_used'] == 0
    result = pipe.execute(child, clients=fx.FakeClients([fx.result(plan()), fx.result(review(), 'director')]))
    assert result['status'] == 'text_ready_for_production', result['blockers']
    assert result['state']['director_revisions_used'] == 2
    assert result['state']['quality_director_revisions_used'] == 1
    assert result['combined_calls_started'] == 10


def test_fresh_v9_still_uses_same_full_request_review_route(environment):
    run = environment[0] / 'fresh-v9'
    pipe.prepare(run, source_path=environment[1], title='Fresh v9 story', source_kind='original')
    result = pipe.execute(run, clients=fx.FakeClients(success_values()))
    assert result['status'] == 'text_ready_for_production', result['blockers']
    assert pipe.core._read(run / 'VIDEO_REQUESTS.json')['compiler_version'] == pipe.director.VERSION


def test_foreign_contract_claim_for_same_native_result_cannot_reclaim_candidate(environment):
    old = stop_parent(environment)
    audit = pipe._audit_known_director_parent(old)
    _, foreign = pipe._known_director_claim(environment[0] / 'other-owner', audit)
    foreign['schema'] = 'future_contract_example/v10'
    foreign_path = environment[2] / '_known_director_continuations' / 'future' / 'another-id.json'
    pipe.core._write(foreign_path, foreign)
    before = snapshot(environment[2])
    child = environment[0] / 'child'
    with pytest.raises(RuntimeError, match='跨版本'):
        pipe.prepare_known_director_continuation(child, parent_run=old)
    assert not child.exists() and snapshot(environment[2]) == before


def test_fresh_syntax_projection_with_real_content_failure_revises_complete_native_plan(environment):
    run = environment[0] / 'fresh-v9'
    pipe.prepare(run, source_path=environment[1], title='Fresh syntax and content case',
                 source_kind='original', brief={'max_duration_seconds': 15})
    raw = json.dumps(invalid_plan(), ensure_ascii=False)
    marker = '"Face and eyes readable in medium close-up."}]}]'
    assert marker in raw
    damaged = raw.replace(marker, '"Face and eyes readable in medium close-up."}}]', 1)
    clients = fx.FakeClients([*success_values()[:2], fx.result(damaged), fx.result(plan()),
                              fx.result(review(), 'director')])
    result = pipe.execute(run, clients=clients)
    assert result['status'] == 'text_ready_for_production', result['blockers']
    assert result['calls_started'] == 5 and result['state']['quality_director_revisions_used'] == 1
    feedback = json.loads(clients.calls[3]['messages'][-1]['content'])['revision_feedback']
    assert feedback['native_director_text'] == damaged
    assert feedback['native_projection']['insertions']
    codes = {row['code'] for row in feedback['content_contract_errors']}
    assert {'DIRECTOR_BEAT_TIME', 'DIRECTOR_TOTAL_DURATION'} <= codes
    assert pipe.core._read(run / 'RESPONSE_003.json')['response_text'] == damaged
    assert pipe.core._read(run / 'DIRECTOR_REJECTED_003.json') == invalid_plan()
