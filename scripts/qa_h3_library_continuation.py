"""Independent CPU QA for an explicitly sourced following minute.

This module cannot submit media or change service state. Source coverage,
actual library pixels and guide routing are separate from visual quality.
"""
from __future__ import annotations
import argparse
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import sys
import types

SCRIPTS = Path(__file__).resolve().parent
for p in (SCRIPTS, SCRIPTS.parent):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
import qa_h3_library_minute as base
from src.content_factory import visual_h3_continuity_input_v33 as core

PROJECT, IDS = base.PROJECT, base.IDS
read, bind, checked, require, sha, freeze, digest = base.read, base.bind, base.checked, base.require, base.sha, base.freeze, base.digest
VERSION = 'library_minute_continuation/v1'
SEALED_BASE_QA = 'b5cc0fab7b836d1f5fd9b1b57daf369973314c67c6640e1da764e38b02c758bc'


def source_entry(binding, sid, project=PROJECT):
    p = checked(binding, project); value = read(p)
    require(len(value.get('shots', [])) == 1 and value['shots'][0].get('shot_id') == sid, 'one_source_entry_required')
    e = value['shots'][0]; validated = core.validate_entry(e)
    require(validated['source_coverage_complete'], 'source_actions_and_audio_must_be_covered')
    require(e.get('source_entry_role') == 'script_plan_only_actual_start_bound_in_LIBRARY_INPUT'
            and e.get('actual_first_image_role') == 'legacy_compatibility_planning_preview_not_dispatch_input',
            'planning_preview_must_not_claim_to_be_actual_generated_start')
    manuscript = checked(e['authoritative_script'], project).read_text(encoding='utf-8')
    selection_path = checked(e['script_selection'], project); selection = read(selection_path)
    require(selection['source']['path'] == e['authoritative_script']['path']
            and selection['source']['sha256'] == e['authoritative_script']['sha256'], 'selected_original_manuscript_changed')
    s = next(x for x in selection['segments'] if x['shot_id'] == sid)
    require(e['full_clip_actor_ids'] == s['entire_segment_actor_ids']
            and set(e['canonical_characters']) == set(e['full_clip_actor_ids'])
            and e['place_id'] == s['place_id'], 'whole_clip_cast_and_place_must_follow_selected_source')
    spans = {x['id']: x for x in e['source_spans']}
    body = []
    for p in e['source_item_provenance']:
        if 'original' not in p: continue
        o = p['original']; text = manuscript[o['source_start']:o['source_end']]
        require(text == o['text'] and hashlib.sha256(text.encode()).hexdigest() == o['sha256'], 'manuscript_quote_or_action_offset_changed')
        expected = '“'+text+'”' if p['render_transform'] == 'add_quote_delimiters_only' else text.replace('**','')
        require(spans[p['span_id']]['text'] == expected, 'source_transform_changed_beyond_format_delimiters')
        if p['kind'] == 'selected_body_item': body.append((p['item_index'], o))
    require([i for i, _ in body] == list(range(len(s['ordered_source_items'])))
            and [o for _, o in body] == s['ordered_source_items'], 'every_selected_source_item_exactly_once_in_order_required')
    expected_audio = [x for x in s['ordered_source_items'] if x['kind'] == 'audio']
    audio_spans = [x for x in e['source_spans'] if x['kind'] == 'audio']
    require([x['text'][1:-1] for x in audio_spans] == [x['text'] for x in expected_audio], 'source_audio_cannot_be_replaced_by_old_minute_quotes')
    for actual, selected in zip(e['audio'], expected_audio):
        mode = {'narration': 'voiceover', 'onscreen': 'dialogue'}.get(selected['mode'], selected['mode'])
        require(actual['speaker'] == selected['speaker']
                and (actual['mode'] == mode or actual['mode'] == selected['mode']), 'source_speaker_or_voiceover_role_changed')
    return e


def series_inputs(run, project=PROJECT):
    run, project = Path(run).resolve(), Path(project).resolve(); p = read(run/'PLAN.json')
    require(run.is_relative_to(project/'data') and p.get('schema') == base.SERIES_SCHEMA
            and p.get('continuation_contract') == VERSION and p.get('all_segments_new') is True
            and p.get('publication') is False and p.get('production_approved') is False
            and p.get('new_video_submissions') == 4 and not any(k in p for k in ('prefix','imports','prefix_results')),
            'four_fresh_explicit_continuation_segments_required')
    require((p['frames_per_segment'],p['expected_frames'],p['width'],p['height'],p['fps'],p['steps']) == (362,1448,736,1312,24,12), 'continuation_clock_changed')
    for k in ('config','authority','library_binding','binding_approval','library_selection','continuation_origin'): checked(p[k], project)
    require([r['shot_id'] for r in p['sources']] == list(IDS), 'ordered_four_sources_required')
    entries = {}
    for r in p['sources']:
        sid = r['shot_id']
        require(checked(r['source_case'],project) == run/'segments'/sid/'SOURCE_CASE.json'
                and Path(r['native_run']).resolve() == run/'visual_h3_v3'/(run.name+'_'+sid), 'new_source_namespace_changed')
        entries[sid] = source_entry(r['source_case'], sid, project)
    return dict(run=run, plan=p, plan_binding=bind(run/'PLAN.json'), entries=entries)


def minimum_script(entry, fields, sid, selection):
    actors = set(entry['full_clip_actor_ids']); quotes = [x['text'][1:-1] for x in entry['source_spans'] if x['kind']=='audio']
    require(set(fields.get('characters',[])) == actors and len(fields['characters']) == len(actors), 'whole_segment_cast_cannot_be_filtered_by_opening')
    t, l = fields.get('time',{}), fields.get('location',{})
    require(t.get('story_time') == selection['story_time'] and t.get('clip_start_seconds') == IDS.index(sid)*362/24
            and t.get('clip_duration_seconds') == 362/24, 'story_time_and_real_clip_clock_required')
    require(l.get('place_id') == entry['place_id'] == selection['place_id'] and l.get('name') == selection['place_name'], 'bound_script_place_changed')
    require(fields.get('visuals') == entry['camera_beats'], 'original_visual_beats_changed')
    require(len(fields.get('language',[])) == len(entry['audio']), 'every_audio_item_required')
    for a, original in zip(fields['language'], entry['audio']):
        require({k:a.get(k) for k in original} == original and a.get('text') == quotes[original['quote_index']], 'source_language_speaker_mode_or_timing_changed')
        if a['speaker'] == 'narrator': require(a['mode'] == 'voiceover' and 'narrator' not in actors, 'narrator_is_an_offscreen_voice_not_actor_asset')
    spans = {s['id']:s for s in entry['source_spans']}
    require(len(fields.get('actions',[])) == len(entry['camera_beats']), 'all_camera_actions_required')
    for a,b in zip(fields['actions'],entry['camera_beats']):
        require(a.get('source_span_ids') == b['source_span_ids'] and a.get('text') == ''.join(spans[s]['text'] for s in b['source_span_ids'])
                and (a['start'],a['end']) == (b['start'],b['end']), 'source_action_and_camera_correspondence_changed')
    return dict(required_actor_ids=sorted(actors),place_id=entry['place_id'],fields=deepcopy(fields),opening_actor_ids=entry['camera_beats'][0]['actors'],content_quality_verified=False)


def library_reference_cards(binding, refs, actor_ids, selection, project):
    index = read(checked(binding,project)); required=set(actor_ids)|{selection['place_id']}
    requests=[(c,'character',v) for c in actor_ids for v in selection['actor_views'][c]]
    requests += [(selection['place_id'],'place',v) for v in selection['place_views']]
    require(len(requests)<=8 and [(r['entity_id'],r['kind'],r['view']) for r in refs] == requests, 'all_explicit_selected_views_must_be_sent_without_truncation')
    cards={}; normalized=[]
    for r in refs:
        eid=r['entity_id'];cat='characters' if r['kind']=='character' else 'places'; declared=index[cat][eid]
        require(r['feature_card']==declared['feature_card'],'same_version_feature_card_required')
        cp=checked(r['feature_card'],project);card=read(cp);selected=card['images'][r['view']]
        require(selected==declared['images'][r['view']] and card['kind']==r['kind'] and card['entity_id']==eid
                and card['appearance_description']==card['description'] and bool(card['description']) and bool(card['features']), 'source_bound_card_identity_or_description_changed')
        for k in ('entity_id','kind','view','asset_id','version','design_version','identity_group','image'):
            require(r.get(k)==selected[k],'exact_selected_registry_'+k+'_changed')
        ip=checked(r['image'],project);rp=checked(selected['registry_record'],project);record=read(rp)
        require(all(record.get(k)==r.get(k) for k in ('entity_id','kind','view','asset_id','version','design_version','identity_group'))
                and record['sha256']==r['image']['sha256'] and (rp.parent/record['file']).resolve()==ip,'original_registry_pixels_or_identity_changed')
        base.rgb_bytes(ip);cards[eid]=dict(card_binding=bind(cp),card=card);normalized.append(deepcopy(r))
    require(set(cards)==required,'all_required_actors_and_environment_need_real_images')
    for cid in actor_ids:
        views=selection['actor_views'][cid]
        require(views[0]=='front' and len(set(views))==len(views),'every_actor_needs_own_front_image')
        if len(views)==1:
            decision=selection.get('capacity_decision',{})
            require(cid in decision.get('front_only_actor_ids',[]) and bool(decision.get('reason')),'single_view_is_explicit_capacity_decision_not_silent_drop')
    return dict(binding_index=binding,references=normalized,cards=cards,required_entities=sorted(required),CPU_identity_quality_verified=False)


def native_tail(binding, project):
    path=checked(binding,project);folder=path.parent;nr=folder.parents[1];result=read(path);sid=result['shot_id']
    p=read(nr/'PLAN.json');row=p['shots'][0];graph=read(folder/'workflow_api.json');state=read(folder/'STATE.json');pid=result['prompt_id']
    require(path==nr/'shots'/sid/'RESULT.json' and p.get('schema')==base.NATIVE_SCHEMA
            and result.get('schema')==base.media_qa.native.SCHEMA and result.get('publication') is False
            and result.get('production_approved') is False
            and row['id']==sid and row['graph_sha256']==digest(graph) and read(folder/'REQUEST.json')['prompt']==graph
            and state['status']=='technical_saved' and state['prompt_id']==pid==read(folder/'RESPONSE.json')['prompt_id']
            and state['plan_sha256']==digest(p) and result['technical_status']=='technical_saved', 'actual_native_predecessor_saved_records_required')
    base.media_qa.exact_endpoint_selection(graph)
    event=read(folder/'HISTORY.json')[pid];hp=event['prompt'];hs=event['status']
    require(hp[1]==pid and base.media_qa.native.native_graph_equivalence(graph,hp[2]) is not None
            and hs['completed'] is True and hs['status_str']=='success','predecessor_actual_success_history_required')
    root=Path(p['config']['output_root']).resolve();scope=(root/row['scope']).resolve()
    require(set(result['files'])=={'video','audio','first','last'},'predecessor_four_originals_required')
    for role,r in result['files'].items():
        local=checked(r,project);origin=Path(r['source_path']).resolve();emitted=event['outputs']['save_'+role]['audio' if role=='audio' else 'images']
        require(local.is_relative_to(folder/'artifacts') and origin.parent==scope and sha(origin)==r['sha256']
                and len(emitted)==1 and (root/emitted[0].get('subfolder','')/emitted[0]['filename']).resolve()==origin,'predecessor_original_output_mapping_changed')
    return dict(image={k:result['files']['last'][k] for k in ('path','sha256')},native_id=pid,result=result,binding=binding)


def scene_guide(run, selection, image, receipt, project):
    path=Path(selection['scene_guide_path']).resolve();require(path.is_relative_to(run),'scene_receipt_must_be_owned_by_this_run')
    v=read(path);require(v==receipt and v.get('schema')=='library_generated_scene_guide/v1' and v.get('completion_known') is True
        and v.get('outcome_unknown') is False and v.get('image')==image,'actual_completed_scene_guide_required')
    records=v['generation_records'];require(set(records)=={'plan','request','history','result'},'scene_native_records_required')
    for b in records.values():checked(b,project)
    plan=read(Path(records['plan']['path']));graph=read(Path(records['request']['path']))['prompt'];pid=v['native_prompt_id']
    event=read(Path(records['history']['path']))[pid];hp=event['prompt']
    expected_job_id=selection.get('scene_job_id',run.name+'_children_start')
    result=read(Path(records['result']['path']))
    require(event['status']['completed'] is True and event['status']['status_str']=='success' and hp[1]==pid and hp[2]==graph
            and plan.get('version')=='visual_image_jobs/v3' and plan['job_id']==expected_job_id
            and plan['graph_sha256']==digest(graph) and result.get('job_id')==expected_job_id
            and result.get('prompt_id')==pid and result.get('technical_status')=='saved'
            and result.get('graph_sha256')==plan['graph_sha256'] and result.get('inputs_sha256')==digest(plan['inputs'])
            and result.get('production_approved') is False,'actual_scene_start_success_graph_and_namespace_required')
    output=v['native_output'];rows=event['outputs'][output['node_id']]['images'];index=output['index'];row=rows[index]
    root=Path(plan['config']['output_root']).resolve();origin=(root/row.get('subfolder','')/row['filename']).resolve()
    require(row['type']=='output' and origin==Path(output['source_path']).resolve()
            and origin.is_relative_to(root/'visual_assets_v3'/expected_job_id)
            and bind(origin)==v['source_image'] and sha(origin)==image['sha256'] and checked(image,project).is_relative_to(run), 'scene_guide_actual_output_pixels_changed')
    def has(x):
        return (x.get('sha256')==image['sha256'] or any(has(y) for y in x.values())) if isinstance(x,dict) else any(has(y) for y in x) if isinstance(x,list) else False
    require(has(result),'scene_RESULT_must_bind_same_image')
    for row in plan['inputs']:
        require(sha(row['path'])==row['sha256']==sha(row['staged_path']), 'scene_image_generation_reference_pixels_changed')
    return bind(path)


def graph_pixel_routes(graph, normalized, guide, project=PROJECT):
    extra=guide is not None
    reduced=deepcopy(graph);rows=deepcopy(normalized)
    if extra:
        require(reduced.pop('scene_start',None)==dict(class_type='LoadImage',inputs={'image':guide['input_name']})
                and reduced['guide_start']['inputs']['image']==['scene_start',0], 'scene_cut_must_encode_independent_generated_stage_at_frame0')
        require(guide['image']==guide['staged'] or guide['image']['sha256']==guide['staged']['sha256'],'staged_guide_pixels_changed')
        require(base.rgb_bytes(checked(guide['image'],project))==base.rgb_bytes(checked(guide['staged'],project)),'scene_guide_source_staged_RGB_changed')
        reduced['guide_start']['inputs']['image']=[rows[-1]['node_id'],0]
    result=base.graph_pixel_routes(reduced,rows,project)
    result['actual_guide_image']=guide['image'] if extra else rows[-1]['source']
    result['guide_node']='scene_start' if extra else rows[-1]['node_id']
    result['actual_LoadImage_count']=len(rows)+(1 if extra else 0)
    result['scene_start_is_independent_of_previous_tail']=extra
    if extra:result['separate_guide']=guide
    return result


def prepared_graph(nr,sid,project=PROJECT):
    nr=Path(nr).resolve();p=read(nr/'PLAN.json');folder=nr/'shots'/sid;run=checked(p['series_plan'],project).parent
    series=series_inputs(run,project);entry=series['entries'][sid];selection=read(checked(series['plan']['library_selection'],project))['segments'][sid]
    require(nr==run/'visual_h3_v3'/(run.name+'_'+sid) and p.get('schema')==base.NATIVE_SCHEMA and p.get('upstream_contract')==base.INPUT_SCHEMA
            and p.get('production_approved') is False and p.get('publication') is False and p.get('full_video_quality_passed') is False
            and p.get('old_batch_resume') is False,'explicit_new_native_namespace_and_contract_required')
    require(len(p['shots'])==1 and p['shots'][0]['id']==sid,'one_native_segment_required');row=p['shots'][0]
    ip=checked(p['input'],project);require(ip==run/'segments'/sid/'LIBRARY_INPUT.json','actual_segment_input_required');c=read(ip)
    require(c.get('schema')==base.INPUT_SCHEMA and c.get('shot_id')==sid and c.get('publication') is False
            and c.get('continuation_contract')==VERSION and c.get('source_case')==p['source']==bind(run/'segments'/sid/'SOURCE_CASE.json')
            and c['entry_sha256']==digest(entry) and c.get('full_video_quality_passed') is False and c.get('production_approved') is False,'actual_source_input_changed_or_false_quality_claim')
    script=minimum_script(entry,c['script_fields'],sid,selection)
    require(c['required_actor_assets']==entry['full_clip_actor_ids'] and c['segment_selection']==selection,'full_cast_and_explicit_per_segment_selection_required')
    refs=c['references'];require(2<=len(refs)<=9,'nine_positive_ref_limit_no_truncation')
    require(c['library_binding']==series['plan']['library_binding'] and c['binding_approval']==series['plan']['binding_approval'],'same_confirmed_library_per_clip_required')
    library=library_reference_cards(c['library_binding'],refs[:-1],c['required_actor_assets'],selection,project)
    base.binding_confirmation(c['library_binding'],c['binding_approval'],library,project)
    resolution=c['library_resolution'];require(resolution['status']=='ready' and resolution['model_dispatch_allowed'] is True and len(resolution['references'])==len(refs)-1,'actual_library_resolution_required')
    for actual,original in zip(refs[:-1],resolution['references']): require({k:actual[k] for k in original}==original,'declared_library_resolution_changed')
    for actor in c['required_actor_assets']: require(resolution['character_descriptions'][actor]==library['cards'][actor]['card'],'version_matched_character_description_required')
    require(resolution['environment_description']==library['cards'][selection['place_id']]['card'],'version_matched_environment_description_required')
    prev=c['predecessor_result']
    if sid=='S01':
        origin=read(checked(series['plan']['continuation_origin'],project));final=read(checked(origin['preceding_final_result'],project))
        require(origin.get('schema')=='library_continuation_origin/v1' and prev==origin['native_result']==final['segments'][-1]['native_result']
                and final['all_segments_new'] is True and len(set(final['native_ids']))==4
                and [r['shot_id'] for r in final['segments']]==list(IDS), 'S01_must_follow_selected_last_original_of_previous_movie')
        checked(final['file'],project)
    else:require(checked(prev,project)==run/'visual_h3_v3'/(run.name+'_'+IDS[IDS.index(sid)-1])/'shots'/IDS[IDS.index(sid)-1]/'RESULT.json','immediate_predecessor_tail_required')
    prior=native_tail(prev,project);require(refs[-1]['image']==prior['image'] and refs[-1]['asset_id']=='native_tail:'+prior['native_id'],'actual_predecessor_tail_must_reach_reference')
    require(c['predecessor_receipt']['result_binding']==prev,'predecessor_receipt_binding_changed')
    image=c['first_image'];require(image==row['first_frame'] and base.rgb_bytes(checked(image,project))[0]==(736,1312),'real_current_guide_geometry_required')
    cut=selection['mode']=='scene_cut'
    if cut:
        require(refs[-1]['kind']=='previous_scene_context' and c['guide_kind']=='generated_scene','scene_cut_tail_is_context_only_not_current_room')
        scene_guide(run,selection,image,c['generation_receipt'],project)
    else:require(refs[-1]['kind']=='dynamic_guide' and image==prior['image'] and c['guide_kind']=='native_tail','same_scene_guide_must_be_real_last_frame')
    rp=checked(c['guide_review'],project);review=read(rp);visible=c['guide_visible_actor_ids'];world=c['world_actor_state']
    require(rp==run/'segments'/sid/'GUIDE_STATE_REVIEW.json' and review.get('schema')==base.STATE_SCHEMA
            and review['predecessor_result']==prev and review['guide_image']==image
            and review['world_actor_state']==world and review['guide_visible_actor_ids']==visible
            and review['completion_known'] is True and review['outcome_unknown'] is False
            and bool(review['reviewed_by']) and bool(review['evidence']) and len(visible)==len(set(visible))
            and set(visible)<=set(c['required_actor_assets']) and set(review['screen_identity_map'])==set(visible)
            and set(world)==set(c['required_actor_assets'])
            and all(isinstance(v,str) and v.strip() for v in [*world.values(),*review['screen_identity_map'].values()]),
            'actual_review_subset_must_not_filter_whole_segment_cast')
    proof={k:deepcopy(c[k]) for k in ('schema','source_case','first_image','predecessor_result','guide_review','library_binding','binding_approval','library_resolution','references','required_actor_assets','guide_visible_actor_ids','world_actor_state','script_fields','compiled_prompt_utf8_sha256')};proof['input']=p['input']
    require(row['library_input']==proof,'native_frozen_input_proof_changed')
    root=Path(p['config']['input_root']).resolve();normalized=[];require(len(row['reference_map'])==len(refs),'no_silent_reference_drop')
    for i,(actual,expected) in enumerate(zip(row['reference_map'],refs)):
        require({k:actual[k] for k in expected}==expected and actual['slot']==i and actual['tag']==f'<Picture {i+1}>','exact_actual_reference_mapping_required')
        staged=(root/actual['input_name']).resolve();require(staged.is_relative_to(root),'reference_scope_escaped')
        normalized.append(dict(slot=i,label=f'P{i+1}',source=expected['image'],staged=bind(staged),node_id=f'ref_{i}',input_name=actual['input_name']))
    guide=row.get('guide_map');actualguide=None
    if cut:
        require(guide==dict(image=image,input_name=row['scope']+'/scene_start.png') and row['input_name']==guide['input_name'],'scene_cut_separate_guide_map_required')
        actualguide=dict(guide,staged=bind(root/guide['input_name']))
    else:require(guide is None and row['input_name']==row['reference_map'][-1]['input_name'],'same_scene_no_independent_fabricated_stage')
    graph_path=folder/'workflow_api.json';graph=read(graph_path);routes=graph_pixel_routes(graph,normalized,actualguide,project)
    prompt=graph['condition']['inputs']['prompt'];expected=[s['text'][1:-1] for s in entry['source_spans'] if s['kind']=='audio']
    require(prompt==c['compiled_prompt'] and sha_text(prompt)==c['compiled_prompt_utf8_sha256'] and digest(graph)==row['graph_sha256']
            and base.quotes(prompt)==expected,'actual_source_quotes_or_prompt_changed')
    for item in library['cards'].values():require(item['card']['description'] in prompt,'actual_registered_description_not_sent')
    require((graph['124']['inputs']['steps'],graph['130']['inputs']['fps'],row['timing']['native_frames'],row['timing']['requested_seconds'])==(12,24,362,15),'native_profile_changed')
    for b in (p['series_plan'],p['base_workflow'],*p['code']):base.old_reference_qa.checked_code(b,project)
    return dict(nr=nr,folder=folder,plan=p,row=row,graph=graph,context=c,library=library,routes=routes,first_input=image,source=p['source'],script=script,entry=entry,
        binding=dict(plan=bind(nr/'PLAN.json'),input=p['input'],graph=bind(graph_path),series_plan=p['series_plan'],library_binding=c['library_binding'],binding_approval=c['binding_approval'],guide_review=bind(rp)))


def sha_text(text): return hashlib.sha256(text.encode()).hexdigest()


def for_run(run):
    """Clone only CPU media checks; no imported producer globals are modified."""
    require(sha(Path(base.__file__))==SEALED_BASE_QA,'sealed_base_CPU_QA_source_changed')
    run=Path(run).resolve();ns=dict(base.__dict__);ns['__file__']=__file__
    for name,f in list(ns.items()):
        if isinstance(f,types.FunctionType) and f.__module__==base.__name__:
            g=types.FunctionType(f.__code__,ns,f.__name__,f.__defaults__,f.__closure__);g.__kwdefaults__=f.__kwdefaults__;ns[name]=g
    ns.update(source_entry=source_entry,series_inputs=series_inputs,prepared_graph=prepared_graph)
    ns['EXPECTED_QUOTES']={sid:[s['text'][1:-1] for s in source_entry(bind(run/'segments'/sid/'SOURCE_CASE.json'),sid)['source_spans'] if s['kind']=='audio'] for sid in IDS}
    def prepared(value,project=PROJECT):
        result=series_inputs(value,project);rows=[]
        selection=read(checked(result['plan']['library_selection'],project))['segments']
        index=read(checked(result['plan']['library_binding'],project))
        for sid in IDS:
            # Validate every source/card even before upstream media exist.
            e=result['entries'][sid];sel=selection[sid];refs=[]
            for c in e['full_clip_actor_ids']:
                for v in sel['actor_views'][c]:
                    p=index['characters'][c]['images'][v];refs.append(dict(feature_card=index['characters'][c]['feature_card'],actor_id=c,**{k:p[k] for k in ('entity_id','kind','view','asset_id','version','design_version','identity_group','image')}))
            for v in sel['place_views']:
                p=index['places'][sel['place_id']]['images'][v];refs.append(dict(feature_card=index['places'][sel['place_id']]['feature_card'],actor_id=None,**{k:p[k] for k in ('entity_id','kind','view','asset_id','version','design_version','identity_group','image')}))
            lib=library_reference_cards(result['plan']['library_binding'],refs,e['full_clip_actor_ids'],sel,project)
            base.binding_confirmation(result['plan']['library_binding'],result['plan']['binding_approval'],lib,project)
            nr=Path(value)/'visual_h3_v3'/(Path(value).name+'_'+sid)
            if (nr/'PLAN.json').exists():
                x=prepared_graph(nr,sid,project);rows.append(dict(shot_id=sid,status='actual_prepared_graph_verified',binding=x['binding'],reference_count=len(x['context']['references']),actual_LoadImage_count=x['routes']['actual_LoadImage_count']))
            else:rows.append(dict(shot_id=sid,status='native_graph_not_prepared_yet',bound_library_refs=len(refs),whole_segment_actor_ids=e['full_clip_actor_ids']))
        return dict(status='CPU_prepared_inspection_complete',series_plan=result['plan_binding'],segments=rows,model_posts=0,GPU_calls=0,content_quality_passed=False)
    ns['validate_prepared']=prepared
    # The installed protocol is executed below with the real separate guide.
    src=ast.parse(inspect.getsource(base.cpu_source_protocol));fn=src.body[0]
    fn.args.kwonlyargs.append(ast.arg(arg='guide'));fn.args.kw_defaults.append(ast.Constant(None))
    # Replace only the guide tensor expression and expected guide labels. The
    # reference list remains the actual <=9 positive images.
    text=ast.unparse(fn)
    text=text.replace("require(images[-1][1] == (736, 1312), 'native_geometry_guide_image_required')", "guide_path = checked(guide if guide is not None else reference_rows[-1]['image'], project)\n    guide_size, guide_pixels = rgb_bytes(guide_path)\n    require(guide_size == (736, 1312), 'native_geometry_guide_image_required')\n    guide_tag = 'actual_frame0_guide'\n    guide_sha = hashlib.sha256(guide_pixels).hexdigest()")
    text=text.replace("image=tensors[f'ref_image_{count - 1}']", "image=Tensor(guide_tag, (1, guide_size[1], guide_size[0], 3), guide_sha)")
    text=text.replace('labels + [labels[-1]]','labels + [guide_tag]').replace('[labels[-1]] + labels','[guide_tag] + labels')
    exec(compile(text,__file__,'exec'),ns)
    require('actual_frame0_guide' in text and "image=Tensor(guide_tag" in text,'independent_guide_protocol_transform_required')
    # QA call supplies the row's true first_input rather than assuming P9.
    tree=ast.parse(inspect.getsource(base.qa))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='cpu_source_protocol':
            node.keywords.append(ast.keyword(arg='guide',value=ast.Subscript(value=ast.Name(id='row',ctx=ast.Load()),slice=ast.Constant('first_input'),ctx=ast.Load())))
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),ns)
    return types.SimpleNamespace(**ns)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--prepared',action='store_true');p.add_argument('--preview',choices=IDS);p.add_argument('--asr',action='store_true');a=p.parse_args(argv)
    q=for_run(a.run)
    value=q.validate_prepared(a.run) if a.prepared else q.preview_segment(a.run,a.preview) if a.preview else q.qa(a.run,asr=a.asr)
    if a.prepared:
        out=a.run/'independent_qa/CPU_PREPARED_QA.json';freeze(out,value);value=dict(status=value['status'],manifest=bind(out),segments=[{k:v for k,v in x.items() if k!='binding'} for x in value['segments']],model_posts=0)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
