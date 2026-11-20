"""A frozen original-work authority for serial, audited, non-uploading checks.

The v1 authority and handoff rows remain immutable. Ordinary operations keep
their existing quota and unresolved-command gates.
"""
import hashlib
import json
import math
import os
from pathlib import Path

from . import publication_reconciliation_authorization as v1
from . import publication_two_run_authorization as quota
from .browser_control import BrowserControlRejected, _json
from .publication_bounded_retry_authorization import _read_command

SCHEMA='publication_autonomous_reconciliation_authorization/v2'
AUTH_SHA256='9dbe372c8a4168d838791fa1b3437023beadb3d13045c9232686e25e88a66447'
REGISTRY=quota.ROOT/'data/account_browser_control_authorizations/publication_autonomous_reconciliation.ref.json'
TABLE='browser_control_autonomous_reconciliation'
AUDIT_TABLE=TABLE+'_history'


def _reject():
    raise BrowserControlRejected('autonomous_reconciliation_invalid','原作品自主核查授权或原生证据不匹配，未放行。')


def is_v2(reference):
    return isinstance(reference,dict) and reference.get('sha256')==AUTH_SHA256


def validate_authorization(reference,*,require_registered=True):
    if not is_v2(reference):_reject()
    auth=v1._load(reference)
    if require_registered and json.loads(REGISTRY.read_bytes())!=reference:_reject()
    if (auth.get('schema')!=SCHEMA or auth.get('decision_source')!='explicit_user_statement' or not auth.get('user_statement')
            or auth.get('minimum_interval_seconds')!=30 or auth.get('active_control_revision')!=43
            or auth.get('baseline_daily_runs')!=34
            or any(auth.get(k) is not True for k in ('read_only_reconciliation_unlimited','project_browser_process_termination_authorized',
                'backend_restart_authorized','preserve_original_unknown_snapshots','retain_submission_lock','preserve_daily_runs',
                'ordinary_daily_limit_unchanged','comment_authorization_is_original_prepared','stop_on_unknown_comment_submission'))
            or any(auth.get(k) is not False for k in ('new_upload_authorized','new_publish_click_authorized','comment_retry_authorized'))):_reject()
    prior=v1._load(auth['prior_authorization'])
    if auth['prior_authorization']!=v1.registered_reference() or auth['prior_authorization']['sha256']!=v1.AUTH_SHA256:_reject()
    before=v1._load(auth['original_command']); previous=v1._load(auth['prior_reconciliation'])
    if (before!=_read_command(auth['original_command_id']) or previous!=_read_command(auth['prior_reconciliation_id'])
            or before.get('state')!='outcome_unknown' or before.get('kind')!='publish'
            or before.get('result',{}).get('status')!='submission_unknown'
            or previous.get('state')!='outcome_unknown' or previous.get('kind')!='publication_reconcile'
            or previous.get('result',{}).get('status')!='not_found'
            or previous.get('result',{}).get('comment',{}).get('status')!='not_submitted'
            or previous['payload'].get('reconciliation_authorization')!=auth['prior_authorization']
            or previous['payload'].get('original_command_id')!=auth['original_command_id']
            or before.get('binding_version')!=auth['binding_version'] or previous.get('binding_version')!=auth['binding_version']
            or any(c.get('account_id')!=auth['account_uuid'] for c in (before,previous))):_reject()
    for field in ('original_command_id','prepared','original_journal','original_submission_lock'):
        if auth[field]!=prior[field]:_reject()
    if v1._load(prior['original_command'])!=before:_reject()
    prepared=v1._load(auth['prepared'])
    quota.validate_publication_payload({'account_uuid':auth['account_uuid'],'account_key':auth['account_key'],
        'prepared':auth['prepared'],'video':prepared['video']},before['payload'])
    if prepared.get('ai_generated') is not True or prepared.get('fictional_story') is not True:_reject()
    _,raw,_=quota._read(auth['original_journal']['path'],auth['original_journal']['sha256'])
    rows=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    lock=v1._load(auth['original_submission_lock'])
    if (not rows or rows[0].get('stage')!='prepared' or rows[-1].get('stage')!='submission_unknown'
            or lock.get('status')!='submission_started' or lock.get('journal')!=auth['original_journal']['path']):_reject()
    evidence=v1._load(previous['result']['evidence_ref'])
    if (evidence.get('original_command_id')!=auth['original_command_id'] or evidence.get('reconciliation_command_id')!=previous['command_id']
            or evidence.get('result')!={k:previous['result'][k] for k in ('status','publish_evidence','comment')}):_reject()
    owner=v1._load(auth['owner_snapshot'])
    if (owner.get('owner_id')!=auth['source_owner_id'] or owner.get('generation')!=auth['source_generation']
            or owner.get('binding_version')!=auth['binding_version'] or owner.get('account_id')!=auth['account_uuid']):_reject()
    frozen=v1._load(auth['control_snapshot'])
    if (frozen.get('state')!='paused' or frozen.get('revision')!=43 or frozen.get('account_uuid')!=auth['account_uuid']
            or auth.get('allowed_reconciliation_control_state')!='paused' or auth.get('allowed_reconciliation_control_revision')!=43
            or auth.get('resume_known_scheduler_pause_after_verified_publication') is not True
            or auth.get('resume_control_expected_revision')!=43 or auth.get('resume_control_target_revision')!=44
            or auth.get('resume_control_target_state')!='active'):_reject()
    return {'authorization':auth,'original_command':before,'prepared':prepared,'journal_rows':rows,
        'original_submission_lock':lock,'prior_reconciliation':previous}


def register_authorization(path,sha256):
    reference={'path':str(Path(path).resolve()),'sha256':sha256}
    validate_authorization(reference,require_registered=False)
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    try:
        with REGISTRY.open('x',encoding='utf-8') as handle:
            handle.write(_json(reference));handle.flush();os.fsync(handle.fileno())
    except FileExistsError:
        if json.loads(REGISTRY.read_bytes())!=reference:_reject()
    return reference


def get_verified_reconciliation_inputs(payload):
    reference=payload.get('reconciliation_authorization') if isinstance(payload,dict) else None
    if not is_v2(reference):return v1.get_verified_reconciliation_inputs(payload)
    if set(payload)!={'account_uuid','account_key','original_command_id','reconciliation_authorization','reconciliation_attempt'}:_reject()
    attempt=payload['reconciliation_attempt']
    if type(attempt) is not int or attempt<1:_reject()
    inputs=validate_authorization(reference);auth=inputs['authorization']
    if any(payload[k]!=auth[k] for k in ('account_uuid','account_key','original_command_id')):_reject()
    return inputs


def key(reference,index):
    return f"publication-reconcile:{reference['sha256']}:attempt:{index}"


def daily_limit(ctx,operation,default,account_uuid,control):
    if not is_v2(ctx.command.get('payload',{}).get('reconciliation_authorization')):
        return v1.daily_limit(ctx,operation,default,account_uuid,control)
    if ctx.command['kind']!='publication_reconcile' or operation!='publication-reconciliation' or default!=20:return default
    auth=get_verified_reconciliation_inputs(ctx.command['payload'])['authorization']
    if (ctx.account_id!=account_uuid or account_uuid!=auth['account_uuid']
            or ctx.command['idempotency_key']!=key(ctx.command['payload']['reconciliation_authorization'],ctx.command['payload']['reconciliation_attempt'])
            or not control or not control_allowed(auth)
            or control.get('account_uuid')!=account_uuid or control.get('account_key')!=auth['account_key']):_reject()
    return float('inf')  # Comparison only; acquire_runtime persists the integer run counter.


def control_allowed(auth):
    import sqlite3
    from src.scheduler.account_refresh import DB
    with sqlite3.connect(Path(DB).resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
        db.row_factory=sqlite3.Row
        current=db.execute('SELECT * FROM account_controls WHERE account_uuid=?',(auth['account_uuid'],)).fetchone()
        return current is not None and dict(current)==v1._load(auth['control_snapshot'])


def resume_verified_control(store,account_id):
    """Explicit scope CAS, after complete publication evidence; no browser RPC."""
    import sqlite3
    from src.scheduler.account_refresh import DB
    with store._db() as db:
        record=row(db,account_id)
        if not record or not record['resolution']:_reject()
        reference=json.loads(record['authorization']);auth=v1._load(reference)
        if not is_v2(reference) or json.loads(REGISTRY.read_bytes())!=reference:_reject()
    frozen=v1._load(auth['control_snapshot'])
    with sqlite3.connect(Path(DB).resolve().as_uri()+'?mode=rw',uri=True,timeout=10) as db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
        current=dict(db.execute('SELECT * FROM account_controls WHERE account_uuid=?',(account_id,)).fetchone())
        db.execute('CREATE TABLE IF NOT EXISTS publication_reconciliation_control_resumes(account_uuid TEXT PRIMARY KEY,authorization TEXT NOT NULL,before_snapshot TEXT NOT NULL,after_snapshot TEXT NOT NULL)')
        prior=db.execute('SELECT * FROM publication_reconciliation_control_resumes WHERE account_uuid=?',(account_id,)).fetchone()
        if prior:
            if prior['authorization']!=_json(reference) or json.loads(prior['after_snapshot'])!=current:_reject()
            return current
        if current!=frozen:_reject()
        db.execute("UPDATE account_controls SET state='active',reason='',error_code='',recovery_requested_at=NULL,recovery_lease_until=0,recovery_token=NULL,revision=44,updated_at=? WHERE account_uuid=? AND revision=43",(store.clock(),account_id))
        after=dict(db.execute('SELECT * FROM account_controls WHERE account_uuid=?',(account_id,)).fetchone())
        db.execute('INSERT INTO publication_reconciliation_control_resumes VALUES(?,?,?,?)',(account_id,_json(reference),_json(frozen),_json(after)))
        return after


def _completed_resolution(db,account_id):
    """Use the atomically settled command/native receipt, not nested audit blobs."""
    try:
        if not REGISTRY.exists():return None
        reference=json.loads(REGISTRY.read_bytes());auth=v1._load(reference)
        if auth.get('schema')!=SCHEMA or auth.get('account_uuid')!=account_id:return None
        command=db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(auth['original_command_id'],)).fetchone()
        if not command or command['account_id']!=account_id or command['kind']!='publish' or command['state']!='succeeded':return None
        result=json.loads(command['result']);before=v1._load(auth['original_command'])
        from .browser_control import BrowserControlStore
        current=BrowserControlStore._command(command)
        if any(current.get(k)!=before.get(k)for k in('command_id','account_id','binding_version','kind','idempotency_key','payload','request_sha','priority','owner_id','generation','cursor','created_at')):return None
        if (result.get('status')!='published' or result.get('success')is not True
                or result.get('original_unknown_snapshot')!=before or result.get('review_status')!='clear'
                or any(result.get(k)is not True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified'))):return None
        native=v1._load(result['reconciliation_evidence']);proof=native.get('result',{});post=proof.get('publish_evidence',{})
        if (native.get('schema')!='publication_reconciliation_evidence/20261019/v1'
                or native.get('account_uuid')!=account_id or native.get('original_command_id')!=auth['original_command_id']
                or native.get('reconciliation_command_id')!=result['reconciliation_command_id']
                or proof.get('status')!='verified_published' or proof.get('comment')!=result.get('comment')
                or post.get('review_status')!='clear'
                or any(post.get(k)is not True for k in('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified'))
                or any(result.get(k)!=v for k,v in post.items())):return None
        return result
    except (OSError,ValueError,TypeError,KeyError,BrowserControlRejected):return None


def row(db,account_id,*,include_retirement=True):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():return None
    if not include_retirement:
        completed=_completed_resolution(db,account_id)
        if completed is not None:
            return {'account_id':account_id,'resolution':_json(completed)}
    fields='*'if include_retirement else 'account_id,authorization,original_owner_id,original_generation,binding_version,released_at,new_owner_id,new_generation,resolution,new_owner_create_time'
    result=db.execute(f'SELECT {fields} FROM {TABLE} WHERE account_id=?',(account_id,)).fetchone()
    return dict(result) if result else None


def _identity_checks(auth,dead):
    import psutil
    checks=[]
    identities=[(dead['original_backend_pid'],dead['original_backend_create_time'])]+[(c['pid'],c['create_time']) for c in dead['observed_children']]
    prior=dead.get('pid_identity_checks')
    if not isinstance(prior,list) or len(prior)!=len(identities):_reject()
    for (pid,created),proof in zip(identities,prior):
        if proof.get('pid')!=pid or proof.get('expected_create_time')!=created or proof.get('status') not in {'not_present','pid_reused'}:_reject()
        try:current=psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            checks.append({'pid':pid,'expected_create_time':created,'status':'not_present'});continue
        except (psutil.Error,OSError,ValueError):_reject()
        if (not math.isfinite(current) or abs(current-created)<=1e-6 or proof.get('status')!='pid_reused'
                or abs(proof.get('current_create_time',created)-current)>1e-6):_reject()
        checks.append({'pid':pid,'expected_create_time':created,'status':'pid_reused','current_create_time':current})
    return checks


def _attempts(db,account_id,reference):
    values=db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND kind='publication_reconcile' ORDER BY created_at,command_id",(account_id,)).fetchall()
    return [dict(c) for c in values if json.loads(c['payload']).get('reconciliation_authorization')==reference]


def _allowed_unresolved(db,auth,reference):
    initial={auth['original_command_id'],auth['prior_reconciliation_id']}
    for cmd in _attempts(db,auth['account_uuid'],reference):
        if cmd['state']=='outcome_unknown' and cmd['result']:
            result=json.loads(cmd['result'])
            # No missing handler/IO result may be laundered as a repeatable read.
            if result.get('evidence_ref') and result.get('status') in {'not_found','verification_pending','outcome_unknown','human_required'}:
                frozen=v1._load(result['evidence_ref'])
                if frozen.get('reconciliation_command_id')==cmd['command_id'] and frozen.get('result')=={k:result[k] for k in ('status','publish_evidence','comment')}:
                    initial.add(cmd['command_id'])
    from .publication_comment_settlement_control import allowed_ids
    return initial|allowed_ids(db,auth,reference)


def _repeatable_result(command,auth):
    """A new check is allowed only after evidenced, non-submitted work."""
    from src.platform_adapter.publish_verification import video_id
    result=command.get('result')
    if isinstance(result,str):result=json.loads(result)
    if command.get('state')!='outcome_unknown' or not isinstance(result,dict) or result.get('status') not in {'not_found','verification_pending'}:return False
    try:
        native=v1._load(result['evidence_ref'])
        ctxdir=(quota.ROOT/'data/publication_reconciliations'/command['command_id']).resolve()
        if (Path(result['evidence_ref']['path']).resolve().parent!=ctxdir
                or native.get('schema')!='publication_reconciliation_evidence/20261019/v1'
                or native.get('account_uuid')!=auth['account_uuid'] or native.get('original_command_id')!=auth['original_command_id']
                or native.get('reconciliation_command_id')!=command['command_id']
                or native.get('result')!={k:result[k] for k in ('status','publish_evidence','comment')}):return False
        comment=result['comment'];evidence=result['publish_evidence']
        if comment.get('status') in {'not_submitted','not_requested'}:return True
        if (result['status']!='verification_pending' or comment.get('schema')!='authorized_publication_comment/v1'
                or comment.get('status') not in {'comment_editor_unavailable','comment_submit_unavailable'}
                or comment.get('submitted') is not False or comment.get('submission_lock_retained') is not False
                or evidence.get('review_status')!='clear'
                or any(evidence.get(k) is not True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified'))
                or evidence.get('human_required') or comment.get('human_required')):return False
        text=str(v1._load(auth['prepared']).get('comment') or '').strip();post=evidence.get('post_id')
        if not text or not isinstance(post,str) or video_id(evidence.get('publish_url',''))!=post:return False
        identity={'account_uuid':auth['account_uuid'],'post_id':post,'comment_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
        if comment.get('identity')!=identity or comment.get('comment')!=text or comment.get('post_url')!=f'https://www.douyin.com/video/{post}':return False
        receipt_key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        directory=quota.ROOT/'data/publish_comments'
        if (directory/(receipt_key+'.submitted.json')).exists():return False
        _,raw,_=quota._read(directory/(receipt_key+'.receipt.json'))
        current=json.loads(raw)
        if (current.get('schema')!='authorized_publication_comment/v1' or current.get('post_url')!=f'https://www.douyin.com/video/{post}'
                or current.get('identity')!=identity or current.get('comment')!=text
                or current.get('status') not in {'comment_editor_unavailable','comment_submit_unavailable'}
                or current.get('submitted') is not False or current.get('submission_lock_retained') is not False
                or current.get('human_required')):return False
        frozen_path=ctxdir/'comment_pre_submit_receipt.json'
        if not frozen_path.exists():
            if json.loads(raw)!=comment:return False
            try:
                with frozen_path.open('xb') as handle:
                    handle.write(raw);handle.flush();os.fsync(handle.fileno())
            except FileExistsError:pass
        return v1._load(v1._ref(frozen_path))==comment and not (directory/(receipt_key+'.submitted.json')).exists()
    except (KeyError,TypeError,ValueError,OSError,BrowserControlRejected):
        return False


def handoff(store,*,owner_id,generation,authorization,expected_snapshots_sha256,retirement_evidence,connection):
    db=connection
    if not db.in_transaction or Path(next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')).resolve()!=store.path:_reject()
    inputs=validate_authorization(authorization);auth=inputs['authorization'];old=row(db,auth['account_uuid'])
    if not control_allowed(auth):_reject()
    owner=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(auth['account_uuid'],)).fetchone()
    if (not owner or owner['state']!='active' or owner['owner_id']!=owner_id or owner['generation']!=generation
            or owner['binding_version']!=auth['binding_version']):_reject()
    if old:
        if old['new_owner_id']!=owner_id or old['new_generation']!=generation or json.loads(old['authorization'])!=authorization:_reject()
    elif owner_id!=auth['source_owner_id'] or generation!=auth['source_generation']:_reject()
    commands=[store._command(c) for c in db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",(auth['account_uuid'],))]
    if (not commands or any(c['state']!='outcome_unknown' or c['command_id'] not in _allowed_unresolved(db,auth,authorization) for c in commands)
            or {c['command_id']:hashlib.sha256(_json(c).encode()).hexdigest() for c in commands}!=expected_snapshots_sha256):_reject()
    dead=v1._load(retirement_evidence)
    if (dead.get('account_uuid')!=auth['account_uuid'] or dead.get('original_command_id')!=auth['original_command_id']
            or dead.get('owner_id')!=owner_id or dead.get('generation')!=generation or dead.get('parent_exited') is not True
            or dead.get('descendants_exited') is not True or dead.get('alive_child_ids')!=[]
            or not isinstance(dead.get('observed_children'),list) or set(dead.get('gone_child_ids',[]))!={c['pid'] for c in dead['observed_children']}
            or not 0<=store.clock()-dead.get('finished_at',0)<=300):_reject()
    if not old and (dead.get('original_backend_pid')!=auth['source_backend_pid'] or dead.get('original_backend_create_time')!=auth['source_backend_create_time']):_reject()
    if old and (dead.get('original_backend_pid')!=int(owner_id.split(':')[1]) or dead.get('original_backend_create_time')!=old['new_owner_create_time']):_reject()
    checks=_identity_checks(auth,dead)
    db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE}(account_id TEXT PRIMARY KEY,authorization TEXT NOT NULL,
        original_owner_id TEXT NOT NULL,original_generation INTEGER NOT NULL,binding_version TEXT NOT NULL,
        retirement_evidence TEXT NOT NULL,released_at REAL NOT NULL,new_owner_id TEXT,new_generation INTEGER,resolution TEXT,new_owner_create_time REAL)''')
    db.execute(f'CREATE TABLE IF NOT EXISTS {AUDIT_TABLE}(audit_id INTEGER PRIMARY KEY,account_id TEXT NOT NULL,evidence TEXT NOT NULL,created_at REAL NOT NULL)')
    audit={'authorization':authorization,'retirement_evidence':retirement_evidence,'original_snapshots':commands,
        'previous_v1_handoff':v1.handoff_row(db,auth['account_uuid']),'previous_v2_handoff':old,'pid_identity_checks':checks}
    db.execute(f'INSERT INTO {AUDIT_TABLE}(account_id,evidence,created_at) VALUES(?,?,?)',(auth['account_uuid'],_json(audit),store.clock()))
    db.execute(f'INSERT OR REPLACE INTO {TABLE} VALUES(?,?,?,?,?,?,?,?,?,?,?)',(auth['account_uuid'],_json(authorization),owner_id,generation,auth['binding_version'],_json(audit),store.clock(),None,None,None,None))
    db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",(store.clock(),auth['account_uuid']))
    return audit


def acquire_owner(store,account_id,binding_version,owner_id,authorization):
    auth=validate_authorization(authorization)['authorization']
    if not control_allowed(auth):_reject()
    with store._db(write=True) as db:
        record=row(db,account_id);old=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone()
        if (not record or not old or old['state']!='released' or record['new_owner_id'] is not None
                or old['owner_id']!=record['original_owner_id'] or old['generation']!=record['original_generation']
                or json.loads(record['authorization'])!=authorization or account_id!=auth['account_uuid']
                or binding_version!=auth['binding_version'] or old['binding_version']!=binding_version):_reject()
        import psutil
        try:
            if not owner_id.startswith('backend:'):_reject()
            created=psutil.Process(int(owner_id.split(':')[1])).create_time()
        except (ValueError,IndexError,psutil.Error,OSError):_reject()
        gen=old['generation']+1;now=store.clock()
        db.execute("UPDATE browser_control_owners SET owner_id=?,generation=?,state='active',heartbeat=?,updated_at=? WHERE account_id=?",(owner_id,gen,now,now,account_id))
        db.execute(f'UPDATE {TABLE} SET new_owner_id=?,new_generation=?,new_owner_create_time=? WHERE account_id=?',(owner_id,gen,created,account_id))
        return dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone())


def claim(store,db,account_id,binding_version,owner_id,generation):
    record=row(db,account_id)
    if not record or record['new_owner_id']!=owner_id or record['new_generation']!=generation or record['resolution'] is not None:return None
    reference=json.loads(record['authorization']);auth=validate_authorization(reference)['authorization']
    blockers=db.execute("SELECT command_id,state FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",(account_id,)).fetchall()
    if any(c['state']!='outcome_unknown' or c['command_id'] not in _allowed_unresolved(db,auth,reference) for c in blockers):return None
    attempts=_attempts(db,account_id,reference)
    if any(c['state'] in {'running','paused','waiting_human'} for c in attempts):return None
    prior=[c for c in attempts if c['state'] not in {'queued'}]
    if prior and not _repeatable_result(prior[-1],auth):return None
    if prior and store.clock()-max(c['updated_at'] for c in prior)<auth['minimum_interval_seconds']:return None
    queued=[c for c in attempts if c['state']=='queued']
    if not queued:return None
    command=store._command(queued[0]);get_verified_reconciliation_inputs(command['payload'])
    if command['binding_version']!=binding_version or command['idempotency_key']!=key(reference,command['payload']['reconciliation_attempt']):_reject()
    db.execute("UPDATE browser_control_commands SET state='running',owner_id=?,generation=?,updated_at=? WHERE command_id=?",(owner_id,generation,store.clock(),command['command_id']))
    return store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(command['command_id'],)).fetchone())


def queue(store,authorization,binding_version,attempt=None):
    auth=validate_authorization(authorization)['authorization']
    with store._db(write=True) as db:
        attempts=_attempts(db,auth['account_uuid'],authorization)
        live=[c for c in attempts if c['state'] in {'queued','running','paused','waiting_human'}]
        if live:return store._command(live[0])
        index=max([json.loads(c['payload'])['reconciliation_attempt'] for c in attempts] or [0])+1
        if attempt is not None:
            existing=next((c for c in attempts if json.loads(c['payload'])['reconciliation_attempt']==attempt),None)
            if existing:return store._command(existing)
            if attempt!=index:_reject()
        if attempts and not _repeatable_result(attempts[-1],auth):_reject()
        payload={'account_uuid':auth['account_uuid'],'account_key':auth['account_key'],'original_command_id':auth['original_command_id'],
            'reconciliation_authorization':authorization,'reconciliation_attempt':index}
        # submit owns its transaction. The unique key remains the cross-process CAS.
    return store.submit(auth['account_uuid'],binding_version,'publication_reconcile',key(authorization,index),payload,priority=400)


def queue_continuation(store,account_id):
    with store._db() as db:
        record=row(db,account_id,include_retirement=False)
        if not record or record['resolution'] is not None:return None
        reference=json.loads(record['authorization'])
        attempts=_attempts(db,account_id,reference)
        if not attempts or any(c['state'] in {'queued','running','paused','waiting_human'} for c in attempts):return None
        latest=attempts[-1]
        if not latest['result'] or store.clock()-latest['updated_at']<30:return None
        auth=validate_authorization(reference)['authorization']
        if not _repeatable_result(latest,auth):return None
        if latest['command_id'] not in _allowed_unresolved(db,auth,reference):return None
    return queue(store,reference,record['binding_version'])


def unresolved(store,db,account_id,states):
    """Only exact readonly snapshots settled by a verified result cease blocking."""
    record=None;settled={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():
        completed=_completed_resolution(db,account_id)
        record={'resolution':_json(completed)}if completed is not None else db.execute(f'SELECT resolution FROM {TABLE} WHERE account_id=?',(account_id,)).fetchone()
    if record and record['resolution']:
        resolution=json.loads(record['resolution'])
        settled={c['command_id']:c for c in resolution.get('settled_readonly_snapshots',[])}
    marks=','.join('?' for _ in states)
    commands=[store._command(c) for c in db.execute(f'SELECT * FROM browser_control_commands WHERE account_id=? AND state IN ({marks})',(account_id,*states))]
    return [c for c in commands if settled.get(c['command_id'])!=c]


_load=v1._load
_ref=v1._ref


def resolve(store,reconciliation_id,owner_id,generation,result):
    from src.platform_adapter.publish_verification import video_id
    with store._db(write=True) as db:
        command=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(reconciliation_id,)).fetchone())
        from . import publication_comment_settlement_control as settlement
        readonly_comment=command is not None and command['kind']==settlement.KIND
        if not command or command['kind'] not in {'publication_reconcile',settlement.KIND} or command['state']!='running' or command['owner_id']!=owner_id or command['generation']!=generation: _reject()
        inputs=settlement.get_verified_settlement_inputs(command['payload']) if readonly_comment else get_verified_reconciliation_inputs(command['payload'])
        auth=inputs['authorization']; before=inputs['original_command']
        store._owner(db,auth['account_uuid'],owner_id,generation,before['binding_version'])
        record=row(db,auth['account_uuid'])
        if not record or record['new_owner_id']!=owner_id or record['new_generation']!=generation or record['resolution'] is not None: _reject()
        evidence=result.get('publish_evidence') or {}; comment=result.get('comment') or {}
        if (result.get('status')!='verified_published' or not evidence.get('post_id') or video_id(evidence.get('publish_url',''))!=evidence['post_id']
                or any(evidence.get(k) is not True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified'))
                or evidence.get('review_status')!='clear' or comment.get('status') not in {'sent_visible','matching_comment_already_visible','not_requested'}): _reject()
        comment_text=str(inputs['prepared'].get('comment') or '').strip()
        if readonly_comment:
            settlement.validate_readonly_comment(command,inputs,result)
        elif comment_text:
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
        resolved['settled_readonly_snapshots']=[store._command(c) for c in db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND state='outcome_unknown'",(auth['account_uuid'],)) if c['command_id']!=auth['original_command_id'] and c['command_id'] in _allowed_unresolved(db,auth,command['payload']['reconciliation_authorization'])]
        db.execute("UPDATE browser_control_commands SET state='succeeded',error_code=NULL,result=?,updated_at=? WHERE command_id=?",(_json(resolved),store.clock(),auth['original_command_id']))
        db.execute(f'UPDATE {TABLE} SET resolution=? WHERE account_id=?',(_json(resolved),auth['account_uuid']))
        return resolved
