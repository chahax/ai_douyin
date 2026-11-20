"""Finite CPU evidence for the explicitly authorized R1/R2 films.

This is a result reader, not an executor or an automatic content approval.  The
old QA validators remain frozen; only their CPU clock/board/ASR helpers are used.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import uuid

from PIL import Image, ImageChops, ImageStat

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from qa_h3_continuity_minute_v34 import board, card, clock, asr_intervals
from qa_h3_reference_full_minute_cpu import command, transcribe

PROJECT = SCRIPTS.parent
ROOT_REL = Path('data/video_generation/h3_baseline_two_rounds_20261109_v1')
IDS = ('S01', 'S02', 'S03', 'S04')
SCHEMA = 'h3_baseline_two_rounds/v38'
QUOTE_COUNTS = (3, 2, 2, 3)
LIMITS = dict(asr_identifies_acoustic_speaker=False,
              asr_missing_match_proves_missing_speech=False,
              samples_prove_every_video_frame=False,
              visual_review='root_actual_sample_review_required',
              human_listening_review='not_performed_by_CPU_tool',
              production_approved=False)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def bind(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def freeze(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(read(path) == value, 'existing_CPU_evidence_binding_changed')
    else:
        with path.open('x', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
    return bind(path)


def checked(value, project):
    require(isinstance(value, dict) and isinstance(value.get('sha256'), str),
            'physical_file_binding_required')
    path = Path(value['path']).resolve()
    require(path.is_relative_to(Path(project).resolve()), 'bound_file_outside_project')
    require(path.is_file() and sha(path) == value['sha256'], 'bound_file_SHA_changed')
    return path


def scoped(run, project=PROJECT):
    run = Path(run).resolve()
    require(run.parent == (Path(project).resolve() / ROOT_REL) and run.name in ('R1', 'R2'),
            'explicit_new_R1_or_R2_required')
    return run


def quotes(text):
    return re.findall(r'[“「]([^”」]+)[”」]', text)


def normalized_graph(value):
    # Native validation may coerce numeric widget values to floats. Python
    # numeric equality preserves that harmless conversion without dropping keys.
    return value


def validate(run, *, project=PROJECT):
    """Independently bind the four actual requests and their native originals."""
    run = scoped(run, project)
    plan = read(run / 'PLAN.json')
    require(plan.get('schema') == SCHEMA and plan.get('round') == run.name and
            plan.get('image_generation_calls') == 0 and plan.get('publication') is False and
            plan.get('production_approved') is False, 'v38_frozen_PLAN_schema_required')
    require(plan.get('profile') == dict(width=736, height=1312, frames=362, fps=24,
                                       steps=12, native_audio=True), 'v38_native_profile_changed')
    rows = plan.get('segments', [])
    require([r.get('id') for r in rows] == list(IDS), 'four_ordered_segments_required')
    plan_binding = bind(run / 'PLAN.json')
    cfg = plan['config']
    output_root = Path(cfg['output_root']).resolve()
    input_root = Path(cfg['input_root']).resolve()
    require(output_root.is_relative_to(Path(project).resolve()) and
            input_root.is_relative_to(Path(project).resolve()), 'local_service_roots_required')
    values = []
    for index, row in enumerate(rows):
        sid = row['id']
        folder = run / 'shots' / sid
        state = read(folder / 'STATE.json')
        result = read(folder / 'RESULT.json')
        graph_binding = read(folder / 'GRAPH_BINDING.json')
        require(graph_binding == row, 'frozen_PLAN_GRAPH_BINDING_changed')
        graph = read(folder / 'workflow_api.json')
        request = read(folder / 'REQUEST.json')
        response = read(folder / 'RESPONSE.json')
        claim = read(folder / 'CLAIM.json')
        pid = state.get('prompt_id')
        require(state.get('status') == 'technical_saved' and state.get('id') == sid and
                state.get('plan_sha256') == digest(plan), 'source_STATE_not_original_saved')
        require(isinstance(pid, str) and pid == response.get('prompt_id') == result.get('prompt_id') and
                result.get('shot_id') == sid and result.get('schema') == 'visual_h3_handoff/v3' and
                result.get('technical_status') == 'technical_saved', 'native_RESULT_identity_changed')
        gh = digest(graph)
        require(gh == graph_binding.get('graph_sha256') == result.get('graph_sha256') ==
                claim.get('graph_sha256') and request.get('prompt') == graph,
                'actual_REQUEST_graph_binding_changed')
        history = read(folder / 'HISTORY.json').get(pid, {})
        hp, hs = history.get('prompt', []), history.get('status', {})
        require(len(hp) > 2 and hp[1] == pid and normalized_graph(hp[2]) == graph and
                hs.get('completed') is True and hs.get('status_str') == 'success',
                'original_native_success_history_changed')
        prompt_path = checked(row['prompt'], project)
        require(prompt_path == run / 'prompts' / (sid + '.txt'), 'actual_prompt_path_changed')
        prompt = prompt_path.read_bytes().decode('utf-8')
        condition = graph['condition']['inputs']
        require(condition.get('prompt') == prompt, 'actual_POST_prompt_not_frozen_prompt_bytes')
        require(row['source_prompt'] == row['prompt'], 'frozen_source_prompt_binding_changed')
        expected = quotes(prompt)
        require(len(expected) == QUOTE_COUNTS[index], 'actual_prompt_source_quote_coverage_changed')
        baseline_request = read(checked(row['baseline_request'], project))
        baseline_graph = baseline_request['prompt']
        baseline_text = checked(row['baseline_prompt'], project).read_bytes().decode('utf-8')
        require(quotes(baseline_text) == expected == quotes(baseline_graph['condition']['inputs']['prompt']),
                'original_ten_quoted_speech_changed')
        restored = deepcopy(graph)
        restored['condition']['inputs']['prompt'] = baseline_graph['condition']['inputs']['prompt']
        restored['ref_scene']['inputs']['image'] = baseline_graph['ref_scene']['inputs']['image']
        for role in ('video', 'audio', 'first', 'last'):
            restored['save_' + role]['inputs']['filename_prefix'] = baseline_graph['save_' + role]['inputs']['filename_prefix']
        require(restored == baseline_graph and row['seed'] == row['baseline_seed'] ==
                graph['129']['inputs']['noise_seed'], 'actual_call_changed_outside_explicit_prompt_and_namespace')
        first = checked(graph_binding['first_frame'], project)
        require(first == folder / 'first_input.png' and result.get('first_frame_sha256') == sha(first) ==
                claim.get('first_frame_sha256'), 'actual_first_input_binding_changed')
        checked(row['first'], project)
        checked(row['baseline_first'], project)
        require(row['first']['sha256'] == row['first_frame']['sha256'], 'selected_first_not_actual_input')
        if run.name == 'R1':
            require(row['first'] == row['baseline_first'], 'R1_baseline_first_pixels_changed')
        require(graph['ref_scene']['class_type'] == 'LoadImage' and
                graph['ref_scene']['inputs']['image'] == graph_binding['input_name'],
                'actual_first_input_staging_changed')
        staged_first = (input_root / graph_binding['input_name']).resolve()
        scope = (output_root / graph_binding['scope']).resolve()
        require(staged_first.is_relative_to(input_root) and scope.is_relative_to(output_root),
                'native_staging_or_output_namespace_escaped')
        require(sha(staged_first) == sha(first), 'actual_first_input_staging_changed')
        require(set(result.get('files', {})) == {'video', 'audio', 'first', 'last'},
                'all_four_original_native_outputs_required')
        originals = {}
        for role in ('video', 'audio', 'first', 'last'):
            item = result['files'][role]
            local = checked(item, project)
            require(local.is_relative_to(folder / 'artifacts') and local.stat().st_size > 0,
                    'saved_original_outside_new_segment')
            source = Path(item['source_path']).resolve()
            require(graph['save_' + role]['inputs']['filename_prefix'] == graph_binding['scope'] + '/' + role,
                    'actual_save_node_output_prefix_changed')
            require(source.parent == scope and
                    source.is_file() and source.stat().st_size > 0 and sha(source) == item['sha256'],
                    'native_original_SHA_or_scope_changed')
            key = 'audio' if role == 'audio' else 'images'
            entries = history.get('outputs', {}).get('save_' + role, {}).get(key, [])
            require(len(entries) == 1 and entries[0].get('type') == 'output' and
                    (output_root / entries[0].get('subfolder', '') / entries[0]['filename']).resolve() == source,
                    'native_history_save_node_source_changed')
            originals[role] = dict(local=bind(local), native_original=bind(source))
        values.append(dict(id=sid, native_id=pid, folder=folder, result=result,
                           result_binding=bind(folder / 'RESULT.json'), originals=originals,
                           first_input=bind(first), actual_prompt=row['prompt'],
                           baseline_request=row['baseline_request'], baseline_first=row['baseline_first'],
                           expected_quotes=expected, actual_seed=graph['129']['inputs']['noise_seed'],
                           request=bind(folder / 'REQUEST.json'), history=bind(folder / 'HISTORY.json')))
    native_ids = [r['native_id'] for r in values]
    require(len(set(native_ids)) == 4 and len({r['originals']['video']['local']['sha256'] for r in values}) == 4,
            'four_unique_new_native_videos_required')
    final = read(run / 'FINAL_RESULT.json')
    native_results = [r['result_binding'] for r in values]
    require(final.get('schema') == SCHEMA and final.get('round') == run.name and
            final.get('production_approved') is False and final.get('publication') is False and
            final.get('native_ids') == native_ids and final.get('native_results') == native_results and
            final.get('assembly_inputs_sha256') == digest(dict(plan=plan_binding, native_results=native_results)),
            'final_assembly_original_inputs_changed')
    movie = checked(final['file'], project)
    require(movie == run / ('BASELINE_' + run.name + '_736x1312.mp4'), 'new_round_final_file_required')
    if run.name == 'R2':
        require(isinstance(plan.get('r1_overall_review'), dict) and isinstance(plan.get('round_spec'), dict),
                'R2_requires_actual_completed_R1_overall_review')
        review_path = checked(plan['r1_overall_review'], project)
        require(review_path == run.parent / 'R1/ROOT_OVERALL_VIDEO_REVIEW.json', 'actual_R1_review_path_required')
        review, r1_final = read(review_path), read(run.parent / 'R1/FINAL_RESULT.json')
        require(review.get('schema') == 'h3_baseline_overall_review/v38' and
                review.get('review_completed_by') == 'root_agent' and
                review.get('overall_video_review_completed') is True and review.get('allow_prepare_r2') is True and
                review.get('final_result') == bind(run.parent / 'R1/FINAL_RESULT.json') and
                review.get('reviewed_video') == r1_final['file'], 'R2_requires_actual_completed_R1_overall_review')
        checked(r1_final['file'], project)
        require(not set(native_ids).intersection(r1_final.get('native_ids', [])),
                'R2_cannot_reuse_original_R1_native_IDs')
        choice_path = checked(plan['round_spec'], project)
        require(choice_path == run / 'ROUND_SPEC.json', 'R2_explicit_spec_path_changed')
        choice = read(choice_path)
        require(choice.get('schema') == 'h3_baseline_round_spec/v38' and choice.get('round') == 'R2' and
                choice.get('r1_overall_review') == plan['r1_overall_review'] and
                [r.get('id') for r in choice.get('segments', [])] == list(IDS), 'R2_review_bound_choices_changed')
        for row, picked in zip(rows, choice['segments']):
            require(row['first'] == picked['first'] and
                    checked(picked['prompt'], project).read_bytes() == checked(row['prompt'], project).read_bytes(),
                    'R2_actual_prompt_or_first_not_reviewed_choice')
    return dict(run=run, plan=plan, plan_binding=plan_binding, values=values,
                final=final, final_binding=bind(run / 'FINAL_RESULT.json'), movie=movie)


def indices(start, end, *, max_index=1447, stride=3):
    return list(range(max(0, round(start * 24)), min(max_index, round(end * 24)) + 1, stride))


def sample_plan():
    return dict(timeline=list(range(0, 61 * 24, 24)) + [1447],
                dense=[dict(label=f'ACTUAL global {a}-{b}s', start=a, end=b,
                            indices=indices(a, b))
                       for a, b in ((0, 3), (26, 28), (29, 31), (44, 46), (49, 51))],
                joins=[dict(boundary_frame=n, indices=list(range(n - 12, n + 14, 3)) + [n, n + 1])
                       for n in (361, 723, 1085)])


def extract_batch(video, frame_indices, directory):
    """One CPU decode for missing frames; no original media is edited."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    wanted = sorted(set(frame_indices))
    require(all(type(i) is int and i >= 0 for i in wanted), 'nonnegative_frame_indices_required')
    missing = [i for i in wanted if not (directory / f'actual_{i:04d}.png').exists()]
    if missing:
        batch = directory / ('BATCH_' + uuid.uuid4().hex)
        batch.mkdir()
        expr = '+'.join(f'eq(n\\,{i})' for i in missing)
        args = ['ffmpeg', '-nostdin', '-v', 'error', '-hwaccel', 'none', '-threads', '2',
                '-i', str(video), '-vf', 'select=' + expr, '-fps_mode', 'vfr',
                '-frames:v', str(len(missing)), str(batch / 'frame_%06d.png')]
        raw = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=600)
        (batch / 'ffmpeg.stderr.log').write_text(raw.stderr, encoding='utf-8')
        require(raw.returncode == 0, 'CPU_frame_extract_failed')
        outputs = sorted(batch.glob('frame_*.png'))
        require(len(outputs) == len(missing), 'CPU_frame_extract_count_changed')
        for frame, output in zip(missing, outputs):
            with Image.open(output) as image:
                image.verify()
            target = directory / f'actual_{frame:04d}.png'
            require(not target.exists(), 'CPU_frame_concurrent_writer')
            output.rename(target)
    return {i: dict(**bind(directory / f'actual_{i:04d}.png'), frame_index=i, seconds=i / 24)
            for i in wanted}


def make_board(items, path, *, columns=4, prefix='ACTUAL'):
    return board([card(r['path'], f'{prefix} n={r["frame_index"]} t={r["seconds"]:.3f}s') for r in items],
                 path, columns)


def first_comparison(first, decoded, path):
    result = board([card(first['path'], 'ACTUAL model first input PNG'),
                    card(decoded['path'], 'ACTUAL decoded first frame')], path, 2)
    with Image.open(first['path']) as a, Image.open(decoded['path']) as b:
        a, b = a.convert('RGB'), b.convert('RGB')
        require(a.size == b.size, 'input_vs_first_geometry_changed')
        mae = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
    return dict(contact=result, mean_absolute_pixel_difference=mae,
                semantic_or_identity_pass=None)


def cpu_asr(project, value, folder, enabled):
    if not enabled:
        return dict(status='not_requested', normalized_text=None, quote_intervals=[])
    folder.mkdir(parents=True, exist_ok=True)
    wav, output, receipt = folder / 'audio_16k.wav', folder / 'ASR.json', folder / 'ASR_BINDING.json'
    video = value['originals']['video']['local']
    source_binding = dict(video=video, transcriber=bind(Path(project) / 'scripts/transcribe_video_local.py'),
                          mode='local_CPU_offline_no_punctuation')
    if receipt.exists():
        prior = read(receipt)
        require(prior['source'] == source_binding and bind(output) == prior['asr'] and bind(wav) == prior['wav'],
                'existing_ASR_binding_changed')
    else:
        if not wav.exists():
            command(['ffmpeg', '-nostdin', '-v', 'error', '-hwaccel', 'none', '-i', video['path'],
                     '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)])
        if not output.exists():
            transcribe(project, wav, output, folder)
        freeze(receipt, dict(source=source_binding, wav=bind(wav), asr=bind(output)))
    text, intervals = asr_intervals(output, value['expected_quotes'])
    return dict(status='CPU_ASR_complete', source=source_binding, raw=bind(output),
                normalized_text=text, expected_quotes=value['expected_quotes'], quote_intervals=intervals,
                limits=LIMITS)


def inspect_clock(video, frames, *, final=False):
    timing, metadata = clock(video, frames, final=final)
    audio = next(s for s in metadata['streams'] if s['codec_type'] == 'audio')
    duration = Fraction(audio['duration_ts']) * Fraction(audio['time_base'])
    delta = duration - Fraction(frames, 24)
    require(abs(delta) <= (Fraction(1, 48000) if final else Fraction(1, 4)),
            'actual_audio_end_skew_exceeds_source_or_final_policy')
    return dict(clock=timing, audio_seconds=float(duration), audio_end_skew_seconds=float(delta)), metadata


def qa(run, *, asr=False, project=PROJECT):
    value = validate(run, project=project)
    run = value['run']
    folder = run / 'qc_v38' / value['final']['file']['sha256']
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(plan=value['plan_binding'], final_result=value['final_binding'],
                   final_video=value['final']['file'], originals=[r['result_binding'] for r in value['values']],
                   asr_requested=asr)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'FINAL_QA.json'
    if manifest.exists():
        old = read(manifest)
        for item in old['artifacts']:
            checked(item, project)
        require(old['binding'] == binding, 'existing_QA_input_changed')
        return dict(status='already_complete', manifest=bind(manifest), file=value['final']['file'])
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    source_copy = attempt / 'qa_source.py'
    source_copy.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source_code=bind(source_copy), started_at=time.time()))
    try:
        segments, artifacts = [], []
        for vi, row in enumerate(value['values']):
            sf = folder / row['id'] / row['native_id']
            sf.mkdir(parents=True, exist_ok=True)
            geometry, metadata = inspect_clock(row['originals']['video']['local']['path'], 362)
            artifacts.append(freeze(sf / 'PROBE.json', metadata))
            speech = cpu_asr(project, row, sf, asr)
            wanted = {0, 36, 108, 180, 252, 324}
            intervals = []
            for item in speech['quote_intervals']:
                q = dict(item, native_id=row['native_id'], video_sha256=row['originals']['video']['local']['sha256'],
                         intended_speaker_from_prompt_only=True, actual_acoustic_speaker=None)
                if item['exactly_detected']:
                    a = max(0, min(361, round(item['start_ms'] * 24 / 1000)))
                    b = max(a, min(361, round(item['end_ms'] * 24 / 1000)))
                    q['indices'] = sorted({round(a + (b - a) * k / 4) for k in range(5)})
                    q['global_start_seconds'] = vi * 362 / 24 + item['start_ms'] / 1000
                    q['global_end_seconds'] = vi * 362 / 24 + item['end_ms'] / 1000
                    wanted.update(q['indices'])
                    if (row['id'], item['quote_index']) in {('S01', 1), ('S02', 0), ('S03', 0), ('S03', 1), ('S04', 0), ('S04', 1)}:
                        q['dense_indices'] = list(range(a, b + 1, 3))
                        wanted.update(q['dense_indices'])
                intervals.append(q)
            frames = extract_batch(row['originals']['video']['local']['path'], wanted, sf / 'frames')
            artifacts.extend({k: v for k, v in r.items() if k in ('path', 'sha256')} for r in frames.values())
            base = [frames[i] for i in (0, 36, 108, 180, 252, 324)]
            contact = board([card(r['path'], f'ACTUAL n={r["frame_index"]} t={r["seconds"]:.3f}s') for r in base] +
                            [card(row['originals']['last']['local']['path'], 'ACTUAL native last PNG')], sf / 'CONTACT.jpg', 4)
            artifacts.append(contact)
            comparison = first_comparison(row['first_input'], frames[0], sf / 'INPUT_VS_ACTUAL_FIRST.jpg')
            artifacts.append(comparison['contact'])
            for qi, item in enumerate(intervals):
                if item.get('indices'):
                    item['contact'] = make_board([frames[i] for i in item['indices']], sf / f'QUOTE_{qi:02d}.jpg', columns=5)
                    artifacts.append(item['contact'])
                if item.get('dense_indices'):
                    item['dense_contact'] = make_board([frames[i] for i in item['dense_indices']], sf / f'QUOTE_{qi:02d}_DENSE.jpg', columns=6)
                    artifacts.append(item['dense_contact'])
            segments.append(dict(segment=row['id'], native_id=row['native_id'], video=row['originals']['video']['local'],
                                 originals=row['originals'], actual_seed=row['actual_seed'], clock=geometry,
                                 contact=contact, first_input_comparison=comparison, asr=speech,
                                 quote_intervals=intervals, root_visual_review=None))
        geometry, metadata = inspect_clock(value['movie'], 1448, final=True)
        artifacts.append(freeze(folder / 'FINAL_PROBE.json', metadata))
        samples = sample_plan()
        wanted = set(samples['timeline'])
        for r in samples['dense'] + samples['joins']:
            wanted.update(r['indices'])
        frames = extract_batch(value['movie'], wanted, folder / 'final_frames')
        artifacts.extend({k: v for k, v in r.items() if k in ('path', 'sha256')} for r in frames.values())
        timeline = []
        for page in range(3):
            subset = samples['timeline'][page * 21:(page + 1) * 21]
            contact = make_board([frames[i] for i in subset], folder / f'TIMELINE_{page+1:02d}.jpg', columns=5)
            timeline.append(dict(indices=subset, contact=contact))
            artifacts.append(contact)
        for i, region in enumerate(samples['dense']):
            region['contact'] = make_board([frames[j] for j in region['indices']], folder / f'DENSE_{i:02d}.jpg', columns=6)
            artifacts.append(region['contact'])
        for i, join in enumerate(samples['joins']):
            join['indices'] = sorted(set(join['indices']))
            join['contact'] = make_board([frames[j] for j in join['indices']], folder / f'JOIN_{i+1:02d}.jpg', columns=5)
            artifacts.append(join['contact'])
        validate(run, project=project)
        report = dict(schema='h3_baseline_two_rounds_CPU_QA/v38', binding=binding,
                      source_code=bind(source_copy),
                      final_video=value['final']['file'], native_ids=value['final']['native_ids'], final_clock=geometry,
                      segments=segments, timeline=timeline, dense=samples['dense'], joins=samples['joins'],
                      artifacts=list({r['path']: r for r in artifacts}.values()), limits=LIMITS,
                      root_overall_video_review=None, production_approved=False)
        freeze(manifest, report)
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), finished_at=time.time()))
        return dict(status='CPU_QA_complete', manifest=bind(manifest), file=value['final']['file'],
                    timeline=[r['contact'] for r in timeline], dense=[r['contact'] for r in samples['dense']],
                    joins=[r['contact'] for r in samples['joins']], production_approved=False)
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc(),
                                          no_media_retry=True, failed_at=time.time()))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--asr', action='store_true')
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    args = parser.parse_args(argv)
    try:
        result = qa(args.run, asr=args.asr, project=args.project_root)
    except Exception as error:
        print(json.dumps(dict(status='CPU_QA_failed', error=type(error).__name__, message=str(error),
                              no_media_retry=True), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
