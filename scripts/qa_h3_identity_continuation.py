"""CPU evidence for two retained clips and two actual-native-tail successors.

No HTTP, GPU, media submission, automatic repair, or identity/speaker approval.
Metadata coverage and an observer's bound findings are evidence, not proof that
all faces or performances are correct.
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
import qa_h3_story_opening_minute as prior_qa
from src.content_factory import visual_h3_handoff_v3 as native
from src.content_factory import visual_h3_prompt_parity_v19 as assembly_clock

DEFAULT_RUN = PROJECT / 'data/video_generation/h3_identity_continuation_from_s03_20261111_v1'
SERIES_SCHEMA = 'h3_identity_continuation_series/v1'
NATIVE_SCHEMA = 'h3_identity_continuation_native/v1'
INPUT_SCHEMA = 'actual_native_tail_identity/v1'
IDS = ('S01', 'S02', 'S03', 'S04')
NEW_IDS = ('S03', 'S04')
ACTORS = {'su_mo', 'ye_nan', 'ye_xijue'}
RETAINED = {
    'S01': ('5fad6720-7090-4e09-9fb7-302342a951b3', '1cb2f0ce6c1fd0de355762a816bc86da9cbded2daa64f1d94cf22cf4fa7ee83a'),
    'S02': ('ad632988-544f-4074-91c5-76ccfff0f88e', '333c204265493be12503173e836094b6bfb06b85a316a32ac242b0d2ecdb12a5'),
}
EXPECTED_QUOTES = {
    'S03': ['这孩子后来成了独眼神医。还好，现在他的眼睛还是完好的。', '他一定在想怎么打我。'],
    'S04': ['做得很好，下次不要了。', '好的爸爸，我下次一定不会只带个面包，我会偷很多钱回来。', '我说的是，不要再出去偷东西啊！'],
}


def input_context(binding):
    from src.content_factory.visual_h3_identity_continuation_v1 import validate_input
    return validate_input(binding)


def exact_endpoint_selection(graph):
    require(graph['pick_last']['inputs'] == dict(image=['122', 0], batch_index=361, length=1)
            and graph['save_last']['inputs'].get('images') == ['pick_last', 0]
            and graph['pick_first']['inputs'] == dict(image=['122', 0], batch_index=0, length=1)
            and graph['save_first']['inputs'].get('images') == ['pick_first', 0],
            'native_first_last_must_select_actual_decoded_endpoint_images')


def prepared_graph(native_run, sid, project=PROJECT):
    """Check actual staged bytes and the frozen API graph without submission."""
    project, native_run = Path(project).resolve(), Path(native_run).resolve()
    require(native_run.is_relative_to(project / 'data/video_generation'), 'project_native_run_required')
    plan_path, folder = native_run / 'PLAN.json', native_run / 'shots' / sid
    plan = read(plan_path)
    require(plan.get('schema') == NATIVE_SCHEMA and plan.get('upstream_contract') == INPUT_SCHEMA
            and plan.get('publication') is False and plan.get('production_approved') is False
            and len(plan.get('shots', [])) == 1, 'explicit_identity_continuation_plan_required')
    row = plan['shots'][0]
    require(row.get('id') == sid and sid in NEW_IDS and 'continuity_input' not in row,
            'new_tail_identity_contract_must_not_forge_old_ready_proof')
    proof = row['identity_continuation']
    context = input_context(proof['input'])
    require(context['proof'] == proof and proof.get('schema') == INPUT_SCHEMA
            and plan.get('input') == proof['input'] and plan.get('source') == proof['source_case'],
            'actual_native_tail_input_proof_changed')
    source = checked(proof['source_case'], project)
    first = checked(row['first_frame'], project)
    require(bind(first) == proof['first_image'] == context['first_image'], 'selected_native_tail_image_changed')
    require(len(proof.get('clip_identity_actor_ids', [])) == 3
            and set(proof['clip_identity_actor_ids']) == ACTORS
            and len(proof.get('opening_actor_ids', [])) == 1
            and set(proof['opening_actor_ids']) == ({'ye_xijue'} if sid == 'S03' else {'su_mo'}),
            'three_clip_actors_and_actual_opening_actor_contract_required')
    predecessor = checked(proof['predecessor_result'], project)
    previous = read(predecessor)
    pred_sid = 'S02' if sid == 'S03' else 'S03'
    require(previous.get('shot_id') == pred_sid and previous.get('technical_status') == 'technical_saved'
            and previous.get('publication') is False and previous.get('production_approved') is False
            and set(previous.get('files', {})) == {'video', 'audio', 'first', 'last'},
            'actual_saved_predecessor_required')
    last = previous['files']['last']
    require(bind(checked(last, project)) == bind(first), 'first_image_must_be_exact_predecessor_native_last')
    previous_value = saved_originals(predecessor.parents[2], pred_sid, project)
    require(previous_value['result_binding'] == proof['predecessor_result']
            and previous_value['originals']['last']['local'] == bind(first),
            'actual_predecessor_native_tail_history_changed')
    review = checked(proof['coverage_review'], project)
    observed = read(review)
    require(observed.get('schema') == 'h3_identity_tail_coverage/v1' and observed.get('shot_id') == sid
            and observed.get('anchor_result') == proof['predecessor_result']
            and observed.get('anchor_image') == bind(first) and observed.get('completion_known') is True
            and observed.get('outcome_unknown') is False and observed.get('reviewed_by')
            and observed.get('evidence') and set(observed.get('actual_anchor_actor_ids', [])) == ACTORS
            and set(observed.get('identity_by_actor', {})) == ACTORS,
            'actual_three_actor_observation_binding_changed')
    # The core authenticates the detailed three-person observation contract.
    # Its existence is never converted into a semantic identity pass here.
    require(context.get('quality_passed') is False and context.get('full_video_quality_passed') is False,
            'metadata_must_not_claim_identity_quality_passed')
    for item in (plan['series_plan'], plan['base_workflow'], *plan['code']):
        checked(item, project)
    series_root = Path(plan['series_plan']['path']).parent.resolve()
    require(native_run == series_root / 'visual_h3_v3' / (series_root.name + '_' + sid),
            'new_series_native_namespace_changed')
    if sid == 'S03':
        imported = read(series_root / 'imported/S02/IMPORT.json')
        require(proof['predecessor_result'] == imported['native_result']
                and previous['prompt_id'] == RETAINED['S02'][0]
                and previous['files']['video']['sha256'] == RETAINED['S02'][1],
                'S03_must_continue_the_preserved_original_S02')
    else:
        require(predecessor == series_root / 'visual_h3_v3' / (series_root.name + '_S03') / 'shots/S03/RESULT.json',
                'S04_must_continue_this_runs_new_S03')
    graph = read(folder / 'workflow_api.json')
    native._validate_graph(graph, row['scope'], row['input_name'])
    exact_endpoint_selection(graph)
    c = graph['condition']['inputs']
    require((c['width'], c['height'], c['length'], graph['124']['inputs']['steps'],
             graph['130']['inputs']['fps']) == (736, 1312, 362, 12, 24), 'native_profile_changed')
    require(c['prompt'] == context['compiled_prompt']
            and proof['compiled_prompt_utf8_sha256'] == context['compiled_prompt_utf8_sha256']
            and quotes(c['prompt']) == EXPECTED_QUOTES[sid], 'five_original_tail_quotes_or_prompt_changed')
    require(context['entry'].get('duration') == row.get('timing', {}).get('requested_seconds') == 15
            and row['timing'].get('native_frames') == 362 and row['timing'].get('automatic_audio_cut') is False,
            'source_native_timing_or_automatic_cut_policy_changed')
    require(digest(graph) == row['graph_sha256'], 'frozen_API_graph_changed')
    cfg = plan['config']
    input_root, output_root = [Path(cfg[k]).resolve() for k in ('input_root', 'output_root')]
    staged = (input_root / row['input_name']).resolve()
    require(input_root.is_relative_to(project) and output_root.is_relative_to(project)
            and staged.is_relative_to(input_root) and sha(staged) == sha(first),
            'actual_staged_tail_pixels_changed')
    require(graph['ref_scene']['inputs']['image'] == row['input_name'], 'actual_graph_first_input_name_changed')
    return dict(native_run=native_run, folder=folder, plan=plan, row=row, context=context, graph=graph,
                source=bind(source), first_input=bind(first), predecessor_result=bind(predecessor),
                coverage_review=bind(review), staged_input=bind(staged),
                binding=dict(plan=bind(plan_path), source=bind(source), input=proof['input'],
                             graph=bind(folder / 'workflow_api.json'), predecessor_result=bind(predecessor),
                             coverage_review=bind(review), staged_input=bind(staged)))


def saved_originals(native_run, sid, project=PROJECT):
    """Independently read actual POST/history and all four original outputs."""
    native_run = Path(native_run).resolve()
    folder, plan = native_run / 'shots' / sid, read(native_run / 'PLAN.json')
    rows = plan.get('shots', [])
    require(len(rows) == 1 and rows[0].get('id') == sid, 'one_original_native_shot_required')
    row, graph = rows[0], read(folder / 'workflow_api.json')
    native._validate_graph(graph, row['scope'], row['input_name'])
    exact_endpoint_selection(graph)
    c = graph['condition']['inputs']
    require((c['width'], c['height'], c['length'], graph['124']['inputs']['steps'],
             graph['130']['inputs']['fps']) == (736, 1312, 362, 12, 24), 'original_native_profile_changed')
    require(digest(graph) == row['graph_sha256'] and read(folder / 'REQUEST.json').get('prompt') == graph,
            'actual_POST_graph_changed')
    state, result = read(folder / 'STATE.json'), read(folder / 'RESULT.json')
    pid = state.get('prompt_id')
    require(state.get('status') == 'technical_saved' and state.get('id') == sid
            and state.get('plan_sha256') == digest(plan) and pid
            and result.get('prompt_id') == read(folder / 'RESPONSE.json').get('prompt_id') == pid,
            'original_saved_native_ID_required')
    require(result.get('schema') == native.SCHEMA and result.get('shot_id') == sid
            and result.get('technical_status') == 'technical_saved'
            and result.get('graph_sha256') == row['graph_sha256']
            and result.get('first_frame_sha256') == row['first_frame']['sha256']
            and result.get('timing') == row['timing'] and result.get('publication') is False
            and result.get('production_approved') is False, 'original_native_RESULT_changed')
    claim = read(folder / 'CLAIM.json')
    require(claim.get('graph_sha256') == row['graph_sha256']
            and claim.get('first_frame_sha256') == row['first_frame']['sha256'], 'actual_CLAIM_changed')
    history = read(folder / 'HISTORY.json').get(pid, {})
    hp, hs = history.get('prompt', []), history.get('status', {})
    require(len(hp) > 2 and hp[1] == pid and native.native_graph_equivalence(graph, hp[2]) is not None
            and hs.get('completed') is True and hs.get('status_str') == 'success', 'native_success_history_changed')
    output_root = Path(plan['config']['output_root']).resolve()
    input_root = Path(plan['config']['input_root']).resolve()
    first = checked(row['first_frame'], project)
    staged = (input_root / row['input_name']).resolve()
    require(input_root.is_relative_to(Path(project).resolve()) and staged.is_relative_to(input_root)
            and sha(staged) == sha(first), 'native_original_staged_first_changed')
    scope = (output_root / row['scope']).resolve()
    require(output_root.is_relative_to(Path(project).resolve()) and scope.is_relative_to(output_root),
            'native_output_scope_escaped')
    require(set(result.get('files', {})) == {'video', 'audio', 'first', 'last'}, 'four_native_originals_required')
    originals = {}
    for role, item in result['files'].items():
        local, origin = checked(item, project), Path(item['source_path']).resolve()
        require(local.is_relative_to(folder / 'artifacts') and local.stat().st_size > 0
                and origin.parent == scope and origin.is_file() and sha(origin) == item['sha256'],
                'native_original_pixels_changed')
        mapped = history.get('outputs', {}).get('save_' + role, {}).get('audio' if role == 'audio' else 'images', [])
        require(len(mapped) == 1 and mapped[0].get('type') == 'output'
                and (output_root / mapped[0].get('subfolder', '') / mapped[0]['filename']).resolve() == origin,
                'native_history_save_mapping_changed')
        originals[role] = dict(local=bind(local), native_original=bind(origin))
    return dict(id=sid, native_id=pid, plan=plan, row=row, graph=graph, result=result, originals=originals,
                result_binding=bind(folder / 'RESULT.json'),
                binding=dict(plan=bind(native_run / 'PLAN.json'), request=bind(folder / 'REQUEST.json'),
                             result=bind(folder / 'RESULT.json'), history=bind(folder / 'HISTORY.json')))


def validate_new_native(native_run, sid, project=PROJECT):
    prepared = prepared_graph(native_run, sid, project)
    value = saved_originals(native_run, sid, project)
    require(value['result'].get('continuity_input') is None, 'new_contract_must_not_forge_old_ready_proof')
    path = Path(native_run) / 'IDENTITY_CONTINUATION_RESULT.json'
    receipt = read(path)
    expected_records = {k: value['binding'][k] for k in ('plan', 'request', 'history')}
    require(receipt.get('schema') == INPUT_SCHEMA and receipt.get('native_result') == value['result_binding']
            and receipt.get('input') == prepared['row']['identity_continuation']['input']
            and receipt.get('identity_continuation') == prepared['row']['identity_continuation']
            and receipt.get('native_records') == expected_records and receipt.get('production_approved') is False,
            'saved_native_continuation_receipt_changed')
    value.update(kind='new', first_input=prepared['first_input'], expected_quotes=EXPECTED_QUOTES[sid],
                 source_entry=prepared['context']['entry'], actual_seed=value['graph']['129']['inputs']['noise_seed'],
                 continuation_receipt=bind(path),
                 input_status=dict(contract=INPUT_SCHEMA, predecessor_result=prepared['predecessor_result'],
                     previous_native_last_equals_staged_and_POST=True,
                     coverage_review=prepared['coverage_review'], metadata_clip_actor_ids=sorted(ACTORS),
                     opening_actor_ids=prepared['row']['identity_continuation']['opening_actor_ids'],
                     metadata_coverage_complete=prepared['context'].get('identity_coverage_complete'),
                     identity_quality_verified_by_CPU=False, full_video_quality_passed=False),
                 binding=dict(**value['binding'], source=prepared['source'],
                              input=prepared['row']['identity_continuation']['input'],
                              predecessor_result=prepared['predecessor_result'],
                              coverage_review=prepared['coverage_review'], continuation_receipt=bind(path)))
    return value


def series_inputs(run, project=PROJECT):
    project, run = Path(project).resolve(), Path(run).resolve()
    require(run.parent == project / 'data/video_generation', 'project_continuation_run_required')
    plan = read(run / 'PLAN.json')
    require(plan.get('schema') == SERIES_SCHEMA and plan.get('publication') is False
            and plan.get('production_approved') is False and plan.get('new_image_submissions') == 0
            and plan.get('new_video_submissions') == 2 and plan.get('preserved_prefix_frames') == 724
            and plan.get('prefix_source_media_unchanged') is True
            and plan.get('output_prefix_pixel_identity_claimed') is False,
            'two_preserved_two_new_series_contract_required')
    require(tuple(plan.get(k) for k in ('width', 'height', 'frames_per_segment', 'fps', 'steps', 'expected_frames'))
            == (736, 1312, 362, 24, 12, 1448), 'series_clock_profile_changed')
    checked(plan['config'], project)
    checked(plan['authority'], project)
    require([r.get('shot_id') for r in plan.get('prefix', [])] == list(IDS[:2])
            and [r.get('shot_id') for r in plan.get('sources', [])] == list(NEW_IDS),
            'two_prefix_and_two_source_orders_required')
    values = []
    for descriptor in plan['prefix']:
        sid = descriptor['shot_id']
        path = checked(descriptor['imported'], project)
        require(path == run / 'imported' / sid / 'IMPORT.json', 'preserved_prefix_descriptor_changed')
        imported = read(path)
        result_path = checked(imported['native_result'], project)
        value = prior_qa.validate_native(result_path.parents[2], sid, project)
        graph = read(result_path.parent / 'workflow_api.json')
        exact_endpoint_selection(graph)
        result = read(result_path)
        require(imported.get('schema') == SERIES_SCHEMA and imported.get('shot_id') == sid
                and imported.get('kind') == 'preserved_native_prefix'
                and imported.get('native_result') == value['result_binding']
                and imported.get('native_files') == result['files']
                and imported.get('prompt_id') == value['native_id'] == RETAINED[sid][0]
                and imported.get('file') == value['originals']['video']['local']
                and imported['file']['sha256'] == RETAINED[sid][1]
                and imported.get('new_model_calls') == 0 and imported.get('source_media_unchanged') is True,
                'exact_preserved_prefix_native_ID_or_pixels_changed')
        records = {k: value['binding'][k] for k in ('plan', 'request', 'history', 'result')}
        require(imported.get('native_records') == records, 'preserved_prefix_original_records_changed')
        value.update(kind='imported', descriptor=bind(path), continuation_receipt=None)
        values.append(value)
    for descriptor in plan['sources']:
        sid = descriptor['shot_id']
        path = checked(descriptor['source_case'], project)
        require(path == run / 'segments' / sid / 'SOURCE_CASE.json'
                and Path(descriptor['native_run']).resolve() == run / 'visual_h3_v3' / (run.name + '_' + sid),
                'new_continuation_source_or_native_namespace_changed')
        entries = prior_qa.core._entries(bind(path))
        require(len(entries) == 1 and entries[0]['shot_id'] == sid
                and quotes(prior_qa.core.compile_prompt(entries[0])['compiled_prompt']) == EXPECTED_QUOTES[sid],
                'five_original_source_quotes_changed')
    return dict(run=run, plan=plan, plan_binding=bind(run / 'PLAN.json'), values=values)


def validate_prepared(run=DEFAULT_RUN, project=PROJECT):
    value = series_inputs(run, project)
    rows = []
    for descriptor in value['plan']['sources']:
        sid, nr = descriptor['shot_id'], Path(descriptor['native_run'])
        if not (nr / 'PLAN.json').exists():
            rows.append(dict(id=sid, status='not_prepared_no_future_tail_invented', model_calls=0))
            continue
        current = prepared_graph(nr, sid, project)
        rows.append(dict(id=sid, status='frozen_actual_tail_graph_verified_not_submitted_by_QA',
                         binding=current['binding'], input_status=dict(metadata_only=True,
                         identity_quality_verified_by_CPU=False), model_calls=0))
    return dict(schema='identity_continuation_prepared_CPU_QA/v1', plan=value['plan_binding'],
                preserved_native_ids=[r['native_id'] for r in value['values']], new_segments=rows,
                media_calls=0, production_approved=False)


def validate(run=DEFAULT_RUN, project=PROJECT):
    value = series_inputs(run, project)
    run, values = value['run'], value['values']
    for descriptor in value['plan']['sources']:
        sid = descriptor['shot_id']
        row = validate_new_native(descriptor['native_run'], sid, project)
        require(row['binding']['source'] == descriptor['source_case'], 'saved_new_source_binding_changed')
        path = run / 'segments' / sid / 'FINAL_RESULT.json'
        final = read(path)
        require(final.get('native_result') == row['result_binding'] and final.get('prompt_id') == row['native_id']
                and final.get('file') == row['originals']['video']['local'] and final.get('postprocessing') == []
                and final.get('continuation_receipt') == row['continuation_receipt']
                and final.get('production_approved') is False, 'new_segment_final_not_saved_native_original')
        row['descriptor'] = bind(path)
        values.append(row)
    require([r['id'] for r in values] == list(IDS) and len({r['native_id'] for r in values}) == 4
            and len({r['originals']['video']['local']['sha256'] for r in values}) == 4,
            'four_distinct_ordered_native_clips_required')
    rows = [dict(shot_id=r['id'], native_result=r['result_binding'], file=r['originals']['video']['local'],
                 prompt_id=r['native_id'], kind=r['kind'], descriptor=r['descriptor']) for r in values]
    inputs = dict(plan=value['plan_binding'], segments=rows)
    final = read(run / 'FINAL_RESULT.json')
    require(final.get('schema') == SERIES_SCHEMA and final.get('segments') == rows
            and final.get('native_ids') == [r['native_id'] for r in values]
            and final.get('assembly_inputs_sha256') == digest(inputs)
            and final.get('prefix_source_media_unchanged') is True
            and final.get('output_prefix_pixel_identity_claimed') is False
            and final.get('publication') is False and final.get('production_approved') is False,
            'final_assembly_sources_or_order_changed')
    request = read(run / 'ASSEMBLY_REQUEST.json')
    require(request.get('inputs') == inputs and request.get('prefix_source_media_unchanged') is True
            and request.get('output_prefix_pixel_identity_claimed') is False
            and request.get('temporal_leading_trim') is False, 'assembly_prefix_or_clock_policy_changed')
    movie = checked(final['file'], project)
    require(movie == run / 'H3_IDENTITY_CONTINUATION_MINUTE_736x1312.mp4', 'continuation_movie_path_changed')
    expected_command, expected_filter = assembly_clock.assembly_command(
        [row['file']['path'] for row in rows], run / 'ASSEMBLY_FILTER.txt', movie, frames=362)
    require(normalize_assembly_command(request['command'], project) == normalize_assembly_command(expected_command, project)
            and (run / 'ASSEMBLY_FILTER.txt').read_text(encoding='utf-8') == expected_filter,
            'actual_assembly_command_or_order_changed')
    value.update(values=values, final=final, final_binding=bind(run / 'FINAL_RESULT.json'), movie=movie)
    return value


def normalize_assembly_command(command, project=PROJECT):
    """Only path spelling is normalized; options and input order remain exact."""
    value = list(command)
    for index in [i + 1 for i, item in enumerate(value[:-1]) if item in ('-i', '-filter_complex_script')] + [len(value) - 1]:
        path = Path(value[index])
        value[index] = str((path if path.is_absolute() else Path(project) / path).resolve())
    return value


def retained_speech(run, row, project=PROJECT):
    prefix = read(run / 'imported/S01/IMPORT.json')
    old = Path(prefix['native_result']['path']).parents[4]
    previous = read(old / 'FINAL_RESULT.json')
    path = old / 'qc_opening_minute' / previous['file']['sha256'] / 'with_asr/FINAL_QA.json'
    report = read(path)
    prior = next(item for item in report['segments'] if item['segment'] == row['id'])
    require(prior['native_id'] == row['native_id'] and prior['video'] == row['originals']['video']['local'],
            'retained_original_ASR_report_binding_changed')
    return dict(status='preserved_prefix_prior_report_no_reanalysis', prior_cpu_qa=bind(path),
                prior_asr=prior['asr'], quality_reassessment=False)


def segment_evidence(row, folder, *, asr=False, preview=False, project=PROJECT):
    folder.mkdir(parents=True, exist_ok=True)
    geometry, metadata = inspect_clock(row['originals']['video']['local']['path'], 362)
    artifacts = [freeze(folder / 'PROBE.json', metadata)]
    speech = (dict(status='not_requested', quote_intervals=[]) if preview else
              dict(status='preserved_prefix_no_reanalysis', quote_intervals=[]) if row['kind'] == 'imported' else
              cpu_asr(project, row, folder / 'asr', asr))
    wanted = set(range(0, 361, 12)) | {361} if preview else {0, 36, 108, 180, 252, 324, 361}
    intervals = []
    for item in speech.get('quote_intervals', []):
        item = dict(item, actual_acoustic_speaker=None)
        if item['exactly_detected']:
            a = max(0, min(361, round(item['start_ms'] * 24 / 1000)))
            b = max(a, min(361, round(item['end_ms'] * 24 / 1000)))
            item['indices'] = sorted({round(a + (b - a) * k / 4) for k in range(5)})
            wanted.update(item['indices'])
        intervals.append(item)
    planned = []
    if preview:
        for audio in row['source_entry']['audio']:
            a, b = max(0, round(audio['start'] * 24)), min(361, round(audio['end'] * 24))
            indices = sorted({round(a + (b - a) * k / 4) for k in range(5)})
            planned.append(dict(planned_start=audio['start'], planned_end=audio['end'],
                                speaker_from_source_only=audio['speaker'], mode=audio['mode'], indices=indices))
            wanted.update(indices)
    frames = extract_batch(row['originals']['video']['local']['path'], wanted, folder / 'frames')
    artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
    contacts = []
    base = list(range(0, 361, 12)) + [361] if preview else [0, 36, 108, 180, 252, 324, 361]
    for offset in range(0, len(base), 8):
        contact = make_board([frames[i] for i in base[offset:offset + 8]], folder / f'CONTACT_{offset//8+1:02d}.jpg')
        contacts.append(contact)
        artifacts.append(contact)
    comparison = first_comparison(row['first_input'], frames[0], folder / 'INPUT_VS_ACTUAL_FIRST.jpg')
    artifacts.append(comparison['contact'])
    for name, items in (('QUOTE', intervals), ('PLANNED_SOUND', planned)):
        for index, item in enumerate(items):
            if item.get('indices'):
                item['contact'] = make_board([frames[i] for i in item['indices']], folder / f'{name}_{index+1:02d}.jpg', columns=5)
                artifacts.append(item['contact'])
    return dict(segment=row['id'], native_id=row['native_id'], kind=row['kind'],
                video=row['originals']['video']['local'], clock=geometry, input_status=row['input_status'],
                actual_seed=row['actual_seed'], contacts=contacts, first_input_comparison=comparison,
                asr=speech, quote_intervals=intervals, planned_sound_windows=planned,
                root_visual_review=None), artifacts


def sample_plan():
    value = prior_qa.sample_plan()
    value['repair_boundary'] = sorted(set(range(696, 769, 3)) | {723, 724})
    return value


def qa(run=DEFAULT_RUN, *, asr=False, project=PROJECT):
    value = validate(run, project)
    run = value['run']
    folder = run / 'qc_identity' / value['final']['file']['sha256'] / ('with_asr' if asr else 'without_asr')
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(plan=value['plan_binding'], final=value['final_binding'], video=value['final']['file'],
                   originals=[r['binding'] for r in value['values']], descriptors=[r['descriptor'] for r in value['values']],
                   asr_requested=asr, retained_prefix_retranscribed=False)
    freeze(folder / 'BINDING.json', binding)
    manifest = folder / 'FINAL_QA.json'
    if manifest.exists():
        prior = read(manifest)
        require(prior['binding'] == binding, 'existing_continuation_QA_inputs_changed')
        for item in prior['artifacts']:
            checked(item, project)
        return dict(status='already_complete', manifest=bind(manifest), file=value['final']['file'])
    attempt = folder / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    code = attempt / 'qa_source.py'
    code.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source_code=bind(code), at_epoch=time.time()))
    try:
        segments, artifacts = [], []
        for row in value['values']:
            sf = folder / row['id'] / row['native_id']
            segment, files = segment_evidence(row, sf, asr=asr, project=project)
            if row['kind'] == 'imported':
                segment['asr'] = retained_speech(run, row, project)
                artifacts.append(segment['asr']['prior_cpu_qa'])
            segments.append(segment)
            artifacts.extend(files)
        geometry, metadata = inspect_clock(value['movie'], 1448, final=True)
        artifacts.append(freeze(folder / 'FINAL_PROBE.json', metadata))
        samples = sample_plan()
        wanted = set(samples['timeline']) | set(samples['opening']) | set(samples['repair_boundary'])
        for join in samples['joins']:
            wanted.update(join['indices'])
        frames = extract_batch(value['movie'], wanted, folder / 'final_frames')
        artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values())
        timeline = []
        for offset in range(0, len(samples['timeline']), 21):
            selected = samples['timeline'][offset:offset + 21]
            contact = make_board([frames[i] for i in selected], folder / f'TIMELINE_{offset//21+1:02d}.jpg', columns=5)
            timeline.append(dict(indices=selected, contact=contact))
            artifacts.append(contact)
        regions = {}
        for name in ('opening', 'repair_boundary'):
            contact = make_board([frames[i] for i in samples[name]], folder / (name.upper() + '.jpg'), columns=5)
            regions[name] = dict(indices=samples[name], contact=contact)
            artifacts.append(contact)
        for index, join in enumerate(samples['joins']):
            join['contact'] = make_board([frames[i] for i in join['indices']], folder / f'JOIN_{index+1:02d}.jpg', columns=5)
            artifacts.append(join['contact'])
        validate(run, project)
        report = dict(schema='identity_continuation_CPU_QA/v1', binding=binding, source_code=bind(code),
                      file=value['final']['file'], native_ids=value['final']['native_ids'], final_clock=geometry,
                      preserved_prefix_frames=724, preserved_source_media=True, output_prefix_pixel_identity_claimed=False,
                      segments=segments, timeline=timeline, regions=regions, joins=samples['joins'],
                      artifacts=list({r['path']: r for r in artifacts}.values()), limits=LIMITS,
                      CPU_identity_quality_verified=False, root_actual_visual_review=None, production_approved=False)
        freeze(manifest, report)
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), finished_at=time.time()))
        return dict(status='CPU_QA_complete', manifest=bind(manifest), file=value['final']['file'],
                    timeline=[p['contact'] for p in timeline], joins=[p['contact'] for p in samples['joins']],
                    regions=regions, production_approved=False)
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error),
                                          traceback=traceback.format_exc(), no_media_retry=True))
        raise


def preview_segment(run, sid, project=PROJECT):
    require(sid in NEW_IDS, 'preview_only_new_saved_tail_segments')
    value = validate_new_native(Path(run) / 'visual_h3_v3' / (Path(run).name + '_' + sid), sid, project)
    folder = Path(run) / 'qc_segment_previews' / sid / value['native_id']
    report, artifacts = segment_evidence(value, folder, preview=True, project=project)
    path = folder / 'PREVIEW.json'
    freeze(path, dict(schema='identity_continuation_CPU_preview/v1', report=report, artifacts=artifacts,
                      native_binding=value['binding'], ASR_executed=False, production_approved=False))
    return dict(status='CPU_preview_complete', native_id=value['native_id'], manifest=bind(path), contacts=report['contacts'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--asr', action='store_true')
    parser.add_argument('--prepared', action='store_true')
    parser.add_argument('--preview', choices=NEW_IDS)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    args = parser.parse_args(argv)
    import json
    try:
        result = (validate_prepared(args.run, args.project_root) if args.prepared else
                  preview_segment(args.run, args.preview, args.project_root) if args.preview else
                  qa(args.run, asr=args.asr, project=args.project_root))
    except Exception as error:
        print(json.dumps(dict(status='CPU_QA_failed', error=type(error).__name__, message=str(error), no_media_retry=True), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

