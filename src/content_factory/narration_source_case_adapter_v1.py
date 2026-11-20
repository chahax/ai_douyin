"""Fresh SOURCE_CASE consumer for approved narration placement, with CPU proof.

No frozen source, in-flight graph, account task, service, or media is changed.
Long speech and missing assets produce machine-readable notices, not truncation.
"""
from copy import deepcopy
from pathlib import Path

from . import narration_placement_policy_v2 as policy
from . import visual_h3_library_continuation_v1 as continuation

VERSION='narration_source_case_adapter/v1'
core=continuation.base.core


def _notice(folder,status,details):
    value=dict(schema=VERSION,status=status,details=details,media_dispatch_allowed=False,production_approved=False)
    policy.freeze(Path(folder)/'NOTICE.json',value);return value


def _reaction_plan(case,receipt):
    original=policy.compile_before_video(case,receipt);value=deepcopy(original)
    items={i['id']:i for i in value['items']};action=items['A_STOP'];last_turn=items['Q_GIRL'];oral=items['N_S04']
    decision=next(r for r in receipt['candidate']['decisions'] if r['source_quote_id']=='N_S04')
    if decision['slot_id']!='GAP:A_STOP':raise ValueError('reaction_variant_requires_same_approved_after_slot')
    duration=round(action['end']-action['start'],3);start=round(last_turn['end']-duration,3)
    if start<last_turn['start']:raise ValueError('reaction_action_does_not_fit_within_listening_turn')
    old_duration=round(oral['end']-oral['start'],3)
    action.update(start=start,end=last_turn['end']);oral.update(start=last_turn['end'],end=round(last_turn['end']+old_duration,3))
    value['audio_items']=[i for i in value['items'] if i['kind']=='audio']
    if oral['start']<action['end'] or oral['start']<last_turn['end']:raise ValueError('reaction_does_not_preserve_after_action_and_group')
    lines=[]
    for item in value['items']:
        if item['kind']=='scene':lines.append('场景：'+item['text'])
        elif item['kind']=='action':lines.append(f"{item['start']:g}—{item['end']:g}秒，动作与画面："+item['text'])
        else:
            who='旁白画外叙述' if item['mode']=='voiceover' else case['characters'][item['speaker_id']]+'本人开口说'
            lines.append(f"{item['start']:g}—{item['end']:g}秒，"+who+'：“'+item['text']+'”')
    value['compiled_prompt']='\n'.join(lines)
    return original,value


def reaction_schedule_variant(folder,case_binding,receipt_binding):
    folder=Path(folder);case=policy.read(policy.checked(case_binding));receipt=policy.read(policy.checked(receipt_binding))
    original,compiled=_reaction_plan(case,receipt)
    script=case['source_bindings'][0];body=policy.checked(script).read_text(encoding='utf-8')
    begin=body.index('叶嫣儿也抬起头附和');end=body.index('**【旁白】** 是啊，苏墨每天',begin)
    evidence=dict(document=script,start=begin,end=end,text=body[begin:end])
    value=dict(schema='narration_reaction_schedule_variant/v1',case=case_binding,receipt=receipt_binding,
        original_compilation_sha256=policy.digest(original),compilation=compiled,source_evidence=evidence,
        approved_by='root_task_and_independent_source_auditor',
        interpretation='Dong may begin stopping his fist while listening to the end of the girl warning; his oral explanation remains after the full warning and action end.',
        action_duration_changed=False,speech_duration_or_text_changed=False,specific_schedule_reviewed_by_MiniMax=False,
        replaces_strict_split=False,media_dispatch_allowed=False)
    policy.freeze(folder/'SCHEDULING_VARIANT.json',value);return policy.bind(folder/'SCHEDULING_VARIANT.json')


def materialize(folder,base_source_binding,case_binding,receipt_binding,quote_ids,*,action_span_map=None,split_plan=None,scheduling_variant=None):
    folder=Path(folder);case=policy.read(policy.checked(case_binding));receipt=policy.read(policy.checked(receipt_binding))
    compiled=policy.compile_before_video(case,receipt)
    if scheduling_variant is not None:
        variant=policy.read(policy.checked(scheduling_variant));original,derived=_reaction_plan(case,receipt)
        if (variant.get('schema')!='narration_reaction_schedule_variant/v1' or variant.get('case')!=case_binding
                or variant.get('receipt')!=receipt_binding or variant.get('original_compilation_sha256')!=policy.digest(original)
                or variant.get('compilation')!=derived or variant.get('speech_duration_or_text_changed') is not False):
            raise ValueError('explicit_source_bound_reaction_variant_required')
        evidence=variant['source_evidence'];text=policy.checked(evidence['document']).read_text(encoding='utf-8')[evidence['start']:evidence['end']]
        if text!=evidence['text']:raise ValueError('reaction_variant_original_evidence_changed')
        compiled=derived
    source=policy.read(policy.checked(base_source_binding));entry=deepcopy(source['shots'][0]);sid=entry['shot_id']
    old_quotes=[s['text'][1:-1] for s in entry['source_spans'] if s['kind']=='audio']
    originals={q['id']:q for q in case['quotes']}
    full_quote_ids=split_plan['full_quote_ids'] if split_plan is not None else quote_ids
    if (len(full_quote_ids)!=len(entry['audio']) or len(full_quote_ids)!=len(set(full_quote_ids))
            or any(q not in originals for q in full_quote_ids) or [originals[q]['text'] for q in full_quote_ids]!=old_quotes):
        raise ValueError('explicit_complete_baseline_audio_to_original_quote_mapping_required')
    if split_plan is not None:
        parts=split_plan.get('parts',[])
        if (split_plan.get('schema')!='narration_deterministic_split/v1' or split_plan.get('base_source_case')!=base_source_binding
                or [q for part in parts for q in part['quote_ids']]!=full_quote_ids
                or quote_ids not in [part['quote_ids'] for part in parts]):
            raise ValueError('explicit_lossless_split_plan_required')
        for group in case['dialogue_groups']:
            members=set(group['quote_ids'])&set(full_quote_ids)
            if members and not any(members<=set(part['quote_ids']) for part in parts):raise ValueError('protected_dialogue_group_cannot_split')
    selected=[a for a in compiled['audio_items'] if a['source_quote_id'] in quote_ids]
    if len(selected)!=len(quote_ids):raise ValueError('every_selected_audio_item_once_required')
    action_ids={s['id'] for s in entry['source_spans'] if s['kind']=='action'}
    if split_plan is not None:
        all_spans=[span for part in split_plan['parts'] for span in part['action_span_map']]
        if set(all_spans)!=action_ids or len(all_spans)!=len(set(all_spans)):raise ValueError('every_original_action_once_across_split_required')
        expected_actions=next(part['action_span_map'] for part in split_plan['parts'] if part['quote_ids']==quote_ids)
    else:expected_actions={s:None for s in action_ids}
    if not isinstance(action_span_map,dict) or set(action_span_map)!=set(expected_actions):
        return _notice(folder,'needs_action_binding',dict(required_base_action_span_ids=sorted(action_ids),
            reason='Every original action needs an explicit approved case action/quote anchor; old camera times are never silently reused.'))
    ordered=[i for i in compiled['items'] if i['kind']!='scene'];planned={i['id']:i for i in ordered}
    event_ids=set(quote_ids)|set(action_span_map.values())
    if any(i not in planned for i in event_ids):return _notice(folder,'needs_action_binding',dict(unknown_case_event_ids=sorted(event_ids-set(planned))))
    indices=[j for j,item in enumerate(ordered) if item['id'] in event_ids]
    interval=ordered[min(indices):max(indices)+1]
    unwanted=[i['source_quote_id'] for i in interval if i['kind']=='audio' and i['source_quote_id'] not in quote_ids]
    if unwanted:return _notice(folder,'needs_segment_boundary_expansion',dict(required_quote_ids=unwanted,
        reason='Approved action/audio interval crosses another dialogue turn; fixed old shot assignment cannot discard it.'))
    if len({planned[i]['scene_id'] for i in event_ids})!=1:return _notice(folder,'needs_scene_split',dict(case_event_ids=sorted(event_ids)))
    offset=min(planned[i]['start'] for i in event_ids);audio=[]
    for a in selected:
        audio.append(dict(a,start=round(a['start']-offset+.2,3),end=round(a['end']-offset+.2,3)))
    event_times={i:dict(start=round(planned[i]['start']-offset+.2,3),end=round(planned[i]['end']-offset+.2,3)) for i in event_ids}
    required=max(t['end'] for t in event_times.values())+.2
    if required>15:
        return _notice(folder,'needs_segment_split',dict(required_seconds=required,max_seconds=15,quote_ids=quote_ids,
            original_dialogue_preserved=True,silent_truncation=False))
    try:
        for value in [*entry['canonical_characters'].values(),entry['canonical_room'],entry['actual_first_image']]:core.image(value)
    except (FileNotFoundError,OSError,ValueError) as error:
        return _notice(folder,'needs_asset',dict(shot_id=sid,error_type=type(error).__name__,asset_keys=list(entry['canonical_characters'])))
    chunks=[];spans=[];remap={}
    def add(kind,text):
        start=sum(len(s) for s in chunks);identity='s%03d'%len(spans)
        spans.append(dict(id=identity,kind=kind,start=start,end=start+len(text),text=text,sha256=core.sha(text)))
        chunks.extend((text,'\n'));return identity
    for span in entry['source_spans']:
        if span['kind']!='audio':
            kind='context' if split_plan is not None and span['kind']=='action' and span['id'] not in action_span_map else span['kind']
            remap[span['id']]=add(kind,span['text'])
    transformed=[]
    for a in audio:
        quoted='“'+a['text']+'”';add('audio',quoted)
        transformed.append(dict(quote_index=len(transformed),quote_sha256=core.sha(quoted),speaker=a['speaker_id'],mode=a['mode'],start=a['start'],end=a['end']))
    text=''.join(chunks);folder.mkdir(parents=True,exist_ok=True);prompt_path=folder/'SOURCE.txt'
    if prompt_path.exists() and prompt_path.read_text(encoding='utf-8')!=text:raise ValueError('frozen_transformed_source_changed')
    if not prompt_path.exists():prompt_path.write_text(text,encoding='utf-8')
    old_beats=deepcopy(entry['camera_beats']);poses={}
    for beat in old_beats:
        for cid,actor in beat['actors'].items():poses.setdefault(cid,deepcopy(actor))
    bounds=sorted({0.0,15.0,*[t[k] for t in event_times.values() for k in ('start','end')],*[a[k] for a in audio for k in ('start','end')]})
    beats=[];assigned=set()
    for start,end in zip(bounds,bounds[1:]):
        middle=(start+end)/2
        active_spans=[s for s,event in action_span_map.items() if event_times[event]['start']<=middle<event_times[event]['end']]
        template=next((b for b in old_beats if any(s in b['source_span_ids'] for s in active_spans)),old_beats[-1])
        if active_spans:
            for identity in active_spans:
                original_span=next(s for s in entry['source_spans'] if s['id']==identity)
                action_template=next(b for b in old_beats if identity in b['source_span_ids'])
                for cid,actor in action_template['actors'].items():
                    if entry['character_names'][cid] in original_span['text']:poses[cid]=deepcopy(actor)
        actors=deepcopy(template['actors']) if active_spans else deepcopy(poses)
        framing=template['framing'] if active_spans else 'medium'
        active=[a for a in audio if a['mode']=='onscreen' and a['start']<end and a['end']>start]
        if active:
            cid=active[0]['speaker_id']
            if cid not in poses:return _notice(folder,'needs_asset',dict(actor_id=cid,reason='no_source_anchored_pose'))
            actor=deepcopy(poses[cid]);actor['visible_parts']=list(dict.fromkeys(['face',*actor['visible_parts']]))
            actors={cid:actor};framing='face_close'
            # A listening reaction may overlap another actor's line. Preserve
            # both the speaker's visible face and the source-named action actor.
            for identity in active_spans:
                source_span=next(s for s in entry['source_spans'] if s['id']==identity)
                participants=[c for c,name in entry['character_names'].items() if c in poses and name in source_span['text']]
                if not participants:return _notice(folder,'needs_action_actor_binding',dict(base_span_id=identity))
                action_template=next(b for b in old_beats if identity in b['source_span_ids'])
                for participant in participants:
                    if participant not in actors:actors[participant]=deepcopy(action_template['actors'].get(participant,poses[participant]))
            if len(actors)>1:framing='medium'
        if start>=max(a['end'] for a in audio):actors=deepcopy(poses);framing='medium'
        actions=[]
        for identity,event in action_span_map.items():
            if start<=event_times[event]['start']<end and identity not in assigned:
                actions.append(remap[identity]);assigned.add(identity)
        beats.append(dict(start=start,end=end,cut=bool(beats),framing=framing,actors=actors,source_span_ids=actions))
    for span in entry['source_spans']:
        if span['kind']=='action' and span['id'] in action_span_map and span['id'] not in assigned:
            beats[0]['source_span_ids'].append(remap[span['id']]);assigned.add(span['id'])
    old_authority=entry.get('authoritative_script')
    entry.update(source=policy.bind(prompt_path),source_scope=dict(start=0,end=len(text)),source_spans=spans,audio=transformed,camera_beats=beats,
        source_state_span_ids=[s['id'] for s in spans if s['kind'] in ('context','action')],
        character_description_span_ids={c:[remap[i] for i in values] for c,values in entry['character_description_span_ids'].items()},
        audio_context_span_ids=[remap[i] for i in entry['audio_context_span_ids']],source_case_transform_contract=VERSION,
        original_source_case=base_source_binding,original_authoritative_script=old_authority,authoritative_script=policy.bind(prompt_path),
        narration_case=case_binding,narration_receipt=receipt_binding,selected_quote_ids=quote_ids,
        narration_action_bindings=[dict(base_span_id=s,new_span_id=remap[s],case_event_id=event,**event_times[event]) for s,event in action_span_map.items()],
        deterministic_split=split_plan,split_context_only_action_span_ids=sorted(action_ids-set(action_span_map)) if split_plan is not None else [],
        narration_scheduling_variant=scheduling_variant,
        source_entry_role=continuation.SOURCE_ROLE,planning_preview_image=entry['actual_first_image'],
        actual_first_image_role='legacy_compatibility_planning_preview_not_dispatch_input')
    entry.pop('source_item_provenance',None)
    core.validate_entry(entry);shot=continuation.source_shot(entry)
    decisions={r['source_quote_id']:r for r in receipt['candidate']['decisions']}
    for a in audio:
        row=decisions.get(a['source_quote_id'])
        if row and row['slot_id'].startswith('GAP:'):
            anchor=row['slot_id'][4:]
            if anchor not in event_times or a['start']<event_times[anchor]['end']:
                raise ValueError('approved_action_gap_not_preserved_in_actual_segment')
    for a in transformed:
        if a['mode']=='onscreen' and any(a['start']<b['end'] and a['end']>b['start'] and 'face' not in b['actors'].get(a['speaker'],{}).get('visible_parts',[]) for b in beats):
            raise ValueError('converted_character_face_must_cover_entire_audio_window')
    target=folder/'SOURCE_CASE.json';policy.freeze(target,dict(schema=core.SCHEMA,shots=[entry]))
    result=dict(schema=VERSION,status='fresh_source_case_ready_for_actual_asset_tail_gate',source_case=policy.bind(target),
        compiled_plan_sha256=policy.digest(compiled),source_shot_sha256=core.digest(shot),required_seconds=required,
        media_dispatch_allowed=False,production_approved=False,actual_future_tail_claimed=False)
    policy.freeze(folder/'RESULT.json',result);return result


def split_warning_segment(folder,base_source_binding,case_binding,receipt_binding):
    """This bounded split keeps the complete two-turn warning together.

    It creates planning sources only. The second part will still require the
    true first part's saved tail before any future production dispatch.
    """
    folder=Path(folder)
    split=dict(schema='narration_deterministic_split/v1',base_source_case=base_source_binding,
        full_quote_ids=['Q_NAN','Q_GIRL','N_S04'],parts=[
            dict(id='P01',quote_ids=['Q_NAN','Q_GIRL'],action_span_map={'s010':'Q_NAN','s012':'Q_GIRL'}),
            dict(id='P02',quote_ids=['N_S04'],action_span_map={'s014':'A_STOP'})],
        reason='Complete G_WARN remains intact; stopping action then oral explanation occupy a separate bounded segment.',
        publication=False,actual_future_tail_claimed=False)
    policy.freeze(folder/'SPLIT_PLAN.json',split);rows=[]
    for part in split['parts']:
        value=materialize(folder/part['id'],base_source_binding,case_binding,receipt_binding,part['quote_ids'],
            action_span_map=part['action_span_map'],split_plan=split)
        rows.append(dict(part_id=part['id'],quote_ids=part['quote_ids'],result=value,
            predecessor_required='original_previous_actual_tail' if part['id']=='P01' else 'P01_new_saved_actual_tail_not_yet_available'))
    receipt=dict(schema='narration_split_source_consumption/v1',split_plan=policy.bind(folder/'SPLIT_PLAN.json'),parts=rows,
        source_dialogue_coverage_exactly_once=True,actual_future_tail_claimed=False,media_dispatch_allowed=False)
    policy.freeze(folder/'SPLIT_RESULT.json',receipt);return receipt


def prove_graph(folder,source_case_binding,baseline_input_binding,config_binding):
    """Run the real SOURCE_CASE→render→H3 build_graph path, entirely on CPU."""
    folder=Path(folder);entry=policy.read(policy.checked(source_case_binding))['shots'][0]
    baseline=policy.read(policy.checked(baseline_input_binding));cfg=policy.read(policy.checked(config_binding))
    library=continuation.resolve_library(baseline['library_binding'],baseline['binding_approval'],entry['full_clip_actor_ids'],baseline['segment_selection'])
    if library.get('status')!='ready':return _notice(folder,'needs_asset',library)
    review=policy.read(policy.checked(baseline['guide_review']));refs=deepcopy(baseline['references'])
    for ref in refs:policy.checked(ref['image'])
    renderer=continuation.for_run(folder);fields=renderer.script_fields(entry,baseline['segment_selection'])
    text=renderer.render(entry,review,library,refs,fields)
    value=dict(compiled_prompt=text,first_image=baseline['first_image'])
    shot=continuation.source_shot(entry);scope='narration_cpu_only/'+folder.name+'/'+entry['shot_id']
    mapping=[dict(r,input_name=scope+'/references/P'+str(i+1)+'.png') for i,r in enumerate(refs)]
    graph=continuation.base.build_graph(policy.read(cfg['base_workflow']),shot,value,mapping,scope)
    if graph['condition']['inputs']['prompt']!=text or core.QUOTE.findall(text)!=core.QUOTE.findall(core.compile_prompt(entry)['compiled_prompt']):
        raise ValueError('actual_narration_audio_not_consumed_by_positive_graph')
    policy.freeze(folder/'CPU_WORKFLOW.json',graph)
    result=dict(schema=VERSION,status='actual_source_render_build_graph_CPU_proven',source_case=source_case_binding,
        baseline_input=baseline_input_binding,graph=policy.bind(folder/'CPU_WORKFLOW.json'),
        positive_prompt_sha256=core.sha(text),audio=[dict(a,text=core.QUOTE.findall(text)[a['quote_index']][1:-1]) for a in entry['audio']],
        reference_count=len(refs),actual_LoadImage_count=sum(n['class_type']=='LoadImage' for n in graph.values()),
        guide_kind='historical_real_tail_for_CPU_probe_not_pending_production_tail',input_images_staged=False,
        GPU_calls=0,model_posts=0,production_approved=False,media_dispatch_allowed=False)
    policy.freeze(folder/'CPU_PROOF.json',result);return result
