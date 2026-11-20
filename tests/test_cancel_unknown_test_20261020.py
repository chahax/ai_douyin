import json

import pytest

from scripts import cancel_unknown_test_20261020 as repair
from src.operations_accounts.browser_control import BrowserControlStore


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    store=BrowserControlStore(tmp_path/'control.db')
    monkeypatch.setattr(repair,'ACCOUNT','fixture')
    monkeypatch.setattr(repair,'OWNER','fixture-owner')
    request=store.submit('fixture','binding','maintenance','original',
        {'options':{'authorization_reference':'local test, no network'}})
    monkeypatch.setattr(repair,'CID',request['command_id'])
    owner=store.acquire_owner('fixture','binding','fixture-owner')
    store.claim_next('fixture','binding','fixture-owner',owner['generation'])
    store.transition(request['command_id'],'fixture-owner',owner['generation'],'outcome_unknown')
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_owners SET generation=34")
        db.execute("UPDATE browser_control_commands SET generation=34")
        original=dict(db.execute('SELECT * FROM browser_control_commands').fetchone())
    auth=dict(user_response='取消',command_id=repair.CID)
    facts=dict.fromkeys(('old_process_absent','profile_absent','leases_empty','manual_windows_closed','pause_preserved'),True)
    return store,original,auth,facts


def test_exact_disposal_keeps_original_uncertainty_and_releases_only_owner(prepared):
    store,original,auth,facts=prepared
    with store._db(write=True) as db:
        result=repair.dispose(db,store,original,auth,facts)
    assert result['original_outcome_known'] is False
    assert result['task_replayed'] is False
    with store._db() as db:
        audit=db.execute('SELECT * FROM browser_control_operator_disposals').fetchone()
        assert json.loads(audit['original_command'])==original
        current=dict(db.execute('SELECT * FROM browser_control_commands').fetchone())
        for key in original.keys()-{'state','error_code','result','updated_at'}:
            assert current[key]==original[key]
        assert current['error_code']=='operator_cancelled_unknown_test'
        assert db.execute('SELECT state FROM browser_control_owners').fetchone()[0]=='released'


@pytest.mark.parametrize('change',['approval','snapshot','idle','another_task'])
def test_changed_or_incomplete_disposal_leaves_original_untouched(prepared,change):
    store,original,auth,facts=prepared
    if change=='approval': auth['user_response']=''
    if change=='snapshot': original=dict(original,priority=999)
    if change=='idle': facts['profile_absent']=False
    if change=='another_task': store.submit('fixture','binding','maintenance','another',{})
    before=store.get(repair.CID)
    with pytest.raises(RuntimeError):
        with store._db(write=True) as db:
            repair.dispose(db,store,original,auth,facts)
    assert store.get(repair.CID)==before
    with store._db() as db:
        assert db.execute('SELECT state FROM browser_control_owners').fetchone()[0]=='active'
