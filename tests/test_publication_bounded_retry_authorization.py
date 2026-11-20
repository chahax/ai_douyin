"""New v5 actor/SQLite gates; old v1-v4 validator isolated, native chain reviewed separately."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import shutil
import time
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_bounded_retry_authorization as bounded
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlActor, BrowserCommandResult, BrowserControlRejected, BrowserControlStore, _json
from src.operations_accounts.repository import AccountBindingRepository
from src.operations_accounts.runtime import AccountRuntimeContext, AccountRuntimeService
from src.scheduler import account_refresh


def write(path, value):
    path.write_text(_json(value), encoding='utf-8')
    return ref(path)


def ref(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture(scope='module')
def account_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp('bounded_minimal_seed')
    repository = AccountBindingRepository(root / 'account.db')
    with repository.connection() as db:
        db.execute("INSERT INTO douyin_accounts(account_uuid,account_key,created_at,updated_at) VALUES('acct:one','one','old','old')")
    repository.get_runtime_state('acct:one')
    with repository.connection() as db:
        db.execute("UPDATE account_runtime_state SET daily_runs=27,day_key=? WHERE account_uuid='acct:one'",
            (datetime.now(timezone.utc).date().isoformat(),))
    with account_refresh.connect(root / 'scheduler.db') as db:
        db.execute("INSERT INTO account_controls(account_uuid,account_key,state,consecutive_failures,updated_at,revision) VALUES('acct:one','one','active',2,1,42)")
    return root


@pytest.fixture
def ready(account_seed, tmp_path, monkeypatch):
    root = tmp_path
    (root / 'data/publish_runs').mkdir(parents=True)
    for name in ('account.db', 'scheduler.db'):
        shutil.copyfile(account_seed / name, root / name)
    monkeypatch.setattr(quota, 'ROOT', root)
    monkeypatch.setattr(bridge, 'ROOT', root)
    for name in ('REGISTRY', 'REGISTRY_V2', 'REGISTRY_V3', 'REGISTRY_V4', 'REGISTRY_V5'):
        monkeypatch.setattr(quota, name, root / (name + '.json'))
    monkeypatch.setattr(account_refresh, 'DB', root / 'scheduler.db')
    video = root / 'original.mp4'
    video.write_bytes(b'original same approved video')
    prepared = root / 'PREPARED.json'
    p = {'decision_source':'explicit_user_statement','full_film_accepted_for_publication':True,
        'user_statement':'原片批准发布','ai_generated':True,'fictional_story':True,'account_uuid':'acct:one','account_key':'one',
        'video':ref(video),'title':'Approved','description':'剧情虚构，非真实事件。','hashtags':['劳动法'],'visibility':'public'}
    prepared_ref = write(prepared, p)
    older = []
    for n, registry in enumerate((quota.REGISTRY, quota.REGISTRY_V2, quota.REGISTRY_V3, quota.REGISTRY_V4), 1):
        value = {'schema': [quota.SCHEMA, quota.SCHEMA_V2, quota.SCHEMA_V3, quota.SCHEMA_V4][n - 1],
            'utc_day':datetime.now(timezone.utc).date().isoformat(),'recovery_control_revision':41,
            'account_uuid':'acct:one','account_key':'one','video':p['video'],'prepared':prepared_ref,
            'idempotency_keys':{'publish':f'old-publish-{n}'},'max_daily_runs':[22,25,26,27][n-1]}
        path = root / f'OLD{n}.json'
        value_ref = write(path, value)
        write(registry, value_ref)
        older.append((value_ref, value))
    original_validator = quota.validate_authorization

    def isolated_old_validator(reference, **kwargs):
        for previous_ref, value in older:
            if reference == previous_ref:
                # Exact old file+registry remain real; only legacy semantic chain is isolated.
                assert quota._load_reference(reference)[0] == value
                return value
        return original_validator(reference, **kwargs)

    monkeypatch.setattr(quota, 'validate_authorization', isolated_old_validator)
    repository = AccountBindingRepository(root / 'account.db')
    binding = NS(account_uuid='acct:one',account_key='one',platform_identity_key='public:original',
        browser_environment_key='env:one',browser_profile_dir='profile/one',storage_state_path='state/one',
        confirmed_by='user',created_at='old',status='active')
    profile = NS(account_uuid='acct:one',account_key='one',profile_version=1,status='active')
    context = AccountRuntimeContext(profile,binding,'env:one','profile/one','state/one')
    runtime = object.__new__(AccountRuntimeService)
    runtime.resolve=lambda *a, **k:context
    runtime.profiles=NS(get=lambda *a:profile)
    runtime.bindings=NS(get_runtime_state=repository.get_runtime_state,get=lambda *a:binding,
        acquire_runtime=repository.acquire_runtime,release_runtime=repository.release_runtime,connection=repository.connection)
    resource = bridge.AccountBrowserResource(context,runtime)
    store = BrowserControlStore(root / 'data/account_browser_control.db')
    monkeypatch.setattr(bridge,'_store',lambda:store)
    monkeypatch.setattr(bridge,'_runtime',lambda:runtime)
    monkeypatch.setattr(bridge,'_legacy_manual_gate',lambda *a:None)
    monkeypatch.setattr(bridge,'_controls',lambda *a:quota.control_snapshot('acct:one'))
    from src.platform_adapter.models import PublishRequest
    from dataclasses import asdict
    request = PublishRequest(video_path=str(video),title=p['title'],description=p['description'],hashtags=p['hashtags'],
        visibility='public',ai_generated=True,fictional_story=True,extra_metadata={'account_uuid':'acct:one'})
    payload = {'account_uuid':'acct:one','account_key':'one','quota_authorization':older[-1][0],
        'authorization':prepared_ref,'video_sha256':p['video']['sha256'],'request':asdict(request)}
    original = store.submit('acct:one',bridge.binding_version(context),'publish','old-publish-4',payload)
    start = time.time() - 20
    with store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='failed',result=?,created_at=?,updated_at=? WHERE command_id=?",
            (_json({'status':'upload_failed','success':False,'post_id':'','publish_url':''}),start,start+15,original['command_id']))
    original = store.get(original['command_id'])
    monkeypatch.setattr(bounded,'PREVIOUS_COMMAND_ID',original['command_id'])
    key = hashlib.sha256(json.dumps({'platform_identity_key':'public:original','video_sha256':p['video']['sha256']},sort_keys=True).encode()).hexdigest()

    def journal(name, *, status='upload_failed', hashtag=False, extra=None, at=None):
        path = root / 'data/publish_runs' / (key + '.' + name + '.jsonl')
        first = {'stage':'prepared','account':'one','account_uuid':'acct:one','platform_identity_key':'public:original',
            'video_path':str(video),'video_sha256':p['video']['sha256'],'title':'Approved',
            'at_bjt':datetime.fromtimestamp(at or time.time(),timezone.utc).isoformat()}
        rows=[first, {'stage':'uploading'}]
        if extra: rows.append(extra)
        if hashtag: rows.extend([{'stage':'hashtags_readback','phase':'failed'},{'stage':'failed','error_type':'HashtagReadbackError'}])
        else: rows.append({'stage':status,'post_id':'','publish_url':''})
        path.write_text('\n'.join(_json(row) for row in rows),encoding='utf-8')
        return ref(path)

    previous_journal = journal('v4',at=start+5)
    original_no_alias=dict(original)
    original_no_alias.pop('task_id')
    final=write(root/'FINAL.json',{'original_command':original_no_alias,'new_submission_lock_exists':False,
        'journal':previous_journal['path'],'control':{'state':'active','revision':42},
        'runtime':{'daily_runs':27,'day_key':datetime.now(timezone.utc).date().isoformat(),'lock_owner':'','lock_expires_at':''}})
    approval={'schema':bounded.AUTH_SCHEMA,'decision_source':'explicit_user_statement','user_statement':'可以',
        'approval_question':'是否允许最多3次，仅明确提交前失败修复后续行，未知停止？','account_uuid':'acct:one','account_key':'one',
        'video':p['video'],'prepared':prepared_ref,'previous_authorization':older[-1][0],
        'previous_command':write(root/'PREVIOUS.json',original),'previous_command_id':original['command_id'],
        'previous_journal':previous_journal,'previous_final_state':final,'deployment_authorized':True,
        'additional_publication_runs':3,'additional_recovery_runs':0,'new_media_authorized':False,
        'utc_day':datetime.now(timezone.utc).date().isoformat(),'baseline_daily_runs':27,'max_daily_runs':30,
        'active_control_revision':42,'only_known_pre_submission_failures':True,'stop_on_unknown':True,
        'stop_on_human_required':True,'retain_original_history':True}
    authority=write(root/'USER_AUTHORIZATION.json',approval)
    monkeypatch.setattr(bounded,'APPROVAL_SHA256',authority['sha256'])
    value=bounded.build_bounded_authorization(authority)
    parent_path=root/'PARENT.json'
    parent=write(parent_path,value)
    prior={path:path.read_bytes() for path in (quota.REGISTRY,quota.REGISTRY_V2,quota.REGISTRY_V3,quota.REGISTRY_V4)}
    quota.register_authorization(parent_path,parent['sha256'])
    events=[]
    journals={}
    @bridge._with_active
    def publish(ctx,payload):
        index=payload['quota_attempt_index']
        with bridge._publication_lease(resource):
            events.append(repository.get_runtime_state('acct:one').daily_runs)
            journals[index]=journal(f'slot{index}',hashtag=index==2)
        return BrowserCommandResult('failed',{'status':'error' if index==2 else 'upload_failed','success':False,'post_id':'','publish_url':''})
    actor=BrowserControlActor(store,'acct:one',bridge.binding_version(context),'owner:one',{'publish':publish},
        context=resource,admission=bridge._admission)
    result=NS(root=root,store=store,actor=actor,repository=repository,resource=resource,parent=parent,value=value,
        parent_path=parent_path,prepared=prepared,journal=journal,journals=journals,events=events,key=key,prior=prior,older=older)
    yield result
    actor.stop_heartbeat()


def queue(f,index):
    return bridge.queue_prepared_publication(f.prepared,quota_authorization=f.parent,quota_attempt_index=index)


def continuation(f,index,**overrides):
    previous=f.store.get(next(c['command_id'] for c in f.store.snapshot('acct:one')['commands']
        if c['idempotency_key']==bounded.PUBLISH_KEYS[index-2]))
    source=write(f.root/f'PREDECESSOR_{index}.json',previous)
    return bounded.register_continuation(f.parent,index,previous_command_snapshot=source,
        previous_journal=overrides.get('journal',f.journals[index-1]))


def test_three_real_actor_slots28_29_30_repeat_no_consumption_and_immutable_proofs(ready):
    f=ready
    for index in (1,2,3):
        if index>1:
            proof=continuation(f,index)
            assert continuation(f,index)==proof
        command=queue(f,index)
        assert command['priority']==250 and command['payload']['quota_attempt_index']==index
        assert bounded.validate_attempt(f.parent,index)==27+index
        assert f.actor.run_next()['state']=='failed'
        assert queue(f,index)['command_id']==command['command_id']
        assert f.actor.run_next() is None
    assert f.events==[28,29,30] and f.repository.get_runtime_state('acct:one').daily_runs==30
    assert all(path.read_bytes()==body for path,body in f.prior.items())
    assert [quota.validate_authorization(r)['max_daily_runs'] for r,_ in f.older]==[22,25,26,27]
    with pytest.raises(BrowserControlRejected): queue(f,4)


def test_missing_or_skipped_index_and_slot1_cannot_acquire30(ready):
    f=ready
    for index in (None,True,0,2,3,4):
        with pytest.raises(BrowserControlRejected): queue(f,index)
    command=queue(f,1)
    ctx=NS(account_id='acct:one',command=command)
    control=quota.control_snapshot('acct:one')
    assert quota.authorized_daily_limit(ctx,'publish',account_uuid='acct:one',control=control)==28
    wrong=dict(command,payload=dict(command['payload'],quota_attempt_index=3))
    with pytest.raises(BrowserControlRejected):
        quota.authorized_daily_limit(NS(account_id='acct:one',command=wrong),'publish',account_uuid='acct:one',control=control)
    assert f.repository.get_runtime_state('acct:one').daily_runs==27


def test_unknown_human_and_submit_markers_reject_continuation_without_files(ready):
    f=ready
    command=queue(f,1)
    f.actor.run_next()
    before=f.store.get(command['command_id'])
    for state,status in (('outcome_unknown','submission_unknown'),('failed','human_required')):
        with f.store._db(write=True) as db:
            db.execute('UPDATE browser_control_commands SET state=?,result=? WHERE command_id=?',
                (state,_json(dict(before['result'],status=status)),command['command_id']))
        with pytest.raises(BrowserControlRejected): continuation(f,2)
    with f.store._db(write=True) as db:
        db.execute('UPDATE browser_control_commands SET state=?,result=? WHERE command_id=?',
            (before['state'],_json(before['result']),command['command_id']))
    for extra in ({'stage':'submission_started'},{'stage':'uploading','error_code':'human_required'}):
        journal=f.journal('bad'+str(len(extra)),extra=extra,at=before['created_at'])
        with pytest.raises(BrowserControlRejected): continuation(f,2,journal=journal)
    assert not bounded._continuation_path(2,'ref').exists()
    assert f.repository.get_runtime_state('acct:one').daily_runs==28


def test_registered_proof_revalidated_at_queue_admission_and_real_lease(ready):
    f=ready
    queue(f,1)
    first=f.actor.run_next()
    continuation(f,2)
    command=queue(f,2)
    # Change native predecessor after enqueue: admission must stop the handler.
    with f.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(first['command_id'],))
    assert f.actor.run_next() is None  # Original core's stronger unknown gate blocks even claiming.
    with f.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='failed',result=? WHERE command_id=?",
            (_json(dict(first['result'],status='human_required')),first['command_id']))
    assert f.actor.run_next()['state']=='failed'
    assert f.events==[28] and f.repository.get_runtime_state('acct:one').daily_runs==28
    with pytest.raises(BrowserControlRejected): queue(f,2)
    # The same proof gate is reached by the real operation lease, before acquire_runtime.
    ctx=NS(account_id='acct:one',command=command,resource=f.resource)
    @bridge._with_active
    def try_lease(ctx,payload):
        with bridge._publication_lease(f.resource): pytest.fail('invalid predecessor acquired lease')
    with pytest.raises(BrowserControlRejected): try_lease(ctx,command['payload'])


def test_lock_proof_replacement_generic_error_and_recovery_never_borrow_batch(ready):
    f=ready
    queue(f,1)
    before=f.actor.run_next()
    lock=f.root/'data/publish_runs'/(f.key+'.submitted.json')
    lock.write_text('{}',encoding='utf-8')
    with pytest.raises(BrowserControlRejected): continuation(f,2)
    lock.unlink()
    proof=continuation(f,2)
    copied=f.root/'OTHER_PREDECESSOR.json'
    original_ref=quota._load_reference(proof)[0]['previous_command']
    from pathlib import Path
    copied.write_bytes(Path(original_ref['path']).read_bytes())
    with pytest.raises(BrowserControlRejected):
        bounded.register_continuation(f.parent,2,previous_command_snapshot=ref(copied),previous_journal=f.journals[1])
    ctx=NS(account_id='acct:one',command={'kind':'recovery','idempotency_key':bounded.PUBLISH_KEYS[0],
        'payload':{'account_uuid':'acct:one','account_key':'one','quota_authorization':f.parent,'identity_probe_only':True}})
    with pytest.raises(BrowserControlRejected):
        quota.authorized_daily_limit(ctx,'identity-recovery',account_uuid='acct:one',control=quota.control_snapshot('acct:one'))
    assert quota.authorized_daily_limit(ctx,'manual-session',account_uuid='acct:one')==20
    assert quota.registered_recovery('one') is None
    with f.store._db(write=True) as db:
        db.execute('UPDATE browser_control_commands SET result=? WHERE command_id=?',
            (_json(dict(before['result'],status='error')),before['command_id']))
    with pytest.raises(BrowserControlRejected): continuation(f,2)
