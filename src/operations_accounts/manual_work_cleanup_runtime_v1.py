"""Original-actor cleanup inventory only; no deletion action is implemented."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import types

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1'
ARM=ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1/manual_runtime_v10/ARM.json'
PLAN_SCHEMA='manual_work_cleanup_plan/v1'
CONFIG_SCHEMA='manual_republication_runtime_config/v10'  # Stable cached loader admission only.
ACTION='inspect_cards_only'
SOURCE_PATHS={
    'runtime_v10':ROOT/'src/operations_accounts/manual_republication_runtime_v10.py',
    'cleanup_runtime':Path(__file__).resolve(),
    'adapter':ROOT/'src/platform_adapter/douyin_work_cleanup_v1.py',
    'guard_v1':ROOT/'src/operations_accounts/manual_republication_runtime_v1.py',
    'flow_v1':ROOT/'src/operations_accounts/manual_republication_flow_v1.py',
    'app':ROOT/'src/web/app.py','host':ROOT/'src/operations_accounts/browser_control_runtime.py',
    'browser_session':ROOT/'src/platform_adapter/browser_session.py',
}
DELETE_CANDIDATES={'7709043480894524722','7708948487446056192'}
PROTECTED={'7709219071845256488','7700201288079920427'}
PINNED_SCOPE=dict(backend_pid=15996,backend_create_time=1794839021.466901,account_key='novel_account_02',account_id='account:9158f1d29f70eff9819c46b4',
    owner_id='backend:15996:0ac797390b494944895c93290208941a',generation=33,binding_version='8132c743df4e628fec8dcbec22de03dc419ab7ff0e0f11ac535c550d5cbfce49',
    manual_command_id='d57c1fd794854d949d91a8f17d09b702',manual_request_sha256='259b3458158c4ffed10926784563f60e05f3fb847038a66e66e58d1113590f10',
    tab_id='tab-2ca2337788b34674a816b4ae28ec2708-2',browser_db=str(ROOT/'data/account_browser_control.db'),control_db=str(ROOT/'data/account_refresh.db'),control_snapshot={'state':'paused','revision':59})


def reference(path):
    path=Path(path).resolve()
    if not path.is_file() or not path.is_relative_to(ROOT):raise ValueError('cleanup_project_reference_required')
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def read(ref):
    if not isinstance(ref,dict) or set(ref)!={'path','sha256'} or reference(ref['path'])!=ref:raise ValueError('cleanup_reference_changed')
    return json.loads(Path(ref['path']).read_text(encoding='utf-8-sig'))


def once(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True);f.flush();os.fsync(f.fileno())
    return reference(path)


def _process(pid):
    import psutil
    return psutil.Process(pid).create_time()


def _load(key,config):
    path=SOURCE_PATHS[key];ref=config['sources'][key]
    raw=path.read_bytes()
    if reference(path)!=ref or hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('cleanup_source_changed:'+key)
    mod=types.ModuleType('src.'+('platform_adapter' if key=='adapter' else 'operations_accounts')+'._cleanup_'+key+'_'+ref['sha256'][:16])
    mod.__file__,mod.__package__=str(path),'src.platform_adapter' if key=='adapter' else 'src.operations_accounts'
    exec(compile(raw,str(path),'exec'),mod.__dict__);return mod


def _scope(config):
    fields={'schema','backend_pid','backend_create_time','account_key','account_id','owner_id','generation','binding_version','browser_db','control_db',
            'control_snapshot','manual_command_id','manual_request_sha256','tab_id','authority','sources'}
    if (set(config)!=fields or config['schema']!=CONFIG_SCHEMA or type(config['backend_pid']) is not int
            or type(config['generation']) is not int or config['generation']<1
            or not config['owner_id'].startswith('backend:'+str(config['backend_pid'])+':')
            or _process(config['backend_pid'])!=config['backend_create_time']):raise ValueError('cleanup_original_process_scope_required')
    if any(config.get(k)!=v for k,v in PINNED_SCOPE.items()):raise ValueError('cleanup_exact_original_manual_scope_required')
    if set(config['sources'])!=set(SOURCE_PATHS):raise ValueError('cleanup_exact_sources_required')
    for key,path in SOURCE_PATHS.items():
        if reference(path)!=config['sources'][key]:raise ValueError('cleanup_source_changed:'+key)
    if Path(config['authority']['path']).resolve()!=RUN/'USER_AUTHORIZATION.json':raise ValueError('cleanup_exact_authority_required')
    auth=read(config['authority'])
    if (auth.get('schema')!='explicit_platform_cleanup_rebind_authorization/v1' or not auth.get('user_statement')
            or auth.get('account_key')!=config['account_key'] or auth.get('account_uuid')!=config['account_id'] or auth.get('expected_public_uid')!='75891235130'
            or set(auth.get('delete_douyin_only_ids',[]))!=DELETE_CANDIDATES or set(auth.get('protected_post_ids',[]))!=PROTECTED
            or auth.get('requires_current_native_reduced_traffic_label') is not True or auth.get('new_publication_allowed') is not False
            or auth.get('old_unknowns_and_claims_unchanged') is not True or auth.get('models_and_media_calls_allowed') is not False):raise ValueError('cleanup_authority_scope_invalid')
    return auth


def _config(ref):
    config=read(ref);_scope(config);return config


def _request(ref,config_ref):
    value=read(ref)
    if set(value)!={'schema','config','action'} or value['schema']!='manual_work_cleanup_request/v1' or value['config']!=config_ref or value['action']!=ACTION:
        raise ValueError('cleanup_inventory_only_request_required')
    return value


def _state(config):return _load('guard_v1',config)._state(config)


def validate_live(actor,resource,config):
    auth=_scope(config);state=_load('guard_v1',config).validate_live(actor,resource,config)
    binding=resource.runtime.bindings.get(config['account_key']);profile=resource.runtime.profiles.get(config['account_key'])
    reader=_load('flow_v1',config)
    if (binding.account_uuid!=config['account_id'] or profile.account_uuid!=config['account_id']
            or reader._binding_version(types.SimpleNamespace(binding=binding,profile=profile))!=config['binding_version']
            or str(binding.public_uid)!=auth['expected_public_uid']):raise ValueError('cleanup_bound_original_identity_changed')
    return state


def prepare(config_ref,request_ref,output_directory):
    directory=Path(output_directory).resolve()
    if directory!=RUN/'inspect_001' or directory.exists():raise ValueError('cleanup_unique_new_inventory_directory_required')
    config=_config(config_ref);_request(request_ref,config_ref);state=_state(config)
    snapshots={}
    for key in ('runtime_v10','cleanup_runtime','adapter'):
        path=directory/'producer_sources'/(key+'.py');path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(SOURCE_PATHS[key].read_bytes())
        snapshots[key]=reference(path)
        if snapshots[key]['sha256']!=config['sources'][key]['sha256']:raise ValueError('cleanup_producer_source_changed')
    return once(directory/'PLAN.json',dict(schema=PLAN_SCHEMA,config=config_ref,request=request_ref,state=state,action=ACTION,
        producer_source_snapshot=snapshots,navigations_allowed=0,input_actions_allowed=0,delete_entries_allowed=0,delete_confirmations_allowed=0,api_requests_allowed=0))


def _plan(ref):
    value=read(ref)
    if value.get('schema')!=PLAN_SCHEMA or Path(ref['path']).resolve()!=RUN/'inspect_001/PLAN.json' or value.get('action')!=ACTION:
        raise ValueError('cleanup_original_plan_required')
    config=_config(value['config']);request=_request(value['request'],value['config'])
    if any(type(value.get(k)) is not int or value[k]!=0 for k in ('navigations_allowed','input_actions_allowed','delete_entries_allowed','delete_confirmations_allowed','api_requests_allowed')):
        raise ValueError('cleanup_inventory_effect_limit_changed')
    for key,source in value['producer_source_snapshot'].items():
        if reference(source['path'])!=source or source['sha256']!=config['sources'][key]['sha256']:raise ValueError('cleanup_producer_changed')
    return value,config,request


def status(plan_ref):
    _plan(plan_ref);folder=Path(plan_ref['path']).parent
    if (folder/'RESULT.json').is_file():return dict(status='inventory_completed',result=reference(folder/'RESULT.json'))
    return dict(status='observation_unknown',automatic_replay_allowed=False) if (folder/'ACTION_CLAIM.json').exists() else dict(status='prepared',plan=plan_ref)


def _perform(actor,resource,plan_ref,arm_ref):
    plan,config,request=_plan(plan_ref);state=validate_live(actor,resource,config)
    if state!=plan['state'] or reference(ARM)!=arm_ref:raise ValueError('cleanup_context_changed')
    folder=Path(plan_ref['path']).parent
    if status(plan_ref)['status']!='prepared':return status(plan_ref)
    claim=once(folder/'ACTION_CLAIM.json',dict(schema='manual_work_cleanup_action_claim/v1',plan=plan_ref,request=plan['request'],
        owner_id=actor.owner_id,generation=actor.generation,tab_id=config['tab_id'],actor_thread_id=threading.get_ident(),at_epoch=time.time(),action=ACTION,
        input_actions_allowed=0,delete_entries_allowed=0,delete_confirmations_allowed=0,navigations_allowed=0))
    session=resource.session;deadline=time.monotonic()+150
    def guard():
        if time.monotonic()>deadline or resource.session is not session:raise ValueError('cleanup_session_or_budget_changed')
        if reference(ARM)!=arm_ref or validate_live(actor,resource,config)!=plan['state']:raise ValueError('cleanup_original_context_changed')
    try:
        guard();page=session.get_page(config['tab_id']);guard()
        if page._session is not session or page.tab_id!=config['tab_id']:raise ValueError('cleanup_original_page_required')
        evidence=[]
        def checkpoint(stage,value):guard();ref=once(folder/'inspection'/(stage.upper()+'.json'),value);evidence.append(ref);guard()
        value=_load('adapter',config).inspect_cards(page,guard=guard,checkpoint=checkpoint)
        if (value.get('schema')!='manual_work_cleanup_inventory/v1' or value.get('navigations_count')!=0 or value.get('api_request_count')!=0
                or any(value.get(k) is not False for k in ('input_performed','delete_entry_clicked','deletion_confirmed','submitted','file_selected','published','delete_allowed'))):raise ValueError('cleanup_readonly_receipt_required')
        guard();auth=read(config['authority']);cards=value['inventory'].get('cards',[])
        candidates=[c['native_post_id'] for c in cards if c.get('native_id_bound') is True and c.get('native_post_id') in DELETE_CANDIDATES and c.get('status_text')=='流量减少']
        return_ref=once(folder/'RESULT.json',dict(schema='manual_work_cleanup_result/v1',plan=plan_ref,claim=claim,inspection=value,evidence=evidence,
            native_reduced_traffic_candidates=candidates,protected_post_ids=auth['protected_post_ids'],actual_public_uid_matches=value['inventory'].get('public_uids')==[auth['expected_public_uid']],
            delete_allowed=False,deleted=False,account_pause_changed=False,old_claims_and_records_unchanged=True))
        return dict(status='inventory_completed',result=return_ref)
    except Exception as error:
        if not (folder/'UNKNOWN.json').exists():once(folder/'UNKNOWN.json',dict(schema='manual_work_cleanup_unknown/v1',plan=plan_ref,claim=claim,error_type=type(error).__name__,reason=str(error) if isinstance(error,ValueError) else 'native_observation_failed',deleted=False,automatic_replay_allowed=False))
        return dict(status='observation_unknown',automatic_replay_allowed=False)


def install_if_armed(plan_ref,arm_ref):
    try:
        arm=read(arm_ref)
        if reference(ARM)!=arm_ref or arm!={'schema':'manual_republication_runtime_arm/v10','plan':plan_ref}:raise ValueError('cleanup_exact_arm_required')
        plan,config,request=_plan(plan_ref);folder=Path(plan_ref['path']).parent
        if os.getpid()!=config['backend_pid']:return dict(status='different_process_no_install')
        if status(plan_ref)['status']!='prepared':return status(plan_ref)
        spaces=[t._target.__globals__ for t in threading.enumerate() if t.name=='AccountBrowser-'+config['account_key'] and t.is_alive()
            and getattr(getattr(t,'_target',None),'__name__','')=='_host' and Path(t._target.__code__.co_filename).resolve()==SOURCE_PATHS['host'] and getattr(t,'_args',())==(config['account_key'],)]
        if len(spaces)!=1:raise ValueError('cleanup_unique_original_actor_required')
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
    except Exception as error:return dict(status='refused',error_type=type(error).__name__,reason=str(error) if isinstance(error,ValueError) else 'cleanup_guard_refused')
