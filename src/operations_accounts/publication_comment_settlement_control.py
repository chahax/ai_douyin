"""Frozen original submitted-comment identity; admission to DOM-only settlement."""
import hashlib
import json
import os
from pathlib import Path

from . import publication_autonomous_reconciliation as auto
from . import publication_reconciliation_authorization as v1
from . import publication_two_run_authorization as quota
from .browser_control import BrowserControlRejected,_json
from .publication_bounded_retry_authorization import _read_command

KIND='publication_comment_settlement'
SCHEMA='publication_comment_readonly_settlement_scope/v1'
REGISTRY=quota.ROOT/'data/account_browser_control_authorizations/publication_comment_settlement.ref.json'


def _reject():
    raise BrowserControlRejected('comment_settlement_invalid','原已提交评论只读补核证据不匹配；未允许再次发送。')


def _full_post(evidence,post):
    from src.platform_adapter.publish_verification import video_id
    return (isinstance(post,str) and video_id(evidence.get('publish_url',''))==post
        and evidence.get('post_id')==post and evidence.get('review_status')=='clear'
        and all(evidence.get(k) is True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified')))


def build_candidate(source_command,authority):
    inputs=auto.validate_authorization(authority);auth=inputs['authorization']
    source=v1._load(source_command)
    if (source!=_read_command(source['command_id']) or source.get('kind')!='publication_reconcile' or source.get('state')!='outcome_unknown'
            or source.get('account_id')!=auth['account_uuid'] or source.get('binding_version')!=auth['binding_version']
            or source['payload'].get('reconciliation_authorization')!=authority):_reject()
    result=source.get('result') or {};comment=result.get('comment') or {};post=comment.get('identity',{}).get('post_id')
    text=str(inputs['prepared'].get('comment') or '').strip()
    identity={'account_uuid':auth['account_uuid'],'post_id':post,'comment_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();directory=quota.ROOT/'data/publish_comments'
    receipt=v1._ref(directory/(key+'.receipt.json'));claim=v1._ref(directory/(key+'.submitted.json'))
    native=v1._load(result['evidence_ref']);ctxdir=(quota.ROOT/'data/publication_reconciliations'/source['command_id']).resolve()
    if (not text or result.get('status')!='outcome_unknown' or not _full_post(result.get('publish_evidence') or {},post)
            or comment.get('schema')!='authorized_publication_comment/v1' or comment.get('status')!='outcome_unknown'
            or comment.get('identity')!=identity or comment.get('comment')!=text
            or comment.get('post_url')!=f'https://www.douyin.com/video/{post}'
            or comment.get('submission_lock_retained') is not True or comment.get('submitted') is not None
            or v1._load(receipt)!=comment or v1._load(claim)!={'identity':identity,'status':'submission_started'}
            or Path(result['evidence_ref']['path']).resolve().parent!=ctxdir
            or native.get('schema')!='publication_reconciliation_evidence/20261019/v1'
            or native.get('account_uuid')!=auth['account_uuid'] or native.get('original_command_id')!=auth['original_command_id']
            or native.get('reconciliation_command_id')!=source['command_id']
            or native.get('result')!={k:result[k] for k in ('status','publish_evidence','comment')}):_reject()
    return {'schema':SCHEMA,'authority':authority,'source_command':source_command,'source_evidence':result['evidence_ref'],
        'source_unknown_receipt':receipt,'source_claim':claim,'prepared':auth['prepared'],'account_uuid':auth['account_uuid'],
        'account_key':auth['account_key'],'original_command_id':auth['original_command_id'],'original_comment_command_id':source['command_id'],
        'binding_version':auth['binding_version'],'post_id':post,'comment_identity':identity,'readonly':True,'new_submission_authorized':False}


def validate(reference,*,require_registered=True):
    manifest=v1._load(reference)
    if require_registered and json.loads(REGISTRY.read_bytes())!=reference:_reject()
    if manifest.get('schema')!=SCHEMA or manifest!=build_candidate(manifest['source_command'],manifest['authority']):_reject()
    inputs=auto.validate_authorization(manifest['authority'])
    return dict(inputs,settlement=manifest,manifest=manifest,source_command=v1._load(manifest['source_command']),
        source_evidence=v1._load(manifest['source_evidence']),source_comment_receipt=v1._load(manifest['source_unknown_receipt']),
        source_comment_claim=v1._load(manifest['source_claim']),post_id=manifest['post_id'],
        comment_text=str(inputs['prepared']['comment']).strip(),comment_identity=manifest['comment_identity'])


def register(path,sha256):
    reference={'path':str(Path(path).resolve()),'sha256':sha256};validate(reference,require_registered=False)
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    try:
        with REGISTRY.open('x',encoding='utf-8') as handle:handle.write(_json(reference));handle.flush();os.fsync(handle.fileno())
    except FileExistsError:
        if json.loads(REGISTRY.read_bytes())!=reference:_reject()
    return reference


def get_verified_settlement_inputs(payload):
    if not isinstance(payload,dict) or set(payload)!={'account_uuid','account_key','reconciliation_authorization','comment_settlement','settlement_attempt'}:_reject()
    if type(payload['settlement_attempt']) is not int or payload['settlement_attempt']<1:_reject()
    inputs=validate(payload['comment_settlement']);scope=inputs['settlement']
    if payload['reconciliation_authorization']!=scope['authority'] or any(payload[k]!=scope[k] for k in ('account_uuid','account_key')):_reject()
    return inputs


def key(reference,index):return f"publication-comment-settlement:{reference['sha256']}:{index}"


def daily_limit(ctx,operation,default,account_uuid,control):
    if not ctx or ctx.command['kind']!=KIND or operation!='publication-comment-settlement' or default!=20:return default
    inputs=get_verified_settlement_inputs(ctx.command['payload']);auth=inputs['authorization'];payload=ctx.command['payload']
    if (ctx.account_id!=auth['account_uuid'] or account_uuid!=ctx.account_id
            or ctx.command['idempotency_key']!=key(payload['comment_settlement'],payload['settlement_attempt'])
            or not auto.control_allowed(auth) or control.get('account_uuid')!=account_uuid):_reject()
    return float('inf')


def _attempts(db,account,reference):
    return [dict(c) for c in db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND kind=? ORDER BY created_at,command_id",(account,KIND))
        if json.loads(c['payload']).get('comment_settlement')==reference]


def _native_result(command,scope):
    result=command.get('result')
    if isinstance(result,str):result=json.loads(result)
    if command['state']!='outcome_unknown' or not result:return False
    try:
        frozen=v1._load(result['evidence_ref'])
        return (Path(result['evidence_ref']['path']).resolve().parent==(quota.ROOT/'data/publication_reconciliations'/command['command_id']).resolve()
            and frozen.get('schema')=='publication_reconciliation_evidence/20261019/v1'
            and frozen.get('account_uuid')==scope['account_uuid'] and frozen.get('original_command_id')==scope['original_command_id']
            and frozen.get('reconciliation_command_id')==command['command_id']
            and frozen.get('result')=={k:result[k] for k in ('status','publish_evidence','comment')}
            and result.get('comment',{}).get('new_submission') is False
            and result.get('comment',{}).get('schema')=='authorized_publication_comment_readonly/v1')
    except (OSError,ValueError,KeyError,TypeError):return False


def allowed_ids(db,auth,authority):
    if not REGISTRY.exists():return set()
    reference=json.loads(REGISTRY.read_bytes());inputs=validate(reference);scope=inputs['settlement']
    if scope['authority']!=authority or scope['account_uuid']!=auth['account_uuid']:_reject()
    return {c['command_id'] for c in _attempts(db,auth['account_uuid'],reference) if _native_result(c,scope)}


def queue(store,reference,binding_version,attempt=None):
    scope=validate(reference)['settlement']
    if binding_version!=scope['binding_version']:_reject()
    with store._db() as db:
        values=_attempts(db,scope['account_uuid'],reference)
        if attempt is not None:
            existing=next((c for c in values if json.loads(c['payload'])['settlement_attempt']==attempt),None)
            if existing:return store._command(existing)
        live=[c for c in values if c['state'] in {'queued','running','paused','waiting_human'}]
        if live:return store._command(live[0])
        index=max([json.loads(c['payload'])['settlement_attempt'] for c in values] or [0])+1
        if attempt is not None and attempt!=index:_reject()
    payload={'account_uuid':scope['account_uuid'],'account_key':scope['account_key'],'reconciliation_authorization':scope['authority'],
        'comment_settlement':reference,'settlement_attempt':index}
    return store.submit(scope['account_uuid'],binding_version,KIND,key(reference,index),payload,priority=450)


def claim(store,db,account_id,binding_version,owner_id,generation):
    if not REGISTRY.exists():return None
    reference=json.loads(REGISTRY.read_bytes());inputs=validate(reference);scope=inputs['settlement'];auth=inputs['authorization']
    record=auto.row(db,account_id)
    if (account_id!=scope['account_uuid'] or binding_version!=scope['binding_version'] or not record
            or record['resolution'] is not None or record['new_owner_id']!=owner_id or record['new_generation']!=generation
            or json.loads(record['authorization'])!=scope['authority']):return None
    allowed=auto._allowed_unresolved(db,auth,scope['authority'])
    blockers=db.execute("SELECT command_id,state FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused','waiting_human','outcome_unknown')",(account_id,)).fetchall()
    if any(c['state']!='outcome_unknown' or c['command_id'] not in allowed for c in blockers):return None
    attempts=_attempts(db,account_id,reference);prior=[c for c in attempts if c['state']!='queued']
    if prior:
        latest=prior[-1]
        if not _native_result(latest,scope) or store.clock()-latest['updated_at']<30:return None
        result=json.loads(latest['result'])
        if result.get('comment',{}).get('status')=='human_required':return None
    queued=[c for c in attempts if c['state']=='queued']
    if not queued:return None
    command=store._command(queued[0]);get_verified_settlement_inputs(command['payload'])
    if command['idempotency_key']!=key(reference,command['payload']['settlement_attempt']):_reject()
    db.execute("UPDATE browser_control_commands SET state='running',owner_id=?,generation=?,updated_at=? WHERE command_id=?",(owner_id,generation,store.clock(),command['command_id']))
    return store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(command['command_id'],)).fetchone())


def validate_readonly_comment(command,inputs,result):
    scope=inputs['settlement'];comment=result.get('comment') or {};post=scope['post_id']
    if (not _full_post(result.get('publish_evidence') or {},post) or comment.get('schema')!='authorized_publication_comment_readonly/v1'
            or comment.get('status')!='matching_comment_already_visible' or comment.get('exact_visible') is not True
            or comment.get('new_submission') is not False or comment.get('ownership_verified') is not False
            or comment.get('identity')!=scope['comment_identity'] or comment.get('comment')!=inputs['comment_text']
            or comment.get('post_url')!=f'https://www.douyin.com/video/{post}'
            or comment.get('original_comment_command_id')!=scope['original_comment_command_id']
            or comment.get('source_unknown_receipt')!=scope['source_unknown_receipt'] or comment.get('source_claim')!=scope['source_claim']):_reject()
    reference=comment['readonly_evidence_ref'];native=v1._load(reference)
    if (not Path(reference['path']).resolve().is_relative_to((quota.ROOT/'data/publication_reconciliations'/command['command_id']).resolve())
            or native!={k:v for k,v in comment.items() if k!='readonly_evidence_ref'}):_reject()
