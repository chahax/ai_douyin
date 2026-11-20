"""Synthetic CPU/protocol fixtures; these tests never generate H3 media."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest

from scripts import qa_spatial_movie_v24 as qa


TEXTS = {
    'S01': ['二哥，今天没偷到钱，怎么办呀？', '哥哥发传单挣了十块，先给你。', '不行，你没交上钱，他会打你的。'],
    'S02': ['我竟然穿成了六个孩子的恶毒继父。书里，他们长大后会报复我。', '爸爸，这是好心人给我的面包。'],
    'S03': ['这孩子后来成了独眼神医。还好，现在他的眼睛还是完好的。', '他一定在想怎么打我。'],
    'S04': ['做得很好，下次不要了。', '好的爸爸，我下次一定不会只带个面包，我会偷很多钱回来。', '我说的是，不要再出去偷东西啊！'],
}


@pytest.fixture(scope='module')
def cpu_media(tmp_path_factory):
    folder = tmp_path_factory.mktemp('SPATIAL_CPU_ONLY_FIXTURE')
    for name, width, height, frames in [('probe', 288, 512, 124), ('native', 736, 1312, 362), ('final', 736, 1312, 1448)]:
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', f'color=c=gray:s={width}x{height}:r=24',
                        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-frames:v', str(frames), '-t', str(frames / 24),
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000',
                        '-video_track_timescale', '12288', '-movie_timescale', '48000', str(folder / (name + '.mp4'))], check=True, timeout=90)
        Image.new('RGB', (width, height), 'gray').save(folder / (name + '.png'))
        if name != 'final':
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                            '-t', str(frames / 24), '-c:a', 'flac', str(folder / (name + '.flac'))], check=True, timeout=30)
    return folder


def put(path, data):
    qa.write(path, data)
    return qa.binding(path)


def fixture(root, media, *, profile='probe', end_guide=False, native_floats=False, native_format=False, handoff=None, versioned_place_ids=False, bare_place_ids=False):
    experiment = root / qa.EXPERIMENT
    run = experiment / 'variants' / ('canary_A' if profile == 'probe' else 'B' if native_format else 'A')
    source = root / 'data/video_generation/h3_reference_full_minute_20261107_v1'
    parent = put(source / 'PLAN.json', {'synthetic_CPU_protocol_fixture': True})
    auth = put(experiment / 'AUTH.json', dict(schema='spatial_minute_experiment_authorization/v24',
               user_statement='CPU fixture, not production media authorization', publication=False, new_cloud_media_calls=0))
    pause = put(root / 'data/old_PAUSE.json', dict(unchanged=True))
    provenance = put(experiment / 'INPUTS.json', dict(fixture=True))
    refs = []
    for i, ref_id in enumerate(qa.REFERENCE_IDS):
        path = experiment / 'refs' / (str(i) + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (32, 48), ('gray' if i < 3 else 'blue')).save(path)
        kind, entity, view = ref_id.split(':')
        if versioned_place_ids and kind == 'place':
            ref_id = ('' if bare_place_ids else kind + ':' + entity + ':') + 'room_' + view + '_spatial_v26'
        image = qa.binding(path)
        review = put(experiment / 'reviews' / (str(i) + '.json'), dict(reviewed_by='root_agent', accepted_for_reference=True,
                     image=image, entity_id=entity, provenance=provenance))
        refs.append(dict(reference_id=ref_id, kind=kind, entity_id=entity, view=view, display_name=entity,
                         description='CPU declared reference ' + entity, image=image, provenance=provenance, root_review=review))
    guide_file = experiment / 'guide.png'
    Image.new('RGB', (736, 1312), 'gray').save(guide_file)
    guide_image = qa.binding(guide_file)
    old_result = put(experiment / 'OLD_NATIVE_RESULT.json', dict(prompt_id='ORIGINAL_CPU_FIXTURE', technical_status='technical_saved', files=dict(first=guide_image)))
    guide_review = put(experiment / 'reviews/guide.json', dict(reviewed_by='root_agent', accepted_for_guide=True, image=guide_image))
    guide = dict(image=guide_image, native_result=old_result, role='first', root_review=guide_review)
    segments = []
    for sid in (['S01'] if profile == 'probe' else qa.IDS):
        original = source / 'sources' / (sid + '.prompt.txt')
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_text('CPU fixture source\n' + '\n'.join('角色：“' + q + '”' for q in TEXTS[sid]), encoding='utf-8')
        prompt = experiment / 'sources' / (sid + '.txt')
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text('CPU fixture actual prompt\n' + '\n'.join('角色：“' + q + '”' for q in (TEXTS[sid][:1] if profile == 'probe' else TEXTS[sid])), encoding='utf-8')
        if native_format:
            prompt.write_text('subject_definitions:\n<Subject 1> <Subject 2> <Subject 3> <Subject 4>\n<Picture 1> <Picture 2> <Picture 3> <Picture 4> <Picture 5>\n\nsummary:\nCPU protocol fixture\n\nretention_analysis:\nDeclared references only.\n\ndetailed_description:\n' + '\n'.join('<d>[Mandarin Chinese] “' + q + '”</d>' for q in TEXTS[sid]) + '\n\noverall_soundscape:\nRoom tone.\n\nnon_diegetic_music:\nN/A\n', encoding='utf-8')
        segment = dict(id=sid, original_prompt=qa.binding(original), prompt=qa.binding(prompt))
        if end_guide is True or end_guide == sid:
            segment['end_guide'] = guide
        segments.append(segment)
    config = dict(service_url='http://127.0.0.1:8190', input_root=str(experiment / 'native_input'), output_root=str(experiment / 'native_output'), timeout=30)
    base = {'condition': dict(class_type='MiniMaxH3ImageToVideo', inputs=dict(clip=['128', 0], vae=['119', 0])),
            '119': dict(class_type='VAELoader', inputs={}), '128': dict(class_type='CLIPLoader', inputs={}),
            '124': dict(class_type='BasicScheduler', inputs=dict(steps=12, denoise=1)),
            '127': dict(class_type='UNETLoader', inputs={}), '129': dict(class_type='RandomNoise', inputs={}),
            '126': dict(class_type='BasicGuider', inputs={}), '130': dict(class_type='CreateVideo', inputs=dict(fps=24)),
            'pick_first': dict(class_type='ImageFromBatch', inputs={}), 'pick_last': dict(class_type='ImageFromBatch', inputs={})}
    for role in qa.ROLES:
        base['save_' + role] = dict(class_type='SaveAudio' if role == 'audio' else 'SaveVideo' if role == 'video' else 'SaveImage', inputs={})
    base_binding = put(experiment / 'BASE_GRAPH.json', base)
    spec_config = dict(config, base_workflow=base_binding)
    width, height, frames = (288, 512, 124) if profile == 'probe' else (736, 1312, 362)
    settings = dict(schema='spatial_h3_spec/v24', variant=run.name, profile=profile, parent_runner_plan=parent,
                    authorization=auth, references=refs, initial_guide=guide, segments=segments,
                    width=width, height=height, frames=frames, config=spec_config, seed=12345)
    if native_format:
        settings['prompt_format'] = 'official_ref2va_v29'
    if handoff:
        settings['spatial_handoff'] = qa.binding(handoff)
    spec = put(experiment / ('SPEC_' + run.name + '.json'), settings)
    approval = put(experiment / ('APPROVAL_' + run.name + '.json'), dict(reviewed_by='root_agent', approved_for_generation=True,
                   spec=spec, diagnostic_only=True))
    plan = dict(schema=qa.DELIVERY, variant=run.name, profile=profile, spec=spec, approval=approval, authorization=auth,
                settings=settings, config=config, base=base, protected_pause=pause, diagnostic_preview=True, production_approved=False, publication=False)
    put(run / 'PLAN.json', plan)
    for index, segment in enumerate(segments):
        sid = segment['id']
        folder = run / 'shots' / sid
        scope = 'visual_spatial_h3_v24/' + run.name + '/' + sid
        actual_guide = deepcopy(guide)
        if index:
            previous_path = run / 'shots' / segments[index - 1]['id'] / 'RESULT.json'
            previous = qa.read(previous_path)
            actual_guide = dict(image={k: previous['files']['last'][k] for k in ('path', 'sha256')}, native_result=qa.binding(previous_path),
                                role='last', native_id=previous['prompt_id'], previous_segment=segments[index - 1]['id'],
                                policy='actual_previous_native_tail_even_if_semantically_imperfect')
        graph = qa.expected_graph(plan, segment, scope)
        digest = qa.fingerprint(graph)
        put(folder / 'workflow_api.json', graph)
        row = dict(id=sid, scope=scope, graph_sha256=digest, guide=actual_guide, source_prompt=segment['prompt'],
                   reference_sha256=qa.fingerprint(refs), end_guide=segment.get('end_guide'))
        put(folder / 'GRAPH_BINDING.json', row)
        put(folder / 'CLAIM.json', dict(graph_sha256=digest, at=0))
        put(folder / 'REQUEST.json', dict(prompt=graph, client_id='CPU_FIXTURE'))
        pid = 'CPU_FIXTURE_NATIVE_' + sid
        put(folder / 'RESPONSE.json', dict(prompt_id=pid))
        for name, image in [(f'references/{i}.png', r['image']) for i, r in enumerate(refs)] + [('guides/start.png', actual_guide['image'])] + ([('guides/end.png', guide['image'])] if segment.get('end_guide') else []):
            stage = Path(config['input_root']) / scope / name
            stage.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image['path'], stage)
        files, outputs = {}, {}
        kind = 'probe' if profile == 'probe' else 'native'
        for role, suffix, original in [('video', '.mp4', kind + '.mp4'), ('audio', '.flac', kind + '.flac'), ('first', '.png', kind + '.png'), ('last', '.png', kind + '.png')]:
            name = role + '_00001_' + suffix
            native_source = Path(config['output_root']) / scope / name
            native_source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(media / original, native_source)
            if role == 'video':
                with native_source.open('ab') as stream:
                    stream.write(('CPU_PROTOCOL_FIXTURE_' + sid).encode())
            target = folder / 'artifacts' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(native_source, target)
            files[role] = dict(path=str(target), source_path=str(native_source), sha256=qa.sha(target))
            outputs['save_' + role] = {('audio' if role == 'audio' else 'images'): [dict(filename=name, subfolder=scope, type='output')]}
        observed = deepcopy(graph)
        if native_floats:
            observed['124']['inputs']['denoise'] = 1.0
            observed['130']['inputs']['fps'] = 24.0
        put(folder / 'HISTORY.json', {pid: dict(prompt=[0, pid, observed], status=dict(completed=True, status_str='success'), outputs=outputs)})
        result = dict(schema=qa.DELIVERY, shot_id=sid, prompt_id=pid, graph_sha256=digest, files=files, guide=actual_guide,
                      source_prompt=segment['prompt'], references_sha256=qa.fingerprint(refs), technical_status='technical_saved',
                      content_status='diagnostic_raw_quality_not_gated', production_approved=False, publication=False)
        put(folder / 'RESULT.json', result)
        put(folder / 'STATE.json', dict(id=sid, status='technical_saved', prompt_id=pid, graph_sha256=digest,
                                      plan_sha256=qa.fingerprint(plan), result_sha256=qa.sha(folder / 'RESULT.json')))
    if native_format:
        put(experiment / 'B_NATIVE_COMPILED_PREFLIGHT.json', dict(native_spec=spec, rows=[dict(
            id=s['id'], actual_compiled_text_exact_source=True,
            utf8_sha256=__import__('hashlib').sha256(Path(s['prompt']['path']).read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
            quote_count=len(TEXTS[s['id']]), end_guide=bool(s.get('end_guide'))) for s in segments]))
    return run


def test_cpu_probe_samples_bindings_guide_comparison_and_repeat(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, native_floats=True)
    originals = {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    first = qa.qa_segment(run, 'S01', project=tmp_path)
    assert first['status'] == 'cpu_qa_complete' and first['production_approved'] is False
    report = qa.read(first['manifest']['path'])
    assert report['geometry'] == dict(width=288, height=512, native_frames=124, decoded_frames=124, fps=24, seconds=124 / 24)
    assert len(report['frames']) == 6 and report['native_graph_float_normalizations'] == ['124.inputs.denoise', '130.inputs.fps']
    assert report['guide_vs_native_first_metrics']['semantic_pass'] is None
    assert report['planned_spatial']['status'] == 'not_supplied' and report['asr_status'] == 'not_requested'
    assert qa.qa_segment(run, 'S01', project=tmp_path) == first
    assert all(Path(path).read_bytes() == data for path, data in originals.items())


@pytest.mark.parametrize('mutation', ['unknown', 'pid', 'result', 'history', 'bool_float', 'arbitrary_numeric', 'frame0', 'refs', 'stage', 'claim', 'source', 'native_output', 'guide', 'pause', 'history_output'])
def test_tampered_or_unknown_native_inputs_block_before_any_cpu_command(tmp_path, cpu_media, monkeypatch, mutation):
    run = fixture(tmp_path, cpu_media)
    folder = run / 'shots/S01'
    state, result, graph = qa.read(folder / 'STATE.json'), qa.read(folder / 'RESULT.json'), qa.read(folder / 'workflow_api.json')
    pid = result['prompt_id']
    history = qa.read(folder / 'HISTORY.json')
    if mutation == 'unknown': state['status'] = 'outcome_unknown'
    if mutation == 'pid': state['prompt_id'] = 'another'
    if mutation == 'result': state['result_sha256'] = '0' * 64
    if mutation == 'history': history[pid]['status']['completed'] = False
    if mutation == 'bool_float': history[pid]['prompt'][2]['124']['inputs']['denoise'] = True
    if mutation == 'arbitrary_numeric': history[pid]['prompt'][2]['condition']['inputs']['width'] = 288.0
    if mutation == 'frame0': graph['guide_start']['inputs']['frame_idx'] = 1
    if mutation == 'refs': graph.pop('ref_4')
    if mutation == 'stage':
        plan = qa.read(run / 'PLAN.json')
        (Path(plan['config']['input_root']) / 'visual_spatial_h3_v24/canary_A/S01/guides/start.png').write_bytes(b'tamper')
    if mutation == 'claim': put(folder / 'CLAIM.json', dict(graph_sha256='0' * 64))
    if mutation == 'source': Path(result['source_prompt']['path']).write_text('changed', encoding='utf-8')
    if mutation == 'native_output': Path(result['files']['video']['source_path']).write_bytes(b'tamper')
    if mutation == 'guide':
        row = qa.read(folder / 'GRAPH_BINDING.json')
        row['guide']['role'] = 'last'
        put(folder / 'GRAPH_BINDING.json', row)
    if mutation == 'pause': put(Path(qa.read(run / 'PLAN.json')['protected_pause']['path']), dict(changed=True))
    if mutation == 'history_output': history[pid]['outputs']['save_last']['images'][0]['filename'] = 'other.png'
    put(folder / 'STATE.json', state)
    put(folder / 'workflow_api.json', graph)
    put(folder / 'HISTORY.json', history)
    monkeypatch.setattr(qa, 'command', lambda *a, **k: pytest.fail('invalid native input reached ffmpeg'))
    monkeypatch.setattr(qa, 'transcribe', lambda *a, **k: pytest.fail('invalid native input reached ASR'))
    with pytest.raises(ValueError):
        qa.qa_segment(run, 'S01', asr=True, project=tmp_path)
    assert not (run / 'qc').exists()


def test_optional_end_guide_is_time_anchored_and_preserved(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, end_guide=True)
    result = qa.validate_segment(run, 'S01', project=tmp_path)
    assert result['row']['end_guide']['role'] == 'first'
    assert qa.read(run / 'shots/S01/workflow_api.json')['guide_end']['inputs']['frame_idx'] == 123


def test_actual_native_tail_chain_has_no_fabricated_root_review(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, profile='minute')
    result = qa.validate_segment(run, 'S04', project=tmp_path)
    assert result['result']['guide']['previous_segment'] == 'S03'
    assert 'root_review' not in result['result']['guide']
    previous = run / 'shots/S03/RESULT.json'
    changed = qa.read(previous)
    changed['files']['last']['sha256'] = '0' * 64
    put(previous, changed)
    with pytest.raises(ValueError):
        qa.validate_segment(run, 'S04', project=tmp_path)


def test_cpu_asr_detects_quotes_without_claiming_listening_review(tmp_path, cpu_media, monkeypatch):
    run = fixture(tmp_path, cpu_media)
    calls = []
    def asr(project, wav, output, folder):
        calls.append(str(wav))
        put(output, dict(fixture='protocol only, no model run', result=[dict(text=TEXTS['S01'][0])]))
    monkeypatch.setattr(qa, 'transcribe', asr)
    first = qa.qa_segment(run, 'S01', asr=True, project=tmp_path)
    report = qa.read(first['manifest']['path'])
    assert report['normalized_matches'] is True and report['quoted_speech_exactly_detected'][0]['exactly_detected'] is True
    assert 'not proof of omission' in report['scope']
    assert qa.qa_segment(run, 'S01', asr=True, project=tmp_path) == first and len(calls) == 1


def test_cli_blackbox_idempotent_and_no_legacy_scope(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media)
    args = [sys.executable, '-X', 'utf8', '-B', qa.__file__, 'segment', '--run', str(run), '--segment', 'S01', '--project-root', str(tmp_path)]
    first = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert first.returncode == 0, first.stdout + first.stderr
    second = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert second.returncode == 0 and json.loads(first.stdout) == json.loads(second.stdout)
    with pytest.raises(ValueError, match='scope'):
        qa.qa_segment(tmp_path / 'data/video_generation/old_H3', 'S01', project=tmp_path)


def test_explicit_spatial_plan_is_labelled_planned_not_actual(tmp_path, cpu_media):
    spatial = tmp_path / qa.EXPERIMENT / 'spatial'
    plan = put(spatial / 'SPATIAL_PLAN.json', dict(schema='explicit_spatial_scene/v24', metric_basis='fictional staging design'))
    handoff = spatial / 'HANDOFF.json'
    put(handoff, dict(schema='spatial_reference_handoff/v24', plan=plan,
                     segments=[dict(id='S01', start_state=dict(actors={'su_mo': 'planned lying'}), end_state=dict(actors={'su_mo': 'planned lying'}))]))
    (spatial / 'diagrams').mkdir()
    for suffix in ('start', 'end'):
        Image.new('RGB', (64, 64), 'blue').save(spatial / 'diagrams' / ('S01_' + suffix + '.png'))
    run = fixture(tmp_path, cpu_media, handoff=handoff)
    receipt = qa.qa_segment(run, 'S01', spatial_handoff=handoff, project=tmp_path)
    report = qa.read(receipt['manifest']['path'])
    assert report['planned_spatial']['status'] == 'planned_only_not_actual_detection'
    assert 'not actual actor recognition' in report['scope']


def test_official_native_six_sections_are_exact_source_without_legacy_appendix(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, profile='minute', native_format=True, end_guide=True)
    value = qa.validate_segment(run, 'S04', project=tmp_path)
    graph = qa.read(run / 'shots/S04/workflow_api.json')
    assert graph['condition']['inputs']['prompt'] == value['source'].read_text(encoding='utf-8')
    assert '参考身份与环境' not in graph['condition']['inputs']['prompt']
    assert value['prompt_preflight']['legacy_chinese_appendix_present'] is False
    assert value['prompt_preflight']['quote_count'] == 3
    assert value['prompt_preflight']['actual_request_prompt_utf8_sha256'] == value['prompt_preflight']['preflight_prompt_utf8_sha256']
    assert value['row']['guide']['previous_segment'] == 'S03'


def test_native_s03_bound_end_guide_actual_last_and_decoded_frame361_board(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, profile='minute', native_format=True, end_guide='S03')
    receipt = qa.qa_segment(run, 'S03', project=tmp_path)
    report = qa.read(receipt['manifest']['path'])
    end = report['end_guide_vs_actual']
    source = qa.read(run / 'PLAN.json')['settings']['segments'][2]['end_guide']
    assert end['input_guide'] == source and end['frame_index'] == 361
    assert end['original_native_last'] == qa.read(run / 'shots/S03/RESULT.json')['files']['last']
    assert qa.sha(end['decoded_last']['path']) == end['decoded_last']['sha256']
    assert end['guide_to_native_last_metrics']['semantic_pass'] is None
    assert Image.open(end['contact']['path']).size == (864, 554)
    assert receipt['end_guide_vs_actual'] == end['contact']
    assert qa.qa_segment(run, 'S03', project=tmp_path) == receipt
    Path(source['image']['path']).write_bytes(b'changed original guide')
    with pytest.raises(ValueError):
        qa.qa_segment(run, 'S03', project=tmp_path)


@pytest.mark.parametrize('bare_ids', [False, True])
def test_reference_asset_version_suffix_is_not_misread_as_camera_view(tmp_path, cpu_media, bare_ids):
    run = fixture(tmp_path, cpu_media, profile='minute', native_format=True, versioned_place_ids=True, bare_place_ids=bare_ids)
    value = qa.validate_segment(run, 'S04', project=tmp_path)
    refs = value['plan']['settings']['references']
    assert refs[3]['reference_id'].endswith('room_front_spatial_v26') and refs[3]['view'] == 'front'
    assert refs[4]['reference_id'].endswith('room_side_spatial_v26') and refs[4]['view'] == 'side'
    assert value['prompt_preflight']['exact_source_text'] is True


def test_reference_view_declaration_still_requires_both_room_front_and_side(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, versioned_place_ids=True)
    plan = qa.read(run / 'PLAN.json')
    plan['settings']['references'][4]['view'] = 'front'
    spec_path = Path(plan['spec']['path'])
    put(spec_path, plan['settings']);plan['spec'] = qa.binding(spec_path)
    approval = qa.read(plan['approval']['path']);approval['spec'] = plan['spec']
    put(plan['approval']['path'], approval);plan['approval'] = qa.binding(plan['approval']['path'])
    put(run / 'PLAN.json', plan)
    with pytest.raises(ValueError, match='ordered five'):
        qa.validate_segment(run, 'S01', project=tmp_path)


@pytest.mark.parametrize('mutation', ['hash', 'spec', 'appendix'])
def test_native_preflight_or_legacy_appendix_mutation_fails_before_cpu(tmp_path, cpu_media, monkeypatch, mutation):
    run = fixture(tmp_path, cpu_media, profile='minute', native_format=True)
    path = tmp_path / qa.EXPERIMENT / 'B_NATIVE_COMPILED_PREFLIGHT.json'
    preflight = qa.read(path)
    if mutation == 'hash': preflight['rows'][0]['utf8_sha256'] = '0' * 64
    if mutation == 'spec': preflight['native_spec']['sha256'] = '0' * 64
    if mutation == 'appendix':
        source = qa.read(run / 'PLAN.json')['settings']['segments'][0]['prompt']
        with Path(source['path']).open('a', encoding='utf-8') as stream:
            stream.write('\n参考身份与环境：苏墨\n')
    put(path, preflight)
    monkeypatch.setattr(qa, 'command', lambda *a, **k: pytest.fail('tampered native prompt reached CPU command'))
    with pytest.raises(ValueError):
        qa.qa_segment(run, 'S01', project=tmp_path)


def test_arbitrary_planned_spatial_handoff_is_not_attached_to_unrelated_spec(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media)
    handoff = tmp_path / qa.EXPERIMENT / 'unconsumed/HANDOFF.json'
    put(handoff, dict(unconsumed_design_only=True))
    with pytest.raises(ValueError, match='actual frozen SPEC'):
        qa.qa_segment(run, 'S01', spatial_handoff=handoff, project=tmp_path)


def test_final_real_cpu_clock_and_three_before_after_join_pairs(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, profile='minute')
    final = run / 'DIAGNOSTIC_MINUTE_736x1312.mp4'
    shutil.copyfile(cpu_media / 'final.mp4', final)
    results = [qa.binding(run / 'shots' / sid / 'RESULT.json') for sid in qa.IDS]
    ids = [qa.read(r['path'])['prompt_id'] for r in results]
    put(run / 'FINAL_RESULT.json', dict(schema=qa.DELIVERY, file=qa.binding(final), native_ids=ids,
        assembly_inputs_sha256=qa.fingerprint(dict(plan=qa.binding(run / 'PLAN.json'), results=results))))
    first = qa.qa_final(run, project=tmp_path)
    report = first['clock']
    assert report['stream_audio_samples'] == 2896000 and report['decoded_frames'] == 1448
    assert report['video_start'] == report['audio_start'] == 0 and len(report['joins']) == 3
    assert [(j['frame_before'], j['frame_after']) for j in report['joins']] == [(361, 362), (723, 724), (1085, 1086)]
    assert all(j['pixel_difference']['semantic_pass'] is None for j in report['joins'])
    assert qa.qa_final(run, project=tmp_path) == first
    Path(qa.read(run / 'shots/S02/RESULT.json')['files']['video']['path']).write_bytes(b'tamper')
    with pytest.raises(ValueError):
        qa.qa_final(run, project=tmp_path)


def test_derived_tamper_is_not_silently_reaccepted(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media)
    receipt = qa.qa_segment(run, 'S01', project=tmp_path)
    Path(receipt['contact']['path']).write_bytes(b'tamper')
    with pytest.raises(ValueError, match='bound source'):
        qa.qa_segment(run, 'S01', project=tmp_path)


def room_only_fixture(root, media):
    """CPU-only A native receipts plus an independent two-room donor SPEC."""
    a_run = fixture(root, media, profile='minute')
    experiment = root / qa.EXPERIMENT
    a_plan = qa.read(a_run / 'PLAN.json')
    a_spec = deepcopy(a_plan['settings'])
    a_binding = put(experiment / 'A_SPEC.json', a_spec)
    a_plan['spec'] = a_binding
    approved = qa.read(a_plan['approval']['path'])
    approved['spec'] = a_binding
    put(a_plan['approval']['path'], approved)
    a_plan['approval'] = qa.binding(a_plan['approval']['path'])
    put(a_run / 'PLAN.json', a_plan)
    for sid in qa.IDS:
        path = a_run / 'shots' / sid / 'STATE.json'
        state = qa.read(path)
        state['plan_sha256'] = qa.fingerprint(a_plan)
        put(path, state)
    donor = deepcopy(a_spec)
    donor.update(variant='B', prompt_format='official_ref2va_v29', seed=99999)
    for i in (3, 4):
        path = experiment / 'donor' / f'room_{i}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (32, 48), 'tan' if i == 3 else 'brown').save(path)
        image = qa.binding(path)
        provenance = put(path.with_suffix('.provenance.json'), dict(CPU_fixture_only=True, input_index=i))
        proof = put(path.with_suffix('.review.json'), dict(reviewed_by='root_agent', accepted_for_reference=True,
                    entity_id='su_mo_room', image=image, provenance=provenance))
        donor['references'][i].update(image=image, provenance=provenance, root_review=proof,
                                     reference_id='room_versioned_' + str(i))
    donor_binding = put(experiment / 'B_NATIVE_SPEC.json', donor)
    authorization = dict(schema='spatial_room_only_authorization/v31', user_statement='好',
                         approved_proposal='CPU fixture: replace two room images only', interpretation='CPU protocol only',
                         engineering_scope_not_user_quoted_numeric_limit=True, baseline_a_spec=a_binding,
                         spatial_room_donor_spec=donor_binding, max_full_video_submissions=4, max_probe_video_submissions=0,
                         new_cloud_media_calls=0, publication=False, old_authorization_and_usage_preserved=True,
                         service_restarts=False, downloads=False, unknown_native_replay=False)
    auth_binding = put(experiment / 'C_ROOM_ONLY_USER_AUTHORIZATION.json', authorization)
    spec = deepcopy(a_spec)
    spec.update(variant=qa.ROOM_ONLY_VARIANT, authorization=auth_binding)
    for i in (3, 4):
        for key in ('image', 'provenance', 'root_review'):
            spec['references'][i][key] = deepcopy(donor['references'][i][key])
    spec_binding = put(experiment / 'C_ROOM_ONLY_SPEC.json', spec)
    rows = []
    for i, sid in enumerate(qa.IDS):
        text = qa.read(a_run / 'shots' / sid / 'REQUEST.json')['prompt']['condition']['inputs']['prompt']
        digest = __import__('hashlib').sha256(text.encode('utf-8')).hexdigest()
        rows.append(dict(id=sid, actual_a_prompt_utf8_sha256=digest, c_compiled_prompt_utf8_sha256=digest,
                         exact_prompt_equal=True, graph_equal_except_output_and_staging_namespace=True,
                         seed=a_spec['seed']+i, guide_end=False))
    put(experiment / 'room_only_v31/SINGLE_FACTOR_PREFLIGHT.json', dict(schema='spatial_room_only_preflight/v31',
        baseline_spec=a_binding, test_spec=spec_binding, rows=rows, changed_reference_slots_zero_based=[3, 4]))
    return experiment / 'variants' / qa.ROOM_ONLY_VARIANT, spec


def update_room_candidate(run, spec):
    root = run.parent.parent
    put(root / 'C_ROOM_ONLY_SPEC.json', spec)
    path = root / 'room_only_v31/SINGLE_FACTOR_PREFLIGHT.json'
    preflight = qa.read(path)
    preflight['test_spec'] = qa.binding(root / 'C_ROOM_ONLY_SPEC.json')
    put(path, preflight)


def test_room_only_independent_preflight_reads_actual_A_and_does_not_create_C_run(tmp_path, cpu_media, monkeypatch):
    run, spec = room_only_fixture(tmp_path, cpu_media)
    before = {str(p): p.read_bytes() for p in (tmp_path / qa.EXPERIMENT).rglob('*') if p.is_file()}
    monkeypatch.setattr(qa, 'command', lambda *a, **k: pytest.fail('preflight called a media process'))
    cert = qa.validate_room_only_spec(spec, run, project=tmp_path)
    assert cert['changed_fields'] == [f'references[{i}].{k}' for i in (3, 4) for k in ('image', 'provenance', 'root_review')]
    assert len(cert['compiled_prompt_comparison']) == 4 and cert['production_approved'] is False
    assert all(r['actual_a_prompt_utf8_sha256'] == r['c_compiled_prompt_utf8_sha256'] for r in cert['compiled_prompt_comparison'])
    assert not run.exists()
    assert {str(p): p.read_bytes() for p in (tmp_path / qa.EXPERIMENT).rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('mutation', ['seed', 'float_seed', 'character', 'initial_guide', 'prompt', 'config',
    'width', 'end_guide', 'room_id', 'room_view', 'description', 'prompt_format', 'extra', 'profile', 'variant', 'wrong_donor_image'])
def test_room_only_rejects_any_change_beyond_exact_six_fields(tmp_path, cpu_media, mutation):
    run, spec = room_only_fixture(tmp_path, cpu_media)
    if mutation == 'seed': spec['seed'] += 1
    if mutation == 'float_seed': spec['seed'] = float(spec['seed'])
    if mutation == 'character': spec['references'][0]['image'] = spec['references'][3]['image']
    if mutation == 'initial_guide': spec['initial_guide']['role'] = 'last'
    if mutation == 'prompt': spec['segments'][0]['prompt'] = spec['segments'][1]['prompt']
    if mutation == 'config': spec['config']['timeout'] += 1
    if mutation == 'width': spec['width'] += 16
    if mutation == 'end_guide': spec['segments'][2]['end_guide'] = spec['initial_guide']
    if mutation == 'room_id': spec['references'][3]['reference_id'] = 'new_id'
    if mutation == 'room_view': spec['references'][4]['view'] = 'front'
    if mutation == 'description': spec['references'][3]['description'] = 'different description changes compiled text'
    if mutation == 'prompt_format': spec['prompt_format'] = 'official_ref2va_v29'
    if mutation == 'extra': spec['new_metadata'] = 'unapproved'
    if mutation == 'profile': spec['profile'] = 'probe'
    if mutation == 'variant': spec['variant'] = 'other_room_test'
    if mutation == 'wrong_donor_image': spec['references'][3]['image'] = spec['references'][4]['image']
    update_room_candidate(run, spec)
    with pytest.raises(ValueError):
        qa.validate_room_only_spec(spec, run, project=tmp_path)


@pytest.mark.parametrize('mutation', ['full', 'full_float', 'probe', 'cloud', 'replay', 'restart', 'download',
    'publish', 'preserve', 'statement', 'baseline_alias', 'donor_alias', 'auth_alias', 'wrong_run'])
def test_room_only_authorization_path_bindings_and_four_zero_limits(tmp_path, cpu_media, mutation):
    run, spec = room_only_fixture(tmp_path, cpu_media)
    root = run.parent.parent
    path = root / 'C_ROOM_ONLY_USER_AUTHORIZATION.json'
    auth = qa.read(path)
    changes = {'full': ('max_full_video_submissions', 5), 'full_float': ('max_full_video_submissions', 4.0),
        'probe': ('max_probe_video_submissions', 1), 'cloud': ('new_cloud_media_calls', 1),
        'replay': ('unknown_native_replay', True), 'restart': ('service_restarts', True),
        'download': ('downloads', True), 'publish': ('publication', True),
        'preserve': ('old_authorization_and_usage_preserved', False), 'statement': ('user_statement', 'yes')}
    if mutation in changes:
        key, value = changes[mutation];auth[key] = value
    if mutation in ('baseline_alias', 'donor_alias'):
        key = 'baseline_a_spec' if mutation == 'baseline_alias' else 'spatial_room_donor_spec'
        alias = root / (mutation + '.json');shutil.copyfile(auth[key]['path'], alias);auth[key] = qa.binding(alias)
    put(path, auth);spec['authorization'] = qa.binding(path)
    if mutation == 'auth_alias':
        alias = root / 'AUTH_COPY.json';shutil.copyfile(path, alias);spec['authorization'] = qa.binding(alias)
    update_room_candidate(run, spec)
    if mutation == 'wrong_run': run = run.with_name('C_other')
    with pytest.raises(ValueError):
        qa.validate_room_only_spec(spec, run, project=tmp_path)


@pytest.mark.parametrize('mutation', ['row_hash', 'equal_flag', 'graph_flag', 'seed', 'end', 'order', 'test_sha', 'A_request', 'donor_bytes'])
def test_room_only_preflight_does_not_trust_claims_or_changed_inputs(tmp_path, cpu_media, mutation):
    run, spec = room_only_fixture(tmp_path, cpu_media)
    root = run.parent.parent;path = root / 'room_only_v31/SINGLE_FACTOR_PREFLIGHT.json'
    data = qa.read(path)
    if mutation == 'row_hash': data['rows'][0]['c_compiled_prompt_utf8_sha256'] = '0' * 64
    if mutation == 'equal_flag': data['rows'][0]['exact_prompt_equal'] = False
    if mutation == 'graph_flag': data['rows'][0]['graph_equal_except_output_and_staging_namespace'] = False
    if mutation == 'seed': data['rows'][0]['seed'] += 1
    if mutation == 'end': data['rows'][2]['guide_end'] = True
    if mutation == 'order': data['rows'].reverse()
    if mutation == 'test_sha': data['test_spec']['sha256'] = '0' * 64
    if mutation == 'A_request':
        request_path = root / 'variants/A/shots/S01/REQUEST.json';request = qa.read(request_path)
        request['prompt']['condition']['inputs']['prompt'] += ' changed';put(request_path, request)
    if mutation == 'donor_bytes': Path(spec['references'][3]['image']['path']).write_bytes(b'changed donor bytes')
    put(path, data)
    with pytest.raises(ValueError):
        qa.validate_room_only_spec(spec, run, project=tmp_path)


def test_room_only_new_authorization_integrates_before_C_submission(tmp_path, cpu_media):
    run, spec = room_only_fixture(tmp_path, cpu_media)
    root = run.parent.parent;plan = qa.read(root / 'variants/A/PLAN.json')
    plan.update(variant=qa.ROOM_ONLY_VARIANT, settings=spec, authorization=spec['authorization'],
                spec=qa.binding(root / 'C_ROOM_ONLY_SPEC.json'))
    plan['approval'] = put(root / 'C_APPROVAL.json', dict(reviewed_by='root_agent', approved_for_generation=True,
                           diagnostic_only=True, spec=plan['spec']))
    put(run / 'PLAN.json', plan)
    put(run / 'shots/S01/STATE.json', dict(id='S01', status='prepared', plan_sha256=qa.fingerprint(plan)))
    with pytest.raises(FileNotFoundError, match='RESULT.json'):
        qa.validate_segment(run, 'S01', project=tmp_path)


def observation_fixture(root, media, status='running'):
    run, spec = room_only_fixture(root, media)
    experiment = run.parent.parent;plan = qa.read(experiment / 'variants/A/PLAN.json')
    plan.update(variant=qa.ROOM_ONLY_VARIANT, settings=spec, authorization=spec['authorization'],
                spec=qa.binding(experiment / 'C_ROOM_ONLY_SPEC.json'))
    plan['approval'] = put(experiment / 'C_APPROVAL.json', dict(reviewed_by='root_agent', approved_for_generation=True,
                         diagnostic_only=True, spec=plan['spec']))
    put(run / 'PLAN.json', plan)
    for sid in qa.IDS:
        put(run / 'shots' / sid / 'STATE.json', dict(id=sid, status=status if sid == 'S01' else 'prepared',
            prompt_id='CPU_C_ORIGINAL_S01' if sid == 'S01' else None, plan_sha256=qa.fingerprint(plan)))
    return run


def test_quote_interval_frames_are_actual_CPU_frames_without_speaker_claim(tmp_path, cpu_media):
    run = fixture(tmp_path, cpu_media, profile='minute')
    receipt = qa.qa_segment(run, 'S01', project=tmp_path)
    folder = Path(receipt['manifest']['path']).parent
    text = qa.normalized(TEXTS['S01'][0]);timestamps = [[100+i*100, 200+i*100] for i in range(len(text))]
    put(folder / 'ASR.json', dict(CPU_PROTOCOL_ONLY=True, result=[dict(text=' '.join(text), timestamp=timestamps)]))
    result = qa.quote_evidence(run, 'S01', project=tmp_path)
    data = qa.read(result['intervals']['path'])
    assert len(data['frames']) == 3 and data['quotes'][0]['start_ms'] == 100
    assert data['quotes'][0]['exactly_detected'] is True and data['quotes'][1]['exactly_detected'] is False
    assert 'no actual identity, mouth state' in data['scope'] and data['production_approved'] is False
    assert qa.quote_evidence(run, 'S01', project=tmp_path) == result
    video = qa.read(folder / 'OBJECTIVE_QA.json')['binding']['video']['path']
    Path(video).write_bytes(b'changed original video after QA')
    with pytest.raises(ValueError, match='bound source'):
        qa.quote_evidence(run, 'S01', project=tmp_path)


def test_room_only_observer_CLI_is_bounded_local_only_and_records_own_identity(tmp_path, cpu_media):
    run = observation_fixture(tmp_path, cpu_media)
    folder = tmp_path / 'data/qa/CPU_OBSERVER_FIXTURE'
    before = {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    args = [sys.executable, '-X', 'utf8', '-B', qa.__file__, 'observe-room-only', '--run', str(run),
            '--project-root', str(tmp_path), '--observer-dir', str(folder), '--first-native-id', 'CPU_C_ORIGINAL_S01',
            '--helper-sha256', qa.sha(qa.__file__), '--max-seconds', '1']
    process = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert process.returncode == 3, process.stdout + process.stderr
    assert json.loads(process.stdout)['status'] == 'bounded_observation_expired'
    identity = qa.read(folder / 'OBSERVER.json')
    assert identity['pid'] > 0 and identity['create_time'] > 0 and identity['command']
    assert identity['poll_seconds'] == 30 and identity['max_seconds'] == 1
    assert {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()} == before
    again = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert again.returncode == 2 and 'FileExistsError' in again.stdout


def test_room_only_observer_unknown_stops_itself_and_keeps_original_state(tmp_path, cpu_media, monkeypatch):
    run = observation_fixture(tmp_path, cpu_media, status='outcome_unknown')
    folder = tmp_path / 'data/qa/CPU_UNKNOWN_OBSERVER'
    state = (run / 'shots/S01/STATE.json').read_bytes()
    monkeypatch.setattr(qa.subprocess, 'run', lambda *a, **k: pytest.fail('observer attempted CPU/media replay'))
    with pytest.raises(ValueError, match='outcome_unknown'):
        qa.observe_room_only(run, folder, 'CPU_C_ORIGINAL_S01', qa.sha(qa.__file__), max_seconds=5, project=tmp_path)
    assert qa.read(folder / 'ERROR.json')['status'] == 'observer_stopped_on_error'
    assert (run / 'shots/S01/STATE.json').read_bytes() == state
    assert (folder / 'OBSERVER_CLAIM.json').exists()


def test_room_only_observer_stops_before_CPU_if_frozen_helper_changes(tmp_path, cpu_media, monkeypatch):
    run = observation_fixture(tmp_path, cpu_media, status='technical_saved')
    folder = tmp_path / 'data/qa/CPU_CHANGED_OBSERVER'
    original = qa.sha;source = Path(qa.__file__).resolve();expected = original(source);calls = []
    def source_changed(path):
        if Path(path).resolve() == source:
            calls.append(path)
            if len(calls) > 2:
                return '0' * 64
        return original(path)
    monkeypatch.setattr(qa, 'sha', source_changed)
    monkeypatch.setattr(qa.subprocess, 'run', lambda *a, **k: pytest.fail('changed source reached CPU subprocess'))
    with pytest.raises(ValueError, match='frozen helper changed'):
        qa.observe_room_only(run, folder, 'CPU_C_ORIGINAL_S01', expected, max_seconds=5, project=tmp_path)
    assert qa.read(folder / 'ERROR.json')['error']['type'] == 'ValueError'
