"""Managed-owner black boxes with fake pages only; no live platform actions."""
from copy import deepcopy
import json
import sqlite3
import time
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import fanqie_managed_promotion_v1 as p
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected
from src.operations_accounts.fanqie_account_control import FanqieAccounts,run_owner,write_json
from src.platform_adapter.fanqie_list_filter_inventory_v1 import LIST_FILTER_INVENTORY_JS


def visible_list_filters():
    """The fixture list has a table but no rendered filter controls."""
    return dict(schema='fanqie_visible_list_filters/v1',controls=[],visible_control_count=0,
        truncated=False,input_values_read=False,filter_changed=False,request_query_read=False,
        all_statuses_included=None,completeness='unknown',
        limitations=['Visible controls only; defaults and server-side filters are not inferred.'])


def row(**updates):
    value=dict(platform_task_id='task-7',book_id='1234567890123456789',book_name='准确书名',alias_id='alias-8',
        alias='准确推广词',promotion_path='别名推广',publish_type='AIGC',alias_status='生效中',book_status='正常',
        valid_from='2026-01-01 00:00:00',valid_until='2027-01-01 00:00:00',published_links=[],fill_status='未填写',
        identity_attributes=[dict(name='data-task-id',value='task-7'),dict(name='data-alias-id',value='alias-8'),
                             dict(name='data-promotion-path',value='别名推广')])
    value.update(updates);return value


class Session:
    rows=[];submit_count=0;crash_on_submit=False;fence_on_submit=False;instances=[]
    def __init__(self,config):
        self.config=config;self.n=0;self.saved=0;self.stopped=False;self.url='';self.goto_calls=[]
        type(self).instances.append(self)
    def get_page(self):return self
    def new_tab(self,*args):return self
    def goto(self,url,**kwargs):self.url=url;self.goto_calls.append(url)
    def _cmd(self,action,**kwargs):
        if action=='current_url':return {'url':self.url}
        return dict(evidence=dict(verified=True,challenge=False,platform_identity_key='uid:12345',
            observed_at=time.time(),identity_source='platform_account_id',page_location=dict(origin='https://kol.fanqieopen.com')))
    def window_status(self):
        self.n+=1;return dict(open=self.n==1)
    def save_storage_state(self):self.saved+=1
    def wait_for_timeout(self,ms):pass
    def stop(self):self.stopped=True
    def evaluate(self,js):
        from src.platform_adapter.fanqie_promotion_observer_v1 import RESOURCE_JS
        from src.platform_adapter.fanqie_promotion_preflight_v1 import VIEW_JS
        if js==RESOURCE_JS:return []
        if js==LIST_FILTER_INVENTORY_JS:return visible_list_filters()
        if js==VIEW_JS:return dict(book_titles=['准确书名'],visible_modal_count=0,search_controls=[],filter_buttons=[])
        if js==p.LIST_JS:return dict(items=deepcopy(type(self).rows),table_ready=True,loading=False,has_next=False,empty_state=not type(self).rows)
        if 'const cards=' in js:
            intent=json.loads(js.split('const want=',1)[1].split(';const entryLabel=',1)[0])
            assert intent['book_id']==row()['book_id'] and intent['book_name']==row()['book_name']
            assert intent['promotion_path']=='别名推广'
            return dict(clicked=True,book_name=intent['book_name'],entry_label='别名推广')
        if 'buttons[0].click();' in js:
            type(self).submit_count+=1
            if type(self).fence_on_submit:raise BrowserControlRejected('owner_changed','fixture owner fenced')
            if type(self).crash_on_submit:raise TimeoutError('fixture response lost')
            type(self).rows=[row()];return dict(ready=True,submitted=True)
        return dict(ready=True,submitted=False)


@pytest.fixture
def accounts(tmp_path):
    BrowserControlStore(tmp_path/'control.db')
    with sqlite3.connect(tmp_path/'douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid,account_key,platform_identity_key,browser_environment_key,browser_profile_dir,created_at,platform,status)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?,?,?,?,?,?,?)',('novel-uuid','novel','novel-id','novel-env','profile','fixed','douyin','active'))
    accounts=FanqieAccounts(tmp_path/'control.db',tmp_path/'profiles',tmp_path/'evidence',tmp_path/'douyin.db')
    accounts.install();env=accounts.create('小说番茄','novel');cmd=accounts.queue(env['resource_id'])
    Session.rows=[];Session.submit_count=0;Session.crash_on_submit=False;Session.fence_on_submit=False;Session.instances=[]
    assert run_owner(env['resource_id'],accounts,session_factory=Session,max_login_seconds=1)['state']=='succeeded'
    accounts.confirm(cmd['command_id'],'uid:12345','fixture user')
    return accounts,env


@pytest.fixture
def exact_book_location(accounts,monkeypatch):
    """These owner units substitute search I/O; real freshness has DOM tests."""
    from src.platform_adapter import fanqie_exact_book_locator_v1 as locator
    calls=[]
    def locate(page,*,book_id,book_name,guard,checkpoint,search_allowed):
        assert book_id==row()['book_id'] and book_name==row()['book_name']
        assert search_allowed is True
        guard()
        assert page.url==p.CONTENT_URL
        result=dict(schema=locator.VERSION,book_id=book_id,book_name=book_name,
            status='located_after_exact_search',search_attempted=True,all_content_clicked=True,
            query_filled=True,enter_pressed=True,search_count=1,search_mode='exact_public_book_name',
            platform_book_availability=None,api_requests_issued=0,alias_filled=False,
            promotion_submitted=False,book_id_verification='requires_exact_modal_identity',
            result_freshness_verified=True,fixture_source='isolated_locator_edge_not_live_DOM')
        checkpoint('fixture_exact_search',result)
        guard()
        calls.append(dict(book_id=book_id,book_name=book_name,search_allowed=search_allowed))
        return result
    monkeypatch.setattr(locator,'locate_exact_book',locate)
    return calls


def request(accounts,env,**updates):
    intent=dict(resource_id=env['resource_id'],binding_version=env['binding_version'],platform_identity_key='uid:12345',
        **{k:row()[k] for k in ('book_id','book_name','alias','promotion_path','publish_type')})
    intent.update(updates)
    auth=write_json(accounts.evidence/'AUTH.json',dict(schema='fanqie_promotion_apply_authorization/v1',
        confirmed_by='user',intent=intent,max_submissions=1))
    return write_json(accounts.evidence/'REQUEST.json',dict(schema='fanqie_promotion_apply_request/v1',authorization=auth,**intent))


def test_native_ID_evidence_required_never_trust_prefilled_book_or_row_number():
    source=row(identity_attributes=[],identity_links=[],identity_columns=[])
    snap=p.normalise_snapshot(dict(items=[source],table_ready=True),resource_id='r',binding_version='v',platform_identity_key='i')
    item=snap['rows'][0]
    assert item['platform_task_id'] is None and item['alias_id'] is None and item['promotion_path'] is None
    assert item['stable_identity_status']=='needs_sync' and item['status']=='pending'


def test_conflicting_ids_pending_explicit_columns_and_dates_remain_separate():
    source=row(identity_columns=[dict(header='任务ID',value='other-task')])
    item=p.normalise_snapshot(dict(items=[source]),resource_id='r',binding_version='v',platform_identity_key='i')['rows'][0]
    assert item['platform_task_id'] is None and 'platform_task_id' in item['pending_fields']
    source=row(identity_attributes=[],identity_columns=[dict(header='任务ID',value='T'),dict(header='别名ID',value='A'),dict(header='推广路径',value='P')],
        valid_from=None,valid_until=None,valid_range='2026-01-01 00:00:00 ~ 2027-01-01 00:00:00')
    item=p.normalise_snapshot(dict(items=[source]),resource_id='r',binding_version='v',platform_identity_key='i')['rows'][0]
    assert item['platform_task_id']=='T' and item['valid_from']=='2026-01-01 00:00:00'


def test_real_owner_list_reuses_exact_profile_and_bound_identity(accounts):
    a,env=accounts;Session.rows=[row()]
    command=a.queue(env['resource_id'],'fanqie_promotion_list')
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and result['result']['rows']==1
    snapshot=json.loads(open(result['result']['promotion_snapshot']['path'],encoding='utf-8').read())
    raw=p._read(snapshot['evidence_ref'])
    assert snapshot['rows'][0]['platform_task_id']=='task-7' and snapshot['identity_verified']
    assert raw['subject']['resource_id']==env['resource_id'] and snapshot['pagination_complete']
    assert snapshot['normalizer_version']=='v1.1'
    inventory=p._read(result['result']['resource_paths'])
    assert inventory['native_requests_issued']==0 and inventory['resources']==[]
    filters=p._read(result['result']['visible_list_filters'])['observation']
    assert filters==visible_list_filters() and filters['all_statuses_included']is None
    session=Session.instances[-1]
    assert session.config.user_data_dir==env['profile_dir'] and session.config.headless and session.config.mute_audio
    assert session.stopped and Session.submit_count==0


def observer_request(accounts,env,**updates):
    value=dict(schema='fanqie_promotion_observer_request/v1',resource_id=env['resource_id'],
        binding_version=env['binding_version'],platform_identity_key='uid:12345',environment_key=env['environment_key'],
        endpoint_paths=['/api/actual/observed'],wait_ms=0,purpose='read_only_promotion_metadata_diagnosis')
    value.update(updates)
    return write_json(accounts.evidence/'OBSERVER_REQUEST.json',value)


def test_opt_in_observer_receives_exact_owned_page_and_subject(accounts,monkeypatch):
    from src.platform_adapter import fanqie_promotion_observation_diagnostic_v1 as diagnostic
    a,env=accounts;calls=[];Session.rows=[row()]
    req=observer_request(a,env)
    def observe(page,**kwargs):
        kwargs['guard']();calls.append((page,kwargs))
        return dict(status='incomplete',promotion_contract_verified=False,business_write_allowed=False)
    monkeypatch.setattr(diagnostic,'run_observation',observe)
    command=a.queue(env['resource_id'],'fanqie_promotion_list',observer_request=req)
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and len(calls)==1 and Session.submit_count==0
    page,kwargs=calls[0]
    assert page.page is Session.instances[-1] and kwargs['observer_request']==req
    assert kwargs['subject']==dict(resource_id=env['resource_id'],binding_version=env['binding_version'],
        environment_key=env['environment_key'],platform_identity_key='uid:12345',
        owner_id=result['owner_id'],generation=result['generation'],task_id=command['command_id'])
    assert p._read(result['result']['observer_diagnostic'])['status']=='incomplete'


def test_observer_wrong_scope_or_write_kind_rejected_before_queue(accounts):
    a,env=accounts
    req=observer_request(a,env,platform_identity_key='different-identity')
    before=a.latest_command(env['resource_id'])
    with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_promotion_list',observer_request=req)
    with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_promotion_apply',observer_request=req)
    assert a.latest_command(env['resource_id'])==before


def test_existing_task_is_observed_without_any_application(accounts):
    a,env=accounts;Session.rows=[row()]
    a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=request(a,env))
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and result['result']['status']=='existing_promotion_preserved'
    assert Session.submit_count==0


def test_unrelated_book_missing_ids_does_not_block_exact_new_application(accounts,exact_book_location):
    a,env=accounts;Session.rows=[row(book_id='different-book',identity_attributes=[])]
    cmd=a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=request(a,env))
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and Session.submit_count==1
    assert len(exact_book_location)==1
    claim=p._read(p._bind(a.folder(cmd['command_id'])/'SUBMIT_CLAIM.json'))
    assert claim['intent']['book_id']==row()['book_id'] and claim['intent']['promotion_path']=='别名推广'
    assert len(list((a.evidence/'promotion_application_claims').glob('*/CLAIM.json')))==1


def test_snapshot_cannot_change_rows_outside_original_observation(accounts):
    a,env=accounts;Session.rows=[row()]
    a.queue(env['resource_id'],'fanqie_promotion_list')
    result=run_owner(env['resource_id'],a,session_factory=Session)
    snapshot=p._read(result['result']['promotion_snapshot'])
    assert p.validate_snapshot(snapshot)==snapshot
    snapshot['rows'][0]['book_id']='caller-invented'
    with pytest.raises(BrowserControlRejected,match='DOM'):p.validate_snapshot(snapshot)


def test_exact_application_claims_once_then_reads_same_platform_task(accounts,exact_book_location):
    a,env=accounts
    cmd=a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=request(a,env))
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and result['result']['status']=='promotion_observed'
    assert Session.submit_count==1 and (a.folder(cmd['command_id'])/'SUBMIT_CLAIM.json').is_file()
    assert len(exact_book_location)==1


def test_submit_response_unknown_never_requeues_or_repeats(accounts,exact_book_location):
    a,env=accounts;Session.crash_on_submit=True
    req=request(a,env);cmd=a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=req)
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and result['result']['application_status']=='outcome_unknown'
    assert not result['result']['confirmed'] and result['result']['requires_read_only_sync']
    listing=a.queue(env['resource_id'],'fanqie_promotion_list')
    assert listing['command_id']!=cmd['command_id']
    assert run_owner(env['resource_id'],a,session_factory=Session)['state']=='succeeded'
    old=p._read(req);auth=p._read(old['authorization']);auth['new_authorization_statement']='another explicit grant'
    old['authorization']=write_json(a.evidence/'AUTH_2.json',auth)
    newreq=write_json(a.evidence/'REQUEST_2.json',old)
    a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=newreq)
    again=run_owner(env['resource_id'],a,session_factory=Session)
    assert again['result']['application_status']=='outcome_unknown'
    assert Session.submit_count==1
    assert len(exact_book_location)==1


def test_missing_native_ids_prevents_new_submit(accounts):
    a,env=accounts;Session.rows=[row(identity_attributes=[],identity_columns=[],identity_links=[])]
    a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=request(a,env))
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='failed' and Session.submit_count==0


def test_fenced_submit_retains_broker_unknown_and_original_command(accounts,exact_book_location):
    a,env=accounts;Session.fence_on_submit=True
    req=request(a,env);cmd=a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=req)
    outcome=run_owner(env['resource_id'],a,session_factory=Session)
    assert outcome['state']=='outcome_unknown' and Session.submit_count==1
    assert a.queue(env['resource_id'],'fanqie_promotion_list')['command_id']==cmd['command_id']


def test_navigation_timeout_keeps_original_healthy_page_without_second_goto(accounts):
    from src.platform_adapter.browser_session import BrowserNavigationTimeout
    a,env=accounts;Session.rows=[row()]
    class TimedPage(Session):
        def goto(self,url,**kwargs):
            super().goto(url,**kwargs)
            if url==p.LIST_URL:raise BrowserNavigationTimeout(dict(target_matched=True,navigation_committed=True,ready_state='complete'))
    cmd=a.queue(env['resource_id'],'fanqie_promotion_list')
    outcome=run_owner(env['resource_id'],a,session_factory=TimedPage)
    assert outcome['state']=='succeeded' and TimedPage.instances[-1].goto_calls.count(p.LIST_URL)==1
    assert list(a.folder(cmd['command_id']).glob('NAVIGATION_TIMEOUT_*.json'))


def test_navigation_wrong_origin_is_rejected_before_promotion_DOM(accounts):
    a,env=accounts;Session.rows=[row()]
    class WrongPage(Session):
        def goto(self,url,**kwargs):
            super().goto(url,**kwargs)
            if url==p.LIST_URL:self.url='https://not-fanqie.example/redirect'
        def evaluate(self,js):
            if self.url.startswith('https://not-fanqie'):pytest.fail('No DOM IO on other origin')
            return super().evaluate(js)
    a.queue(env['resource_id'],'fanqie_promotion_list')
    outcome=run_owner(env['resource_id'],a,session_factory=WrongPage)
    assert outcome['state']=='failed' and Session.submit_count==0


@pytest.mark.parametrize('updates',[dict(publish_type='视频'),dict(platform_identity_key='uid:other'),dict(book_name='')])
def test_wrong_or_incomplete_exact_request_rejected_before_queue(accounts,updates):
    a,env=accounts
    with pytest.raises(BrowserControlRejected):a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=request(a,env,**updates))
    assert Session.submit_count==0


def test_guard_failure_stops_dom_io_before_read_or_submit(tmp_path):
    calls=[]
    page=NS(evaluate=lambda js:calls.append(js),wait_for_timeout=lambda ms:None)
    def guard():raise BrowserControlRejected('owner_changed','fixture owner changed')
    with pytest.raises(BrowserControlRejected):p.capture(page,guard,resource_id='r',binding_version='v',
        identity=lambda:{},evidence_path=tmp_path/'capture.json')
    assert calls==[]


def test_broken_pipe_or_known_dead_worker_retains_broker_unknown():
    page=NS(page=NS(_session=NS(worker_failure=lambda:'worker_exited')))
    assert p._hard_worker_failure(BrokenPipeError('lost pipe'),NS())
    assert p._hard_worker_failure(TimeoutError('response lost'),page)
    outcome=p._application_unknown('pipe_closed',hard=p._hard_worker_failure(BrokenPipeError(),NS()))
    assert outcome.state=='outcome_unknown' and outcome.result['confirmed'] is False
    assert outcome.result['automatic_resubmit'] is False


def test_completed_confirmation_pending_remains_business_unknown_not_broker_fence():
    page=NS(page=NS(_session=NS(worker_failure=lambda:'')))
    assert not p._hard_worker_failure(TimeoutError('confirmation pending'),page)
    outcome=p._application_unknown('confirmation_pending')
    assert outcome.state=='succeeded' and outcome.result['application_status']=='outcome_unknown'
    assert outcome.result['requires_read_only_sync'] and not outcome.result['confirmed']


def test_actual_platform_fullwidth_tilde_validity_preserves_server_raw():
    fixture=json.loads((p.ROOT/'tests/fixtures/fanqie_promotion_validity_live_20261116.json').read_text(encoding='utf-8'))
    for case in fixture['cases']:
        source=row(valid_from=None,valid_until=None,valid_range=case['raw'])
        item=p.normalise_snapshot(dict(items=[source]),resource_id='r',binding_version='v',platform_identity_key='i')['rows'][0]
        assert item['valid_from']==case['expected_from'] and item['valid_until']==case['expected_until']
        assert item['source_raw_valid_range']==case['raw']


def test_legacy_real_snapshot_is_still_readable_without_rewriting_old_dates():
    path=p.ROOT/'data/fanqie_account_control/commands/da13e0f73df543dbaaf3cbb409ec7140/PROMOTION_SNAPSHOT.json'
    value=json.loads(path.read_text(encoding='utf-8'))
    before=path.read_bytes()
    assert 'normalizer_version' not in value and p.validate_snapshot(value)==value
    assert all(r['valid_from'] is None for r in value['rows']) and path.read_bytes()==before
    value['normalizer_version']='future-version'
    with pytest.raises(BrowserControlRejected,match='版本'):p.validate_snapshot(value)
