"""New, explicitly sourced minutes after a completed library-bound minute.

The sealed v2 producer is reused through isolated function globals. Its files,
old native requests, unknown results and selections are never rewritten.
"""
from copy import deepcopy
from pathlib import Path
import re
import types

from . import visual_h3_library_minute_v2 as base

VERSION = 'library_minute_continuation/v1'
ORIGIN = 'library_continuation_origin/v1'
SCENE_GUIDE = 'library_generated_scene_guide/v1'
SOURCE_ROLE = 'script_plan_only_actual_start_bound_in_LIBRARY_INPUT'
IDS = base.IDS
read, bind, freeze = base.read, base.bind, base.freeze
SOURCE_TOOLS = tuple(Path(__file__).resolve().parents[2]/'scripts'/name for name in (
    'prepare_h3_continuation_sources.py','prepare_h3_continuation_scene_stage.py'))


def _actors(entry):
    return base.core.validate_entry(entry)['visible_actors']


def source_shot(entry):
    """Only compile source facts; a planning preview is never a generated guide."""
    req = base.core.validate_entry(entry)
    if not req['source_coverage_complete']:
        raise ValueError('source_plan_must_cover_exact_source_without_action_audio_misclassification')
    if (entry.get('source_entry_role') != SOURCE_ROLE
            or entry.get('planning_preview_image') != entry['actual_first_image']):
        raise ValueError('explicit_source_only_planning_preview_required')
    shot = dict(id=entry['shot_id'],source_entry_sha256=base.core.digest(entry),start=0,end=entry['duration'],
        visible_cast=req['visible_actors'],visual_prompt=''.join(s['text'] for s in entry['source_spans'] if s['kind']=='action'),
        audio=[dict(speaker=a['speaker'],mode=a['mode'],text=req['quotes'][a['quote_index']].group()[1:-1]) for a in entry['audio']],
        camera_beats=deepcopy(entry['camera_beats']),references=[dict(entity_id=c,kind='character',**entry['canonical_characters'][c]) for c in req['visible_actors']])
    shot['binding_sha256']=base.core.digest(shot)
    return shot


def source_snapshot(binding, config):
    return None, None, dict(shots=[source_shot(e) for e in base.core._entries(binding)])


def _selection(value, actors):
    """Views are an explicit decision, never an implicit capacity truncation."""
    value = deepcopy(value)
    if 'actor_views' not in value and 'angle_by_actor' in value:
        value['actor_views'] = {c: ['front', a] for c, a in value['angle_by_actor'].items()}
    views = value.get('actor_views', {})
    if set(views) != set(actors):
        raise ValueError('selection_must_cover_exact_whole_segment_cast')
    for cid, selected in views.items():
        if (not isinstance(selected, list) or not selected or selected[0] != 'front'
                or len(selected) != len(set(selected)) or any(not isinstance(v, str) or not v for v in selected)):
            raise ValueError('explicit_distinct_actor_views_beginning_with_front_required')
        if len(selected) == 1:
            decision = value.get('capacity_decision', {})
            if (decision.get('front_only_actor_ids') is None or cid not in decision['front_only_actor_ids']
                    or not isinstance(decision.get('reason'), str) or not decision['reason'].strip()):
                raise ValueError('front_only_requires_explicit_capacity_decision')
    if (not value.get('place_id') or not isinstance(value.get('place_views'), list)
            or not value['place_views'] or len(value['place_views']) != len(set(value['place_views']))):
        raise ValueError('explicit_segment_place_and_distinct_views_required')
    if not isinstance(value.get('place_name'), str) or not value['place_name'].strip():
        raise ValueError('explicit_segment_place_name_required')
    if type(value.get('include_predecessor_context_reference', False)) is not bool:
        raise ValueError('explicit_context_reference_policy_required')
    mode = value.get('mode', 'same_scene')
    if mode not in ('same_scene', 'scene_cut'):
        raise ValueError('explicit_same_scene_or_scene_cut_required')
    if mode == 'scene_cut':
        if not value.get('scene_guide_path') or value.get('include_predecessor_context_reference') is not True:
            raise ValueError('scene_cut_needs_generated_start_and_actual_previous_tail_context')
    elif value.get('scene_guide_path') or value.get('include_predecessor_context_reference'):
        raise ValueError('same_scene_uses_only_actual_previous_tail_as_guide')
    return value


def resolve_library(binding, approval_binding, actors, selection):
    """Resolve only the declared views, preserving card and registry provenance."""
    try:
        selection = _selection(selection, actors)
        path, index, cards = base.features._load_index(binding)
        approval = read(base.core.check(approval_binding))
        entities = set(index['characters']) | set(index['places'])
        if (approval.get('schema') != base.features.APPROVAL_SCHEMA
                or approval.get('binding_index') != bind(path)
                or not approval.get('approved_by') or not base._strings(approval.get('evidence'))
                or set(approval.get('confirmed_entities', [])) != entities
                or approval.get('production_approved') is not False):
            raise ValueError('project_binding_confirmation_changed_or_missing')
        allowed = set()
        for a in approval.get('allow_candidate_assets', []):
            if (not isinstance(a, dict) or set(a) != {'asset_id', 'version', 'sha256'}
                    or type(a.get('version')) is not int or a['version'] < 1
                    or not re.fullmatch('[0-9a-f]{64}', str(a.get('sha256')))):
                raise ValueError('exact_candidate_asset_allowance_required')
            allowed.add((a['asset_id'], a['version'], a['sha256']))
        requests = [(c, 'character', v) for c in actors for v in selection['actor_views'][c]]
        requests += [(selection['place_id'], 'place', v) for v in selection['place_views']]
        # The independent dynamic guide always reserves one of the nine slots.
        if len(requests) > 8:
            raise ValueError('required_references_exceed_capacity_no_truncation')
        refs, descriptions = [], {}
        for eid, kind, view in requests:
            category = 'characters' if kind == 'character' else 'places'
            if eid not in cards[category]:
                raise ValueError(f'{kind}_binding_missing:{eid}')
            card = cards[category][eid]
            if view not in card['images']:
                raise ValueError(f'bound_view_image_missing:{eid}:{view}')
            pinned = card['images'][view]
            row, _ = base.features._asset(index['library'], index['book_id'], eid, kind, view, pinned)
            if row['status'] != 'reviewed' and (pinned['asset_id'], pinned['version'], pinned['image']['sha256']) not in allowed:
                raise ValueError(f'candidate_view_not_confirmed:{eid}:{view}')
            refs.append(dict(entity_id=eid, actor_id=eid if kind == 'character' else None,
                feature_card=index[category][eid]['feature_card'],
                **{k: pinned[k] for k in ('kind', 'view', 'asset_id', 'version', 'design_version', 'identity_group', 'image')}))
            if kind == 'character': descriptions[eid] = card
        if len({r['image']['sha256'] for r in refs}) != len(refs):
            raise ValueError('distinct_declared_reference_pixels_required')
        return dict(status='ready', binding_index=bind(path), binding_approval=approval_binding,
            references=refs, character_descriptions=descriptions,
            environment_description=cards['places'][selection['place_id']],
            source_library=index['library'], book_id=index['book_id'],
            selected_actor_views=selection['actor_views'], capacity_decision=selection.get('capacity_decision'),
            model_dispatch_allowed=True, production_approved=False, new_model_calls=0)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return dict(status='missing_notice', notices=[dict(code=str(e), actor_ids=list(actors),
            place_id=selection.get('place_id') if isinstance(selection,dict) else None, action='补齐对应素材、描述、版本绑定或明确容量选择；不得静默丢图。')],
            model_dispatch_allowed=False, new_model_calls=0)


def verify_origin(value):
    """Authenticate the last selected original of a real completed preceding film."""
    if value.get('schema') != ORIGIN:
        raise ValueError('explicit_completed_minute_origin_required')
    proof = base.verify_native(value['native_result'])
    final = read(base.core.check(value['preceding_final_result']))
    if (final.get('schema')!=base.SERIES or final.get('all_segments_new') is not True
            or [s.get('shot_id') for s in final.get('segments',[])]!=list(IDS)
            or len(set(final.get('native_ids',[])))!=4
            or final['segments'][-1].get('native_result') != value['native_result']
            or final.get('native_ids', [None])[-1] != proof['result']['prompt_id']
            or final['segments'][-1].get('prompt_id') != proof['result']['prompt_id']
            or final['segments'][-1].get('file') != {k:proof['result']['files']['video'][k] for k in ('path','sha256')}):
        raise ValueError('origin_must_be_last_selected_native_of_preceding_movie')
    base.core.check(final['file'])
    return proof


def prepare(run, spec):
    run = Path(run).resolve(); run.mkdir(parents=True, exist_ok=True)
    if set(spec['sources']) != set(IDS) or any(k in spec for k in ('prefix', 'prefix_results', 'imports')):
        raise ValueError('four_explicit_fresh_continuation_sources_required')
    verify_origin(spec['continuation_origin'])
    entries = {s: base.core._entries(spec['sources'][s]) for s in IDS}
    selections = spec['segment_selections']
    if set(selections) != set(IDS): raise ValueError('per_segment_selection_required')
    checked = {}
    for sid in IDS:
        if len(entries[sid]) != 1 or entries[sid][0].get('shot_id') != sid or 'reanchor' in entries[sid][0]:
            raise ValueError('one_exact_new_source_per_segment_required')
        entry = entries[sid][0]; actors = _actors(entry)
        source_shot(entry)
        try: selected = _selection(selections[sid], actors)
        except ValueError as e: return base.missing_notice(run, dict(shot_id=sid, code=str(e)))
        resolved = resolve_library(spec['library_binding'], spec['binding_approval'], actors, selected)
        if resolved.get('status') != 'ready':
            return base.missing_notice(run, dict(shot_id=sid, library_notice=resolved))
        # Same-scene tail or cross-scene context uses the ninth reference slot.
        # A cross-scene generated start is separately encoded by AddGuide only.
        if len(resolved['references']) + 1 > 9:
            return base.missing_notice(run, dict(shot_id=sid, code='context_and_guide_exceed_capacity_no_truncation'))
        if selected.get('include_predecessor_context_reference') and not selected.get('scene_guide_path'):
            raise ValueError('extra_tail_context_only_needed_for_explicit_scene_guide')
        checked[sid] = selected
    cfg = deepcopy(spec['config']); cfg['runs_root'] = str(run/'visual_h3_v3')
    freeze(run/'H3_CONFIG.json', cfg); freeze(run/'USER_AUTHORIZATION.json', spec['authorization'])
    freeze(run/'LIBRARY_SELECTION.json', dict(segments=checked))
    freeze(run/'CONTINUATION_ORIGIN.json', spec['continuation_origin'])
    rows = []
    for sid in IDS:
        freeze(base.part(run, sid)/'SOURCE_CASE.json', dict(schema=base.core.SCHEMA, shots=entries[sid]))
        rows.append(dict(shot_id=sid, source_case=bind(base.part(run, sid)/'SOURCE_CASE.json'), native_run=str(base.native_run(run, sid))))
    freeze(run/'PLAN.json', dict(schema=base.SERIES, continuation_contract=VERSION, sources=rows,
        config=bind(run/'H3_CONFIG.json'), authority=bind(run/'USER_AUTHORIZATION.json'),
        library_binding=spec['library_binding'], binding_approval=spec['binding_approval'],
        library_selection=bind(run/'LIBRARY_SELECTION.json'), continuation_origin=bind(run/'CONTINUATION_ORIGIN.json'),
        frames_per_segment=362, expected_frames=1448, width=736, height=1312, fps=24, steps=12,
        new_video_submissions=4, all_segments_new=True, publication=False, production_approved=False))
    return dict(status='source_prepared_no_post', plan=bind(run/'PLAN.json'), model_posts=0)


def generated_scene_guide(run, path, expected_job_id=None):
    run = Path(run).resolve(); path = Path(path).resolve()
    if not path.is_relative_to(run): raise ValueError('scene_guide_receipt_must_belong_to_new_run')
    if not path.exists(): return None
    v = read(path)
    if (v.get('schema') != SCENE_GUIDE or v.get('completion_known') is not True
            or v.get('outcome_unknown') is not False or set(v.get('generation_records', {})) != {'plan','request','history','result'}):
        raise ValueError('completed_scene_guide_native_records_required')
    image = Path(base.core.check(v['image'])); records = v['generation_records']
    for b in records.values(): base.core.check(b)
    request, history = read(base.core.check(records['request'])), read(base.core.check(records['history']))
    pid = v.get('native_prompt_id'); event = history.get(pid, {}); hp = event.get('prompt', [])
    if (not isinstance(pid, str) or len(hp) < 3 or hp[1] != pid or request.get('prompt') != hp[2]
            or event.get('status', {}).get('completed') is not True or event['status'].get('status_str') != 'success'):
        raise ValueError('actual_scene_guide_success_history_required')
    output = v.get('native_output', {}); node, index = output.get('node_id'), output.get('index')
    images = event.get('outputs', {}).get(node, {}).get('images', [])
    if type(index) is not int or not 0 <= index < len(images) or images[index].get('type') != 'output':
        raise ValueError('actual_scene_guide_output_locator_required')
    cfg = read(base.core.check(read(run/'PLAN.json')['config']))
    source = base.native.bound(cfg['output_root'], (Path(images[index].get('subfolder', ''))/images[index]['filename']).as_posix())
    if (Path(output.get('source_path', '')).resolve() != source
            or not image.is_relative_to(run) or bind(source) != v.get('source_image') or bind(source)['sha256'] != v['image']['sha256']):
        raise ValueError('scene_guide_must_be_actual_output_of_this_run')
    plan_path=Path(base.core.check(records['plan']));plan=read(plan_path)
    expected_job_id=expected_job_id or run.name+'_children_start'
    result_path=Path(base.core.check(records['result']));result=read(result_path)
    if (not plan_path.is_relative_to(run) or result_path.parent!=plan_path.parent
            or plan.get('version')!='visual_image_jobs/v3' or plan.get('job_id')!=expected_job_id
            or result.get('version')!=plan['version'] or result.get('job_id')!=expected_job_id
            or result.get('prompt_id')!=pid or result.get('technical_status')!='saved'
            or result.get('production_approved') is not False
            or plan.get('graph_sha256')!=base.core.digest(request['prompt'])
            or result.get('graph_sha256')!=plan['graph_sha256']
            or result.get('inputs_sha256')!=base.core.digest(plan.get('inputs',[]))):
        raise ValueError('scene_guide_image_job_identity_plan_graph_and_RESULT_required')
    jobcfg=plan.get('config',{})
    if Path(jobcfg.get('output_root','')).resolve()!=Path(cfg['output_root']).resolve():
        raise ValueError('scene_guide_same_local_output_root_required')
    prefix=Path(jobcfg.get('allowed_prefix',''))
    if not prefix.parts or prefix.is_absolute() or '..' in prefix.parts:
        raise ValueError('exact_relative_scene_job_prefix_required')
    scope=(Path(cfg['output_root'])/prefix/expected_job_id).resolve()
    graph_node=request['prompt'].get(node,{})
    save_prefix=Path(graph_node.get('inputs',{}).get('filename_prefix',''))
    if (graph_node.get('class_type')!='SaveImage' or not source.is_relative_to(scope)
            or not (Path(cfg['output_root'])/save_prefix).resolve().is_relative_to(scope)):
        raise ValueError('scene_guide_exact_new_job_output_scope_required')
    matching=[x for x in result.get('images',[]) if x.get('path')==str(image)
        and x.get('sha256')==v['image']['sha256'] and Path(x.get('source_path','')).resolve()==source and x.get('save_node')==node]
    if len(matching)!=1 or not image.is_relative_to(plan_path.parent/'artifacts'):
        raise ValueError('scene_guide_RESULT_must_bind_same_saved_image')
    with base.Image.open(image) as opened:
        if opened.size != (736,1312): raise ValueError('native_geometry_scene_guide_required')
    return v


def for_run(run):
    """Reuse unchanged sealed transport/graph code with new explicit input policy."""
    run = Path(run).resolve(); ns = dict(base.__dict__)
    for name, function in list(ns.items()):
        if isinstance(function, types.FunctionType) and function.__module__ == base.__name__:
            isolated = types.FunctionType(function.__code__, ns, function.__name__, function.__defaults__, function.__closure__)
            isolated.__kwdefaults__ = function.__kwdefaults__; ns[name] = isolated
    def same(value):
        if Path(value).resolve() != run: raise ValueError('continuation_adapter_bound_to_one_run')
    def settings(value, sid):
        same(value)
        p = read(run/'PLAN.json')
        if p.get('continuation_contract') != VERSION: raise ValueError('explicit_continuation_plan_required')
        selection = read(base.core.check(p['library_selection']))['segments'][sid]
        return _selection(selection, _actors(base.core._entries(bind(base.part(run,sid)/'SOURCE_CASE.json'))[0]))
    def library_value(value, entry):
        same(value); p = read(run/'PLAN.json')
        return resolve_library(p['library_binding'], p['binding_approval'], _actors(entry), settings(run,entry['shot_id']))
    def predecessor(value, sid):
        same(value)
        if sid not in IDS: raise ValueError('explicit_four_segment_id_required')
        p = read(run/'PLAN.json'); origin = read(base.core.check(p['continuation_origin']))
        verify_origin(origin)
        if sid == 'S01': return origin['native_result']
        previous = IDS[IDS.index(sid)-1]; path = base.native_run(run,previous)/'shots'/previous/'RESULT.json'
        if not path.exists(): return None
        plan = read(path.parents[2]/'PLAN.json')
        if plan.get('schema') != base.SCHEMA or plan.get('series_plan') != bind(run/'PLAN.json'):
            raise ValueError('current_run_immediate_native_predecessor_required')
        return bind(path)
    def review_request(value, sid):
        same(value); selection = settings(run,sid); prev = predecessor(run,sid)
        if prev is None: return dict(status='upstream_native_tail_required', predecessor_shot_id=IDS[IDS.index(sid)-1], model_posts=0)
        previous = ns['verify_native'](prev)
        if selection.get('scene_guide_path'):
            guide_receipt = generated_scene_guide(run, selection['scene_guide_path'],selection.get('scene_job_id'))
            if guide_receipt is None: return dict(status='scene_generated_guide_required', shot_id=sid, model_posts=0)
            guide, kind = guide_receipt['image'], 'generated_scene'
        else: guide_receipt, guide, kind = previous, previous['last_image'], 'native_tail'
        entry = base.core._entries(bind(base.part(run,sid)/'SOURCE_CASE.json'))[0]
        result = dict(schema=base.REVIEW+'_request',shot_id=sid, predecessor_result=prev,
            predecessor_receipt=previous, guide_image=guide, guide_kind=kind, generation_receipt=guide_receipt,
            required_actor_assets=_actors(entry), opening_actor_ids=list(entry['camera_beats'][0]['actors']),
            required_review_file=str(base.part(run,sid)/'GUIDE_STATE_REVIEW.json'), guide_visibility_does_not_filter_required_assets=True)
        freeze(base.part(run,sid)/'GUIDE_STATE_REQUEST.json', result)
        return dict(status='actual_guide_state_review_required',request=bind(base.part(run,sid)/'GUIDE_STATE_REQUEST.json'),model_posts=0)
    def script_fields(entry, selection):
        actors = _actors(entry); req = base.core.validate_entry(entry)
        quoted = base.core.QUOTE.findall(base.core.compile_prompt(entry)['compiled_prompt'])
        return dict(characters=actors,time=dict(story_time=selection.get('story_time','原文未明确具体时刻'),
            clip_start_seconds=IDS.index(entry['shot_id'])*362/24,clip_duration_seconds=362/24),
            location=dict(place_id=selection['place_id'],name=selection['place_name']),
            actions=[dict(start=b['start'],end=b['end'],text=''.join(req['spans'][s]['text'] for s in b['source_span_ids']),source_span_ids=b['source_span_ids']) for b in entry['camera_beats']],
            language=[dict(a,text=quoted[i][1:-1]) for i,a in enumerate(entry['audio'])],visuals=deepcopy(entry['camera_beats']))
    def render(entry, review, library, refs, fields):
        names = entry['character_names']
        lines = ['真人写实中国家庭短剧，竖屏9:16，普通话与原生同步声音。对白文字仅作发音内容，画面呈现摄影剧情；人物按情节看互动对象，自由切换景别。',
            '本段时间：'+fields['time']['story_time']+'；地点：'+fields['location']['name']+'。']
        for cid in fields['characters']:
            tags = '、'.join(r['tag'] for r in refs if r.get('actor_id')==cid)
            lines.append(names[cid]+'对应'+tags+'中的同一人物。身份与服装特点：'+library['character_descriptions'][cid]['description'])
        tags = '、'.join(r['tag'] for r in refs if r['kind']=='place')
        lines.append('背景对应'+tags+'。'+library['environment_description']['description'])
        cut = refs[-1]['kind']=='previous_scene_context'
        if cut:
            lines.append(refs[-1]['tag']+'是前段结束在前一场景的实际状态，仅帮助理解前情和人物所处的前后地点。'+review['previous_scene_state']+'当前新场景从单独输入的场景首帧开始，按本段分镜演出。')
        else:
            lines.append(refs[-1]['tag']+'是当前真实首帧状态参考，姿态、位置、视线与持物依本段状态继续；人物肖像中的制图姿态不作为剧情动作。')
        for cid in review['guide_visible_actor_ids']:
            lines.append(('当前场景首帧' if cut else refs[-1]['tag'])+'中'+review['screen_identity_map'][cid]+'对应'+names[cid]+'。')
        lines.append('当前真实状态：'+'；'.join(names[c]+':'+review['world_actor_state'][c] for c in fields['characters']))
        lines.append('各人物的普通话声线在本段及续段中保持一致。')
        framing=dict(face_close='头肩近景',hands_close='手部及所持物近景',medium='中景',wide='全景',detail='局部细节镜头')
        emitted=set()
        for beat,action in zip(entry['camera_beats'],fields['actions']):
            lines.append(f"{beat['start']:g}—{beat['end']:g}秒，"+('切到' if beat.get('cut') else '以')+framing[beat['framing']]+'呈现，画面人物为'+'、'.join(names[c] for c in beat['actors'])+'。'+action['text'])
            for i,a in enumerate(fields['language']):
                if i in emitted or not beat['start']<=a['start']<beat['end']: continue
                emitted.add(i); who=names[a['speaker']]
                if a['mode']=='inner_voice': lead=who+'的内心独白，以'+who+'的画外音说'; tail='；本人入镜时嘴唇自然闭合，保持当时动作与思考神情。'
                elif a['mode']=='voiceover': lead='中性旁白以画外声叙述'; tail='；在场人物依当时动作与神情表演，旁白不赋予他们开口动作。'
                elif a['mode']=='offscreen_dialogue': lead=who+'从画外说'; tail='；画面中的人物依当时动作倾听和反应。'
                else: lead=who+'本人开口说'; tail='，其他人在其台词期间倾听并按剧情反应。'
                lines.append(f"{a['start']:g}—{a['end']:g}秒，"+lead+'：“'+a['text']+'”'+tail)
        if len(emitted)!=len(fields['language']): raise ValueError('every_source_audio_must_be_interwoven_once')
        text='\n'.join(lines)
        if base.core.QUOTE.findall(text)!=base.core.QUOTE.findall(base.core.compile_prompt(entry)['compiled_prompt']):
            raise ValueError('original_quotes_or_order_changed')
        return text
    def input_value(value,sid):
        same(value); source=bind(base.part(run,sid)/'SOURCE_CASE.json'); entry=base.core._entries(source)[0]
        lib=library_value(run,entry)
        if lib.get('status')!='ready': return base.missing_notice(run,dict(shot_id=sid,library_notice=lib))
        request=review_request(run,sid)
        if request['status']!='actual_guide_state_review_required': return request
        q=read(base.core.check(request['request'])); path=base.part(run,sid)/'GUIDE_STATE_REVIEW.json'
        if not path.exists(): return request
        review=read(path); visible=review.get('guide_visible_actor_ids',[]); world=review.get('world_actor_state',{}); screen=review.get('screen_identity_map',{})
        actors=_actors(entry)
        if (review.get('schema')!=base.REVIEW or review.get('shot_id')!=sid or review.get('predecessor_result')!=q['predecessor_result']
                or review.get('guide_image')!=q['guide_image'] or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
                or not review.get('reviewed_by') or not base._strings(review.get('evidence')) or not isinstance(visible,list)
                or len(visible)!=len(set(visible)) or not set(visible)<=set(actors) or set(world)!=set(actors) or set(screen)!=set(visible)
                or any(not isinstance(v,str) or not v.strip() for v in [*world.values(),*screen.values()])):
            raise ValueError('actual_guide_visibility_and_world_state_required')
        if q['guide_kind']=='generated_scene' and (not isinstance(review.get('previous_scene_state'),str) or not review['previous_scene_state'].strip()):
            raise ValueError('scene_cut_requires_actual_previous_scene_state_description')
        refs=[dict(r,slot=i,tag=f'<Picture {i+1}>') for i,r in enumerate(lib['references'])]
        selection=settings(run,sid)
        previous_id=q['predecessor_receipt']['result']['prompt_id']
        if q['guide_kind']=='generated_scene':
            refs.append(dict(slot=len(refs),tag=f'<Picture {len(refs)+1}>',kind='continuity_context',entity_id='preceding_scene_state',
                asset_id='native_tail:'+previous_id,version=1,view='previous_segment_tail',image=q['predecessor_receipt']['last_image']))
            refs[-1]['kind']='previous_scene_context'
        else:
            refs.append(dict(slot=len(refs),tag=f'<Picture {len(refs)+1}>',kind='dynamic_guide',entity_id='current_scene_state',
                asset_id='native_tail:'+previous_id,version=1,view='guide_start',image=q['guide_image']))
        if len(refs)>9: raise ValueError('model_reference_capacity_exceeded_no_truncation')
        p=read(run/'PLAN.json'); fields=script_fields(entry,selection); text=render(entry,review,lib,refs,fields)
        return dict(schema=base.CONTRACT,continuation_contract=VERSION,shot_id=sid,source_case=source,entry_sha256=base.core.digest(entry),
            first_image=q['guide_image'],predecessor_result=q['predecessor_result'],predecessor_receipt=q['predecessor_receipt'],
            generation_receipt=q['generation_receipt'],guide_kind=q['guide_kind'],guide_review=bind(path),
            continuation_origin=p['continuation_origin'],segment_selection=selection,
            library_binding=p['library_binding'],binding_approval=p['binding_approval'],library_resolution=lib,references=refs,
            required_actor_assets=actors,guide_visible_actor_ids=visible,world_actor_state=world,script_fields=fields,
            compiled_prompt=text,compiled_prompt_utf8_sha256=base.core.sha(text),full_video_quality_passed=False,
            production_approved=False,publication=False,conditioning_mode=base.CONDITIONING)
    def validate_graph(graph, scope, mapping):
        if mapping[-1]['kind']!='previous_scene_context':
            return base.validate_graph(graph,scope,mapping)
        fake=deepcopy(mapping);fake[-1]['kind']='dynamic_guide'
        restored=deepcopy(graph)
        node=restored.pop('scene_start',None)
        if node!={'class_type':'LoadImage','inputs':{'image':scope+'/scene_start.png'}}:
            raise ValueError('separate_actual_scene_start_LoadImage_required')
        if restored['guide_start']['inputs'].get('image')!=['scene_start',0]:
            raise ValueError('scene_cut_guide_must_use_generated_start_not_previous_room_tail')
        restored['guide_start']['inputs']['image']=[f'ref_{len(mapping)-1}',0]
        base.validate_graph(restored,scope,fake)
    def build_graph(original,shot,value,mapping,scope):
        if value['guide_kind']!='generated_scene': return base.build_graph(original,shot,value,mapping,scope)
        fake=deepcopy(mapping);fake[-1]['kind']='dynamic_guide'
        graph=base.build_graph(original,shot,value,fake,scope)
        graph['scene_start']=dict(class_type='LoadImage',inputs=dict(image=scope+'/scene_start.png'))
        graph['guide_start']['inputs']['image']=['scene_start',0]
        validate_graph(graph,scope,mapping)
        return graph
    def prepare_video(value,sid,*,code_files=()):
        same(value);v=input_value(run,sid)
        if 'status' in v:return v
        folder=base.part(run,sid);freeze(folder/'LIBRARY_INPUT.json',v);ib=bind(folder/'LIBRARY_INPUT.json')
        checked=ns['validate_input'](ib)
        cfg=read(base.core.check(read(run/'PLAN.json')['config']))
        cfg=base.native._config(dict(config=dict(image_service=cfg,**{k:cfg[k] for k in ('gpu_lock_root','protected_pause_path')})),cfg)
        nr=base.native_run(run,sid);base.native._target(nr,cfg);shot=source_shot(base.core._entries(v['source_case'])[0])
        timing=base.native._timing(shot);scope=base.native.PREFIX+'/'+nr.name+'/'+sid
        mapping=[dict(r,input_name=scope+'/references/P'+str(i+1)+'.png') for i,r in enumerate(v['references'])]
        graph=build_graph(read(cfg['base_workflow']),shot,v,mapping,scope)
        guide=dict(image=v['first_image'],input_name=scope+'/scene_start.png') if v['guide_kind']=='generated_scene' else None
        row=dict(id=sid,binding_sha256=shot['binding_sha256'],first_frame=v['first_image'],graph_sha256=base.core.digest(graph),
            scope=scope,input_name=guide['input_name'] if guide else mapping[-1]['input_name'],timing=timing,
            library_input=checked['proof'],reference_map=mapping,guide_map=guide)
        plan=dict(schema=base.SCHEMA,upstream_contract=base.CONTRACT,series_plan=bind(run/'PLAN.json'),config=cfg,input=ib,source=v['source_case'],
            shots=[row],base_workflow=bind(cfg['base_workflow']),protected_pause=bind(cfg['protected_pause_path']),
            code=[bind(x) for x in (__file__,base.__file__,base.features.__file__,base.features.registry.__file__,base.native.__file__,base.core.__file__,*SOURCE_TOOLS,*code_files,*base.CAPABILITY_FILES)],
            publication=False,production_approved=False,old_batch_resume=False,full_video_quality_passed=False,conditioning_mode=base.CONDITIONING)
        nr.mkdir(parents=True,exist_ok=True)
        with base.native.jobs.run_lock(nr):
            freeze(nr/'PLAN.json',plan)
            for ref in mapping:
                base.native.jobs.stage_input({k:cfg[k] for k in ('service_url','input_root','output_root','timeout')},ref['image']['path'],ref['input_name'],ref['image']['sha256'])
            if guide:
                base.native.jobs.stage_input({k:cfg[k] for k in ('service_url','input_root','output_root','timeout')},guide['image']['path'],guide['input_name'],guide['image']['sha256'])
            freeze(nr/'shots'/sid/'workflow_api.json',graph)
            state=nr/'shots'/sid/'STATE.json'
            if not state.exists():base.native.write(state,dict(id=sid,status='prepared',prompt_id=None,plan_sha256=base.core.digest(plan)))
        freeze(folder/'LAUNCH_REQUEST_VIDEO.json',ns['launch_request'](run,sid))
        return ns['status'](run,sid)
    original_submit=ns['submit'];original_load=ns['_load']
    def load(value,sid,current=True):
        same(value);nr,p,row=original_load(value,sid,current=current)
        if current:
            origin=read(base.core.check(read(run/'PLAN.json')['continuation_origin']));verify_origin(origin)
        guide=row.get('guide_map')
        if guide:
            context=read(base.core.check(p['input']))
            if (guide.get('image')!=row['first_frame'] or guide['image']!=context['first_image']
                    or guide.get('input_name')!=row['scope']+'/scene_start.png' or row['input_name']!=guide['input_name']):
                raise ValueError('actual_scene_guide_mapping_changed')
            if current and base.native.file_sha(base.native.bound(p['config']['input_root'],guide['input_name']))!=guide['image']['sha256']:
                raise ValueError('actual_staged_scene_guide_pixels_changed')
        return nr,p,row
    def submit(value,sid):
        same(value);load(value,sid)
        return original_submit(value,sid)
    ns.update(prepare=prepare,library_value=library_value,_predecessor=predecessor,review_request=review_request,
        script_fields=script_fields,render=render,input_value=input_value,prepare_video=prepare_video,
        validate_graph=validate_graph,build_graph=build_graph,_load=load,submit=submit)
    # The sealed base _load needs its textual shot binding, not its old image
    # coverage/evaluate route. This proxy changes no imported module globals.
    ns['core']=types.SimpleNamespace(**dict(base.core.__dict__,handoff_snapshot=source_snapshot))
    return types.SimpleNamespace(**ns,continuation_version=VERSION)
