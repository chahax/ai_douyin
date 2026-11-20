"""Finite CPU evidence for a four-segment source-driven minute.

Reads saved native originals only.  It never contacts a service, submits media,
changes a user's accepted segment, retries a generation or approves content.
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
from qa_h3_story_opening_sample import verified_image_origin
from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_h3_handoff_v3 as native
from src.content_factory import visual_opening_frame as opening

IDS = ('S01', 'S02', 'S03', 'S04')
QUOTE_COUNTS = (3, 2, 2, 3)
SCHEMA = 'h3_story_opening_minute/v1'
DIAGNOSTIC_SCHEMA = 'h3_story_opening_diagnostic/v1'
DIAGNOSTIC_CONTRACT = 'source_bound_user_review_diagnostic/v1'
ACCEPTED_ID = 'ad632988-544f-4074-91c5-76ccfff0f88e'
ACCEPTED_SHA = '333c204265493be12503173e836094b6bfb06b85a316a32ac242b0d2ecdb12a5'
DEFAULT_RUN = PROJECT / 'data/video_generation/h3_story_opening_minute_20261111_v1'


def diagnostic_input(binding):
    """Local technical ancestry; never interpret a diagnostic choice as ready."""
    from run_h3_story_opening_diagnostic import validate_input
    return validate_input(binding)


def validate_native(native_run, sid, project=PROJECT):
    """Independent read of actual source, POST, history and saved pixels."""
    project, native_run = Path(project).resolve(), Path(native_run).resolve()
    require(native_run.is_relative_to(project / 'data/video_generation') and sid in IDS,
            'project_native_segment_required')
    folder = native_run / 'shots' / sid
    plan_path = native_run / 'PLAN.json'
    plan = read(plan_path)
    diagnostic = plan.get('schema') == DIAGNOSTIC_SCHEMA
    require(plan.get('schema') in (native.SCHEMA, DIAGNOSTIC_SCHEMA) and plan.get('publication') is False
            and (plan.get('old_batch_resume') is not True if diagnostic else plan.get('old_batch_resume') is False)
            and plan.get('upstream_contract') == (DIAGNOSTIC_CONTRACT if diagnostic else core.SCHEMA)
            and len(plan.get('shots', [])) == 1, 'single_source_driven_native_plan_required')
    row = plan['shots'][0]
    require(row.get('id') == sid, 'original_segment_order_changed')
    if diagnostic:
        require(sid != 'S02' and 'continuity_input' not in row,
                'diagnostic_must_not_forge_ready_continuity_proof')
        observed = diagnostic_input(plan['diagnostic_input'])
        source = observed['source_case']
        checked(source, project)
        entry, proof = observed['entry'], observed['proof']
        require(observed.get('quality_passed') is False and proof == row['diagnostic_input'],
                'diagnostic_quality_or_input_proof_changed')
        first = checked(row['first_frame'], project)
        require(observed.get('first_image') == bind(first)
                and verified_image_origin(observed.get('generation_receipt', {})),
                'diagnostic_selected_image_technical_receipt_changed')
        actual_source = core.evaluate(entry)
        require(actual_source == observed.get('source_evaluation') == plan.get('source_evaluation')
                and actual_source.get('status') == 'reanchor_required' and plan.get('source') == source
                and plan.get('quality_passed') is False and plan.get('visual_ready') is False
                and plan.get('production_approved') is False, 'diagnostic_source_evaluation_changed')
        for item in (plan['base_workflow'], plan['authority'], *plan['code']):
            checked(item, project)
        draft = core.compile_prompt(entry)
        require(draft['compiled_prompt'] == observed['compiled_prompt']
                and draft['compiled_prompt_utf8_sha256'] == observed['compiled_prompt_utf8_sha256'],
                'diagnostic_prompt_must_equal_original_source_compiler')
        override = read(checked(observed['override'], project))
        require(override.get('quality_passed') is False and override.get('decision') == 'generate_for_user_review'
                and override.get('source_case') == source and override.get('image') == bind(first),
                'diagnostic_choice_must_preserve_failed_quality')
        observation = read(checked(override['observation'], project))
        require(observation.get('quality_passed') is False and observation.get('actual_image') == bind(first),
                'diagnostic_actual_observation_changed')
        input_status = dict(contract=DIAGNOSTIC_CONTRACT, quality_passed=False,
                            source_evaluation=actual_source, override=observed['override'],
                            observation=override['observation'], diagnostic_input=proof)
    else:
        source = plan.get('continuity_source_plan')
        source_path = checked(source, project)
        require(plan['config'].get('continuity_input_plan') == source, 'native_source_binding_changed')
        entries = core._entries(bind(source_path))
        require(len(entries) == 1 and entries[0].get('shot_id') == sid
                and entries[0].get('first_frame_policy') == opening.POLICY,
                'first_camera_beat_source_policy_required')
        entry = entries[0]
        observed = core.evaluate(entry)
        first = checked(row['first_frame'], project)
        require(observed.get('status') == 'ready' and observed.get('first_image') == bind(first)
                and verified_image_origin(observed.get('generation_receipt', {})),
                'source_selected_first_image_receipt_changed')
        proof = native._continuity_proof(dict(observed, plan=source))
        require(row.get('continuity_input') == proof, 'native_source_proof_changed')
        input_status = dict(contract=core.SCHEMA, source_evaluation_status=observed['status'])
    require(entry.get('shot_id') == sid and entry.get('first_frame_policy') == opening.POLICY,
            'first_camera_beat_source_policy_required')
    graph = read(folder / 'workflow_api.json')
    native._validate_graph(graph, row['scope'], row['input_name'])
    c = graph['condition']['inputs']
    require((c['width'], c['height'], c['length'], graph['124']['inputs']['steps'],
             graph['130']['inputs']['fps']) == (736, 1312, 362, 12, 24), 'native_profile_changed')
    expected = quotes(c['prompt'])
    require(c['prompt'] == observed['compiled_prompt']
            and observed['compiled_prompt_utf8_sha256'] == core.sha(c['prompt'])
            and len(expected) == QUOTE_COUNTS[IDS.index(sid)], 'actual_source_prompt_or_quotes_changed')
    require(row.get('timing', {}).get('requested_seconds') == entry['duration'] == 15
            and row['timing'].get('native_frames') == 362
            and row['timing'].get('automatic_audio_cut') is False, 'native_timing_policy_changed')
    gh = digest(graph)
    require(gh == row['graph_sha256'] and read(folder / 'REQUEST.json').get('prompt') == graph,
            'actual_POST_graph_changed')
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    pid = state.get('prompt_id')
    require(state.get('status') == 'technical_saved' and state.get('id') == sid
            and state.get('plan_sha256') == digest(plan) and pid
            and result.get('prompt_id') == read(folder / 'RESPONSE.json').get('prompt_id') == pid,
            'saved_original_native_ID_required')
    require(result.get('schema') == native.SCHEMA and result.get('shot_id') == sid
            and result.get('technical_status') == 'technical_saved'
            and result.get('graph_sha256') == gh and result.get('first_frame_sha256') == sha(first)
            and (result.get('continuity_input') is None if diagnostic else result.get('continuity_input') == proof)
            and result.get('timing') == row['timing']
            and result.get('publication') is False and result.get('production_approved') is False,
            'saved_native_RESULT_binding_changed')
    claim = read(folder / 'CLAIM.json')
    require(claim.get('graph_sha256') == gh and claim.get('first_frame_sha256') == sha(first),
            'native_CLAIM_changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    hp, hs = history.get('prompt', []), history.get('status', {})
    require(len(hp) > 2 and hp[1] == pid and native.native_graph_equivalence(graph, hp[2]) is not None
            and hs.get('completed') is True and hs.get('status_str') == 'success',
            'original_success_history_changed')
    cfg = plan['config']
    input_root, output_root = [Path(cfg[k]).resolve() for k in ('input_root', 'output_root')]
    staged, scope = (input_root / row['input_name']).resolve(), (output_root / row['scope']).resolve()
    require(input_root.is_relative_to(project) and output_root.is_relative_to(project)
            and staged.is_relative_to(input_root) and scope.is_relative_to(output_root)
            and sha(staged) == sha(first), 'actual_staged_first_image_changed')
    require(set(result.get('files', {})) == {'video', 'audio', 'first', 'last'},
            'four_original_native_outputs_required')
    originals = {}
    for role, item in result['files'].items():
        local, origin = checked(item, project), Path(item['source_path']).resolve()
        require(local.is_relative_to(folder / 'artifacts') and local.stat().st_size > 0
                and origin.parent == scope and origin.is_file() and sha(origin) == item['sha256'],
                'native_original_pixels_changed')
        saved = history.get('outputs', {}).get('save_' + role, {}).get('audio' if role == 'audio' else 'images', [])
        require(len(saved) == 1 and saved[0].get('type') == 'output'
                and (output_root / saved[0].get('subfolder', '') / saved[0]['filename']).resolve() == origin,
                'native_history_output_mapping_changed')
        originals[role] = dict(local=bind(local), native_original=bind(origin))
    diagnostic_receipt = None
    if diagnostic:
        receipt_path = native_run / 'DIAGNOSTIC_RESULT.json'
        receipt = read(receipt_path)
        require(receipt == dict(schema=DIAGNOSTIC_SCHEMA, native_result=bind(folder / 'RESULT.json'),
                                input=plan['diagnostic_input'], diagnostic_input=proof, quality_passed=False,
                                source_evaluation=actual_source, visual_ready=False, production_approved=False,
                                native_records=dict(plan=bind(plan_path), request=bind(folder / 'REQUEST.json'),
                                                    history=bind(folder / 'HISTORY.json'))),
                'diagnostic_saved_result_receipt_changed')
        diagnostic_receipt = bind(receipt_path)
        input_status['result_receipt'] = diagnostic_receipt
    return dict(id=sid, native_id=pid, originals=originals, first_input=bind(first), input_status=input_status,
                diagnostic_receipt=diagnostic_receipt,
                expected_quotes=expected, actual_seed=graph['129']['inputs']['noise_seed'],
                opening_contract=opening.contract(entry), source_entry=entry,
                result_binding=bind(folder / 'RESULT.json'),
                binding=dict(plan=bind(plan_path), source=source, request=bind(folder / 'REQUEST.json'),
                             result=bind(folder / 'RESULT.json'), history=bind(folder / 'HISTORY.json')))


def sample_plan():
    """Cover the full minute and both sides of every real concatenation."""
    return dict(timeline=list(range(0, 1448, 24)) + [1447],
                opening=list(range(0, 49, 3)),
                joins=[dict(first_after=n, last_before=n - 1,
                            indices=sorted(set(range(n - 12, n + 13, 3)) | {n - 1, n}))
                       for n in (362, 724, 1086)])


def validate_import(run, descriptor, value, project=PROJECT):
    """Acceptance is an additional record; the prior review is never rewritten."""
    imported_path = checked(descriptor['imported'], project)
    require(imported_path == run / 'imported/S02/IMPORT.json', 'accepted_import_path_changed')
    imported = read(imported_path)
    accepted_path = checked(imported['acceptance'], project)
    require(accepted_path == run / 'USER_ACCEPTED_BASELINE.json', 'user_acceptance_binding_changed')
    accepted = read(accepted_path)
    result = read(checked(value['result_binding'], project))
    require(imported.get('schema') == SCHEMA and imported.get('shot_id') == 'S02'
            and imported.get('kind') == descriptor.get('kind') == 'imported_user_accepted_native'
            and imported.get('native_result') == descriptor.get('native_result') == value['result_binding']
            and imported.get('native_files') == result['files']
            and imported.get('prompt_id') == accepted.get('prompt_id') == value['native_id'] == ACCEPTED_ID
            and imported.get('file') == accepted.get('file') == value['originals']['video']['local']
            and imported['file']['sha256'] == ACCEPTED_SHA
            and imported.get('new_model_posts') == 0 and imported.get('temporal_trim') is False
            and imported.get('source_media_unchanged') is True,
            'exact_user_accepted_native_import_changed')
    require(accepted.get('native_result') == value['result_binding']
            and accepted.get('prior_review_unchanged') is True
            and accepted.get('new_acceptance_does_not_rewrite_prior_quality_record') is True,
            'acceptance_must_preserve_prior_quality_record')
    checked(accepted['prior_root_review'], project)
    records = imported.get('native_records', {})
    require(set(records) == {'PLAN', 'REQUEST', 'HISTORY', 'RESULT'}, 'original_import_records_required')
    require(records == dict(PLAN=value['binding']['plan'], REQUEST=value['binding']['request'],
                            HISTORY=value['binding']['history'], RESULT=value['result_binding']),
            'accepted_import_native_record_bindings_changed')
    for item in records.values():
        checked(item, project)
    return dict(imported=bind(imported_path), acceptance=bind(accepted_path),
                prior_review=accepted['prior_root_review'], quality_reassessment=False)


def validate(run, project=PROJECT):
    project, run = Path(project).resolve(), Path(run).resolve()
    require(run.parent == project / 'data/video_generation', 'project_minute_run_required')
    plan = read(run / 'PLAN.json')
    require(plan.get('schema') == SCHEMA and plan.get('publication') is False
            and plan.get('production_approved') is False and plan.get('temporal_leading_trim') is False,
            'source_driven_minute_plan_required')
    require(tuple(plan.get(k) for k in ('width', 'height', 'frames_per_segment', 'fps', 'steps',
                                      'expected_frames', 'expected_audio_rate', 'expected_audio_samples'))
            == (736, 1312, 362, 24, 12, 1448, 48000, 2896000), 'minute_clock_profile_changed')
    for key in ('source_case', 'authority', 'accepted_baseline'):
        checked(plan[key], project)
    descriptors = plan.get('segments', [])
    require([row.get('shot_id') for row in descriptors] == list(IDS), 'four_ordered_segments_required')
    values, rows, accepted_binding = [], [], None
    for descriptor in descriptors:
        sid = descriptor['shot_id']
        source_path = checked(descriptor['source_case'], project)
        require(source_path == run / 'segments' / sid / 'SOURCE_CASE.json', 'frozen_segment_source_changed')
        value = validate_native(descriptor['native_run'], sid, project)
        value['kind'] = 'imported' if sid == 'S02' else 'new'
        if sid == 'S02':
            accepted_binding = validate_import(run, descriptor, value, project)
            require(plan['accepted_baseline'] == accepted_binding['acceptance'], 'PLAN_acceptance_changed')
        else:
            expected_native = run / 'visual_h3_v3' / (run.name + '_' + sid)
            require(descriptor.get('kind') == 'new_native'
                    and Path(descriptor['native_run']).resolve() == expected_native
                    and Path(descriptor['native_result_path']).resolve()
                    == expected_native / 'shots' / sid / 'RESULT.json', 'new_native_namespace_changed')
            expected_source = 'SOURCE_CASE.json' if value.get('diagnostic_receipt') else 'VIDEO_SOURCE_CASE.json'
            require(Path(value['binding']['source']['path']).resolve()
                    == run / 'segments' / sid / expected_source, 'native_video_source_path_changed')
            original = core._entries(bind(source_path))
            require(len(original) == 1, 'one_frozen_source_segment_required')
            a, b = dict(original[0]), dict(value['source_entry'])
            a.pop('reanchor', None)
            b.pop('reanchor', None)
            require(a == b, 'source_changed_outside_selected_first_image')
            local = read(run / 'segments' / sid / 'FINAL_RESULT.json')
            require(local.get('native_result') == value['result_binding']
                    and local.get('file') == value['originals']['video']['local']
                    and local.get('prompt_id') == value['native_id'] and local.get('postprocessing') == [],
                    'new_segment_final_not_original_native')
            if value.get('diagnostic_receipt'):
                require(local.get('diagnostic_receipt') == value['diagnostic_receipt'],
                        'segment_final_diagnostic_receipt_changed')
        rows.append(dict(shot_id=sid, native_result=value['result_binding'], prompt_id=value['native_id'],
                         file=value['originals']['video']['local'], kind=value['kind']))
        values.append(value)
    require(len({row['prompt_id'] for row in rows}) == 4
            and len({row['file']['sha256'] for row in rows}) == 4, 'four_distinct_native_videos_required')
    inputs = dict(plan=bind(run / 'PLAN.json'), segments=rows)
    final = read(run / 'FINAL_RESULT.json')
    require(final.get('schema') == SCHEMA and final.get('segments') == rows
            and final.get('native_ids') == [row['prompt_id'] for row in rows]
            and final.get('native_results') == [row['native_result'] for row in rows]
            and final.get('assembly_inputs_sha256') == digest(inputs)
            and final.get('imported_s02') == accepted_binding['imported']
            and final.get('temporal_leading_trim') is False and final.get('publication') is False
            and final.get('production_approved') is False, 'final_assembly_original_inputs_changed')
    movie = checked(final['file'], project)
    require(movie == run / 'H3_STORY_OPENING_MINUTE_736x1312.mp4', 'minute_final_output_path_changed')
    request = read(run / 'ASSEMBLY_REQUEST.json')
    require(request.get('inputs') == inputs and request.get('source_media_unchanged') is True
            and request.get('temporal_leading_trim') is False
            and request.get('audio_resampled_to_48k') is True, 'assembly_request_input_policy_changed')
    return dict(run=run, plan=bind(run / 'PLAN.json'), values=values, imported=accepted_binding,
                final=final, final_binding=bind(run / 'FINAL_RESULT.json'), movie=movie)


def qa(run=DEFAULT_RUN, *, asr=False, project=PROJECT):
    value = validate(run, project)
    run = value['run']
    folder = run / 'qc_opening_minute' / value['final']['file']['sha256'] / ('with_asr' if asr else 'without_asr')
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(plan=value['plan'], final=value['final_binding'], file=value['final']['file'],
                   originals=[row['binding'] for row in value['values']], accepted_import=value['imported'],
                   diagnostic_results=[row.get('diagnostic_receipt') for row in value['values']],
                   asr_requested=asr)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'FINAL_QA.json'
    if manifest.exists():
        prior = read(manifest)
        require(prior['binding'] == binding, 'existing_minute_QA_input_changed')
        for item in prior['artifacts']:
            checked(item, project)
        return dict(status='already_complete', manifest=bind(manifest), file=value['final']['file'])
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    code = attempt / 'qa_source.py'
    code.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source=bind(code), started_at=time.time()))
    try:
        segments, artifacts = [], []
        for row in value['values']:
            sf = folder / row['id'] / row['native_id']
            sf.mkdir(parents=True, exist_ok=True)
            geometry, metadata = inspect_clock(row['originals']['video']['local']['path'], 362)
            artifacts.append(freeze(sf / 'PROBE.json', metadata))
            # User accepted S02: reuse its bound prior CPU report; do not re-run
            # speech recognition or infer that acceptance changed prior quality.
            if row['id'] == 'S02':
                native_run = Path(row['binding']['plan']['path']).parent
                prior_path = native_run.parents[1] / 'qc_opening' / row['native_id'] / 'with_asr/QA.json'
                speech = dict(status='accepted_import_no_reanalysis', quality_reassessment=False)
                if prior_path.exists():
                    prior = read(prior_path)
                    require(prior['video'] == row['originals']['video']['local'], 'imported_prior_QA_video_changed')
                    speech.update(prior_cpu_qa=bind(prior_path), prior_asr=prior.get('asr'))
                    artifacts.append(bind(prior_path))
            else:
                speech = cpu_asr(project, row, sf / 'asr', asr)
            wanted = {0, 36, 108, 180, 252, 324, 361}
            intervals = []
            for item in speech.get('quote_intervals', []):
                item = dict(item, actual_acoustic_speaker=None)
                if item['exactly_detected']:
                    a = max(0, min(361, round(item['start_ms'] * 24 / 1000)))
                    b = max(a, min(361, round(item['end_ms'] * 24 / 1000)))
                    item['indices'] = sorted({round(a + (b - a) * k / 4) for k in range(5)})
                    wanted.update(item['indices'])
                intervals.append(item)
            frames = extract_batch(row['originals']['video']['local']['path'], wanted, sf / 'frames')
            artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
            contact = make_board([frames[i] for i in (0, 36, 108, 180, 252, 324, 361)], sf / 'CONTACT.jpg')
            comparison = first_comparison(row['first_input'], frames[0], sf / 'INPUT_VS_ACTUAL_FIRST.jpg')
            artifacts.extend([contact, comparison['contact']])
            for qi, item in enumerate(intervals):
                if item.get('indices'):
                    item['contact'] = make_board([frames[i] for i in item['indices']], sf / f'QUOTE_{qi+1:02d}.jpg', columns=5)
                    artifacts.append(item['contact'])
            segments.append(dict(segment=row['id'], native_id=row['native_id'], kind=row['kind'],
                                 video=row['originals']['video']['local'], clock=geometry,
                                 input_status=row['input_status'],
                                 opening_contract=row['opening_contract'], actual_seed=row['actual_seed'],
                                 contact=contact, first_input_comparison=comparison,
                                 asr=speech, quote_intervals=intervals, root_visual_review=None))
        geometry, metadata = inspect_clock(value['movie'], 1448, final=True)
        artifacts.append(freeze(folder / 'FINAL_PROBE.json', metadata))
        samples = sample_plan()
        wanted = set(samples['timeline']) | set(samples['opening'])
        for row in samples['joins']:
            wanted.update(row['indices'])
        frames = extract_batch(value['movie'], wanted, folder / 'final_frames')
        artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
        timeline = []
        for offset in range(0, len(samples['timeline']), 21):
            selected = samples['timeline'][offset:offset + 21]
            contact = make_board([frames[i] for i in selected], folder / f'TIMELINE_{offset//21+1:02d}.jpg', columns=5)
            timeline.append(dict(indices=selected, contact=contact))
            artifacts.append(contact)
        opening_contact = make_board([frames[i] for i in samples['opening']], folder / 'OPENING_DENSE.jpg', columns=5)
        artifacts.append(opening_contact)
        for index, join in enumerate(samples['joins']):
            join['contact'] = make_board([frames[i] for i in join['indices']], folder / f'JOIN_{index+1:02d}.jpg', columns=5)
            artifacts.append(join['contact'])
        validate(run, project)
        report = dict(schema='story_opening_minute_CPU_QA/v1', binding=binding, source_code=bind(code),
                      file=value['final']['file'], native_ids=value['final']['native_ids'], final_clock=geometry,
                      diagnostic_segments=[row['id'] for row in value['values'] if row.get('diagnostic_receipt')],
                      content_status='user_review_pending_not_visual_quality_approval',
                      segments=segments, timeline=timeline, opening_dense=dict(indices=samples['opening'], contact=opening_contact),
                      joins=samples['joins'], limits=LIMITS, root_actual_visual_review=None,
                      artifacts=list({r['path']: r for r in artifacts}.values()), production_approved=False)
        freeze(manifest, report)
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), finished_at=time.time()))
        return dict(status='CPU_QA_complete', manifest=bind(manifest), file=value['final']['file'],
                    timeline=[p['contact'] for p in timeline], joins=[p['contact'] for p in samples['joins']],
                    opening_dense=opening_contact, production_approved=False)
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error),
                                          traceback=traceback.format_exc(), no_media_retry=True))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--asr', action='store_true', help='CPU ASR of the three new segments; reuse accepted S02 report')
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    args = parser.parse_args(argv)
    try:
        result = qa(args.run, asr=args.asr, project=args.project_root)
    except Exception as error:
        import json
        print(json.dumps(dict(status='CPU_QA_failed', error=type(error).__name__, message=str(error),
                              no_media_retry=True), ensure_ascii=False))
        return 2
    import json
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

