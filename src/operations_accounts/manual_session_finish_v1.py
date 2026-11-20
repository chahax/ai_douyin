"""Save and close one original manual tab; normal host polling settles it.

This leaf has no loader, recovery, publication, queue, or manual-settlement API.
Its caller supplies the reviewed original-actor/source guard and a strict
validator for the immutable, successful Fanqie completion receipt.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time


ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1'
SCOPE=dict(account_key='novel_account_02',account_id='account:9158f1d29f70eff9819c46b4',
    owner_id='backend:15996:0ac797390b494944895c93290208941a',generation=33,
    binding_version='8132c743df4e628fec8dcbec22de03dc419ab7ff0e0f11ac535c550d5cbfce49',
    manual_command_id='d57c1fd794854d949d91a8f17d09b702',
    manual_request_sha256='259b3458158c4ffed10926784563f60e05f3fb847038a66e66e58d1113590f10',
    tab_id='tab-2ca2337788b34674a816b4ae28ec2708-2')


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


def close_original_manual_once(actor,resource,*,permit_ref,outdir,guard,verify_completion):
    """Run only on the original actor after a verified completion permit.

    ``guard`` must recheck the pinned backend, original binding, paused control,
    original manual request, and reviewed sources. ``verify_completion`` must
    independently validate the actual Fanqie receipt and return exactly True.
    Neither callback is optional. A consumed claim is never replayed.
    """
    folder=Path(outdir).resolve()
    if folder!=RUN/'manual_finish_001' or Path(permit_ref['path']).resolve()!=RUN/'MANUAL_SESSION_FINISH_PERMIT.json':
        raise ValueError('finish_exact_named_intent_required')
    permit=read(permit_ref)
    if (set(permit)!={'schema','scope','cleanup_authority','completion_ref','helper_source','save_state_calls_allowed','close_tab_calls_allowed','account_recovery_allowed'}
            or permit['schema']!='original_manual_session_finish_permit/v1' or permit['scope']!=SCOPE
            or permit['helper_source']!=reference(__file__) or permit['save_state_calls_allowed']!=1 or permit['close_tab_calls_allowed']!=1
            or permit['account_recovery_allowed'] is not False):raise ValueError('finish_exact_permission_required')
    if (RUN/'MANUAL_SESSION_FINISH_CLAIM.json').exists():raise FileExistsError('finish_original_intent_already_claimed')
    authority=read(permit['cleanup_authority'])
    if (Path(permit['cleanup_authority']['path']).resolve()!=RUN/'USER_AUTHORIZATION.json'
            or authority.get('account_key')!=SCOPE['account_key'] or authority.get('account_uuid')!=SCOPE['account_id']
            or authority.get('expected_public_uid')!='75891235130'):raise ValueError('finish_original_authority_required')
    if verify_completion(permit['completion_ref']) is not True:raise ValueError('finish_fanqie_success_not_verified')
    completion_hash=reference(permit['completion_ref']['path'])
    if completion_hash!=permit['completion_ref']:raise ValueError('finish_completion_changed')
    original=resource.session;process=getattr(original,'_proc',None)
    def check():
        guard();actor._assert_thread();actor._check_owner()
        if (resource.session is not original or getattr(original,'_proc',None) is not process or process is None
                or process.poll() is not None or original.worker_failure() or original.config.headless is not False
                or actor.account_id!=SCOPE['account_id'] or actor.owner_id!=SCOPE['owner_id'] or actor.generation!=SCOPE['generation']
                or actor._stack or getattr(resource,'console_tasks',{}) or resource.manual_tasks!={SCOPE['manual_command_id']:SCOPE['tab_id']}):
            raise ValueError('finish_original_live_manual_required')
        command=actor.store.get(SCOPE['manual_command_id'])
        if (not command or command.get('kind')!='manual' or command.get('state')!='waiting_human'
                or command.get('account_id')!=SCOPE['account_id'] or command.get('owner_id')!=SCOPE['owner_id'] or command.get('generation')!=SCOPE['generation']
                or command.get('binding_version')!=SCOPE['binding_version'] or command.get('request_sha')!=SCOPE['manual_request_sha256']
                or command.get('result',{}).get('tab_id')!=SCOPE['tab_id']):raise ValueError('finish_original_manual_changed')
        if reference(permit_ref['path'])!=permit_ref or reference(__file__)!=permit['helper_source'] or reference(permit['completion_ref']['path'])!=completion_hash:
            raise ValueError('finish_source_or_completion_changed')
    check()
    status=original.window_status();check()
    matches=[t for t in status.get('tabs',[]) if t.get('tab_id')==SCOPE['tab_id']]
    if (status.get('context_closed') is True or len(matches)!=1 or matches[0].get('closed') is not False or matches[0].get('role')!='manual'):
        raise ValueError('finish_exact_open_manual_tab_required')
    # The caller guard binds this live storage-state path to the original profile.
    state_path=original.config.storage_state_path
    if not state_path or Path(state_path).resolve()!=Path(resource.context.storage_state_path).resolve():raise ValueError('finish_original_state_path_changed')
    claim=once(RUN/'MANUAL_SESSION_FINISH_CLAIM.json',dict(schema='original_manual_session_finish_claim/v1',permit=permit_ref,
        completion_ref=completion_hash,scope=SCOPE,actor_thread_id=threading.get_ident(),at_epoch=time.time(),save_state_calls_allowed=1,
        close_tab_calls_allowed=1,automatic_replay_allowed=False,account_recovery_allowed=False))
    saves=closes=0;saved=False;closed=False
    try:
        check();saves=1
        save_ack=original.cmd('save_state',path=state_path)
        saved=isinstance(save_ack,dict) and save_ack.get('state_saved') is True
        once(folder/'SAVE_STATE_ACK.json',dict(state_saved=saved,ack_returned=True))
        if not saved:raise ValueError('finish_state_saved_not_confirmed')
        check();closes=1
        close_ack=original.close_tab(SCOPE['tab_id'])
        closed=isinstance(close_ack,dict) and close_ack.get('tab_id')==SCOPE['tab_id'] and close_ack.get('closed') is True
        once(folder/'CLOSE_TAB_ACK.json',dict(tab_id=close_ack.get('tab_id') if isinstance(close_ack,dict) else None,closed=closed,ack_returned=True))
        if not closed:raise ValueError('finish_original_tab_close_not_confirmed')
        # Do not call the live-manual guard after closure: the normal actor poll
        # is now responsible for seeing the closed tab and settling the command.
        actor._assert_thread();actor._check_owner()
        return once(folder/'RESULT.json',dict(schema='original_manual_session_finish_result/v1',claim=claim,status='waiting_natural_manual_settlement',
            state_saved=True,tab_close_acknowledged=True,tab_id=SCOPE['tab_id'],save_state_dispatches=1,close_tab_dispatches=1,
            manual_completed_by_helper=False,account_pause_changed=False,recovery_requested=False,automatic_replay_allowed=False))
    except Exception as error:
        first=str(error).splitlines()[0] if str(error) else ''
        return once(folder/'UNKNOWN.json',dict(schema='original_manual_session_finish_unknown/v1',claim=claim,error_type=type(error).__name__,
            safe_error=re.sub(r'https?://\S+','<url>',first)[:500],state_saved_acknowledged=saved,tab_close_acknowledged=closed,
            save_state_dispatches=saves,close_tab_dispatches=closes,manual_completed_by_helper=False,account_pause_changed=False,
            recovery_requested=False,automatic_replay_allowed=False))
