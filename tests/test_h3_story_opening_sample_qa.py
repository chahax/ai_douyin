"""Synthetic saved-native ancestry; upstream visual/core evaluation is stubbed.

These tests verify the reader's source/POST/output boundary, not image quality.
No FFmpeg, ASR, GPU, model or service is invoked.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import qa_h3_story_opening_sample as qa


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def fixture(root, monkeypatch):
    run = root / 'data/video_generation/new_opening'
    h3 = run / 'visual_h3_v3/opening_S02'
    folder = h3 / 'shots/S02'
    folder.mkdir(parents=True)
    first, previous = run / 'new_first.png', run / 'previous.png'
    for path, color in ((first, 'gray'), (previous, 'brown')):
        Image.new('RGB', (736, 1312), color).save(path)
    entry = dict(shot_id='S02', first_frame_policy=qa.opening.POLICY,
                 duration=15,
                 actual_first_image=qa.bind(previous), source=qa.bind(previous),
                 source_scope=dict(start=0, end=1), source_spans=[],
                 camera_beats=[dict(start=0, end=15, cut=False, framing='face_close',
                                    actors={'su_mo': dict(visible_parts=['face'], pose='lying')},
                                    source_span_ids=[])],
                 canonical_characters={'su_mo': qa.bind(first)}, canonical_room=qa.bind(previous))
    source_path = run / 'VIDEO_SOURCE_CASE.json'
    write(source_path, dict(schema=qa.core.SCHEMA, shots=[entry]))
    source = qa.bind(source_path)
    text = '0—7秒，父亲闭口心声：“原句一。”\n7—15秒，孩子说：“原句二。”'
    review = run / 'fixture_review.json'
    write(review, {'fixture_only_not_visual_approval': True})
    observed = dict(status='ready', schema=qa.core.SCHEMA, entry_sha256=qa.digest(entry),
                    first_image=qa.bind(first), coverage_review=qa.bind(review),
                    compiled_prompt=text, compiled_prompt_utf8_sha256=qa.core.sha(text),
                    generation_receipt=dict(actual_generation_inputs_verified=True,
                                            synthetic_protocol_fixture_only=True))
    monkeypatch.setattr(qa.core, 'evaluate', lambda _: deepcopy(observed))
    monkeypatch.setattr(qa.native, '_http', lambda *a, **k: pytest.fail('QA must not contact a service'))
    proof = qa.native._continuity_proof(dict(observed, plan=source))
    scope, input_name, pid = 'fixture/opening_S02/S02', 'fixture/first.png', 'fixture_original_S02'
    graph = {key: dict(class_type=kind, inputs={}) for key, kind in qa.native.CLASSES.items()}
    graph['condition']['inputs'].update(first_frame=['ref_scene', 0], width=736, height=1312,
                                       length=362, prompt=text)
    graph['ref_scene']['inputs'] = dict(image=input_name)
    graph['127']['inputs'] = dict(unet_name='minimax_h3_fl2va_pruned_int8_convrot.safetensors')
    for node, key in [('119', 'vae_name'), ('120', 'vae_name'), ('128', 'clip_name')]:
        graph[node]['inputs'][key] = 'fixture.safetensors'
    graph['124']['inputs']['steps'] = 12
    graph['129']['inputs']['noise_seed'] = 41
    graph['130']['inputs']['fps'] = 24
    for role in ('video', 'audio', 'first', 'last'):
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    inputs, outputs = root / 'input', root / 'output'
    staged = inputs / input_name
    staged.parent.mkdir(parents=True)
    staged.write_bytes(first.read_bytes())
    row = dict(id='S02', scope=scope, input_name=input_name, first_frame=qa.bind(first),
               graph_sha256=qa.digest(graph), continuity_input=proof,
               timing=dict(requested_seconds=15, native_frames=362, automatic_audio_cut=False))
    plan = dict(schema=qa.native.SCHEMA, publication=False, old_batch_resume=False,
                upstream_contract=qa.core.SCHEMA, continuity_source_plan=source,
                config=dict(input_root=str(inputs), output_root=str(outputs), continuity_input_plan=source),
                shots=[row])
    files, history_outputs = {}, {}
    for role, suffix in [('video', '.mp4'), ('audio', '.flac'), ('first', '.png'), ('last', '.png')]:
        origin = outputs / scope / (role + '_00001_' + suffix)
        origin.parent.mkdir(parents=True, exist_ok=True)
        origin.write_bytes(b'synthetic_non_media_' + role.encode())
        local = folder / 'artifacts' / origin.name
        local.parent.mkdir(exist_ok=True)
        local.write_bytes(origin.read_bytes())
        files[role] = dict(**qa.bind(local), source_path=str(origin))
        history_outputs['save_' + role] = {
            'audio' if role == 'audio' else 'images':
                [dict(filename=origin.name, subfolder=scope, type='output')]}
    result = dict(schema=qa.native.SCHEMA, shot_id='S02', prompt_id=pid,
                  technical_status='technical_saved', publication=False, production_approved=False,
                  graph_sha256=qa.digest(graph), first_frame_sha256=qa.sha(first),
                  continuity_input=proof, files=files, timing=row['timing'])
    write(h3 / 'PLAN.json', plan)
    write(folder / 'workflow_api.json', graph)
    write(folder / 'REQUEST.json', dict(prompt=graph))
    write(folder / 'RESPONSE.json', dict(prompt_id=pid))
    write(folder / 'STATE.json', dict(status='technical_saved', id='S02', prompt_id=pid,
                                     plan_sha256=qa.digest(plan)))
    write(folder / 'CLAIM.json', dict(graph_sha256=qa.digest(graph), first_frame_sha256=qa.sha(first)))
    write(folder / 'RESULT.json', result)
    write(folder / 'HISTORY.json', {pid: dict(prompt=[0, pid, graph],
        status=dict(completed=True, status_str='success'), outputs=history_outputs)})
    write(run / 'FINAL_RESULT.json', dict(native_result=qa.bind(folder / 'RESULT.json'),
        file=qa.bind(files['video']['path']), prompt_id=pid, postprocessing=[]))
    return run, folder


def test_saved_original_lineage_is_read_without_HTTP(tmp_path, monkeypatch):
    run, _ = fixture(tmp_path, monkeypatch)
    result = qa.validate(run, tmp_path)
    assert result['native_id'] == 'fixture_original_S02'
    assert len(result['originals']) == 4 and len(result['expected_quotes']) == 2
    assert result['opening_contract']['opening_visible_actors'] == ['su_mo']
    assert result['actual_seed'] == 41


def test_unknown_record_is_not_promoted_to_saved(tmp_path, monkeypatch):
    run, folder = fixture(tmp_path, monkeypatch)
    state = qa.read(folder / 'STATE.json')
    state['status'] = 'outcome_unknown'
    write(folder / 'STATE.json', state)
    with pytest.raises(ValueError, match='saved_original_native_ID'):
        qa.validate(run, tmp_path)


@pytest.mark.parametrize('role', ['video', 'audio', 'first', 'last'])
def test_altered_native_original_is_rejected(tmp_path, monkeypatch, role):
    run, folder = fixture(tmp_path, monkeypatch)
    origin = qa.read(folder / 'RESULT.json')['files'][role]['source_path']
    Path(origin).write_bytes(b'changed')
    with pytest.raises(ValueError, match='native_original_pixels'):
        qa.validate(run, tmp_path)


def test_changed_first_policy_is_not_silently_accepted(tmp_path, monkeypatch):
    run, _ = fixture(tmp_path, monkeypatch)
    source = run / 'VIDEO_SOURCE_CASE.json'
    value = qa.read(source)
    value['shots'][0].pop('first_frame_policy')
    write(source, value)
    with pytest.raises(ValueError, match='VIDEO_SOURCE_CASE_binding'):
        qa.validate(run, tmp_path)


def test_sample_windows_include_actual_frame_zero_and_entire_clip():
    sample = qa.sample_plan()
    assert sample['half_second'] == list(range(0, 361, 12)) + [361]
    assert sample['opening_dense'] == list(range(0, 49, 3))
    assert sample['inner_voice'][0] == 0 and sample['inner_voice'][-1] == 168


def test_crop_origin_is_verified_as_derivative_not_relabelled_native():
    receipt = dict(kind='derived_opening_crop/v1', exact_pixels_verified=True, native_output=False,
                   parent_generation_proof=dict(actual_generation_inputs_verified=True))
    assert qa.verified_image_origin(receipt)
    receipt['native_output'] = True
    assert not qa.verified_image_origin(receipt)
    receipt['native_output'] = False
    receipt['parent_generation_proof']['actual_generation_inputs_verified'] = None
    assert not qa.verified_image_origin(receipt)
