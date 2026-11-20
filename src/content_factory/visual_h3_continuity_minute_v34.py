"""One new minute: actual native tail -> reviewed reanchor -> serial I2V.

Preparation/status are CPU only. Only tick/execute may contact the native local
service, and new submissions require frozen root approvals. An original native
ID is collected before current-source/approval checks; it is never replayed.
"""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import subprocess
import time

from . import visual_h3_continuity_input_v33 as core
from . import visual_h3_handoff_v3 as native
from . import visual_spatial_stills_v24 as stills
from . import visual_image_jobs_v3 as jobs
from . import visual_h3_prompt_parity_v19 as clock
from .visual_spatial_clock_v30 import clock_input

PROJECT=Path(__file__).resolve().parents[2]
RUN=PROJECT/'data/video_generation/h3_continuity_full_minute_20261109_v1'
SCHEMA='h3_continuity_minute/v34'
IDS=('S01','S02','S03','S04')
WIDTH,HEIGHT,FRAMES,FPS,DURATION,QUOTES=736,1312,362,24,15,10
BAD={'outcome_unknown','failed','interrupted','rejected','cancelled'}

class MinuteError(ValueError):pass

def read(path):return native.read(path)
def bind(path):return core.binding(path)
def check(value):return core.check(value)
def digest(value):return core.digest(value)
def freeze(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);native.freeze(path,value)
def _scope(run):
    run=Path(run).resolve()
    if run!=Path(RUN).resolve():raise MinuteError('explicit_new_minute_root_required')
    return run
def _folder(run,sid):
    if sid not in IDS:raise MinuteError('four_ordered_source_segments_required')
    return Path(run)/'segments'/sid
def _video_run(run,sid):return Path(run)/'visual_h3_v3'/(Path(run).name+'_'+sid)
def _still_run(run,sid):return Path(run)/'stills'/(Path(run).name+'_'+sid)
def _image_job(run,sid):return _still_run(run,sid)/'batches'/('reanchor_'+sid)
def _profile():return dict(width=WIDTH,height=HEIGHT,frames=FRAMES,fps=FPS,source_seconds=DURATION,steps=12,native_audio=True)

def _recovery(run):
    from . import visual_h3_service_exit_image_successor_v35 as recovery
    return recovery if recovery.has_context(run) else None

def _authority(value,source):
    a=core.read(value);limits=a.get('engineering_limits',{})
    if (a.get('schema')!='h3_continuity_minute_authorization/v34' or not a.get('user_statement')
            or a.get('upstream_spec')!=source or limits.get('video_submissions')!=4
            or type(limits.get('image_submissions')) is not int or not 4<=limits['image_submissions']<=8
            or limits.get('cloud_media')!=0 or a.get('publication') is not False or a.get('diagnostic') is not True
            or a.get('engineering_scope_not_user_quoted_numeric_limit') is not True):
        raise MinuteError('new_local_diagnostic_minute_authorization_required')
    if (a.get('text_model_calls',0)!=0 or a.get('unknown_native_replay',False) is not False
            or a.get('unknown_replays',False) is not False or a.get('automatic_semantic_video_retakes',False) is not False):raise MinuteError('no_text_calls_or_unknown_replay')
    return a

def _template(row):
    return {k:deepcopy(v) for k,v in row.items() if k not in ('actual_first_image','coverage_review','reanchor','handoff_binding')}

def _image_authority(root_binding,authority):
    return dict(schema='h3_continuity_image_authorization_projection/v34',root_authorization=root_binding,
        user_statement=authority['user_statement'],max_image_submissions=authority['engineering_limits']['image_submissions'],
        new_cloud_media_calls=0,publication=False,engineering_scope_not_user_quoted_numeric_limit=True,
        projection_only_no_new_user_authorization=True)

def _settings(spec,run):
    if spec.get('schema')!='h3_continuity_minute_spec/v34':raise MinuteError('new_minute_spec_required')
    source=spec['source_case'];rows=core._entries(source)
    if tuple(r['shot_id'] for r in rows)!=IDS or sum(len(r['audio']) for r in rows)!=QUOTES:raise MinuteError('four_sources_and_all_original_quotes_required')
    for row in rows:
        draft=core.compile_prompt(row)
        if not draft['source_coverage_complete'] or row['duration']!=DURATION:raise MinuteError('complete_source_and_camera_contract_required')
        if row['canonical_characters']!=rows[0]['canonical_characters'] or row['canonical_room']!=rows[0]['canonical_room']:raise MinuteError('one_canonical_cast_and_room_for_the_minute_required')
    cfg=deepcopy(spec['h3_config']);required=('service_url','input_root','output_root','gpu_lock_root','protected_pause_path','base_workflow')
    if any(k not in cfg for k in required) or cfg.get('video_enabled') is not True:raise MinuteError('explicit_shared_local_video_config_required')
    if cfg.get('width')!=WIDTH or cfg.get('height')!=HEIGHT or Path(cfg.get('runs_root','')).resolve()!=run/'visual_h3_v3':raise MinuteError('new_minute_h3_geometry_or_namespace_changed')
    base=read(cfg['base_workflow'])
    if set(base)!=set(native.CLASSES) or any(base[k]['class_type']!=v for k,v in native.CLASSES.items()) or base['124']['inputs']['steps']!=12 or base['130']['inputs']['fps']!=FPS:
        raise MinuteError('frozen_twelve_step_native_i2v_recipe_required')
    for value in spec['spatial'].values():check(value)
    if set(spec['spatial'])!={'handoff','render_result','inputs','config'} or set(spec['stage_items'])!=set(IDS):raise MinuteError('actual_spatial_source_and_per_segment_stages_required')
    core.image(spec['initial_context']['image'])
    image_cfg=stills._config(core.read(spec['spatial']['config']))
    base_cfg=dict(config=dict(image_service=image_cfg,gpu_lock_root=cfg['gpu_lock_root'],protected_pause_path=cfg['protected_pause_path']))
    cfg=native._config(base_cfg,cfg)
    if Path(cfg['gpu_lock_root'])!=(stills.ROOT/'data/visual_asset_pipeline/gpu').resolve():raise MinuteError('shared_image_and_video_gpu_mutex_required')
    if Path(image_cfg['protected_pause_path']).resolve()!=Path(cfg['protected_pause_path']):raise MinuteError('shared_original_pause_scope_required')
    return rows,cfg

def prepare(run=RUN):
    run=_scope(run);sp=bind(run/'MINUTE_SPEC.json');spec=core.read(sp);rows,cfg=_settings(spec,run)
    auth=bind(run/'USER_AUTHORIZATION.json');authority=_authority(auth,spec['source_case'])
    image_authority=run/'IMAGE_AUTHORIZATION_PROJECTION.json';freeze(image_authority,_image_authority(auth,authority))
    plan=dict(schema=SCHEMA,spec=sp,authorization=auth,source_case=spec['source_case'],profile=_profile(),
        image_authorization=bind(image_authority),
        config=cfg,base_workflow=bind(cfg['base_workflow']),protected_pause=bind(cfg['protected_pause_path']),
        templates={r['shot_id']:dict(path=str((run/'templates'/(r['shot_id']+'.json')).resolve()),sha256=None) for r in rows},
        publication=False,production_approved=False,old_batch_resume=False)
    for row in rows:
        path=run/'templates'/(row['shot_id']+'.json');freeze(path,_template(row));plan['templates'][row['shot_id']]=bind(path)
    freeze(run/'PLAN.json',plan)
    if not (run/'STATE.json').exists():native.write(run/'STATE.json',dict(schema=SCHEMA,plan_sha256=digest(plan),status='prepared'))
    return status(run)

def _load(run,current=False):
    run=_scope(run);plan=read(run/'PLAN.json')
    if (plan.get('schema')!=SCHEMA or plan.get('profile')!=_profile() or plan.get('publication') is not False
            or plan.get('old_batch_resume') is not False or read(run/'STATE.json').get('plan_sha256')!=digest(plan)):
        raise MinuteError('frozen_new_minute_plan_changed')
    if current:
        spec=core.read(plan['spec']);rows,cfg=_settings(spec,run);authority=_authority(plan['authorization'],plan['source_case'])
        if core.read(plan['image_authorization'])!=_image_authority(plan['authorization'],authority):raise MinuteError('image_authorization_projection_changed')
        if authority.get('old_pause',plan['protected_pause'])!=plan['protected_pause']:raise MinuteError('authorization_protected_pause_changed')
        if cfg!=plan['config'] or bind(cfg['base_workflow'])!=plan['base_workflow'] or bind(cfg['protected_pause_path'])!=plan['protected_pause']:raise MinuteError('frozen_recipe_or_protected_pause_changed')
        for row in rows:
            if core.read(plan['templates'][row['shot_id']])!=_template(row):raise MinuteError('source_template_changed')
    return run,plan

def _video_local(run,sid):
    folder=_video_run(run,sid)
    if not (folder/'PLAN.json').exists():return None
    _,plan=native._load(folder,current=False)
    if len(plan['shots'])!=1 or plan['shots'][0]['id']!=sid:raise MinuteError('one_native_segment_per_handoff_required')
    return native._shot_state(folder/'shots'/sid,plan,plan['shots'][0])

def _result(run,sid):
    state=_video_local(run,sid)
    if not state or state['status']!='technical_saved':return None
    path=_video_run(run,sid)/'shots'/sid/'RESULT.json';value=read(path)
    if value['timing']['native_frames']!=FRAMES or value['timing']['requested_seconds']!=DURATION:raise MinuteError('native_segment_clock_changed')
    return path,value

def status(run=RUN):
    run,plan=_load(run);rows=[];recovery=_recovery(run)
    for sid in IDS:
        folder=_folder(run,sid);job=_image_job(run,sid);video=_video_local(run,sid)
        image=jobs.status(job) if (job/'PLAN.json').exists() else None
        state='technical_saved' if video and video['status']=='technical_saved' else video['status'] if video else 'image_'+image['status'] if image else 'context_review_required' if (folder/'CONTEXT.json').exists() else 'awaiting_context' if sid==IDS[0] else 'awaiting_predecessor'
        protection=recovery.original_protection(run,sid) if recovery else None
        rows.append(dict(id=sid,status=state,image=image,video=video,context=bind(folder/'CONTEXT.json') if (folder/'CONTEXT.json').exists() else None,
            **(dict(recovery_image=recovery.view(run,sid),original_image_provider_outcome='unknown_after_service_exit' if protection['valid'] else None,
                original_image_poll_protected=protection['preserve_original'],original_protection_error=protection.get('error')) if recovery else {})))
    return dict(schema=SCHEMA,run=str(run),shots=rows,technical_saved=sum(r['status']=='technical_saved' for r in rows),
        paused=(run/'PAUSE.json').exists(),publication=False,production_approved=False,profile=plan['profile'])

def stage_context(run=RUN,sid='S01'):
    run,plan=_load(run,current=True);folder=_folder(run,sid);index=IDS.index(sid);spec=core.read(plan['spec'])
    if index:
        result=_result(run,IDS[index-1])
        if result is None:return dict(status='awaiting_predecessor',shot_id=sid,model_calls=0)
        path,value=result;image={k:value['files']['last'][k] for k in ('path','sha256')}
        origin=dict(kind='actual_previous_native_tail',previous_segment=IDS[index-1],native_result=bind(path),native_id=value['prompt_id'],role='last')
    else:image=spec['initial_context']['image'];origin=dict(kind='approved_initial_context_only',evidence=spec['initial_context'].get('origin'))
    core.image(image);template=core.read(plan['templates'][sid])
    context=dict(schema='h3_minute_actual_context/v34',shot_id=sid,image=image,origin=origin,source_template=plan['templates'][sid],
        role='continuity_context_not_automatic_identity_or_pose_truth')
    freeze(folder/'CONTEXT.json',context)
    request=dict(schema='h3_minute_context_review_request/v34',context=bind(folder/'CONTEXT.json'),target_image=image,
        canonical_characters=template['canonical_characters'],canonical_room=template['canonical_room'],
        source=template['source'],source_state_span_ids=template.get('source_state_span_ids',[]),review_not_yet_observed=True)
    if template.get('first_frame_policy'):
        from .visual_opening_frame import contract
        request['opening_frame']=contract(template)
    freeze(folder/'CONTEXT_REVIEW_REQUEST.json',request)
    return dict(status='context_review_required',shot_id=sid,context=bind(folder/'CONTEXT.json'),request=bind(folder/'CONTEXT_REVIEW_REQUEST.json'),model_calls=0)

def prepare_context_entry(run=RUN,sid='S01'):
    run,plan=_load(run,current=True);result=stage_context(run,sid);folder=_folder(run,sid)
    if result['status']=='awaiting_predecessor':return result
    review=folder/'CONTEXT_REVIEW.json'
    if not review.exists():return result
    context=read(folder/'CONTEXT.json');entry=core.read(plan['templates'][sid]);entry.update(handoff_binding=None,actual_first_image=context['image'],coverage_review=bind(review))
    value=dict(schema=core.SCHEMA,shots=[entry]);path=folder/'CONTEXT_SPEC.json';freeze(path,value)
    report=core.preflight(bind(path),sid);freeze(folder/'CONTEXT_PREFLIGHT.json',report)
    if report['status']=='reanchor_required':freeze(folder/'REANCHOR_WORK_ORDER.json',report['work_order'])
    return dict(report,context_spec=bind(path),model_calls=0)

def _anchor_prepared_contract(result):
    """Immutable recipe proof, separate from mutable native/budget observations."""
    saved=deepcopy(result);saved.pop('receipt_template',None);batch=saved['batch'];state=batch['state']
    batch['state']={key:state[key] for key in ('job_id','plan_sha256')}
    batch.pop('global_reserved_branches',None)
    return saved

def prepare_anchor(run=RUN,sid='S01'):
    run,plan=_load(run,current=True);report=prepare_context_entry(run,sid);folder=_folder(run,sid)
    if report['status']!='reanchor_required':return report
    review=folder/'SOURCE_STATE_REVIEW.json'
    if not review.exists():return dict(status='source_state_review_required',shot_id=sid,work_order=bind(folder/'REANCHOR_WORK_ORDER.json'))
    spec=core.read(plan['spec']);spatial=spec['spatial'];still=_still_run(run,sid)
    result=core.prepare_reanchor(bind(folder/'CONTEXT_SPEC.json'),sid,still,
        handoff=check(spatial['handoff']),render_result=check(spatial['render_result']),inputs=check(spatial['inputs']),
        authorization=check(plan['image_authorization']),config=check(spatial['config']),item_id=spec['stage_items'][sid],source_binding_review=bind(review))
    # An accepted ID changing state is not a change to the prepared recipe.
    # Legacy event records retain their exact bytes; compare only their stable
    # contract. Native status and the shared reservation count remain live.
    saved=_anchor_prepared_contract(result);record=folder/'ANCHOR_PREPARED.json'
    if record.exists():
        if _anchor_prepared_contract(read(record))!=saved:raise MinuteError('frozen_anchor_prepared_contract_changed')
    else:freeze(record,saved)
    return dict(status='image_prepared',shot_id=sid,native_job=bind(_image_job(run,sid)/'PLAN.json'),model_calls=0)

def _candidate(run,sid):
    job=_image_job(run,sid);result=read(job/'RESULT.json');batch=read(job/'BATCH.json')
    if result.get('technical_status')!='saved' or len(batch['item_ids'])!=1:raise MinuteError('one_actual_native_still_branch_required')
    name=batch['item_ids'][0];images=[x for x in result['images'] if x['save_node']==name+'__save']
    if len(images)!=1 or images[0]['dimensions']!=[WIDTH,HEIGHT]:raise MinuteError('actual_reanchor_geometry_changed')
    image=images[0];selected=dict(id=name,image={k:image[k] for k in ('path','sha256')},save_node=image['save_node'],prompt_id=result['prompt_id'],production_approved=False)
    value=dict(schema=stills.SCHEMA,batch=bind(job/'BATCH.json'),native_result=bind(job/'RESULT.json'),items=[selected],
        content_status='root_visual_review_required_before_video_guide',production_approved=False)
    freeze(job/'CANDIDATES.json',value)
    return selected

def _rejected_original(run,sid,work_sha):
    job=_image_job(run,sid);state=jobs.status(job)
    if state['status']!='saved':raise MinuteError('original_image_must_be_known_saved_before_successor_selection')
    original=_candidate(run,sid);path=_folder(run,sid)/'ROOT_ANCHOR_REJECTION.json';review=read(path)
    if (review.get('schema')!='h3_minute_anchor_rejection/v34' or review.get('decision')!='rejected'
            or review.get('original_native_result')!=bind(job/'RESULT.json') or review.get('original_image')!=original['image']
            or review.get('original_native_id')!=original['prompt_id'] or review.get('work_order_sha256')!=work_sha
            or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
            or not isinstance(review.get('reviewed_by'),str) or not review['reviewed_by'].strip()
            or not isinstance(review.get('evidence'),list) or not review['evidence'] or any(not isinstance(e,str) or not e.strip() for e in review['evidence'])):
        raise MinuteError('root_known_original_image_rejection_required')
    return original,bind(path)

def select_anchor(run,sid,receipt_binding,coverage_review):
    """Select one already-saved known-image successor; never makes a model call."""
    run,plan=_load(run,current=True);folder=_folder(run,sid);report=prepare_context_entry(run,sid)
    if (_video_run(run,sid)/'PLAN.json').exists():raise MinuteError('frozen_video_handoff_anchor_cannot_be_replaced')
    if report['status']!='reanchor_required':raise MinuteError('same_original_reanchor_work_order_required')
    original,rejection=_rejected_original(run,sid,report['work_order_sha256']);receipt=core.read(receipt_binding)
    if receipt.get('kind')!='spatial_still_v24':raise MinuteError('real_spatial_successor_receipt_required')
    successor=Path(receipt['run']).resolve()
    if successor.parent!=run/'stills' or successor==_still_run(run,sid):raise MinuteError('new_known_successor_inside_same_minute_required')
    _,p,job,b=stills._batch(successor,receipt['batch_id'])
    if p['source']['authorization']!=plan['image_authorization'] or jobs.status(job)['status']!='saved':raise MinuteError('same_projection_known_saved_successor_required')
    if read(successor/'REANCHOR_WORK_ORDER.json')!=read(folder/'REANCHOR_WORK_ORDER.json'):raise MinuteError('successor_cannot_change_original_tail_source_or_work_order')
    candidates=core.read(receipt['candidates']);matches=[x for x in candidates['items'] if x['id']==receipt['item_id']]
    if len(matches)!=1 or matches[0]['prompt_id']==original['prompt_id']:raise MinuteError('distinct_actual_successor_native_id_required')
    selected=matches[0];entry=deepcopy(core._entries(bind(folder/'CONTEXT_SPEC.json'))[0])
    entry['reanchor']=dict(image=selected['image'],coverage_review=coverage_review,work_order_sha256=report['work_order_sha256'],generation_receipt=receipt)
    qualified=core.evaluate(entry)
    if qualified['status']!='ready':raise MinuteError('successor_not_same_source_reviewed_ready')
    limits=budget(run)
    if limits['image_unknown_claims']:raise MinuteError('unknown_image_claim_blocks_successor_selection')
    value=dict(schema='h3_minute_known_anchor_selection/v34',context_spec=bind(folder/'CONTEXT_SPEC.json'),work_order_sha256=report['work_order_sha256'],
        original_rejection=rejection,receipt=receipt_binding,coverage_review=coverage_review,image=selected['image'],native_id=selected['prompt_id'],
        native_result=bind(job/'RESULT.json'),automatic_retry=False,production_approved=False)
    freeze(folder/'SELECTED_ANCHOR.json',value);_remember(run,sid,'image_successor',jobs.status(job),job)
    return dict(status='known_successor_selected',selection=bind(folder/'SELECTED_ANCHOR.json'),model_calls=0)

def prepare_video(run=RUN,sid='S01'):
    run,plan=_load(run,current=True);report=prepare_context_entry(run,sid);folder=_folder(run,sid)
    if report['status'] not in ('ready','reanchor_required'):return report
    entry=deepcopy(core._entries(bind(folder/'CONTEXT_SPEC.json'))[0])
    if report['status']=='reanchor_required':
        job=_image_job(run,sid)
        recovery=_recovery(run);service_exit_selection=None
        if recovery and recovery.configured(run,sid):
            phase=recovery.advance(run,sid)
            if phase['status']!='service_exit_selection_ready':return phase
            service_exit_selection=phase['selection']
        if service_exit_selection is None and not (job/'RESULT.json').exists():return prepare_anchor(run,sid)
        selection_path=folder/'SELECTED_ANCHOR.json'
        if service_exit_selection is not None:
            receipt=core.read(service_exit_selection['receipt']);review=check(service_exit_selection['coverage_review']);selected=dict(image=service_exit_selection['image'])
        elif selection_path.exists():
            selection=read(selection_path)
            if selection['context_spec']!=bind(folder/'CONTEXT_SPEC.json') or selection['work_order_sha256']!=report['work_order_sha256']:raise MinuteError('frozen_anchor_selection_source_changed')
            original,rejection=_rejected_original(run,sid,report['work_order_sha256'])
            if selection['original_rejection']!=rejection:raise MinuteError('known_original_rejection_changed')
            receipt=core.read(selection['receipt']);review=check(selection['coverage_review']);selected=dict(image=selection['image'])
        else:
            selected=_candidate(run,sid);review=folder/'ANCHOR_REVIEW.json'
            receipt=dict(kind='spatial_still_v24',run=str(_still_run(run,sid)),batch_id='reanchor_'+sid,
                item_id=selected['id'],candidates=bind(job/'CANDIDATES.json'),source_binding_review=bind(folder/'SOURCE_STATE_REVIEW.json'))
        request=dict(schema='h3_minute_anchor_review_request/v34',target_image=selected['image'],work_order=bind(folder/'REANCHOR_WORK_ORDER.json'),
            canonical_characters=entry['canonical_characters'],canonical_room=entry['canonical_room'],source_current_state_review_required=True)
        if entry.get('first_frame_policy'):
            from .visual_opening_frame import contract
            request['opening_frame']=contract(entry)
        freeze(folder/('SERVICE_EXIT_ANCHOR_REVIEW_REQUEST.json' if service_exit_selection is not None else 'SELECTED_ANCHOR_REVIEW_REQUEST.json' if selection_path.exists() else 'ANCHOR_REVIEW_REQUEST.json'),request)
        if not review.exists():return dict(status='anchor_review_required',shot_id=sid,candidate=selected)
        entry['reanchor']=dict(image=selected['image'],coverage_review=bind(review),work_order_sha256=report['work_order_sha256'],generation_receipt=receipt)
    else:
        reviewed=core.read(entry['coverage_review'])
        if reviewed.get('source_current_state_matches') is not True or reviewed.get('stage_matches') is not True:
            return dict(status='current_state_and_stage_review_required',shot_id=sid)
    actual=core.evaluate(entry)
    if actual['status']!='ready':return actual
    executable=folder/'EXECUTABLE_SPEC.json';freeze(executable,dict(schema=core.SCHEMA,shots=[entry]));cfg=deepcopy(plan['config'])
    video=_video_run(run,sid);value=native.prepare_from_continuity(bind(executable),video,cfg)
    row=read(video/'PLAN.json')['shots'][0];graph=read(video/'shots'/sid/'workflow_api.json')
    if ((graph['condition']['inputs']['width'],graph['condition']['inputs']['height'],graph['condition']['inputs']['length'],graph['124']['inputs']['steps'],graph['130']['inputs']['fps'])!=(WIDTH,HEIGHT,FRAMES,12,FPS)
            or row['timing']['requested_seconds']!=DURATION or graph['condition']['class_type']!='MiniMaxH3ImageToVideo'
            or 'last_frame' in graph['condition']['inputs'] or set(graph)!=set(native.CLASSES)):
        raise MinuteError('prepared_native_recipe_changed')
    freeze(folder/'VIDEO_PREPARED.json',dict(schema=SCHEMA,context=bind(folder/'CONTEXT.json'),context_spec=bind(folder/'CONTEXT_SPEC.json'),
        executable_spec=bind(executable),native_plan=bind(video/'PLAN.json'),graph=bind(video/'shots'/sid/'workflow_api.json'),selected_first=actual['first_image'],
        prompt_utf8_sha256=actual['compiled_prompt_utf8_sha256'],direct_reference_slots=0))
    freeze(folder/'VIDEO_BINDING.json',dict(schema='h3_continuity_minute_video_binding/v34',segment=sid,shot_id=sid,h3_run=str(video.resolve()),
        segment_spec=bind(executable),h3_plan=bind(video/'PLAN.json'),context=bind(folder/'CONTEXT.json'),selected_first=actual['first_image'],
        prompt_utf8_sha256=actual['compiled_prompt_utf8_sha256'],actual_seed=graph['129']['inputs']['noise_seed'],
        seed_policy='sealed_v33_shot_binding_and_first_image_sha_derived_not_legacy_seed_replay'))
    return dict(status='video_prepared',shot_id=sid,handoff=value,native_plan=bind(video/'PLAN.json'),model_calls=0)

def advance(run=RUN):
    """Only local CPU preparation; never polls or submits a native request."""
    run,plan=_load(run,current=True)
    for sid in IDS:
        state=_video_local(run,sid)
        if state and state['status']=='technical_saved':continue
        if state:return dict(status='video_prepared' if state['status']=='prepared' else state['status'],shot_id=sid,model_calls=0)
        return prepare_video(run,sid)
    return dict(status='four_native_segments_saved',model_calls=0)

def _sources():
    return dict(coordinator=bind(__file__),cli=bind(PROJECT/'scripts/run_h3_continuity_minute_v34.py'),
        core=bind(core.__file__),handoff=bind(native.__file__),stills=bind(stills.__file__),image_jobs=bind(jobs.__file__),
        assembly_clock=bind(clock.__file__),native_clock=bind(Path(__file__).with_name('visual_spatial_clock_v30.py')))

def _launch(run,plan):
    recovery=_recovery(run);source=_sources();name='ROOT_LAUNCH_APPROVAL.json'
    if recovery and (run/recovery.OPT).exists():
        recovery.verified(run);name='ROOT_LAUNCH_APPROVAL_REVISION_V35.json'
        source.update(service_exit_image_recovery=bind(recovery.__file__),service_exit_image_recovery_cli=bind(PROJECT/'scripts/run_h3_service_exit_image_successor_v35.py'))
        if (run/'ROOT_LAUNCH_APPROVAL_REVISION_V35_R3.json').exists():name='ROOT_LAUNCH_APPROVAL_REVISION_V35_R3.json'
    value=read(run/name)
    if name=='ROOT_LAUNCH_APPROVAL_REVISION_V35_R3.json' and value.get('prior_launch')!=bind(run/'ROOT_LAUNCH_APPROVAL_REVISION_V35.json'):
        raise MinuteError('root_prior_frozen_service_exit_launch_binding_changed')
    if (value.get('schema')!='h3_continuity_minute_launch_approval/v34' or value.get('plan')!=bind(run/'PLAN.json')
            or value.get('authorization')!=plan['authorization'] or value.get('approved_for_new_media') is not True
            or value.get('execution_sources')!=source):raise MinuteError('root_launch_or_execution_sources_not_approved')
    if name!='ROOT_LAUNCH_APPROVAL.json' and value.get('service_exit_recovery_opt_in')!=bind(run/recovery.OPT):raise MinuteError('root_service_exit_launch_revision_binding_changed')
    acceptance=check(value['cpu_acceptance'])
    if not acceptance.is_relative_to(PROJECT/'data/qa') or acceptance.suffix!='.json':raise MinuteError('project_cpu_acceptance_binding_required')
    return value

def approval_request(run=RUN,sid='S01',kind='image'):
    run,plan=_load(run,current=True);folder=_folder(run,sid)
    if kind=='image':
        job=_image_job(run,sid);expected=dict(native_plan=bind(job/'PLAN.json'),graph=bind(job/'workflow_api.json'),
            context_spec=bind(folder/'CONTEXT_SPEC.json'),work_order=bind(folder/'REANCHOR_WORK_ORDER.json'),source_state_review=bind(folder/'SOURCE_STATE_REVIEW.json'))
    elif kind=='video':
        video=_video_run(run,sid);expected=dict(native_plan=bind(video/'PLAN.json'),graph=bind(video/'shots'/sid/'workflow_api.json'),
            executable_spec=bind(folder/'EXECUTABLE_SPEC.json'),video_prepared=bind(folder/'VIDEO_PREPARED.json'))
    else:raise MinuteError('image_or_video_stage_required')
    return dict(schema='h3_continuity_minute_stage_approval/v34',kind=kind,shot_id=sid,plan=bind(run/'PLAN.json'),
        authorization=plan['authorization'],inputs=expected,approved_for_dispatch=None,reviewed_by=None,evidence=[])

def _stage_approval(run,sid,kind):
    expected=approval_request(run,sid,kind);value=read(_folder(run,sid)/('ROOT_'+kind.upper()+'_APPROVAL.json'))
    for key in ('schema','kind','shot_id','plan','authorization','inputs'):
        if value.get(key)!=expected[key]:raise MinuteError('root_stage_approval_binding_changed')
    if (value.get('approved_for_dispatch') is not True or not isinstance(value.get('reviewed_by'),str) or not value['reviewed_by'].strip()
            or not isinstance(value.get('evidence'),list) or not value['evidence'] or any(not isinstance(x,str) or not x.strip() for x in value['evidence'])):
        raise MinuteError('root_actual_stage_review_required')

def budget(run=RUN):
    run,plan=_load(run);auth=_authority(plan['authorization'],plan['source_case']);images=[];videos=[]
    if core.read(plan['image_authorization'])!=_image_authority(plan['authorization'],auth):raise MinuteError('image_authorization_projection_changed')
    unknown=0;raw_unknown=0;recovery=_recovery(run);disposed=recovery.verified(run) if recovery else {}
    for f in (run/'stills').glob('*/batches/*/BATCH.json'):
        batch=read(f);parent=f.parents[2];p=read(parent/'PLAN.json')
        if p['source']['authorization']!=plan['image_authorization']:raise MinuteError('foreign_image_authorization_in_new_minute')
        check(batch['native_plan']);g=read(f.parent/'workflow_api.json');count=sum(n['class_type']=='SaveImage' for n in g.values())
        if count!=len(batch['item_ids']):raise MinuteError('image_budget_branch_changed')
        state=jobs.status(f.parent)
        disposed_original=any(f.parent==_image_job(run,sid) for sid in disposed)
        if (state['status']=='outcome_unknown' or disposed_original) and (f.parent/'CLAIM.json').exists():raw_unknown+=count
        if state['status']=='outcome_unknown' and (f.parent/'CLAIM.json').exists() and not disposed_original:unknown+=count
        images.append(dict(batch=bind(f),reserved=count,claimed=count if (f.parent/'CLAIM.json').exists() else 0))
    for sid in IDS:
        folder=_video_run(run,sid)/'shots'/sid
        if (folder/'CLAIM.json').exists():videos.append(dict(shot_id=sid,claim=bind(folder/'CLAIM.json')))
    if sum(x['reserved'] for x in images)>auth['engineering_limits']['image_submissions'] or len(videos)>4:raise MinuteError('new_authorization_budget_exceeded')
    return dict(image_reserved=sum(x['reserved'] for x in images),image_claimed=sum(x['claimed'] for x in images),image_unknown_claims=unknown,
        **(dict(image_unknown_claims_raw=raw_unknown,explicit_service_exit_dispositions=len(disposed)) if recovery else {}),video_claimed=len(videos),images=images,videos=videos,limits=auth['engineering_limits'])

def _remember(run,sid,kind,state,path):
    pid=state.get('prompt_id')
    if not pid:return
    native.slug(pid);folder=run/'native_ids';folder.mkdir(exist_ok=True)
    for old in folder.glob('*.json'):
        item=read(old)
        if item['native_id']==pid and (item['shot_id'],item['kind'])!=(sid,kind):raise MinuteError('native_id_reused_between_new_segments')
    value=dict(shot_id=sid,kind=kind,native_id=pid,native_plan=bind(Path(path)/'PLAN.json'))
    freeze(folder/(kind+'_'+sid+'.json'),value)
    wanted=kind+':'+sid+' '+pid;ledger=run/'job_ids.txt';lines=ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else []
    if wanted not in lines:
        with ledger.open('a',encoding='utf-8') as stream:stream.write(wanted+'\n');stream.flush()
        with (run/'LOG.md').open('a',encoding='utf-8') as stream:stream.write(f'\n- {time.time()} NATIVE {wanted}\n')

def collect_known(run=RUN):
    run,plan=_load(run);recovery=_recovery(run)
    if recovery:recovery.collect_known(run)
    # Current opt-in/approval is irrelevant to collection of frozen native IDs.
    # Complete every known video first, before examining any image protection.
    for sid in IDS:
        state=_video_local(run,sid)
        if state:
            if state.get('prompt_id') and state['status'] not in ('technical_saved','failed','interrupted','rejected'):
                native.poll_collect(_video_run(run,sid));state=_video_local(run,sid)
            _remember(run,sid,'video',state,_video_run(run,sid))
    errors=[]
    for sid in IDS:
        job=_image_job(run,sid)
        if (job/'PLAN.json').exists():
            state=jobs.status(job)
            protection=recovery.original_protection(run,sid) if recovery else None
            preserve_original=protection and protection['preserve_original']
            if protection and protection.get('error'):errors.append(dict(shot_id=sid,**protection))
            if not preserve_original and state.get('prompt_id') and state['status'] not in ('saved','failed','interrupted','rejected','cancelled'):
                if state['status']!='native_complete':state=jobs.poll(job)
                if state['status']=='native_complete':jobs.collect(job);state=jobs.status(job)
            if state['status']=='saved':_candidate(run,sid)
            _remember(run,sid,'image',state,job)
    value=status(run)
    if errors:
        native.write(run/'COLLECTION_INPUT_INVALID.json',dict(at=time.time(),errors=errors,new_dispatch_blocked=True))
        value['collection_input_errors']=errors
    return value

def tick(run=RUN,*,allow_submit=False):
    if type(allow_submit) is not bool:raise MinuteError('explicit_submit_boolean_required')
    run,plan=_load(run)
    with jobs.run_lock(run,'COORDINATOR_STEP.lock'):
        current=collect_known(run)
        if current['technical_saved']==4:return assemble(run)
        if current.get('collection_input_errors'):return dict(current,dispatch='blocked_collection_configuration')
        recovery=_recovery(run)
        try:disposed=recovery.verified(run,live=allow_submit) if recovery else {}
        except (OSError,ValueError,KeyError) as error:
            value=dict(status='blocked_current_inputs',error=dict(type=type(error).__name__,message=str(error)),original_ids_preserved=True,new_dispatch_blocked=True)
            native.write(run/'INPUT_INVALID.json',value);return value
        if any((row['video'] and row['video']['status'] in BAD) or (row['image'] and row['image']['status'] in BAD and row['id'] not in disposed)
            or (row.get('recovery_image') and row['recovery_image']['status'] in BAD) for row in current['shots']):return dict(current,dispatch='native_terminal_or_unknown_preserved')
        if current['paused']:return dict(current,dispatch='paused_no_new_media')
        try:phase=advance(run)
        except (OSError,ValueError,KeyError) as error:
            value=dict(status='blocked_current_inputs',error=dict(type=type(error).__name__,message=str(error)),original_ids_preserved=True)
            native.write(run/'INPUT_INVALID.json',value);return value
        if not allow_submit:return phase
        sid=phase.get('shot_id');stage=phase['status']
        if stage not in ('image_prepared','video_prepared','service_exit_image_prepared'):return phase
        _load(run,current=True);_launch(run,plan)
        if budget(run)['image_unknown_claims']:return dict(current,dispatch='native_terminal_or_unknown_preserved')
        if stage=='service_exit_image_prepared':
            if not (_folder(run,sid)/'ROOT_SERVICE_EXIT_IMAGE_APPROVAL.json').exists():return dict(phase,dispatch='root_service_exit_image_approval_required')
            recovery.submit_successor(run,sid);return status(run)
        kind='image' if stage=='image_prepared' else 'video'
        approval=_folder(run,sid)/('ROOT_'+kind.upper()+'_APPROVAL.json')
        if not approval.exists():return dict(phase,dispatch='root_'+kind+'_approval_required')
        _stage_approval(run,sid,kind)
        if kind=='image':
            job=_image_job(run,sid);state=jobs.status(job)
            if state['status']!='prepared':return dict(phase,dispatch='original_image_id_only')
            stills.tick(_still_run(run,sid),'reanchor_'+sid);state=jobs.status(job);_remember(run,sid,kind,state,job)
        else:
            if budget(run)['video_claimed']>=4:raise MinuteError('four_new_video_posts_maximum')
            native.submit_next(_video_run(run,sid));state=_video_local(run,sid);_remember(run,sid,kind,state,_video_run(run,sid))
        return status(run)

def assemble(run=RUN):
    run,plan=_load(run)
    with jobs.run_lock(run,'ASSEMBLY.lock'):
        rows=[_result(run,sid) for sid in IDS]
        if any(r is None for r in rows):raise MinuteError('four_saved_new_native_segments_required')
        values=[v for _,v in rows];ids=[v['prompt_id'] for v in values];videos=[v['files']['video'] for v in values]
        if len(set(ids))!=4 or len({v['sha256'] for v in videos})!=4:raise MinuteError('four_distinct_native_video_results_required')
        inputs=dict(plan=bind(run/'PLAN.json'),results=[bind(p) for p,_ in rows]);source_hash=digest(inputs)
        final=run/'FINAL_RESULT.json';output=run/'H3_CONTINUITY_MINUTE_736x1312.mp4'
        if final.exists():
            value=read(final);check(value['file'])
            if value['assembly_inputs_sha256']!=source_hash:raise MinuteError('frozen_assembly_sources_changed')
            return value
        if output.exists():raise MinuteError('unreceipted_final_movie_preserved')
        adjustments=[clock_input(v['path'],v['sha256'],frames=FRAMES,width=WIDTH,height=HEIGHT) for v in videos]
        filters=run/'ASSEMBLY_FILTER.txt';command,text=clock.assembly_command([v['path'] for v in videos],filters,output,frames=FRAMES)
        filters.write_text(text,encoding='utf-8');freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,adjustments=adjustments,command=command))
        process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(process.stderr,encoding='utf-8');process.check_returncode()
        timing=clock.verify_clock(clock._probe(output,count=True),frames=4*FRAMES,width=WIDTH,height=HEIGHT)
        if [bind(p) for p,_ in rows]!=inputs['results']:raise MinuteError('native_results_changed_during_cpu_assembly')
        value=dict(schema=SCHEMA,file=bind(output),native_ids=ids,clock=timing,assembly_inputs_sha256=source_hash,
            segment_results=[bind(p) for p,_ in rows],source_videos=[{k:v[k] for k in ('path','sha256')} for v in videos],
            task_mode='source_bound_reanchored_first_only_i2v',direct_reference_slots=0,diagnostic_preview=True,production_approved=False,publication=False)
        freeze(final,value);return value

def execute(run=RUN,poll_seconds=20,max_seconds=86400):
    if not 1<=poll_seconds<=60 or not 0<max_seconds<=172800:raise MinuteError('bounded_poll_window_required')
    run,plan=_load(run);started=time.monotonic()
    with jobs.run_lock(run,'RUNNER.lock'):
        while True:
            value=tick(run,allow_submit=True)
            if value.get('file') or value.get('status') in ('blocked_current_inputs','context_review_required','source_state_review_required','anchor_review_required','service_exit_anchor_review_required','current_state_and_stage_review_required') or value.get('dispatch') in ('native_terminal_or_unknown_preserved','root_image_approval_required','root_video_approval_required','root_service_exit_image_approval_required'):
                return value
            current=status(run)
            active=any((r['image'] and r['image']['status'] in ('submitted','running','queued') and r.get('original_image_provider_outcome') is None)
                or (r.get('recovery_image') and r['recovery_image']['status'] in ('submitted','running','queued')) or (r['video'] and r['video']['status'] in ('submitted','running','queued')) for r in current['shots'])
            if current['paused'] and not active:return value
            if time.monotonic()-started>=max_seconds:return dict(current,dispatch='bounded_wait_original_ids_preserved')
            time.sleep(poll_seconds)
