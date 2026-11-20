"""One registered, non-uploading reconciliation of the original uncertain publication."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import os
import time

from . import publication_two_run_authorization as quota
from .browser_control import BrowserControlRejected, BrowserControlStore, _json
from .publication_bounded_retry_authorization import _read_command

REGISTRY = quota.ROOT / 'data/account_browser_control_authorizations/publication_reconciliation_20261019.ref.json'
AUTH_SHA256 = '3933466384fa7d4a2a317d5d506acc7a373de19952202e4b17d8a32fa4227a6c'
SCHEMA = 'publication_reconciliation_repair_authorization/20261019/v1'
KEY = 'user-publication-reconciliation-20261019:original-1582'
TABLE = 'browser_control_reconciliation_handoffs'


def _reject():
    raise BrowserControlRejected('publication_reconciliation_invalid', '原未知发布核查授权、身份或原生证据不匹配，未放行。')


def _load(reference):
    return quota._load_reference(reference)[0]


def _ref(path):
    path, _, sha = quota._read(path)
    return {'path':str(path),'sha256':sha}


def validate_reconciliation_authorization(reference, *, require_registered=True):
    if not isinstance(reference,dict) or reference.get('sha256') != AUTH_SHA256:
        _reject()
    auth=_load(reference)
    if require_registered:
        try: registered=json.loads(REGISTRY.read_bytes())
        except (OSError,ValueError): _reject()
        if registered != reference: _reject()
    if (auth.get('schema') != SCHEMA or auth.get('decision_source') != 'explicit_user_statement'
            or not auth.get('user_statement') or not auth.get('preceding_user_confirmation')
            or auth.get('utc_day') != datetime.now(timezone.utc).date().isoformat()
            or auth.get('baseline_daily_runs') != 33 or auth.get('max_daily_runs') != 34
            or auth.get('additional_reconciliation_runs') != 1 or auth.get('active_control_revision') != 42
            or auth.get('new_upload_authorized') is not False or auth.get('new_publish_click_authorized') is not False
            or auth.get('comment_retry_authorized') is not False
            or any(auth.get(k) is not True for k in ('preserve_original_unknown_snapshot','retain_submission_lock',
                'visible_managed_window_authorized','verify_exact_work_before_comment','comment_authorization_is_original_prepared',
                'stop_on_human_required_or_unknown','deployment_authorized'))):
        _reject()
    before=_load(auth['original_command'])
    if (before != _read_command(auth['original_command_id']) or before.get('task_id') != auth['original_command_id']
            or before.get('command_id') != auth['original_command_id'] or before.get('kind') != 'publish'
            or before.get('state') != 'outcome_unknown' or before.get('account_id') != auth['account_uuid']
            or before.get('owner_id') != auth['original_owner_id'] or before.get('generation') != auth['original_generation']
            or before.get('result',{}).get('status') != 'submission_unknown'):
        _reject()
    prepared=_load(auth['prepared'])
    value={'account_uuid':auth['account_uuid'],'account_key':auth['account_key'],'prepared':auth['prepared'],'video':prepared['video']}
    quota.validate_publication_payload(value,before['payload'])
    if (prepared.get('decision_source') != 'explicit_user_statement' or prepared.get('full_film_accepted_for_publication') is not True
            or prepared.get('ai_generated') is not True or prepared.get('fictional_story') is not True
            or before['payload'].get('account_uuid') != auth['account_uuid'] or before['payload'].get('account_key') != auth['account_key']):
        _reject()
    # This checks immutable grant identity, not the old no-submission-lock retry gate.
    old_ref=before['payload']['quota_authorization']; old=_load(old_ref)
    if (json.loads(quota.REGISTRY_V8.read_bytes()) != old_ref or old.get('schema') != quota.SCHEMA_V8
            or old.get('max_daily_runs') != 33 or old.get('prepared') != auth['prepared'] or old.get('video') != prepared['video']
            or old.get('account_uuid') != auth['account_uuid'] or old.get('account_key') != auth['account_key']
            or old.get('idempotency_keys',{}).get('publish') != before['idempotency_key']):
        _reject()
    journal_path, raw, _=quota._read(auth['original_journal']['path'],auth['original_journal']['sha256'])
    rows=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    lock=_load(auth['original_submission_lock'])
    if (not rows or rows[0].get('stage') != 'prepared' or rows[-1].get('stage') != 'submission_unknown'
            or sum(row.get('stage')=='submission_started' for row in rows) != 1
            or lock.get('status') != 'submission_started' or lock.get('journal') != str(journal_path)):
        _reject()
    first=rows[0]; runs=(quota.ROOT/'data/publish_runs').resolve()
    key=hashlib.sha256(json.dumps({'platform_identity_key':first.get('platform_identity_key'),
        'video_sha256':prepared['video']['sha256']},sort_keys=True).encode()).hexdigest()
    if (not first.get('platform_identity_key') or journal_path.parent != runs or not journal_path.name.startswith(key+'.')
            or Path(auth['original_submission_lock']['path']).resolve() != runs/(key+'.submitted.json')
            or first.get('account_uuid') != auth['account_uuid'] or first.get('account') != auth['account_key']
            or first.get('video_sha256') != prepared['video']['sha256'] or first.get('video_path') != prepared['video']['path']
            or first.get('title') != prepared['title']
            or not before['created_at'] <= datetime.fromisoformat(first['at_bjt']).timestamp() <= before['updated_at']):
        _reject()
    return {'authorization':auth,'original_command':before,'prepared':prepared,'journal_rows':rows,'original_submission_lock':lock}


def register_reconciliation_authorization(path,sha256):
    reference={'path':str(Path(path).resolve()),'sha256':sha256}
    validate_reconciliation_authorization(reference,require_registered=False)
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    try:
        with REGISTRY.open('x',encoding='utf-8') as handle:
            handle.write(_json(reference)); handle.flush(); os.fsync(handle.fileno())
    except FileExistsError:
        if json.loads(REGISTRY.read_bytes()) != reference: _reject()
    return reference


def registered_reference():
    if not REGISTRY.exists(): return None
    try: return json.loads(REGISTRY.read_bytes())
    except (OSError,ValueError): _reject()


def get_verified_reconciliation_inputs(payload):
    if (not isinstance(payload,dict) or set(payload) != {'account_uuid','account_key','original_command_id','reconciliation_authorization'}):
        _reject()
    inputs=validate_reconciliation_authorization(payload['reconciliation_authorization']); auth=inputs['authorization']
    if any(payload[k] != auth[k] for k in ('account_uuid','account_key','original_command_id')): _reject()
    return inputs


def daily_limit(ctx,operation,default,account_uuid,control):
    if ctx is None or ctx.command['kind'] != 'publication_reconcile' or operation != 'publication-reconciliation' or default != 20:
        return default
    inputs=get_verified_reconciliation_inputs(ctx.command['payload']); auth=inputs['authorization']
    if (ctx.account_id != auth['account_uuid'] or account_uuid != auth['account_uuid'] or ctx.command['idempotency_key'] != KEY
            or not control or control.get('state') != 'active' or control.get('revision') != 42
            or control.get('account_uuid') != auth['account_uuid'] or control.get('account_key') != auth['account_key']):
        _reject()
    return 34


def handoff_row(db,account_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone(): return None
    row=db.execute(f'SELECT * FROM {TABLE} WHERE account_id=?',(account_id,)).fetchone()
    return dict(row) if row else None


def handoff(store,*,owner_id,generation,authorization,expected_snapshot_sha256,retirement_evidence,connection):
    db=connection
    if not db.in_transaction or Path(next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')).resolve() != store.path:
        _reject()
    inputs=validate_reconciliation_authorization(authorization); auth=inputs['authorization']; before=inputs['original_command']
    if (owner_id != auth['original_owner_id'] or generation != auth['original_generation']
            or hashlib.sha256(_json(before).encode()).hexdigest() != expected_snapshot_sha256): _reject()
    owner=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(auth['account_uuid'],)).fetchone()
    if not owner or owner['owner_id'] != owner_id or owner['generation'] != generation or owner['state'] != 'active' or owner['binding_version'] != before['binding_version']: _reject()
    current=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(auth['original_command_id'],)).fetchone())
    others=db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','outcome_unknown','waiting_human')",(auth['account_uuid'],)).fetchall()
    if current != before or [r[0] for r in others] != [auth['original_command_id']]: _reject()
    dead=_load(retirement_evidence)
    if (dead.get('schema') != 'publication_reconciliation_retirement/20261019/v1'
            or any(dead.get(k) != auth[k] for k in ('account_uuid','original_command_id'))
            or dead.get('owner_id') != owner_id or dead.get('generation') != generation
            or dead.get('original_backend_pid') != auth['original_backend_pid']
            or dead.get('original_backend_create_time') != auth['original_backend_create_time']
            or dead.get('parent_exited') is not True or dead.get('descendants_exited') is not True
            or dead.get('alive_child_ids') != [] or not isinstance(dead.get('observed_children'),list)
            or set(dead.get('gone_child_ids',[])) != {c['pid'] for c in dead['observed_children']}
            or not before['updated_at'] <= dead.get('finished_at',0) <= store.clock()+5
            or store.clock()-dead['finished_at'] > 300): _reject()
    import psutil
    # An exited process's numeric PID can already belong to an unrelated process.
    identities=[(auth['original_backend_pid'],auth['original_backend_create_time'])]+[(c['pid'],c['create_time']) for c in dead['observed_children']]
    recorded=dead.get('pid_identity_checks')
    if not isinstance(recorded,list) or len(recorded)!=len(identities): _reject()
    checks=[]
    for (pid,created), prior in zip(identities,recorded):
        if (not isinstance(prior,dict) or prior.get('pid')!=pid or prior.get('expected_create_time')!=created
                or not isinstance(created,(int,float)) or not math.isfinite(created)
                or prior.get('status') not in {'not_present','pid_reused'}): _reject()
        expected_keys={'pid','expected_create_time','status'}
        if prior['status']=='pid_reused':
            expected_keys.add('current_create_time')
            current=prior.get('current_create_time')
            if (not isinstance(current,(int,float)) or not math.isfinite(current)
                    or abs(current-created)<=1e-6): _reject()
        if set(prior)!=expected_keys: _reject()
        try:
            current=psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            checks.append({'pid':pid,'expected_create_time':created,'status':'not_present'})
            continue
        except (psutil.Error,OSError,ValueError):
            _reject()
        if (not isinstance(current,(int,float)) or not math.isfinite(current) or abs(current-created)<=1e-6
                or prior['status']!='pid_reused' or abs(prior['current_create_time']-current)>1e-6): _reject()
        checks.append({'pid':pid,'expected_create_time':created,'status':'pid_reused','current_create_time':current})
    db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE}(account_id TEXT PRIMARY KEY,authorization TEXT NOT NULL,
        original_command_id TEXT NOT NULL,original_owner_id TEXT NOT NULL,original_generation INTEGER NOT NULL,
        binding_version TEXT NOT NULL,retirement_evidence TEXT NOT NULL,released_at REAL NOT NULL,
        new_owner_id TEXT,new_generation INTEGER,resolution TEXT)''')
    if handoff_row(db,auth['account_uuid']): _reject()
    audit={'authorization':authorization,'retirement_evidence':retirement_evidence,'original_snapshot_sha256':expected_snapshot_sha256,
        'original_snapshot':before,'submitted_lock_retained':auth['original_submission_lock'],'pid_identity_checks':checks}
    db.execute(f'INSERT INTO {TABLE}(account_id,authorization,original_command_id,original_owner_id,original_generation,binding_version,retirement_evidence,released_at) VALUES(?,?,?,?,?,?,?,?)',
        (auth['account_uuid'],_json(authorization),auth['original_command_id'],owner_id,generation,before['binding_version'],_json(audit),store.clock()))
    db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",(store.clock(),auth['account_uuid']))
    return audit


def acquire_owner(store,account_id,binding_version,owner_id,authorization):
    inputs=validate_reconciliation_authorization(authorization); auth=inputs['authorization']
    with store._db(write=True) as db:
        row=handoff_row(db,account_id); old=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone()
        if (not row or json.loads(row['authorization']) != authorization or row['new_owner_id'] is not None
                or not old or old['state'] != 'released' or old['owner_id'] != auth['original_owner_id'] or old['generation'] != auth['original_generation']
                or account_id != auth['account_uuid'] or row['binding_version'] != binding_version or old['binding_version'] != binding_version): _reject()
        unknown=db.execute("SELECT command_id FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",(account_id,)).fetchall()
        if [r[0] for r in unknown] != [auth['original_command_id']]: _reject()
        generation=old['generation']+1; now=store.clock()
        db.execute("UPDATE browser_control_owners SET owner_id=?,generation=?,state='active',heartbeat=?,updated_at=? WHERE account_id=?",(owner_id,generation,now,now,account_id))
        db.execute(f'UPDATE {TABLE} SET new_owner_id=?,new_generation=? WHERE account_id=?',(owner_id,generation,account_id))
        return dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone())


def claim(store,db,account_id,binding_version,owner_id,generation):
    row=handoff_row(db,account_id)
    if not row or row['new_owner_id'] != owner_id or row['new_generation'] != generation: return None
    if row['resolution'] is not None: return None
    ref=json.loads(row['authorization']); inputs=validate_reconciliation_authorization(ref)
    unresolved=db.execute("SELECT command_id,state FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",(account_id,)).fetchall()
    if len(unresolved)!=1 or unresolved[0]['command_id'] != row['original_command_id'] or unresolved[0]['state']!='outcome_unknown': return None
    cmd=db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND kind='publication_reconcile' AND idempotency_key=? AND state='queued'",(account_id,KEY)).fetchone()
    if not cmd: return None
    command=store._command(cmd); get_verified_reconciliation_inputs(command['payload'])
    if command['binding_version'] != binding_version or command['payload']['reconciliation_authorization'] != ref: _reject()
    db.execute("UPDATE browser_control_commands SET state='running',owner_id=?,generation=?,updated_at=? WHERE command_id=?",(owner_id,generation,store.clock(),cmd['command_id']))
    return store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(cmd['command_id'],)).fetchone())


def resolve(store,reconciliation_id,owner_id,generation,result):
    from src.platform_adapter.publish_verification import video_id
    with store._db(write=True) as db:
        command=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(reconciliation_id,)).fetchone())
        if not command or command['kind']!='publication_reconcile' or command['state']!='running' or command['owner_id']!=owner_id or command['generation']!=generation: _reject()
        inputs=get_verified_reconciliation_inputs(command['payload']); auth=inputs['authorization']; before=inputs['original_command']
        store._owner(db,auth['account_uuid'],owner_id,generation,before['binding_version'])
        row=handoff_row(db,auth['account_uuid'])
        if not row or row['new_owner_id']!=owner_id or row['new_generation']!=generation or row['resolution'] is not None: _reject()
        evidence=result.get('publish_evidence') or {}; comment=result.get('comment') or {}
        if (result.get('status')!='verified_published' or not evidence.get('post_id') or video_id(evidence.get('publish_url',''))!=evidence['post_id']
                or any(evidence.get(k) is not True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified'))
                or evidence.get('review_status')!='clear' or comment.get('status') not in {'sent_visible','matching_comment_already_visible','not_requested'}): _reject()
        comment_text=str(inputs['prepared'].get('comment') or '').strip()
        if comment_text:
            identity={'account_uuid':auth['account_uuid'],'post_id':evidence['post_id'],
                'comment_sha256':hashlib.sha256(comment_text.encode('utf-8')).hexdigest()}
            comment_key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            if (comment.get('status') not in {'sent_visible','matching_comment_already_visible'}
                    or comment.get('schema')!='authorized_publication_comment/v1' or comment.get('identity')!=identity
                    or comment.get('post_url')!=f"https://www.douyin.com/video/{evidence['post_id']}"
                    or comment.get('comment')!=comment_text): _reject()
            receipt_path=quota.ROOT/'data/publish_comments'/f'{comment_key}.receipt.json'
            if _load(_ref(receipt_path))!=comment: _reject()
        elif comment.get('status')!='not_requested':
            _reject()
        evidence_ref=result['evidence_ref']; frozen=_load(evidence_ref)
        if (Path(evidence_ref['path']).resolve().parent != (quota.ROOT/'data/publication_reconciliations'/reconciliation_id).resolve()
                or frozen.get('schema')!='publication_reconciliation_evidence/20261019/v1'
                or frozen.get('account_uuid')!=auth['account_uuid'] or frozen.get('original_command_id')!=auth['original_command_id']
                or frozen.get('reconciliation_command_id')!=reconciliation_id
                or frozen.get('result')!={k:result[k] for k in ('status','publish_evidence','comment')}): _reject()
        resolved={'original_unknown_snapshot':before,'reconciliation_command_id':reconciliation_id,
            'reconciliation_evidence':evidence_ref,'status':'published','success':True,**evidence,'comment':comment,
            'original_journal':auth['original_journal'],'submission_lock_retained':auth['original_submission_lock']}
        db.execute("UPDATE browser_control_commands SET state='succeeded',error_code=NULL,result=?,updated_at=? WHERE command_id=?",(_json(resolved),store.clock(),auth['original_command_id']))
        db.execute(f'UPDATE {TABLE} SET resolution=? WHERE account_id=?',(_json(resolved),auth['account_uuid']))
        return resolved
