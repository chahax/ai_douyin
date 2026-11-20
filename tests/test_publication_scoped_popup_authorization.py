"""Only new v7 actor/SQLite gates; old v1-v6 semantics isolated, native chain checked separately."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_scoped_popup_authorization as scoped
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlRejected, BrowserControlStore, _json
from src.operations_accounts.repository import AccountBindingRepository
from src.operations_accounts.runtime import AccountRuntimeContext, AccountRuntimeService
from src.platform_adapter.models import PublishRequest
from src.scheduler import account_refresh
from test_publication_bounded_retry_authorization import account_seed, write, ref


@pytest.fixture
def grant(account_seed,tmp_path,monkeypatch):
    # This is an October 19 frozen authority fixture, not current permission.
    # Freeze every date consumer locally; production authority stays expired.
    import sys
    from src.operations_accounts import repository as repository_module
    class HistoricalDay(datetime):
        @classmethod
        def now(cls,tz=None):
            value=cls(2026,10,19,12,tzinfo=timezone.utc)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    for module in (sys.modules[__name__],quota,scoped,repository_module,bridge):
        monkeypatch.setattr(module,'datetime',HistoricalDay)
    monkeypatch.setenv('AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT','1')
    root=tmp_path
    (root/'data/publish_runs').mkdir(parents=True)
    for name in ('account.db','scheduler.db'):
        shutil.copyfile(account_seed/name,root/name)
    monkeypatch.setattr(quota,'ROOT',root)
    monkeypatch.setattr(bridge,'ROOT',root)
    for name in ('REGISTRY','REGISTRY_V2','REGISTRY_V3','REGISTRY_V4','REGISTRY_V5','REGISTRY_V6','REGISTRY_V7'):
        monkeypatch.setattr(quota,name,root/(name+'.json'))
    monkeypatch.setattr(account_refresh,'DB',root/'scheduler.db')
    repository=AccountBindingRepository(root/'account.db')
    with repository.connection() as db:
        db.execute('UPDATE account_runtime_state SET daily_runs=31,day_key=?',('2026-10-19',))
    video=root/'original.mp4'; video.write_bytes(b'approved same film')
    p={'decision_source':'explicit_user_statement','full_film_accepted_for_publication':True,'user_statement':'原完整片批准',
        'ai_generated':True,'fictional_story':True,'account_uuid':'acct:one','account_key':'one','video':ref(video),
        'title':'Approved','description':'剧情虚构，非真实事件。','hashtags':['劳动法'],'visibility':'public'}
    prepared=root/'PREPARED.json'; prepared_ref=write(prepared,p)
    binding=NS(account_uuid='acct:one',account_key='one',platform_identity_key='public:original',browser_environment_key='env:one',
        browser_profile_dir='profile/one',storage_state_path='state/one',confirmed_by='user',created_at='old',status='active')
    profile=NS(account_uuid='acct:one',account_key='one',profile_version=1,status='active')
    context=AccountRuntimeContext(profile,binding,'env:one','profile/one','state/one')
    runtime=object.__new__(AccountRuntimeService)
    runtime.resolve=lambda *a,**k:context
    runtime.profiles=NS(get=lambda *a:profile)
    runtime.bindings=NS(get_runtime_state=repository.get_runtime_state,get=lambda *a:binding,acquire_runtime=repository.acquire_runtime,
        release_runtime=repository.release_runtime,connection=repository.connection)
    resource=bridge.AccountBrowserResource(context,runtime)
    store=BrowserControlStore(root/'data/account_browser_control.db')
    monkeypatch.setattr(bridge,'_runtime',lambda:runtime)
    monkeypatch.setattr(bridge,'_store',lambda:store)
    monkeypatch.setattr(bridge,'_legacy_manual_gate',lambda *a:None)
    monkeypatch.setattr(bridge,'_controls',lambda *a:quota.control_snapshot('acct:one'))
    older=[]
    for n,registry in enumerate((quota.REGISTRY,quota.REGISTRY_V2,quota.REGISTRY_V3,quota.REGISTRY_V4,quota.REGISTRY_V5,quota.REGISTRY_V6),1):
        old={'schema':[quota.SCHEMA,quota.SCHEMA_V2,quota.SCHEMA_V3,quota.SCHEMA_V4,quota.SCHEMA_V5,quota.SCHEMA_V6][n-1],
            'account_uuid':'acct:one','account_key':'one','video':p['video'],'prepared':prepared_ref,
            'utc_day':datetime.now(timezone.utc).date().isoformat(),'recovery_control_revision':41,
            'idempotency_keys':{'publish':[f'old5:{i}' for i in (1,2,3)] if n==5 else f'old-publish-{n}'},
            'max_daily_runs':[22,25,26,27,30,31][n-1]}
        path=root/f'OLD{n}.json'; old_ref=write(path,old); write(registry,old_ref); older.append((old_ref,old))
    request=PublishRequest(video_path=str(video),title=p['title'],description=p['description'],hashtags=p['hashtags'],
        visibility='public',ai_generated=True,fictional_story=True,extra_metadata={'account_uuid':'acct:one'})
    payload={'account_uuid':'acct:one','account_key':'one','quota_authorization':older[-1][0],
        'authorization':prepared_ref,'request':asdict(request),'video_sha256':p['video']['sha256']}
    before=store.submit('acct:one',bridge.binding_version(context),'publish','old-publish-6',payload)
    start=time.time()-20
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='failed',created_at=?,updated_at=?,result=? WHERE command_id=?",
            (start,start+15,_json({'status':'ai_declaration_unverified','success':False,'post_id':'','publish_url':''}),before['command_id']))
    before=store.get(before['command_id'])
    monkeypatch.setattr(scoped,'PREVIOUS_COMMAND_ID',before['command_id'])
    key=hashlib.sha256(json.dumps({'platform_identity_key':'public:original','video_sha256':p['video']['sha256']},sort_keys=True).encode()).hexdigest()
    journal=root/'data/publish_runs'/(key+'.original.jsonl')
    journal.write_text('\n'.join(_json(v) for v in ({'stage':'prepared','account':'one','account_uuid':'acct:one',
        'platform_identity_key':'public:original','video_sha256':p['video']['sha256'],'video_path':str(video),'title':'Approved',
        'at_bjt':datetime.fromtimestamp(start+5,timezone.utc).isoformat()}, {'stage':'ai_declaration_unverified'})),encoding='utf-8')
    before_ref=write(root/'PREVIOUS.json',before)
    old_anchor=write(root/'OLD6_AUTH.json',{'previous_command':before_ref,'previous_journal':ref(journal)})
    older[-1][1]['user_authorization']=old_anchor
    old6path=Path(older[-1][0]['path'])
    old6ref=write(old6path,older[-1][1]); older[-1]=(old6ref,older[-1][1]); write(quota.REGISTRY_V6,old6ref)
    with store._db(write=True) as db:
        payload['quota_authorization']=old6ref
        db.execute('UPDATE browser_control_commands SET payload=? WHERE command_id=?',(_json(payload),before['command_id']))
    before=store.get(before['command_id']); before_ref=write(root/'PREVIOUS.json',before)
    # Keep the old opaque anchor ref current; only old semantic validation is isolated.
    old_anchor=write(root/'OLD6_AUTH.json',{'previous_command':before_ref,'previous_journal':ref(journal)})
    # Anchor reference hash is stored in old6; update the closed fixture once more.
    older[-1][1]['user_authorization']=old_anchor
    old6ref=write(old6path,older[-1][1]); older[-1]=(old6ref,older[-1][1]); write(quota.REGISTRY_V6,old6ref)
    # Avoid a self-referential file hash: anchor carries only binding identity, as the isolated old chain boundary.
    anchor=write(root/'ANCHOR.json',{'binding_version':before['binding_version']})
    old_anchor=write(root/'OLD6_ANCHOR_AUTH.json',{'previous_command':anchor,'previous_journal':ref(journal)})
    older[-1][1]['user_authorization']=old_anchor
    old6ref=write(old6path,older[-1][1]); older[-1]=(old6ref,older[-1][1]); write(quota.REGISTRY_V6,old6ref)
    payload['quota_authorization']=old6ref
    with store._db(write=True) as db: db.execute('UPDATE browser_control_commands SET payload=? WHERE command_id=?',(_json(payload),before['command_id']))
    before=store.get(before['command_id']); before_ref=write(root/'PREVIOUS.json',before)
    original_validator=quota.validate_authorization
    def isolate_old(reference,**kwargs):
        for old_ref,value in older:
            if reference==old_ref:
                assert quota._load_reference(reference)[0]==value
                if not kwargs.get('allow_expired',False) and value['utc_day']!=quota.datetime.now(timezone.utc).date().isoformat(): quota._reject()
                return value
        return original_validator(reference,**kwargs)
    monkeypatch.setattr(quota,'validate_authorization',isolate_old)
    repair=root/'src/platform_adapter/ai_content_declaration.py'; repair.parent.mkdir(parents=True); repair.write_bytes(b'frozen scoped popup repair')
    monkeypatch.setattr(scoped,'REPAIR_SHA256',ref(repair)['sha256'])
    frozen_repair=root/scoped.REPAIR_SNAPSHOT; frozen_repair.parent.mkdir(parents=True); frozen_repair.write_bytes(repair.read_bytes())
    legacy=hashlib.sha256(json.dumps({'account':'one','video_sha256':p['video']['sha256']},sort_keys=True).encode()).hexdigest()
    locks=[{'path':str((root/'data/publish_runs'/(k+'.submitted.json')).resolve()),'exists':False} for k in (key,legacy)]
    final=write(root/'FINAL.json',{'original_command':before,'journal':ref(journal),'runtime':{'daily_runs':31,'day_key':older[-1][1]['utc_day'],
        'lock_owner':'','lock_expires_at':''},'control':{'state':'active','revision':42},'platform_submission_started':False,
        'publication_completed':False,'submission_locks':locks,'new_runs_used':1,'new_runs_remaining':0,
        'offline_helper_sha256':scoped.REPAIR_SHA256,'no_second_run_dispatched':True})
    approval={'schema':scoped.AUTH_SCHEMA,'decision_source':'explicit_user_statement','user_statement':'追加','approval_question':'是否追加1次继续发布？',
        'account_uuid':'acct:one','account_key':'one','prepared':prepared_ref,'video':p['video'],'previous_authorization':old6ref,
        'previous_command':before_ref,'previous_command_id':before['command_id'],'previous_journal':ref(journal),'previous_final_state':final,
        'repair_source':ref(repair),'deployment_authorized':True,'additional_publication_runs':1,'additional_recovery_runs':0,
        'new_media_authorized':False,'retain_original_history':True,'stop_on_unknown':True,'stop_on_human_required':True,
        'utc_day':older[-1][1]['utc_day'],'baseline_daily_runs':31,'max_daily_runs':32,'active_control_revision':42}
    authority=write(root/'USER_AUTHORIZATION.json',approval)
    monkeypatch.setattr(scoped,'APPROVAL_SHA256',authority['sha256'])
    value=scoped.build_scoped_popup_authorization(authority); parent_path=root/'V7_FROZEN.json'; parent=write(parent_path,value)
    prior={p:p.read_bytes() for p in (quota.REGISTRY,quota.REGISTRY_V2,quota.REGISTRY_V3,quota.REGISTRY_V4,quota.REGISTRY_V5,quota.REGISTRY_V6)}
    quota.register_authorization(parent_path,parent['sha256'])
    events=[]
    @bridge._with_active
    def publish(ctx,payload):
        with bridge._publication_lease(resource): events.append(repository.get_runtime_state('acct:one').daily_runs)
        return {'published_once':True}
    actor=BrowserControlActor(store,'acct:one',bridge.binding_version(context),'owner:one',{'publish':publish},context=resource,admission=bridge._admission)
    yield NS(root=root,parent=parent,parent_path=parent_path,value=value,prior=prior,prepared=prepared,store=store,before=before,
        actor=actor,resource=resource,repository=repository,events=events,journal=journal,locks=locks,repair=repair,frozen_repair=frozen_repair)
    actor.stop_heartbeat()


def queue7(g,**kwargs): return bridge.queue_prepared_publication(g.prepared,quota_authorization=g.parent,**kwargs)


def test_real31_to32_once_and_old_registries_caps_do_not_expand(grant):
    g=grant; command=queue7(g)
    assert command['priority']==250 and 'quota_attempt_index' not in command['payload']
    assert g.actor.run_next()['state']=='succeeded' and g.events==[32]
    assert queue7(g)['command_id']==command['command_id'] and g.actor.run_next() is None
    assert g.repository.get_runtime_state('acct:one').daily_runs==32
    assert all(path.read_bytes()==body for path,body in g.prior.items())
    assert quota.validate_authorization(json.loads(quota.REGISTRY_V6.read_bytes()))['max_daily_runs']==31
    assert quota.registered_recovery('one') is None


def test_unknown_human_lock_or_frozen_repair_change_rejects_before_consume(grant):
    g=grant
    for state,status in (('outcome_unknown','submission_unknown'),('failed','human_required')):
        with g.store._db(write=True) as db:
            db.execute('UPDATE browser_control_commands SET state=?,result=? WHERE command_id=?',
                (state,_json(dict(g.before['result'],status=status)),g.before['command_id']))
        with pytest.raises(BrowserControlRejected): queue7(g)
    with g.store._db(write=True) as db:
        db.execute('UPDATE browser_control_commands SET state=?,result=? WHERE command_id=?',
            (g.before['state'],_json(g.before['result']),g.before['command_id']))
    lock=Path(g.locks[0]['path']); lock.write_text('{}',encoding='utf-8')
    with pytest.raises(BrowserControlRejected): queue7(g)
    lock.unlink()
    g.frozen_repair.write_bytes(b'changed immutable repair')
    with pytest.raises(BrowserControlRejected): queue7(g)
    assert g.repository.get_runtime_state('acct:one').daily_runs==31


def test_exact_scope_no_index_key_expansion_and_expired_history_only(grant,monkeypatch):
    g=grant
    for index in (1,2,3):
        with pytest.raises(BrowserControlRejected): queue7(g,quota_attempt_index=index)
    for field,new_value in (('max_daily_runs',33),('active_control_revision',43),('repair_source',{'path':str(g.repair),'sha256':'0'*64})):
        value=deepcopy(g.value); value[field]=new_value
        candidate=write(g.root/(field+'.json'),value)
        with pytest.raises(BrowserControlRejected): quota.validate_authorization(candidate,require_registered=False)
    command=queue7(g)
    for changed in (dict(command,idempotency_key='another-key'),dict(command,kind='recovery'),
            dict(command,payload=dict(command['payload'],quota_attempt_index=None))):
        with pytest.raises(BrowserControlRejected):
            quota.authorized_daily_limit(NS(account_id='acct:one',command=changed),
                'identity-recovery' if changed['kind']=='recovery' else 'publish',account_uuid='acct:one',control=quota.control_snapshot('acct:one'))
    assert quota.authorized_daily_limit(NS(command={'kind':'manual'}),'manual-session',account_uuid='acct:one')==20
    # Future source edits do not erase the frozen c93 repair identity/history.
    g.repair.write_bytes(b'future legitimate source version')
    class NextDay(datetime):
        @classmethod
        def now(cls,tz=None): return datetime(2026,10,20,tzinfo=timezone.utc)
    monkeypatch.setattr(scoped,'datetime',NextDay); monkeypatch.setattr(quota,'datetime',NextDay)
    assert quota.validate_authorization(g.parent,allow_expired=True)['max_daily_runs']==32
    with pytest.raises(BrowserControlRejected): queue7(g)
    assert g.repository.get_runtime_state('acct:one').daily_runs==31
