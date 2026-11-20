from types import SimpleNamespace as NS
import pytest


@pytest.mark.parametrize('permit', [False, True])
def test_explicit_window_only_never_reaches_automatic_handback(monkeypatch, permit):
    from src.operations_accounts import clear_feed_resume as feed
    command = {'state': 'waiting_human', 'account_id': 'a',
        'payload': {'allow_automatic_resume': permit}, 'result': {'target': {'source': 'recommend_feed'}}}
    touched = []
    monkeypatch.setattr(feed, 'allowed', lambda *a: touched.append('preferences') or False)
    actor = NS(store=NS(get=lambda _: command))
    resource = NS(account_uuid='a',manual_tasks={'original':'tab'},console_tasks={})
    feed.poll(actor, resource)
    assert touched == (['preferences'] if permit else [])


def test_queue_binds_no_resume_to_new_original_request(monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    monkeypatch.setattr(bridge, '_runtime', lambda:NS(resolve=lambda *a,**k:NS(account_uuid='a')))
    monkeypatch.setattr(bridge, '_window_commands', lambda *a:[])
    monkeypatch.setattr(bridge, '_manual_public', lambda c:c)
    calls=[]
    def submit(account, kind, payload, key, priority):
        calls.append(payload)
        return {'command_id':'new-original','payload':payload}
    monkeypatch.setattr(bridge, '_submit', submit)
    receipt=bridge.queue_manual_window('a','one','confirmed-user',allow_automatic_resume=False)
    assert receipt['command_id']=='new-original'
    assert calls==[{'requested_by':'confirmed-user','incident_id':None,'allow_automatic_resume':False}]
