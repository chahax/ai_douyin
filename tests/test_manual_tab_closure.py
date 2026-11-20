from types import SimpleNamespace as NS
import pytest

from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.manual_tab_closure import settle_closed_manual_tabs


@pytest.mark.parametrize('remaining',['blank','unclaimed','manual'])
def test_only_original_closed_manual_tab_settles_and_other_work_is_preserved(tmp_path,remaining):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    store.acquire_owner('a','binding','backend:123:abc')
    task=store.submit('a','binding','manual','original',{},200)
    store.claim_next('a','binding','backend:123:abc',1)
    store.transition(task['command_id'],'backend:123:abc',1,'waiting_human',result={'tab_id':'manual-tab'})
    events=[]
    resource=NS(manual_tasks={task['command_id']:'manual-tab'},console_tasks={},headless=False,
        session=NS(save_storage_state=lambda:events.append('saved')),
        shutdown=lambda:events.append('shutdown'))
    actor=NS(store=store,owner_id='backend:123:abc',generation=1)
    other={'tab_id':'other','role':'default'if remaining=='blank'else remaining,
           'url':'about:blank'if remaining=='blank'else'https://www.douyin.com/','closed':False}
    status={'context_closed':False,'tabs':[{'tab_id':'manual-tab','role':'manual','closed':True},other]}
    assert settle_closed_manual_tabs(actor,resource,status) is (remaining=='blank')
    assert resource.manual_tasks=={}
    result=store.get(task['command_id'])['result']
    assert result['window_closed'] and result['identity_verified'] is False and result['account_pause_changed'] is False
    assert events==(['saved','shutdown']if remaining=='blank'else['saved'])


@pytest.mark.parametrize('change',['open','wrong_tab','wrong_role','no_evidence','wrong_owner'])
def test_closed_window_claim_alone_or_foreign_tab_never_settles(tmp_path,change):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    store.acquire_owner('a','binding','backend:123:abc')
    task=store.submit('a','binding','manual','original',{},200)
    store.claim_next('a','binding','backend:123:abc',1)
    store.transition(task['command_id'],'backend:123:abc',1,'waiting_human',result={'tab_id':'manual-tab'})
    resource=NS(manual_tasks={task['command_id']:'manual-tab'},console_tasks={},session=NS())
    actor=NS(store=store,owner_id='foreign'if change=='wrong_owner'else'backend:123:abc',generation=1)
    row={'tab_id':'wrong'if change=='wrong_tab'else'manual-tab','role':'unclaimed'if change=='wrong_role'else'manual','closed':change!='open'}
    assert not settle_closed_manual_tabs(actor,resource,{'tabs':[]if change=='no_evidence'else[row]})
    assert store.get(task['command_id'])['state']=='waiting_human'
