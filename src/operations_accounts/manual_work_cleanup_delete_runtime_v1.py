"""Named original-owner UI steps with a late, once-only final deletion claim.

Inventory, selection, and exact confirmation are separate immutable actions.
The final action preserves protected works and proves fresh native absence.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import types
import uuid

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1'
ARM=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1/manual_runtime_v10/ARM.json'
ACTION='open_batch_controls'
SELECT_ACTION='select_targets_open_confirmation'
INSPECT_SELECTION_ACTION='inspect_current_selection'
VISIBLE_SELECT_ACTION='select_visible_targets_open_confirmation'
CONFIRM_ACTION='confirm_exact_selection'
FINAL_DELETE_CLAIM=RUN/'DOUYIN_FINAL_DELETE_CLAIM.json'
BATCH_PRODUCER_SHA={'cleanup_runtime':'77fbbaf4764299d47e7125d793dc516dc6f3c7721853a031adadb6b430047cdb',
    'adapter':'a4508b5129371b0300c923c623dd8a0d7f520051303998acbd800df0c00aae1d'}
SELECT_PRODUCER_SHA={'cleanup_runtime':'b80d5c45c2c4213b0cf2b4cc582bdb9c83a2d9bae607494b1efd45455fcd1fa3',
    'adapter':'d1ecfacbe5241a4a524620ee82e159cfcfa4d1dd190e769b23427c5b3ccfc881'}
PROBE_PRODUCER_SHA={'cleanup_runtime':'91ab59ce0b24dd5fa8b0afbd3c512f016ddc8960f7950f782b6cc2bf6f63ff42',
    'adapter':'527bbd16fe7b453e861ef7455617d0d7cc46d85c68ab8a9b4ca50a3a759b781b'}
VISIBLE_PRODUCER_SHA={'cleanup_runtime':'0f57ea0a84c2d11014797b0080363a43c8e4829b77e8a89a8f1ed32f0467afd5',
    'adapter':'08e73ad2a9c15eaa9478b923f050b851a04369f98caf8e195933b530bc87b430'}
SOURCE_PATHS={
    'runtime_v10':ROOT/'src/operations_accounts/manual_republication_runtime_v10.py','cleanup_runtime':Path(__file__).resolve(),
    'adapter':ROOT/'src/platform_adapter/douyin_work_cleanup_delete_v1.py',
    'inspector_runtime':ROOT/'src/operations_accounts/manual_work_cleanup_runtime_v1.py',
    'inspector_adapter':ROOT/'src/platform_adapter/douyin_work_cleanup_v1.py',
    'guard_v1':ROOT/'src/operations_accounts/manual_republication_runtime_v1.py','flow_v1':ROOT/'src/operations_accounts/manual_republication_flow_v1.py',
    'app':ROOT/'src/web/app.py','host':ROOT/'src/operations_accounts/browser_control_runtime.py','browser_session':ROOT/'src/platform_adapter/browser_session.py',
}


def reference(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('cleanup_project_reference_required')
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def read(ref):
    if not isinstance(ref,dict) or set(ref)!={'path','sha256'} or reference(ref['path'])!=ref:raise ValueError('cleanup_reference_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def once(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    return reference(path)


def _load(key,config):
    path=SOURCE_PATHS[key];raw=path.read_bytes();ref=config['sources'][key]
    if reference(path)!=ref or hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('cleanup_source_changed:'+key)
    package='src.platform_adapter' if key in {'adapter','inspector_adapter'} else 'src.operations_accounts'
    module=types.ModuleType(package+'._batch_'+key+'_'+ref['sha256'][:16]);module.__file__,module.__package__=str(path),package
    exec(compile(raw,str(path),'exec'),module.__dict__);return module


def _project(config):
    sources={k:v for k,v in config['sources'].items() if k not in {'inspector_runtime','inspector_adapter'}}
    sources['cleanup_runtime']=config['sources']['inspector_runtime'];sources['adapter']=config['sources']['inspector_adapter']
    return dict(config,sources=sources)


def _config(ref):
    config=read(ref)
    if set(config.get('sources',{}))!=set(SOURCE_PATHS):raise ValueError('cleanup_exact_batch_sources_required')
    for k,p in SOURCE_PATHS.items():
        if reference(p)!=config['sources'][k]:raise ValueError('cleanup_batch_source_changed:'+k)
    _load('inspector_runtime',config)._scope(_project(config));return config


def _request(ref,config_ref):
    value=read(ref)
    fields={'schema','config','action','selection_result','deletion_contract'} if value.get('action')==CONFIRM_ACTION else {'schema','config','action','current_selection_result','prior_unknown'} if value.get('action')==VISIBLE_SELECT_ACTION else {'schema','config','action','prior_unknown'} if value.get('action')==INSPECT_SELECTION_ACTION else {'schema','config','action','batch_result'} if value.get('action')==SELECT_ACTION else {'schema','config','action','inventory_result'}
    if set(value)!=fields or value['schema']!='manual_work_cleanup_request/v1' or value['config']!=config_ref or value['action'] not in {ACTION,SELECT_ACTION,INSPECT_SELECTION_ACTION,VISIBLE_SELECT_ACTION,CONFIRM_ACTION}:
        raise ValueError('cleanup_named_inspection_or_selection_request_required')
    return value


def _inventory_prior(request,config):
    value=read(request['inventory_result']);library=_load('inspector_runtime',config)
    if (Path(request['inventory_result']['path']).resolve()!=RUN/'inspect_001/RESULT.json' or value.get('schema')!='manual_work_cleanup_result/v1'
            or value.get('actual_public_uid_matches') is not True or value.get('deleted') is not False or value.get('delete_allowed') is not False):
        raise ValueError('cleanup_original_readonly_inventory_required')
    plan,old_config,_=library._plan(value['plan']);read(value['claim'])
    if {k:v for k,v in old_config.items() if k!='sources'}!={k:v for k,v in config.items() if k!='sources'}:raise ValueError('cleanup_inventory_subject_changed')
    for ref in value['evidence']:read(ref)
    expected=read(config['authority']);cards=value.get('inspection',{}).get('inventory',{})
    if (cards.get('public_uids')!=[expected['expected_public_uid']] or set(value.get('native_reduced_traffic_candidates',[]))!=set(expected['delete_douyin_only_ids'])
            or set(value.get('protected_post_ids',[]))!=set(expected['protected_post_ids'])):raise ValueError('cleanup_original_targets_changed')
    return dict(inventory_result=request['inventory_result'],inventory_plan=value['plan'],inventory_claim=value['claim'])


def _producer_history(plan,config,folder):
    snapshots=plan.get('producer_source_snapshot',{})
    if set(snapshots)!={'cleanup_runtime','adapter'}:raise ValueError('cleanup_historical_producer_snapshots_required')
    for key,ref in snapshots.items():
        if Path(ref['path']).resolve()!=folder/'producer_sources'/(key+'.py') or reference(ref['path'])!=ref or ref['sha256']!=config['sources'][key]['sha256']:
            raise ValueError('cleanup_historical_producer_changed')


def _batch_prior(request,config):
    value=read(request['batch_result']);folder=RUN/'batch_controls_001'
    if Path(request['batch_result']['path']).resolve()!=folder/'RESULT.json' or value.get('schema')!='manual_work_batch_result/v1':raise ValueError('cleanup_actual_batch_receipt_required')
    old_plan=read(value['plan']);old_config=read(old_plan['config']);old_request=read(old_plan['request']);claim=read(value['claim'])
    if (Path(value['plan']['path']).resolve()!=folder/'PLAN.json' or old_plan.get('schema')!='manual_work_cleanup_plan/v1' or old_plan.get('action')!=ACTION
            or set(old_request)!={'schema','config','action','inventory_result'} or old_request.get('schema')!='manual_work_cleanup_request/v1' or old_request.get('config')!=old_plan['config'] or old_request.get('action')!=ACTION
            or claim.get('schema')!='manual_work_batch_action_claim/v1'
            or claim.get('plan')!=value['plan'] or claim.get('request')!=old_plan['request']
            or claim.get('action')!=ACTION or claim.get('batch_entry_limit')!=1
            or any(claim.get(k)!=0 for k in ('selections_allowed','deletions_allowed','confirmations_allowed'))
            or any(value.get(k) is not False for k in ('selected','deleted','delete_allowed','account_pause_changed'))
            or value.get('batch_entry_native_dispatches')!=1):raise ValueError('cleanup_batch_once_history_changed')
    if {k:v for k,v in old_config.items() if k!='sources'}!={k:v for k,v in config.items() if k!='sources'}:raise ValueError('cleanup_batch_subject_changed')
    for key in set(SOURCE_PATHS)-{'cleanup_runtime','adapter'}:
        if old_config['sources'][key]!=config['sources'][key]:raise ValueError('cleanup_batch_stable_dependency_changed')
    _producer_history(old_plan,old_config,folder)
    if any(old_config['sources'][k]['sha256']!=sha for k,sha in BATCH_PRODUCER_SHA.items()) or any(claim.get(k)!=old_config[k] for k in ('owner_id','generation','tab_id')):
        raise ValueError('cleanup_known_batch_producer_or_owner_changed')
    if old_plan.get('batch_entry_clicks_allowed')!=1 or any(type(old_plan.get(k)) is not int or old_plan[k]!=0 for k in ('selections_allowed','deletions_allowed','confirmations_allowed','navigations_allowed')):
        raise ValueError('cleanup_historical_batch_limits_changed')
    if old_plan.get('prior')!=_inventory_prior(old_request,old_config):raise ValueError('cleanup_batch_inventory_chain_changed')
    for ref in value['evidence']:read(ref)
    observed=value.get('inspection',{}).get('inventory',{});controls=observed.get('native_controls',[])
    ids={x.get('unique_native_post_id') for x in controls if x.get('unique_native_post_id')}
    auth=read(config['authority'])
    if (len(controls)!=5 or ids!=set(auth['delete_douyin_only_ids'])|set(auth['protected_post_ids'])
            or any(x.get('checked') is not False or x.get('aria_checked')!='false' or x.get('disabled') is not False for x in controls)
            or observed.get('visible_modal_count')!=0 or observed.get('truncated') is not False):raise ValueError('cleanup_batch_initial_public_checkbox_state_required')
    return dict(batch_result=request['batch_result'],batch_plan=value['plan'],batch_claim=value['claim'],producer_source_snapshot=old_plan['producer_source_snapshot'])


def _unknown_selection_prior(request,config):
    value=read(request['prior_unknown']);folder=RUN/'select_001'
    if (Path(request['prior_unknown']['path']).resolve()!=folder/'UNKNOWN.json' or value.get('schema')!='manual_work_batch_unknown/v1'
            or value.get('deleted') is not False or value.get('automatic_replay_allowed') is not False or value.get('delete_entry_native_dispatches')!=0
            or value.get('batch_entry_native_dispatches')!=0 or not set(value.get('target_native_dispatches',[])).issubset(set(read(config['authority'])['delete_douyin_only_ids']))):
        raise ValueError('cleanup_original_selection_unknown_required')
    old_plan=read(value['plan']);old_config=read(old_plan['config']);old_request=read(old_plan['request']);claim=read(value['claim'])
    if (Path(value['plan']['path']).resolve()!=folder/'PLAN.json' or old_plan.get('action')!=SELECT_ACTION
            or set(old_request)!={'schema','config','action','batch_result'} or old_request.get('action')!=SELECT_ACTION
            or old_request.get('config')!=old_plan['config'] or claim.get('plan')!=value['plan'] or claim.get('request')!=old_plan['request']
            or claim.get('action')!=SELECT_ACTION or claim.get('selections_allowed')!=2 or claim.get('deletions_allowed')!=0 or claim.get('confirmations_allowed')!=0
            or {k:v for k,v in old_config.items() if k!='sources'}!={k:v for k,v in config.items() if k!='sources'}):raise ValueError('cleanup_selection_unknown_subject_changed')
    _producer_history(old_plan,old_config,folder)
    if any(old_config['sources'][k]['sha256']!=v for k,v in SELECT_PRODUCER_SHA.items()):raise ValueError('cleanup_selection_unknown_producer_changed')
    for key in set(SOURCE_PATHS)-{'cleanup_runtime','adapter'}:
        if old_config['sources'][key]!=config['sources'][key]:raise ValueError('cleanup_selection_stable_dependency_changed')
    if old_plan.get('prior')!=_batch_prior(old_request,old_config):raise ValueError('cleanup_selection_unknown_parent_changed')
    return dict(prior_unknown=request['prior_unknown'],selection_plan=value['plan'],selection_claim=value['claim'],producer_source_snapshot=old_plan['producer_source_snapshot'],
        dispatched_native_selectors=value['target_native_dispatches'],original_dom_events_known=False)


def _prior(request,config):
    return _final_contract_prior(request,config) if request['action']==CONFIRM_ACTION else _current_probe_prior(request,config) if request['action']==VISIBLE_SELECT_ACTION else _unknown_selection_prior(request,config) if request['action']==INSPECT_SELECTION_ACTION else _batch_prior(request,config) if request['action']==SELECT_ACTION else _inventory_prior(request,config)


def _slot(action):return 'confirm_001' if action==CONFIRM_ACTION else 'select_visible_001' if action==VISIBLE_SELECT_ACTION else 'current_selection_001' if action==INSPECT_SELECTION_ACTION else 'select_001' if action==SELECT_ACTION else 'batch_controls_001'


def _final_contract_prior(request,config):
    contract=read(request['deletion_contract']);auth=read(config['authority']);folder=RUN/'select_visible_001';value=read(request['selection_result'])
    if (Path(request['deletion_contract']['path']).resolve()!=RUN/'DOUYIN_FINAL_DELETE_CONTRACT.json' or contract.get('schema')!='douyin_exact_two_work_deletion_contract/v1'
            or contract.get('authority')!=config['authority'] or contract.get('selection_result')!=request['selection_result'] or contract.get('current_uid')!=auth['expected_public_uid']
            or contract.get('delete_post_ids')!=auth['delete_douyin_only_ids'] or contract.get('protected_post_ids')!=auth['protected_post_ids']
            or contract.get('expected_title')!='确认删除2个作品？' or contract.get('expected_warning')!='删除后作品将无法找回，建议设为私密作品'
            or contract.get('final_confirmation_limit')!=1 or contract.get('post_confirm_reload_limit')!=1 or contract.get('reselect_allowed') is not False
            or contract.get('new_publication_allowed') is not False or contract.get('native_modal_reader_count_retained')!=0
            or contract.get('semantic_modal_observed_without_role_or_semi_modal_wrapper') is not True
            or contract.get('post_confirm_readonly_reload_url')!='https://www.douyin.com/user/self?from_tab_name=main'):
        raise ValueError('cleanup_concrete_final_delete_contract_required')
    expected_button={'tag':'button','role':'','class_name':'semi-button semi-button-primary N1nTvZOT','text':'确认删除','type':'button','disabled':False}
    if contract.get('confirmation_button')!=expected_button or reference(contract['crosscheck_uia']['path'])!=contract['crosscheck_uia']:raise ValueError('cleanup_actual_native_confirmation_contract_changed')
    plan=read(value['plan']);old=read(plan['config']);old_request=read(plan['request']);claim=read(value['claim'])
    if (Path(request['selection_result']['path']).resolve()!=folder/'RESULT.json' or value.get('schema')!='manual_work_cleanup_selection_result/v1'
            or Path(value['plan']['path']).resolve()!=folder/'PLAN.json' or plan.get('action')!=VISIBLE_SELECT_ACTION or old_request.get('action')!=VISIBLE_SELECT_ACTION
            or claim.get('plan')!=value['plan'] or claim.get('request')!=plan['request'] or claim.get('action')!=VISIBLE_SELECT_ACTION
            or {k:v for k,v in old.items() if k!='sources'}!={k:v for k,v in config.items() if k!='sources'}
            or value.get('deleted') is not False or value.get('selected') is not True or value.get('delete_allowed') is not False
            or set(value.get('target_native_dispatches',[]))!=set(auth['delete_douyin_only_ids']) or value.get('delete_entry_native_dispatches')!=1):raise ValueError('cleanup_actual_visible_selection_receipt_required')
    _producer_history(plan,old,folder)
    if any(old['sources'][k]['sha256']!=v for k,v in VISIBLE_PRODUCER_SHA.items()) or plan.get('prior')!=_current_probe_prior(old_request,old):raise ValueError('cleanup_visible_selection_producer_changed')
    for key in set(SOURCE_PATHS)-{'cleanup_runtime','adapter'}:
        if old['sources'][key]!=config['sources'][key]:raise ValueError('cleanup_final_stable_dependency_changed')
    for ref in value['evidence']:read(ref)
    inspection=value['inspection'];events=inspection.get('event_recorder_final',{});raw=inspection.get('confirmation',{})
    counts={p:0 for p in auth['delete_douyin_only_ids']}
    for event in events.get('events',[]):
        if event.get('type')=='click' and event.get('is_trusted') is True and event.get('blocked') is False:
            if event.get('post_id') not in counts:raise ValueError('cleanup_foreign_native_selection_event')
            counts[event['post_id']]+=1
    if (events.get('active') is not False or events.get('nonce')!=plan.get('interaction_nonce') or claim.get('event_nonce')!=events['nonce'] or inspection.get('event_nonce')!=events['nonce']
            or events.get('trusted_display_click_counts')!={p:1 for p in counts} or counts!={p:1 for p in counts} or events.get('blocked_event_count')!=0 or events.get('outside_target_trusted_clicks')!=0
            or raw.get('visible_modal_count')!=0 or raw.get('visible_text_lines',[]).count(contract['expected_title'])!=1 or raw.get('visible_text_lines',[]).count(contract['expected_warning'])!=1
            or len([b for b in raw.get('buttons',[]) if b==expected_button])!=1):raise ValueError('cleanup_actual_roleless_confirmation_evidence_required')
    controls=raw.get('native_controls',[]);rows={x.get('unique_native_post_id'):x for x in controls if x.get('unique_native_post_id')}
    if len(controls)!=5 or set(rows)!=set(auth['delete_douyin_only_ids'])|set(auth['protected_post_ids']):raise ValueError('cleanup_historical_five_selected_controls_required')
    for control in controls:
        chosen=control.get('unique_native_post_id') in auth['delete_douyin_only_ids']
        if control.get('checked') is not chosen or control.get('aria_checked')!=('true' if chosen else 'false'):raise ValueError('cleanup_historical_exact_native_selection_required')
    return dict(selection_result=request['selection_result'],selection_plan=value['plan'],selection_claim=value['claim'],deletion_contract=request['deletion_contract'],event_nonce=events['nonce'],producer_source_snapshot=plan['producer_source_snapshot'])


def _current_probe_prior(request,config):
    value=read(request['current_selection_result']);folder=RUN/'current_selection_001'
    if Path(request['current_selection_result']['path']).resolve()!=folder/'RESULT.json' or value.get('schema')!='manual_work_current_selection_result/v1':raise ValueError('cleanup_actual_zero_selection_probe_required')
    plan=read(value['plan']);old_config=read(plan['config']);old_request=read(plan['request']);claim=read(value['claim'])
    if (Path(value['plan']['path']).resolve()!=folder/'PLAN.json' or plan.get('action')!=INSPECT_SELECTION_ACTION
            or old_request.get('prior_unknown')!=request['prior_unknown'] or old_request.get('action')!=INSPECT_SELECTION_ACTION
            or claim.get('plan')!=value['plan'] or claim.get('request')!=plan['request']
            or any(value.get(k) is not False for k in ('deleted','selected','delete_allowed','account_pause_changed'))
            or value.get('target_native_dispatches')!=[] or value.get('delete_entry_native_dispatches')!=0
            or {k:v for k,v in old_config.items() if k!='sources'}!={k:v for k,v in config.items() if k!='sources'}):raise ValueError('cleanup_zero_selection_probe_scope_changed')
    _producer_history(plan,old_config,folder)
    if any(old_config['sources'][k]['sha256']!=v for k,v in PROBE_PRODUCER_SHA.items()) or plan.get('prior')!=_unknown_selection_prior(old_request,old_config):raise ValueError('cleanup_zero_selection_probe_producer_changed')
    for key in set(SOURCE_PATHS)-{'cleanup_runtime','adapter'}:
        if old_config['sources'][key]!=config['sources'][key]:raise ValueError('cleanup_probe_stable_dependency_changed')
    for ref in value['evidence']:read(ref)
    inspection=value['inspection'];observation=inspection['observation'];dom=read(inspection['dom_readback'])
    if dom.get('observation')!=observation or inspection.get('worker_health_after_optional_screenshot',{}).get('healthy') is not True:raise ValueError('cleanup_completed_healthy_native_probe_required')
    auth=read(config['authority']);controls=observation.get('controls',[])
    mapped={c['post_ids'][0]:c for c in controls if len(c.get('post_ids',[]))==1}
    if (observation.get('checkbox_count')!=5 or len(controls)!=5 or set(mapped)!=set(auth['delete_douyin_only_ids'])|set(auth['protected_post_ids'])
            or observation.get('visible_modal_count')!=0 or observation.get('truncated') is not False
            or len(observation.get('selected_count_texts',[]))!=1 or not re.fullmatch(r'已选\s*0\s*个作品',observation['selected_count_texts'][0])
            or any(c.get('native_checked') is not False or c.get('aria_checked')!='false' or any(a.get('component_checked_class') for a in c.get('ancestors',[])) for c in controls)):
        raise ValueError('cleanup_current_zero_selected_public_evidence_required')
    for post_id in auth['delete_douyin_only_ids']:
        control=mapped[post_id];hit=control.get('center_hit') or {}
        if control.get('style',{}).get('opacity')!='0' or control.get('center_hit_inside_component') is not True or hit.get('tag')!='span' or 'semi-checkbox-inner-display' not in hit.get('class_name','').split():
            raise ValueError('cleanup_observed_visible_display_target_required')
    return dict(current_selection_result=request['current_selection_result'],current_selection_plan=value['plan'],current_selection_claim=value['claim'],
        dom_readback=inspection['dom_readback'],prior_unknown=request['prior_unknown'],producer_source_snapshot=plan['producer_source_snapshot'],past_dom_event_count=None)


def _safe_error(error):
    first=str(error).splitlines()[0] if str(error) else type(error).__name__
    return re.sub(r'https?://\S+','<url>',first)[:500]


def validate_live(actor,resource,config):return _load('inspector_runtime',config).validate_live(actor,resource,_project(config))


def prepare(config_ref,request_ref,output_directory):
    folder=Path(output_directory).resolve()
    config=_config(config_ref);request=_request(request_ref,config_ref)
    expected=RUN/_slot(request['action'])
    if folder!=expected or folder.exists():raise ValueError('cleanup_unique_named_directory_required')
    prior=_prior(request,config)
    state=_load('inspector_runtime',config)._state(_project(config));snapshots={}
    for key in ('cleanup_runtime','adapter'):
        p=folder/'producer_sources'/(key+'.py');p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(SOURCE_PATHS[key].read_bytes())
        snapshots[key]=reference(p)
    selecting=request['action'] in {SELECT_ACTION,VISIBLE_SELECT_ACTION};inspecting=request['action']==INSPECT_SELECTION_ACTION;confirming=request['action']==CONFIRM_ACTION
    if confirming and FINAL_DELETE_CLAIM.exists():raise ValueError('cleanup_final_delete_already_claimed')
    return once(folder/'PLAN.json',dict(schema='manual_work_cleanup_plan/v1',config=config_ref,request=request_ref,action=request['action'],prior=prior,state=state,
        producer_source_snapshot=snapshots,batch_entry_clicks_allowed=int(not selecting and not inspecting and not confirming),selections_allowed=2 if selecting else 0,delete_entries_allowed=int(selecting),
        deletions_allowed=2 if confirming else 0,confirmations_allowed=int(confirming),navigations_allowed=int(confirming),final_delete_claim_path=str(FINAL_DELETE_CLAIM) if confirming else None,
        interaction_nonce=uuid.uuid4().hex if request['action']==VISIBLE_SELECT_ACTION else None))


def _plan(ref):
    plan=read(ref)
    selecting=plan.get('action') in {SELECT_ACTION,VISIBLE_SELECT_ACTION};inspecting=plan.get('action')==INSPECT_SELECTION_ACTION;confirming=plan.get('action')==CONFIRM_ACTION
    if plan.get('schema')!='manual_work_cleanup_plan/v1' or plan.get('action') not in {ACTION,SELECT_ACTION,INSPECT_SELECTION_ACTION,VISIBLE_SELECT_ACTION,CONFIRM_ACTION} or Path(ref['path']).resolve()!=RUN/_slot(plan['action'])/'PLAN.json':raise ValueError('cleanup_named_batch_plan_required')
    config=_config(plan['config']);request=_request(plan['request'],plan['config'])
    limits=dict(batch_entry_clicks_allowed=int(not selecting and not inspecting and not confirming),selections_allowed=2 if selecting else 0,delete_entries_allowed=int(selecting),deletions_allowed=2 if confirming else 0,confirmations_allowed=int(confirming),navigations_allowed=int(confirming))
    if plan.get('prior')!=_prior(request,config) or any(type(plan.get(k)) is not int or plan[k]!=v for k,v in limits.items()):raise ValueError('cleanup_batch_scope_changed')
    if request['action']==VISIBLE_SELECT_ACTION and (not isinstance(plan.get('interaction_nonce'),str) or not re.fullmatch(r'[0-9a-f]{32}',plan['interaction_nonce'])):raise ValueError('cleanup_visible_interaction_nonce_required')
    if confirming and plan.get('final_delete_claim_path')!=str(FINAL_DELETE_CLAIM):raise ValueError('cleanup_final_claim_path_changed')
    for k,source in plan['producer_source_snapshot'].items():
        if reference(source['path'])!=source or source['sha256']!=config['sources'][k]['sha256']:raise ValueError('cleanup_batch_producer_changed')
    return plan,config,request


def status(ref):
    folder=Path(ref['path']).resolve().parent
    if (folder/'RESULT.json').exists():
        plan=read(ref);config=read(plan['config']);result=read(reference(folder/'RESULT.json'));claim=read(result['claim'])
        if folder not in {RUN/'batch_controls_001',RUN/'select_001',RUN/'current_selection_001',RUN/'select_visible_001',RUN/'confirm_001'} or result.get('plan')!=ref or claim.get('plan')!=ref:raise ValueError('cleanup_cached_original_result_required')
        _producer_history(plan,config,folder)
        for evidence in result['evidence']:read(evidence)
        return dict(status=result.get('inspection',{}).get('status','deletion_unknown') if plan['action']==CONFIRM_ACTION else 'current_selection_observed' if plan['action']==INSPECT_SELECTION_ACTION else 'selection_observed' if plan['action'] in {SELECT_ACTION,VISIBLE_SELECT_ACTION} else 'batch_controls_observed',result=reference(folder/'RESULT.json'))
    _plan(ref)
    return dict(status='batch_observation_unknown',automatic_replay_allowed=False) if (folder/'ACTION_CLAIM.json').exists() else dict(status='prepared',plan=ref)


def claim_final_deletion(actor,resource,config,request,plan_ref,action_claim,preflight_ref):
    plan,actual_config,actual_request=_plan(plan_ref)
    if actual_config!=config or actual_request!=request or request['action']!=CONFIRM_ACTION or validate_live(actor,resource,config)!=plan['state']:
        raise ValueError('cleanup_original_final_action_required')
    folder=Path(plan_ref['path']).parent
    if Path(preflight_ref['path']).resolve()!=folder/'inspection/FINAL_DELETE_PREFLIGHT.json':raise ValueError('cleanup_original_final_preflight_path_required')
    action=read(action_claim);preflight=read(preflight_ref);auth=read(config['authority']);contract=read(request['deletion_contract']);adapter=_load('adapter',config)
    if action.get('plan')!=plan_ref or action.get('request')!=plan['request'] or action.get('actor_thread_id')!=threading.get_ident():raise ValueError('cleanup_original_final_action_claim_changed')
    stamp=preflight.get('observed_at')
    if (preflight.get('schema')!='manual_work_final_delete_preflight/v1' or preflight.get('deletion_contract')!=request['deletion_contract']
            or preflight.get('selection_result')!=request['selection_result'] or preflight.get('delete_post_ids')!=auth['delete_douyin_only_ids']
            or preflight.get('protected_post_ids')!=auth['protected_post_ids'] or preflight.get('final_confirmation_limit')!=1
            or type(stamp) not in {int,float} or not math.isfinite(stamp) or not 0<=time.time()-stamp<=30):raise ValueError('cleanup_fresh_exact_final_preflight_required')
    adapter._ready(preflight['profile'],auth['expected_public_uid'],auth['delete_douyin_only_ids'],auth['protected_post_ids'])
    adapter._final_selected(preflight['selection'],auth['delete_douyin_only_ids'],auth['protected_post_ids'])
    scope=preflight.get('confirmation',{})
    if (scope.get('eligible') is not True or scope.get('same_element') is not True or scope.get('title_count')!=1 or scope.get('warning_count')!=1
            or scope.get('button_count')!=1 or scope.get('button')!=contract['confirmation_button'] or scope.get('center_hit_within_button') is not True
            or contract['expected_title'] not in scope.get('semantic_scope',{}).get('text','') or contract['expected_warning'] not in scope.get('semantic_scope',{}).get('text','')):
        raise ValueError('cleanup_actual_roleless_final_scope_required')
    validate_live(actor,resource,config)
    return once(FINAL_DELETE_CLAIM,dict(schema='manual_work_final_delete_claim/v1',authority=config['authority'],plan=plan_ref,action_claim=action_claim,request=plan['request'],
        deletion_contract=request['deletion_contract'],selection_result=request['selection_result'],preflight=preflight_ref,
        delete_post_ids=auth['delete_douyin_only_ids'],protected_post_ids=auth['protected_post_ids'],owner_id=actor.owner_id,generation=actor.generation,
        tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),final_confirmation_limit=1,automatic_replay_allowed=False))


def _perform(actor,resource,plan_ref,arm_ref):
    from src.platform_adapter.browser_session import Page
    plan,config,request=_plan(plan_ref);folder=Path(plan_ref['path']).parent
    if validate_live(actor,resource,config)!=plan['state'] or reference(ARM)!=arm_ref:raise ValueError('cleanup_original_batch_context_changed')
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    claim=once(folder/'ACTION_CLAIM.json',dict(schema='manual_work_batch_action_claim/v1',plan=plan_ref,request=plan['request'],actor_thread_id=threading.get_ident(),
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],action=request['action'],at_epoch=time.time(),
        batch_entry_limit=plan['batch_entry_clicks_allowed'],selections_allowed=plan['selections_allowed'],deletions_allowed=plan.get('deletions_allowed',0),confirmations_allowed=plan.get('confirmations_allowed',0),event_nonce=plan.get('interaction_nonce')))
    original=resource.session;deadline=time.monotonic()+420;native_clicks=0;selected_clicks=set();delete_entry_clicks=0;final_clicks=0;reloads=0
    def guard():
        _config(plan['config'])
        if resource.session is not original or time.monotonic()>deadline or reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('cleanup_batch_owner_or_source_changed')
    try:
        guard();raw=original.get_page(config['tab_id']);guard()
        if raw._session is not original or raw.tab_id!=config['tab_id']:raise ValueError('cleanup_batch_original_page_required')
        adapter=_load('adapter',config);inspector=_load('inspector_adapter',config);auth=read(config['authority']);selecting=request['action'] in {SELECT_ACTION,VISIBLE_SELECT_ACTION};inspecting=request['action']==INSPECT_SELECTION_ACTION;visible_select=request['action']==VISIBLE_SELECT_ACTION;confirming=request['action']==CONFIRM_ACTION
        contract=read(request['deletion_contract']) if confirming else None
        target_selector=adapter.display_selector if visible_select else adapter.checkbox_selector if selecting else None
        class Gate:
            def cmd(self,kind,**kw):
                nonlocal native_clicks,delete_entry_clicks,final_clicks,reloads
                if kw.pop('tab_id',raw.tab_id)!=raw.tab_id:raise ValueError('cleanup_batch_tab_changed')
                guard()
                if kind=='click':
                    if inspecting:raise ValueError('cleanup_inspection_has_no_click_permission')
                    if kw.get('index')!=0 or kw.get('force') is not False or kw.get('timeout')!=8000:raise ValueError('cleanup_native_click_parameters_required')
                    if confirming:
                        if final_clicks or kw.get('selector')!=adapter.FINAL_CONFIRM:raise ValueError('cleanup_only_once_exact_native_final_confirmation_allowed')
                        claimed=read(reference(FINAL_DELETE_CLAIM))
                        if claimed.get('plan')!=plan_ref or claimed.get('action_claim')!=claim or claimed.get('deletion_contract')!=request['deletion_contract'] or claimed.get('delete_post_ids')!=auth['delete_douyin_only_ids']:raise ValueError('cleanup_global_final_claim_required_before_native_click')
                        final_clicks+=1
                    elif selecting:
                        selector=kw.get('selector');matched=[p for p in auth['delete_douyin_only_ids'] if selector==target_selector(p)]
                        if matched:
                            if matched[0] in selected_clicks:raise ValueError('cleanup_target_checkbox_already_clicked')
                            selected_clicks.add(matched[0])
                        elif selector==adapter.DELETE_ENTRY and not delete_entry_clicks and selected_clicks==set(auth['delete_douyin_only_ids']):delete_entry_clicks+=1
                        else:raise ValueError('cleanup_only_exact_targets_and_toolbar_entry_allowed')
                    else:
                        if native_clicks or kw.get('selector')!=adapter.ENTRY:raise ValueError('cleanup_only_observed_batch_entry_click_allowed')
                        native_clicks+=1
                elif kind=='evaluate':
                    scripts={inspector.INVENTORY_JS,adapter.selection_script(),adapter.final_confirmation_script(contract)} if confirming else {adapter.CURRENT_SELECTION_INSPECTION_JS} if inspecting else {inspector.INVENTORY_JS,adapter.BATCH_JS,adapter.selection_script()} if selecting else {inspector.INVENTORY_JS,adapter.BATCH_JS}
                    if visible_select:scripts|={adapter.recorder_script(plan['interaction_nonce'],mode,auth['delete_douyin_only_ids']) for mode in ('install','snapshot','stop')}
                    ordinary=kw.get('js') in scripts and not kw.get('selector')
                    element=kw.get('js')==adapter.final_confirmation_script(contract,True) and kw.get('selector')==adapter.FINAL_CONFIRM and kw.get('index')==0 if confirming else not inspecting and kw.get('index')==0 and ((kw.get('js')==(adapter.display_probe_script() if visible_select else adapter.selection_script(True)) and kw.get('selector') in {target_selector(p) for p in auth['delete_douyin_only_ids']}) or (kw.get('js')==adapter.selection_script(True) and kw.get('selector')==adapter.DELETE_ENTRY)) if selecting else not inspecting and kw.get('js')==adapter.ENTRY_PROBE and kw.get('selector')==adapter.ENTRY and kw.get('index')==0
                    if not (ordinary or element):
                        raise ValueError('cleanup_batch_only_bound_projection_allowed')
                elif kind=='wait_for_timeout':
                    if type(kw.get('ms')) is not int or not 0<=kw['ms']<=350:raise ValueError('cleanup_batch_wait_limit')
                elif kind=='goto' and confirming:
                    if reloads or final_clicks!=1 or kw.get('url')!=contract['post_confirm_readonly_reload_url'] or kw.get('wait_until')!='commit' or kw.get('timeout')!=30000:raise ValueError('cleanup_only_one_post_confirm_exact_self_reload_allowed')
                    reloads+=1
                elif kind=='screenshot' and inspecting:
                    if Path(kw.get('path','')).resolve()!=folder/'inspection/CURRENT_SELECTION.png' or Path(kw['path']).exists():raise ValueError('cleanup_inspection_screenshot_scope')
                else:raise ValueError('cleanup_batch_rpc_not_allowed')
                try:value=original.cmd(kind,tab_id=raw.tab_id,**kw)
                except Exception as error:
                    if not (folder/'NATIVE_RPC_ERROR.json').exists():once(folder/'NATIVE_RPC_ERROR.json',dict(action=kind,selector=kw.get('selector'),index=kw.get('index'),error_type=type(error).__name__,safe_error=_safe_error(error)))
                    raise
                guard();return value
        evidence=[]
        def checkpoint(stage,value):guard();ref=once(folder/'inspection'/(stage.upper()+'.json'),value);evidence.append(ref);guard();return ref
        checked_page=Page(Gate(),raw.tab_id)
        if confirming:
            value=adapter.confirm_exact_selection(checked_page,guard=guard,checkpoint=checkpoint,inventory_script=inspector.INVENTORY_JS,expected_uid=auth['expected_public_uid'],
                delete_ids=auth['delete_douyin_only_ids'],protected_ids=auth['protected_post_ids'],contract=contract,contract_ref=request['deletion_contract'],selection_result_ref=request['selection_result'],
                claim_final_deletion=lambda ref:claim_final_deletion(actor,resource,config,request,plan_ref,claim,ref),final_claim_path=FINAL_DELETE_CLAIM)
            if (value.get('schema')!='manual_work_final_delete/v1' or final_clicks!=1 or value.get('final_native_click_count')!=1 or value.get('selection_performed') is not False
                    or value.get('final_delete_claim')!=reference(FINAL_DELETE_CLAIM) or value.get('readonly_reload_count')!=reloads
                    or value.get('deleted') is True and (reloads!=1 or value.get('status')!='deletion_verified')):raise ValueError('cleanup_once_final_receipt_required')
        elif inspecting:
            value=adapter.inspect_current_selection(checked_page,guard=guard,checkpoint=checkpoint)
            if value.get('schema')!='manual_work_current_selection/v1' or value.get('native_events_dispatched')!=0 or any(value.get(k) is not False for k in ('selection_performed','delete_entry_clicked','confirmation_performed','deleted')):raise ValueError('cleanup_zero_click_inspection_required')
            guard();dom_ref=once(folder/'inspection/DOM_READBACK.json',value)
            try:
                image=folder/'inspection/CURRENT_SELECTION.png';checked_page._cmd('screenshot',path=str(image),full_page=False);value['screenshot']=dict(status='saved',file=reference(image))
            except Exception as error:value['screenshot']=dict(status='unavailable',error_type=type(error).__name__,safe_error=_safe_error(error))
            value['dom_readback']=dom_ref
            failure=getattr(original,'worker_failure',lambda:'unobservable')()
            value['worker_health_after_optional_screenshot']=dict(healthy=not bool(failure),failure_code=failure)
        else:
            run=adapter.select_visible_targets_open_confirmation if visible_select else adapter.select_targets_open_confirmation if selecting else adapter.open_batch_controls
            kwargs=dict(guard=guard,checkpoint=checkpoint,inventory_script=inspector.INVENTORY_JS,expected_uid=auth['expected_public_uid'],delete_ids=auth['delete_douyin_only_ids'],protected_ids=auth['protected_post_ids'])
            if visible_select:kwargs['event_nonce']=plan['interaction_nonce']
            value=run(checked_page,**kwargs)
        if selecting:
            if (value.get('schema')!='manual_work_cleanup_selection/v1' or set(value.get('selected_ids',[]))!=set(auth['delete_douyin_only_ids'])
                    or selected_clicks!=set(auth['delete_douyin_only_ids']) or delete_entry_clicks!=1
                    or value.get('confirmation_performed') is not False or value.get('deleted') is not False):raise ValueError('cleanup_selection_without_final_confirmation_required')
            if visible_select:
                recorded=value.get('event_recorder_final',{})
                if value.get('event_nonce')!=plan['interaction_nonce'] or recorded.get('nonce')!=plan['interaction_nonce'] or recorded.get('active') is not False or recorded.get('trusted_display_click_counts')!={p:1 for p in auth['delete_douyin_only_ids']} or recorded.get('blocked_event_count')!=0 or recorded.get('outside_target_trusted_clicks')!=0:raise ValueError('cleanup_trusted_visible_events_and_cleanup_required')
        elif not inspecting and not confirming and (value.get('schema')!='manual_work_batch_controls/v1' or value.get('batch_entry_click_count')!=native_clicks or native_clicks!=1
                or any(value.get(k) is not False for k in ('selection_performed','delete_performed','confirmation_performed','delete_allowed'))):raise ValueError('cleanup_batch_readonly_receipt_required')
        if inspecting:
            # The guarded DOM observation is already immutable. A failed
            # best-effort image must not erase it or pretend the worker lives.
            _config(plan['config'])
            if resource.session is not original or _load('inspector_runtime',config)._state(_project(config))!=plan['state']:raise ValueError('cleanup_post_observation_owner_changed')
        else:guard()
        result=once(folder/'RESULT.json',dict(schema='manual_work_final_delete_result/v1' if confirming else 'manual_work_current_selection_result/v1' if inspecting else 'manual_work_cleanup_selection_result/v1' if selecting else 'manual_work_batch_result/v1',plan=plan_ref,claim=claim,inspection=value,evidence=evidence,
            batch_entry_native_dispatches=native_clicks,target_native_dispatches=sorted(selected_clicks),delete_entry_native_dispatches=delete_entry_clicks,
            final_confirmation_native_dispatches=final_clicks,readonly_reload_dispatches=reloads,native_rpc_error=reference(folder/'NATIVE_RPC_ERROR.json') if (folder/'NATIVE_RPC_ERROR.json').is_file() else None,
            deleted=value.get('deleted') is True if confirming else False,selected=selecting,delete_allowed=False,account_pause_changed=False,original_records_and_claims_unchanged=True))
        return dict(status=value['status'] if confirming else 'current_selection_observed' if inspecting else 'selection_observed' if selecting else 'batch_controls_observed',result=result)
    except Exception as error:
        once(folder/'UNKNOWN.json',dict(schema='manual_work_batch_unknown/v1',plan=plan_ref,claim=claim,error_type=type(error).__name__,safe_error=_safe_error(error),reason=str(error) if isinstance(error,ValueError) else 'native_batch_read_failed',batch_entry_native_dispatches=native_clicks,
            target_native_dispatches=sorted(selected_clicks),delete_entry_native_dispatches=delete_entry_clicks,final_confirmation_native_dispatches=final_clicks,readonly_reload_dispatches=reloads,
            final_delete_claim=reference(FINAL_DELETE_CLAIM) if FINAL_DELETE_CLAIM.is_file() else None,native_rpc_error=reference(folder/'NATIVE_RPC_ERROR.json') if (folder/'NATIVE_RPC_ERROR.json').is_file() else None,automatic_replay_allowed=False,deleted=False))
        return dict(status='batch_observation_unknown',automatic_replay_allowed=False)


def install_if_armed(plan_ref,arm_ref):
    try:
        if reference(ARM)!=arm_ref or read(arm_ref)!={'schema':'manual_republication_runtime_arm/v10','plan':plan_ref}:raise ValueError('cleanup_exact_batch_arm_required')
        plan,config,request=_plan(plan_ref);folder=Path(plan_ref['path']).parent
        if os.getpid()!=config['backend_pid']:return dict(status='different_process_no_install')
        if status(plan_ref)['status']!='prepared':return status(plan_ref)
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive() and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'] and getattr(t,'_args',())==(config['account_key'],)]
        if len(spaces)!=1:raise ValueError('cleanup_unique_original_batch_actor_required')
        namespace=spaces[0];previous=namespace['_poll_manual_windows']
        if getattr(previous,'_manual_cleanup_plan',None)==plan_ref:return dict(status='callback_already_registered')
        if getattr(previous,'_manual_cleanup_plan',None) is not None:raise ValueError('cleanup_other_plan_registered')
        def poll(actor,resource):
            if (actor.account_id,actor.owner_id,actor.generation)!=(config['account_id'],config['owner_id'],config['generation']):return previous(actor,resource)
            defer=False
            try:
                actor._assert_thread();actor._check_owner();value=previous(actor,resource)
                if actor._stack:defer=True;return value
                _perform(actor,resource,plan_ref,arm_ref)
            except Exception as error:
                if not (folder/'REFUSED.json').exists():once(folder/'REFUSED.json',dict(error_type=type(error).__name__,action_started=(folder/'ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_cleanup_plan=plan_ref;namespace['_poll_manual_windows']=poll
        return dict(status='callback_registered_waiting_original_actor_tick')
    except Exception as error:return dict(status='refused',error_type=type(error).__name__,reason=str(error) if isinstance(error,ValueError) else 'cleanup_batch_guard_refused')
