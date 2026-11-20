"""One finite, local CPU evidence pass for the authorized S02 prompt probe."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import traceback
import uuid

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from qa_h3_baseline_two_rounds_v38 import (
    PROJECT, LIMITS, bind, checked, digest, freeze, read, require, sha,
    quotes, extract_batch, make_board, first_comparison, cpu_asr, inspect_clock,
)

ROOT_REL = Path('data/video_generation/h3_s02_prompt_probe_20261110_v1')
SCHEMA = 'h3_s02_prompt_probe/v39'


def validate(run, project=PROJECT):
    run = Path(run).resolve()
    require(run == Path(project).resolve() / ROOT_REL, 'explicit_single_v39_probe_required')
    plan = read(run / 'PLAN.json')
    require(plan.get('schema') == SCHEMA and plan.get('max_native_video_submissions') == 1 and
            plan.get('image_generation_calls') == 0 and plan.get('publication') is False,
            'single_new_native_probe_PLAN_required')
    row, folder = plan['shot'], run / 'shots/S02'
    require(row.get('id') == 'S02', 'one_S02_required')
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    graph = read(folder / 'workflow_api.json')
    pid = state.get('prompt_id')
    require(state.get('status') == 'technical_saved' and state.get('id') == 'S02' and
            state.get('plan_sha256') == digest(plan) and pid != plan['source_native_id'],
            'new_saved_native_ID_required')
    require(read(folder / 'GRAPH_BINDING.json') == row and
            pid == read(folder / 'RESPONSE.json').get('prompt_id') == result.get('prompt_id') and
            result.get('schema') == 'visual_h3_handoff/v3' and result.get('shot_id') == 'S02' and
            result.get('technical_status') == 'technical_saved', 'original_RESULT_identity_changed')
    require(read(folder / 'REQUEST.json').get('prompt') == graph and
            digest(graph) == row['graph_sha256'] == result['graph_sha256'] ==
            read(folder / 'CLAIM.json').get('graph_sha256'), 'actual_POST_graph_binding_changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    hp, hs = history.get('prompt', []), history.get('status', {})
    require(len(hp) > 2 and hp[1] == pid and hp[2] == graph and hs.get('completed') is True and
            hs.get('status_str') == 'success', 'original_native_success_history_changed')
    prompt = checked(plan['prompt'], project).read_bytes().decode('utf-8')
    source_graph = read(checked(plan['source_request'], project))['prompt']
    checked(plan['source_plan'], project)
    source_result = read(checked(plan['source_result'], project))
    require(source_result.get('prompt_id') == plan['source_native_id'] and
            source_result.get('technical_status') == 'technical_saved' and
            source_result.get('graph_sha256') == digest(source_graph) and
            source_result.get('first_frame_sha256') == row['source_first']['sha256'],
            'original_source_receipt_binding_changed')
    require(row['source_prompt'] == plan['prompt'] and row['source_request'] == plan['source_request'] and
            graph['condition']['inputs']['prompt'] == prompt and
            len(quotes(prompt)) == 2 and quotes(prompt) == quotes(source_graph['condition']['inputs']['prompt']),
            'actual_prompt_or_two_original_quotes_changed')
    restored = deepcopy(graph)
    restored['condition']['inputs']['prompt'] = source_graph['condition']['inputs']['prompt']
    restored['ref_scene']['inputs']['image'] = source_graph['ref_scene']['inputs']['image']
    for role in ('video', 'audio', 'first', 'last'):
        restored['save_' + role]['inputs']['filename_prefix'] = source_graph['save_' + role]['inputs']['filename_prefix']
    require(restored == source_graph and graph['129']['inputs']['noise_seed'] == row['seed'],
            'native_call_changed_outside_prompt_and_namespace')
    first = checked(row['first_frame'], project)
    checked(row['source_first'], project)
    require(first == folder / 'first_input.png' and sha(first) == row['source_first']['sha256'] ==
            result['first_frame_sha256'] == read(folder / 'CLAIM.json')['first_frame_sha256'],
            'same_original_first_pixels_required')
    input_root, output_root = [Path(plan['config'][k]).resolve() for k in ('input_root', 'output_root')]
    staged, scope = (input_root / row['input_name']).resolve(), (output_root / row['scope']).resolve()
    require(input_root.is_relative_to(Path(project).resolve()) and output_root.is_relative_to(Path(project).resolve()) and
            staged.is_relative_to(input_root) and scope.is_relative_to(output_root), 'local_namespaces_required')
    require(graph['ref_scene']['inputs']['image'] == row['input_name'] and sha(staged) == sha(first),
            'actual_staged_first_pixels_changed')
    originals = {}
    require(set(result['files']) == {'video', 'audio', 'first', 'last'}, 'four_native_originals_required')
    for role, item in result['files'].items():
        local, source = checked(item, project), Path(item['source_path']).resolve()
        require(local.is_relative_to(folder / 'artifacts') and local.stat().st_size > 0 and source.parent == scope and
                source.stat().st_size > 0 and sha(source) == item['sha256'], 'original_output_SHA_or_scope_changed')
        entries = history.get('outputs', {}).get('save_' + role, {}).get('audio' if role == 'audio' else 'images', [])
        require(len(entries) == 1 and entries[0].get('type') == 'output' and
                (output_root / entries[0].get('subfolder', '') / entries[0]['filename']).resolve() == source and
                graph['save_' + role]['inputs']['filename_prefix'] == row['scope'] + '/' + role,
                'native_save_node_source_changed')
        originals[role] = dict(local=bind(local), native_original=bind(source))
    final = read(run / 'FINAL_RESULT.json')
    require(final.get('schema') == SCHEMA and final.get('native_id') == pid and
            final.get('native_result') == bind(folder / 'RESULT.json') and final.get('files') == result['files'] and
            final.get('file') == originals['video']['local'] and final.get('postprocessing') == [] and
            final.get('publication') is False, 'single_native_final_binding_changed')
    return dict(run=run, plan=plan, native_id=pid, final=final, originals=originals,
                first_input=bind(first), expected_quotes=quotes(prompt), actual_seed=row['seed'],
                binding=dict(plan=bind(run / 'PLAN.json'), result=bind(folder / 'RESULT.json'),
                             request=bind(folder / 'REQUEST.json'), history=bind(folder / 'HISTORY.json'),
                             final=bind(run / 'FINAL_RESULT.json'), video=originals['video']['local']))


def sample_plan():
    return dict(half_second=list(range(0, 361, 12)) + [361],
                subtitle_window=list(range(0, 241, 3)), inner_voice_window=list(range(48, 169, 3)))


def qa(run, *, asr=False, project=PROJECT):
    value = validate(run, project)
    folder = value['run'] / 'qc_v39' / value['native_id']
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(**value['binding'], asr_requested=asr)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'QA.json'
    if manifest.exists():
        old = read(manifest)
        require(old['binding'] == binding, 'existing_CPU_QA_inputs_changed')
        for item in old['artifacts']:
            checked(item, project)
        return dict(status='already_complete', manifest=bind(manifest))
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    source = attempt / 'qa_source.py'
    source.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source=bind(source), started_at=time.time()))
    try:
        geometry, metadata = inspect_clock(value['originals']['video']['local']['path'], 362)
        artifacts = [freeze(folder / 'PROBE.json', metadata)]
        speech = cpu_asr(project, value, folder / 'asr', asr)
        samples = sample_plan()
        wanted = set().union(*[set(rows) for rows in samples.values()])
        intervals = []
        for item in speech['quote_intervals']:
            item = dict(item, actual_acoustic_speaker=None)
            if item['exactly_detected']:
                a = max(0, min(361, round(item['start_ms'] * 24 / 1000)))
                b = max(a, min(361, round(item['end_ms'] * 24 / 1000)))
                item['indices'] = sorted({round(a + (b - a) * k / 4) for k in range(5)})
                wanted.update(item['indices'])
            intervals.append(item)
        frames = extract_batch(value['originals']['video']['local']['path'], wanted, folder / 'frames')
        artifacts.extend({k: r[k] for k in ('path', 'sha256')} for r in frames.values())
        pages = {}
        for name, indices in samples.items():
            size, cols = (8, 4) if name == 'half_second' else (21, 5)
            pages[name] = []
            for start in range(0, len(indices), size):
                selected = indices[start:start + size]
                contact = make_board([frames[i] for i in selected], folder / f'{name}_{start//size+1:02d}.jpg', columns=cols)
                pages[name].append(dict(indices=selected, contact=contact))
                artifacts.append(contact)
        comparison = first_comparison(value['first_input'], frames[0], folder / 'INPUT_VS_ACTUAL_FIRST.jpg')
        artifacts.append(comparison['contact'])
        for i, item in enumerate(intervals):
            if item.get('indices'):
                item['contact'] = make_board([frames[n] for n in item['indices']], folder / f'QUOTE_{i+1:02d}.jpg', columns=5)
                artifacts.append(item['contact'])
        validate(run, project)
        report = dict(schema='h3_s02_prompt_probe_CPU_QA/v39', binding=binding, native_id=value['native_id'],
                      video=value['originals']['video']['local'], originals=value['originals'], clock=geometry,
                      actual_seed=value['actual_seed'], source_code=bind(source), half_second=pages['half_second'],
                      subtitle_window=pages['subtitle_window'], inner_voice_window=pages['inner_voice_window'],
                      first_comparison=comparison, asr=speech, quote_intervals=intervals,
                      native_last=value['originals']['last']['local'], root_actual_visual_review=None,
                      artifacts=artifacts, limits=LIMITS, production_approved=False)
        freeze(manifest, report)
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), finished_at=time.time()))
        return dict(status='single_CPU_QA_complete', manifest=bind(manifest), video=report['video'],
                    half_second=[r['contact'] for r in report['half_second']],
                    subtitle_window=[r['contact'] for r in report['subtitle_window']],
                    inner_voice_window=[r['contact'] for r in report['inner_voice_window']], production_approved=False)
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error),
                                          traceback=traceback.format_exc(), no_media_retry=True))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=PROJECT / ROOT_REL)
    parser.add_argument('--asr', action='store_true')
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    args = parser.parse_args(argv)
    try:
        result = qa(args.run, asr=args.asr, project=args.project_root)
    except Exception as error:
        print(json.dumps(dict(status='single_CPU_QA_failed', type=type(error).__name__, message=str(error), no_media_retry=True)))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
