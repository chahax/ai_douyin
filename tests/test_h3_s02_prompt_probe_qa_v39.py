"""Only synthetic ancestry bytes; no native service, GPU or ASR model."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import shutil

import pytest

PROJECT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qa = load('single_probe_cpu_qa_v39', PROJECT / 'scripts/qa_h3_s02_prompt_probe_v39.py')
base_fixture = load('baseline_v38_fixture_for_single', PROJECT / 'tests/test_h3_baseline_two_rounds_qa_v38.py')
write = base_fixture.write


def single_fixture(root):
    source = base_fixture.fixture_run(root, 'R2')
    old_folder = source / 'shots/S02'
    old_result = qa.read(old_folder / 'RESULT.json')
    old_graph = qa.read(old_folder / 'workflow_api.json')
    cfg = qa.read(source / 'PLAN.json')['config']
    run, sid, pid = root / qa.ROOT_REL, 'S02', 'fixture_single_new_S02'
    folder = run / 'shots/S02'
    folder.mkdir(parents=True)
    prompt = run / 'PROMPT.txt'
    text = old_graph['condition']['inputs']['prompt'] + '\nfixture prompt adjustment'
    prompt.write_bytes(text.encode('utf-8'))
    first = folder / 'first_input.png'
    shutil.copyfile(old_folder / 'first_input.png', first)
    scope = 'fixture_probe_v39/S02'
    graph = deepcopy(old_graph)
    graph['condition']['inputs']['prompt'] = text
    graph['ref_scene']['inputs']['image'] = scope + '/first_input.png'
    for role in ('video', 'audio', 'first', 'last'):
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    staged = Path(cfg['input_root']) / scope / 'first_input.png'
    staged.parent.mkdir(parents=True)
    shutil.copyfile(first, staged)
    row = dict(id=sid, scope=scope, graph_sha256=qa.digest(graph), first_frame=qa.bind(first),
               input_name=scope + '/first_input.png', seed=graph['129']['inputs']['noise_seed'],
               source_prompt=qa.bind(prompt), source_request=qa.bind(old_folder / 'REQUEST.json'),
               source_first=qa.bind(old_folder / 'first_input.png'))
    plan = dict(schema=qa.SCHEMA, shot=row, config=cfg, prompt=qa.bind(prompt),
                source_plan=qa.bind(source / 'PLAN.json'), source_result=qa.bind(old_folder / 'RESULT.json'),
                source_request=qa.bind(old_folder / 'REQUEST.json'), source_native_id=old_result['prompt_id'],
                max_native_video_submissions=1, image_generation_calls=0, publication=False)
    files, outputs = {}, {}
    for role, old in old_result['files'].items():
        native = Path(cfg['output_root']) / scope / Path(old['source_path']).name
        native.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(old['path'], native)
        local = folder / 'artifacts' / native.name
        local.parent.mkdir(exist_ok=True)
        shutil.copyfile(native, local)
        files[role] = dict(**qa.bind(local), source_path=str(native))
        outputs['save_' + role] = {'audio' if role == 'audio' else 'images':
                                 [dict(type='output', subfolder=scope, filename=native.name)]}
    result = dict(schema='visual_h3_handoff/v3', shot_id=sid, prompt_id=pid, technical_status='technical_saved',
                  graph_sha256=qa.digest(graph), first_frame_sha256=qa.sha(first), files=files)
    write(run / 'PLAN.json', plan)
    write(folder / 'GRAPH_BINDING.json', row)
    write(folder / 'workflow_api.json', graph)
    write(folder / 'REQUEST.json', dict(prompt=graph))
    write(folder / 'CLAIM.json', dict(graph_sha256=qa.digest(graph), first_frame_sha256=qa.sha(first)))
    write(folder / 'RESPONSE.json', dict(prompt_id=pid))
    write(folder / 'STATE.json', dict(id=sid, prompt_id=pid, status='technical_saved', plan_sha256=qa.digest(plan)))
    write(folder / 'HISTORY.json', {pid: dict(prompt=[0, pid, graph], status=dict(completed=True, status_str='success'), outputs=outputs)})
    write(folder / 'RESULT.json', result)
    write(run / 'FINAL_RESULT.json', dict(schema=qa.SCHEMA, native_id=pid, native_result=qa.bind(folder / 'RESULT.json'),
          file=qa.bind(files['video']['path']), files=files, postprocessing=[], publication=False))
    return run


def test_single_saved_ID_four_originals_and_two_quotes(tmp_path):
    result = qa.validate(single_fixture(tmp_path), tmp_path)
    assert result['native_id'] == 'fixture_single_new_S02'
    assert len(result['originals']) == 4 and len(result['expected_quotes']) == 2


def test_single_sampling_covers_whole_clip_and_specific_risk_windows():
    plan = qa.sample_plan()
    assert plan['half_second'] == list(range(0, 361, 12)) + [361]
    assert len(plan['half_second']) == 32
    assert len(plan['subtitle_window']) == 81 and plan['subtitle_window'][0] == 0 and plan['subtitle_window'][-1] == 240
    assert len(plan['inner_voice_window']) == 41 and plan['inner_voice_window'][0] == 48 and plan['inner_voice_window'][-1] == 168


def test_unknown_is_never_relabelled_saved(tmp_path):
    run = single_fixture(tmp_path)
    path = run / 'shots/S02/STATE.json'
    state = qa.read(path)
    state['status'] = 'outcome_unknown'
    write(path, state)
    with pytest.raises(ValueError, match='new_saved_native_ID'):
        qa.validate(run, tmp_path)


@pytest.mark.parametrize('role', ('video', 'audio', 'first', 'last'))
def test_changed_original_is_blocked(tmp_path, role):
    run = single_fixture(tmp_path)
    result = qa.read(run / 'shots/S02/RESULT.json')
    Path(result['files'][role]['source_path']).write_bytes(b'changed_fixture')
    with pytest.raises(ValueError, match='original_output_SHA'):
        qa.validate(run, tmp_path)


def test_old_minute_run_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='explicit_single_v39_probe'):
        qa.validate(tmp_path / 'old_h3', tmp_path)
