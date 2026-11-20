from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore
from src.operations_accounts import manual_window_visibility as visibility


@pytest.mark.parametrize('state', ['visible', 'hidden', 'closed', 'bad_bounds'])
def test_native_restore_uses_existing_target_and_confirms_readback(state):
    calls = []
    def send(method, params=None):
        calls.append((method, params))
        if method == 'Browser.getWindowForTarget':
            return {'windowId': 7}
        if method == 'Browser.getWindowBounds':
            return {'bounds': {'windowState': 'minimized' if state == 'bad_bounds' else 'normal'}}
        return {}
    cdp = NS(send=send, detach=lambda: calls.append(('detach', None)))
    page = NS(is_closed=lambda: state == 'closed',
        context=NS(new_cdp_session=lambda original: cdp),
        bring_to_front=lambda: calls.append(('bring_to_front', None)),
        evaluate=lambda script: state if state in {'visible','hidden'} else 'visible')
    if state == 'visible':
        assert visibility.restore_native_window(page)['restored'] is True
        assert all(params is None or params.get('windowId', 7) == 7 for _, params in calls)
        assert ('bring_to_front', None) in calls
    else:
        with pytest.raises(RuntimeError):
            visibility.restore_native_window(page)
    if state != 'closed':
        assert calls[-1] == ('detach', None)
    else:
        assert not calls


@pytest.mark.parametrize('change', ['', 'tab', 'owner', 'generation', 'account', 'state', 'headless', 'extra_params'])
def test_serial_actor_restores_only_original_manual_and_never_completes_it(tmp_path, monkeypatch, change):
    monkeypatch.setattr('src.operations_accounts.interactive_desktop.require_interactive_desktop', lambda: None)
    store = BrowserControlStore(tmp_path / 'browser.db', clock=lambda: 1000)
    calls = []
    page = NS(_cmd=lambda action: calls.append(action) or {'restored': True})
    resource = NS(manual_tasks={}, session=NS(config=NS(headless=False), get_page=lambda tab: page))
    original = store.submit('a', 'binding', 'manual', 'original-manual', {})
    actor = BrowserControlActor(store, 'a', 'binding', 'owner', {
        'manual': lambda ctx, payload: bridge.BrowserCommandResult('waiting_human', {'tab_id': 'manual-tab'}),
        'read': bridge._adapter_read}, context=resource)
    actor.run_next()
    resource.manual_tasks[original['command_id']] = 'manual-tab'
    before = store.get(original['command_id'])
    payload = {'method': visibility.METHOD, 'operation_profile': None, 'params': {
        'manual_id': original['command_id'], 'owner_id': actor.owner_id,
        'generation': actor.generation, 'tab_id': 'manual-tab'}}
    if change in {'tab', 'owner', 'generation'}:
        key = {'tab':'tab_id','owner':'owner_id','generation':'generation'}[change]
        payload['params'][key] = 'changed'
    elif change == 'extra_params':
        payload['params']['url'] = 'https://example.com'
    elif change == 'account':
        payload['params']['manual_id'] = store.submit('other', 'binding', 'manual', 'foreign', {})['command_id']
    elif change == 'state':
        store.complete_waiting(original['command_id'], actor.owner_id, actor.generation, {'window_closed': True})
        before = store.get(original['command_id'])
    elif change == 'headless':
        resource.session.config.headless = True
    request = store.submit('a', 'binding', 'read', 'display-once', payload, 300)
    try:
        result = actor.run_next()
        assert result['command_id'] == request['command_id']
        assert (result['state'] == 'succeeded') is (not change)
        assert calls == ([] if change else ['reveal_manual_window'])
        assert store.get(original['command_id']) == before
        if not change:
            assert result['result']['read_result']['identity_verified'] is False
            assert result['result']['read_result']['account_pause_changed'] is False
    finally:
        actor.stop_heartbeat()


def test_repeated_ui_display_request_reuses_one_queued_read(tmp_path, monkeypatch):
    store = BrowserControlStore(tmp_path / 'browser.db', clock=lambda: 1000)
    owner = store.acquire_owner('a','binding','owner')
    original = store.submit('a', 'binding', 'manual', 'manual', {'account_key': 'key'})
    store.claim_next('a','binding','owner',owner['generation'])
    store.transition(original['command_id'],'owner',owner['generation'],'waiting_human',result={'tab_id':'tab'})
    monkeypatch.setattr(bridge,'_store',lambda:store)
    monkeypatch.setattr(bridge,'_window_commands',lambda key,kind:store.commands_of_kind('a',kind))
    calls=[]
    def submit(key,kind,payload,idempotency,priority):
        calls.append(kind)
        return store.submit('a','binding',kind,idempotency,dict(payload,account_key=key,account_uuid='a'),priority)
    monkeypatch.setattr(bridge,'_submit',submit)
    first=visibility.queue('a','key');second=visibility.queue('a','key')
    assert first['command_id']==second['command_id']
    assert calls==['read']
    assert store.get(original['command_id'])['state']=='waiting_human'


@pytest.mark.parametrize('desktop,allowed', [('Default',True),('default',True),(None,True),('',False),('CodexSandboxDesktop-test',False),('Winlogon',False)])
def test_noninteractive_desktop_is_rejected_before_open_or_focus(monkeypatch,desktop,allowed):
    from src.operations_accounts import interactive_desktop
    monkeypatch.setattr(interactive_desktop,'current_desktop_name',lambda:desktop)
    if allowed:
        interactive_desktop.require_interactive_desktop()
    else:
        with pytest.raises(bridge.BrowserControlRejected) as error:
            interactive_desktop.require_interactive_desktop()
        assert error.value.code=='manual_window_noninteractive_desktop'


def test_manual_handler_never_opens_a_window_on_isolated_desktop(monkeypatch):
    from src.operations_accounts import interactive_desktop, manual_handling
    from src.scheduler import account_refresh
    monkeypatch.setattr(interactive_desktop,'current_desktop_name',lambda:'CodexSandboxDesktop-test')
    monkeypatch.setattr(account_refresh,'snapshot',lambda:{})
    monkeypatch.setattr(manual_handling,'_pause_for_handling',lambda *a:pytest.fail('not admitted'))
    monkeypatch.setattr(manual_handling,'resolve_manual_handling_target',lambda *a,**k:pytest.fail('not admitted'))
    resource=NS(account_uuid='a',account_key='key')
    with pytest.raises(bridge.BrowserControlRejected) as error:
        bridge._manual(NS(resource=resource),{})
    assert error.value.code=='manual_window_noninteractive_desktop'
