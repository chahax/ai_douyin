"""Synthetic single-job evidence fixtures, no models or native service."""
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


qa = load('official_probe_cpu_qa_v40', PROJECT / 'scripts/qa_h3_s02_official_prompt_probe_v40.py')
old = load('prior_probe_v39_fixture_for_official', PROJECT / 'tests/test_h3_s02_prompt_probe_qa_v39.py')
write = old.write


def fixture_run(root):
    source = old.single_fixture(root)
    source_folder = source / 'shots/S02'
    prior = qa.read(source_folder / 'RESULT.json')
    source_graph = qa.read(source_folder / 'workflow_api.json')
    old_plan = qa.read(source / 'PLAN.json')
    run, folder = root / qa.ROOT_REL, root / qa.ROOT_REL / 'shots/S02'
    folder.mkdir(parents=True)
    words = qa.quotes(source_graph['condition']['inputs']['prompt'])
    text = 'first line\n[S1] adult [S2] child\n' + ''.join(f'<d>[Chinese] {s} </d>' for s in words)
    prompt = run / 'PROMPT.txt'
    prompt.write_bytes(text.encode('utf-8'))
    first = folder / 'first_input.png'
    shutil.copyfile(source_folder / 'first_input.png', first)
    scope = 'fixture_official_probe/S02'
    graph = deepcopy(source_graph)
    graph['condition']['inputs']['prompt'] = text
    graph['ref_scene']['inputs']['image'] = scope + '/first_input.png'
    for role in ('video', 'audio', 'first', 'last'):
        graph['save_' + role]['inputs']['filename_prefix'] = scope + '/' + role
    staged = Path(old_plan['config']['input_root']) / scope / 'first_input.png'
    staged.parent.mkdir(parents=True)
    shutil.copyfile(first, staged)
    row = dict(id='S02', scope=scope, graph_sha256=qa.digest(graph), first_frame=qa.bind(first),
               input_name=scope + '/first_input.png', seed=graph['129']['inputs']['noise_seed'],
               source_prompt=qa.bind(prompt), source_request=qa.bind(source_folder / 'REQUEST.json'),
               source_first=qa.bind(source_folder / 'first_input.png'))
    plan = dict(schema=qa.SCHEMA, shot=row, config=old_plan['config'], prompt=qa.bind(prompt),
                source_plan=qa.bind(source / 'PLAN.json'), source_result=qa.bind(source_folder / 'RESULT.json'),
                source_request=qa.bind(source_folder / 'REQUEST.json'), source_native_id=prior['prompt_id'],
                max_native_video_submissions=1, image_generation_calls=0, publication=False)
    pid, files, outputs = 'fixture_new_official_native_S02', {}, {}
    for role, item in prior['files'].items():
        native = Path(plan['config']['output_root']) / scope / Path(item['source_path']).name
        native.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item['path'], native)
        local = folder / 'artifacts' / native.name
        local.parent.mkdir(exist_ok=True)
        shutil.copyfile(native, local)
        files[role] = dict(**qa.bind(local), source_path=str(native))
        outputs['save_' + role] = {'audio' if role == 'audio' else 'images':
                                  [dict(type='output', subfolder=scope, filename=native.name)]}
    result = dict(schema='visual_h3_handoff/v3', shot_id='S02', prompt_id=pid,
                  technical_status='technical_saved', graph_sha256=qa.digest(graph),
                  first_frame_sha256=qa.sha(first), files=files)
    write(run / 'PLAN.json', plan)
    write(folder / 'GRAPH_BINDING.json', row)
    write(folder / 'workflow_api.json', graph)
    write(folder / 'REQUEST.json', dict(prompt=graph))
    write(folder / 'CLAIM.json', dict(graph_sha256=qa.digest(graph), first_frame_sha256=qa.sha(first)))
    write(folder / 'RESPONSE.json', dict(prompt_id=pid))
    write(folder / 'STATE.json', dict(id='S02', prompt_id=pid, status='technical_saved', plan_sha256=qa.digest(plan)))
    write(folder / 'HISTORY.json', {pid: dict(prompt=[0, pid, graph], status=dict(completed=True, status_str='success'), outputs=outputs)})
    write(folder / 'RESULT.json', result)
    write(run / 'FINAL_RESULT.json', dict(schema=qa.SCHEMA, native_id=pid,
          native_result=qa.bind(folder / 'RESULT.json'), file=qa.bind(files['video']['path']),
          files=files, postprocessing=[], publication=False))
    return run, words


def test_d_tags_trim_only_language_and_boundary_spaces_without_quotes():
    text = '[S1]<d> [Chinese] 我竟然穿成了继父。 </d> [S2]<d>[Chinese]\n爸爸，这是面包。\n</d>'
    assert qa.d_speech(text) == ['我竟然穿成了继父。', '爸爸，这是面包。']
    assert qa.quotes(text) == []


@pytest.mark.parametrize('text', [
    '<d>[Chinese] 一句 </d>',
    '<d>[Chinese] 一句 </d><d>[English] two </d>',
    '<d>[Chinese] </d><d>[Chinese] 第二句 </d>',
    '<d>[Chinese] 一句 </d><d>[Chinese] 二句 </d><d>[Chinese] 三句 </d>',
    '<d>[Chinese] 一句 <d>[Chinese] 二句 </d>',
])
def test_malformed_or_other_language_d_tags_blocked(text):
    with pytest.raises(ValueError):
        qa.d_speech(text)


def test_official_speech_validates_against_saved_v39_curly_quote_source(tmp_path):
    run, words = fixture_run(tmp_path)
    value = qa.validate(run, tmp_path)
    assert value['expected_quotes'] == words
    assert value['native_id'] == 'fixture_new_official_native_S02'
    assert len(value['originals']) == 4
    assert qa.quotes((run / 'PROMPT.txt').read_text(encoding='utf-8')) == []


def test_unknown_not_relabelled_and_no_old_probe_scope(tmp_path):
    run, _ = fixture_run(tmp_path)
    path = run / 'shots/S02/STATE.json'
    state = qa.read(path)
    state['status'] = 'outcome_unknown'
    write(path, state)
    with pytest.raises(ValueError, match='new_saved_native_ID'):
        qa.validate(run, tmp_path)
    with pytest.raises(ValueError, match='explicit_single_v40_probe'):
        qa.validate(tmp_path / old.qa.ROOT_REL, tmp_path)


def test_sampling_preserved_and_no_four_segment_requirements():
    samples = qa.sample_plan()
    assert [len(samples[k]) for k in ['half_second', 'subtitle_window', 'inner_voice_window']] == [32, 81, 41]
