"""Independent CPU QA for two preserved clips and two oral-dialogue revisions.

No media dispatch, service changes, or semantic approval. ASR is confined to
the two fresh clips, with an exclusive per-clip claim and cached-result reuse.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import traceback
import types
import uuid

SCRIPTS = Path(__file__).resolve().parent
for path in (SCRIPTS, SCRIPTS.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import qa_h3_library_continuation_v2 as previous

base = previous.previous.base
PROJECT, IDS = base.PROJECT, base.IDS
FRESH = ('S03', 'S04')
PREFIX = ('S01', 'S02')
VERSION = 'library_oral_revision/v1'
OLD = PROJECT / 'data/video_generation/h3_library_bound_next_minute_20261113_v1'
read, bind, checked, require, sha, freeze, digest = base.read, base.bind, base.checked, base.require, base.sha, base.freeze, base.digest


def revision(binding, project=PROJECT):
    value = read(checked(binding, project))
    require(value.get('schema') == 'library_oral_script_revision/v1'
            and value.get('fresh_shot_ids') == list(FRESH)
            and value.get('scope') == {'imports': list(PREFIX), 'regenerated': list(FRESH)}
            and value.get('wording_is_authorized_oral_adaptation_not_verbatim_novel') is True
            and value.get('production_approved') is False and value.get('publication') is False,
            'explicit_oral_revision_scope_required')
    source = checked(value['original_script'], project).read_text(encoding='utf-8')
    checked(value['original_selection'], project)
    lines = source.splitlines()
    for key, item in value['evidence'].items():
        text = item['text']
        require(str(item['line']) == key and lines[item['line'] - 1] == text
                and source[item['source_start']:item['source_end']] == text
                and hashlib.sha256(text.encode()).hexdigest() == item['sha256'],
                'original_manuscript_line_offsets_or_hash_changed')
    require(set(value['segments']) == set(FRESH), 'only_two_fresh_oral_segments_required')
    return value


def source_entry(binding, sid, revision_binding, project=PROJECT):
    require(sid in FRESH, 'preserved_prefix_is_not_a_new_source')
    raw = read(checked(binding, project))
    require(len(raw.get('shots', [])) == 1 and raw['shots'][0].get('shot_id') == sid,
            'one_explicit_new_source_required')
    entry = raw['shots'][0]
    compiled = previous.previous.core.validate_entry(entry)
    require(compiled['source_coverage_complete'], 'complete_source_audio_action_coverage_required')
    rev = revision(revision_binding, project)
    require(entry.get('script_revision') == entry.get('oral_revision') == revision_binding
            and entry.get('script_selection') == revision_binding
            and entry.get('authoritative_script') == rev['original_script'],
            'new_source_must_bind_authorized_oral_revision')
    quotes = [s['text'][1:-1] for s in entry['source_spans'] if s['kind'] == 'audio']
    require(len(entry['audio']) == len(quotes) == len(rev['segments'][sid]),
            'all_oral_lines_exactly_once_required')
    actors = entry['full_clip_actor_ids']
    require(previous.same_unique_cast(actors, ['ye_dong', 'ye_nan', 'ye_yaner', 'ye_xijue'])
            and set(entry['character_names']) == set(actors) and entry['place_id'] == 'children_room',
            'four_children_in_whole_segment_required')
    provenance = {item['span_id']: item for item in entry['source_item_provenance']}
    audio_spans = [span for span in entry['source_spans'] if span['kind'] == 'audio']
    for audio, text, original in zip(entry['audio'], quotes, rev['segments'][sid]):
        require(audio['speaker'] == original['speaker'] and audio['speaker'] in actors
                and audio['mode'] == 'onscreen' and text == original['text']
                and (audio['start'], audio['end']) == (original['start'], original['end'])
                and 0 <= audio['start'] < audio['end'] <= 15
                and original['readable_characters'] == len(re.findall(r'[\u3400-\u9fffA-Za-z0-9]', text))
                and original['source_lines']
                and all(str(line) in rev['evidence'] for line in original['source_lines']),
                'oral_speaker_text_window_or_original_evidence_changed')
        covered = sum(max(0, min(audio['end'], beat['end']) - max(audio['start'], beat['start']))
                      for beat in entry['camera_beats'] if audio['speaker'] in beat['actors']
                      and 'face' in beat['actors'][audio['speaker']]['visible_parts'])
        require(abs(covered - (audio['end'] - audio['start'])) < 1e-8,
                'onscreen_speaker_face_must_cover_full_speaking_window')
    for span, line in zip(audio_spans, rev['segments'][sid]):
        origin = provenance[span['id']]
        require(origin.get('kind') == 'authorized_oral_revision_audio' and origin.get('revision') == revision_binding
                and origin.get('source_lines') == line['source_lines'], 'each_oral_line_original_provenance_required')
    for span in entry['source_spans']:
        if span['kind'] == 'action':
            origin = provenance[span['id']]
            require(origin.get('kind') == 'authorized_oral_revision_action' and origin.get('revision') == revision_binding,
                    'each_oral_action_must_bind_reviewed_revision')
    for before, after in zip(entry['audio'], entry['audio'][1:]):
        require(before['end'] <= after['start'], 'oral_turns_must_not_overlap')
    return entry


def prefix_imports(run, plan=None, project=PROJECT):
    run = Path(run).resolve(); plan = read(run / 'PLAN.json') if plan is None else plan
    path = checked(plan['imports'], project)
    require(path == run / 'PREFIX_IMPORTS.json', 'explicit_prefix_import_manifest_required')
    manifest = read(path)
    require(manifest.get('schema') == 'library_oral_revision_prefix/v1', 'prefix_manifest_schema_changed')
    source_final = checked(manifest['source_final_result'], project)
    require(source_final == OLD / 'FINAL_RESULT.json', 'prefix_must_be_from_selected_completed_minute')
    original = read(source_final); checked(original['file'], project)
    require(original.get('schema') == base.SERIES_SCHEMA and original.get('all_segments_new') is True
            and [r['shot_id'] for r in original['segments']] == list(IDS)
            and len(set(original['native_ids'])) == 4, 'original_final_native_identity_changed')
    rows = manifest.get('segments', [])
    require([r['shot_id'] for r in rows] == list(PREFIX), 'only_ordered_S01_S02_imports_required')
    reader = previous.for_run(OLD); result = []
    for declared, old in zip(rows, original['segments'][:2]):
        for key in ('shot_id', 'prompt_id', 'native_result', 'file', 'descriptor'):
            require(declared.get(key) == old[key], 'imported_UUID_original_file_or_descriptor_changed')
        sid = declared['shot_id']; oldrow = reader.validate_new_native(OLD / 'visual_h3_v3' / (OLD.name + '_' + sid), sid, project)
        require(declared['native_result'] == oldrow['result_binding']
                and declared['file'] == oldrow['originals']['video']['local']
                and declared['source_case'] == bind(OLD / 'segments' / sid / 'SOURCE_CASE.json')
                and declared['library_input'] == bind(OLD / 'segments' / sid / 'LIBRARY_INPUT.json'),
                'imported_native_source_records_changed')
        descriptor = read(checked(declared['descriptor'], project))
        require(descriptor['native_result'] == declared['native_result']
                and descriptor['file'] == declared['file'] and descriptor['prompt_id'] == declared['prompt_id']
                and descriptor['postprocessing'] == [], 'imported_descriptor_no_longer_original')
        nr = OLD / 'visual_h3_v3' / (OLD.name + '_' + sid); folder = nr / 'shots' / sid
        require(declared.get('native_plan') == bind(nr / 'PLAN.json')
                and declared.get('native_records') == dict(plan=bind(nr / 'PLAN.json'), request=bind(folder / 'REQUEST.json'),
                                                          history=bind(folder / 'HISTORY.json'), result=declared['native_result'])
                and declared.get('last_image') == oldrow['originals']['last']['local']
                and declared.get('library_binding') == oldrow['input_status']['library_binding'] == plan['library_binding'],
                'imported_native_records_library_or_last_image_changed')
        oldrow.update(kind='imported', descriptor=declared['descriptor'])
        result.append(oldrow)
    return dict(manifest=manifest, binding=bind(path), values=result)


def series_inputs(run, project=PROJECT):
    run, project = Path(run).resolve(), Path(project).resolve(); plan = read(run / 'PLAN.json')
    require(run.parent == project / 'data/video_generation' and plan.get('schema') == base.SERIES_SCHEMA
            and plan.get('oral_revision_contract') == VERSION and plan.get('all_segments_new') is False
            and plan.get('new_video_submissions') == 2 and plan.get('reused_native_segments') == 2
            and plan.get('publication') is False and plan.get('production_approved') is False,
            'two_imports_two_fresh_oral_revision_contract_required')
    require((plan['frames_per_segment'], plan['expected_frames'], plan['width'], plan['height'], plan['fps'], plan['steps'])
            == (362, 1448, 736, 1312, 24, 12), 'oral_revision_clock_changed')
    for key in ('config', 'authority', 'library_binding', 'binding_approval', 'library_selection', 'voice_profiles', 'script_revision'):
        checked(plan[key], project)
    revision(plan['script_revision'], project)
    imports = prefix_imports(run, plan, project)
    require([row['shot_id'] for row in plan['sources']] == list(FRESH), 'only_S03_S04_new_sources_required')
    entries = {}
    for row in plan['sources']:
        sid = row['shot_id']
        require(checked(row['source_case'], project) == run / 'segments' / sid / 'SOURCE_CASE.json'
                and Path(row['native_run']).resolve() == run / 'visual_h3_v3' / (run.name + '_' + sid),
                'fresh_source_namespace_changed')
        entries[sid] = source_entry(row['source_case'], sid, plan['script_revision'], project)
    return dict(run=run, plan=plan, plan_binding=bind(run / 'PLAN.json'), imports=imports, entries=entries)


def voice_profiles(context, prompt, plan, actors, project=PROJECT):
    binding = context.get('voice_profiles_binding')
    require(binding == plan['voice_profiles'], 'same_bound_voice_profiles_required')
    voice = read(checked(binding, project)); profiles = voice['profiles']
    require(voice.get('schema') == 'library_voice_profiles/v1' and voice.get('control_mode') == 'prompt_only'
            and voice.get('voice_reference_assets') == [] and voice.get('fixed_voice_identity_verified') is False
            and context.get('voice_profiles') == profiles and set(profiles) == set(actors),
            'whole_cast_prompt_only_voice_profiles_required')
    for cid, profile in profiles.items():
        require(set(profile) == {'actor', 'type', 'description'} and profile.get('actor') == cid
                and profile.get('type') == ('female_child' if cid == 'ye_yaner' else 'male_child')
                and isinstance(profile.get('description'), str) and profile['description'].strip()
                and not re.search(r'(?:成人|成年|成熟).{0,5}(?:声|嗓)|adult.{0,20}(?:voice|fallback)', profile['description'], re.I)
                and profile['description'] in prompt, 'complete_child_voice_description_must_reach_positive_prompt')
    return dict(binding=binding, prompt_only=True, exact_voice_identity_verified=False)


def expected_predecessor(run, sid, imports):
    if sid == 'S03':
        return imports['manifest']['segments'][1]['native_result']
    require(sid == 'S04', 'only_fresh_back_half_has_predecessor')
    return bind(Path(run) / 'visual_h3_v3' / (Path(run).name + '_S03') / 'shots/S03/RESULT.json')


def prepared_graph(native_run, sid, project=PROJECT):
    nr = Path(native_run).resolve(); plan = read(nr / 'PLAN.json'); folder = nr / 'shots' / sid
    run = checked(plan['series_plan'], project).parent; series = series_inputs(run, project); entry = series['entries'][sid]
    selection = read(checked(series['plan']['library_selection'], project))['segments'][sid]
    require(nr == run / 'visual_h3_v3' / (run.name + '_' + sid) and plan.get('schema') == base.NATIVE_SCHEMA
            and plan.get('upstream_contract') == base.INPUT_SCHEMA and plan.get('production_approved') is False
            and plan.get('publication') is False and plan.get('full_video_quality_passed') is False
            and plan.get('old_batch_resume') is False and len(plan['shots']) == 1 and plan['shots'][0]['id'] == sid,
            'fresh_oral_native_namespace_and_contract_required')
    row = plan['shots'][0]; ip = checked(plan['input'], project); context = read(ip)
    require(ip == run / 'segments' / sid / 'LIBRARY_INPUT.json' and context.get('schema') == base.INPUT_SCHEMA
            and context.get('oral_revision_contract') == VERSION and context.get('shot_id') == sid
            and context.get('source_case') == plan['source'] == bind(run / 'segments' / sid / 'SOURCE_CASE.json')
            and context.get('entry_sha256') == digest(entry) and context.get('script_revision') == series['plan']['script_revision']
            and all(context.get(key) is False for key in ('publication', 'production_approved', 'full_video_quality_passed')),
            'actual_authorized_oral_input_changed')
    script = previous.minimum_script(entry, context['script_fields'], sid, selection)
    require(previous.same_unique_cast(context['required_actor_assets'], entry['full_clip_actor_ids'])
            and context['segment_selection'] == selection and selection['mode'] == 'same_scene',
            'whole_cast_same_scene_selection_required')
    refs = context['references']; require(len(refs) == 9, 'all_nine_real_positive_references_required')
    require(context['library_binding'] == series['plan']['library_binding']
            and context['binding_approval'] == series['plan']['binding_approval'], 'same_library_and_approval_required')
    library = previous.library_reference_cards(context['library_binding'], refs[:-1], context['required_actor_assets'], selection, project)
    base.binding_confirmation(context['library_binding'], context['binding_approval'], library, project)
    resolution = context['library_resolution']
    require(resolution['status'] == 'ready' and resolution['model_dispatch_allowed'] is True
            and len(resolution['references']) == 8, 'actual_complete_asset_resolution_required')
    for actual, original in zip(refs[:-1], resolution['references']):
        require({k: actual[k] for k in original} == original, 'resolved_reference_mapping_changed')
    for actor in context['required_actor_assets']:
        require(resolution['character_descriptions'][actor] == library['cards'][actor]['card'], 'actor_feature_description_changed')
    require(resolution['environment_description'] == library['cards'][selection['place_id']]['card'], 'environment_features_changed')
    predecessor = expected_predecessor(run, sid, series['imports'])
    require(context['predecessor_result'] == predecessor, 'immediate_actual_predecessor_required')
    prior = previous.previous.native_tail(predecessor, project)
    require(refs[-1]['image'] == prior['image'] and refs[-1]['asset_id'] == 'native_tail:' + prior['native_id']
            and refs[-1]['kind'] == 'dynamic_guide' and context['first_image'] == prior['image'] == row['first_frame']
            and context['guide_kind'] == 'native_tail' and context['predecessor_receipt']['result_binding'] == predecessor,
            'previous_native_last_must_be_P9_and_frame_zero')
    review_path = checked(context['guide_review'], project); review = read(review_path)
    visible = context['guide_visible_actor_ids']; world = context['world_actor_state']; actors = set(context['required_actor_assets'])
    require(review_path == run / 'segments' / sid / 'GUIDE_STATE_REVIEW.json' and review.get('schema') == base.STATE_SCHEMA
            and review['predecessor_result'] == predecessor and review['guide_image'] == context['first_image']
            and review['world_actor_state'] == world and review['guide_visible_actor_ids'] == visible
            and review['completion_known'] is True and review['outcome_unknown'] is False
            and bool(review['reviewed_by']) and bool(review['evidence']) and len(visible) == len(set(visible))
            and set(visible) <= actors and set(review['screen_identity_map']) == set(visible) and set(world) == actors
            and all(isinstance(v, str) and v.strip() for v in [*world.values(), *review['screen_identity_map'].values()]),
            'actual_tail_review_cannot_filter_whole_cast')
    keys = ('schema', 'source_case', 'first_image', 'predecessor_result', 'guide_review', 'library_binding', 'binding_approval',
            'library_resolution', 'references', 'required_actor_assets', 'guide_visible_actor_ids', 'world_actor_state',
            'script_fields', 'compiled_prompt_utf8_sha256', 'oral_revision_contract', 'voice_profiles', 'voice_profiles_binding', 'script_revision')
    proof = {key: deepcopy(context[key]) for key in keys}; proof['input'] = plan['input']
    require(row['library_input'] == proof, 'native_frozen_oral_and_voice_proof_changed')
    root = Path(plan['config']['input_root']).resolve(); normalized = []
    require(len(row['reference_map']) == 9 and row.get('guide_map') is None, 'nine_independent_reference_maps_required')
    for i, (actual, expected) in enumerate(zip(row['reference_map'], refs)):
        require({k: actual[k] for k in expected} == expected and actual['slot'] == i and actual['tag'] == f'<Picture {i+1}>',
                'physical_reference_slot_mapping_changed')
        staged = (root / actual['input_name']).resolve(); require(staged.is_relative_to(root), 'staged_reference_scope_escaped')
        normalized.append(dict(slot=i, label=f'P{i+1}', source=expected['image'], staged=bind(staged), node_id=f'ref_{i}', input_name=actual['input_name']))
    require(row['input_name'] == row['reference_map'][-1]['input_name'], 'P9_must_be_same_scene_guide')
    graph_path = folder / 'workflow_api.json'; graph = read(graph_path)
    routes = previous.graph_pixel_routes(graph, normalized, None, project)
    prompt = graph['condition']['inputs']['prompt']; quotes = [s['text'][1:-1] for s in entry['source_spans'] if s['kind'] == 'audio']
    require(prompt == context['compiled_prompt'] and hashlib.sha256(prompt.encode()).hexdigest() == context['compiled_prompt_utf8_sha256']
            and digest(graph) == row['graph_sha256'] and base.quotes(prompt) == quotes, 'actual_oral_positive_prompt_or_quotes_changed')
    voices = voice_profiles(context, prompt, series['plan'], context['required_actor_assets'], project)
    for item in library['cards'].values():
        require(item['card']['description'] in prompt, 'versioned_asset_description_not_in_positive_prompt')
    require((graph['124']['inputs']['steps'], graph['130']['inputs']['fps'], row['timing']['native_frames'], row['timing']['requested_seconds'])
            == (12, 24, 362, 15), 'fresh_oral_native_profile_changed')
    for binding in (plan['series_plan'], plan['base_workflow'], *plan['code']):
        base.old_reference_qa.checked_code(binding, project)
    return dict(nr=nr, folder=folder, plan=plan, row=row, graph=graph, context=context, library=library, routes=routes,
                first_input=context['first_image'], source=plan['source'], script=script, entry=entry, voice_control=voices,
                binding=dict(plan=bind(nr / 'PLAN.json'), input=plan['input'], graph=bind(graph_path), series_plan=plan['series_plan'],
                             library_binding=context['library_binding'], binding_approval=context['binding_approval'], guide_review=bind(review_path)))


def _reader(run):
    ns = dict(base.__dict__)
    for name, function in list(ns.items()):
        if isinstance(function, types.FunctionType) and function.__module__ == base.__name__:
            local = types.FunctionType(function.__code__, ns, function.__name__, function.__defaults__, function.__closure__)
            local.__kwdefaults__ = function.__kwdefaults__; ns[name] = local
    ns.update(prepared_graph=prepared_graph)
    plan = read(Path(run) / 'PLAN.json')
    ns['EXPECTED_QUOTES'] = {sid: [a['text'] for a in revision(plan['script_revision'])['segments'][sid]] for sid in FRESH}
    return types.SimpleNamespace(**ns)


def validate_prepared(run, project=PROJECT):
    value = series_inputs(run, project); rows = []
    for sid in FRESH:
        nr = Path(run) / 'visual_h3_v3' / (Path(run).name + '_' + sid)
        if (nr / 'PLAN.json').exists():
            prepared = prepared_graph(nr, sid, project)
            rows.append(dict(shot_id=sid, status='actual_prepared_graph_verified', binding=prepared['binding'],
                             reference_count=9, actual_LoadImage_count=prepared['routes']['actual_LoadImage_count'], voice_control=prepared['voice_control']))
        else:
            rows.append(dict(shot_id=sid, status='native_graph_not_prepared_yet'))
    return dict(status='CPU_prepared_inspection_complete', series_plan=value['plan_binding'], imports=value['imports']['binding'],
                fresh_segments=rows, model_posts=0, GPU_calls=0, content_quality_passed=False)


def validate(run, project=PROJECT):
    value = series_inputs(run, project); run = value['run']; rows = list(value['imports']['values']); reader = _reader(run)
    for sid in FRESH:
        row = reader.validate_new_native(run / 'visual_h3_v3' / (run.name + '_' + sid), sid, project)
        descriptor_path = run / 'segments' / sid / 'FINAL_RESULT.json'; descriptor = read(descriptor_path)
        require(descriptor.get('native_result') == row['result_binding'] and descriptor.get('file') == row['originals']['video']['local']
                and descriptor.get('prompt_id') == row['native_id'] and descriptor.get('postprocessing') == []
                and descriptor.get('library_receipt') == row['library_receipt'] and descriptor.get('production_approved') is False,
                'fresh_oral_segment_descriptor_changed')
        row['descriptor'] = bind(descriptor_path); rows.append(row)
    require(len({r['native_id'] for r in rows}) == 4 and len({r['originals']['video']['local']['sha256'] for r in rows}) == 4,
            'four_distinct_original_native_outputs_required')
    output_rows = [dict(shot_id=r['id'], native_result=r['result_binding'], file=r['originals']['video']['local'], prompt_id=r['native_id'],
                        kind='import' if r['id'] in PREFIX else 'new', descriptor=r['descriptor']) for r in rows]
    inputs = dict(plan=value['plan_binding'], imports=value['plan']['imports'], segments=output_rows); final = read(run / 'FINAL_RESULT.json')
    require(final.get('schema') == base.SERIES_SCHEMA and final.get('all_segments_new') is False
            and final.get('preserved_prefix_frames') == 724 and final.get('segments') == output_rows
            and final.get('native_ids') == [r['native_id'] for r in rows] and final.get('assembly_inputs_sha256') == digest(inputs)
            and final.get('publication') is False and final.get('production_approved') is False,
            'final_movie_import_new_order_or_identity_changed')
    request = read(run / 'ASSEMBLY_REQUEST.json')
    require(request.get('inputs') == inputs and request.get('all_segments_new') is False
            and request.get('preserved_prefix_frames') == 724 and request.get('temporal_leading_trim') is False,
            'actual_assembly_import_clock_policy_changed')
    movie = checked(final['file'], project)
    require(movie.parent == run and movie.name == 'H3_ORAL_REVISION_MINUTE_736x1312.mp4', 'oral_revision_movie_path_changed')
    command, filter_text = base.media_qa.assembly_clock.assembly_command([r['file']['path'] for r in output_rows], run / 'ASSEMBLY_FILTER.txt', movie, frames=362)
    require(base.media_qa.normalize_assembly_command(request['command'], project) == base.media_qa.normalize_assembly_command(command, project)
            and (run / 'ASSEMBLY_FILTER.txt').read_text(encoding='utf-8') == filter_text, 'actual_assembly_command_or_source_order_changed')
    value.update(values=rows, final=final, final_binding=bind(run / 'FINAL_RESULT.json'), movie=movie)
    return value


def claim_asr(row, folder):
    """Do not repeat a transcriber after an interrupted/unknown claimed attempt."""
    require(row['id'] in FRESH and row['kind'] == 'new', 'ASR_only_for_fresh_back_half')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'ASR_ONCE_CLAIM.json'
    payload = dict(schema='oral_revision_single_ASR/v1', video=row['originals']['video']['local'], native_id=row['native_id'],
                   expected_quotes=row['expected_quotes'], no_blind_retry=True)
    try:
        with path.open('x', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError:
        require(read(path) == payload, 'existing_ASR_claim_input_changed')
        require((folder / 'asr/ASR_BINDING.json').is_file(), 'ASR_claimed_outcome_unknown_no_retranscription')
    return bind(path)


def preview_segment(run, sid, project=PROJECT):
    require(sid in FRESH, 'preserved_prefix_preview_not_regenerated')
    return _reader(run).preview_segment(run, sid, project)


def segment_report(row, folder, *, asr, protocol, project=PROJECT):
    """The only final-QA ASR dispatch path; preserved clips always skip it."""
    folder = Path(folder); artifacts = []; fresh = row['id'] in FRESH
    require(row['id'] in IDS and row['kind'] == ('new' if fresh else 'imported'), 'segment_import_fresh_kind_changed')
    if asr and fresh:
        artifacts.append(claim_asr(row, folder))
    report, files = base.media_qa.segment_evidence(row, folder, asr=bool(asr and fresh), project=project)
    artifacts.extend(files)
    if not fresh:
        report['asr'] = dict(status='preserved_prefix_explicit_skip', ASR_executed=False,
                             reason='original_S01_S02_retained_no_retranscription', quote_intervals=[])
    else:
        report['installed_source_protocol'] = freeze(folder / 'CPU_SOURCE_PROTOCOL.json', protocol(row['references'], project, guide=row['first_input']))
        artifacts.append(report['installed_source_protocol'])
    return report, artifacts


def qa(run, *, asr=False, project=PROJECT):
    value = validate(run, project); run = value['run']
    folder = run / 'qc_oral_revision' / value['final']['file']['sha256'] / ('with_asr' if asr else 'without_asr')
    folder.mkdir(parents=True, exist_ok=True)
    binding = dict(plan=value['plan_binding'], final=value['final_binding'], video=value['final']['file'],
                   imports=value['imports']['binding'], originals=[r['binding'] for r in value['values']],
                   all_segments_new=False, preserved_prefix_frames=724, asr_requested=asr, asr_fresh_only=True)
    freeze(folder / 'BINDING.json', binding); manifest = folder / 'FINAL_QA.json'
    if manifest.exists():
        prior = read(manifest); require(prior['binding'] == binding, 'existing_oral_QA_binding_changed')
        for item in prior['artifacts']: checked(item, project)
        return dict(status='already_complete', manifest=bind(manifest), file=value['final']['file'])
    attempt = folder / 'attempts' / uuid.uuid4().hex; attempt.mkdir(parents=True)
    code = attempt / 'qa_source.py'; code.write_bytes(Path(__file__).read_bytes())
    freeze(attempt / 'START.json', dict(binding=binding, source_code=bind(code), at_epoch=time.time()))
    try:
        segments, artifacts = [], []; protocol = previous.for_run(OLD).cpu_source_protocol
        for row in value['values']:
            sf = folder / row['id'] / row['native_id']
            segment, files = segment_report(row, sf, asr=asr, protocol=protocol, project=project)
            segments.append(segment); artifacts.extend(files)
        geometry, metadata = base.inspect_clock(value['movie'], 1448, final=True)
        artifacts.append(freeze(folder / 'FINAL_PROBE.json', metadata))
        samples = base.media_qa.sample_plan(); wanted = set(samples['timeline']) | set(samples['opening']) | set(samples['repair_boundary'])
        for join in samples['joins']: wanted.update(join['indices'])
        frames = base.extract_batch(value['movie'], wanted, folder / 'final_frames')
        artifacts.extend(dict(path=r['path'], sha256=r['sha256']) for r in frames.values()); timeline = []; regions = {}
        for offset in range(0, len(samples['timeline']), 21):
            indices = samples['timeline'][offset:offset + 21]
            contact = base.make_board([frames[i] for i in indices], folder / f'TIMELINE_{offset//21+1:02d}.jpg', columns=5)
            timeline.append(dict(indices=indices, contact=contact)); artifacts.append(contact)
        for name in ('opening', 'repair_boundary'):
            contact = base.make_board([frames[i] for i in samples[name]], folder / (name.upper() + '.jpg'), columns=5)
            regions[name] = dict(indices=samples[name], contact=contact); artifacts.append(contact)
        for i, join in enumerate(samples['joins']):
            join['contact'] = base.make_board([frames[n] for n in join['indices']], folder / f'JOIN_{i+1:02d}.jpg', columns=5)
            artifacts.append(join['contact'])
        validate(run, project)
        freeze(manifest, dict(schema='library_oral_revision_CPU_QA/v1', binding=binding, source_code=bind(code), file=value['final']['file'],
               native_ids=value['final']['native_ids'], final_clock=geometry, all_segments_new=False, preserved_prefix_frames=724,
               segments=segments, timeline=timeline, regions=regions, joins=samples['joins'], retained_prefix_retranscribed=False,
               limits=base.LIMITS, artifacts=list({r['path']: r for r in artifacts}.values()),
               content_quality_passed=False, production_approved=False, root_actual_visual_review=None))
        freeze(attempt / 'COMPLETE.json', dict(manifest=bind(manifest), at_epoch=time.time()))
        return dict(status='CPU_QA_complete', manifest=bind(manifest), file=value['final']['file'],
                    timeline=[r['contact'] for r in timeline], joins=[r['contact'] for r in samples['joins']])
    except Exception as error:
        freeze(attempt / 'ERROR.json', dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc(), no_media_retry=True))
        raise


def for_run(run):
    return types.SimpleNamespace(validate_prepared=validate_prepared, prepared_graph=prepared_graph, validate=validate,
                                 preview_segment=preview_segment, qa=qa, cpu_source_protocol=previous.for_run(OLD).cpu_source_protocol)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True); parser.add_argument('--prepared', action='store_true')
    parser.add_argument('--preview', choices=FRESH); parser.add_argument('--asr', action='store_true'); args = parser.parse_args(argv)
    result = validate_prepared(args.run) if args.prepared else preview_segment(args.run, args.preview) if args.preview else qa(args.run, asr=args.asr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
