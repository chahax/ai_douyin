"""One explicit F0012 capacity amendment, never a general review-budget reset.

The two known original failures remain immutable. Only their completed blind
observations and actor reviews are reused; one new room MODEL and, if it passes,
one target style review are authorized. No image or video is generated here.
"""
from copy import deepcopy
import json
from pathlib import Path
import time

import psutil

from . import visual_asset_pipeline_v3 as p
from . import visual_asset_review_v3 as v
from . import visual_residence_review_v5 as dispatcher
from . import visual_split_observation_v14 as split

VERSION='first_frame_known_capacity_extension/v17'
SHOT='F0012'
TARGET='2f5cced600ce164e5729d204ec0f35ef1a99962907eed002d7e38d4af4ac800d'
ERROR='local visual output exhausted limit without completion marker'


def artifact(path):return dict(path=str(Path(path).resolve()),sha256=p.file_sha(path))
def _sidecar(run):return Path(run).resolve()/'known_capacity_extension_v17'/SHOT


def _verify_files(files):
    for item in files:
        if p.file_sha(item['path'])!=item['sha256']:raise ValueError('capacity_original_evidence_changed')


def _exit(folder,request):
    exit=p.read(folder/'WORKER_EXIT.json');runtime=p.read(folder/'WORKER_RUNTIME.json')
    state=p.read(folder/'WORKER_STATE.json')
    if (exit.get('exited') is not True or exit.get('code')!=0 or state.get('stage')!='completed'
            or exit.get('request_binding_sha256')!=request['request_binding_sha256']
            or runtime.get('request_binding_sha256')!=request['request_binding_sha256']):
        raise ValueError('capacity_original_worker_not_known_exited')
    for pid in (runtime['pid'],runtime['ppid']):
        try:
            process=psutil.Process(pid)
            if process.create_time()>exit['at']:continue # A different, later process owns the reused PID.
        except psutil.NoSuchProcess:continue
        except Exception as error:raise ValueError('capacity_original_exit_unconfirmed') from error
        raise ValueError('capacity_original_worker_still_exists')


def _known_attempt(folder):
    request=p.read(folder/'REQUEST.json');saved=p.read(folder/'RESULTS.json');prepared=request['prepared'];values=saved['results']
    binding=v.digest(dict(config=request['config'],requests=prepared))
    if (len(prepared)!=3 or len(values)!=3 or request['config'].get('max_tokens')!=1800
            or request['request_binding_sha256']!=binding or saved.get('request_binding_sha256')!=binding
            or saved.get('results_sha256')!=v.digest(values)
            or p.read(folder/'CLAIM.json').get('request_binding_sha256')!=binding):
        raise ValueError('capacity_original_batch_binding_invalid')
    _exit(folder,request)
    for item,value in zip(prepared,values):
        v._unchanged(item)
        if (item['target']['sha256']!=TARGET or value.get('target_sha256')!=TARGET
                or value.get('binding_sha256')!=v.digest(item) or value.get('completion_known') is not True
                or value.get('outcome_unknown') is not False):raise ValueError('capacity_original_batch_unknown_or_changed')
    if any(x.get('decision')!='accepted' or any(c is not True for c in x['checks'].values()) for x in values[:2]):
        raise ValueError('capacity_requires_two_accepted_actor_reviews')
    room=values[2];item=folder/'item_0002'
    error=p.read(item/'MODEL_ERROR.json')
    if (room.get('decision')!='unavailable' or room.get('error_type')!='ReviewProtocolError' or room.get('error')!=ERROR
            or error.get('message')!=ERROR or error.get('completion_known') is not True or (item/'MODEL_NATIVE.json').exists()
            or not split.enabled(prepared[2]['expectation'])):
        raise ValueError('capacity_requires_known_room_length_failure')
    # Every prior native claim must have either its completed native or this one
    # known MODEL error. An unresolved extra call cannot be hidden in the batch.
    for claim in folder.rglob('*_CLAIM.json'):
        stem=claim.name[:-len('_CLAIM.json')]
        if p.read(claim).get('request_sha256')!=v.digest(p.read(claim.with_name(stem+'_REQUEST.json'))):
            raise ValueError('capacity_original_native_claim_changed')
        if not claim.with_name(stem+'_NATIVE.json').exists():
            if claim!=item/'MODEL_CLAIM.json':raise ValueError('capacity_prior_native_outcome_unknown')
    if not all((item/name).is_file() for name in ('PEOPLE_REQUEST.json','PEOPLE_NATIVE.json','FURNITURE_REQUEST.json',
            'FURNITURE_NATIVE.json','FURNITURE_NORMALIZATION.json')):
        raise ValueError('capacity_missing_completed_blind_observation')
    def no_inference(_):raise ValueError('capacity_missing_completed_blind_observation')
    blind,scope=split.observe(prepared[2],no_inference,item)
    if blind['observations']['people_count'] is None or any(o['count'] is None for o in blind['object_observations'].values()):
        raise ValueError('capacity_blind_observation_unknown')
    from . import visual_furniture_taxonomy_v12 as taxonomy
    _,proof=taxonomy.recheck(blind['object_observations'],prepared[2]['target'],no_inference,item,observation_scope=scope)
    if proof is not None:raise ValueError('capacity_scope_does_not_include_taxonomy_successor')
    return request,values


def prepare_extension(run,*,authorization):
    """CPU-only preflight and immutable sidecar; never changes STATE or PLAN."""
    run=Path(run).resolve();side=_sidecar(run)
    if (authorization.get('scope')!=VERSION or authorization.get('authorized_by')!='root_task'
            or not str(authorization.get('reason','')).strip()):raise ValueError('explicit_capacity_authorization_required')
    with p.images.run_lock(run):
        if (side/'PLAN.json').exists():return _current(run)
        plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json');frame=state.get('first_frames',{}).get(SHOT,{})
        if (frame.get('sha256')!=TARGET or frame.get('review_attempts')!=2 or plan['config'].get('max_review_attempts',2)!=2
                or state.get('status')!='blocked_first_frame_review' or frame.get('review',{}).get('outcome_unknown') is not False
                or any(j.get('status')!='collected' for j in state.get('jobs',{}).values())):
            raise ValueError('capacity_case_not_exact_two_known_attempts')
        base=run/'first_frame_reviews'/frame['binding_sha256']/TARGET
        original=[];files=[artifact(run/'PLAN.json'),artifact(run/'SHOT_BINDINGS.json'),artifact(frame['path'])]
        for attempt in (0,1):
            folder=base/str(attempt);request,values=_known_attempt(folder)
            original.append(dict(folder=str(folder),request=request,results=values))
            files.extend(artifact(f) for f in folder.rglob('*') if f.is_file() and 'cache' not in f.relative_to(folder).parts and 'temp' not in f.relative_to(folder).parts)
        if original[0]['request']!=original[1]['request']:
            raise ValueError('capacity_original_attempt_inputs_differ')
        room=original[1]['request']['prepared'][2]
        if (frame['environment_guide']['sha256']!=room['layout_guide']['sha256']
                or frame['review']['subreviews']!=original[1]['results']
                or Path(frame['path']).resolve()!=Path(room['target']['path']).resolve()
                or p.file_sha(frame['path'])!=TARGET):raise ValueError('capacity_current_frame_not_original')
        source=plan['packet']['source'];source_file=artifact(source['path'])
        if source_file['sha256']!=source['sha256']:raise ValueError('capacity_original_source_changed')
        files.append(source_file)
        config=deepcopy(original[1]['request']['config']);config['max_tokens']=4096
        shot=next(s for s in p.read(run/'SHOT_BINDINGS.json')['shots'] if s['id']==SHOT)
        place=next(a for a in shot['references'] if a['kind']=='place');entity=p._entity(plan,place)
        # Binding the existing READY/source is read-only; no master/source review.
        bundle=p._style_reference_for_entity(run,plan,entity)
        if not bundle:raise ValueError('capacity_existing_style_reference_required')
        from . import visual_residence_style_v5 as residence
        style_request=residence.target_request(bundle,entity,frame['path'])
        p.freeze(side/'ORIGINAL_STATE.json',state)
        files.append(artifact(side/'ORIGINAL_STATE.json'))
        value=dict(schema=VERSION,run=str(run),shot_id=SHOT,target_sha256=TARGET,authorization=deepcopy(authorization),
            original_state_sha256=p.file_sha(run/'STATE.json'),original_plan_sha256=p.file_sha(run/'PLAN.json'),
            original_attempts=2,additional_room_reviews=1,additional_target_style_reviews=1,total_composition_attempts=3,
            review_config=config,original=original,files=files,room_prepared=room,shot=shot,place_entity=entity,
            target_style_request=style_request,created_at=time.time(),publication=False,production_approved=False)
        p.freeze(side/'PLAN.json',value)
        return value


def _current(run):
    side=_sidecar(run);value=p.read(side/'PLAN.json')
    if value.get('schema')!=VERSION or value['run']!=str(Path(run).resolve()) or value['target_sha256']!=TARGET:
        raise ValueError('capacity_extension_scope_changed')
    _verify_files(value['files'])
    if (p.file_sha(Path(run)/'STATE.json')!=value['original_state_sha256']
            or p.file_sha(Path(run)/'PLAN.json')!=value['original_plan_sha256']):raise ValueError('capacity_current_frame_CAS_changed')
    for old in value['original']:_exit(Path(old['folder']),old['request'])
    return value


def _prepared(request):
    value=deepcopy(request)
    if value.get('schema')!=VERSION:raise ValueError('capacity_worker_scope_invalid')
    _unchanged(value)
    return value


def _unchanged(prepared):
    _verify_files(prepared['files']);v._unchanged(prepared['room_prepared'])


def _unavailable(prepared,error,model=None,**kwargs):
    value=v._unavailable(prepared['room_prepared'],error,model,**kwargs)
    value['original_room_binding_sha256']=value['binding_sha256'];value['binding_sha256']=v.digest(prepared)
    return value


def _review_one(prepared,infer,model,folder):
    """Only MODEL can invoke infer. Original blind natives stay at original paths."""
    room=prepared['room_prepared'];old=Path(prepared['original_folder'])/'item_0002'
    def forbidden(_):raise v.ReviewProtocolError('capacity_reuse_must_not_dispatch_blind_observations')
    blind,scope=split.observe(room,forbidden,old)
    payload=p.read(old/'MODEL_REQUEST.json')
    if payload['images']!=[dict(role='target',binding=room['target']),dict(role='reference',binding=room['reference']),dict(role='layout_guide',binding=room['layout_guide'])]:
        raise v.ReviewProtocolError('capacity_room_model_sources_changed')
    raw=v._native_call(infer,payload,folder,'MODEL')
    observed=v.validate_observation(v._parse_content(raw['text']),room['expectation'])
    observed['observations']=deepcopy(blind['observations']);observed['rois']=deepcopy(blind['rois'])
    observed['evidence']=blind['evidence']+observed['evidence']
    observed['object_observations']=deepcopy(blind['object_observations']);observed['split_observation']=scope
    result=v._finish(room,observed,model,[])
    result['original_room_binding_sha256']=result['binding_sha256'];result['binding_sha256']=v.digest(prepared)
    result['capacity_extension']=dict(schema=VERSION,original_room_folder=str(old),primary_only=True,actual_model_calls=1)
    return result


def execute_extension(run):
    """One room MODEL plus one target style if accepted. Unknown is never replayed."""
    side=_sidecar(run);value=_current(run)
    if (side/'RESULT.json').exists():return p.read(side/'RESULT.json')
    request=dict(schema=VERSION,room_prepared=value['room_prepared'],original_folder=value['original'][1]['folder'],files=value['files'])
    client=v.VisualReviewClient(value['review_config']);plan=p.read(Path(run)/'PLAN.json')
    with p.gpu_access(plan):
        with p.images.run_lock(run):
            _current(run)
            if (Path(run)/'PAUSE.json').exists():raise ValueError('capacity_run_paused')
            try:
                with (side/'EXECUTION_CLAIM.json').open('x',encoding='utf-8') as stream:
                    json.dump(dict(plan_sha256=p.file_sha(side/'PLAN.json'),at=time.time()),stream)
            except FileExistsError as error:raise v.ReviewOutcomeUnknown('capacity successor already claimed; no replay') from error
        room=dispatcher.review(client,request,evidence_dir=side/'room_review',backend=__import__(__name__,fromlist=['_review_one']))
        style=None
        if room['decision']=='accepted' and not (Path(run)/'PAUSE.json').exists():
            style=p._residence_style_review(Path(run),plan,value['place_entity'],value['room_prepared']['target']['path'],client,side/'target_style_review')
            if style is None or style['request']!=value['target_style_request']:raise ValueError('capacity_target_style_binding_changed')
    result=dict(schema=VERSION,plan_sha256=p.file_sha(side/'PLAN.json'),room=room,style=style,
        completion_known=room.get('completion_known') is True and (style is None or style['result'].get('completion_known') is True),production_approved=False)
    p.freeze(side/'RESULT.json',result);return result


def verify_applied(review):
    """Durable qualification for pipeline/H3; no current STATE hash dependency."""
    proof=review.get('capacity_extension_proof')
    if isinstance(proof,dict) and proof.get('scope')=='first_frame_compact_room_successor/v18':
        from .visual_room_contract_successor_v18 import verify_applied as compact_verify
        return compact_verify(review)
    if proof is None:
        def marked(value):
            if not isinstance(value,dict):return False
            return (value.get('capacity_extension',{}).get('schema')==VERSION or 'original_room_binding_sha256' in value
                or marked(value.get('layout_review')) or any(marked(x) for x in value.get('subreviews',[])))
        if marked(review):raise ValueError('capacity_persistent_proof_required')
        return
    if proof.get('scope')!=VERSION:raise ValueError('capacity_persistent_scope_changed')
    _verify_files([proof['plan'],proof['result'],*proof['native_artifacts']])
    plan=p.read(proof['plan']['path']);side=_sidecar(plan['run'])
    if Path(proof['plan']['path']).resolve()!=side/'PLAN.json' or Path(proof['result']['path']).resolve()!=side/'RESULT.json':
        raise ValueError('capacity_persistent_path_changed')
    _verify_files(plan['files']);v._unchanged(plan['room_prepared'])
    result=p.read(proof['result']['path']);receipt=p.read(side/'APPLIED.json')
    if (result.get('plan_sha256')!=proof['plan']['sha256'] or receipt.get('capacity_proof_sha256')!=v.digest(proof)
            or receipt.get('target_sha256')!=review.get('target_sha256') or receipt.get('result')!=proof['result']
            or receipt.get('total_composition_attempts')!=3 or receipt.get('original_attempts')!=2):
        raise ValueError('capacity_persistent_receipt_changed')
    layout=review.get('layout_review',review)
    if (layout.get('subreviews')!=plan['original'][1]['results'][:2]+[result['room']]
            or review.get('style_review')!=result['style'] or result['room'].get('decision')!='accepted'):
        raise ValueError('capacity_persistent_accepted_result_changed')


def apply_extension(run):
    """CAS append only after complete room AND style acceptance; no PLAN edits."""
    run=Path(run).resolve();side=_sidecar(run)
    with p.images.run_lock(run):
        if (side/'APPLIED.json').exists():
            receipt=p.read(side/'APPLIED.json')
            if p.file_sha(run/'STATE.json')!=receipt['state_sha256']:raise ValueError('capacity_applied_state_changed')
            return receipt
        value=_current(run);result=p.read(side/'RESULT.json');room=result['room'];style=result['style']
        if (result['plan_sha256']!=p.file_sha(side/'PLAN.json') or room.get('decision')!='accepted'
                or room.get('completion_known') is not True or room.get('outcome_unknown') is not False
                or not style or style['result'].get('decision')!='accepted'
                or style['result'].get('completion_known') is not True or style['result'].get('outcome_unknown') is not False
                or any(x is not True for x in room['checks'].values())):raise ValueError('capacity_successor_not_fully_accepted')
        plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json');frame=state['first_frames'][SHOT]
        prepared=dict(schema=VERSION,room_prepared=value['room_prepared'],original_folder=value['original'][1]['folder'],files=value['files'])
        saved=p.read(side/'room_review/RESULTS.json')
        if saved['results']!=[room] or saved['results_sha256']!=v.digest([room]) or room['binding_sha256']!=v.digest(prepared):
            raise ValueError('capacity_successor_native_receipt_changed')
        native=p.read(side/'room_review/item_0000/MODEL_NATIVE.json')
        if native.get('completion_marker_present') is not True or native.get('finish_reason')!='stop':
            raise ValueError('capacity_successor_requires_actual_completion_marker')
        def no_inference(_):raise ValueError('capacity_apply_cannot_dispatch_model')
        replay=_review_one(prepared,no_inference,room['model_binding'],side/'room_review/item_0000')
        if replay!=room:raise ValueError('capacity_room_result_differs_from_actual_native')
        style_saved=p.read(side/'target_style_review/RESULTS.json')
        if style_saved.get('results')!=[style['result']] or style_saved.get('results_sha256')!=v.digest([style['result']]):
            raise ValueError('capacity_target_style_result_changed')
        stem='APPEARANCE' if style['request'].get('binding',{}).get('reference_contract')=='appearance/v1' else 'STYLE'
        style_native=p.read(side/'target_style_review/item_0000'/(stem+'_NATIVE.json'))
        if style_native.get('completion_marker_present') is not True or style_native.get('finish_reason')!='stop':
            raise ValueError('capacity_target_style_requires_actual_completion_marker')
        combined=deepcopy(frame['review']);parts=deepcopy(value['original'][1]['results'][:2])+[room]
        combined.update(subreviews=parts,decision='accepted',completion_known=True,outcome_unknown=False,retryable=False,
            checks={key:all(x.get('checks',{}).get(key,True) is True for x in parts) for key in combined['checks']},
            issues=[i for x in parts for i in x.get('issues',[])],evidence=[e for x in parts for e in x.get('evidence',[])],
            visual_evidence=[e for x in parts for e in x.get('visual_evidence',[])])
        for key in ('object_observations','split_observation','observations','layout_object_inventory','furniture_observation_scope'):
            if key in room:combined[key]=deepcopy(room[key])
        combined=p._consume_layout_inventory(combined,p._review_layout_inventory(plan,value['place_entity']))
        combined=p._combine_residence_style(combined,style)
        p._verify_residence_style_receipt(run,plan,value['place_entity'],frame['path'],combined)
        p._verify_first_frame_inventory_contents(plan,value['place_entity'],combined)
        p._verify_first_frame_generation(plan,value['shot'],frame)
        if combined['decision']!='accepted':raise ValueError('capacity_combined_not_accepted')
        proof=dict(plan=artifact(side/'PLAN.json'),result=artifact(side/'RESULT.json'),scope=VERSION,
            native_artifacts=[artifact(f) for folder in (side/'room_review',side/'target_style_review')
                for f in folder.rglob('*') if f.is_file() and 'cache' not in f.relative_to(folder).parts and 'temp' not in f.relative_to(folder).parts])
        combined['capacity_extension_proof']=deepcopy(proof)
        frame.setdefault('review_history',[]).append(deepcopy(frame['review']));frame['review']=combined
        frame.update(original_review_attempts=2,capacity_extension_attempts=1,review_attempts=3,
            capacity_extension=proof)
        state['status']='first_frame_capacity_review_completed';p.write(run/'STATE.json',state)
        receipt=dict(schema=VERSION,shot_id=SHOT,target_sha256=TARGET,original_attempts=2,additional_room_reviews=1,
            additional_target_style_reviews=1,total_composition_attempts=3,state_sha256=p.file_sha(run/'STATE.json'),
            result=artifact(side/'RESULT.json'),capacity_proof_sha256=v.digest(proof),at=time.time(),production_approved=False)
        p.freeze(side/'APPLIED.json',receipt);return receipt
