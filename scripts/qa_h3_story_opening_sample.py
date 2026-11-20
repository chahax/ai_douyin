"""Finite CPU evidence for a saved source-driven S02 opening sample.

No service queries, media submissions, automatic retries or content approval.
The optional ASR uses the existing offline CPU transcriber.
"""
import argparse
from pathlib import Path
import sys
import time
import traceback
import uuid

SCRIPTS = Path(__file__).resolve().parent
for item in (SCRIPTS, SCRIPTS.parent):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))
from qa_h3_baseline_two_rounds_v38 import (
    PROJECT, LIMITS, read, bind, checked, digest, freeze, require, sha, quotes,
    inspect_clock, extract_batch, make_board, first_comparison, cpu_asr,
)
from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_h3_handoff_v3 as native
from src.content_factory import visual_opening_frame as opening

DEFAULT_RUN = PROJECT / 'data/video_generation/h3_story_opening_s02_20261110_v1'
SID = 'S02'


def verified_image_origin(receipt):
    if receipt.get('kind') == 'derived_opening_crop/v1':
        return (receipt.get('exact_pixels_verified') is True and receipt.get('native_output') is False
                and receipt.get('parent_generation_proof', {}).get('actual_generation_inputs_verified') is True)
    return receipt.get('actual_generation_inputs_verified') is True


def validate(run, project=PROJECT):
    """Bind saved pixels and original POST/history back to the first-shot source."""
    project, run = Path(project).resolve(), Path(run).resolve()
    require(run.parent == project / 'data/video_generation', 'new_project_media_run_required')
    h3 = run / 'visual_h3_v3/opening_S02'
    folder = h3 / 'shots' / SID
    plan = read(h3 / 'PLAN.json')
    require(plan.get('schema') == native.SCHEMA and plan.get('publication') is False and
            plan.get('old_batch_resume') is False and len(plan.get('shots', [])) == 1,
            'one_new_continuity_native_shot_required')
    row = plan['shots'][0]
    require(row.get('id') == SID and plan.get('upstream_contract') == core.SCHEMA,
            'source_driven_S02_adapter_required')
    source = bind(run / 'VIDEO_SOURCE_CASE.json')
    require(plan.get('continuity_source_plan') == source and
            plan['config'].get('continuity_input_plan') == source,
            'actual_VIDEO_SOURCE_CASE_binding_changed')
    entries = core._entries(source)
    require(len(entries) == 1 and entries[0]['shot_id'] == SID and
            entries[0].get('first_frame_policy') == opening.POLICY,
            'first_camera_beat_policy_required')
    entry = entries[0]
    observed = core.evaluate(entry)
    first = checked(row['first_frame'], project)
    require(observed['status'] == 'ready' and observed['first_image'] == bind(first) and
            verified_image_origin(observed.get('generation_receipt', {})) and
            bind(first)['sha256'] != entry['actual_first_image']['sha256'],
            'real_new_opening_first_image_and_receipt_required')
    proof = row.get('continuity_input')
    require(proof == native._continuity_proof(dict(observed, plan=source)),
            'native_first_source_proof_changed')
    graph = read(folder / 'workflow_api.json')
    cfg = plan['config']
    native._validate_graph(graph, row['scope'], row['input_name'])
    c = graph['condition']['inputs']
    require((c['width'], c['height'], c['length'], graph['124']['inputs']['steps'],
             graph['130']['inputs']['fps']) == (736, 1312, 362, 12, 24),
            'saved_native_profile_changed')
    require(c['prompt'] == observed['compiled_prompt'] and len(quotes(c['prompt'])) == 2 and
            observed['compiled_prompt_utf8_sha256'] == core.sha(c['prompt']),
            'actual_compiled_prompt_or_two_original_quotes_changed')
    require(row.get('timing', {}).get('requested_seconds') == entry['duration'] == 15 and
            row['timing'].get('native_frames') == 362 and
            row['timing'].get('automatic_audio_cut') is False, 'source_native_clock_changed')
    require(digest(graph) == row['graph_sha256'] and read(folder / 'REQUEST.json')['prompt'] == graph,
            'actual_POST_graph_changed')
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    pid = state.get('prompt_id')
    require(state.get('status') == 'technical_saved' and state.get('id') == SID and
            state.get('plan_sha256') == digest(plan) and pid and
            result.get('prompt_id') == read(folder / 'RESPONSE.json').get('prompt_id') == pid,
            'saved_original_native_ID_required')
    require(result.get('schema') == native.SCHEMA and result.get('shot_id') == SID and
            result.get('technical_status') == 'technical_saved' and
            result.get('graph_sha256') == row['graph_sha256'] and
            result.get('first_frame_sha256') == row['first_frame']['sha256'] and
            result.get('continuity_input') == proof and result.get('publication') is False and
            result.get('production_approved') is False and result.get('timing') == row['timing'],
            'original_RESULT_binding_changed')
    claim = read(folder / 'CLAIM.json')
    require(claim.get('graph_sha256') == row['graph_sha256'] and
            claim.get('first_frame_sha256') == row['first_frame']['sha256'], 'native_CLAIM_changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    hp, hs = history.get('prompt', []), history.get('status', {})
    require(len(hp) > 2 and hp[1] == pid and
            native.native_graph_equivalence(graph, hp[2]) is not None and
            hs.get('completed') is True and hs.get('status_str') == 'success',
            'original_success_history_changed')
    input_root, output_root = [Path(cfg[k]).resolve() for k in ('input_root', 'output_root')]
    staged = (input_root / row['input_name']).resolve()
    output_scope = (output_root / row['scope']).resolve()
    require(input_root.is_relative_to(project) and output_root.is_relative_to(project) and
            staged.is_relative_to(input_root) and output_scope.is_relative_to(output_root) and
            sha(staged) == row['first_frame']['sha256'], 'actual_staged_first_image_changed')
    originals = {}
    require(set(result['files']) == {'video', 'audio', 'first', 'last'}, 'four_native_outputs_required')
    for role, item in result['files'].items():
        local, origin = checked(item, project), Path(item['source_path']).resolve()
        require(local.is_relative_to(folder / 'artifacts') and origin.parent == output_scope and
                origin.is_file() and sha(origin) == item['sha256'], 'native_original_pixels_changed')
        rows = history.get('outputs', {}).get('save_' + role, {}).get('audio' if role == 'audio' else 'images', [])
        require(len(rows) == 1 and rows[0].get('type') == 'output' and
                (output_root / rows[0].get('subfolder', '') / rows[0]['filename']).resolve() == origin,
                'native_save_output_mapping_changed')
        originals[role] = dict(local=bind(local), native_original=bind(origin))
    final = read(run / 'FINAL_RESULT.json')
    require(final.get('native_result') == bind(folder / 'RESULT.json') and
            final.get('file') == originals['video']['local'] and final.get('prompt_id') == pid and
            final.get('postprocessing') == [], 'saved_final_not_original_native_video')
    return dict(run=run, native_id=pid, originals=originals, first_input=bind(first),
                expected_quotes=quotes(c['prompt']), actual_seed=graph['129']['inputs']['noise_seed'],
                opening_contract=opening.contract(entry),
                binding=dict(plan=bind(h3 / 'PLAN.json'), source=source,
                             request=bind(folder / 'REQUEST.json'), result=bind(folder / 'RESULT.json'),
                             history=bind(folder / 'HISTORY.json'), final=bind(run / 'FINAL_RESULT.json'),
                             video=originals['video']['local']))


def sample_plan():
    return dict(half_second=list(range(0, 361, 12)) + [361],
                opening_dense=list(range(0, 49, 3)),
                inner_voice=list(range(0, 169, 4)))


def qa(run=DEFAULT_RUN, *, asr=False, project=PROJECT):
    value = validate(run, project)
    folder = value['run'] / 'qc_opening' / value['native_id'] / ('with_asr' if asr else 'without_asr')
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(**value['binding'], asr_requested=asr)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'QA.json'
    if manifest.exists():
        prior = read(manifest)
        require(prior['binding'] == binding, 'existing_CPU_evidence_changed')
        for item in prior['artifacts']:
            checked(item, project)
        return dict(status='already_complete', manifest=bind(manifest))
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    code = attempt / 'qa_source.py'
    code.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source=bind(code), started_at=time.time()))
    try:
        geometry, metadata = inspect_clock(value['originals']['video']['local']['path'], 362)
        artifacts = [freeze(folder / 'PROBE.json', metadata)]
        speech = cpu_asr(project, value, folder / 'asr', asr)
        samples = sample_plan()
        wanted = set().union(*map(set, samples.values()))
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
        artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
        pages = {}
        for name, indices in samples.items():
            size, columns = (8, 4) if name == 'half_second' else (21, 5)
            pages[name] = []
            for offset in range(0, len(indices), size):
                selected = indices[offset:offset + size]
                board = make_board([frames[i] for i in selected], folder / f'{name}_{offset//size+1:02d}.jpg', columns=columns)
                pages[name].append(dict(indices=selected, contact=board))
                artifacts.append(board)
        comparison = first_comparison(value['first_input'], frames[0], folder / 'INPUT_VS_ACTUAL_FIRST.jpg')
        artifacts.append(comparison['contact'])
        for index, item in enumerate(intervals):
            if item.get('indices'):
                item['contact'] = make_board([frames[i] for i in item['indices']], folder / f'QUOTE_{index+1:02d}.jpg', columns=5)
                artifacts.append(item['contact'])
        validate(run, project)
        report = dict(schema='story_opening_sample_CPU_QA/v1', binding=binding, native_id=value['native_id'],
                      video=value['originals']['video']['local'], originals=value['originals'], clock=geometry,
                      source_code=bind(code), actual_seed=value['actual_seed'], opening_contract=value['opening_contract'],
                      samples=pages, first_comparison=comparison, asr=speech, quote_intervals=intervals,
                      native_last=value['originals']['last']['local'], artifacts=artifacts,
                      root_actual_visual_review=None, limits=LIMITS, production_approved=False)
        freeze(manifest, report)
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), finished_at=time.time()))
        return dict(status='CPU_evidence_complete', manifest=bind(manifest), video=report['video'],
                    sample_boards={k: [p['contact'] for p in rows] for k, rows in pages.items()},
                    production_approved=False)
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error),
                                          traceback=traceback.format_exc(), no_media_retry=True))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--asr', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = qa(args.run, asr=args.asr)
    except Exception as error:
        print(__import__('json').dumps(dict(status='CPU_evidence_failed', type=type(error).__name__,
                                          message=str(error), no_media_retry=True), ensure_ascii=False))
        return 2
    print(__import__('json').dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
