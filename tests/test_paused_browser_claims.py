import sqlite3
from types import SimpleNamespace as NS
import pytest

from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.paused_browser_claims import install


@pytest.mark.parametrize('state,human',[('paused',False),('recovery_requested',False),('recovering',False),('active',True),('active',False)])
def test_preclaim_gate_preserves_queue_until_active_and_human_handoff(tmp_path,state,human):
    path=tmp_path/'refresh.db'
    with sqlite3.connect(path)as db:
        db.execute('create table account_controls(account_uuid text,state text)')
        db.execute('insert into account_controls values(?,?)',('a',state))
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    owner=store.acquire_owner('a','binding','owner')
    original=store.submit('a','binding','maintenance','original',{'mode':'post-publish'})
    actor=NS(store=store,account_id='a')
    resource=NS(manual_tasks={'manual':'tab'}if human else{},console_tasks={})
    install(actor,resource,path=path);guard=store.claim_next;install(actor,resource,path=path)
    assert store.claim_next is guard
    result=store.claim_next('a','binding','owner',owner['generation'])
    if state=='active'and not human:
        assert result['command_id']==original['command_id'] and result['state']=='running'
    else:
        assert result is None
        assert store.get(original['command_id'])==original
        with sqlite3.connect(path)as db:db.execute("update account_controls set state='active'")
        resource.manual_tasks.clear()
        assert store.claim_next('a','binding','owner',owner['generation'])['command_id']==original['command_id']


@pytest.mark.parametrize('kind',['manual','recovery','read','publication_verify'])
def test_repair_requests_remain_claimable_while_business_stays_queued(tmp_path,kind):
    path=tmp_path/'refresh.db'
    with sqlite3.connect(path)as db:
        db.execute('create table account_controls(account_uuid text,state text)')
        db.execute("insert into account_controls values('a','paused')")
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    owner=store.acquire_owner('a','binding','owner')
    original=store.submit('a','binding','maintenance','original',{},1000)
    repair=store.submit('a','binding',kind,'repair',{},200)
    install(NS(store=store,account_id='a'),NS(manual_tasks={},console_tasks={}),path=path)
    assert store.claim_next('a','binding','owner',owner['generation'])['command_id']==repair['command_id']
    assert store.get(original['command_id'])==original


def test_unreadable_control_does_not_claim_ordinary_maintenance(tmp_path):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    owner=store.acquire_owner('a','binding','owner')
    original=store.submit('a','binding','maintenance','original',{})
    install(NS(store=store,account_id='a'),NS(manual_tasks={},console_tasks={}),path=tmp_path/'absent.db')
    assert store.claim_next('a','binding','owner',owner['generation'])is None
    assert store.get(original['command_id'])==original
