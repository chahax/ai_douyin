import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.operations_accounts import browser_control_runtime as runtime


@pytest.mark.parametrize('status,resolve,closed',[
    ('verified_published',True,True),('verification_pending',False,True),('human_required',False,False)])
def test_settlement_handler_serial_closure_and_resolution(monkeypatch,status,resolve,closed):
    from src.operations_accounts import publication_comment_settlement_workflow as workflow
    from src.operations_accounts import publication_autonomous_reconciliation as auto
    events=[]
    @contextmanager
    def lease(*args,**kwargs):
        assert kwargs['operation']=='publication-comment-settlement'
        events.append('lease');yield
    resource=SimpleNamespace(session=None,headless=True,context=object(),console_tasks={},
        runtime=SimpleNamespace(operation_lease=lease),ensure_session=lambda:events.append('session'))
    class Borrowed:
        def __init__(self,*args):self.page=SimpleNamespace(tab_id='original-work-tab')
        def stop(self):events.append('close')
    monkeypatch.setattr(runtime,'BorrowedSession',Borrowed)
    monkeypatch.setattr(workflow,'run_settlement',lambda *args:dict(status=status))
    monkeypatch.setattr(auto,'resume_verified_control',lambda *args:events.append('resume'))
    store=SimpleNamespace(resolve_publication_reconciliation=lambda *args:events.append('resolve'))
    ctx=SimpleNamespace(task_id='a'*32,account_id='account',resource=resource,
        actor=SimpleNamespace(store=store,owner_id='owner',generation=30))
    result=runtime._publication_comment_settlement(ctx,{})
    assert ('resolve'in events)==resolve
    assert ('close'in events)==closed
    if resolve:assert events.index('close')<events.index('resolve')<events.index('resume')
    assert bool(resource.console_tasks)==(status=='human_required')


def test_workflow_requires_new_full_post_evidence_and_records_original_refs(monkeypatch,tmp_path):
    from src.operations_accounts import publication_comment_settlement_workflow as workflow
    from src.operations_accounts import publication_comment_settlement_control as control
    from src.operations_accounts import publication_comment_settlement as reader
    from src.operations_accounts import publication_reconciliation as original
    from src.platform_adapter import douyin_adapter
    scope={'account_uuid':'account','account_key':'account01','post_id':'123',
        'original_command_id':'old-publish','original_comment_command_id':'old-comment',
        'source_unknown_receipt':{'path':'old-receipt','sha256':'x'},'source_claim':{'path':'old-claim','sha256':'y'}}
    inputs={'manifest':scope,'prepared':{'title':'title','hashtags':['tag']},'comment_text':'exact original',
        'original_command':{'payload':{'authorization':{'comment':'exact original'}}},'journal_rows':['journal'],
        'source_evidence':{'result':{'publish_evidence':{'post_verified':True,'review_status':'clear'}}}}
    monkeypatch.setattr(workflow,'ROOT',tmp_path)
    monkeypatch.setattr(control,'get_verified_settlement_inputs',lambda payload:inputs)
    monkeypatch.setattr(original,'_active_ai_source',lambda rows:True)
    monkeypatch.setattr(douyin_adapter,'DouyinAdapter',lambda **kwargs:object())
    seen=[]
    def read(adapter,frozen,post_id,**kwargs):
        seen.append(frozen)
        return {'status':'matching_comment_already_visible','exact_visible':True,'new_submission':False,'publish_evidence':{}}
    monkeypatch.setattr(reader,'verify_only',read)
    ctx=SimpleNamespace(task_id='a'*32,resource=SimpleNamespace(account_uuid='account',account_key='account01',context=object()),check_dispatch=lambda:None)
    result=workflow.run_settlement(ctx,{},object())
    assert result['status']=='verification_pending'
    assert seen[0]['source_claim']==scope['source_claim']
    assert seen[0]['source_unknown_receipt']==scope['source_unknown_receipt']
    saved=json.loads((tmp_path/'data/publication_reconciliations'/ctx.task_id/'evidence.json').read_text(encoding='utf-8'))
    assert saved['result']['publish_evidence']['ai_active_source_verified'] is True
    assert 'post_verified'not in saved['result']['publish_evidence']
