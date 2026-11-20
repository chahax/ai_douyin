"""Native sync/provider wiring with isolated owner DB and evidence fixtures."""
from types import SimpleNamespace as NS

import pytest

from test_fanqie_managed_promotion_v1 import accounts,Session,row
from test_fanqie_promotion_identity_v2 import make_case,save
from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from src.operations_accounts.fanqie_account_control import run_owner
from src.operations_accounts.browser_control import BrowserControlStore
from src.services import fanqie_promotion_identity_v2 as native


def real_fixture_snapshot(folder,subject):
    case=make_case(folder,identity=subject['platform_identity_key'])
    case['subject']=subject
    legacy=case['legacy'];source={k:subject[k] for k in native.SCOPE}
    source.update(observed_at=case['at'],identity_verified=True,challenge=False)
    evidence=native._read(legacy['evidence_ref']);evidence['subject']=source
    source_ref=save(folder/'DOM.json',evidence)
    legacy=managed.normalise_snapshot(evidence['raw'],**source,evidence_ref=source_ref)
    old_ref=save(folder/'LEGACY.json',legacy)
    case['observation']['subject']=subject
    obs_ref=save(folder/'OBSERVATION.json',case['observation'])
    return native.prepare_snapshot(old_ref,obs_ref,folder/'native',managed_subject=subject)


def test_native_capture_auto_request_only_uses_current_observed_paths(tmp_path,monkeypatch):
    from src.platform_adapter import fanqie_promotion_observation_diagnostic_v1 as diagnostic
    from src.platform_adapter.fanqie_promotion_observer_v1 import RESOURCE_JS
    case=make_case(tmp_path/'fixture');calls=[];guards=[]
    page=NS(url='https://kol.fanqieopen.com/page/promotion-list',evaluate=lambda js:[
        dict(origin='https://kol.fanqieopen.com',path=path,initiator_type='fetch')
        for path in (native.PROMOTION_ENDPOINT,native.ENUM_ENDPOINT)])
    def observation(actual,**kwargs):
        assert actual is page
        req=native._read(kwargs['observer_request']);calls.append(req)
        kwargs['guard']()
        return dict(status='observed',observer_stop_confirmed=True,evidence=dict(observation=case['observation_ref']))
    monkeypatch.setattr(diagnostic,'run_observation',observation)
    ref=managed.capture_native_snapshot(page,env={k:case['subject'][k] for k in ('resource_id','binding_version')},
        managed_subject=case['subject'],identity=lambda:None,guard=lambda:guards.append(1),
        evidence_directory=tmp_path/'sync',legacy_snapshot_ref=case['legacy_ref'])
    assert native.validate_snapshot(native._read(ref))['rows'][0]['publishable']
    assert calls[0]['endpoint_paths']==[native.PROMOTION_ENDPOINT,native.ENUM_ENDPOINT] and len(guards)>=3
    page.evaluate=lambda js:[]
    with pytest.raises(Exception,match='元数据资源'):
        managed.capture_native_snapshot(page,env={k:case['subject'][k] for k in ('resource_id','binding_version')},
            managed_subject=case['subject'],identity=lambda:None,guard=lambda:None,
            evidence_directory=tmp_path/'missing',legacy_snapshot_ref=case['legacy_ref'])
    assert len(calls)==1


def test_opt_in_v2_owner_returns_native_snapshot_and_keeps_default_payload(accounts,monkeypatch):
    a,env=accounts;Session.rows=[row()];calls=[]
    def capture(page,**kwargs):
        calls.append(kwargs)
        return real_fixture_snapshot(kwargs['evidence_directory']/'fixture',kwargs['managed_subject'])
    monkeypatch.setattr(managed,'capture_native_snapshot',capture)
    command=a.queue(env['resource_id'],'fanqie_promotion_list',snapshot_version='v2')
    assert command['payload']['snapshot_version']=='v2'
    result=run_owner(env['resource_id'],a,session_factory=Session)
    snap=native.validate_snapshot(native._read(result['result']['promotion_snapshot']))
    assert result['state']=='succeeded' and result['result']['snapshot_version']=='v2' and len(calls)==1
    assert snap['schema']==native.SCHEMA and 'platform_task_id' not in snap['rows'][0]
    original=a.queue(env['resource_id'],'fanqie_promotion_list')
    assert 'snapshot_version' not in original['payload']
    run_owner(env['resource_id'],a,session_factory=Session)
    assert len(calls)==1 and Session.submit_count==0
    with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_login',snapshot_version='v2')


def test_v3_provider_uses_separate_tab_and_forced_refresh_not_form_page(accounts,monkeypatch):
    from src.operations_accounts import fanqie_backfill_control as backfill
    a,env=accounts;calls=[];receipts=[];tabs=[]
    class Tab:
        def __init__(self,parent,role):self.parent=parent;self.role=role;self.url='about:blank';self.gotos=[]
        def goto(self,url,**kwargs):self.url=url;self.gotos.append(url)
        def _cmd(self,action,**kwargs):
            return dict(url=self.url) if action=='current_url' else self.parent._cmd(action,**kwargs)
    class OwnedSession(Session):
        def new_tab(self,role):
            tab=Tab(self,role);tabs.append(tab);return tab
    def capture(page,**kwargs):
        calls.append((page.page,kwargs))
        return real_fixture_snapshot(kwargs['evidence_directory']/'fixture',kwargs['managed_subject'])
    monkeypatch.setattr(managed,'capture_native_snapshot',capture)
    def factory(accounts,environment,*,page_provider,probe_provider,ledger_path,native_snapshot_provider):
        def handler(ctx,payload):
            form=page_provider(ctx,'https://kol.fanqieopen.com/page/batch-history')
            original=form.page.url
            receipts.append(native_snapshot_provider(ctx))
            receipts.append(native_snapshot_provider(ctx))
            for phase in ('pre_submit','post_submit','reconcile'):
                receipts.append(native_snapshot_provider(ctx,phase=phase,force_refresh=True))
                assert form.page.url==original
            from src.operations_accounts.browser_control import BrowserCommandResult
            return BrowserCommandResult('succeeded',dict(test_read_only=True))
        return dict(fanqie_backfill_reconcile=handler)
    monkeypatch.setattr(backfill,'build_managed_backfill_handlers',factory)
    command=BrowserControlStore(a.db).submit(env['resource_id'],env['binding_version'],'fanqie_backfill_reconcile',
        'native-provider-fixture',dict(environment_key=env['environment_key'],binding_uuid='fixture',manifest_sha256='fixture'))
    result=run_owner(env['resource_id'],a,session_factory=OwnedSession)
    assert result['state']=='succeeded' and receipts[0]==receipts[1]
    assert len({ref['path'] for ref in receipts})==4 and len(calls)==4 and len(tabs)==1
    assert tabs[0].role=='native-promotion-evidence'
    assert all(page is tabs[0] for page,_ in calls)
    assert len(tabs[0].gotos)==4 and Session.submit_count==0
