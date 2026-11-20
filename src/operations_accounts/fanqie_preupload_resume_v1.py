"""One named successor after a proved, known failure before backfill upload.

The original outbox/command/authorization/events remain unchanged. A new broker
record is the append-only successor. Unknown or externally started work never
obtains another slot.
"""
import hashlib
import json
from pathlib import Path

from .browser_control import BrowserControlRejected, _json
from src.services.fanqie_backfill_workflow import digest
from src.services.fanqie_promotion_ledger import TRANSITIONS

ROOT=Path(__file__).resolve().parents[2]
SCHEMA='fanqie_known_preupload_resume/v1'
CAUSE='fanqie_backfill_preupload_readonly_cause/v1'
REASON='existing_backfill_requires_reconciliation'


def need(ok,code):
    if not ok:raise BrowserControlRejected(code,'回填上传前后继依据不匹配；原任务、授权和提交记录保留。')


def reference(path):
    path=Path(path).resolve();need(path.is_relative_to(ROOT) and path.is_file(),'preupload_project_file_required')
    with path.open('rb') as source:sha=hashlib.file_digest(source,'sha256').hexdigest()
    return dict(path=str(path),sha256=sha)


def read(ref):
    need(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,'preupload_evidence_changed')
    path=Path(ref['path']);need(path.is_relative_to(ROOT/'data') and path.stat().st_size<=2*1024*1024,'preupload_project_evidence_required')
    value=json.loads(path.read_text(encoding='utf8'));need(isinstance(value,dict),'preupload_evidence_object_required')
    return value


def _state(ledger,bid):
    with ledger._db() as db:
        row=ledger._row(db,bid)
        binding=dict(db.execute('SELECT * FROM fanqie_bindings WHERE binding_uuid=?',(bid,)).fetchone())
        outbox=db.execute('SELECT * FROM fanqie_dispatch_outbox WHERE binding_uuid=?',(bid,)).fetchone()
        events=[dict(e) for e in db.execute("SELECT * FROM fanqie_operation_events WHERE event_type='backfill_v2' AND json_extract(payload_json,'$.binding_uuid')=? ORDER BY id",(bid,))]
    need(outbox is not None,'preupload_original_outbox_required')
    return dict(row=row,binding=binding,outbox=dict(outbox),events=events)


def _initial(state):
    row=state['row'];events=state['events']
    need(row['status']=='ready' and row['revision']==1 and row['attempt_count']==0 and row['batch_id'] is None
        and row['authorization_json'] and len(events)==2
        and [(e['from_status'],e['to_status']) for e in events]==[(None,'prepared'),('prepared','ready')],
        'preupload_original_not_unstarted_ready')


def _original(store,state,cid):
    old=store.get(cid);box=state['outbox'];row=state['row']
    need(old and old['kind']=='fanqie_backfill' and old['state']=='failed'
        and (old.get('result') or {}).get('reason')==REASON
        and box['command_id']==cid and old['idempotency_key']==box['dispatch_key']=='fanqie-backfill:'+row['business_key']
        and old['account_id']==box['account_id'] and old['binding_version']==box['binding_version']
        and old['payload']==json.loads(box['payload_json'])==dict(binding_uuid=row['binding_uuid'],manifest_sha256=row['manifest_sha']),
        'known_failed_preupload_command_required')
    return old


def _no_other_live(store,account,current_id=None):
    with store._db() as db:
        rows=db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown')",(account,)).fetchall()
    need(all(r['command_id']==current_id for r in rows),'preupload_other_command_unresolved')


def _evidence(authority_ref,causal_ref,fix_ref,state,old):
    authority,cause,fix=read(authority_ref),read(causal_ref),read(fix_ref)
    contract=json.loads(state['row']['contract_json']);manifest=json.loads(state['row']['manifest_json'])
    need(authority.get('schema')=='fanqie_production_trial_user_authorization/v1' and authority.get('user_statement')
        and authority.get('authorized_target',{}).get('media')==contract['media']
        and authority['authorized_target'].get('douyin_account_key')==contract['douyin_account_key']
        and str(authority['authorized_target'].get('book_id'))==str(manifest['binding']['book_id']),
        'preupload_original_parent_authority_required')
    need(reference(contract['media']['path'])==contract['media'],'preupload_original_media_changed')
    need(cause.get('schema')==CAUSE and cause.get('classification')=='known_pre_upload_local_guard_failure; not uncertain external upload/submit'
        and cause.get('binding',{}).get('binding_uuid')==state['row']['binding_uuid']
        and cause.get('binding',{}).get('status')=='ready' and cause['binding'].get('attempt_count')==0
        and cause.get('contract')=={k:state['row'][k] for k in ('business_key','manifest_sha','revision','batch_id')}
        and cause.get('outbox',{}).get('command_id')==old['command_id']
        and cause.get('actual_native_row',{}).get('published_links')==[],
        'preupload_exact_causal_proof_required')
    for ref in cause.get('artifacts',{}).values():need(reference(ref['path'])==ref,'preupload_causal_artifact_changed')
    need(cause.get('artifacts'),'preupload_causal_artifacts_required')
    need(fix.get('schema')=='fanqie_fill_status_fix_acceptance/v1' and fix.get('accepted') is True
        and isinstance(fix.get('sources'),list) and fix['sources'] and fix.get('tests'),
        'preupload_reviewed_status_fix_required')
    for ref in fix['sources']+fix['tests']:need(reference(ref['path'])==ref,'preupload_status_fix_changed')


def _key(state,old):
    baseline=digest(dict(binding=state,original=old))
    return 'preupload-resume:'+state['row']['business_key']+':'+old['command_id']+':'+baseline


def _payload(plan,ref):
    row=plan['baseline']['row']
    return dict(binding_uuid=row['binding_uuid'],manifest_sha256=row['manifest_sha'],preupload_resume=ref)


def prepare(binding_uuid,previous_command_id,*,authority_ref,causal_ref,fix_acceptance_ref,output_directory,ledger,store):
    state=_state(ledger,binding_uuid);_initial(state);old=_original(store,state,previous_command_id)
    _no_other_live(store,old['account_id'])
    from src.services.fanqie_backfill_coordinator import BackfillCoordinator
    BackfillCoordinator(ledger,store.path,require_strict_contract=True).inspect(binding_uuid)
    _evidence(authority_ref,causal_ref,fix_acceptance_ref,state,old)
    plan=dict(schema=SCHEMA,baseline=state,original=old,ledger_path=str(ledger.path.resolve()),browser_db=str(store.path.resolve()),
        authority=authority_ref,causal_proof=causal_ref,fix_acceptance=fix_acceptance_ref,idempotency_key=_key(state,old),
        code=[reference(ROOT/'src/operations_accounts/fanqie_preupload_resume_v1.py'),reference(ROOT/'src/operations_accounts/fanqie_backfill_control.py')],
        max_named_successors=1,preserve_original_outbox=True,allow_unknown_replay=False)
    directory=Path(output_directory).resolve();need(directory.is_relative_to(ROOT/'data'),'preupload_project_directory_required')
    directory.mkdir(parents=True,exist_ok=True);path=directory/'PLAN.json';raw=(_json(plan)+'\n').encode()
    if path.exists():need(path.read_bytes()==raw,'existing_preupload_plan_preserved')
    else:
        with path.open('xb') as out:out.write(raw)
    return reference(path)


def _plan(ref,ledger,store):
    plan=read(ref)
    need(plan.get('schema')==SCHEMA and plan.get('max_named_successors')==1 and plan.get('preserve_original_outbox') is True
        and plan.get('allow_unknown_replay') is False and plan['ledger_path']==str(ledger.path.resolve())
        and plan['browser_db']==str(store.path.resolve()) and plan['idempotency_key']==_key(plan['baseline'],plan['original']),
        'preupload_plan_scope_changed')
    for source in plan['code']:need(reference(source['path'])==source,'preupload_resume_code_changed')
    _evidence(plan['authority'],plan['causal_proof'],plan['fix_acceptance'],plan['baseline'],plan['original'])
    need(store.get(plan['original']['command_id'])==plan['original'],'preupload_original_failed_command_changed')
    return plan


def enqueue(ref,*,ledger,store):
    plan=_plan(ref,ledger,store);row=plan['baseline']['row']
    with store._db() as db:
        existing=store._command(db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
            (plan['original']['account_id'],plan['idempotency_key'])).fetchone())
    if existing:
        need(existing['kind']=='fanqie_backfill' and existing['payload']==_payload(plan,ref),'preupload_successor_slot_already_used')
        return dict(command_id=existing['command_id'],state=existing['state'],reused=True)
    state=_state(ledger,row['binding_uuid']);_initial(state)
    need(state==plan['baseline'],'preupload_baseline_changed')
    try:_no_other_live(store,plan['original']['account_id'])
    except BrowserControlRejected:
        # A concurrent caller may have committed this exact same slot after
        # our first lookup. Returning its CID is not another dispatch.
        with store._db() as db:
            raced=store._command(db.execute('SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?',
                (plan['original']['account_id'],plan['idempotency_key'])).fetchone())
        if raced and raced['kind']=='fanqie_backfill' and raced['payload']==_payload(plan,ref):
            return dict(command_id=raced['command_id'],state=raced['state'],reused=True)
        raise
    command=store.submit(plan['original']['account_id'],plan['original']['binding_version'],'fanqie_backfill',
        plan['idempotency_key'],_payload(plan,ref),200)
    need(command['payload']==_payload(plan,ref),'preupload_successor_slot_already_used')
    return dict(command_id=command['command_id'],state=command['state'],reused=False)


def validate_managed_resume(ledger,store,command,contract):
    """Guard the immutable baseline and this one command's legal event suffix."""
    ref=command['payload'].get('preupload_resume');plan=_plan(ref,ledger,store)
    need(command['kind']=='fanqie_backfill' and command['idempotency_key']==plan['idempotency_key']
        and command['account_id']==plan['original']['account_id'] and command['binding_version']==plan['original']['binding_version']
        and command['payload']==_payload(plan,ref),'preupload_managed_command_changed')
    _no_other_live(store,command['account_id'],command['command_id'])
    current=_state(ledger,command['payload']['binding_uuid']);baseline=plan['baseline']
    immutable=lambda row:{k:v for k,v in row.items() if k not in ('revision','status','attempt_count','batch_id')}
    immutable_binding=lambda row:{k:v for k,v in row.items() if k not in ('status','attempt_count')}
    need(current['outbox']==baseline['outbox'] and immutable(current['row'])==immutable(baseline['row'])
        and immutable_binding(current['binding'])==immutable_binding(baseline['binding'])
        and json.loads(current['row']['contract_json'])==contract
        and current['events'][:len(baseline['events'])]==baseline['events'],'preupload_business_intent_changed')
    suffix=current['events'][len(baseline['events']):];state='ready';uploads=0
    for event in suffix:
        need(event['from_status']==state and event['to_status'] in TRANSITIONS.get(state,set()),'preupload_progress_lineage_changed')
        state=event['to_status'];uploads+=int(state=='upload_started')
        payload=json.loads(event['payload_json'])
        need(payload.get('binding_uuid')==command['payload']['binding_uuid'] and digest(payload)==event['audit_artifact_hash'],
             'preupload_progress_event_changed')
    need((not suffix or suffix[0]['to_status']=='upload_started' or (len(suffix)==1 and state=='confirmed')) and uploads<=1
        and current['row']['status']==state and current['row']['revision']==baseline['row']['revision']+len(suffix)
        and current['row']['attempt_count']==uploads,'preupload_progress_or_attempt_changed')
    if not suffix:_initial(current)
    return True
