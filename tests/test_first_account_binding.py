from dataclasses import replace
from types import SimpleNamespace as NS
import pytest

from src.operations_accounts import AccountProfile,AccountProfileRepository,AccountBindingRepository,stable_account_uuid,DouyinIdentity
from src.operations_accounts import runtime as mod
from src.operations_accounts.browser_control import BrowserControlStore,BrowserControlRejected
from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL','1')
    browser=tmp_path/'account_browser_control.db'
    monkeypatch.setenv('ACCOUNT_BROWSER_CONTROL_DB',str(browser))
    profiles=AccountProfileRepository(tmp_path/'accounts.db')
    profile=profiles.save(AccountProfile(account_key='novel',account_uuid=stable_account_uuid('novel'),display_name='novel',domain_strategy_id='novel_promotion'))
    bindings=AccountBindingRepository(profiles.db_path)
    runtime=mod.AccountRuntimeService(profile_repository=profiles,binding_repository=bindings)
    prepared=mod.PreparedBrowserEnvironment(profile,'environment',str(tmp_path/'profile'),str(tmp_path/'state.json'))
    monkeypatch.setattr(runtime,'prepare_browser_environment',lambda _:prepared)
    sessions=[]
    def build(*args,**kwargs):
        s=BrowserSession(BrowserSessionConfig(base_url='http://127.0.0.1',home_url='http://127.0.0.1',
            user_data_dir=prepared.browser_profile_dir,storage_state_path=prepared.storage_state_path,headless=kwargs['headless']))
        sessions.append(s);return s
    monkeypatch.setattr(mod.DouyinWarmupService,'build_browser_session',build)
    return runtime,prepared,bindings,BrowserControlStore(browser),sessions


def test_managed_mode_first_login_and_probe_share_exclusive_scope(setup):
    runtime,p,b,s,sessions=setup
    with pytest.raises(BrowserControlRejected):p.create_browser_session()
    with runtime.manual_browser_environment('novel'):
        p.create_browser_session()
        runtime.verifier.probe=lambda session:DouyinIdentity(nickname='novel',public_uid='123')
        identity=runtime.probe_unbound_identity('novel')
        assert identity.public_uid=='123' and len(sessions)==2
        assert b.get_optional('novel') is None
    assert not b.get_runtime_state(p.account_uuid).lock_owner
    with pytest.raises(BrowserControlRejected):p.create_browser_session()


@pytest.mark.parametrize('change',['account','path','state_path','environment'])
def test_scope_cannot_open_other_environment(setup,change):
    runtime,p,b,s,sessions=setup
    with runtime.manual_browser_environment('novel'):
        other=replace(p,**{'account':{'profile':replace(p.profile,account_key='other')},'path':{'browser_profile_dir':'other'},
            'state_path':{'storage_state_path':'other'},'environment':{'browser_environment_key':'other'}}[change])
        with pytest.raises(mod.AccountRuntimeError):other.create_browser_session()
    assert not sessions


@pytest.mark.parametrize('state',['queued','running','waiting_human','outcome_unknown'])
def test_pending_task_prevents_bootstrap(setup,state):
    runtime,p,b,s,sessions=setup
    c=s.submit(p.account_uuid,'b','manual','original',{})
    with s._db(write=True) as db:db.execute('UPDATE browser_control_commands SET state=?',(state,))
    with pytest.raises(mod.AccountRuntimeError,match='未打开新窗口'):
        with runtime.manual_browser_environment('novel'):pytest.fail('must block')
    assert not sessions and s.get(c['command_id'])['state']==state


def test_binding_created_during_login_cannot_bypass_managed_path(setup):
    runtime,p,b,s,sessions=setup
    with runtime.manual_browser_environment('novel'):
        b.bind(p.profile,DouyinIdentity(nickname='novel',public_uid='123'),browser_environment_key=p.browser_environment_key,
            browser_profile_dir=p.browser_profile_dir,storage_state_path=p.storage_state_path,confirmed_by='admin')
        with pytest.raises(mod.AccountRuntimeError):p.create_browser_session()
    with runtime.manual_browser_environment('novel'):
        with pytest.raises(BrowserControlRejected):p.create_browser_session()


def test_expired_manual_lease_stops_session_creation(setup):
    runtime,p,b,s,sessions=setup
    with runtime.manual_browser_environment('novel'):
        with b.connection() as db:db.execute("UPDATE account_runtime_state SET lock_expires_at='2000-01-01T00:00:00+00:00'")
        with pytest.raises(mod.AccountRuntimeError):p.create_browser_session()
    assert not sessions


def test_mutating_prepared_environment_does_not_mutate_scope(setup):
    runtime,p,b,s,sessions=setup
    with runtime.manual_browser_environment('novel'):
        p.browser_profile_dir='different'
        with pytest.raises(mod.AccountRuntimeError):p.create_browser_session()
    assert not sessions


def test_actual_chrome_bootstrap_uses_isolated_profile(setup):
    runtime,p,b,s,sessions=setup
    with runtime.manual_browser_environment('novel'):
        session=p.create_browser_session(headless=True)
        try:
            session._start()
            assert session.active and session._worker_stage=='ready'
            assert session.list_tabs()
        finally:session.stop()
    assert b.get_optional('novel') is None
