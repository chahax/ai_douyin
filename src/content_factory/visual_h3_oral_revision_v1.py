"""Two explicitly revised shots after two authenticated unchanged originals.

This adapter never rewrites the completed run, disguises imports as new jobs,
or retries an unknown native request. Character voices are prompt instructions,
not an unverified audio-reference capability or a voice-identity guarantee.
"""
from copy import deepcopy
from pathlib import Path
import subprocess
import types

from . import visual_h3_library_continuation_v1 as continuation

base = continuation.base
VERSION = 'library_oral_revision/v1'
PREFIX = 'library_oral_revision_prefix/v1'
VOICE = 'library_voice_profiles/v1'
REVISION = 'library_oral_script_revision/v1'
IDS, NEW, IMPORTED = base.IDS, ('S03', 'S04'), ('S01', 'S02')
CHILDREN = ('ye_nan', 'ye_xijue', 'ye_dong', 'ye_yaner')
ACTIVE = {'S03': ('ye_xijue', 'ye_dong'), 'S04': ('ye_nan', 'ye_yaner')}
read, bind, freeze = base.read, base.bind, base.freeze
PROOF_KEYS = ('schema', 'source_case', 'first_image', 'predecessor_result', 'guide_review',
    'library_binding', 'binding_approval', 'library_resolution', 'references',
    'required_actor_assets', 'guide_visible_actor_ids', 'world_actor_state', 'script_fields',
    'compiled_prompt_utf8_sha256', 'oral_revision_contract', 'voice_profiles',
    'voice_profiles_binding', 'script_revision')


def _prefix(final_binding):
    """Authenticate actual original files and their input/history evidence only."""
    path = Path(base.core.check(final_binding)); final = read(path); old = path.parent
    if (final.get('schema') != base.SERIES or final.get('all_segments_new') is not True
            or [r.get('shot_id') for r in final.get('segments', [])] != list(IDS)
            or len(set(final.get('native_ids', []))) != 4):
        raise ValueError('completed_four_segment_prefix_source_required')
    base.core.check(final['file'])
    original = continuation.for_run(old); rows = []
    for sid, selected in zip(IMPORTED, final['segments'][:2]):
        nr, native_plan, row = original._load(old, sid, current=False)
        result_binding = bind(nr/'shots'/sid/'RESULT.json')
        proof = original.verify_native(result_binding); result = proof['result']
        descriptor_binding = bind(old/'segments'/sid/'FINAL_RESULT.json')
        descriptor = read(descriptor_binding['path']); video = {k:result['files']['video'][k] for k in ('path', 'sha256')}
        if (selected.get('native_result') != result_binding or selected.get('descriptor') != descriptor_binding
                or selected.get('prompt_id') != result['prompt_id'] or selected.get('file') != video
                or descriptor.get('native_result') != result_binding or descriptor.get('file') != video
                or descriptor.get('prompt_id') != result['prompt_id'] or descriptor.get('postprocessing') != []):
            raise ValueError('selected_prefix_original_id_file_or_descriptor_changed')
        input_binding = native_plan['input']; context = read(base.core.check(input_binding))
        # Validate the original resolved images/descriptions and exact physical slots;
        # no new visual compatibility, generated identity, or content-quality gate.
        original.validate_input(input_binding)
        for ref in context['references']:
            base.core.check(ref['image'])
        rows.append(dict(shot_id=sid, prompt_id=result['prompt_id'], native_result=result_binding,
            file=video, descriptor=descriptor_binding, source_case=native_plan['source'],
            library_input=input_binding, native_plan=bind(nr/'PLAN.json'),
            native_records=proof['records'], library_binding=context['library_binding'],
            last_image=proof['last_image']))
    return dict(schema=PREFIX, source_final_result=final_binding, segments=rows,
        identity_compatibility_gate=False, originals_unchanged=True, preserved_prefix_frames=724)


def verify_imports(run):
    plan = read(Path(run)/'PLAN.json'); receipt = read(base.core.check(plan['imports']))
    actual = _prefix(receipt['source_final_result'])
    if receipt != actual or any(r['library_binding'] != plan['library_binding'] for r in actual['segments']):
        raise ValueError('frozen_original_prefix_or_exact_library_binding_changed')
    return actual


def voice_profiles(binding):
    value = read(base.core.check(binding)); profiles = value.get('profiles', {})
    if value.get('schema') != VOICE or set(profiles) != set(CHILDREN):
        raise ValueError('four_explicit_character_voice_profiles_required')
    for cid, p in profiles.items():
        kind = 'female_child' if cid == 'ye_yaner' else 'male_child'
        if (not isinstance(p, dict) or p.get('actor') != cid or p.get('type') != kind
                or not isinstance(p.get('description'), str) or not p['description'].strip()
                or base.core.QUOTE.findall(p['description'])):
            raise ValueError('explicit_matched_child_voice_actor_type_description_required')
    return deepcopy(profiles)


def revision_binding(binding):
    value = read(base.core.check(binding))
    if (value.get('schema') != REVISION or value.get('fresh_shot_ids') != list(NEW)
            or value.get('publication') is not False):
        raise ValueError('explicit_two_shot_oral_revision_authority_required')
    return binding


def validate_entry(entry, revision):
    continuation.source_shot(entry)
    if (entry.get('shot_id') not in NEW or set(entry.get('full_clip_actor_ids', [])) != set(CHILDREN)
            or len(entry.get('full_clip_actor_ids', [])) != 4 or entry.get('place_id') != 'children_room'
            or entry.get('script_revision') != revision or not entry.get('audio')
            or any(a['mode'] != 'onscreen' or a['speaker'] not in CHILDREN for a in entry['audio'])):
        raise ValueError('revised_children_room_full_cast_onscreen_dialogue_and_authority_required')
    prior_end = -1
    for audio in entry['audio']:
        if audio['start'] < prior_end:
            raise ValueError('oral_lines_have_distinct_nonoverlapping_time_windows')
        prior_end = audio['end']; cursor = audio['start']
        for beat in entry['camera_beats']:
            actor = beat['actors'].get(audio['speaker'], {})
            if (beat['start'] <= cursor < beat['end'] and 'face' in actor.get('visible_parts', [])):
                cursor = min(audio['end'], beat['end'])
            if cursor >= audio['end']: break
        if cursor < audio['end']:
            raise ValueError('speaker_face_must_cover_entire_onscreen_audio_window')
    return entry


def selection_for(sid, selection):
    selected = continuation._selection(selection, list(CHILDREN))
    expected = {c:['front', 'left_oblique'] if c in ACTIVE[sid] else ['front'] for c in CHILDREN}
    if (selected.get('mode', 'same_scene') != 'same_scene' or selected['place_id'] != 'children_room'
            or selected['actor_views'] != expected or selected['place_views'] != ['front', 'side']):
        raise ValueError('explicit_four_front_two_active_side_two_room_plus_actual_tail_required')
    return selected


def prepare(run, spec):
    run = Path(run).resolve()
    if set(spec.get('sources', {})) != set(NEW) or set(spec.get('segment_selections', {})) != set(NEW):
        raise ValueError('only_two_revised_sources_and_selections_required')
    prefix = _prefix(spec['prefix_final_result'])
    if any(r['library_binding'] != spec['library_binding'] for r in prefix['segments']):
        raise ValueError('exact_original_library_binding_required')
    voice_profiles(spec['voice_profiles']); revision_binding(spec['script_revision'])
    if spec.get('source_builder') is not None: base.core.check(spec['source_builder'])
    entries, selections = {}, {}
    for sid in NEW:
        values = base.core._entries(spec['sources'][sid])
        if len(values) != 1 or values[0].get('shot_id') != sid:
            raise ValueError('one_exact_source_entry_required')
        entries[sid] = validate_entry(values[0], spec['script_revision'])
        selections[sid] = selection_for(sid, spec['segment_selections'][sid])
        resolution = continuation.resolve_library(spec['library_binding'], spec['binding_approval'], list(CHILDREN), selections[sid])
        if resolution.get('status') != 'ready':
            return base.missing_notice(run, dict(shot_id=sid, library_notice=resolution))
        if len(resolution['references']) != 8:
            raise ValueError('eight_explicit_library_images_required_before_actual_tail')
    cfg = deepcopy(spec['config']); cfg['runs_root'] = str(run/'visual_h3_v3')
    freeze(run/'H3_CONFIG.json', cfg); freeze(run/'USER_AUTHORIZATION.json', spec['authorization'])
    freeze(run/'PREFIX_IMPORTS.json', prefix); freeze(run/'LIBRARY_SELECTION.json', dict(segments=selections))
    rows = []
    for sid in NEW:
        freeze(base.part(run, sid)/'SOURCE_CASE.json', dict(schema=base.core.SCHEMA, shots=[entries[sid]]))
        rows.append(dict(shot_id=sid, source_case=bind(base.part(run, sid)/'SOURCE_CASE.json'), native_run=str(base.native_run(run, sid))))
    freeze(run/'PLAN.json', dict(schema=base.SERIES, oral_revision_contract=VERSION, sources=rows,
        imports=bind(run/'PREFIX_IMPORTS.json'), config=bind(run/'H3_CONFIG.json'), authority=bind(run/'USER_AUTHORIZATION.json'),
        library_binding=spec['library_binding'], binding_approval=spec['binding_approval'],
        library_selection=bind(run/'LIBRARY_SELECTION.json'), voice_profiles=spec['voice_profiles'], script_revision=spec['script_revision'],
        source_builder=spec.get('source_builder'),
        frames_per_segment=362, expected_frames=1448, width=736, height=1312, fps=24, steps=12,
        new_video_submissions=2, reused_native_segments=2, all_segments_new=False, preserved_prefix_frames=724,
        publication=False, production_approved=False))
    return dict(status='source_prepared_no_post', plan=bind(run/'PLAN.json'), model_posts=0)


def for_run(run):
    """Bind isolated sealed transport functions to the explicit revised policy."""
    run = Path(run).resolve(); ns = dict(base.__dict__)
    for name, f in list(ns.items()):
        if isinstance(f, types.FunctionType) and f.__module__ == base.__name__:
            cloned = types.FunctionType(f.__code__, ns, f.__name__, f.__defaults__, f.__closure__)
            cloned.__kwdefaults__ = f.__kwdefaults__; ns[name] = cloned
    text_policy = continuation.for_run(run)
    def same(value):
        if Path(value).resolve() != run: raise ValueError('oral_adapter_bound_to_one_run')
    def plan_value():
        p = read(run/'PLAN.json')
        if (p.get('oral_revision_contract') != VERSION or p.get('all_segments_new') is not False
                or p.get('new_video_submissions') != 2):
            raise ValueError('explicit_two_new_two_imported_oral_plan_required')
        return p
    def entry_value(sid):
        if sid not in NEW: raise ValueError('imported_original_is_never_a_new_job')
        p = plan_value(); revision_binding(p['script_revision'])
        return validate_entry(base.core._entries(bind(base.part(run, sid)/'SOURCE_CASE.json'))[0], p['script_revision'])
    def settings(sid):
        p = plan_value(); return selection_for(sid, read(base.core.check(p['library_selection']))['segments'][sid])
    def library_value(value, entry):
        same(value); p = plan_value()
        return continuation.resolve_library(p['library_binding'], p['binding_approval'], list(CHILDREN), settings(entry['shot_id']))
    def predecessor(value, sid):
        same(value); entry_value(sid); prefix = verify_imports(run)
        if sid == 'S03': return prefix['segments'][1]['native_result']
        path = base.native_run(run, 'S03')/'shots'/'S03'/'RESULT.json'
        if not path.exists(): return None
        native_plan = read(path.parents[2]/'PLAN.json')
        if native_plan.get('series_plan') != bind(run/'PLAN.json'):
            raise ValueError('S04_requires_this_revision_S03_original')
        return bind(path)
    def review_request(value, sid):
        same(value); entry = entry_value(sid); prev = predecessor(run, sid)
        if prev is None: return dict(status='upstream_native_tail_required', predecessor_shot_id='S03', model_posts=0)
        # Imported S02 has a separate scene guide; use its original policy to
        # authenticate it, not the new same-scene-only graph validator.
        proof = continuation.for_run(Path(prev['path']).parents[4]).verify_native(prev) if sid == 'S03' else ns['verify_native'](prev)
        request = dict(schema=base.REVIEW+'_request', shot_id=sid, predecessor_result=prev,
            predecessor_receipt=proof, guide_image=proof['last_image'], guide_kind='native_tail', generation_receipt=proof,
            required_actor_assets=list(CHILDREN), opening_actor_ids=list(entry['camera_beats'][0]['actors']),
            required_review_file=str(base.part(run, sid)/'GUIDE_STATE_REVIEW.json'), guide_visibility_does_not_filter_required_assets=True)
        freeze(base.part(run, sid)/'GUIDE_STATE_REQUEST.json', request)
        return dict(status='actual_guide_state_review_required', request=bind(base.part(run, sid)/'GUIDE_STATE_REQUEST.json'), model_posts=0)
    def input_value(value, sid):
        same(value); p = plan_value(); entry = entry_value(sid); lib = library_value(run, entry)
        if lib.get('status') != 'ready': return base.missing_notice(run, dict(shot_id=sid, library_notice=lib))
        req = review_request(run, sid)
        if req['status'] != 'actual_guide_state_review_required': return req
        q = read(base.core.check(req['request'])); path = base.part(run, sid)/'GUIDE_STATE_REVIEW.json'
        if not path.exists(): return req
        review = read(path); visible = review.get('guide_visible_actor_ids', []); world = review.get('world_actor_state', {}); screen = review.get('screen_identity_map', {})
        if (review.get('schema') != base.REVIEW or review.get('shot_id') != sid
                or review.get('predecessor_result') != q['predecessor_result'] or review.get('guide_image') != q['guide_image']
                or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
                or not review.get('reviewed_by') or not base._strings(review.get('evidence'))
                or not isinstance(visible, list) or len(visible) != len(set(visible)) or not set(visible) <= set(CHILDREN)
                or set(world) != set(CHILDREN) or set(screen) != set(visible)
                or any(not isinstance(v, str) or not v.strip() for v in [*world.values(), *screen.values()])):
            raise ValueError('actual_tail_actor_subset_and_full_world_state_required')
        refs = [dict(r, slot=i, tag=f'<Picture {i+1}>') for i, r in enumerate(lib['references'])]
        refs.append(dict(slot=8, tag='<Picture 9>', kind='dynamic_guide', entity_id='current_scene_state',
            asset_id='native_tail:'+q['predecessor_receipt']['result']['prompt_id'], version=1, view='guide_start', image=q['guide_image']))
        if len(refs) != 9: raise ValueError('nine_actual_images_required')
        fields = text_policy.script_fields(entry, settings(sid)); profiles = voice_profiles(p['voice_profiles'])
        text = text_policy.render(entry, review, lib, refs, fields)
        voices = ['人物发音内容为各署名台词；其余文字是画面与表演说明。',
            '本段发声均为画面中署名人物自然说出口的普通话，动作、神情与相互对话交织。']
        voices += [entry['character_names'][c]+'的声音：'+profiles[c]['description'] for c in CHILDREN]
        text = text.replace('各人物的普通话声线在本段及续段中保持一致。', '\n'.join(voices)+'\n各角色保持自己对应的童声与说话习惯。')
        for cid in CHILDREN:
            text = text.replace(entry['character_names'][cid]+'本人开口说',
                entry['character_names'][cid]+'本人以对应的童声（'+profiles[cid]['description']+'）开口说')
        if (base.core.QUOTE.findall(text) != base.core.QUOTE.findall(base.core.compile_prompt(entry)['compiled_prompt'])
                or not all(profile['description'] in text for profile in profiles.values())
                or voices[0] not in text):
            raise ValueError('only_exact_dialogue_quotes_and_actual_voice_profiles_required')
        return dict(schema=base.CONTRACT, oral_revision_contract=VERSION, shot_id=sid,
            source_case=bind(base.part(run, sid)/'SOURCE_CASE.json'), entry_sha256=base.core.digest(entry),
            first_image=q['guide_image'], predecessor_result=q['predecessor_result'], predecessor_receipt=q['predecessor_receipt'],
            generation_receipt=q['generation_receipt'], guide_kind='native_tail', guide_review=bind(path),
            segment_selection=settings(sid), library_binding=p['library_binding'], binding_approval=p['binding_approval'],
            library_resolution=lib, references=refs, required_actor_assets=list(CHILDREN), guide_visible_actor_ids=visible,
            world_actor_state=world, script_fields=fields, voice_profiles=profiles, voice_profiles_binding=p['voice_profiles'],
            script_revision=p['script_revision'], compiled_prompt=text, compiled_prompt_utf8_sha256=base.core.sha(text),
            full_video_quality_passed=False, production_approved=False, publication=False, conditioning_mode=base.CONDITIONING)
    def validate_input(binding):
        path = Path(base.core.check(binding)); sid = path.parent.name; data = read(path)
        if path != base.part(run, sid)/'LIBRARY_INPUT.json' or input_value(run, sid) != data:
            raise ValueError('oral_source_voice_description_or_pixels_changed')
        proof = {k:deepcopy(data[k]) for k in PROOF_KEYS}; proof['input'] = binding
        return dict(data, entry=entry_value(sid), proof=proof, quality_passed=False)
    original_prepare = ns['prepare_video']
    def prepare_video(value, sid, *, code_files=()):
        same(value); entry_value(sid)
        builder = plan_value().get('source_builder')
        source_code = (base.core.check(builder),) if builder is not None else ()
        return original_prepare(value, sid, code_files=(__file__, continuation.__file__, *source_code, *code_files))
    ns.update(NEW=NEW, input_value=input_value, library_value=library_value, _predecessor=predecessor,
        review_request=review_request, validate_input=validate_input, prepare_video=prepare_video,
        core=types.SimpleNamespace(**dict(base.core.__dict__, handoff_snapshot=continuation.source_snapshot)))
    def assemble(value):
        same(value); return assemble_run(run, types.SimpleNamespace(**ns))
    ns.update(assemble=assemble, verify_imports=verify_imports, entry_value=entry_value, settings=settings,
        voice_profiles=voice_profiles, revision_version=VERSION, PROOF_KEYS=PROOF_KEYS)
    return types.SimpleNamespace(**ns)


def assemble_run(run, flow):
    run = Path(run); p = read(run/'PLAN.json')
    with base.native.jobs.run_lock(run, 'ASSEMBLY.lock'):
        prefix = verify_imports(run)
        rows = [{k:r[k] for k in ('shot_id', 'native_result', 'file', 'prompt_id', 'descriptor')} | {'kind':'import'} for r in prefix['segments']]
        for sid in NEW:
            descriptor_binding = bind(base.part(run, sid)/'FINAL_RESULT.json'); d = read(descriptor_binding['path'])
            expected_result = bind(base.native_run(run, sid)/'shots'/sid/'RESULT.json')
            if (d.get('native_result') != expected_result
                    or d.get('library_receipt') != bind(base.native_run(run, sid)/'LIBRARY_RESULT.json')
                    or d.get('production_approved') is not False):
                raise ValueError('new_descriptor_must_bind_this_run_exact_native_original')
            proof = flow.verify_native(d['native_result']); flow._load(run, sid); result = proof['result']
            if d.get('prompt_id') != result['prompt_id'] or d.get('file') != {k:result['files']['video'][k] for k in ('path','sha256')} or d.get('postprocessing') != []:
                raise ValueError('new_original_descriptor_changed')
            rows.append(dict(shot_id=sid, native_result=d['native_result'], file=d['file'], prompt_id=result['prompt_id'], kind='new', descriptor=descriptor_binding))
        if len({r['prompt_id'] for r in rows}) != 4 or len({r['file']['sha256'] for r in rows}) != 4:
            raise ValueError('four_distinct_ordered_originals_required')
        inputs = dict(plan=bind(run/'PLAN.json'), imports=p['imports'], segments=rows); digest = base.core.digest(inputs)
        final = run/'FINAL_RESULT.json'; out = run/'H3_ORAL_REVISION_MINUTE_736x1312.mp4'
        if final.exists():
            previous = read(final); base.core.check(previous['file'])
            if previous.get('assembly_inputs_sha256') != digest: raise ValueError('frozen_assembly_sources_changed')
            return previous
        if out.exists(): raise ValueError('unreceipted_final_movie_preserved')
        adjustments = [base.clock_input(r['file']['path'], r['file']['sha256'], frames=362, width=736, height=1312) for r in rows]
        filters = run/'ASSEMBLY_FILTER.txt'; command, text = base.clock.assembly_command([r['file']['path'] for r in rows], filters, out, frames=362)
        filters.write_text(text, encoding='utf-8')
        freeze(run/'ASSEMBLY_REQUEST.json', dict(inputs=inputs, adjustments=adjustments, command=command,
            all_segments_new=False, preserved_prefix_frames=724, temporal_leading_trim=False))
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(completed.stderr, encoding='utf-8'); completed.check_returncode()
        timing = base.clock.verify_clock(base.clock._probe(out, count=True), frames=1448, width=736, height=1312)
        verify_imports(run)
        for r in rows: base.core.check(r['native_result']); base.core.check(r['file'])
        value = dict(schema=base.SERIES, oral_revision_contract=VERSION, file=bind(out), segments=rows,
            native_ids=[r['prompt_id'] for r in rows], clock=timing, assembly_inputs_sha256=digest,
            all_segments_new=False, preserved_prefix_frames=724, publication=False, production_approved=False)
        freeze(final, value); return value
