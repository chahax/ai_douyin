import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected
from src.operations_accounts.fanqie_account_control import FanqieAccounts, run_owner, write_json
from src.platform_adapter.fanqie_identity import identity_from_response, FanqieIdentityObserver, HOME

URL = 'https://kol.fanqieopen.com/api/platform/user/info/v1'


@pytest.mark.parametrize('suffix', ['v1','v:version','v%3Aversion','v%3aversion'])
def test_documented_literal_version_endpoint(suffix):
    evidence=identity_from_response('https://kol.fanqieopen.com/api/platform/user/info/'+suffix,200,{'code':0,'data':{'uid':'12345'}},10)
    assert evidence['verified'] and evidence['platform_identity_key']=='uid:12345'


@pytest.fixture
def accounts(tmp_path):
    BrowserControlStore(tmp_path / 'control.db')
    with sqlite3.connect(tmp_path / 'douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid,account_key,platform_identity_key,browser_environment_key,browser_profile_dir,created_at,platform,status)')
        for key in ('legal', 'novel'):
            db.execute('INSERT INTO account_runtime_bindings VALUES(?,?,?,?,?,?,?,?)', (key+'uuid',key,key+'id',key+'env',key+'profile','fixed','douyin','active'))
    a = FanqieAccounts(tmp_path/'control.db', tmp_path/'profiles', tmp_path/'evidence', tmp_path/'douyin.db')
    a.install()
    return a


def test_migration_and_environment_isolation(accounts):
    a = accounts
    first = a.create('小说番茄', 'novel')
    second = a.create('法律番茄', 'legal')
    assert a.create('重复点击', 'novel') == first
    assert first['profile_dir'] != second['profile_dir']
    assert a.install()['status'] == 'already_installed'
    assert len(list(a.evidence.glob('schema_backup_*.db'))) == 1


def test_concurrent_open_reuses_original_command(accounts):
    resource = accounts.create('小说', 'novel')['resource_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        commands = list(pool.map(lambda _: accounts.queue(resource), range(8)))
    assert len({c['command_id'] for c in commands}) == 1


def test_unbound_catalog_and_changed_link_block(accounts):
    env = accounts.create('小说', 'novel')
    with pytest.raises(ValueError, match='登录'):
        accounts.queue(env['resource_id'], 'fanqie_catalog')
    with sqlite3.connect(accounts.douyin_db) as db:
        db.execute("UPDATE account_runtime_bindings SET platform_identity_key='different' WHERE account_key='novel'")
    with pytest.raises(BrowserControlRejected, match='关联'):
        accounts.queue(env['resource_id'])


@pytest.mark.parametrize('url', ['https://evil.example/api/platform/user/info/v1', 'http://kol.fanqieopen.com/api/platform/user/info/v1', URL.replace('/v1','/other'), URL.replace('.com/', '.com:444/'), URL.replace('https://','https://user@')])
def test_identity_rejects_other_origins(url):
    assert identity_from_response(url, 200, {'code':0,'data':{'uid':'12345'}}, 10) is None


@pytest.mark.parametrize('body', [{'code':False,'data':{'uid':12345}}, {'code':1,'data':{'uid':12345}}, {'code':0,'data':{'nickname':'12345'}}, {'code':0,'data':{'uid':True}}, {'code':0,'data':{'uid':'invalid'}}])
def test_identity_requires_official_stable_id(body):
    assert not identity_from_response(URL,200,body,10)['verified']


def test_observer_stale_challenge_navigation_and_login_failure():
    callbacks = {}
    page = SimpleNamespace(url=HOME, main_frame=object(), on=lambda event,fn: callbacks.update({event:fn}), evaluate=lambda js:False)
    observer = FanqieIdentityObserver(page, clock=lambda:1000)
    response = SimpleNamespace(url=URL,status=200,request=SimpleNamespace(frame=page.main_frame),json=lambda:{'code':0,'data':{'uid':'12345','secret':'not_saved'}})
    observer.on_response(response)
    assert observer.observe()['platform_identity_key']=='uid:12345'
    assert 'secret' not in json.dumps(observer.observe())
    page.evaluate=lambda js:True
    assert not observer.observe()['verified']
    page.evaluate=lambda js:False
    observer.latest['observed_at']=0
    assert not observer.observe()['verified']
    observer.on_response(response)
    callbacks['framenavigated'](page.main_frame)
    assert not observer.observe()['verified']
    observer.on_response(response)
    response.status=401
    observer.on_response(response)
    assert not observer.observe()['verified']


class Session:
    def __init__(self, config, identity='uid:12345', verified=True, crash=False):
        self.config,self.identity,self.verified,self.crash = config,identity,verified,crash
        self.n=0; self.saved=0;self.stopped=False
    def get_page(self): return self
    def _cmd(self, action, **kwargs):
        if self.crash: raise RuntimeError('fixture browser crash')
        return {'evidence':dict(verified=self.verified, platform_identity_key=self.identity, observed_at=time.time(), identity_source='platform_account_id', challenge=False)}
    def goto(self,*args,**kwargs): pass
    def window_status(self):
        self.n+=1
        return {'open': self.n<=1}
    def save_storage_state(self): self.saved+=1
    def wait_for_timeout(self,n): pass
    def stop(self): self.stopped=True
    def evaluate(self,js): return 'fixture book catalogue'


def login(accounts, **kwargs):
    env=accounts.create('小说','novel')
    cmd=accounts.queue(env['resource_id'])
    instances=[]
    def factory(config):
        s=Session(config,**kwargs); instances.append(s); return s
    result=run_owner(env['resource_id'],accounts,session_factory=factory,max_login_seconds=2)
    return env,cmd,result,instances[0]


def test_login_confirm_reuse_and_guarded_catalog(accounts):
    env,cmd,result,session=login(accounts)
    assert result['state']=='succeeded'
    assert session.stopped and session.saved and session.config.mute_audio and not session.config.headless
    assert accounts.bindings().get(env['resource_id']) is None
    binding=accounts.confirm(cmd['command_id'],'uid:12345','fixture explicit admin')
    assert accounts.confirm(cmd['command_id'],'uid:12345','fixture explicit admin')==binding
    catalogue=accounts.queue(env['resource_id'],'fanqie_catalog')
    result=run_owner(env['resource_id'],accounts,session_factory=Session)
    assert result['state']=='succeeded'
    assert 'catalog_evidence' in result['result']
    assert catalogue['command_id']!=cmd['command_id']


def test_unknown_worker_cannot_be_reopened(accounts):
    env,cmd,result,session=login(accounts,crash=True)
    assert result['state']=='outcome_unknown' and session.stopped
    assert accounts.queue(env['resource_id'])['command_id']==cmd['command_id']
    with pytest.raises(ValueError): accounts.confirm(cmd['command_id'],'uid:12345','fixture')


def test_unverified_login_cannot_bind(accounts):
    env,cmd,result,session=login(accounts,verified=False)
    assert result['state']=='failed'
    with pytest.raises(ValueError): accounts.confirm(cmd['command_id'],'uid:12345','fixture')


def test_pending_command_blocks_confirmation(accounts):
    env,cmd,result,session=login(accounts)
    accounts.queue(env['resource_id'])
    with pytest.raises(BrowserControlRejected,match='pending_platform'):
        accounts.confirm(cmd['command_id'],'uid:12345','fixture explicit')


def test_wrong_or_stale_identity_rejected(accounts):
    env,cmd,result,session=login(accounts)
    with pytest.raises(ValueError): accounts.confirm(cmd['command_id'],'uid:other','fixture')
    original=accounts.bindings
    def stale_repo():
        repo=original();repo.clock=lambda:time.time()+301;return repo
    accounts.bindings=stale_repo
    with pytest.raises(BrowserControlRejected,match='stable_platform'):
        accounts.confirm(cmd['command_id'],'uid:12345','fixture')


def test_bound_identity_change_stops_read(accounts):
    env,cmd,result,session=login(accounts)
    accounts.confirm(cmd['command_id'],'uid:12345','fixture explicit')
    accounts.queue(env['resource_id'],'fanqie_catalog')
    result=run_owner(env['resource_id'],accounts,session_factory=lambda c:Session(c,identity='uid:99999'))
    assert result['state']=='failed' and result['result']['reason']=='platform_identity_mismatch'


@pytest.mark.parametrize('role,user', [('viewer','someone'),('editor','someone'),('admin','')])
def test_web_mutations_require_authenticated_admin(accounts,monkeypatch,role,user):
    from src.web import fanqie_accounts_panel as panel
    monkeypatch.setattr(panel,'get_current_role',lambda:role)
    monkeypatch.setattr(panel,'get_current_user',lambda:user)
    with pytest.raises(PermissionError): panel.mutate(accounts,'create',label='x',douyin_account='novel')


def test_legacy_public_cache_rejected():
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    with pytest.raises(RuntimeError,match='专属'):
        FanqiePromotionService()._open_browser_cache_session(True)


def test_web_page_shows_dedicated_environment_without_opening_on_refresh(accounts,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src.web import fanqie_accounts_panel as panel
    env=accounts.create('小说番茄','novel')
    monkeypatch.setattr(panel,'FanqieAccounts',lambda:accounts)
    monkeypatch.setattr(panel,'get_current_user',lambda:'fixture admin')
    monkeypatch.setattr(panel,'get_current_role',lambda:'admin')
    opened=[]
    monkeypatch.setattr(panel,'launch_worker',lambda command,a:opened.append(command))
    app=AppTest.from_string('from src.web.fanqie_accounts_panel import render_page\nrender_page()').run(timeout=30)
    assert not app.exception and not opened
    assert any(env['profile_dir'] in item.value for item in app.caption)
    next(button for button in app.button if button.label=='打开／复用专属登录窗口').click().run(timeout=30)
    assert not app.exception and len(opened)==1
    assert accounts.latest_command(env['resource_id'])['command_id']==opened[0]['command_id']


def test_real_worker_identity_rpc_is_fail_closed_on_local_page(tmp_path):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    s=BrowserSession(BrowserSessionConfig(base_url='about:blank',home_url='about:blank',user_data_dir=str(tmp_path/'profile'),storage_state_path=str(tmp_path/'state.json'),headless=True,mute_audio=True,browser_channel='chrome'))
    try:
        page=s.get_page()
        evidence=page._cmd('fanqie_identity',reset=True)['evidence']
        assert evidence['verified'] is False and evidence['challenge'] is False
        assert s.window_status()['open']
    finally:
        s.stop()
