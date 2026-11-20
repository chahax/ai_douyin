"""CPU protocol fixtures; no generated video or semantic quality claims."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from scripts import qa_h3_story_opening_minute as qa
from tests.test_h3_story_opening_sample_qa import fixture, write


def test_saved_import_lineage_is_read_without_service(tmp_path, monkeypatch):
    run, _ = fixture(tmp_path, monkeypatch)
    row = qa.validate_native(run / 'visual_h3_v3/opening_S02', 'S02', tmp_path)
    assert row['native_id'] == 'fixture_original_S02'
    assert set(row['originals']) == {'video', 'audio', 'first', 'last'}
    assert row['opening_contract']['opening_visible_actors'] == ['su_mo']


def test_actual_POST_cannot_differ_from_saved_workflow(tmp_path, monkeypatch):
    run, folder = fixture(tmp_path, monkeypatch)
    request = qa.read(folder / 'REQUEST.json')
    request['prompt']['condition']['inputs']['prompt'] += ' changed after planning'
    write(folder / 'REQUEST.json', request)
    with pytest.raises(ValueError, match='actual_POST_graph'):
        qa.validate_native(run / 'visual_h3_v3/opening_S02', 'S02', tmp_path)


@pytest.mark.parametrize('role', ['video', 'audio', 'first', 'last'])
def test_native_history_cannot_point_to_another_artifact(tmp_path, monkeypatch, role):
    run, folder = fixture(tmp_path, monkeypatch)
    history = qa.read(folder / 'HISTORY.json')
    output = history['fixture_original_S02']['outputs']['save_' + role]
    output['audio' if role == 'audio' else 'images'][0]['filename'] = 'other_file.png'
    write(folder / 'HISTORY.json', history)
    with pytest.raises(ValueError, match='native_history_output_mapping'):
        qa.validate_native(run / 'visual_h3_v3/opening_S02', 'S02', tmp_path)


def test_unknown_is_preserved_and_never_treated_as_saved(tmp_path, monkeypatch):
    run, folder = fixture(tmp_path, monkeypatch)
    state = qa.read(folder / 'STATE.json')
    state['status'] = 'outcome_unknown'
    write(folder / 'STATE.json', state)
    before = (folder / 'STATE.json').read_bytes()
    with pytest.raises(ValueError, match='saved_original_native_ID'):
        qa.validate_native(run / 'visual_h3_v3/opening_S02', 'S02', tmp_path)
    assert (folder / 'STATE.json').read_bytes() == before


def test_minute_samples_include_real_boundary_frames():
    plan = qa.sample_plan()
    assert plan['timeline'][0] == 0 and plan['timeline'][-1] == 1447
    assert all(0 <= frame < 1448 for frame in plan['timeline'] + plan['opening'])
    assert [row['first_after'] for row in plan['joins']] == [362, 724, 1086]
    for row in plan['joins']:
        assert row['first_after'] - 1 in row['indices']
        assert row['first_after'] in row['indices']
        assert all(0 <= frame < 1448 for frame in row['indices'])


def imported_fixture(root, monkeypatch):
    old, _ = fixture(root, monkeypatch)
    value = qa.validate_native(old / 'visual_h3_v3/opening_S02', 'S02', root)
    run = root / 'data/video_generation/minute_fixture'
    prior = old / 'PRIOR_REVIEW.json'
    write(prior, dict(production_approved=False, fixture_only=True))
    accepted = dict(native_result=value['result_binding'], file=value['originals']['video']['local'],
                    prompt_id=value['native_id'], prior_root_review=qa.bind(prior),
                    prior_review_unchanged=True, new_acceptance_does_not_rewrite_prior_quality_record=True)
    write(run / 'USER_ACCEPTED_BASELINE.json', accepted)
    result = qa.read(value['result_binding']['path'])
    imported = dict(schema=qa.SCHEMA, shot_id='S02', kind='imported_user_accepted_native',
                    native_result=value['result_binding'], native_files=result['files'],
                    file=accepted['file'], prompt_id=value['native_id'],
                    acceptance=qa.bind(run / 'USER_ACCEPTED_BASELINE.json'),
                    new_model_posts=0, temporal_trim=False, source_media_unchanged=True,
                    native_records=dict(PLAN=value['binding']['plan'], REQUEST=value['binding']['request'],
                                        HISTORY=value['binding']['history'], RESULT=value['result_binding']))
    write(run / 'imported/S02/IMPORT.json', imported)
    descriptor = dict(kind=imported['kind'], native_result=value['result_binding'],
                      imported=qa.bind(run / 'imported/S02/IMPORT.json'))
    monkeypatch.setattr(qa, 'ACCEPTED_ID', value['native_id'])
    monkeypatch.setattr(qa, 'ACCEPTED_SHA', value['originals']['video']['local']['sha256'])
    return run, descriptor, value, prior


def test_user_acceptance_preserves_prior_false_quality_record(tmp_path, monkeypatch):
    run, descriptor, value, prior = imported_fixture(tmp_path, monkeypatch)
    before = prior.read_bytes()
    result = qa.validate_import(run, descriptor, value, tmp_path)
    assert result['quality_reassessment'] is False
    assert prior.read_bytes() == before
    assert qa.read(prior)['production_approved'] is False


def test_accepted_import_cannot_change_identity_or_spend_new_post(tmp_path, monkeypatch):
    run, descriptor, value, _ = imported_fixture(tmp_path, monkeypatch)
    imported_path = run / 'imported/S02/IMPORT.json'
    imported = qa.read(imported_path)
    imported['new_model_posts'] = 1
    write(imported_path, imported)
    descriptor['imported'] = qa.bind(imported_path)
    with pytest.raises(ValueError, match='exact_user_accepted_native_import'):
        qa.validate_import(run, descriptor, value, tmp_path)


def minute_fixture(root, monkeypatch):
    run, descriptor, imported_value, _ = imported_fixture(root, monkeypatch)
    values, descriptors, rows = {}, [], []
    for sid in qa.IDS:
        source = run / 'segments' / sid / 'SOURCE_CASE.json'
        entry = dict(shot_id=sid, duration=15, fixture_only=True)
        write(source, dict(schema=qa.core.SCHEMA, shots=[entry]))
        if sid == 'S02':
            value = imported_value
            desc = dict(descriptor, shot_id=sid, source_case=qa.bind(source),
                        native_run=str(Path(value['binding']['plan']['path']).parent))
        else:
            native_run = run / 'visual_h3_v3' / (run.name + '_' + sid)
            result_path = native_run / 'shots' / sid / 'RESULT.json'
            write(result_path, dict(fixture_only_not_media=True, shot_id=sid))
            video = native_run / 'shots' / sid / 'artifacts/native.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(b'protocol fixture, not media:' + sid.encode())
            video_source = run / 'segments' / sid / 'VIDEO_SOURCE_CASE.json'
            write(video_source, dict(schema=qa.core.SCHEMA, shots=[dict(entry, reanchor={})]))
            value = dict(id=sid, native_id='new_fixture_' + sid, source_entry=dict(entry, reanchor={}),
                         result_binding=qa.bind(result_path), binding=dict(source=qa.bind(video_source)),
                         originals={'video': {'local': qa.bind(video)}})
            desc = dict(shot_id=sid, kind='new_native', source_case=qa.bind(source),
                        native_run=str(native_run), native_result_path=str(result_path))
            write(run / 'segments' / sid / 'FINAL_RESULT.json',
                  dict(native_result=value['result_binding'], file=value['originals']['video']['local'],
                       prompt_id=value['native_id'], postprocessing=[]))
        values[sid] = value
        descriptors.append(desc)
        rows.append(dict(shot_id=sid, native_result=value['result_binding'], prompt_id=value['native_id'],
                         file=value['originals']['video']['local'], kind='imported' if sid == 'S02' else 'new'))
    authority = run / 'AUTHORITY.json'
    write(authority, dict(fixture_only=True))
    plan = dict(schema=qa.SCHEMA, publication=False, production_approved=False, temporal_leading_trim=False,
                width=736, height=1312, frames_per_segment=362, fps=24, steps=12,
                expected_frames=1448, expected_audio_rate=48000, expected_audio_samples=2896000,
                source_case=qa.bind(authority), authority=qa.bind(authority),
                accepted_baseline=qa.bind(run / 'USER_ACCEPTED_BASELINE.json'), segments=descriptors)
    write(run / 'PLAN.json', plan)
    movie = run / 'H3_STORY_OPENING_MINUTE_736x1312.mp4'
    movie.write_bytes(b'protocol fixture only, no real media')
    inputs = dict(plan=qa.bind(run / 'PLAN.json'), segments=rows)
    final = dict(schema=qa.SCHEMA, segments=rows, native_ids=[r['prompt_id'] for r in rows],
                 native_results=[r['native_result'] for r in rows], assembly_inputs_sha256=qa.digest(inputs),
                 imported_s02=descriptor['imported'], temporal_leading_trim=False,
                 publication=False, production_approved=False, file=qa.bind(movie))
    write(run / 'FINAL_RESULT.json', final)
    write(run / 'ASSEMBLY_REQUEST.json', dict(inputs=inputs, source_media_unchanged=True,
                                            temporal_leading_trim=False, audio_resampled_to_48k=True))
    monkeypatch.setattr(qa, 'validate_native', lambda native_run, sid, project: deepcopy(values[sid]))
    return run


def test_complete_minute_keeps_accepted_import_second(tmp_path, monkeypatch):
    run = minute_fixture(tmp_path, monkeypatch)
    result = qa.validate(run, tmp_path)
    assert [r['id'] for r in result['values']] == list(qa.IDS)
    assert result['values'][1]['kind'] == 'imported'
    assert result['values'][1]['native_id'] == qa.ACCEPTED_ID


def test_final_cannot_swap_segment_order_even_if_ids_still_unique(tmp_path, monkeypatch):
    run = minute_fixture(tmp_path, monkeypatch)
    final = qa.read(run / 'FINAL_RESULT.json')
    final['segments'][0], final['segments'][1] = final['segments'][1], final['segments'][0]
    write(run / 'FINAL_RESULT.json', final)
    with pytest.raises(ValueError, match='final_assembly_original_inputs'):
        qa.validate(run, tmp_path)


def diagnostic_fixture(root, monkeypatch):
    """Adapt the saved protocol fixture, never a passing visual review."""
    run, old_folder = fixture(root, monkeypatch)
    native_run = old_folder.parents[1]
    folder = native_run / 'shots/S03'
    shutil.copytree(old_folder, folder)
    observed = qa.core.evaluate(None)
    source_path = run / 'VIDEO_SOURCE_CASE.json'
    source = qa.read(source_path)
    source['shots'][0]['shot_id'] = 'S03'
    write(source_path, source)
    entry = source['shots'][0]
    observation = run / 'FAILED_OBSERVATION.json'
    write(observation, dict(actual_image=observed['first_image'], quality_passed=False,
                            deviations=['synthetic fixture known mismatch']))
    override = run / 'DIAGNOSTIC_GENERATION_SELECTION.json'
    write(override, dict(quality_passed=False, decision='generate_for_user_review',
                         source_case=qa.bind(source_path), image=observed['first_image'],
                         observation=qa.bind(observation)))
    input_path = run / 'DIAGNOSTIC_INPUT.json'
    write(input_path, dict(fixture_only_not_generation=True))
    pending = dict(status='reanchor_required', reasons=['controlled fixture mismatch'])
    context = dict(entry=entry, source_case=qa.bind(source_path), first_image=observed['first_image'],
                   compiled_prompt=observed['compiled_prompt'],
                   compiled_prompt_utf8_sha256=observed['compiled_prompt_utf8_sha256'],
                   generation_receipt=observed['generation_receipt'], quality_passed=False,
                   proof=qa.bind(input_path), override=qa.bind(override), source_evaluation=pending)
    monkeypatch.setattr(qa, 'diagnostic_input', lambda _: deepcopy(context))
    monkeypatch.setattr(qa.core, 'evaluate', lambda _: deepcopy(pending))
    monkeypatch.setattr(qa.core, 'compile_prompt', lambda _: dict(
        compiled_prompt=context['compiled_prompt'],
        compiled_prompt_utf8_sha256=context['compiled_prompt_utf8_sha256']))
    plan = qa.read(native_run / 'PLAN.json')
    plan['schema'], plan['upstream_contract'] = qa.DIAGNOSTIC_SCHEMA, qa.DIAGNOSTIC_CONTRACT
    plan.update(diagnostic_input=qa.bind(input_path), source=qa.bind(source_path), source_evaluation=pending,
                quality_passed=False, visual_ready=False, production_approved=False,
                base_workflow=qa.bind(input_path), authority=qa.bind(input_path), code=[qa.bind(input_path)])
    row = plan['shots'][0]
    row['id'] = 'S03'
    row.pop('continuity_input')
    row['diagnostic_input'] = qa.bind(input_path)
    write(native_run / 'PLAN.json', plan)
    state = qa.read(folder / 'STATE.json')
    state.update(id='S03', plan_sha256=qa.digest(plan))
    write(folder / 'STATE.json', state)
    result = qa.read(folder / 'RESULT.json')
    result['shot_id'] = 'S03'
    result.pop('continuity_input')
    for item in result['files'].values():
        item['path'] = str(folder / 'artifacts' / Path(item['path']).name)
    write(folder / 'RESULT.json', result)
    write(native_run / 'DIAGNOSTIC_RESULT.json', dict(schema=qa.DIAGNOSTIC_SCHEMA,
          native_result=qa.bind(folder / 'RESULT.json'), input=qa.bind(input_path),
          diagnostic_input=qa.bind(input_path), quality_passed=False, source_evaluation=pending,
          visual_ready=False, production_approved=False,
          native_records=dict(plan=qa.bind(native_run / 'PLAN.json'), request=qa.bind(folder / 'REQUEST.json'),
                              history=qa.bind(folder / 'HISTORY.json'))))
    return run, native_run, folder, context


def test_diagnostic_keeps_pending_source_and_failed_quality(tmp_path, monkeypatch):
    _, native_run, _, _ = diagnostic_fixture(tmp_path, monkeypatch)
    result = qa.validate_native(native_run, 'S03', tmp_path)
    assert result['input_status']['source_evaluation']['status'] == 'reanchor_required'
    assert result['input_status']['quality_passed'] is False
    assert result['input_status']['contract'] == qa.DIAGNOSTIC_CONTRACT


def test_diagnostic_cannot_forge_a_ready_continuity_proof(tmp_path, monkeypatch):
    _, native_run, _, _ = diagnostic_fixture(tmp_path, monkeypatch)
    plan = qa.read(native_run / 'PLAN.json')
    plan['shots'][0]['continuity_input'] = dict(status='ready')
    write(native_run / 'PLAN.json', plan)
    with pytest.raises(ValueError, match='must_not_forge_ready'):
        qa.validate_native(native_run, 'S03', tmp_path)


def test_diagnostic_does_not_relax_actual_POST_binding(tmp_path, monkeypatch):
    _, native_run, folder, _ = diagnostic_fixture(tmp_path, monkeypatch)
    request = qa.read(folder / 'REQUEST.json')
    request['prompt']['condition']['inputs']['prompt'] += ' changed'
    write(folder / 'REQUEST.json', request)
    with pytest.raises(ValueError, match='actual_POST_graph'):
        qa.validate_native(native_run, 'S03', tmp_path)


def test_diagnostic_never_promotes_failed_quality(tmp_path, monkeypatch):
    _, native_run, _, context = diagnostic_fixture(tmp_path, monkeypatch)
    context['quality_passed'] = True
    with pytest.raises(ValueError, match='diagnostic_quality_or_input'):
        qa.validate_native(native_run, 'S03', tmp_path)


def test_diagnostic_keeps_the_real_source_status(tmp_path, monkeypatch):
    _, native_run, _, context = diagnostic_fixture(tmp_path, monkeypatch)
    context['source_evaluation'] = dict(status='ready')
    with pytest.raises(ValueError, match='diagnostic_source_evaluation'):
        qa.validate_native(native_run, 'S03', tmp_path)
