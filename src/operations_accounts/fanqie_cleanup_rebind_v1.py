"""Named cleanup/replacement actions under a new explicit user authorization.

Historical publication/application/backfill receipts and claims are read-only.
This module uses the existing dedicated Fanqie owner, never a second profile.
"""
import hashlib
import json
import time
from pathlib import Path

from .browser_control import BrowserCommandResult,BrowserControlRejected
from . import fanqie_new_publication_backfill_v1 as files
from src.services import fanqie_promotion_identity_v2 as native

ROOT=Path(__file__).resolve().parents[2]
KIND='fanqie_cleanup_rebind'
ACTIONS={'cleanup_aliases','inspect_cleanup_state','replacement_apply','bind_new_publication','inspect_replacement_editor'}
SOURCE_PATHS=tuple(ROOT/p for p in (
 'src/operations_accounts/fanqie_cleanup_rebind_v1.py','src/operations_accounts/fanqie_account_control.py',
 'src/operations_accounts/fanqie_managed_promotion_v1.py','scripts/run_fanqie_account.py',
 'src/platform_adapter/fanqie_cleanup_rebind_v1.py','src/services/fanqie_promotion_identity_v2.py',
 'src/platform_adapter/fanqie_filled_details_controls_v2.py','src/operations_accounts/fanqie_new_publication_backfill_v1.py'))


def need(ok,code):
    if not ok:raise BrowserControlRejected('cleanup_rebind_'+code,'清理重建的原身份或具名授权未通过：'+code)


def source_paths(action):
    extra=() if action in {'cleanup_aliases','inspect_cleanup_state'} else tuple(ROOT/p for p in (
        'src/platform_adapter/fanqie_replacement_forms_v1.py','src/platform_adapter/fanqie_exact_book_locator_v1.py',
        'src/platform_adapter/fanqie_new_post_backfill_v1.py','src/platform_adapter/fanqie_backfill_editor_inspection_v1.py'))
    return SOURCE_PATHS+extra


def validate_request(ref,*,accounts,env,binding,active_subject=None):
    value=files.read(ref);need(value.get('schema')=='fanqie_cleanup_rebind_request/v1' and value.get('action') in ACTIONS
        and value.get('draft_only') is False,'final_request_required')
    if value['action'] in {'inspect_cleanup_state','inspect_replacement_editor'}:need(value.get('read_only') is True,'explicit_read_only_scope_required')
    seal=files.read(value['source_seal']);need(seal.get('schema')=='fanqie_cleanup_rebind_source_seal/v1','source_seal_required')
    sources=seal.get('sources',[]);paths={Path(r['path']).resolve():r for r in sources}
    need(len(paths)==len(sources) and set(source_paths(value['action']))<=set(paths),'source_scope_changed')
    for path,reference in paths.items():need(files.reference(path)==reference,'source_changed')
    files.refs(value);auth=files.read(value['authority']);linked=accounts.check_association(env)
    need(auth.get('schema')=='explicit_platform_cleanup_rebind_authorization/v1' and str(auth.get('user_statement','')).strip()
        and auth.get('fanqie_resource_id')==env['resource_id'] and auth.get('account_uuid')==env['douyin_account_uuid']==linked['account_uuid']
        and linked['account_key']==auth.get('account_key') and linked['platform_identity_key']=='public_uid:'+str(auth.get('expected_public_uid'))
        and auth.get('old_unknowns_and_claims_unchanged') is True and auth.get('local_media_unchanged') is True
        and auth.get('models_and_media_calls_allowed') is False and auth.get('new_publication_allowed') is False,'new_cleanup_authority_required')
    need(binding and binding['status']=='active' and all(binding[k]==env[k]==value[k] for k in ('resource_id','binding_version','environment_key'))
        and value.get('platform_identity_key')==binding['platform_identity_key']==auth.get('fanqie_identity'),'original_environment_changed')
    need(isinstance(value.get('original_records'),list) and value['original_records'],'original_history_required')
    authority_dir=Path(value['authority']['path']).resolve().parent
    if value['action'] in {'cleanup_aliases','inspect_cleanup_state'}:
        from src.platform_adapter.fanqie_cleanup_rebind_v1 import target_from_row
        snapshot=native.validate_snapshot(files.read(value['native_snapshot']))  # Historical manifest, not current admission identity.
        need(all(snapshot[k]==value[k] for k in ('resource_id','binding_version','platform_identity_key')),'manifest_snapshot_scope_changed')
        targets=value.get('targets');need(value.get('delete_authorized') is (value['action']=='cleanup_aliases') and isinstance(targets,list) and 0<len(targets)<=20
            and len({json.dumps(t['native_identity'],sort_keys=True) for t in targets})==len(targets)
            and value.get('delete_claim_directory')==str(authority_dir/'DELETE_CLAIMS'),'exact_delete_targets_required')
        rows=[target_from_row(snapshot,r) for r in snapshot['rows'] if r.get('identity_status')=='verified' and r.get('native_record_id')]
        need(all(t in rows for t in targets),'native_manifest_target_changed')
        need(all((t['book_id']==auth['book_id'] and t['book_name']==auth['book_name'] and t['alias']==auth['preferred_recreated_alias'])
                 or t['alias_status'] in {'强制失效','已失效','审核不通过','已删除'} for t in targets),'delete_outside_authorized_scope')
        if value['action']=='cleanup_aliases' and value.get('known_preconfirm_failure') is not None:_known_preconfirm_failure(value,accounts,request_ref=ref,active_subject=active_subject)
    else:
        need(all(value.get(k)==auth[k] for k in ('book_id','book_name')) and value.get('alias')==auth['preferred_recreated_alias']
            and value.get('publish_type')=='AIGC' and value.get('promotion_path')=='别名推广','exact_replacement_target_required')
        from src.platform_adapter.fanqie_replacement_forms_v1 import validate_action_request
        validate_action_request(value,auth)
        if value.get('known_backfill_preparation_failure') is not None:
            _known_backfill_preparation_failure(value,accounts,request_ref=ref,active_subject=active_subject)
    return value


def _known_preconfirm_failure(request,accounts,*,request_ref=None,active_subject=None):
    """Only the evidenced original content-selector failure, with zero confirms."""
    ref=request['known_preconfirm_failure'];result=files.read(ref);old_request=files.read(result['request']);subject=result.get('subject',{})
    expected=dict(status='action_not_confirmed',error_type='CleanupBlocked',reason='native_confirmation_not_confirmed',automatic_retry=False)
    need(result.get('schema')=='fanqie_cleanup_rebind_command_result/v1' and result.get('broker_state')=='failed' and result.get('result')==expected
         and old_request.get('action')=='cleanup_aliases' and old_request.get('known_preconfirm_failure') is None,'known_preconfirm_failure_required')
    keys=('authority','resource_id','binding_version','environment_key','platform_identity_key','native_snapshot','targets','delete_authorized','delete_claim_directory','original_records')
    need(all(request.get(k)==old_request.get(k) for k in keys),'preconfirm_successor_scope_changed')
    folder=accounts.folder(subject['task_id']);need(Path(ref['path']).resolve()==folder/'CLEANUP_REBIND_RESULT.json','original_failure_directory_required')
    with accounts.connection() as db:row=db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(subject['task_id'],)).fetchone()
    need(row and row['state']=='failed' and row['kind']==KIND and row['account_id']==request['resource_id'] and row['binding_version']==request['binding_version']
         and json.loads(row['payload'])==dict(environment_key=request['environment_key'],request=result['request']),'original_terminal_failure_required')
    broker_result=json.loads(row['result']);need(broker_result.get('reason')==expected['reason'] and broker_result.get('result_evidence')==ref,'original_failed_receipt_changed')
    modal=files.read(files.reference(folder/'cleanup/01/DELETE_MODAL.json'))
    need(modal.get('title')=='删除别名' and modal.get('body')=='' and modal.get('eligible') is False and modal.get('expected_content') is False
         and modal.get('modal_count')==1,'original_content_selector_failure_required')
    need(not any(folder.rglob('DELETE_CONFIRM_INTENT.json')) and not any(folder.rglob('DELETE_PREFLIGHT.json'))
         and not any(folder.rglob('DELETE_UNKNOWN.json')),'prior_delete_effect_cannot_be_excluded')
    claims=list(Path(request['delete_claim_directory']).glob('*.json'))
    if claims:
        expected_subject=active_subject;expected_ref=request_ref
        if expected_subject is None:
            # A repeated public queue call may return the existing successor;
            # it cannot create a second execution or reinterpret an old claim.
            with accounts.connection() as db:current=db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
                (request['resource_id'],idempotency_key(request))).fetchone()
            need(current is not None and current['owner_id'] is not None,'prior_delete_effect_cannot_be_excluded')
            expected_subject={**{k:request[k] for k in ('resource_id','binding_version','environment_key','platform_identity_key')},
                'owner_id':current['owner_id'],'generation':current['generation'],'task_id':current['command_id']}
            expected_ref=json.loads(current['payload'])['request']
        need(expected_ref is not None and expected_subject.get('task_id')!=subject['task_id'],'prior_delete_effect_cannot_be_excluded')
        for path in claims:
            claimed=files.read(files.reference(path));preflight=files.read(claimed['preflight']);target=claimed.get('target')
            need(claimed.get('schema')=='fanqie_cleanup_delete_claim/v1' and claimed.get('subject')==expected_subject and claimed.get('request')==expected_ref
                 and target in request['targets'] and preflight.get('subject')==expected_subject and preflight.get('request')==expected_ref and preflight.get('target')==target
                 and Path(claimed['preflight']['path']).resolve().is_relative_to(accounts.folder(expected_subject['task_id']))
                 and path.name==hashlib.sha256(native.canonical(target['native_identity'])).hexdigest()+'.json','other_delete_claim_not_permitted')
    proof_path=Path(request['authority']['path']).resolve().parent/'known_preconfirm_fix/SOURCE_AND_FAILURE_BEFORE.json'
    proof=files.read(files.reference(proof_path));old_seal=files.read(old_request['source_seal'])
    original=next((r for r in old_seal['sources'] if Path(r['path']).resolve()==ROOT/'src/platform_adapter/fanqie_cleanup_rebind_v1.py'),None)
    need(original and original['sha256']=='1e5d42af662c486ea2edf6b949b6eca3d49a0e038cb37cda4fc1d6a09b5699b2'
         and proof.get('schema')=='fanqie_cleanup_preconfirm_fix_before/v1' and proof.get('command_id')==subject['task_id'],'original_preconfirm_source_required')
    copies=[r for r in proof['sources_and_evidence'] if r['original']==original]
    need(len(copies)==1 and files.reference(copies[0]['snapshot']['path'])==copies[0]['snapshot']
         and copies[0]['snapshot']['sha256']==original['sha256'],'original_source_snapshot_changed')


def idempotency_key(request):
    stable={k:request[k] for k in ('authority','resource_id','binding_version','platform_identity_key','action')}
    if request['action'] in {'cleanup_aliases','inspect_cleanup_state'}:stable['targets']=request['targets']
    else:stable.update({k:request[k] for k in ('book_id','book_name','alias')})
    if request['action']=='cleanup_aliases' and request.get('known_preconfirm_failure') is not None:stable['known_preconfirm_failure']=request['known_preconfirm_failure']
    if request['action']=='bind_new_publication' and request.get('known_backfill_preparation_failure') is not None:stable['known_backfill_preparation_failure']=request['known_backfill_preparation_failure']
    return 'fanqie-cleanup-rebind:'+hashlib.sha256(native.canonical(stable)).hexdigest()


def _known_backfill_preparation_failure(request,accounts,*,request_ref,active_subject=None):
    """Only the original proven zero-row preparation failure, never unknown IO."""
    ref=request['known_backfill_preparation_failure'];result=files.read(ref);old=files.read(result['request']);subject=result['subject']
    expected=dict(status='action_not_confirmed',error_type='NewPostBackfillNotConfirmed',reason='new_form_identity_unconfirmed',automatic_retry=False)
    need(request['action']=='bind_new_publication' and result.get('schema')=='fanqie_cleanup_rebind_command_result/v1'
         and result.get('broker_state')=='failed' and result.get('result')==expected and old.get('action')=='bind_new_publication'
         and old.get('known_backfill_preparation_failure') is None,'known_backfill_preparation_failure_required')
    keys=('authority','resource_id','binding_version','environment_key','platform_identity_key','book_id','book_name','alias','publish_type','promotion_path',
          'replaces_native_identity','new_native_identity','replacement_snapshot','replacement_snapshot_version','replacement_identity_observation',
          'verified_publication','new_publication','cleanup_reconciliation','cleanup_state_result','cleanup_state_receipt','original_records','backfill_limit')
    need(all(request.get(k)==old.get(k) for k in keys),'preparation_successor_scope_changed')
    folder=accounts.folder(subject['task_id']);need(Path(ref['path']).resolve()==folder/'CLEANUP_REBIND_RESULT.json','original_preparation_directory_required')
    with accounts.connection() as db:row=db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(subject['task_id'],)).fetchone()
    need(row and row['state']=='failed' and row['kind']==KIND and row['account_id']==request['resource_id'] and row['binding_version']==request['binding_version']
         and json.loads(row['payload'])==dict(environment_key=request['environment_key'],request=result['request']),'original_preparation_terminal_required')
    broker=json.loads(row['result']);need(broker.get('reason')==expected['reason'] and broker.get('result_evidence')==ref,'original_preparation_result_changed')
    review=files.read(request['preparation_failure_review']);blank_ref=files.reference(folder/'replacement/BLANK_FORM.json');blank=files.read(blank_ref)
    need(review.get('schema')=='fanqie_replacement_known_preparation_failure_independent_review/v1' and review.get('result')==ref
         and review.get('request')==result['request'] and review.get('subject')==subject and review.get('blank_form')==blank_ref
         and review.get('classification')=='known_preparation_failure_not_unknown_submission'
         and files.read(review['result_binding'])==dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=result['request'],subject=subject,result=ref)
         and blank.get('scope_count')==1 and blank.get('input_count')==0 and blank.get('date') is None and blank.get('link') is None
         and blank.get('identity')==dict(book_name=request['book_name'],alias=request['alias'],aigc=True) and blank.get('submit',{}).get('enabled') is False,
         'original_zero_row_preparation_required')
    excluded=('EMPTY_OTHER_DRAFT.json','EMPTY_OTHER_DRAFT_REMOVE_INTENT.json','TWO_INPUT_BLANK_FORM.json','BACKFILL_PREFLIGHT.json','BACKFILL_SUBMIT_INTENT.json','BACKFILL_UNKNOWN.json')
    need(not any((folder/'replacement'/p).exists() for p in excluded),'original_preparation_effect_not_excluded')
    archive=files.read(request['preparation_source_before']);old_sources=files.read(old['source_seal'])['sources'];copies=archive.get('sources',[])
    need(archive.get('schema')=='fanqie_first_empty_editor_source_before/v1' and len(copies)==len(old_sources)
         and {json.dumps(c.get('original'),sort_keys=True) for c in copies}=={json.dumps(r,sort_keys=True) for r in old_sources}
         and all(c.get('original') in old_sources and files.reference(c['snapshot']['path'])==c['snapshot'] and c['snapshot']['sha256']==c['original']['sha256'] for c in copies)
         and any(Path(c['original']['path']).resolve()==ROOT/'src/platform_adapter/fanqie_replacement_forms_v1.py'
             and c['original']['sha256']=='c6edbd164088d0b53fe0d8f6a2ef8c5e6af38c357bee56fde0d23e707e5aa55c' for c in copies),
         'original_preparation_sources_required')
    claim_path=Path(request['authority']['path']).resolve().parent/'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json'
    if claim_path.exists():
        current_subject=active_subject;current_ref=request_ref
        if current_subject is None:
            with accounts.connection() as db:current=db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',(request['resource_id'],idempotency_key(request))).fetchone()
            need(current is not None and current['owner_id'] is not None,'other_preparation_submission_claim')
            current_subject={**{k:request[k] for k in native.SCOPE},'owner_id':current['owner_id'],'generation':current['generation'],'task_id':current['command_id']}
            current_ref=json.loads(current['payload'])['request']
        claimed=files.read(files.reference(claim_path));preflight=files.read(claimed['preflight'])
        need(current_subject['task_id']!=subject['task_id'] and claimed.get('schema')=='fanqie_replacement_backfill_claim/v1'
             and claimed.get('request')==current_ref and claimed.get('subject')==current_subject
             and preflight.get('schema')=='fanqie_replacement_backfill_preflight/v1' and preflight.get('request')==current_ref and preflight.get('subject')==current_subject
             and claimed.get('target')==preflight.get('target')=={k:request[k] for k in ('book_id','book_name','alias','publish_type')}
             and preflight.get('new_publication')==request['new_publication'] and preflight.get('native_identity')==request['new_native_identity']
             and Path(claimed['preflight']['path']).resolve().is_relative_to(accounts.folder(current_subject['task_id'])),'other_preparation_submission_claim')


def require_unclaimed(request):
    """Queue-time only; an active command retains its own claims through readback."""
    if request['action'] in {'inspect_cleanup_state','inspect_replacement_editor'}:return
    if request['action']=='cleanup_aliases':
        for target in request['targets']:
            scope=hashlib.sha256(native.canonical(target['native_identity'])).hexdigest()
            need(not (Path(request['delete_claim_directory'])/(scope+'.json')).exists(),'original_delete_claim_preserved')
    else:
        name='REPLACEMENT_APPLY_CLAIM.json' if request['action']=='replacement_apply' else 'REPLACEMENT_BACKFILL_SUBMIT_CLAIM.json'
        need(not (Path(request['authority']['path']).resolve().parent/name).exists(),'original_replacement_claim_preserved')


def execute(ctx,*,accounts,env,page_provider,identity_guard):
    from .fanqie_managed_promotion_v1 import LIST_URL,capture_native_snapshot,_hard_worker_failure
    from src.platform_adapter.fanqie_cleanup_rebind_v1 import run_cleanup
    payload=ctx.command['payload'];need(set(payload)=={'environment_key','request'} and payload['environment_key']==env['environment_key'],'payload_invalid')
    ref=payload['request'];request=validate_request(ref,accounts=accounts,env=env,binding=accounts.bindings().get(env['resource_id']))
    subject=files.subject_for(ctx,request);folder=accounts.folder(ctx.task_id);folder.mkdir(parents=True,exist_ok=True)
    marker=folder/'CLEANUP_REBIND_ACTION.json'
    need(not marker.exists(),'action_already_executed');files.once(marker,dict(schema='fanqie_cleanup_rebind_action/v1',request=ref,subject=subject,automatic_replay_allowed=False))
    def guard():
        identity_guard();need(accounts.get(env['resource_id'])==env,'environment_changed')
        need(validate_request(ref,accounts=accounts,env=env,binding=accounts.bindings().get(env['resource_id']),active_subject=subject)==request,'request_changed')
    page=None
    try:
        managed=page_provider(ctx,LIST_URL);page=managed.page
        def fresh(stage):
            return capture_native_snapshot(managed,env=env,managed_subject=subject,identity=lambda:identity_guard(),guard=guard,evidence_directory=folder/('native_'+stage))
        def claim(preflight_ref):
            guard();proof=files.read(preflight_ref);files.refs(proof)
            need(proof.get('request')==ref and proof.get('subject')==subject and 0<=time.time()-proof['observed_at']<=45
                and Path(preflight_ref['path']).resolve().is_relative_to(folder),'fresh_original_preflight_required')
            if request['action']=='cleanup_aliases':
                from src.platform_adapter.fanqie_cleanup_rebind_v1 import checked_snapshot,native_matches
                target=proof['target'];need(target in request['targets'] and proof.get('schema')=='fanqie_cleanup_delete_preflight/v1'
                    and proof.get('delete_limit')==1 and all(proof.get('boundary',{}).get(k) is True for k in ('eligible','same_node','center_hit'))
                    and proof.get('boundary',{}).get('modal',{}).get('eligible') is True,'native_delete_preflight_required')
                need(native_matches(checked_snapshot(proof['native_snapshot'],request),target),'fresh_delete_native_identity_required')
                modal=files.read(proof['modal']);need(modal.get('eligible') is True and modal.get('title')=='删除别名' and modal.get('expected_content') is True,'exact_delete_modal_required')
                scope=hashlib.sha256(native.canonical(target['native_identity'])).hexdigest()
                path=Path(request['delete_claim_directory'])/(scope+'.json')
                schema='fanqie_cleanup_delete_claim/v1'
            else:
                from src.platform_adapter.fanqie_replacement_forms_v1 import validate_preflight
                path,schema=validate_preflight(request,proof)
            return files.once(path,dict(schema=schema,request=ref,subject=subject,preflight=preflight_ref,target=proof['target'],at_epoch=time.time(),automatic_replay_allowed=False))
        if request['action']=='inspect_cleanup_state':
            from src.platform_adapter.fanqie_cleanup_rebind_v1 import inspect_cleanup_state
            value=inspect_cleanup_state(page,request=request,request_ref=ref,subject=subject,guard=guard,evidence_directory=folder/'inspection',refresh_native_snapshot=fresh)
        elif request['action']=='cleanup_aliases':
            value=run_cleanup(page,request=request,request_ref=ref,subject=subject,guard=guard,evidence_directory=folder/'cleanup',refresh_native_snapshot=fresh,claim_delete=claim)
        else:
            from src.platform_adapter.fanqie_replacement_forms_v1 import run_action
            value=run_action(managed,request=request,request_ref=ref,subject=subject,guard=guard,evidence_directory=folder/'replacement',refresh_native_snapshot=fresh,
                navigate=lambda url:page_provider(ctx,url),claim_submission=claim)
        guard();files.refs(value)
        unknown=value.get('status') in {'deletion_unknown','application_unknown','submission_unknown'}
        state='outcome_unknown' if _hard_worker_failure(None,page) else 'succeeded'
        result=dict(status=value['status'],business_confirmed=not unknown,native_result=value,automatic_retry=False,requires_read_only_reconciliation=unknown)
    except Exception as error:
        state='outcome_unknown' if isinstance(error,BrowserControlRejected) or _hard_worker_failure(error,page) else 'failed'
        result=dict(status='action_not_confirmed',error_type=type(error).__name__,automatic_retry=False)
        if hasattr(error,'code'):result['reason']=error.code
    result_ref=files.once(folder/'CLEANUP_REBIND_RESULT.json',dict(schema='fanqie_cleanup_rebind_command_result/v1',request=ref,subject=subject,broker_state=state,result=result))
    files.once(folder/'CLEANUP_REBIND_RESULT_BINDING.json',dict(schema='fanqie_cleanup_rebind_result_binding/v1',request=ref,subject=subject,result=result_ref))
    return BrowserCommandResult(state,dict(result,result_evidence=result_ref))
