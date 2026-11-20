import json
import pytest
from scripts import dispose_recovery_probe_20261020 as repair
from src.operations_accounts.browser_control import BrowserControlStore


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    store = BrowserControlStore(tmp_path/'control.db')
    monkeypatch.setattr(repair,'ACCOUNT','fixture')
    monkeypatch.setattr(repair,'OWNER','fixture-owner')
    request = store.submit('fixture','binding','recovery','original',{})
    monkeypatch.setattr(repair,'CID',request['command_id'])
    owner = store.acquire_owner('fixture','binding','fixture-owner')
    store.claim_next('fixture','binding','fixture-owner',owner['generation'])
    store.transition(request['command_id'],'fixture-owner',owner['generation'],'outcome_unknown',
        error_code='handler_exception:AccountRuntimeError')
    with store._db(write=True) as db:
        db.execute('UPDATE browser_control_owners SET generation=35')
        db.execute('UPDATE browser_control_commands SET generation=35')
        original = dict(db.execute('SELECT * FROM browser_control_commands').fetchone())
    auth = dict(user_statement='fixture approval',command_id=repair.CID,cancel_unknown_probe=True)
    facts = dict.fromkeys(('process_exited','profile_exited','leases_empty',
        'manual_windows_closed','pause_preserved','only_original_unresolved'), True)
    return store, original, auth, facts


def test_disposal_retains_original_unknown_without_claiming_identity_verified(prepared):
    store, original, auth, facts = prepared
    with store._db(write=True) as db:
        result = repair.dispose(db,store,original,auth,facts)
    assert result['original_outcome_known'] is False
    assert result['task_replayed'] is False
    with store._db() as db:
        audit = db.execute('SELECT * FROM browser_control_operator_disposals').fetchone()
        assert json.loads(audit['original_command']) == original
        current = dict(db.execute('SELECT * FROM browser_control_commands').fetchone())
        for key in original.keys()-{'state','error_code','result','updated_at'}:
            assert current[key] == original[key]
        assert current['state'] == 'failed'
        assert current['error_code'] == 'operator_cancelled_unknown_probe'
        assert db.execute('SELECT state FROM browser_control_owners').fetchone()[0] == 'released'


@pytest.mark.parametrize('change', ['approval','snapshot','live_process','another_task','owner'])
def test_disposal_refuses_changed_scope_and_preserves_original(prepared, change):
    store, original, auth, facts = prepared
    if change == 'approval': auth['cancel_unknown_probe'] = False
    if change == 'snapshot': original = dict(original,priority=999)
    if change == 'live_process': facts['process_exited'] = False
    if change == 'another_task': store.submit('fixture','binding','recovery','another',{})
    if change == 'owner':
        with store._db(write=True) as db:
            db.execute('UPDATE browser_control_owners SET generation=36')
    before = store.get(repair.CID)
    with pytest.raises(RuntimeError):
        with store._db(write=True) as db:
            repair.dispose(db,store,original,auth,facts)
    assert store.get(repair.CID) == before
