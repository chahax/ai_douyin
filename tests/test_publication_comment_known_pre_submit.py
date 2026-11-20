"""Native receipt/evidence and real SQLite/actor; no platform operations."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_publication_autonomous_reconciliation import authority,actor,transfer,ui
from test_publication_reconciliation_control import incident
from test_publication_bounded_retry_authorization import account_seed,write
from src.operations_accounts import publication_autonomous_reconciliation as auto
from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlRejected
from src.operations_accounts import publication_reconciliation as service


def receipt_paths(f,comment):
    key=hashlib.sha256(json.dumps(comment['identity'],sort_keys=True).encode()).hexdigest()
    directory=f.root/'data/publish_comments'
    return directory/(key+'.receipt.json'),directory/(key+'.submitted.json')


def known_service(f,monkeypatch):
    window=ui(f,monkeypatch,'verified_published')
    original=service.run_reconciliation
    def run(ctx,payload):
        result=original(ctx,payload)
        result['status']='verification_pending'
        result['comment'].update(status='comment_editor_unavailable',submitted=False,submission_lock_retained=False)
        receipt,_=receipt_paths(f,result['comment']);write(receipt,result['comment'])
        path=Path(result['evidence_ref']['path'])
        frozen=json.loads(path.read_text(encoding='utf-8'))
        frozen['result']={k:result[k] for k in ('status','publish_evidence','comment')}
        result['evidence_ref']=write(path,frozen)
        return result
    monkeypatch.setattr(service,'run_reconciliation',run)
    return window


def test_actor_queues_known_unsubmitted_diagnostic_and_keeps_frozen_receipt_history(authority,monkeypatch):
    f=authority;transfer(f);known_service(f,monkeypatch);a=actor(f)
    command=bridge.queue_publication_reconciliation(f.auth)
    try:
        first=a.run_next();assert first['state']=='outcome_unknown'
        result=first['result'];receipt,claim=receipt_paths(f,result['comment'])
        original=receipt.read_bytes()
        f.store.clock=lambda:__import__('time').time()+31
        second=auto.queue_continuation(f.store,'acct:one')
        assert second['payload']['reconciliation_attempt']==2
        frozen=f.root/'data/publication_reconciliations'/command['command_id']/'comment_pre_submit_receipt.json'
        assert frozen.read_bytes()==original and not claim.exists()
        later=dict(result['comment'],status='comment_submit_unavailable',later_diagnostic=True)
        write(receipt,later)
        assert auto._repeatable_result(first,auto.validate_authorization(f.auth)['authorization'])
        write(receipt,dict(later,status='outcome_unknown'))
        assert a.run_next() is None and f.repo.get_runtime_state('acct:one').daily_runs==35
        write(receipt,later)
        assert a.run_next()['state']=='outcome_unknown' and f.repo.get_runtime_state('acct:one').daily_runs==36
        assert f.store.get(f.original['command_id'])==f.original and f.lock.exists()
    finally:a.stop_heartbeat()


def test_submitted_claim_human_unknown_wrong_text_or_native_evidence_cannot_queue(authority,monkeypatch):
    f=authority;transfer(f);known_service(f,monkeypatch);a=actor(f)
    bridge.queue_publication_reconciliation(f.auth)
    try:
        command=a.run_next();original=copy.deepcopy(command)
        auth=auto.validate_authorization(f.auth)['authorization']
        evidence_path=Path(command['result']['evidence_ref']['path'])
        base=json.loads(evidence_path.read_text(encoding='utf-8'))
        receipt,claim=receipt_paths(f,command['result']['comment'])
        for field,value in [('submitted',True),('submission_lock_retained',True),('status','outcome_unknown'),
                ('human_required',True),('comment','different text'),('identity',{'account_uuid':'different'})]:
            changed=copy.deepcopy(original);changed['result']['comment'][field]=value
            frozen=copy.deepcopy(base);frozen['result']={k:changed['result'][k] for k in ('status','publish_evidence','comment')}
            changed['result']['evidence_ref']=write(evidence_path,frozen);write(receipt,changed['result']['comment'])
            assert not auto._repeatable_result(changed,auth)
        command=copy.deepcopy(original);command['result']['evidence_ref']=write(evidence_path,base);write(receipt,command['result']['comment'])
        claim.write_text('{}',encoding='utf-8')
        assert not auto._repeatable_result(command,auth)
        claim.unlink()
        wrong=copy.deepcopy(base);wrong['result']['comment']['comment']='different native evidence'
        command['result']['evidence_ref']=write(evidence_path,wrong)
        assert not auto._repeatable_result(command,auth)
        command['result']['evidence_ref']=write(evidence_path,base)
        for field,value in [('schema',None),('post_url','https://www.douyin.com/video/9999999999999999999')]:
            write(receipt,dict(command['result']['comment'],**{field:value}))
            assert not auto._repeatable_result(command,auth)
        write(receipt,{'status':'different native receipt'})
        assert not auto._repeatable_result(command,auth)
        # Store's original evidence ref is now deliberately invalid: both queue paths stop.
        f.store.clock=lambda:__import__('time').time()+31
        assert auto.queue_continuation(f.store,'acct:one') is None
        with pytest.raises(BrowserControlRejected):bridge.queue_publication_reconciliation(f.auth)
        assert f.repo.get_runtime_state('acct:one').daily_runs==35
    finally:a.stop_heartbeat()
