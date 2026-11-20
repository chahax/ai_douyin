"""CPU-only same-scene input materializer after a real immediate predecessor.

No transport, staging, model execution, ASR or service controls are exposed.
The guide review and initial states are upstream explicit actual observations;
this writer validates their provenance and never reads a portrait to infer pose.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import h3_active_contact_v1 as contact
from src.content_factory import shot_actor_continuity_v1 as continuity
from src.content_factory import visual_image_jobs_v3 as jobs

VERSION='h3_same_scene_materialization/v1'
INITIAL_STATES='same_scene_initial_states/v1'
STATE_TEMPLATE='universal_pending_state_plan_template/v1'
INPUT_TEMPLATE='universal_pending_asset_flow_input_template/v1'
SPEC_KEYS=('source_case','library_binding','binding_approval','base_workflow','place','voice','profile')


class MaterializationError(ValueError):pass


def require(ok,message):
    if not ok:raise MaterializationError(message)
def checked(binding):return flow.core.check(binding)
def bound(binding):return flow.read(checked(binding))
def notice(code,**data):return dict(schema=VERSION,status=code,model_calls=0,ASR_calls=0,HTTP_calls=0,
    physical_staging_performed=False,production_ready=False,**data)


def _same_native_graph(expected,actual):
    value=deepcopy(actual)
    for node,key,integer in [('124','denoise',1),('130','fps',24)]:
        before=expected.get(node,{}).get('inputs',{}).get(key);after=value.get(node,{}).get('inputs',{}).get(key)
        if type(before) is int and before==integer and type(after) is float and after==integer:value[node]['inputs'][key]=before
    return flow.digest(value)==flow.digest(expected)


def _templates(run,sid):
    catalog=flow.read(run/'ORIGINALS.json');design=flow.read(run/'inputs/SOURCE_CATALOG.json')
    series=bound(design['series_plan']);require(checked(design['series_plan'])==run/'PLAN.json','this_run_series_plan_required')
    series_rows=series['sources'];require(isinstance(series_rows,list),'explicit_ordered_series_sources_required')
    order=[r['shot_id'] for r in series_rows];source_by_id={r['shot_id']:r['source_case'] for r in series_rows}
    require(len(order)==len(set(order)) and sid in order and order.index(sid)>0,'same_scene_nonfirst_shot_required')
    predecessor=order[order.index(sid)-1]
    require(catalog.get('scene_modes',{}).get(sid)=='same_scene','declared_same_scene_mode_required')
    input_path=run/'segments'/sid/'INPUT_SPEC_TEMPLATE.json';input_template=flow.read(input_path)
    state_path=checked(input_template['state_plan_template']);state_template=flow.read(state_path)
    require(state_path==run/'segments'/sid/'STATE_PLAN_TEMPLATE.json','this_shot_state_template_required')
    require(input_template.get('schema')==INPUT_TEMPLATE and state_template.get('schema')==STATE_TEMPLATE
        and state_template.get('shot_id')==sid and input_template.get('awaiting_predecessor_shot_id')==predecessor
        and Path(input_template['expected_predecessor_run']).resolve()==run,'explicit_current_template_and_immediate_predecessor_required')
    source=catalog['source_cases'][sid]
    require(source==input_template['source_case']==state_template['source_origin']==design['segments'][sid]['runtime_source_origin_copy'],
        'source_catalog_revision_requires_explicit_new_template_and_adoption')
    checked(source);checked(design['segments'][sid]['series_plan_source'])
    require(source_by_id[sid]==design['segments'][sid]['series_plan_source'],'series_plan_original_source_binding_changed')
    entries=flow.core._entries(source);require(len(entries)==1 and entries[0]['shot_id']==sid,'one_bound_source_entry_required')
    entry=entries[0];req=flow.core.validate_entry(entry)
    require(req['source_coverage_complete'],'complete_bound_source_required')
    return catalog,design,predecessor,input_template,state_template,entry,dict(
        originals=flow.bind(run/'ORIGINALS.json'),source_catalog=flow.bind(run/'inputs/SOURCE_CATALOG.json'),
        series_plan=design['series_plan'],input_template=flow.bind(input_path),state_template=flow.bind(state_path),source_case=source)


def _predecessor(run,predecessor,result_binding,review,cast,catalog):
    expected=run/'visual_h3_v3'/(run.name+'_'+predecessor)/'shots'/predecessor/'RESULT.json'
    require(checked(result_binding)==expected,'only_this_run_immediate_predecessor_result_allowed')
    result=flow.read(expected);folder=expected.parent;nr=folder.parents[1]
    plan=flow.read(nr/'PLAN.json');rows=[r for r in plan['shots'] if r['id']==predecessor]
    require(len(rows)==1,'one_exact_predecessor_shot_required');row=rows[0]
    state=flow.read(folder/'STATE.json');graph=flow.read(folder/'workflow_api.json');request=flow.read(folder/'REQUEST.json')
    response=flow.read(folder/'RESPONSE.json');history=flow.read(folder/'HISTORY.json');pid=result.get('prompt_id')
    require(pid and pid not in catalog.get('prior_native_ids',[]) and result.get('shot_id')==predecessor
        and result.get('technical_status')=='technical_saved' and result.get('publication') is False
        and result.get('production_approved') is False and state.get('id')==predecessor
        and state.get('prompt_id')==pid and state.get('status')=='technical_saved'
        and state.get('plan_sha256')==flow.digest(plan) and response.get('prompt_id')==pid,'known_fresh_saved_predecessor_required')
    require(set(result.get('files',{}))=={'video','audio','first','last'}
        and flow.digest(graph)==row['graph_sha256']==result.get('graph_sha256')
        and _same_native_graph(graph,request['prompt']),'predecessor_four_originals_and_exact_graph_required')
    event=history.get(pid,{})
    require(event.get('status',{}).get('completed') is True and event['status'].get('status_str')=='success'
        and len(event.get('prompt',[]))>2 and event['prompt'][1]==pid
        and _same_native_graph(graph,event['prompt'][2]),'predecessor_native_success_history_required')
    image={k:result['files']['last'][k] for k in ('path','sha256')}
    require(review.get('guide_image')==image and review.get('predecessor_result')==result_binding,'same_actual_tail_review_required')
    guide=dict(image=image,native_result=result_binding,review=review)
    verified=flow.verify_guide(guide,cast)
    originals={role:dict(local={k:item[k] for k in ('path','sha256')},source=flow.bind(item['source_path'])) for role,item in result['files'].items()}
    return guide,dict(native_id=pid,native_plan=flow.bind(nr/'PLAN.json'),graph=flow.bind(folder/'workflow_api.json'),
        records={name:flow.bind(folder/(name+'.json')) for name in ('RESULT','STATE','REQUEST','RESPONSE','HISTORY')},
        originals=originals,verified_guide=verified)


def _initial(envelope,review,result_binding,image,template,cast):
    require(envelope.get('schema')==INITIAL_STATES and envelope.get('predecessor_result')==result_binding
        and envelope.get('guide_image')==image,'same_actual_tail_initial_states_required')
    states=envelope.get('states');observations=envelope.get('observations')
    require(isinstance(states,dict) and set(states)==set(cast) and isinstance(observations,dict) and set(observations)==set(cast),
        'explicit_full_cast_actual_states_and_observations_required')
    visible=review['guide_visible_actor_ids']
    for cid in cast:
        require(not continuity._state_errors(cid,states[cid]) and states[cid]['instance_id']==template['actor_instance_ids'][cid],
            'same_primary_actor_and_complete_initial_state_required')
        observation=observations[cid]
        require(observation.get('posture') in ('visible','occluded','offscreen')
            and isinstance(observation.get('evidence'),str) and observation['evidence'].strip(),'actual_posture_observation_evidence_required')
        if states[cid]['posture']!='unknown':
            require(cid in visible and observation['posture']=='visible','occluded_or_offscreen_posture_must_remain_unknown')
        if observation['posture'] in ('occluded','offscreen'):
            require(states[cid]['posture']=='unknown','occluded_or_offscreen_posture_must_remain_unknown')
    return deepcopy(states)


def materialize(run,shot_id,predecessor_binding,review_binding,initial_states_binding,output_dir):
    run=Path(run).resolve();out=Path(output_dir).resolve()
    require(isinstance(shot_id,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',shot_id),'safe_explicit_shot_id_required')
    require(out.is_relative_to(run/'segments'/shot_id) and out!=run/'segments'/shot_id,'fresh_shot_output_subdirectory_required')
    _,_,expected_predecessor,_,_,_,_=_templates(run,shot_id)
    expected_path=run/'visual_h3_v3'/(run.name+'_'+expected_predecessor)/'shots'/expected_predecessor/'RESULT.json'
    require(Path(predecessor_binding['path']).resolve()==expected_path,'only_this_run_immediate_predecessor_result_allowed')
    if not Path(predecessor_binding['path']).exists():return notice('awaiting_actual_saved_predecessor',shot_id=shot_id)
    try:
        with jobs.run_lock(run/'segments'/shot_id,'SAME_SCENE_MATERIALIZER.lock'):
            catalog,design,predecessor,it,st,entry,inputs=_templates(run,shot_id)
            review=bound(review_binding);envelope=bound(initial_states_binding);cast=entry['full_clip_actor_ids']
            guide,proof=_predecessor(run,predecessor,predecessor_binding,review,cast,catalog)
            states=_initial(envelope,review,predecessor_binding,guide['image'],st,cast)
            basis=dict(guide_image=guide['image'],native_result=predecessor_binding,guide_review_sha256=flow.digest(review))
            state=dict(schema=continuity.STATE_PLAN,initial=states,initial_basis=basis,
                source_actions=deepcopy(st['source_actions']),beats=deepcopy(st['source_action_beats']),
                source_scope=dict(source_case=it['source_case'],state_template=inputs['state_template'],
                    actual_initial_observations=initial_states_binding,actual_guide_review=review_binding,
                    writer_does_not_infer_pose_or_contact=True))
            carried=continuity.carry_states(cast,entry['camera_beats'],entry['audio'],entry['source_spans'],state)
            require(carried['status']=='ready','source_state_carry_not_ready:'+json.dumps(carried['notices'],ensure_ascii=False))
            for target,computed in zip(state['beats'],carried['state_plan_result']['beats']):
                target['asserted_states']={cid:{k:deepcopy(computed['after'][cid][k]) for k in continuity.STATE_FIELDS} for cid in cast}
            cp=None;resolved=None
            if it.get('contact_plan_materialization_required') is True:
                cp=deepcopy(bound(it['historical_contact_plan_comparison_only']));cp['initial_basis']=deepcopy(basis)
                resolved=contact.resolve(dict(schema=contact.CASE,entry=entry,state_plan=state,guide=guide),cp)
                require(resolved['status']=='ready','explicit_actual_contact_not_ready:'+json.dumps(resolved['notices'],ensure_ascii=False))
                if resolved['entry']!=entry:
                    return notice('needs_explicit_source_catalog_revision',shot_id=shot_id,changes=resolved['changes'],source_case=it['source_case'])
            request=dict(schema=VERSION,shot_id=shot_id,run=str(run),inputs=inputs,predecessor=predecessor_binding,
                review=review_binding,initial_states=initial_states_binding,writer=flow.bind(__file__),
                historical_contact_template=it.get('historical_contact_plan_comparison_only'))
            if out.exists() and (out/'MATERIALIZATION_REQUEST.json').exists():
                require(flow.read(out/'MATERIALIZATION_REQUEST.json')==request,'changed_inputs_require_new_materialization_directory')
            flow.freeze(out/'MATERIALIZATION_REQUEST.json',request)
            state_binding=flow.freeze(out/'STATE_PLAN.json',state)
            flow.freeze(out/'GUIDE_REVIEW.json',review);flow.freeze(out/'GUIDE.json',guide)
            spec={k:deepcopy(it[k]) for k in SPEC_KEYS};spec.update(schema=flow.SCHEMA,guide=guide,state_plan=state_binding)
            if cp is not None:
                spec['contact_plan']=flow.freeze(out/'CONTACT_PLAN.json',cp)
                flow.freeze(out/'CONTACT_RESOLVED.json',resolved)
                flow.freeze(out/'CONTACT_RENDERED.json',contact.render_contacts(resolved,entry['character_names']))
            spec_binding=flow.freeze(out/'INPUT_SPEC.json',spec)
            offline=flow.prepare(spec_binding['path'],out/'offline')
            require(offline['status']=='offline_draft_valid','complete_offline_compile_not_ready:'+json.dumps(offline,ensure_ascii=False))
            validation=flow.validate(out/'offline')
            require(validation['status']=='offline_draft_verified','complete_offline_validation_required')
            result=dict(schema=VERSION,status='same_scene_input_materialized',shot_id=shot_id,
                request=flow.bind(out/'MATERIALIZATION_REQUEST.json'),source_case=it['source_case'],state_plan=state_binding,
                input_spec=spec_binding,guide=flow.bind(out/'GUIDE.json'),predecessor_proof=proof,offline=offline,validation=validation,
                contact_plan=spec.get('contact_plan'),source_catalog_modified=False,future_source_prepared=False,
                semantic_observations_supplied_by_caller=True,portrait_inference_performed=False,
                model_calls=0,ASR_calls=0,HTTP_calls=0,physical_staging_performed=False,production_ready=False)
            return dict(result,receipt=flow.freeze(out/'MATERIALIZED.json',result))
    except MaterializationError:raise
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
        raise MaterializationError('invalid_same_scene_materialization:'+str(error)) from error


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('run','shot','predecessor-binding','review-binding','initial-states-binding','out'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args(argv)
    value=materialize(args.run,args.shot,flow.read(args.predecessor_binding),flow.read(args.review_binding),flow.read(args.initial_states_binding),args.out)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
