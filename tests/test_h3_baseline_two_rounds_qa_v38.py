"""CPU-only fixtures; no production media, service or model calls."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('baseline_cpu_qa_v38', PROJECT / 'scripts/qa_h3_baseline_two_rounds_v38.py')
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def fixture_run(root, round_name='R1'):
    """Non-media bytes test ancestry only, never a claimed generated film."""
    run = root / qa.ROOT_REL / round_name
    output, inputs = root / 'native_output', root / 'native_input'
    output.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(exist_ok=True)
    rows, prepared = [], []
    for index, sid in enumerate(qa.IDS):
        folder = run / 'shots' / sid
        folder.mkdir(parents=True)
        prompt = ''.join(f'“fixture {sid} quote {i}”' for i in range(qa.QUOTE_COUNTS[index]))
        p = run / 'prompts' / (sid + '.txt')
        p.parent.mkdir(exist_ok=True)
        p.write_text(prompt, encoding='utf-8')
        first = folder / 'first_input.png'
        Image.new('RGB', (32, 48), (20 + index, 40, 80)).save(first)
        name = 'fixture/' + round_name + '/' + sid + '/first_input.png'
        staged = inputs / name
        staged.parent.mkdir(parents=True)
        shutil.copyfile(first, staged)
        graph = {'condition': {'inputs': {'prompt': prompt}},
                 'ref_scene': {'class_type': 'LoadImage', 'inputs': {'image': name}},
                 '129': {'inputs': {'noise_seed': index}}}
        for role in ('video', 'audio', 'first', 'last'):
            graph['save_' + role] = dict(inputs=dict(filename_prefix='fixture_output/' + round_name + '/' + sid + '/' + role))
        gh, pid, scope = qa.digest(graph), 'fixture_' + round_name + '_' + sid, 'fixture_output/' + round_name + '/' + sid
        baseline_request = root / 'baseline' / round_name / (sid + '.REQUEST.json')
        write(baseline_request, dict(prompt=graph))
        baseline_prompt = root / 'baseline' / round_name / (sid + '.txt')
        baseline_prompt.write_text(prompt, encoding='utf-8')
        row = dict(id=sid, scope=scope, graph_sha256=gh, first_frame=qa.bind(first), first=qa.bind(first),
                   baseline_first=qa.bind(first), baseline_request=qa.bind(baseline_request),
                   baseline_prompt=qa.bind(baseline_prompt), seed=index, baseline_seed=index,
                   input_name=name, prompt=qa.bind(p), source_prompt=qa.bind(p))
        rows.append(row)
        files, saved = {}, {}
        for role, suffix in [('video', '.mp4'), ('audio', '.flac'), ('first', '.png'), ('last', '.png')]:
            native = output / scope / (role + '_00001_' + suffix)
            native.parent.mkdir(parents=True, exist_ok=True)
            if suffix == '.png':
                Image.new('RGB', (32, 48), (40 + index, 60, 100 if role == 'first' else 150)).save(native)
            else:
                native.write_bytes(b'not_generated_fixture_' + (sid + role).encode())
            local = folder / 'artifacts' / native.name
            local.parent.mkdir(exist_ok=True)
            shutil.copyfile(native, local)
            files[role] = dict(**qa.bind(local), source_path=str(native))
            key = 'audio' if role == 'audio' else 'images'
            saved['save_' + role] = {key: [dict(filename=native.name, subfolder=scope, type='output')]}
        result = dict(schema='visual_h3_handoff/v3', shot_id=sid, prompt_id=pid, graph_sha256=gh,
                      first_frame_sha256=qa.sha(first), technical_status='technical_saved', files=files)
        write(folder / 'RESULT.json', result)
        write(folder / 'workflow_api.json', graph)
        write(folder / 'GRAPH_BINDING.json', row)
        write(folder / 'REQUEST.json', dict(prompt=graph))
        write(folder / 'RESPONSE.json', dict(prompt_id=pid))
        write(folder / 'CLAIM.json', dict(graph_sha256=gh, first_frame_sha256=qa.sha(first)))
        write(folder / 'HISTORY.json', {pid: dict(prompt=[0, pid, graph], status=dict(completed=True, status_str='success'), outputs=saved)})
        prepared.append((folder, sid, pid))
    plan = dict(schema=qa.SCHEMA, round=round_name, image_generation_calls=0, publication=False, production_approved=False,
                profile=dict(width=736, height=1312, frames=362, fps=24, steps=12, native_audio=True),
                config=dict(output_root=str(output), input_root=str(inputs)), segments=rows)
    write(run / 'PLAN.json', plan)
    for folder, sid, pid in prepared:
        write(folder / 'STATE.json', dict(id=sid, prompt_id=pid, status='technical_saved', plan_sha256=qa.digest(plan)))
    final_movie = run / ('BASELINE_' + round_name + '_736x1312.mp4')
    final_movie.write_bytes(b'not_a_video_fixture_only')
    results = [qa.bind(folder / 'RESULT.json') for folder, _, _ in prepared]
    write(run / 'FINAL_RESULT.json', dict(schema=qa.SCHEMA, round=round_name, publication=False, production_approved=False,
          file=qa.bind(final_movie), native_ids=[pid for _, _, pid in prepared],
          native_results=results, assembly_inputs_sha256=qa.digest(dict(plan=qa.bind(run / 'PLAN.json'), native_results=results))))
    return run


def test_new_round_scope_only(tmp_path):
    assert qa.scoped(tmp_path / qa.ROOT_REL / 'R1', tmp_path).name == 'R1'
    assert qa.scoped(tmp_path / qa.ROOT_REL / 'R2', tmp_path).name == 'R2'
    for target in [tmp_path / qa.ROOT_REL / 'R3', tmp_path / 'old_h3', tmp_path / qa.ROOT_REL / 'R1' / 'nested']:
        with pytest.raises(ValueError, match='explicit_new'):
            qa.scoped(target, tmp_path)


def test_binding_four_native_ids_and_sixteen_originals(tmp_path):
    value = qa.validate(fixture_run(tmp_path), project=tmp_path)
    assert len(value['values']) == 4
    assert len({r['native_id'] for r in value['values']}) == 4
    assert sum(len(r['originals']) for r in value['values']) == 16
    assert sum(len(r['expected_quotes']) for r in value['values']) == 10


@pytest.mark.parametrize('role', ['video', 'audio', 'first', 'last'])
def test_original_source_change_blocked(tmp_path, role):
    run = fixture_run(tmp_path)
    result = qa.read(run / 'shots/S01/RESULT.json')
    Path(result['files'][role]['source_path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='native_original_SHA'):
        qa.validate(run, project=tmp_path)


def test_unknown_native_not_reinterpreted_as_saved(tmp_path):
    run = fixture_run(tmp_path)
    path = run / 'shots/S02/STATE.json'
    state = qa.read(path)
    state['status'] = 'outcome_unknown'
    write(path, state)
    with pytest.raises(ValueError, match='STATE_not_original_saved'):
        qa.validate(run, project=tmp_path)


def test_actual_request_or_native_id_tamper_blocked(tmp_path):
    run = fixture_run(tmp_path)
    path = run / 'shots/S02/REQUEST.json'
    value = qa.read(path)
    value['prompt']['condition']['inputs']['prompt'] = 'changed'
    write(path, value)
    with pytest.raises(ValueError, match='REQUEST_graph'):
        qa.validate(run, project=tmp_path)


def test_actual_first_staged_pixels_tamper_blocked(tmp_path):
    run = fixture_run(tmp_path)
    (tmp_path / 'native_input/fixture/R1/S03/first_input.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='first_input_staging'):
        qa.validate(run, project=tmp_path)


def test_final_native_order_cannot_relabel(tmp_path):
    run = fixture_run(tmp_path)
    path = run / 'FINAL_RESULT.json'
    value = qa.read(path)
    value['native_ids'].reverse()
    write(path, value)
    with pytest.raises(ValueError, match='assembly_original_inputs'):
        qa.validate(run, project=tmp_path)


def test_sampling_includes_every_second_final_frame_and_actual_joins():
    plan = qa.sample_plan()
    assert plan['timeline'] == list(range(0, 1441, 24)) + [1447]
    assert len(plan['timeline']) == 62
    assert [(r['start'], r['end']) for r in plan['dense']] == [(0, 3), (26, 28), (29, 31), (44, 46), (49, 51)]
    for entry, boundary in zip(plan['joins'], (361, 723, 1085)):
        assert {boundary, boundary + 1}.issubset(entry['indices'])
        assert min(entry['indices']) >= boundary - 12
        assert max(entry['indices']) <= boundary + 13


def test_asr_quotes_do_not_claim_speaker_or_missing_audio(tmp_path):
    path = tmp_path / 'ASR.json'
    write(path, {'result': [dict(text='哥哥 发传单', timestamp=[[100, 400], [400, 900]])]})
    actual, intervals = qa.asr_intervals(path, ['哥哥发传单', '没说出来的句子'])
    assert intervals[0]['start_ms'] == 100 and intervals[0]['end_ms'] == 900
    assert intervals[1]['exactly_detected'] is False and intervals[1]['start_ms'] is None
    assert qa.LIMITS['asr_identifies_acoustic_speaker'] is False
    assert qa.LIMITS['asr_missing_match_proves_missing_speech'] is False


@pytest.fixture(scope='module')
def short_cpu_clip(tmp_path_factory):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('local FFmpeg required for CPU fixture')
    directory = tmp_path_factory.mktemp('short_cpu_media_v38')
    path = directory / 'CPU_SYNTHETIC_NOT_PRODUCTION.mp4'
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=navy:s=736x1312:r=24:d=3',
            '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000:duration=3',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', '-ac', '2',
            '-t', '3', str(path)]
    subprocess.run(args, check=True, capture_output=True, timeout=60)
    return path


def test_real_short_cpu_probe_extract_and_idempotent_board(short_cpu_clip, tmp_path):
    timing, metadata = qa.inspect_clock(short_cpu_clip, 72)
    assert timing['clock']['decoded_frames'] == 72
    assert timing['clock']['decoded_pts_exact_i_over_24'] is True
    frames = qa.extract_batch(short_cpu_clip, [0, 24, 48, 71], tmp_path / 'frames')
    assert set(frames) == {0, 24, 48, 71}
    before = {k: v['sha256'] for k, v in frames.items()}
    again = qa.extract_batch(short_cpu_clip, [0, 24, 48, 71], tmp_path / 'frames')
    assert {k: v['sha256'] for k, v in again.items()} == before
    board = qa.make_board(list(frames.values()), tmp_path / 'CONTACT.jpg')
    assert Path(board['path']).is_file()
    comparison = qa.first_comparison(frames[0], frames[0], tmp_path / 'COMPARE.jpg')
    assert comparison['mean_absolute_pixel_difference'] == 0
    assert comparison['semantic_or_identity_pass'] is None


def test_cli_rejects_old_run_without_models_or_outputs(tmp_path):
    result = subprocess.run([sys.executable, str(PROJECT / 'scripts/qa_h3_baseline_two_rounds_v38.py'),
                             '--run', str(tmp_path / 'old'), '--project-root', str(tmp_path)],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 2
    assert json.loads(result.stdout)['no_media_retry'] is True
    assert not list(tmp_path.rglob('*.json'))


def synthetic_sampling(monkeypatch, counter):
    """Exercise orchestration; these mocked clocks are never production evidence."""
    def clock_fixture(video, frames, *, final=False):
        counter['clock'] += 1
        return dict(clock=dict(decoded_frames=frames), explicit_unit_fixture=True), {'explicit_unit_fixture': True}

    def extract_fixture(video, wanted, directory):
        counter['extract'] += 1
        directory.mkdir(parents=True, exist_ok=True)
        results = {}
        for index in sorted(set(wanted)):
            path = directory / f'actual_{index:04d}.png'
            if not path.exists():
                Image.new('RGB', (32, 48), (index % 255, 50, 80)).save(path)
            results[index] = dict(**qa.bind(path), frame_index=index, seconds=index / 24)
        return results
    monkeypatch.setattr(qa, 'inspect_clock', clock_fixture)
    monkeypatch.setattr(qa, 'extract_batch', extract_fixture)


def test_full_evidence_workflow_and_completed_idempotence(tmp_path, monkeypatch):
    run = fixture_run(tmp_path)
    counter = dict(clock=0, extract=0)
    synthetic_sampling(monkeypatch, counter)
    result = qa.qa(run, project=tmp_path)
    assert result['status'] == 'CPU_QA_complete'
    report = qa.read(result['manifest']['path'])
    assert len(report['timeline']) == 3
    assert sum(len(page['indices']) for page in report['timeline']) == 62
    assert len(report['segments']) == 4 and len(report['joins']) == 3
    assert report['root_overall_video_review'] is None
    assert report['production_approved'] is False
    assert counter == dict(clock=5, extract=5)
    again = qa.qa(run, project=tmp_path)
    assert again['status'] == 'already_complete'
    assert counter == dict(clock=5, extract=5)


def test_failed_cpu_attempt_preserved_then_only_unfinished_work_resumed(tmp_path, monkeypatch):
    run = fixture_run(tmp_path)
    counter = dict(clock=0, extract=0)
    synthetic_sampling(monkeypatch, counter)
    original_extract = qa.extract_batch
    monkeypatch.setattr(qa, 'extract_batch', lambda *a, **k: (_ for _ in ()).throw(ValueError('CPU_fixture_decode_failure')))
    with pytest.raises(ValueError, match='CPU_fixture_decode_failure'):
        qa.qa(run, project=tmp_path)
    errors = list(run.rglob('attempts/*/ERROR.json'))
    assert len(errors) == 1 and qa.read(errors[0])['no_media_retry'] is True
    error_sha = qa.sha(errors[0])
    monkeypatch.setattr(qa, 'extract_batch', original_extract)
    assert qa.qa(run, project=tmp_path)['status'] == 'CPU_QA_complete'
    assert qa.sha(errors[0]) == error_sha
    assert len(list(run.rglob('attempts/*/COMPLETE.json'))) == 1


def test_native_AAC_short_end_uses_source_tolerance_not_final_clock(tmp_path, monkeypatch):
    metadata = {'streams': [dict(codec_type='audio', duration_ts=482400, time_base='1/32000')]}
    monkeypatch.setattr(qa, 'clock', lambda *a, **k: ({'explicit_fixture': True}, metadata))
    result, _ = qa.inspect_clock(tmp_path / 'NOT_MEDIA', 362)
    assert result['audio_end_skew_seconds'] == pytest.approx(-1 / 120)
    with pytest.raises(ValueError, match='actual_audio_end_skew'):
        qa.inspect_clock(tmp_path / 'NOT_MEDIA', 362, final=True)


def test_cpu_asr_binding_idempotence_and_tamper_rejection(tmp_path, monkeypatch):
    transcriber = tmp_path / 'scripts/transcribe_video_local.py'
    transcriber.parent.mkdir()
    transcriber.write_text('# fixture, no model execution', encoding='utf-8')
    video = tmp_path / 'NOT_A_VIDEO.mp4'
    video.write_bytes(b'fixture')
    value = dict(originals=dict(video=dict(local=qa.bind(video))), expected_quotes=['哥哥发传单'])
    folder = tmp_path / 'asr'
    counter = {'calls': 0}

    def command_fixture(args):
        Path(args[-1]).write_bytes(b'not_a_WAV_fixture')

    def transcribe_fixture(project, wav, output, folder):
        counter['calls'] += 1
        write(output, {'result': [dict(text='哥哥 发传单', timestamp=[[100, 400], [400, 900]])]})
    monkeypatch.setattr(qa, 'command', command_fixture)
    monkeypatch.setattr(qa, 'transcribe', transcribe_fixture)
    assert qa.cpu_asr(tmp_path, value, folder, True)['quote_intervals'][0]['exactly_detected'] is True
    assert qa.cpu_asr(tmp_path, value, folder, True)['status'] == 'CPU_ASR_complete'
    assert counter['calls'] == 1
    (folder / 'ASR.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='existing_ASR_binding_changed'):
        qa.cpu_asr(tmp_path, value, folder, True)


def test_R2_is_blocked_without_actual_R1_overall_review(tmp_path):
    run = fixture_run(tmp_path, 'R2')
    with pytest.raises(ValueError, match='R2_requires_actual_completed'):
        qa.validate(run, project=tmp_path)


def test_R2_choices_bind_actual_R1_review_and_final(tmp_path):
    r1, r2 = fixture_run(tmp_path), fixture_run(tmp_path, 'R2')
    r1_final = qa.read(r1 / 'FINAL_RESULT.json')
    review = r1 / 'ROOT_OVERALL_VIDEO_REVIEW.json'
    write(review, dict(schema='h3_baseline_overall_review/v38', review_completed_by='root_agent',
          overall_video_review_completed=True, allow_prepare_r2=True, final_result=qa.bind(r1 / 'FINAL_RESULT.json'),
          reviewed_video=r1_final['file'], explicit_synthetic_test_fixture=True))
    plan = qa.read(r2 / 'PLAN.json')
    plan['r1_overall_review'] = qa.bind(review)
    choices = r2 / 'ROUND_SPEC.json'
    write(choices, dict(schema='h3_baseline_round_spec/v38', round='R2', r1_overall_review=qa.bind(review),
          segments=[dict(id=r['id'], first=r['first'], prompt=r['prompt']) for r in plan['segments']]))
    plan['round_spec'] = qa.bind(choices)
    write(r2 / 'PLAN.json', plan)
    for sid in qa.IDS:
        path = r2 / 'shots' / sid / 'STATE.json'
        state = qa.read(path)
        state['plan_sha256'] = qa.digest(plan)
        write(path, state)
    final = qa.read(r2 / 'FINAL_RESULT.json')
    final['assembly_inputs_sha256'] = qa.digest(dict(plan=qa.bind(r2 / 'PLAN.json'), native_results=final['native_results']))
    write(r2 / 'FINAL_RESULT.json', final)
    assert len(qa.validate(r2, project=tmp_path)['values']) == 4
    changed = qa.read(review)
    changed['allow_prepare_r2'] = False
    write(review, changed)
    with pytest.raises(ValueError, match='bound_file_SHA_changed'):
        qa.validate(r2, project=tmp_path)
