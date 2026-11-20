"""Explicit, once-only known taxonomy refresh. Never generates or resumes media.

prepare_refresh reserves the last existing review attempt. review_refresh makes
one new scoped visual review (and the exact target style pass when needed).
apply_refresh is a separate, read-only-evidence-validated registry append.
Original native files/results remain unchanged; no frozen PLAN field is edited.
"""
from copy import deepcopy
from pathlib import Path
import json
import time

from . import visual_asset_pipeline_v3 as p
from . import visual_asset_review_v3 as v
from . import visual_furniture_taxonomy_v12 as taxonomy

VERSION='known_furniture_taxonomy_refresh/v1'


def _artifact(path):return dict(path=str(Path(path).resolve()),sha256=p.file_sha(path))


def _req(row):return {k:row[k] for k in ('entity_id','kind','view','design_version')}


def _old_native(run,old):
    matches=[]
    for path in (run/'reviews').glob('*/RESULTS.json'):
        results=p.read(path);request=p.read(path.parent/'REQUEST.json')
        if results.get('results_sha256')!=p.fingerprint(results['results']):raise ValueError('original_review_results_changed')
        for i,result in enumerate(results['results']):
            if p.fingerprint(result)==p.fingerprint(old):matches.append((path,request['prepared'][i],i))
    if len(matches)!=1:raise ValueError('known_original_taxonomy_review_required')
    path,prepared,i=matches[0];folder=path.parent/f'item_{i:04}'
    if old.get('binding_sha256')!=p.fingerprint(prepared):raise ValueError('original_review_binding_changed')
    primary=v.validate_observation(v._parse_content(p.read(folder/'MODEL_NATIVE.json')['text']),prepared['expectation'])
    if (not all(value is True for value in primary['checks'].values()) or
        any(issue['severity']!='note' for issue in primary['issues'])):raise ValueError('original_primary_not_all_true')
    blind=v._parse_content(p.read(folder/'BLIND_NATIVE.json')['text'])
    if blind.get('object_observations')!=old.get('object_observations'):raise ValueError('original_blind_counts_changed')
    return prepared,{key:_artifact(file) for key,file in dict(results=path,request=path.parent/'REQUEST.json',
        primary=folder/'MODEL_NATIVE.json',blind=folder/'BLIND_NATIVE.json').items()}


def _qualify_old(run,plan,state,row):
    key=f"{row['asset_id']}:v{row['version']}:{row['sha256']}";old=state['reviews'].get(key)
    if (not old or old.get('decision')!='repair_required' or old.get('completion_known') is not True or
        old.get('outcome_unknown') is not False or old.get('target_sha256')!=row['sha256'] or
        old.get('object_taxonomy_recheck') is not None):raise ValueError('only_known_unrechecked_taxonomy_failure_allowed')
    entity=p._entity(plan,row);inventory=p._review_layout_inventory(plan,entity)
    if inventory is None or old.get('layout_object_inventory')!=inventory:raise ValueError('taxonomy_refresh_inventory_changed')
    v.validate_object_observations(old['object_observations'],inventory)
    selected=taxonomy.candidate(old['object_observations'])
    if (not selected or inventory['table']!=1 or inventory['counter']!=0 or
        old['object_observations']['table']['count']!=1 or old['object_observations']['counter']['count']!=1 or
        old.get('object_inventory_check',{}).get('exceeds')!=['counter'] or
        old.get('object_inventory_check',{}).get('unknown')!=[] or
        len(old.get('issues',[]))!=1 or old['issues'][0].get('inventory_upper_bound') is not True or
        old.get('checks')!={k:(False if k=='layout' else True) for k in v.PLACE_CHECKS}):
        raise ValueError('only_same_instance_table_counter_excess_allowed')
    count=state.get('review_attempts',{}).get(key,0)
    if count!=1 or count>=plan['config'].get('max_review_attempts',2):raise ValueError('taxonomy_refresh_last_attempt_unavailable')
    if key in state.get('taxonomy_refreshes',{}):raise ValueError('taxonomy_refresh_already_reserved')
    prepared,artifacts=_old_native(run,old);v._unchanged(prepared)
    if not p._dependencies(plan,row)[1]:raise ValueError('taxonomy_refresh_generation_inputs_not_bound')
    if (p._latest_review({},row)!=old or prepared['target']['sha256']!=row['sha256'] or
        prepared['layout_guide']['sha256']!=p._environment_guide(run,entity,row['view'])['sha256']):
        raise ValueError('original_taxonomy_asset_or_geometry_changed')
    front=p._lookup(plan,dict(entity_id=row['entity_id'],kind='place',view='front',design_version=row['design_version']))
    if not front or front['status']!='reviewed' or prepared['reference']['sha256']!=front['sha256']:
        raise ValueError('original_taxonomy_front_source_changed')
    return key,old,entity,prepared,artifacts


def prepare_refresh(run,folder,*,asset_id,version,file_sha256):
    """Explicit root action; reserves 1 -> 2, but does not call a model."""
    run=Path(run).resolve();folder=Path(folder).resolve()
    if folder==run or not folder.is_relative_to(run/'taxonomy_refreshes'):raise ValueError('taxonomy_refresh_evidence_must_be_new_run_subdirectory')
    with p.images.run_lock(run):
        plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json')
        if state.get('status')!='blocked_review_or_design':raise ValueError('taxonomy_refresh_requires_terminal_blocked_run')
        rows=p.library.get(plan['config']['library'],book_id=plan['packet']['book_id'],asset_id=asset_id)
        rows=[r for r in rows if r['version']==version and r['sha256']==file_sha256 and r['kind']=='place' and r['view']!='front']
        if len(rows)!=1:raise ValueError('exact_current_taxonomy_asset_required')
        row=rows[0]
        current=p._raw_lookup(plan,_req(row))
        if not current or p._asset_identity(current)!=p._asset_identity(row):raise ValueError('taxonomy_refresh_cannot_review_old_asset_version')
        key,old,entity,prepared,artifacts=_qualify_old(run,plan,state,row)
        q=dict(target=prepared['target']['path'],reference=prepared['reference']['path'],layout_guide=prepared['layout_guide']['path'],expectation=deepcopy(prepared['expectation']))
        frozen=v._prepared(q)
        value=dict(schema=VERSION,run=str(run),case_id=folder.name,key=key,row=p._asset_identity(row),
            original_review_sha256=p.fingerprint(old),original_registry_review_sha256=p.fingerprint(row['review']),
            source_plan=_artifact(run/'PLAN.json'),artifacts=artifacts,request=q,new_prepared=frozen,
            code_sha256={str(Path(path).resolve()):p.file_sha(path) for path in
                (v.__file__,taxonomy.__file__,p.__file__,p.library.__file__,p.generation_refs.__file__,p.residence_style.__file__,__file__)},
            budget=dict(before=1,reserved=2,limit=plan['config'].get('max_review_attempts',2)),image_generation_allowed=False)
        folder.mkdir(parents=True,exist_ok=False);p.write(folder/'ORIGINAL_REVIEW.json',old);p.write(folder/'ORIGINAL_STATE.json',state)
        p.freeze(folder/'PLAN.json',value)
        state.setdefault('review_attempts',{})[key]=2
        state.setdefault('taxonomy_refreshes',{})[key]=dict(case_id=folder.name,path=str(folder),status='reserved',at=time.time())
        p.write(run/'STATE.json',state)
        return value


def _current(folder):
    record=p.read(folder/'PLAN.json');run=Path(record['run']);plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json')
    if record.get('schema')!=VERSION or p.file_sha(run/'PLAN.json')!=record['source_plan']['sha256']:raise ValueError('taxonomy_refresh_plan_changed')
    for item in record['artifacts'].values():
        if p.file_sha(item['path'])!=item['sha256']:raise ValueError('original_taxonomy_native_changed')
    for path,sha in record['code_sha256'].items():
        if p.file_sha(path)!=sha:raise ValueError('taxonomy_refresh_code_changed_after_reservation')
    if v._prepared(record['request'])!=record['new_prepared']:raise ValueError('taxonomy_refresh_images_or_request_changed')
    pending=state.get('taxonomy_refreshes',{}).get(record['key'],{})
    if pending.get('path')!=str(folder) or state['review_attempts'].get(record['key'])!=2:raise ValueError('taxonomy_refresh_budget_or_case_changed')
    row=p._raw_lookup(plan,_req(record['row']))
    if not row or p._asset_identity(row)!=record['row']:raise ValueError('taxonomy_refresh_target_no_longer_current')
    if pending.get('status')!='applied':
        if (p.fingerprint(state['reviews'].get(record['key']))!=record['original_review_sha256'] or
            p.fingerprint(row['review'])!=record['original_registry_review_sha256']):raise ValueError('taxonomy_refresh_original_review_changed')
    return record,run,plan,state,row


def review_refresh(folder,reviewer):
    """One new scope. Does not grant registry eligibility or resume a worker."""
    folder=Path(folder).resolve();record=p.read(folder/'PLAN.json');run=Path(record['run'])
    with p.images.run_lock(run):
        record,run,plan,state,row=_current(folder)
        claim=folder/'EXECUTION_CLAIM.json'
        if claim.exists():raise ValueError('taxonomy_refresh_already_dispatched_no_blind_replay')
        with claim.open('x',encoding='utf-8') as stream:json.dump(dict(at=time.time(),plan_sha256=p.file_sha(folder/'PLAN.json')),stream)
        with p.gpu_access(plan):
            result=reviewer.review_many([record['request']],evidence_dir=folder/'visual')[0]
            if (result.get('target_sha256')!=row['sha256'] or result.get('reference_sha256')!=record['new_prepared']['reference']['sha256'] or
                result.get('layout_guide_sha256')!=record['new_prepared']['layout_guide']['sha256']):raise ValueError('new_taxonomy_review_source_binding_changed')
            result=p._consume_layout_inventory(result,record['request']['expectation']['layout_object_inventory'])
            style=None
            if result.get('decision')=='accepted':
                # Only an exact same-target style receipt can be reused.
                old=p.read(folder/'ORIGINAL_REVIEW.json');style=old.get('style_review')
                if style is not None:p._verify_residence_style_receipt(run,plan,p._entity(plan,row),record['request']['target'],old)
                else:style=p._residence_style_review(run,plan,p._entity(plan,row),record['request']['target'],reviewer,folder/'style')
                if style is not None and style.get('result',{}).get('target_sha256')!=row['sha256']:
                    raise ValueError('taxonomy_refresh_style_must_match_exact_target')
            combined=p._combine_residence_style(result,style)
        value=dict(schema=VERSION,visual=result,style=style,combined=combined,combined_sha256=p.fingerprint(combined),
            image_generation_called=False,source_reference_review_called=False)
        p.write(folder/'REVIEW.json',value)
        state['taxonomy_refreshes'][record['key']].update(status='review_completed',review_sha256=p.fingerprint(value))
        p.write(run/'STATE.json',state)
        return value


def apply_refresh(folder):
    """Explicit controlled append of a known accepted new review and bound style."""
    folder=Path(folder).resolve();record=p.read(folder/'PLAN.json');run=Path(record['run'])
    with p.images.run_lock(run):
        record,run,plan,state,row=_current(folder)
        if state['taxonomy_refreshes'][record['key']]['status']=='applied':return p.read(folder/'APPLIED.json')
        value=p.read(folder/'REVIEW.json');result=value['combined'];visual=value['visual']
        if state['taxonomy_refreshes'][record['key']].get('review_sha256')!=p.fingerprint(value):raise ValueError('taxonomy_refresh_completed_receipt_changed')
        if p.read(folder/'EXECUTION_CLAIM.json').get('plan_sha256')!=p.file_sha(folder/'PLAN.json'):raise ValueError('taxonomy_refresh_execution_claim_required')
        if value['combined_sha256']!=p.fingerprint(result):raise ValueError('taxonomy_refresh_new_result_changed')
        saved=p.read(folder/'visual/RESULTS.json')
        if saved.get('results_sha256')!=p.fingerprint(saved['results']) or saved['results']!=[visual]:raise ValueError('taxonomy_refresh_new_native_result_required')
        actual_request=p.read(folder/'visual/REQUEST.json')
        binding=v.digest(dict(config=v.VisualReviewClient(plan['config']['visual_review']).config,requests=[record['new_prepared']]))
        if (actual_request.get('prepared')!=[record['new_prepared']] or actual_request.get('request_binding_sha256')!=binding or
            saved.get('request_binding_sha256')!=binding or visual.get('binding_sha256')!=p.fingerprint(record['new_prepared'])):
            raise ValueError('taxonomy_refresh_new_request_changed')
        expected=p._combine_residence_style(visual,value['style'])
        if result!=expected or result.get('decision')!='accepted' or result.get('completion_known') is not True or result.get('outcome_unknown') is not False:
            raise ValueError('taxonomy_refresh_requires_known_accepted_result')
        result=p._consume_layout_inventory(result,record['request']['expectation']['layout_object_inventory'])
        if not all(result['checks'].get(k) is True for k in v.PLACE_CHECKS):raise ValueError('taxonomy_refresh_checks_not_all_true')
        p._verify_residence_style_receipt(run,plan,p._entity(plan,row),record['request']['target'],result)
        evidence=dict(image_sha256=row['sha256'],observations=result.get('visual_evidence') or result['evidence'],
            review=p.fingerprint(result),model=result.get('model_binding'),source_review=deepcopy(result),taxonomy_refresh_case=str(folder))
        p.library.review(plan['config']['library'],book_id=row['book_id'],asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
            decision='accepted',reviewer='local_visual_model_taxonomy_refresh',checks={k:v for k,v in result['checks'].items() if type(v) is bool},evidence=evidence,
            expected_review_sha256=record['original_registry_review_sha256'])
        state.setdefault('review_history',{}).setdefault(record['key'],[]).append(deepcopy(state['reviews'][record['key']]))
        state['reviews'][record['key']]=result;state['taxonomy_refreshes'][record['key']]['status']='applied'
        p.write(run/'STATE.json',state)
        receipt=dict(schema=VERSION,status='applied',key=record['key'],new_review_sha256=p.fingerprint(result),
            old_review_preserved=True,budget=record['budget'],image_generation_called=False,worker_resumed=False)
        p.write(folder/'APPLIED.json',receipt);return receipt
