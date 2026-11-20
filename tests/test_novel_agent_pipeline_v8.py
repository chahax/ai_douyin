"""V8 runs the native chain, prompt binding, and inherited caps without services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v8 as pipe
from src.content_factory import novel_agent_pipeline_v7 as v7

_spec = importlib.util.spec_from_file_location('v8_parent_fixtures', Path(__file__).with_name('test_novel_agent_pipeline_v7.py'))
parents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parents)
fx = parents.fixtures


def plan():
    value = fx.plan()
    value['segments'][0]['time_context'] = 'Present afternoon; the answer immediately follows the question.'
    value['segments'][0]['beats'] = [{
        'beat_id': 'B01', 'start_seconds': 0, 'end_seconds': 8, 'event_ids': ['E01'],
        'stimulus': 'An off-screen question asks whether he will choose.',
        'camera': 'Medium close-up on hero, door is the interlocutor direction.',
        'information_change': 'He states that the choice belongs to him.',
        'participants': [{'actor_id': 'hero', 'action': 'Raises his head toward the door.',
            'expression': 'Firm but restrained.', 'gaze_target': 'The off-screen listener at the door.',
            'gaze_change': 'From the table to the listener.', 'head_body_orientation': 'Body beside table, head toward door.',
            'dialogue': 'I will decide.', 'response': 'Listens for the answer.',
            'camera_visibility': 'Face and eyes readable in medium close-up.'}]}]
    return value


def review(verdict='pass', responsibility_layer=None):
    value = fx.director_review(verdict)
    value['responsibility_layer'] = responsibility_layer or ('none' if verdict == 'pass' else 'director')
    # V8's additional semantic checks use the module's published dimensions.
    dimensions = getattr(pipe.director, 'QUALITY_REVIEW_DIMENSIONS', ())
    existing = {row['dimension'] for row in value['checks']}
    for name in dimensions:
        if name not in existing:
            value['checks'].append({'dimension': name, 'checked': True,
                'assessment': 'Compared complete source, draft, plan and actual prompt.', 'issues': []})
    return value


def success_values():
    return [fx.result('World, role, goal and causal plan. Full screenplay: hero looks at the listener and answers. End.'),
            fx.result(fx.review(), 'director'), fx.result(plan()), fx.result(review(), 'director')]


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(pipe, 'CANONICAL_REGISTRY', tmp_path / 'canonical')
    monkeypatch.setattr(pipe.core, '_legacy_blocks', lambda *a, **kw: [])
    source = tmp_path / 'source.txt'
    source.write_text('A person in a room decides whether to answer the question at the door.', encoding='utf-8')
    run = tmp_path / 'run'
    pipe.prepare(run, source_path=source, title='Independent v8 story', source_kind='original')
    return run


@pytest.fixture
def completed_parent(tmp_path, monkeypatch):
    values = parents.chain.__wrapped__(tmp_path, monkeypatch)
    base, source, grand, parent, canonical = values
    monkeypatch.setattr(pipe, 'CANONICAL_REGISTRY', canonical)
    run = base / 'completed-v7'
    v7.prepare_director_continuation(run, parent_run=parent)
    view = v7.execute(run, clients=fx.FakeClients([fx.result(fx.director_review(), 'director')]))
    assert view['status'] == 'text_ready_for_production'
    return run


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_prepare_freezes_one_policy_and_shared_original_route(prepared):
    binding, state = pipe._verify(prepared)
    assert binding['source_kind'] == binding['brief']['source_kind'] == 'original'
    assert binding['quality_policy'] == pipe.quality.quality_policy()
    clients = fx.FakeClients(success_values()[:2])
    view = pipe.execute(prepared, clients=clients, max_steps=2)
    assert view['stage'] == 'director_full'
    assert [row['role'] for row in clients.calls] == ['writer', 'director']
    for call in clients.calls:
        material = json.loads(call['messages'][-1]['content'])
        assert material['quality_policy'] == binding['quality_policy']
        assert material['source_kind'] == 'original'
    assert state['quality_director_revisions_used'] == 0


def test_full_flow_reviews_every_compiled_request_and_preserves_native_output(prepared):
    clients = fx.FakeClients(success_values())
    view = pipe.execute(prepared, clients=clients)
    assert view['status'] == 'text_ready_for_production', view['blockers']
    material = json.loads(clients.calls[-1]['messages'][-1]['content'])
    requests = pipe.core._read(prepared / 'VIDEO_REQUESTS.json')
    assert material['video_requests'] == requests
    assert material['accepted_full_draft'] == (prepared / 'SCREENPLAY.md').read_text(encoding='utf-8')
    handoff = pipe.core._read(prepared / 'PRODUCTION_HANDOFF.json')
    pipe.director.validate_handoff_for_dispatch(handoff)
    assert view['human_approved'] is False and view['media_generated'] is False
    assert pipe.execute(prepared, clients=fx.FakeClients([]))['calls_started'] == 4


def test_quality_revision_keeps_parent_claims_old_stage_and_total_capacity(completed_parent, tmp_path):
    before = snapshot(completed_parent)
    run = tmp_path / 'quality'
    view = pipe.prepare_quality_revision(run, parent_run=completed_parent,
        brief={'source_kind': 'original', 'target_duration_seconds': 120})
    assert view['calls_started'] == 0 and view['combined_calls_started'] == 5
    assert view['combined_known_reported_tokens'] == 500
    assert view['state']['director_revisions_used'] == 1
    assert view['state']['quality_director_revisions_used'] == 0
    assert pipe.preview(run)['remaining_calls'] == 15
    assert pipe.preview(run)['remaining_known_tokens'] == 499500
    binding = pipe.core._read(run / 'BINDING.json')
    assert 'continuation' not in binding
    assert binding['quality_revision']['original_budget']['max_calls'] == 20
    assert binding['quality_revision']['director_candidates'] == 2
    assert snapshot(completed_parent) == before
    with pytest.raises(RuntimeError, match='唯一'):
        pipe.prepare_quality_revision(tmp_path / 'fork', parent_run=completed_parent,
            brief={'source_kind': 'original', 'target_duration_seconds': 120})
    assert not (tmp_path / 'fork').exists()


def test_quality_first_writer_is_new_candidate_not_old_revision(completed_parent, tmp_path):
    run = tmp_path / 'quality'
    pipe.prepare_quality_revision(run, parent_run=completed_parent)
    client = fx.FakeClients([fx.result('New complete quality screenplay.')])
    view = pipe.execute(run, clients=client, max_steps=1)
    assert view['stage'] == 'review_full' and view['calls_started'] == 1
    assert view['state']['revisions_used'] == 0
    assert view['state']['quality_revisions_used'] == 0
    assert view['state']['director_revisions_used'] == 1
    assert json.loads(client.calls[0]['messages'][-1]['content'])['previous_draft'] == (completed_parent / 'SCREENPLAY.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('target', ['parent_receipt', 'parent_draft', 'source'])
def test_quality_parent_tamper_blocks_before_new_dispatch(completed_parent, tmp_path, target):
    run = tmp_path / 'quality'
    pipe.prepare_quality_revision(run, parent_run=completed_parent)
    binding = pipe.core._read(completed_parent / 'BINDING.json')
    path = {'parent_receipt': completed_parent / 'RESPONSE_001.json',
            'parent_draft': completed_parent / 'SCREENPLAY.md',
            'source': Path(binding['source_evidence'][0]['path'])}[target]
    path.write_bytes(path.read_bytes() + b' ')
    client = fx.FakeClients([])
    with pytest.raises(ValueError):
        pipe.execute(run, clients=client)
    assert not client.calls


@pytest.mark.parametrize('finish,unknown', [('length', False), ('stop', True)])
def test_unknown_or_truncated_has_no_automatic_repeat(prepared, finish, unknown):
    client = fx.FakeClients([fx.result('Complete-looking but untrusted.', finish=finish, unknown=unknown)])
    with pytest.raises(RuntimeError):
        pipe.execute(prepared, clients=client)
    assert pipe.inspect(prepared)['pending_call'] == 1
    assert pipe.execute(prepared, clients=fx.FakeClients([]))['calls_started'] == 1
    assert len(list(prepared.glob('REQUEST_*.json'))) == 1


def test_quality_stage_caps_count_new_whole_writer_revisions(prepared):
    values = [value for index in range(3) for value in
        (fx.result('Full draft ' + str(index)), fx.result(fx.review('revise'), 'director'))]
    view = pipe.execute(prepared, clients=fx.FakeClients(values))
    assert view['status'] == 'content_revision_exhausted'
    assert view['state']['quality_revisions_used'] == 2
    assert view['calls_started'] == 6
    assert not (prepared / 'PRODUCTION_HANDOFF.json').exists()


@pytest.mark.parametrize('point', ['claim', 'SOURCE.json', 'BINDING.json', 'BINDING_ANCHOR.json', 'STATE_00001.json'])
def test_quality_partial_preparation_only_exact_owner_can_resume(completed_parent, tmp_path, monkeypatch, point):
    run = tmp_path / 'quality'
    original = pipe.core._write
    failed = False
    def fail(path, value):
        nonlocal failed
        original(path, value)
        path = Path(path)
        match = path.parent.name == 'v8' if point == 'claim' else path == run / point
        if match and not failed:
            failed = True
            raise OSError('Injected local preparation failure')
    monkeypatch.setattr(pipe.core, '_write', fail)
    with pytest.raises(OSError):
        pipe.prepare_quality_revision(run, parent_run=completed_parent)
    monkeypatch.setattr(pipe.core, '_write', original)
    view = pipe.prepare_quality_revision(run, parent_run=completed_parent)
    assert view['stage'] == 'writer_full' and view['calls_started'] == 0
    assert view['combined_calls_started'] == 5
    assert not list(run.glob('REQUEST_*.json'))


def test_projection_recovery_verifies_native_files_without_redispatch(prepared):
    old = (prepared / 'state.json').read_bytes()
    client = fx.FakeClients([success_values()[0]])
    pipe.execute(prepared, clients=client, max_steps=1)
    (prepared / 'state.json').write_bytes(old)
    assert pipe.inspect(prepared)['projection_recovery_available'] is True
    assert pipe.recover_projection(prepared)['calls_started'] == 1
    assert len(client.calls) == 1


def test_preview_serializes_exact_next_request_without_creating_claim(prepared):
    before = snapshot(prepared)
    view = pipe.preview(prepared)
    preflight = view['next_request_preflight']
    assert preflight['stage'] == 'writer_full'
    assert preflight['input_bytes'] > 0 and preflight['max_output_tokens'] == 20000
    assert preflight['reservation_fits'] and preflight['read_only']
    assert preflight['dispatch_authorized'] is False
    client = fx.FakeClients([success_values()[0]])
    pipe.execute(prepared, clients=client, max_steps=1)
    request = pipe.core._read(prepared / 'REQUEST_001.json')
    assert pipe.core._digest(request['messages']) == preflight['messages_sha256']
    assert request['reservation_tokens'] == preflight['reservation_tokens']
    assert len(before) < len(snapshot(prepared))


def test_native_package_writer_failure_routes_to_complete_writer_not_director_patch(prepared):
    values = [*success_values()[:3], fx.result(review('revise', 'writer'), 'director'), *success_values()]
    client = fx.FakeClients(values)
    view = pipe.execute(prepared, clients=client)
    assert view['status'] == 'text_ready_for_production', view['blockers']
    assert view['state']['quality_revisions_used'] == 1
    assert view['state']['quality_director_revisions_used'] == 1
    assert [pipe.core._read(path)['stage'] for path in sorted(prepared.glob('REQUEST_*.json'))] == [
        'writer_full', 'review_full', 'director_full', 'director_review',
        'writer_full', 'review_full', 'director_full', 'director_review']
    feedback = json.loads(client.calls[4]['messages'][-1]['content'])
    assert feedback['previous_draft'] == success_values()[0].text
    assert (prepared / 'EPISODE_002.json').exists() and (prepared / 'EPISODE_006.json').exists()


def test_native_package_compiler_failure_stops_without_rewriting_content(prepared):
    client = fx.FakeClients([*success_values()[:3], fx.result(review('revise', 'compiler'), 'director')])
    view = pipe.execute(prepared, clients=client)
    assert view['status'] == 'needs_attention'
    assert view['calls_started'] == 4 and len(client.calls) == 4
    assert not (prepared / 'PRODUCTION_HANDOFF.json').exists()


@pytest.mark.parametrize('defect', ['time_context', 'beats', 'service_duration', 'beat_time', 'beat_actor'])
def test_complete_known_native_director_content_failures_receive_bounded_full_revision(prepared, defect):
    invalid = plan()
    segment = invalid['segments'][0]
    if defect in {'time_context', 'beats'}:
        segment.pop(defect)
    elif defect == 'service_duration':
        segment['estimated_duration_seconds'] = 16
        segment['beats'][0]['end_seconds'] = 16
    elif defect == 'beat_time':
        segment['beats'][0]['start_seconds'] = 1
    else:
        segment['beats'][0]['participants'][0]['actor_id'] = 'invented'
    clients = fx.FakeClients([*success_values()[:2], fx.result(invalid), fx.result(plan()),
                              fx.result(review(), 'director')])
    view = pipe.execute(prepared, clients=clients)
    assert view['status'] == 'text_ready_for_production', view['blockers']
    assert view['state']['quality_director_revisions_used'] == 1
    materials = json.loads(clients.calls[3]['messages'][-1]['content'])
    assert materials['previous_director'] == invalid
    assert materials['revision_feedback']['content_contract_errors']
    assert (prepared / 'DIRECTOR_REJECTED_003.json').exists()


def test_quality_continuation_can_run_new_director_despite_exhausted_old_director(completed_parent, tmp_path):
    run = tmp_path / 'quality'
    pipe.prepare_quality_revision(run, parent_run=completed_parent)
    view = pipe.execute(run, clients=fx.FakeClients(success_values()))
    assert view['status'] == 'text_ready_for_production', view['blockers']
    assert view['combined_calls_started'] == 9 and view['calls_started'] == 4
    assert view['state']['director_revisions_used'] == 1
    assert view['state']['quality_director_revisions_used'] == 0
    assert pipe.preview(run)['remaining_calls'] == 11


def test_new_director_revision_cap_cannot_be_reset_by_reentry(prepared):
    invalid = plan()
    invalid['segments'][0].pop('beats')
    clients = fx.FakeClients([*success_values()[:2], fx.result(invalid), fx.result(deepcopy(invalid))])
    view = pipe.execute(prepared, clients=clients)
    assert view['status'] == 'director_revision_exhausted'
    assert view['calls_started'] == 4 and view['state']['quality_director_revisions_used'] == 1
    assert pipe.execute(prepared, clients=fx.FakeClients([]))['calls_started'] == 4
