import io
from types import SimpleNamespace as NS
import pytest

from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.manual_visibility_deployment import close_for_upgrade


@pytest.mark.parametrize('case',['normal','not_requested','other_tab','other_human','save_failed','bad_exit'])
def test_display_upgrade_saves_exits_once_without_identity_or_resume(tmp_path,monkeypatch,case):
    store=BrowserControlStore(tmp_path/'browser.db',clock=lambda:1000)
    owner=store.acquire_owner('a','binding','owner')
    task=store.submit('a','binding','manual','manual',{})
    store.claim_next('a','binding','owner',owner['generation'])
    receipt={'tab_id':'tab','current_verification':{'blocking':True,'surface_state':'challenge_ready'}}
    store.transition(task['command_id'],'owner',owner['generation'],'waiting_human',result=receipt)
    config={'account_id':'a','owner_id':'owner','generation':owner['generation'],'manual_id':task['command_id'],
        'purpose':'repair_invisible_manual_window','user_statement':'different'if case=='not_requested'else'看不到 Chrome 处理窗口'}
    stream=io.BytesIO();events=[]
    process=NS(pid=12345,stdin=stream,wait=lambda timeout:1 if case=='bad_exit'else 0)
    tabs=[{'tab_id':'tab','role':'manual','closed':False}]
    if case=='other_tab':tabs.append({'tab_id':'user-tab','role':'default','closed':False,'url':'https://example.com'})
    session=NS(_proc=process,config=NS(storage_state_path='bound-original-state'),window_status=lambda:{'tabs':tabs},
        _send=lambda cmd:events.append(cmd['action'])or{'state_saved':case!='save_failed'})
    resource=NS(session=session,manual_tasks={task['command_id']:'tab'},console_tasks={'other':'tab2'}if case=='other_human'else{},
        shutdown=lambda:events.append('cleanup'))
    actor=NS(store=store,account_id='a',owner_id='owner',generation=owner['generation'],_stack=[],
        _assert_thread=lambda:None,_check_owner=lambda:None)
    monkeypatch.setattr('psutil.Process',lambda pid:NS(children=lambda recursive:[],create_time=lambda:1))
    if case=='bad_exit':
        with pytest.raises(RuntimeError):close_for_upgrade(actor,resource,config,tmp_path)
        assert not close_for_upgrade(actor,resource,config,tmp_path)
    else:
        assert close_for_upgrade(actor,resource,config,tmp_path) is (case=='normal')
    current=store.get(task['command_id'])
    if case=='normal':
        assert stream.getvalue()==b'{"action":"stop"}\n'
        assert current['state']=='succeeded'
        assert current['result']['identity_verified'] is False
        assert current['result']['account_pause_changed'] is False
        assert current['result']['original_window_receipt']==receipt
        assert events==['save_state','cleanup']
    else:
        assert current['state']=='waiting_human'
        if case!='bad_exit':assert not stream.getvalue()
