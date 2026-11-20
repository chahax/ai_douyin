"""Explicit operator abandonment of one unknown publication as a business target.

No platform deletion, claim archival, publication retry, owner impersonation or
control recovery. External publication outcome remains unknown in the receipt.
"""
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .browser_control import BrowserControlRejected, _json
from . import publication_verification_recovery as core

ROOT = Path(__file__).resolve().parents[2]
AUTH = 'publication_abandonment_authority/v1'
PLAN = 'publication_abandonment_plan/v1'
ERROR = 'operator_abandoned_external_outcome_unknown'
RETAIN = ('retain_platform_work','retain_original_unknown','retain_submission_lock','retain_journal')
DENY = ('delete_platform_work','replay_original')


def _require(ok, code):
    if not ok:raise BrowserControlRejected(code, '明确弃用依据或原任务已变化，未处理；旧结果及提交证据保留。')


def _hash(value):return hashlib.sha256(_json(value).encode()).hexdigest()


def _path(value):
    path=Path(value).resolve()
    _require(path.is_relative_to(ROOT/'data'),'abandonment_project_evidence_required')
    return path


def reference(path):
    path=Path(path).resolve()
    _require(path.is_relative_to(ROOT) and path.is_file(),'abandonment_project_file_required')
    with path.open('rb') as handle:sha=hashlib.file_digest(handle,'sha256').hexdigest()
    return dict(path=str(path),sha256=sha)


def _read(ref):
    _require(isinstance(ref,dict) and set(ref)=={'path','sha256'} and reference(ref['path'])==ref,
             'abandonment_evidence_changed')
    raw=_path(ref['path']).read_bytes()
    _require(len(raw)<=2*1024*1024,'abandonment_evidence_too_large')
    value=json.loads(raw)
    _require(isinstance(value,dict),'abandonment_evidence_object_required')
    return value


def _authority(ref):
    value=_read(ref)
    _require(value.get('schema')==AUTH and value.get('decision_source')=='explicit_user_statement'
        and all(value.get(k) is True for k in RETAIN) and all(value.get(k) is False for k in DENY),
        'explicit_abandonment_authority_required')
    for key in ('user_statement','preceding_user_statement','original_command_id','replacement_command_id',
                'replacement_candidate_id','account_uuid','account_key','binding_version'):
        _require(isinstance(value.get(key),str) and 0<len(value[key].strip())<=4000,
                 'abandonment_exact_subject_required')
    _require(type(value.get('expected_prior_verification_count')) is int
        and 1<=value['expected_prior_verification_count']<=50,'abandonment_prior_count_required')
    _require(type(value.get('created_at')) in (float,int) and math.isfinite(value['created_at'])
        and value['created_at']>0,'abandonment_authority_time_required')
    reference(value['replacement_media']['path'])
    _require(reference(value['replacement_media']['path'])==value['replacement_media'],
             'replacement_media_changed')
    scope=_read(value['replacement_scope_authority'])
    _require(scope.get('user_statement')==value['preceding_user_statement']
        and scope.get('authorized_target',{}).get('media')==value['replacement_media']
        and scope.get('authorized_target',{}).get('douyin_account_key')==value['account_key'],
        'replacement_user_scope_mismatch')
    return value


def _services(store,runtime):
    from . import browser_control_runtime as managed
    return (store if store is not None else managed._store(),
            runtime if runtime is not None else managed._runtime())


def _context(value,runtime):
    from .browser_control_runtime import binding_version
    context=runtime.resolve(value['account_key'],require_healthy=False)
    _require(context.account_uuid==value['account_uuid'] and context.account_key==value['account_key']
        and binding_version(context)==value['binding_version'],'abandonment_current_binding_changed')
    return context


def _candidate(value,path,replacement):
    path=_path(path)
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        row=db.execute('SELECT * FROM fanqie_h3_candidates WHERE candidate_id=?',
                       (value['replacement_candidate_id'],)).fetchone()
    _require(row is not None,'replacement_candidate_missing')
    row=dict(row); frozen=json.loads(row['frozen_json'])
    _require(row['media_sha']==value['replacement_media']['sha256']
        and row['command_id']==value['replacement_command_id'] and frozen['media']==value['replacement_media']
        and frozen['account']=={k:value[k] for k in ('account_uuid','account_key','binding_version')},
        'replacement_candidate_subject_changed')
    prepared=json.loads(row['prepared_json'])
    _require(prepared.get('request')==replacement['payload'].get('request')
        and prepared.get('authorization')==replacement['payload'].get('authorization'),
        'replacement_prepared_publication_changed')
    _read(prepared['authorization'])
    return row


def _unentered_maintenance(db,row):
    _require(row['kind']=='maintenance' and row['state']=='queued'
        and row.get('owner_id') is None and row.get('generation') is None,
        'other_original_business_unresolved')
    present=lambda name:bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())
    has_current,has_events=present('browser_control_execution'),present('browser_control_execution_events')
    _require(has_current==has_events,'queued_maintenance_execution_ambiguous')
    current=None;events=[]
    if has_current:
        found=db.execute('SELECT * FROM browser_control_execution WHERE command_id=?',(row['command_id'],)).fetchone()
        current=dict(found) if found else None
        events=[dict(event) for event in db.execute('SELECT * FROM browser_control_execution_events WHERE command_id=? ORDER BY event_id',(row['command_id'],))]
        evidence=([current] if current else [])+[json.loads(event['evidence']) for event in events]
        _require(all(e.get('handler_entered') in (0,False) and e.get('phase')!='handler_entered'
            and e.get('request_sha')==row['request_sha'] for e in evidence),
            'queued_maintenance_handler_already_entered')
    return dict(command=row,execution=dict(tables_present=has_current,current=current,events=events))


def _snapshot(store,db,value,context):
    original=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
        (value['original_command_id'],)).fetchone())
    replacement=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
        (value['replacement_command_id'],)).fetchone())
    _require(original and original['kind']=='publish' and original['state']=='outcome_unknown'
        and original['account_id']==value['account_uuid'] and original['binding_version']==value['binding_version']
        and original['payload'].get('account_key')==value['account_key']
        and isinstance(original.get('result'),dict) and original['result'].get('status')=='submission_unknown'
        and not original['result'].get('post_id') and not original['result'].get('publish_url'),
        'original_unknown_publication_required')
    owner=dict(store._owner(db,original['account_id'],original['owner_id'],original['generation'],original['binding_version']))
    _require(replacement and replacement['kind']=='publish' and replacement['state']=='queued'
        and replacement['account_id']==original['account_id'] and replacement['binding_version']==original['binding_version']
        and replacement['command_id']!=original['command_id']
        and replacement['payload'].get('account_key')==value['account_key']
        and replacement['payload'].get('video_sha256')==value['replacement_media']['sha256']
        and Path(replacement['payload']['request']['video_path']).resolve()==Path(value['replacement_media']['path']).resolve()
        and replacement['payload']['video_sha256']!=original['payload']['video_sha256'],
        'exact_new_queued_publication_required')
    from .publication_autonomous_reconciliation import unresolved
    pending=unresolved(store,db,original['account_id'],('queued','running','paused','waiting_human','outcome_unknown'))
    allowed={original['command_id'],replacement['command_id']}
    _require(allowed.issubset({r['command_id'] for r in pending}),'original_or_replacement_not_pending')
    retained=[_unentered_maintenance(db,row) for row in sorted(pending,key=lambda r:r['command_id']) if row['command_id'] not in allowed]
    prior=core._attempts(store,db,original['command_id'])
    source=core._source(context,original)
    _require(len(prior)==value['expected_prior_verification_count']
        and all(r['state']=='failed' and r['account_id']==original['account_id']
            and r['binding_version']==original['binding_version'] and r['payload'].get('source')==source
            and r['payload'].get('original_snapshot_sha256')==core._digest(original) for r in prior),
        'all_original_verifications_must_be_known_failed')
    _require(max([original['updated_at']]+[r['updated_at'] for r in prior])<=value['created_at']<=store.clock()+5,
             'abandonment_decision_must_follow_original_reads')
    return dict(original=original,replacement=replacement,prior_verifications=prior,source=source,owner=owner,
                retained_queued_maintenance=retained)


def prepare(authority,*,output_directory,store=None,runtime=None,candidate_db=None):
    """Only read current state and freeze a new plan; no business writes."""
    value=_authority(authority); store,runtime=_services(store,runtime); context=_context(value,runtime)
    candidate_path=_path(candidate_db or ROOT/'data/fanqie_closed_loop_p0.db')
    with store._db() as db:
        db.execute('BEGIN')
        snapshot=_snapshot(store,db,value,context)
        candidate=_candidate(value,candidate_path,snapshot['replacement'])
    document=dict(schema=PLAN,authority=authority,authority_content=value,browser_db=str(store.path.resolve()),
        candidate_db=str(candidate_path),candidate=candidate,original_snapshot_sha256=_hash(snapshot['original']),
        **snapshot,code=[reference(ROOT/'src/operations_accounts/publication_abandonment_v1.py'),reference(ROOT/'src/operations_accounts/browser_control.py')],
        interpretation='Abandon only the old business target. Retain platform work, external outcome unknown and original submission evidence. No replay or deletion.')
    directory=_path(output_directory); directory.mkdir(parents=True,exist_ok=True)
    path=directory/'PLAN.json';raw=(_json(document)+'\n').encode()
    if path.exists():_require(path.read_bytes()==raw,'existing_abandonment_plan_preserved')
    else:
        with path.open('xb') as output:output.write(raw)
    return reference(path)


def execute(plan,*,store=None,runtime=None,requested_by):
    store,runtime=_services(store,runtime)
    return store.operator_abandon_unknown_publication(plan,requested_by=requested_by,runtime=runtime)


def apply(store,plan,*,requested_by,runtime):
    """Operator CAS delegate, not a browser actor transition or platform call."""
    _require(isinstance(requested_by,str) and bool(requested_by.strip()) and not requested_by.startswith('backend:'),
             'operator_identity_required')
    document=_read(plan);value=_authority(document['authority'])
    _require(document.get('schema')==PLAN and document.get('authority_content')==value
        and document.get('browser_db')==str(store.path.resolve()),'abandonment_plan_subject_changed')
    for ref in document['code']:_require(reference(ref['path'])==ref,'abandonment_code_changed')
    context=_context(value,runtime)
    with store._db(write=True) as db:
        row=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
                                     (value['original_command_id'],)).fetchone())
        if row and row['state']=='failed' and row['error_code']==ERROR:
            result=row.get('result') or {}
            _require(result.get('decision')==plan and result.get('before_snapshot')==document['original']
                and result.get('before_snapshot_sha256')==document['original_snapshot_sha256'],
                'existing_abandonment_receipt_changed')
            for ref in document['source'].values():_require(reference(ref['path'])==ref,'original_submission_evidence_changed')
            return row
        current=_snapshot(store,db,value,context)
        _require(_hash(current['original'])==document['original_snapshot_sha256']
            and current['original']==document['original'] and current['replacement']==document['replacement']
            and current['prior_verifications']==document['prior_verifications'] and current['source']==document['source']
            and current['retained_queued_maintenance']==document['retained_queued_maintenance']
            and all(current['owner'][k]==document['owner'][k] for k in ('account_id','binding_version','owner_id','generation')),
            'abandonment_snapshot_changed')
        _require(_candidate(value,document['candidate_db'],current['replacement'])==document['candidate'],'replacement_candidate_changed')
        result=dict(operator_abandoned_external_outcome_unknown=True,original_outcome_known=False,
            original_platform_work_deleted=False,original_publication_replayed=False,
            before_snapshot=current['original'],before_snapshot_sha256=document['original_snapshot_sha256'],
            original_unknown_result=current['original']['result'],original_source=current['source'],
            prior_verifications=current['prior_verifications'],decision=plan,authority=document['authority'],
            retained_queued_maintenance=current['retained_queued_maintenance'],
            superseded_by=value['replacement_command_id'],replacement_candidate_id=value['replacement_candidate_id'],
            requested_by=requested_by,abandoned_at=store.clock(),submission_lock_and_journal_retained=True)
        changed=db.execute("UPDATE browser_control_commands SET state='failed',error_code=?,result=?,updated_at=? WHERE command_id=? AND state='outcome_unknown'",
            (ERROR,_json(result),store.clock(),value['original_command_id'])).rowcount
        _require(changed==1,'abandonment_CAS_failed')
        return store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',
                                        (value['original_command_id'],)).fetchone())
