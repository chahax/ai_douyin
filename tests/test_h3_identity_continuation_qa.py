"""Synthetic protocol checks; no HTTP, FFmpeg, model, GPU, or visual approval."""
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import qa_h3_identity_continuation as qa
from tests.test_h3_story_opening_sample_qa import fixture, write


def physical_predecessor(root, monkeypatch):
    run, folder = fixture(root, monkeypatch)
    nr = folder.parents[1]
    graph = qa.read(folder / 'workflow_api.json')
    for role, index in [('first', 0), ('last', 361)]:
        graph['pick_' + role]['inputs'] = dict(image=['122', 0], batch_index=index, length=1)
        graph['save_' + role]['inputs']['images'] = ['pick_' + role, 0]
    plan = qa.read(nr / 'PLAN.json')
    plan['shots'][0]['graph_sha256'] = qa.digest(graph)
    write(nr / 'PLAN.json', plan)
    write(folder / 'workflow_api.json', graph)
    write(folder / 'REQUEST.json', dict(prompt=graph))
    state = qa.read(folder / 'STATE.json')
    state['plan_sha256'] = qa.digest(plan)
    write(folder / 'STATE.json', state)
    result = qa.read(folder / 'RESULT.json')
    result['graph_sha256'] = qa.digest(graph)
    write(folder / 'RESULT.json', result)
    claim = qa.read(folder / 'CLAIM.json')
    claim['graph_sha256'] = qa.digest(graph)
    write(folder / 'CLAIM.json', claim)
    history = qa.read(folder / 'HISTORY.json')
    history[state['prompt_id']]['prompt'][2] = graph
    write(folder / 'HISTORY.json', history)
    return nr, folder, result


def continuation_fixture(root, monkeypatch):
    previous_run, previous_folder, previous = physical_predecessor(root, monkeypatch)
    sid = 'S03'
    run = root / 'data/video_generation/identity_fixture'
    nr = run / 'visual_h3_v3' / (run.name + '_' + sid)
    folder = nr / 'shots' / sid
    folder.mkdir(parents=True)
    source = run / 'segments' / sid / 'SOURCE_CASE.json'
    write(source, dict(fixture_only=True))
    write(run / 'PLAN.json', dict(fixture_only=True))
    predecessor_result = qa.bind(previous_folder / 'RESULT.json')
    write(run / 'imported/S02/IMPORT.json', dict(native_result=predecessor_result))
    last = {k: previous['files']['last'][k] for k in ('path', 'sha256')}
    observation = source.parent / 'TAIL_ANCHOR_COVERAGE_REVIEW.json'
    write(observation, dict(schema='h3_identity_tail_coverage/v1', shot_id=sid,
          anchor_result=predecessor_result, anchor_image=last, completion_known=True, outcome_unknown=False,
          reviewed_by='synthetic fixture only', evidence=['Not a production observation'],
          actual_anchor_actor_ids=sorted(qa.ACTORS), identity_by_actor={a: dict(present=True) for a in qa.ACTORS}))
    input_path = source.parent / 'IDENTITY_CONTINUATION_INPUT.json'
    write(input_path, dict(fixture_only=True))
    prompt = '\n'.join('“' + q + '”' for q in qa.EXPECTED_QUOTES[sid])
    proof = dict(schema=qa.INPUT_SCHEMA, input=qa.bind(input_path), source_case=qa.bind(source), first_image=last,
                 predecessor_result=predecessor_result, coverage_review=qa.bind(observation),
                 clip_identity_actor_ids=sorted(qa.ACTORS), opening_actor_ids=['ye_xijue'],
                 compiled_prompt_utf8_sha256=qa.prior_qa.core.sha(prompt))
    context = dict(proof=proof, first_image=last, source_case=qa.bind(source),
                   compiled_prompt=prompt, compiled_prompt_utf8_sha256=proof['compiled_prompt_utf8_sha256'],
                   quality_passed=False, full_video_quality_passed=False, identity_coverage_complete=True,
                   entry=dict(shot_id=sid, duration=15, audio=[]))
    monkeypatch.setattr(qa, 'input_context', lambda binding: deepcopy(context))
    retained = dict(qa.RETAINED)
    retained['S02'] = (previous['prompt_id'], previous['files']['video']['sha256'])
    monkeypatch.setattr(qa, 'RETAINED', retained)
    graph = deepcopy(qa.read(previous_folder / 'workflow_api.json'))
    scope, input_name = 'fixture/new/S03', 'fixture/new/S03/first.png'
    graph['condition']['inputs']['prompt'] = prompt
    graph['ref_scene']['inputs']['image'] = input_name
    for role in ('video', 'audio', 'first', 'last'):
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    row = dict(id=sid, scope=scope, input_name=input_name, first_frame=last, identity_continuation=proof,
               graph_sha256=qa.digest(graph), timing=dict(requested_seconds=15, native_frames=362, automatic_audio_cut=False))
    previous_plan = qa.read(previous_run / 'PLAN.json')
    staged = Path(previous_plan['config']['input_root']) / input_name
    staged.parent.mkdir(parents=True)
    staged.write_bytes(Path(last['path']).read_bytes())
    plan = dict(schema=qa.NATIVE_SCHEMA, upstream_contract=qa.INPUT_SCHEMA, publication=False,
                production_approved=False, shots=[row], source=qa.bind(source), input=qa.bind(input_path),
                series_plan=qa.bind(run / 'PLAN.json'), base_workflow=qa.bind(source), code=[qa.bind(source)],
                config=previous_plan['config'])
    write(nr / 'PLAN.json', plan)
    write(folder / 'workflow_api.json', graph)
    return run, nr, folder, context, staged, observation, previous_folder


def test_real_native_last_equals_new_first_and_staged(tmp_path, monkeypatch):
    _, nr, _, _, staged, _, _ = continuation_fixture(tmp_path, monkeypatch)
    value = qa.prepared_graph(nr, 'S03', tmp_path)
    assert value['first_input']['sha256'] == qa.sha(staged)
    assert value['context']['quality_passed'] is False


def test_changed_staged_pixels_are_rejected_before_submission(tmp_path, monkeypatch):
    _, nr, _, _, staged, _, _ = continuation_fixture(tmp_path, monkeypatch)
    staged.write_bytes(b'changed staged pixels')
    with pytest.raises(ValueError, match='actual_staged_tail_pixels'):
        qa.prepared_graph(nr, 'S03', tmp_path)


def test_previous_last_save_node_cannot_actually_save_first(tmp_path, monkeypatch):
    _, nr, _, _, _, _, previous = continuation_fixture(tmp_path, monkeypatch)
    graph = qa.read(previous / 'workflow_api.json')
    graph['save_last']['inputs']['images'] = ['pick_first', 0]
    write(previous / 'workflow_api.json', graph)
    with pytest.raises(ValueError, match='actual_decoded_endpoint'):
        qa.prepared_graph(nr, 'S03', tmp_path)


def test_observation_is_bound_to_actual_tail_pixels(tmp_path, monkeypatch):
    _, nr, _, context, _, observation, _ = continuation_fixture(tmp_path, monkeypatch)
    review = qa.read(observation)
    review['anchor_image'] = dict(review['anchor_image'], sha256='0' * 64)
    write(observation, review)
    plan = qa.read(nr / 'PLAN.json')
    plan['shots'][0]['identity_continuation']['coverage_review'] = qa.bind(observation)
    context['proof']['coverage_review'] = qa.bind(observation)
    write(nr / 'PLAN.json', plan)
    with pytest.raises(ValueError, match='actual_three_actor_observation'):
        qa.prepared_graph(nr, 'S03', tmp_path)


def test_full_clip_three_actors_are_not_the_single_opening_actor(tmp_path, monkeypatch):
    _, nr, _, context, _, _, _ = continuation_fixture(tmp_path, monkeypatch)
    plan = qa.read(nr / 'PLAN.json')
    plan['shots'][0]['identity_continuation']['clip_identity_actor_ids'] = ['ye_xijue']
    context['proof']['clip_identity_actor_ids'] = ['ye_xijue']
    write(nr / 'PLAN.json', plan)
    with pytest.raises(ValueError, match='three_clip_actors'):
        qa.prepared_graph(nr, 'S03', tmp_path)


def test_cpu_metadata_cannot_promote_identity_quality(tmp_path, monkeypatch):
    _, nr, _, context, _, _, _ = continuation_fixture(tmp_path, monkeypatch)
    context['quality_passed'] = True
    with pytest.raises(ValueError, match='must_not_claim_identity_quality'):
        qa.prepared_graph(nr, 'S03', tmp_path)


def test_actual_POST_remains_independently_checked(tmp_path, monkeypatch):
    nr, folder, _ = physical_predecessor(tmp_path, monkeypatch)
    request = qa.read(folder / 'REQUEST.json')
    request['prompt']['condition']['inputs']['prompt'] += ' changed actual POST'
    write(folder / 'REQUEST.json', request)
    with pytest.raises(ValueError, match='actual_POST_graph'):
        qa.saved_originals(nr, 'S02', tmp_path)


def test_unknown_original_never_becomes_saved(tmp_path, monkeypatch):
    nr, folder, _ = physical_predecessor(tmp_path, monkeypatch)
    state = qa.read(folder / 'STATE.json')
    state['status'] = 'outcome_unknown'
    write(folder / 'STATE.json', state)
    before = (folder / 'STATE.json').read_bytes()
    with pytest.raises(ValueError, match='original_saved_native_ID'):
        qa.saved_originals(nr, 'S02', tmp_path)
    assert (folder / 'STATE.json').read_bytes() == before


def test_command_path_aliases_preserve_exact_source_order(tmp_path):
    a = ['ffmpeg', '-i', 'one.mp4', '-i', 'two.mp4', '-filter_complex_script', 'filter.txt', 'out.mp4']
    b = ['ffmpeg', '-i', str(tmp_path / 'one.mp4'), '-i', str(tmp_path / 'two.mp4'),
         '-filter_complex_script', str(tmp_path / 'filter.txt'), str(tmp_path / 'out.mp4')]
    assert qa.normalize_assembly_command(a, tmp_path) == qa.normalize_assembly_command(b, tmp_path)
    b[2], b[4] = b[4], b[2]
    assert qa.normalize_assembly_command(a, tmp_path) != qa.normalize_assembly_command(b, tmp_path)


def test_repair_sampling_uses_actual_frame724_boundary():
    plan = qa.sample_plan()
    assert 723 in plan['repair_boundary'] and 724 in plan['repair_boundary']
    assert [r['first_after'] for r in plan['joins']] == [362, 724, 1086]
    assert plan['timeline'][0] == 0 and plan['timeline'][-1] == 1447


def renderer_fixture(root, monkeypatch):
    nr, _, _ = physical_predecessor(root, monkeypatch)
    row = qa.prior_qa.validate_native(nr, 'S02', root)
    monkeypatch.setattr(qa, 'inspect_clock', lambda *a, **k: (dict(clock={'fixture_only': True}), {}))
    monkeypatch.setattr(qa, 'extract_batch', lambda video, indices, directory: {
        i: dict(**row['first_input'], frame_index=i, seconds=i / 24) for i in indices})
    return row


def test_preserved_prefix_is_never_retranscribed(tmp_path, monkeypatch):
    row = renderer_fixture(tmp_path, monkeypatch)
    row['kind'] = 'imported'
    monkeypatch.setattr(qa, 'cpu_asr', lambda *a, **k: pytest.fail('preserved source retranscribed'))
    report, _ = qa.segment_evidence(row, tmp_path / 'CPU_fixture_evidence', asr=True, project=tmp_path)
    assert report['asr']['status'] == 'preserved_prefix_no_reanalysis'


def test_new_tail_uses_only_its_single_optional_ASR_call(tmp_path, monkeypatch):
    row = renderer_fixture(tmp_path, monkeypatch)
    row['kind'] = 'new'
    calls = []
    def only_once(project, value, folder, enabled):
        calls.append((value['id'], enabled))
        return dict(status='synthetic_ASR_fixture', quote_intervals=[])
    monkeypatch.setattr(qa, 'cpu_asr', only_once)
    report, _ = qa.segment_evidence(row, tmp_path / 'CPU_fixture_evidence', asr=True, project=tmp_path)
    assert calls == [('S02', True)]  # Synthetic renderer row; production new IDs are S03/S04.
    assert report['asr']['status'] == 'synthetic_ASR_fixture'
