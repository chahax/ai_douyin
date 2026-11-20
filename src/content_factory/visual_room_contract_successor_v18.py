"""F0012-only compact-contract successor after the evidenced v17 repetition.

This is a separately authorized contract, not an automatic capacity increase.
The original two attempts and the failed v17 attempt remain immutable.
"""
from copy import deepcopy
import json
from pathlib import Path
import time

from . import visual_known_capacity_extension_v17 as old
from . import visual_room_compare_v18 as room_contract
from . import visual_asset_pipeline_v3 as p
from . import visual_asset_review_v3 as v
from . import visual_residence_review_v5 as dispatcher
from . import visual_split_observation_v14 as split

VERSION='first_frame_compact_room_successor/v18'
LOOP='The adult\u2019s face is visible. The child\u2019s face is visible. The adult\u2019s clothing is visible. The child\u2019s clothing is visible. The adult\u2019s hands are visible. The child\u2019s hands are visible.'


def _sidecar(run):return Path(run).resolve()/'known_room_contract_successor_v18'/old.SHOT


def _parent(run):
    value=old._current(run);side=old._sidecar(run)
    if (side/'APPLIED.json').exists():raise ValueError('compact_successor_cannot_replace_applied_parent')
    result=p.read(side/'RESULT.json');folder=side/'room_review';request=p.read(folder/'REQUEST.json')
    if (folder/'item_0000/MODEL_NATIVE.json').exists() or ((side/'target_style_review').exists() and any((side/'target_style_review').rglob('*'))):
        raise ValueError('compact_successor_parent_has_conflicting_or_style_activity')
    old._exit(folder,request);native=p.read(folder/'item_0000/MODEL_INCOMPLETE_NATIVE.json')
    error=p.read(folder/'item_0000/MODEL_ERROR.json');raw=native['native'];saved=p.read(folder/'RESULTS.json')
    expected=dict(schema=old.VERSION,room_prepared=value['room_prepared'],original_folder=value['original'][1]['folder'],files=value['files'])
    binding=v.digest(dict(config=value['review_config'],prepared=expected))
    original_model=value['original'][1]['request']['model_binding']
    if (request.get('prepared')!=[expected] or request.get('config')!=value['review_config']
            or request.get('request_binding_sha256')!=binding or saved.get('request_binding_sha256')!=binding
            or result['room'].get('binding_sha256')!=v.digest(expected)
            or result['room'].get('target_sha256')!=old.TARGET
            or result['room'].get('reference_sha256')!=value['room_prepared']['reference']['sha256']
            or result['room'].get('layout_guide_sha256')!=value['room_prepared']['layout_guide']['sha256']
            or any(request.get('model_binding',{}).get(k)!=original_model.get(k) for k in ('model','config_sha256','index_sha256','shards'))
            or p.read(folder/'item_0000/MODEL_REQUEST.json')!=p.read(Path(value['original'][1]['folder'])/'item_0002/MODEL_REQUEST.json')
            or p.read(folder/'item_0000/MODEL_CLAIM.json').get('request_sha256')!=native.get('request_sha256')):
        raise ValueError('compact_successor_parent_source_binding_changed')
    if (result.get('plan_sha256')!=p.file_sha(side/'PLAN.json') or result.get('style') is not None
            or result['room'].get('decision')!='unavailable' or result['room'].get('error')!=old.ERROR
            or result['room'].get('completion_known') is not True or result['room'].get('outcome_unknown') is not False
            or saved.get('results')!=[result['room']] or saved.get('results_sha256')!=v.digest(saved['results'])
            or error.get('completion_known') is not True or error.get('incomplete_native_sha256')!=p.file_sha(folder/'item_0000/MODEL_INCOMPLETE_NATIVE.json')
            or native.get('request_sha256')!=v.digest(p.read(folder/'item_0000/MODEL_REQUEST.json'))
            or raw.get('finish_reason')!='max_tokens' or raw.get('completion_marker_present') is not False
            or raw.get('usage',{}).get('completion_tokens')!=4096 or raw.get('text','').count(LOOP)<3):
        raise ValueError('compact_successor_requires_exact_known_v17_loop_failure')
    return value,result


def prepare_successor(run,*,authorization):
    if (authorization.get('scope')!=VERSION or authorization.get('authorized_by')!='root_task'
            or not str(authorization.get('reason','')).strip()):raise ValueError('explicit_compact_successor_authorization_required')
    run=Path(run).resolve();side=_sidecar(run)
    with p.images.run_lock(run):
        if (side/'PLAN.json').exists():return _current(run)
        parent,failure=_parent(run);value=deepcopy(parent);source=parent['room_prepared']
        exp=deepcopy(source['expectation']);exp['room_comparison_scope']=room_contract.SCOPE
        prepared=v._prepared(dict(target=source['target']['path'],reference=source['reference']['path'],
            layout_guide=source['layout_guide']['path'],expectation=exp))
        if any(prepared[k]!=source[k] for k in ('target','reference','layout_guide')):
            raise ValueError('compact_successor_sources_changed')
        previous=old._sidecar(run)
        value.update(schema=VERSION,authorization=deepcopy(authorization),original_attempts=3,original_legacy_attempts=2,
            total_composition_attempts=4,room_prepared=prepared,blind_prepared=source,created_at=time.time(),
            v17_failure=deepcopy(failure),parent_plan=old.artifact(previous/'PLAN.json'),parent_result=old.artifact(previous/'RESULT.json'))
        value['files']+= [old.artifact(f) for f in previous.rglob('*') if f.is_file()
            and 'cache' not in f.relative_to(previous).parts and 'temp' not in f.relative_to(previous).parts]
        p.freeze(side/'PLAN.json',value);return value


def _current(run):
    value=p.read(_sidecar(run)/'PLAN.json')
    if value.get('schema')!=VERSION or value.get('total_composition_attempts')!=4:raise ValueError('compact_successor_scope_changed')
    old._verify_files(value['files']);_parent(run)
    if p.file_sha(Path(run)/'STATE.json')!=value['original_state_sha256']:raise ValueError('compact_successor_current_frame_CAS_changed')
    return value


def _prepared(request):
    if request.get('schema')!=VERSION:raise ValueError('compact_successor_worker_scope_invalid')
    value=deepcopy(request);_unchanged(value);return value


def _unchanged(prepared):old._verify_files(prepared['files']);v._unchanged(prepared['room_prepared'])


def _unavailable(prepared,error,model=None,**kwargs):
    result=v._unavailable(prepared['room_prepared'],error,model,**kwargs)
    result['original_room_binding_sha256']=v.digest(prepared['blind_prepared']);result['binding_sha256']=v.digest(prepared)
    return result


def _review_one(prepared,infer,model,folder):
    source=prepared['blind_prepared'];room=prepared['room_prepared'];original=Path(prepared['original_folder'])/'item_0002'
    def forbidden(_):raise v.ReviewProtocolError('compact successor cannot redispatch blind observations')
    blind,scope=split.observe(source,forbidden,original)
    payload=room_contract.payload(room,blind);raw=v._native_call(infer,payload,folder,'MODEL')
    observed=room_contract.observation(v._parse_content(raw['text']),blind)
    observed.update(observations=deepcopy(blind['observations']),object_observations=deepcopy(blind['object_observations']),split_observation=scope,
        room_comparison=dict(schema=room_contract.VERSION,prepared=deepcopy(room),blind=deepcopy(blind),
            request=old.artifact(Path(folder)/'MODEL_REQUEST.json'),native=old.artifact(Path(folder)/'MODEL_NATIVE.json')))
    result=v._finish(room,observed,model,[])
    result.update(original_room_binding_sha256=v.digest(source),binding_sha256=v.digest(prepared),
        capacity_extension=dict(schema=VERSION,primary_only=True,actual_model_calls=1))
    return result


def execute_successor(run):
    run=Path(run).resolve();side=_sidecar(run);value=_current(run)
    if (side/'RESULT.json').exists():return p.read(side/'RESULT.json')
    request={k:value[k] for k in ('room_prepared','blind_prepared','files')}
    request.update(schema=VERSION,original_folder=value['original'][1]['folder'])
    client=v.VisualReviewClient(value['review_config']);plan=p.read(run/'PLAN.json')
    with p.gpu_access(plan):
        with p.images.run_lock(run):
            _current(run)
            if (run/'PAUSE.json').exists():raise ValueError('compact_successor_run_paused')
            try:
                with (side/'EXECUTION_CLAIM.json').open('x',encoding='utf-8') as f:json.dump(dict(plan_sha256=p.file_sha(side/'PLAN.json'),at=time.time()),f)
            except FileExistsError as e:raise v.ReviewOutcomeUnknown('compact successor already claimed; no replay') from e
        room=dispatcher.review(client,request,evidence_dir=side/'room_review',backend=__import__(__name__,fromlist=['_review_one']))
        style=None
        if room['decision']=='accepted' and not (run/'PAUSE.json').exists():
            style=p._residence_style_review(run,plan,value['place_entity'],value['room_prepared']['target']['path'],client,side/'target_style_review')
            if style is None or style['request']!=value['target_style_request']:raise ValueError('compact_successor_target_style_changed')
    result=dict(schema=VERSION,plan_sha256=p.file_sha(side/'PLAN.json'),room=room,style=style,
        completion_known=room.get('completion_known') is True and (style is None or style['result'].get('completion_known') is True),production_approved=False)
    p.freeze(side/'RESULT.json',result);return result


def verify_applied(review):
    proof=review['capacity_extension_proof']
    if proof.get('scope')!=VERSION:raise ValueError('compact_successor_persistent_scope_changed')
    old._verify_files([proof['plan'],proof['result'],*proof['native_artifacts']]);value=p.read(proof['plan']['path']);side=_sidecar(value['run'])
    old._verify_files(value['files']);v._unchanged(value['room_prepared']);result=p.read(proof['result']['path']);receipt=p.read(side/'APPLIED.json')
    if (Path(proof['plan']['path']).resolve()!=side/'PLAN.json' or Path(proof['result']['path']).resolve()!=side/'RESULT.json'
            or result['plan_sha256']!=proof['plan']['sha256'] or receipt['capacity_proof_sha256']!=v.digest(proof)
            or receipt['target_sha256']!=review['target_sha256'] or receipt['total_composition_attempts']!=4
            or review.get('layout_review',review).get('subreviews')!=value['original'][1]['results'][:2]+[result['room']]
            or review.get('style_review')!=result['style']):raise ValueError('compact_successor_persistent_result_changed')
    room_contract.verify_result(result['room'])


def apply_successor(run):
    run=Path(run).resolve();side=_sidecar(run)
    with p.images.run_lock(run):
        if (side/'APPLIED.json').exists():
            verify_applied(p.read(run/'STATE.json')['first_frames'][old.SHOT]['review'])
            return p.read(side/'APPLIED.json')
        value=_current(run);result=p.read(side/'RESULT.json');room=result['room'];style=result['style']
        if (result.get('plan_sha256')!=p.file_sha(side/'PLAN.json') or room.get('decision')!='accepted'
                or room.get('completion_known') is not True or room.get('outcome_unknown') is not False
                or any(x is not True for x in room['checks'].values()) or not style
                or style['result'].get('decision')!='accepted' or style['result'].get('completion_known') is not True
                or style['result'].get('outcome_unknown') is not False):raise ValueError('compact_successor_not_fully_accepted')
        prepared={k:value[k] for k in ('room_prepared','blind_prepared','files')};prepared.update(schema=VERSION,original_folder=value['original'][1]['folder'])
        saved=p.read(side/'room_review/RESULTS.json');native=p.read(side/'room_review/item_0000/MODEL_NATIVE.json')
        if (saved.get('results')!=[room] or saved.get('results_sha256')!=v.digest([room]) or room['binding_sha256']!=v.digest(prepared)
                or native.get('completion_marker_present') is not True or native.get('finish_reason')!='stop'):
            raise ValueError('compact_successor_actual_native_required')
        def forbidden(_):raise ValueError('compact apply cannot dispatch inference')
        if _review_one(prepared,forbidden,room['model_binding'],side/'room_review/item_0000')!=room:
            raise ValueError('compact_successor_result_differs_from_raw')
        styles=p.read(side/'target_style_review/RESULTS.json');stem='APPEARANCE' if style['request'].get('binding',{}).get('reference_contract')=='appearance/v1' else 'STYLE'
        sn=p.read(side/'target_style_review/item_0000'/(stem+'_NATIVE.json'))
        if styles.get('results')!=[style['result']] or styles.get('results_sha256')!=v.digest([style['result']]) or sn.get('completion_marker_present') is not True or sn.get('finish_reason')!='stop':
            raise ValueError('compact_successor_style_native_required')
        plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json');frame=state['first_frames'][old.SHOT];prior=deepcopy(frame['review'])
        parts=deepcopy(value['original'][1]['results'][:2])+[room];combined=deepcopy(prior)
        combined.update(subreviews=parts,decision='accepted',completion_known=True,outcome_unknown=False,retryable=False,
            checks={k:all(x.get('checks',{}).get(k,True) is True for x in parts) for k in combined['checks']},
            issues=[i for x in parts for i in x.get('issues',[])],evidence=[e for x in parts for e in x.get('evidence',[])],visual_evidence=[e for x in parts for e in x.get('visual_evidence',[])])
        for k in ('object_observations','split_observation','observations','layout_object_inventory','furniture_observation_scope'):
            if k in room:combined[k]=deepcopy(room[k])
        combined=p._consume_layout_inventory(combined,p._review_layout_inventory(plan,value['place_entity']));combined=p._combine_residence_style(combined,style)
        p._verify_residence_style_receipt(run,plan,value['place_entity'],frame['path'],combined)
        p._verify_first_frame_inventory_contents(plan,value['place_entity'],combined);p._verify_first_frame_generation(plan,value['shot'],frame)
        if combined['decision']!='accepted':raise ValueError('compact_successor_combined_not_accepted')
        proof=dict(scope=VERSION,plan=old.artifact(side/'PLAN.json'),result=old.artifact(side/'RESULT.json'),
            native_artifacts=[old.artifact(f) for folder in (side/'room_review',side/'target_style_review') for f in folder.rglob('*')
                if f.is_file() and 'cache' not in f.relative_to(folder).parts and 'temp' not in f.relative_to(folder).parts])
        combined['capacity_extension_proof']=deepcopy(proof);failed_v17=deepcopy(prior);failed_v17['subreviews']=deepcopy(value['original'][1]['results'][:2])+[value['v17_failure']['room']]
        frame.setdefault('review_history',[]).extend([prior,failed_v17]);frame.update(review=combined,review_attempts=4,
            original_review_attempts=2,capacity_extension_attempts=2,v17_attempts=1,v18_attempts=1,capacity_extension=proof)
        state['status']='first_frame_compact_review_completed';p.write(run/'STATE.json',state)
        receipt=dict(schema=VERSION,shot_id=old.SHOT,target_sha256=old.TARGET,original_attempts=3,original_legacy_attempts=2,
            additional_room_reviews=1,additional_target_style_reviews=1,total_composition_attempts=4,
            result=old.artifact(side/'RESULT.json'),capacity_proof_sha256=v.digest(proof),at=time.time(),production_approved=False)
        p.freeze(side/'APPLIED.json',receipt);return receipt
