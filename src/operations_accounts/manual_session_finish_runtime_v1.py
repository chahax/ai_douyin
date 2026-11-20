"""One original-actor session finish after immutable native backfill success.

No account recovery, publication, queue, worker shutdown, or direct manual
settlement is exposed. Existing host polling owns normal manual settlement.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import types
from datetime import date

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1'
ARM=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1/manual_runtime_v10/ARM.json'
ACTION='finish_original_manual'
NATIVE_ID=dict(platform_identity_key='uid:2521598930983028',native_kind='promotion_alias',native_record_id='7709342031922872345')
PUBLICATION=dict(canonical_url='https://www.douyin.com/video/7709219071845256488',post_id='7709219071845256488',native_created_epoch=1794942450,publish_date='2026-11-18')
SOURCE_PATHS={
 'runtime_v10':ROOT/'src/operations_accounts/manual_republication_runtime_v10.py','cleanup_runtime':Path(__file__).resolve(),
 'leaf':ROOT/'src/operations_accounts/manual_session_finish_v1.py','inspector_runtime':ROOT/'src/operations_accounts/manual_work_cleanup_runtime_v1.py',
 'inspector_adapter':ROOT/'src/platform_adapter/douyin_work_cleanup_v1.py','guard_v1':ROOT/'src/operations_accounts/manual_republication_runtime_v1.py',
 'flow_v1':ROOT/'src/operations_accounts/manual_republication_flow_v1.py','app':ROOT/'src/web/app.py',
 'host':ROOT/'src/operations_accounts/browser_control_runtime.py','browser_session':ROOT/'src/platform_adapter/browser_session.py'}


def reference(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('finish_project_reference_required')
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def read(ref):
    if not isinstance(ref,dict) or set(ref)!={'path','sha256'} or reference(ref['path'])!=ref:raise ValueError('finish_reference_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def once(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    return reference(path)


def need(condition,code):
    if not condition:raise ValueError('finish_'+code)


def _load(key,config):
    path=SOURCE_PATHS[key];raw=path.read_bytes();need(reference(path)==config['sources'][key],'source_changed_'+key)
    mod=types.ModuleType('src.operations_accounts._finish_'+key+'_'+config['sources'][key]['sha256'][:16]);mod.__file__,mod.__package__=str(path),'src.operations_accounts'
    exec(compile(raw,str(path),'exec'),mod.__dict__);return mod


def _project(config):
    sources={k:v for k,v in config['sources'].items() if k not in {'leaf','inspector_runtime','inspector_adapter'}}
    sources['cleanup_runtime']=config['sources']['inspector_runtime'];sources['adapter']=config['sources']['inspector_adapter']
    return dict(config,sources=sources)


def _config(ref):
    config=read(ref);need(set(config.get('sources',{}))==set(SOURCE_PATHS),'exact_sources_required')
    for key,path in SOURCE_PATHS.items():need(reference(path)==config['sources'][key],'source_changed_'+key)
    _load('inspector_runtime',config)._scope(_project(config));return config


def _request(ref,config_ref):
    request=read(ref)
    need(set(request)=={'schema','config','action','completion'} and request['schema']=='manual_session_finish_request/v1'
        and request['config']==config_ref and request['action']==ACTION,'named_request_required')
    return request


def verify_completion(completion_ref,config):
    """Check the actual command, claim, preflight and scoped native date/URL.

    Historical source seals and snapshots are hashes, never current TTL or a
    reason to rerun Fanqie. No Root boolean substitutes for native evidence.
    """
    completion=read(completion_ref)
    need(set(completion)=={'schema','result','receipt'} and completion['schema']=='verified_fanqie_cleanup_rebind_completion/v1','completion_refs_required')
    result=read(completion['result']);subject=result.get('subject',{});request_ref=result.get('request');request=read(request_ref)
    need(set(subject)=={'resource_id','binding_version','environment_key','platform_identity_key','owner_id','generation','task_id'}
        and re.fullmatch(r'[0-9a-f]{32}',str(subject.get('task_id',''))) is not None,'exact_fanqie_subject_required')
    folder=ROOT/'data/fanqie_account_control/commands'/subject['task_id']
    need(Path(completion['result']['path']).resolve()==folder/'CLEANUP_REBIND_RESULT.json'
        and Path(completion['receipt']['path']).resolve()==folder/'CLEANUP_REBIND_RESULT_BINDING.json','original_fanqie_result_directory_required')
    need(read(completion['receipt'])==dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=request_ref,subject=subject,result=completion['result']),'fanqie_receipt_changed')
    need(result.get('schema')=='fanqie_cleanup_rebind_command_result/v1' and result.get('broker_state')=='succeeded'
        and result.get('result',{}).get('status')=='new_backfill_confirmed' and result['result'].get('business_confirmed') is True,'native_backfill_not_confirmed')
    auth=read(config['authority'])
    need(request.get('schema')=='fanqie_cleanup_rebind_request/v1' and request.get('action')=='bind_new_publication' and request.get('draft_only') is False
        and request.get('authority')==config['authority'] and request.get('resource_id')==auth.get('fanqie_resource_id')=='fanqie:52ce7e06afc9451b8a81bfd9269ad94e'
        and request.get('platform_identity_key')==auth.get('fanqie_identity')=='uid:2521598930983028'
        and request.get('book_id')==auth.get('book_id')=='7302660145530539062' and request.get('book_name')==auth.get('book_name')=='你敢惹我？我有六个反派儿子'
        and request.get('alias')==auth.get('preferred_recreated_alias')=='从旧饭桌开始改命' and request.get('publish_type')=='AIGC'
        and request.get('new_publication')==PUBLICATION and request.get('new_native_identity')==NATIVE_ID
        and all(subject[k]==request[k] for k in ('resource_id','binding_version','environment_key','platform_identity_key')),'original_backfill_target_changed')
    verified=read(request['verified_publication'])
    need(verified.get('schema')=='verified_declared_publication/v1' and verified.get('post_verified') is True and verified.get('numeric_duration_verified') is True
        and verified.get('account_uuid')==config['account_id'] and verified.get('expected_public_uid')=='75891235130'
        and verified.get('post_id')==PUBLICATION['post_id'] and verified.get('canonical_url')==PUBLICATION['canonical_url']
        and verified.get('native_created_epoch')==PUBLICATION['native_created_epoch'],'original_verified_publication_changed')
    value=result['result'].get('native_result',{})
    need(value.get('status')=='new_backfill_confirmed' and value.get('submitted') is True and value.get('new_native_identity')==NATIVE_ID
        and value.get('automatic_retry') is False,'native_result_required')
    claim_ref=value.get('claim');claim=read(claim_ref)
    need(Path(claim_ref['path']).resolve()==RUN/'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json'
        and claim.get('schema')=='fanqie_replacement_backfill_claim/v1' and claim.get('request')==request_ref and claim.get('subject')==subject
        and claim.get('automatic_replay_allowed') is False,'original_backfill_claim_required')
    preflight=read(claim['preflight'])
    need(Path(claim['preflight']['path']).resolve()==folder/'replacement/BACKFILL_PREFLIGHT.json'
        and preflight.get('schema')=='fanqie_replacement_backfill_preflight/v1' and preflight.get('request')==request_ref
        and preflight.get('subject')==subject and preflight.get('target')==claim.get('target')
        and preflight.get('native_identity')==NATIVE_ID and preflight.get('new_publication')==PUBLICATION
        and all(preflight.get('target',{}).get(k)==request[k] for k in ('book_id','book_name','alias','publish_type')),'bound_backfill_preflight_required')
    form=preflight.get('actual_form',{})
    need(form.get('eligible') is True and form.get('scope_count')==1 and form.get('input_count')==2 and form.get('other_inputs')==[]
        and form.get('identity')==dict(book_name=request['book_name'],alias=request['alias'],aigc=True)
        and form.get('date',{}).get('value')==PUBLICATION['publish_date'] and form.get('link',{}).get('value')==PUBLICATION['canonical_url'],'exact_submitted_form_required')
    readback_ref=value.get('readback');readback=read(readback_ref);scope=readback.get('scope',{});text=scope.get('scope',{}).get('visible_text','')
    need(Path(readback_ref['path']).resolve()==folder/'replacement/READBACK_RECORDS.json' and scope.get('eligible') is True
        and scope.get('retained_link_observed') is True and isinstance(text,str) and 0<len(text)<12000,'native_scoped_readback_required')
    pairs=re.findall(r'发文时间\s+(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s+发文链接\s+(https://(?:www\.)?douyin\.com/video/\d{10,24})(?!\d)',text)
    records=[dict(canonical_url=url,publish_date=date(*map(int,re.split(r'[-./]',day))).isoformat()) for day,url in pairs]
    need(len(pairs)>0 and text.count('发文时间')==len(pairs) and records==readback.get('records')==value.get('records')
        and dict(canonical_url=PUBLICATION['canonical_url'],publish_date=PUBLICATION['publish_date']) in records
        and request['book_name'] in text and request['alias'] in text and 'AIGC' in text,'native_date_link_readback_mismatch')
    with sqlite3.connect(Path(config['browser_db']).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(subject['task_id'],)).fetchone()
    need(row is not None and row['state']=='succeeded' and row['kind']=='fanqie_cleanup_rebind' and row['account_id']==subject['resource_id']
        and row['owner_id']==subject['owner_id'] and row['generation']==subject['generation'] and row['binding_version']==subject['binding_version']
        and json.loads(row['payload'])==dict(environment_key=subject['environment_key'],request=request_ref)
        and json.loads(row['result'])==dict(result['result'],result_evidence=completion['result']),'actual_terminal_fanqie_command_required')
    for ref in request.get('original_records',[]):need(reference(ref['path'])==ref,'historical_record_changed')
    return True


def validate_live(actor,resource,config):
    return _load('inspector_runtime',config).validate_live(actor,resource,_project(config))


def prepare(config_ref,request_ref,output_directory):
    folder=Path(output_directory).resolve();need(folder==RUN/'manual_finish_001' and not folder.exists(),'unique_finish_directory_required')
    config=_config(config_ref);request=_request(request_ref,config_ref);verify_completion(request['completion'],config)
    need(not (RUN/'MANUAL_SESSION_FINISH_CLAIM.json').exists(),'finish_already_claimed')
    state=_load('inspector_runtime',config)._state(_project(config));leaf=_load('leaf',config);snapshots={}
    for key in ('runtime_v10','cleanup_runtime','leaf'):
        p=folder/'producer_sources'/(key+'.py');p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(SOURCE_PATHS[key].read_bytes())
        snapshots[key]=reference(p)
    permit=once(RUN/'MANUAL_SESSION_FINISH_PERMIT.json',dict(schema='original_manual_session_finish_permit/v1',scope=leaf.SCOPE,cleanup_authority=config['authority'],
        completion_ref=request['completion'],helper_source=config['sources']['leaf'],save_state_calls_allowed=1,close_tab_calls_allowed=1,account_recovery_allowed=False))
    return once(folder/'PLAN.json',dict(schema='manual_work_cleanup_plan/v1',config=config_ref,request=request_ref,action=ACTION,state=state,permit=permit,
        producer_source_snapshot=snapshots,save_state_calls_allowed=1,close_tab_calls_allowed=1,account_recovery_allowed=False))


def _plan(ref):
    plan=read(ref);need(Path(ref['path']).resolve()==RUN/'manual_finish_001/PLAN.json' and plan.get('schema')=='manual_work_cleanup_plan/v1'
        and plan.get('action')==ACTION and plan.get('save_state_calls_allowed')==1 and plan.get('close_tab_calls_allowed')==1 and plan.get('account_recovery_allowed') is False,'exact_finish_plan_required')
    config=_config(plan['config']);request=_request(plan['request'],plan['config']);verify_completion(request['completion'],config)
    permit=read(plan['permit']);need(permit.get('completion_ref')==request['completion'] and permit.get('cleanup_authority')==config['authority']
        and permit.get('helper_source')==config['sources']['leaf'],'finish_permit_changed')
    for key,ref in plan['producer_source_snapshot'].items():need(reference(ref['path'])==ref and ref['sha256']==config['sources'][key]['sha256'],'finish_producer_changed')
    return plan,config,request


def status(plan_ref):
    folder=Path(plan_ref['path']).resolve().parent
    if (folder/'CALLER_RESULT.json').is_file():
        value=read(reference(folder/'CALLER_RESULT.json'));need(value.get('plan')==plan_ref,'finish_result_changed');read(value['leaf_result'])
        return dict(status='finish_action_observed',result=reference(folder/'CALLER_RESULT.json'))
    _plan(plan_ref)
    if (folder/'CALLER_ACTION_CLAIM.json').exists():return dict(status='finish_unknown_no_replay',automatic_replay_allowed=False)
    return dict(status='prepared',plan=plan_ref)


def _perform(actor,resource,plan_ref,arm_ref):
    plan,config,request=_plan(plan_ref);folder=Path(plan_ref['path']).parent
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    original=resource.session
    def guard():
        _config(plan['config']);verify_completion(request['completion'],config)
        need(reference(ARM)==arm_ref and read(arm_ref)==dict(schema='manual_republication_runtime_arm/v10',plan=plan_ref)
            and resource.session is original and validate_live(actor,resource,config)==plan['state'],'original_finish_context_changed')
    guard();claim=once(folder/'CALLER_ACTION_CLAIM.json',dict(schema='original_manual_session_finish_caller_claim/v1',plan=plan_ref,request=plan['request'],permit=plan['permit'],
        owner_id=actor.owner_id,generation=actor.generation,actor_thread_id=threading.get_ident(),automatic_replay_allowed=False))
    try:
        result=_load('leaf',config).close_original_manual_once(actor,resource,permit_ref=plan['permit'],outdir=folder,guard=guard,
            verify_completion=lambda ref:verify_completion(ref,config))
        value=read(result)
        need(value.get('manual_completed_by_helper') is False and value.get('account_pause_changed') is False and value.get('recovery_requested') is False,'leaf_effects_changed')
        _config(plan['config'])
        return once(folder/'CALLER_RESULT.json',dict(schema='original_manual_session_finish_caller_result/v1',plan=plan_ref,claim=claim,leaf_result=result,
            status=value.get('status','finish_unknown_no_replay'),manual_settlement_pending=True if value.get('tab_close_acknowledged') is True else None if value.get('close_tab_dispatches')==1 else False,
            account_recovery_requested=False))
    except Exception as error:
        return once(folder/'CALLER_UNKNOWN.json',dict(schema='original_manual_session_finish_caller_unknown/v1',plan=plan_ref,claim=claim,error_type=type(error).__name__,automatic_replay_allowed=False))


def install_if_armed(plan_ref,arm_ref):
    try:
        need(reference(ARM)==arm_ref and read(arm_ref)==dict(schema='manual_republication_runtime_arm/v10',plan=plan_ref),'exact_finish_arm_required')
        plan,config,request=_plan(plan_ref);folder=Path(plan_ref['path']).parent
        if os.getpid()!=config['backend_pid']:return dict(status='different_process_no_install')
        if status(plan_ref)['status']!='prepared':return status(plan_ref)
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'] and getattr(t,'_args',())==(config['account_key'],)]
        need(len(spaces)==1,'unique_original_actor_required');namespace=spaces[0];previous=namespace['_poll_manual_windows']
        if getattr(previous,'_manual_cleanup_plan',None)==plan_ref:return dict(status='callback_already_registered')
        need(getattr(previous,'_manual_cleanup_plan',None) is None,'another_cleanup_registered')
        def poll(actor,resource):
            if (actor.account_id,actor.owner_id,actor.generation)!=(config['account_id'],config['owner_id'],config['generation']):return previous(actor,resource)
            defer=False
            try:
                actor._assert_thread();actor._check_owner();value=previous(actor,resource)
                if actor._stack:defer=True;return value
                _perform(actor,resource,plan_ref,arm_ref)
            except Exception as error:
                if not (folder/'REFUSED.json').exists():once(folder/'REFUSED.json',dict(error_type=type(error).__name__,action_started=(folder/'CALLER_ACTION_CLAIM.json').exists()))
            finally:
                if not defer and namespace['_poll_manual_windows'] is poll:namespace['_poll_manual_windows']=previous
            return None
        poll._manual_cleanup_plan=plan_ref;namespace['_poll_manual_windows']=poll
        return dict(status='callback_registered_waiting_original_actor_tick')
    except Exception as error:return dict(status='refused',error_type=type(error).__name__,reason=str(error) if isinstance(error,ValueError) else 'finish_guard_refused')
