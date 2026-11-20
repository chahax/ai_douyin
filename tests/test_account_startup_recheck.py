from types import SimpleNamespace

import pytest

from src.scheduler import account_refresh as ar
from src.scheduler import account_startup_recheck as startup
from src.operations_accounts.browser_control import BrowserControlStore


@pytest.fixture
def setup(tmp_path,monkeypatch):
    path=tmp_path/'refresh.db'
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:2000)
    monkeypatch.setattr(ar,'time',SimpleNamespace(time=lambda:2000))
    with ar.connect(path) as db:
        ar._ensure_control(db,'a','one',500)
        ar._pause(db,'a','one','historical verification','human_required',600)
    return path,store


def request(setup,**kwargs):
    path,store=setup
    return startup.request_rechecks(path=path,store=store,boot_time=1000,now=2000,**kwargs)


def test_once_request_does_not_activate_until_same_identity_probe(setup):
    path,_=setup
    assert len(request(setup))==1
    assert not request(setup)
    control=ar.snapshot(path)['controls'][0]
    assert control['state']=='recovery_requested'
    token=ar._claim_recovery('a','one',now=2000,path=path)
    assert token
    assert ar._finish_recovery('a','one',token,healthy=True,status='active',path=path)
    assert ar.snapshot(path)['controls'][0]['state']=='active'
    with ar.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM account_startup_rechecks').fetchone()[0]==1
        assert db.execute('SELECT handled_by FROM account_handling_requests').fetchone()[0]=='automatic_startup_recheck'


@pytest.mark.parametrize('status',['human_required','verification_ui_unconfirmed','account_uuid_mismatch','recovery_probe_failed'])
def test_failed_probe_keeps_paused_and_does_not_loop_or_retry_after_service_restart(setup,status):
    path,store=setup
    assert request(setup)
    token=ar._claim_recovery('a','one',now=2000,path=path)
    assert not ar._finish_recovery('a','one',token,healthy=False,status=status,path=path)
    assert ar.snapshot(path)['controls'][0]['state']=='paused'
    assert not request(setup)
    # Even a second host boot inside 24h does not consume another attempt.
    assert not startup.request_rechecks(path=path,store=store,boot_time=3000,now=4000)


@pytest.mark.parametrize('state',['queued','running','paused','waiting_human','outcome_unknown'])
def test_original_browser_command_blocks_auto_probe(setup,state):
    path,store=setup
    command=store.submit('a','b','manual','old',{})
    with store._db(write=True) as db:
        db.execute('UPDATE browser_control_commands SET state=?',(state,))
    original=store.get(command['command_id'])
    assert not request(setup)
    assert store.get(command['command_id'])==original
    assert ar.snapshot(path)['controls'][0]['state']=='paused'


@pytest.mark.parametrize('code',['outcome_unknown','recovery_outcome_unknown','operator_paused','login_expired'])
def test_nontransient_or_operator_pause_is_not_auto_released(setup,code):
    path,_=setup
    with ar.connect(path) as db:
        db.execute('UPDATE account_controls SET error_code=?',(code,))
    assert not request(setup)


def test_boot_grace_and_current_boot_pause_are_not_rechecked(setup):
    path,store=setup
    assert not startup.request_rechecks(path=path,store=store,boot_time=1800,now=2000)
    with ar.connect(path) as db:db.execute('UPDATE account_controls SET updated_at=1500')
    assert not request(setup)


def test_read_failure_is_error_not_permission_to_probe(setup,monkeypatch):
    _,store=setup
    def fail(*args,**kwargs):raise OSError('unavailable')
    monkeypatch.setattr(store,'_db',fail)
    with pytest.raises(OSError):request(setup)


def test_new_operator_pause_invalidates_success_of_inflight_recheck(setup):
    path,_=setup
    assert request(setup)
    token=ar._claim_recovery('a','one',now=2000,path=path)
    with ar.connect(path) as db:ar._pause(db,'a','one','operator stop','operator_paused',2100)
    assert not ar._finish_recovery('a','one',token,healthy=True,status='active',path=path)
    assert ar.snapshot(path)['controls'][0]['error_code']=='operator_paused'
