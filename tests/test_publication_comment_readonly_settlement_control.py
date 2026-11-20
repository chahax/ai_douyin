"""Real control owner/SQLite/lease tests; native browser reads are fixtures."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_publication_autonomous_reconciliation import authority,transfer
from test_publication_reconciliation_control import incident
from test_publication_bounded_retry_authorization import account_seed,write
from src.operations_accounts import publication_comment_settlement_control as settlement
from src.operations_accounts import publication_autonomous_reconciliation as auto
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlRejected,BrowserCommandResult,_json


@pytest.fixture
def submitted(authority,monkeypatch):
    f=authority
    monkeypatch.setattr(settlement,'REGISTRY',f.root/'SETTLEMENT_REGISTRY.json')
    transfer(f)
    source=f.store.submit('acct:one',f.original['binding_version'],'publication_reconcile','submitted-one',{
        'account_uuid':'acct:one','account_key':'one','original_command_id':f.original['command_id'],
        'reconciliation_authorization':f.auth,'reconciliation_attempt':1})
    post='1234567890123456789';identity={'account_uuid':'acct:one','post_id':post,'comment_sha256':hashlib.sha256(f.p['comment'].encode()).hexdigest()}
    pe={k:True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified')}
    pe.update(post_id=post,publish_url='https://www.douyin.com/video/'+post,review_status='clear')
    comment={'schema':'authorized_publication_comment/v1','identity':identity,'post_url':pe['publish_url'],'comment':f.p['comment'],
        'status':'outcome_unknown','submitted':None,'submission_lock_retained':True}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    directory=f.root/'data/publish_comments';directory.mkdir(parents=True)
    f.comment_receipt=write(directory/(key+'.receipt.json'),comment)
    f.comment_claim=write(directory/(key+'.submitted.json'),{'identity':identity,'status':'submission_started'})
    result={'status':'outcome_unknown','publish_evidence':pe,'comment':comment}
    out=f.root/'data/publication_reconciliations'/source['command_id'];out.mkdir(parents=True)
    result['evidence_ref']=write(out/'evidence.json',{'schema':'publication_reconciliation_evidence/20261019/v1','account_uuid':'acct:one',
        'original_command_id':f.original['command_id'],'reconciliation_command_id':source['command_id'],'result':copy.deepcopy(result)})
    with f.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id='original-owner',generation=1,result=? WHERE command_id=?",(_json(result),source['command_id']))
    f.source=f.store.get(source['command_id']);source_ref=write(f.root/'SUBMITTED.json',f.source)
    f.scope=write(f.root/'SETTLEMENT.json',settlement.build_candidate(source_ref,f.auth))
    settlement.register(f.scope['path'],f.scope['sha256']);f.pe=pe
    f.original_bytes={p:Path(p).read_bytes() for p in (f.comment_receipt['path'],f.comment_claim['path'],str(f.lock),result['evidence_ref']['path'])}
    return f


def make_result(f,ctx,wrong=False):
    inputs=settlement.get_verified_settlement_inputs(ctx.command['payload']);scope=inputs['manifest']
    comment={'schema':'authorized_publication_comment_readonly/v1','status':'matching_comment_already_visible','identity':scope['comment_identity'],
        'post_url':f.pe['publish_url'],'comment':f.p['comment'],'exact_visible':not wrong,'new_submission':False,'ownership_verified':False,
        'original_comment_command_id':f.source['command_id'],'source_unknown_receipt':scope['source_unknown_receipt'],'source_claim':scope['source_claim']}
    out=f.root/'data/publication_reconciliations'/ctx.task_id;out.mkdir(parents=True)
    comment['readonly_evidence_ref']=write(out/'readonly-comment.json',comment)
    result={'status':'verified_published','publish_evidence':f.pe,'comment':comment}
    result['evidence_ref']=write(out/'evidence.json',{'schema':'publication_reconciliation_evidence/20261019/v1','account_uuid':'acct:one',
        'original_command_id':f.original['command_id'],'reconciliation_command_id':ctx.task_id,'result':copy.deepcopy(result)})
    return result


@pytest.mark.parametrize('wrong',[False,True])
def test_real_actor_only_readonly_evidence_resolves_with_old_unknown_and_claim_retained(submitted,monkeypatch,wrong):
    f=submitted
    def admit(ctx,phase):
        assert settlement.daily_limit(ctx,'publication-comment-settlement',20,'acct:one',quota.control_snapshot('acct:one'))==float('inf')
    original_limit=bridge.operation_daily_limit
    def limit(operation,default,account):
        ctx=bridge.active_context()
        return settlement.daily_limit(ctx,operation,default,account,quota.control_snapshot(account)) if ctx and ctx.command['kind']==settlement.KIND else original_limit(operation,default,account)
    monkeypatch.setattr(bridge,'operation_daily_limit',limit)
    @bridge._with_active
    def handler(ctx,payload):
        with f.resource.runtime.operation_lease(f.resource.context,operation='publication-comment-settlement',daily_limit=20,cooldown_seconds=0):
            ctx.check_dispatch();result=make_result(f,ctx,wrong)
            assert f.repo.get_runtime_state('acct:one').daily_runs==35
        try:f.store.resolve_publication_reconciliation(ctx.task_id,ctx.actor.owner_id,ctx.actor.generation,result)
        except BrowserControlRejected:return BrowserCommandResult('outcome_unknown',result)
        auto.resume_verified_control(f.store,'acct:one')
        return result
    a=BrowserControlActor(f.store,'acct:one',f.original['binding_version'],'backend:3000:readonly',
        {settlement.KIND:handler,'publication_reconcile':lambda *args:pytest.fail('comment sending route dispatched')},
        admission=admit,context=f.resource,owner_acquirer=lambda x,b,o:f.store.acquire_reconciliation_owner(x,b,o,f.auth))
    queued=f.store.queue_publication_comment_settlement(f.scope,f.original['binding_version'])
    assert f.store.queue_publication_comment_settlement(f.scope,f.original['binding_version'])['command_id']==queued['command_id']
    try:
        outcome=a.run_next();assert outcome['state']==('outcome_unknown' if wrong else 'succeeded')
        assert f.store.get(f.source['command_id'])==f.source
        assert all(Path(p).read_bytes()==raw for p,raw in f.original_bytes.items())
        original=f.store.get(f.original['command_id'])
        if wrong:assert original==f.original and quota.control_snapshot('acct:one')['revision']==43
        else:
            assert original['state']=='succeeded' and original['result']['original_unknown_snapshot']==f.original
            assert quota.control_snapshot('acct:one')['revision']==44
            a.close()  # Preserved readonly unknowns no longer block release after exact evidence.
    finally:a.stop_heartbeat()


def test_claim_never_bypasses_other_unknown_human_or_changed_claim(submitted):
    f=submitted;f.store.queue_publication_comment_settlement(f.scope,f.original['binding_version'])
    owner=f.store.acquire_reconciliation_owner('acct:one',f.original['binding_version'],'backend:3000:readonly',f.auth)
    other=f.store.submit('acct:one',f.original['binding_version'],'manual','other',{})
    for state in ('running','waiting_human','outcome_unknown'):
        with f.store._db(write=True) as db:db.execute('UPDATE browser_control_commands SET state=? WHERE command_id=?',(state,other['command_id']))
        assert f.store.claim_next('acct:one',f.original['binding_version'],owner['owner_id'],owner['generation']) is None
    with f.store._db(write=True) as db:db.execute("UPDATE browser_control_commands SET state='failed' WHERE command_id=?",(other['command_id'],))
    original=Path(f.comment_claim['path']).read_bytes()
    Path(f.comment_claim['path']).write_text('{}',encoding='utf-8')
    with pytest.raises((BrowserControlRejected,ValueError)):f.store.claim_next('acct:one',f.original['binding_version'],owner['owner_id'],owner['generation'])
    Path(f.comment_claim['path']).write_bytes(original)
    assert f.repo.get_runtime_state('acct:one').daily_runs==34
