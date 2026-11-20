import io
from types import SimpleNamespace as NS
import pytest

from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.manual_environment_retirement import close_original_environment


@pytest.mark.parametrize('case',['normal','challenge','save_failed','bad_exit','other_human','not_requested'])
def test_owner_graceful_exit_never_launders_identity_or_kills_processes(tmp_path,monkeypatch,case):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    store.acquire_owner('a','binding','backend:123:abc')
    task=store.submit('a','binding','manual','manual',{},200)
    store.claim_next('a','binding','backend:123:abc',1)
    store.transition(task['command_id'],'backend:123:abc',1,'waiting_human',result={'tab_id':'tab'})
    config={'manual_id':task['command_id'],'user_statement':'已关闭','close_original_environment':case!='not_requested'}
    stream=io.BytesIO();events=[]
    process=NS(pid=12345,stdin=stream,wait=lambda timeout:1 if case=='bad_exit'else 0)
    session=NS(_proc=process,config=NS(storage_state_path='original-state'),
        window_status=lambda:{'tabs':[{'tab_id':'tab','role':'manual','closed':False}]},get_page=lambda tab:object(),
        _send=lambda cmd:events.append(cmd['action'])or{'state_saved':case!='save_failed'})
    resource=NS(session=session,manual_tasks={task['command_id']:'tab'},console_tasks={'other':'tab2'}if case=='other_human'else{},
                shutdown=lambda:events.append('normal-cleanup'))
    actor=NS(store=store,account_id='a',owner_id='backend:123:abc',generation=1,_stack=[],
             _assert_thread=lambda:None,_check_owner=lambda:None)
    monkeypatch.setattr('src.platform_adapter.douyin_challenge.confirmed_douyin_challenge',
        lambda page:{'blocking':case=='challenge','surface_state':'challenge_ready'if case=='challenge'else'clear'})
    monkeypatch.setattr('psutil.Process',lambda pid:NS(children=lambda recursive:[]))
    if case=='bad_exit':
        with pytest.raises(RuntimeError):close_original_environment(actor,resource,config,tmp_path)
        assert not close_original_environment(actor,resource,config,tmp_path)  # No repeat stop after unknown outcome.
    else:
        assert close_original_environment(actor,resource,config,tmp_path) is (case=='normal')
    current=store.get(task['command_id'])
    if case=='normal':
        assert stream.getvalue()==b'{"action":"stop"}\n'
        assert current['state']=='succeeded' and current['result']['window_closed'] and current['result']['identity_verified'] is False
        assert events==['save_state','normal-cleanup']
    else:
        assert current['state']=='waiting_human'
        if case!='bad_exit':assert not stream.getvalue()
