"""Real owner/claim/lease/SQLite fencing; fake UI only, no production profile or network."""
from datetime import datetime, timezone
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_reconciliation_authorization as authz
from src.operations_accounts import publication_reconciliation as business
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlRejected,BrowserControlStore,_json
from src.operations_accounts.repository import AccountBindingRepository
from src.operations_accounts.runtime import AccountRuntimeContext,AccountRuntimeService
from src.platform_adapter.models import PublishRequest
from src.scheduler import account_refresh
from test_publication_bounded_retry_authorization import account_seed,write,ref


@pytest.fixture
def incident(account_seed,tmp_path,monkeypatch):
    root=tmp_path; (root/'data/publish_runs').mkdir(parents=True)
    for name in ('account.db','scheduler.db'):shutil.copyfile(account_seed/name,root/name)
    monkeypatch.setattr(quota,'ROOT',root);monkeypatch.setattr(bridge,'ROOT',root)
    monkeypatch.setattr(quota,'REGISTRY_V8',root/'V8_REGISTRY.json')
    monkeypatch.setattr(authz,'REGISTRY',root/'RECON_REGISTRY.json')
    monkeypatch.setattr(account_refresh,'DB',root/'scheduler.db')
    import psutil
    def gone(pid):raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(psutil,'Process',gone)
    repo=AccountBindingRepository(root/'account.db')
    with repo.connection() as db:db.execute('UPDATE account_runtime_state SET daily_runs=33')
    video=root/'original.mp4';video.write_bytes(b'approved original film')
    prepared=root/'PREPARED.json'
    p={'decision_source':'explicit_user_statement','full_film_accepted_for_publication':True,'user_statement':'批准原片及法律评论',
        'account_uuid':'acct:one','account_key':'one','video':ref(video),'ai_generated':True,'fictional_story':True,
        'title':'Approved','description':'剧情虚构，非真实事件。','hashtags':['劳动法'],'visibility':'public','comment':'原批准法律评论'}
    p_ref=write(prepared,p)
    binding=NS(account_uuid='acct:one',account_key='one',platform_identity_key='public:original',browser_environment_key='env:one',
        browser_profile_dir='profile/one',storage_state_path='state/one',confirmed_by='user',created_at='old',status='active')
    profile=NS(account_uuid='acct:one',account_key='one',status='active',profile_version=1)
    context=AccountRuntimeContext(profile,binding,'env:one','profile/one','state/one')
    runtime=object.__new__(AccountRuntimeService);runtime.resolve=lambda *a,**k:context
    runtime.profiles=NS(get=lambda *a:profile)
    runtime.bindings=NS(get_runtime_state=repo.get_runtime_state,get=lambda *a:binding,acquire_runtime=repo.acquire_runtime,
        release_runtime=repo.release_runtime,connection=repo.connection)
    resource=bridge.AccountBrowserResource(context,runtime)
    store=BrowserControlStore(root/'data/account_browser_control.db')
    monkeypatch.setattr(bridge,'_store',lambda:store);monkeypatch.setattr(bridge,'_runtime',lambda:runtime)
    monkeypatch.setattr(bridge,'_legacy_manual_gate',lambda *a:None)
    monkeypatch.setattr(bridge,'_controls',lambda *a:quota.control_snapshot('acct:one'))
    request=PublishRequest(video_path=str(video),title=p['title'],description=p['description'],hashtags=p['hashtags'],visibility='public',
        ai_generated=True,fictional_story=True,extra_metadata={'account_uuid':'acct:one'})
    old=write(root/'V8.json',{'schema':quota.SCHEMA_V8,'account_uuid':'acct:one','account_key':'one','prepared':p_ref,
        'video':p['video'],'max_daily_runs':33,'idempotency_keys':{'publish':'old-v8-key'}})
    write(quota.REGISTRY_V8,old)
    original=store.submit('acct:one',bridge.binding_version(context),'publish','old-v8-key',{'account_uuid':'acct:one','account_key':'one',
        'request':asdict(request),'video_sha256':p['video']['sha256'],'authorization':p_ref,'quota_authorization':old})
    owner=store.acquire_owner('acct:one',bridge.binding_version(context),'original-owner')
    start=time.time()-20
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id=?,generation=1,created_at=?,updated_at=?,result=? WHERE command_id=?",
            ('original-owner',start,start+15,_json({'status':'submission_unknown','success':False,'post_id':'','publish_url':''}),original['command_id']))
    original=store.get(original['command_id'])
    key=hashlib.sha256(json.dumps({'platform_identity_key':'public:original','video_sha256':p['video']['sha256']},sort_keys=True).encode()).hexdigest()
    journal=root/'data/publish_runs'/(key+'.original.jsonl')
    rows=[{'stage':'prepared','account':'one','account_uuid':'acct:one','platform_identity_key':'public:original','video_path':str(video),
        'video_sha256':p['video']['sha256'],'title':'Approved','at_bjt':datetime.fromtimestamp(start+5,timezone.utc).isoformat()},
        {'stage':'ai_declaration_verified','evidence':{'verified':True},'set_selected':True},
        {'stage':'submission_started'},{'stage':'submission_unknown'}]
    journal.write_text('\n'.join(_json(v) for v in rows),encoding='utf-8')
    lock=root/'data/publish_runs'/(key+'.submitted.json');write(lock,{'status':'submission_started','journal':str(journal)})
    a={'schema':authz.SCHEMA,'decision_source':'explicit_user_statement','user_statement':'修复缺陷然后测试再生产测试',
        'preceding_user_confirmation':'已发布状态','account_uuid':'acct:one','account_key':'one','original_command_id':original['command_id'],
        'original_command':write(root/'ORIGINAL.json',original),'original_journal':ref(journal),'original_submission_lock':ref(lock),'prepared':p_ref,
        'original_owner_id':'original-owner','original_generation':1,'original_backend_pid':987654321,'original_backend_create_time':1.,
        'utc_day':datetime.now(timezone.utc).date().isoformat(),'baseline_daily_runs':33,'max_daily_runs':34,'additional_reconciliation_runs':1,
        'new_upload_authorized':False,'new_publish_click_authorized':False,'comment_retry_authorized':False,'active_control_revision':42,
        **{k:True for k in ('preserve_original_unknown_snapshot','retain_submission_lock','visible_managed_window_authorized','verify_exact_work_before_comment',
        'comment_authorization_is_original_prepared','stop_on_human_required_or_unknown','deployment_authorized')}}
    a_path=root/'USER_AUTHORIZATION.json';a_ref=write(a_path,a);monkeypatch.setattr(authz,'AUTH_SHA256',a_ref['sha256'])
    authz.register_reconciliation_authorization(a_path,a_ref['sha256'])
    dead=write(root/'RETIREMENT.json',{'schema':'publication_reconciliation_retirement/20261019/v1','account_uuid':'acct:one',
        'original_command_id':original['command_id'],'owner_id':'original-owner','generation':1,'original_backend_pid':987654321,
        'original_backend_create_time':1.,'parent_exited':True,'descendants_exited':True,'observed_children':[],'gone_child_ids':[],
        'alive_child_ids':[],'finished_at':time.time(),
        'pid_identity_checks':[{'pid':987654321,'expected_create_time':1.,'status':'not_present'}]})
    kwargs=dict(owner_id='original-owner',generation=1,authorization=a_ref,expected_snapshot_sha256=hashlib.sha256(_json(original).encode()).hexdigest(),retirement_evidence=dead)
    return NS(root=root,store=store,original=original,auth=a_ref,kwargs=kwargs,resource=resource,repo=repo,lock=lock,journal=journal,p=p)


def transfer(f):
    with f.store._db(write=True) as db:f.store.handoff_publication_reconciliation(**f.kwargs,connection=db)


def actor_for(f):
    return BrowserControlActor(f.store,'acct:one',f.original['binding_version'],'new-owner',
        {'publication_reconcile':bridge._publication_reconcile,'publish':lambda *a:pytest.fail('ordinary publish ran')},
        admission=bridge._admission,context=f.resource,
        owner_acquirer=lambda a,b,o:f.store.acquire_reconciliation_owner(a,b,o,f.auth))


class Window:
    config=NS(headless=False)
    def __init__(self):self.closed=False;self.stopped=False
    def window_status(self):return {'context_closed':self.closed,'tabs':[{'tab_id':'reconciliation-tab','closed':self.closed}]}
    def stop(self):self.stopped=True


def install_ui(f,monkeypatch,status='verified_published',bad_comment=False,expected_count=34,comment_status=None):
    window=Window()
    def ensure():f.resource.session=window;return window
    f.resource.ensure_session=ensure
    class Borrowed:
        def __init__(self,resource,role):
            bridge.active_context().check_dispatch()
            self.page=NS(tab_id='reconciliation-tab');self.config=window.config
    monkeypatch.setattr(bridge,'BorrowedSession',Borrowed)
    def service(ctx,payload):
        if expected_count is not None:assert f.repo.get_runtime_state('acct:one').daily_runs==expected_count
        ctx.check_dispatch()  # Original operation_scope must prevent false legacy-lock rejection at34.
        assert f.resource.headless is False
        post='1234567890123456789'
        pe={k:True for k in ('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified')}
        pe.update(post_id=post,publish_url='https://www.douyin.com/video/'+post,review_status='clear')
        identity={'account_uuid':'acct:one','post_id':post,'comment_sha256':hashlib.sha256(f.p['comment'].encode()).hexdigest()}
        comment={'schema':'authorized_publication_comment/v1','status':'sent_visible','identity':identity,'post_url':pe['publish_url'],'comment':f.p['comment']}
        comment_key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        receipt=f.root/'data/publish_comments'/(comment_key+'.receipt.json');receipt.parent.mkdir(parents=True,exist_ok=True);write(receipt,comment)
        if bad_comment:comment={'status':'not_requested'}
        if comment_status is not None:comment={'status':comment_status}
        result={'status':status,'publish_evidence':pe,'comment':comment}
        out=f.root/'data/publication_reconciliations'/ctx.task_id;out.mkdir(parents=True)
        result['evidence_ref']=write(out/'EVIDENCE.json',{'schema':'publication_reconciliation_evidence/20261019/v1',
            'account_uuid':'acct:one','original_command_id':f.original['command_id'],'reconciliation_command_id':ctx.task_id,'result':dict(result)})
        return result
    monkeypatch.setattr(business,'run_reconciliation',service)
    return window


def test_atomic_handoff_rollback_then_only_explicit_owner_and_reconcile_claim(incident):
    f=incident
    with pytest.raises(BrowserControlRejected):f.store.acquire_owner('acct:one',f.original['binding_version'],'ordinary')
    with pytest.raises(RuntimeError):
        with f.store._db(write=True) as db:
            f.store.handoff_publication_reconciliation(**f.kwargs,connection=db)
            raise RuntimeError('rollback caller transaction')
    assert f.store.snapshot('acct:one')['owner']['state']=='active' and f.store.pending_reconciliation_authorization('acct:one') is None
    transfer(f)
    assert f.store.get(f.original['command_id'])==f.original
    with pytest.raises(BrowserControlRejected):f.store.acquire_owner('acct:one',f.original['binding_version'],'ordinary')
    other=f.store.submit('acct:one',f.original['binding_version'],'official_console','ordinary',{},1000)
    command=bridge.queue_publication_reconciliation(f.auth)
    assert bridge.queue_publication_reconciliation(f.auth)['command_id']==command['command_id']
    owner=f.store.acquire_reconciliation_owner('acct:one',f.original['binding_version'],'new-owner',f.auth)
    claimed=f.store.claim_next('acct:one',f.original['binding_version'],'new-owner',owner['generation'])
    assert claimed['kind']=='publication_reconcile' and f.store.get(other['command_id'])['state']=='queued'
    with pytest.raises(BrowserControlRejected):f.store.acquire_reconciliation_owner('acct:one',f.original['binding_version'],'third-owner',f.auth)
    assert f.repo.get_runtime_state('acct:one').daily_runs==33


def test_real_actor_one34_exact_work_comment_resolves_last_and_retains_lock_window(incident,monkeypatch):
    monkeypatch.setenv('AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT','1')  # Explicit legacy-cap compatibility case.
    f=incident;transfer(f);window=install_ui(f,monkeypatch)
    before_lock=f.lock.read_bytes();before_journal=f.journal.read_bytes()
    ordinary=f.store.submit('acct:one',f.original['binding_version'],'publish','ordinary-after-resolution',{},1000)
    command=bridge.queue_publication_reconciliation(f.auth);actor=actor_for(f)
    try:
        outcome=actor.run_next();assert outcome['state']=='succeeded'
        resolved=f.store.get(f.original['command_id'])
        assert resolved['state']=='succeeded' and resolved['result']['original_unknown_snapshot']==f.original
        assert resolved['result']['post_id']=='1234567890123456789'
        assert f.repo.get_runtime_state('acct:one').daily_runs==34
        assert f.lock.read_bytes()==before_lock and f.journal.read_bytes()==before_journal
        assert f.resource.console_tasks=={command['command_id']:'reconciliation-tab'}
        held=actor.run_next()
        assert held['command_id']==ordinary['command_id'] and held['state']=='queued' and held['error_code']=='human_required'
        window.closed=True;bridge._poll_manual_windows(actor,f.resource)
        assert window.stopped and not f.resource.console_tasks and f.resource.session is None
        assert f.store.get(command['command_id'])['state']=='succeeded'
        normal=actor.run_next()
        assert normal['command_id']==ordinary['command_id'] and normal['state']=='queued' and normal['error_code']=='daily_quota_exceeded'
        assert f.repo.get_runtime_state('acct:one').daily_runs==34
    finally:actor.stop_heartbeat()


@pytest.mark.parametrize('status,bad_comment',[('verification_pending',False),('verified_published',True)])
def test_unverified_or_skipped_comment_keeps_original_unknown_and_poll_does_not_fake_success(incident,monkeypatch,status,bad_comment):
    f=incident;transfer(f);window=install_ui(f,monkeypatch,status,bad_comment)
    command=bridge.queue_publication_reconciliation(f.auth);actor=actor_for(f)
    try:
        assert actor.run_next()['state']=='outcome_unknown'
        assert f.store.get(f.original['command_id'])==f.original and f.lock.exists()
        assert f.repo.get_runtime_state('acct:one').daily_runs==34
        window.closed=True;bridge._poll_manual_windows(actor,f.resource)
        assert f.store.get(command['command_id'])['state']=='outcome_unknown'
        assert actor.run_next() is None and not f.resource.console_tasks
    finally:actor.stop_heartbeat()


def test_live_process_wrong_evidence_and_ordinary_limits_cannot_borrow_reconciliation(incident,monkeypatch):
    f=incident
    import psutil
    monkeypatch.setattr(psutil,'Process',lambda pid:NS(create_time=lambda:1.))
    with pytest.raises(BrowserControlRejected):transfer(f)
    assert f.store.snapshot('acct:one')['owner']['state']=='active'
    assert f.store.get(f.original['command_id'])==f.original
    assert bridge.operation_daily_limit('publish',20,'acct:one')==20
    assert bridge.operation_daily_limit('inspection-read',20,'acct:one')==20
    with pytest.raises(BrowserControlRejected):
        bridge.queue_publication_reconciliation(dict(f.auth,sha256='0'*64))
    assert f.repo.get_runtime_state('acct:one').daily_runs==33


def test_retirement_pid_identity_rejects_original_unknown_and_unbound_reuse_but_accepts_proven_reuse(incident,monkeypatch):
    f=incident
    import psutil
    pid=987654321
    original=f.store.get(f.original['command_id'])
    monkeypatch.setattr(psutil,'Process',lambda value:NS(create_time=lambda:1.))
    with pytest.raises(BrowserControlRejected):transfer(f)
    def inaccessible(value):raise psutil.AccessDenied(value)
    monkeypatch.setattr(psutil,'Process',inaccessible)
    with pytest.raises(BrowserControlRejected):transfer(f)
    monkeypatch.setattr(psutil,'Process',lambda value:NS(create_time=lambda:2.))
    # A fresh independently checked reuse must also be bound by the retirement receipt.
    with pytest.raises(BrowserControlRejected):transfer(f)
    dead=json.loads(Path(f.kwargs['retirement_evidence']['path']).read_text(encoding='utf-8'))
    dead['observed_children']=[{'pid':987654320,'ppid':pid,'name':'original-worker','create_time':3.}]
    dead['gone_child_ids']=[987654320]
    dead['pid_identity_checks']=[{'pid':pid,'expected_create_time':1.,'status':'pid_reused','current_create_time':2.},
        {'pid':987654320,'expected_create_time':3.,'status':'pid_reused','current_create_time':4.}]
    monkeypatch.setattr(psutil,'Process',lambda value:NS(create_time=lambda:2. if value==pid else 4.))
    f.kwargs['retirement_evidence']=write(f.root/'RETIREMENT_REUSED.json',dead)
    transfer(f)
    assert f.store.get(f.original['command_id'])==original
    assert f.store.snapshot('acct:one')['owner']['state']=='released'
    with f.store._db() as db:row=authz.handoff_row(db,'acct:one')
    audit=json.loads(row['retirement_evidence'])
    assert audit['pid_identity_checks']==dead['pid_identity_checks']
    assert f.repo.get_runtime_state('acct:one').daily_runs==33 and f.lock.exists()
