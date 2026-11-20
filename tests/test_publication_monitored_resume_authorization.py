"""v6 real managed lease and real v5 slot proofs; only older v1-v4 validator isolated."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_monitored_resume_authorization as monitored
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserCommandResult, BrowserControlRejected, _json
from test_publication_bounded_retry_authorization import account_seed, ready, queue, continuation, write, ref


@pytest.fixture
def grant(ready, monkeypatch):
    f=ready
    monkeypatch.setattr(quota,'REGISTRY_V6',f.root/'REGISTRY_V6.json')
    for index in (1,2):
        if index==2: continuation(f,2)
        queue(f,index)
        assert f.actor.run_next()['state']=='failed'
    continuation(f,3)
    @bridge._with_active
    def original_slot3(ctx,payload):
        with bridge._publication_lease(f.resource):
            f.events.append(f.repository.get_runtime_state('acct:one').daily_runs)
            f.journals[3]=f.journal('slot3',status='ai_declaration_unverified')
        return BrowserCommandResult('failed',{'status':'ai_declaration_unverified','success':False,'post_id':'','publish_url':''})
    f.actor.handlers['publish']=original_slot3
    queue(f,3)
    before=f.actor.run_next()
    assert f.events==[28,29,30]
    monkeypatch.setattr(monitored,'PREVIOUS_COMMAND_ID',before['command_id'])
    commands=[c for c in f.store.snapshot('acct:one')['commands'] if c['idempotency_key'] in f.value['idempotency_keys']['publish']]
    video=f.value['video']
    locks=[]
    for identity in ({'platform_identity_key':'public:original','video_sha256':video['sha256']},
            {'account':'one','video_sha256':video['sha256']}):
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        locks.append({'path':str((f.root/'data/publish_runs'/(key+'.submitted.json')).resolve()),'exists':False})
    final=write(f.root/'V5_FINAL.json',{'original_command':before,'commands':commands,'journal':f.journals[3],
        'runtime':{'daily_runs':30,'day_key':f.value['utc_day'],'lock_owner':'','lock_expires_at':''},
        'control':{'state':'active','revision':42},'submission_locks':locks,'platform_submission_started':False,
        'publication_completed':False,'new_runs_used':3,'new_runs_remaining':0})
    approval={'schema':monitored.AUTH_SCHEMA,'decision_source':'explicit_user_statement',
        'user_statement':'之前自动化流程是正常的，你可以启动并监控吗',
        'clarification_question':'你说的之前自动化流程指哪一个？','clarification_answer':'视频的自动发布流程',
        'scope_interpretation':'新请求启动同片自动发布一次并监控；不将旧三次上限改大、不自动重试',
        'account_uuid':'acct:one','account_key':'one','video':video,'prepared':f.value['prepared'],
        'previous_authorization':f.parent,'previous_command':write(f.root/'V5_SLOT3.json',before),
        'previous_command_id':before['command_id'],'previous_journal':f.journals[3],'previous_final_state':final,
        'deployment_authorized':True,'additional_publication_runs':1,'additional_recovery_runs':0,
        'new_media_authorized':False,'retain_original_history':True,'stop_on_unknown':True,'stop_on_human_required':True,
        'utc_day':f.value['utc_day'],'baseline_daily_runs':30,'max_daily_runs':31,'active_control_revision':42}
    authority=write(f.root/'V6_USER_AUTHORIZATION.json',approval)
    monkeypatch.setattr(monitored,'APPROVAL_SHA256',authority['sha256'])
    value=monitored.build_monitored_authorization(authority)
    path=f.root/'V6_FROZEN.json'
    reference=write(path,value)
    prior={p:p.read_bytes() for p in (*f.prior.keys(),quota.REGISTRY_V5)}
    quota.register_authorization(path,reference['sha256'])
    return NS(f=f,value=value,path=path,ref=reference,before=before,prior=prior,locks=locks)


def queue6(g,**kwargs):
    return bridge.queue_prepared_publication(g.f.prepared,quota_authorization=g.ref,**kwargs)


def test_one_real_actor30_to31_duplicate_no_consumption_old_v5_stays30(grant):
    g,f=grant,grant.f
    @bridge._with_active
    def publish(ctx,payload):
        assert 'quota_attempt_index' not in payload
        with bridge._publication_lease(f.resource):
            f.events.append(f.repository.get_runtime_state('acct:one').daily_runs)
        return {'one_new_start':True}
    f.actor.handlers['publish']=publish
    command=queue6(g)
    assert command['priority']==250 and command['idempotency_key']==monitored.PUBLISH_KEY
    assert f.actor.run_next()['state']=='succeeded'
    assert f.events==[28,29,30,31] and f.repository.get_runtime_state('acct:one').daily_runs==31
    assert queue6(g)['command_id']==command['command_id'] and f.actor.run_next() is None
    assert quota.validate_authorization(f.parent)['max_daily_runs']==30
    assert all(p.read_bytes()==body for p,body in g.prior.items())
    assert g.value['user_statement']=='之前自动化流程是正常的，你可以启动并监控吗'
    assert g.value['scope_interpretation'].startswith('新请求启动同片自动发布一次')


def test_no_index_recovery_wrong_key_control_or_larger_budget(grant):
    g,f=grant,grant.f
    for index in (1,2,3):
        with pytest.raises(BrowserControlRejected): queue6(g,quota_attempt_index=index)
    for change in ('cap','key','revision','scope'):
        value=deepcopy(g.value)
        if change=='cap': value['max_daily_runs']=32
        if change=='key': value['idempotency_keys']['publish']='second-new-key'
        if change=='revision': value['active_control_revision']=43
        if change=='scope': value['scope_interpretation']='重写用户逐字批准数字1'
        candidate=write(f.root/(change+'.json'),value)
        with pytest.raises(BrowserControlRejected): quota.validate_authorization(candidate,require_registered=False)
    command=queue6(g)
    control=quota.control_snapshot('acct:one')
    for changed in (dict(command,payload=dict(command['payload'],quota_attempt_index=None)),
            dict(command,idempotency_key='different-key'),dict(command,kind='recovery')):
        with pytest.raises(BrowserControlRejected):
            quota.authorized_daily_limit(NS(account_id='acct:one',command=changed),
                'identity-recovery' if changed['kind']=='recovery' else 'publish',account_uuid='acct:one',control=control)
    with pytest.raises(BrowserControlRejected):
        quota.authorized_daily_limit(NS(account_id='acct:one',command=command),'publish',account_uuid='acct:one',
            control=dict(control,revision=43))
    assert quota.authorized_daily_limit(NS(command={'kind':'manual'}),'manual-session',account_uuid='acct:one')==20
    assert quota.registered_recovery('one') is None
    assert f.repository.get_runtime_state('acct:one').daily_runs==30


def test_unknown_or_changed_native_slot3_rejects_without_consumption(grant):
    g,f=grant,grant.f
    with f.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(g.before['command_id'],))
    with pytest.raises(BrowserControlRejected): queue6(g)
    with f.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='failed' WHERE command_id=?",(g.before['command_id'],))
    path=f.journals[3]['path']
    from pathlib import Path
    Path(path).write_bytes(Path(path).read_bytes()+b'\n')
    with pytest.raises(BrowserControlRejected): queue6(g)
    assert f.repository.get_runtime_state('acct:one').daily_runs==30


def test_locks_missing_prior_slot_proof_or_registry_replacement_fail_closed(grant):
    g,f=grant,grant.f
    from pathlib import Path
    lock=Path(g.locks[0]['path'])
    lock.write_text('{}',encoding='utf-8')
    with pytest.raises(BrowserControlRejected): queue6(g)
    lock.unlink()
    proof=quota.REGISTRY_V5.parent/'publication_bounded_retry_20261019.slot3.ref.json'
    original=proof.read_bytes()
    proof.write_text('{}',encoding='utf-8')
    with pytest.raises(BrowserControlRejected): queue6(g)
    proof.write_bytes(original)
    assert quota.register_authorization(g.path,g.ref['sha256'])==g.ref
    other=f.root/'OTHER_V6.json'
    other.write_bytes(g.path.read_bytes())
    with pytest.raises(BrowserControlRejected): quota.register_authorization(other,ref(other)['sha256'])
    assert f.repository.get_runtime_state('acct:one').daily_runs==30


def test_expired_grant_allows_explicit_history_read_but_no_new_queue_or_lease(grant,monkeypatch):
    from src.operations_accounts import publication_bounded_retry_authorization as bounded
    g,f=grant,grant.f
    command=queue6(g)
    class NextDay(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,20,tzinfo=timezone.utc)
    for module in (monitored,bounded,quota):
        monkeypatch.setattr(module,'datetime',NextDay)
    assert quota.validate_authorization(g.ref,allow_expired=True)['max_daily_runs']==31
    with pytest.raises(BrowserControlRejected): quota.validate_authorization(g.ref)
    with pytest.raises(BrowserControlRejected): queue6(g)
    with pytest.raises(BrowserControlRejected):
        quota.authorized_daily_limit(NS(account_id='acct:one',command=command),'publish',account_uuid='acct:one',
            control=quota.control_snapshot('acct:one'))
    assert f.repository.get_runtime_state('acct:one').daily_runs==30
