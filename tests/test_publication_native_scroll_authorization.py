"""Real v7->v8 actor/SQLite; only v1-v6 semantics isolated by the minimal shared fixture."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_native_scroll_authorization as native
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserCommandResult, BrowserControlRejected, _json
from test_publication_scoped_popup_authorization import grant as previous_grant, account_seed
from test_publication_bounded_retry_authorization import write, ref


@pytest.fixture
def grant(previous_grant,monkeypatch):
    g=previous_grant; root=g.root
    monkeypatch.setattr(quota,'REGISTRY_V8',root/'REGISTRY_V8.json')
    old_key=g.value['video']['sha256']
    key=hashlib.sha256(json.dumps({'platform_identity_key':'public:original','video_sha256':old_key},sort_keys=True).encode()).hexdigest()
    journal=root/'data/publish_runs'/(key+'.v7-upload-failed.jsonl')
    @bridge._with_active
    def original_v7(ctx,payload):
        with bridge._publication_lease(g.resource):
            g.events.append(g.repository.get_runtime_state('acct:one').daily_runs)
            rows=[{'stage':'prepared','account':'one','account_uuid':'acct:one','platform_identity_key':'public:original',
                'video_path':g.value['video']['path'],'video_sha256':old_key,'title':'Approved',
                'at_bjt':datetime.now(timezone.utc).isoformat()},{'stage':'upload_failed','post_id':'','publish_url':''}]
            journal.write_text('\n'.join(_json(v) for v in rows),encoding='utf-8')
        return BrowserCommandResult('failed',{'status':'upload_failed','success':False,'post_id':'','publish_url':''})
    g.actor.handlers['publish']=original_v7
    bridge.queue_prepared_publication(g.prepared,quota_authorization=g.parent)
    before=g.actor.run_next()
    assert g.events==[32]
    monkeypatch.setattr(native,'PREVIOUS_COMMAND_ID',before['command_id'])
    repair=root/'src/shared/upload_check_transition.py'; repair.parent.mkdir(parents=True,exist_ok=True); repair.write_bytes(b'native original scroll repair')
    workflow=root/'src/platform_adapter/publish_workflow.py'; workflow.write_bytes(b'original native scroll workflow')
    monkeypatch.setattr(native,'REPAIR_SHA256',ref(repair)['sha256']); monkeypatch.setattr(native,'WORKFLOW_SHA256',ref(workflow)['sha256'])
    for relative,source in ((native.REPAIR_SNAPSHOT,repair),(native.WORKFLOW_SNAPSHOT,workflow)):
        target=root/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(source.read_bytes())
    primary=root/native.PRIMARY_REVIEW
    primary_ref=write(primary,{'source_sha256':{'src/shared/upload_check_transition.py':native.REPAIR_SHA256,
        'src/platform_adapter/publish_workflow.py':native.WORKFLOW_SHA256},'source_ast_and_necessary_real_dom_worker_tests_reviewed':True})
    monkeypatch.setattr(native,'PRIMARY_REVIEW_SHA256',primary_ref['sha256'])
    final=write(root/'V7_FINAL.json',{'original_command':before,'journal':ref(journal),'runtime':{'daily_runs':32,
        'day_key':g.value['utc_day'],'lock_owner':'','lock_expires_at':''},'control':{'state':'active','revision':42},
        'platform_submission_started':False,'publication_completed':False,'submission_locks':g.locks,
        'new_runs_used':1,'new_runs_remaining':0,'no_second_run_dispatched':True})
    approval={'schema':native.AUTH_SCHEMA,'decision_source':'explicit_user_statement','user_statement':'追加1次，部署并继续发布',
        'approval_question':'是否追加1次部署新修复后继续发布？','account_uuid':'acct:one','account_key':'one','prepared':g.value['prepared'],
        'video':g.value['video'],'previous_authorization':g.parent,'previous_command':write(root/'V7_TERMINAL.json',before),
        'previous_command_id':before['command_id'],'previous_journal':ref(journal),'previous_final_state':final,
        'repair_source':ref(repair),'repair_workflow':ref(workflow),'repair_primary_review':primary_ref,
        'deployment_authorized':True,'additional_publication_runs':1,'additional_recovery_runs':0,'new_media_authorized':False,
        'retain_original_history':True,'stop_on_unknown':True,'stop_on_human_required':True,'utc_day':g.value['utc_day'],
        'baseline_daily_runs':32,'max_daily_runs':33,'active_control_revision':42}
    authority=write(root/'V8_USER_AUTHORIZATION.json',approval)
    monkeypatch.setattr(native,'APPROVAL_SHA256',authority['sha256'])
    value=native.build_native_scroll_authorization(authority); path=root/'V8_FROZEN.json'; parent=write(path,value)
    prior={p:p.read_bytes() for p in (*g.prior.keys(),quota.REGISTRY_V7)}
    quota.register_authorization(path,parent['sha256'])
    return NS(g=g,value=value,path=path,parent=parent,before=before,prior=prior,repair=repair,workflow=workflow)


def queue8(f,**kwargs): return bridge.queue_prepared_publication(f.g.prepared,quota_authorization=f.parent,**kwargs)


def test_real32_to33_once_keeps_old_v7_cap32_and_registry_bytes(grant):
    f,g=grant,grant.g
    @bridge._with_active
    def publish(ctx,payload):
        assert 'quota_attempt_index' not in payload
        with bridge._publication_lease(g.resource): g.events.append(g.repository.get_runtime_state('acct:one').daily_runs)
        return {'published_once':True}
    g.actor.handlers['publish']=publish
    command=queue8(f)
    assert command['priority']==250 and command['idempotency_key']==native.PUBLISH_KEY
    assert g.actor.run_next()['state']=='succeeded' and g.events==[32,33]
    assert queue8(f)['command_id']==command['command_id'] and g.actor.run_next() is None
    assert g.repository.get_runtime_state('acct:one').daily_runs==33
    assert all(p.read_bytes()==body for p,body in f.prior.items())
    assert quota.validate_authorization(g.parent)['max_daily_runs']==32


def test_unknown_human_lock_and_changed_workflow_snapshot_fail_before_consume(grant):
    f,g=grant,grant.g
    for state,status in (('outcome_unknown','submission_unknown'),('failed','human_required')):
        with g.store._db(write=True) as db:
            db.execute('UPDATE browser_control_commands SET state=?,result=? WHERE command_id=?',
                (state,_json(dict(f.before['result'],status=status)),f.before['command_id']))
        with pytest.raises(BrowserControlRejected): queue8(f)
    with g.store._db(write=True) as db:
        db.execute('UPDATE browser_control_commands SET state=?,result=? WHERE command_id=?',
            (f.before['state'],_json(f.before['result']),f.before['command_id']))
    lock=Path(g.locks[0]['path']); lock.write_text('{}',encoding='utf-8')
    with pytest.raises(BrowserControlRejected): queue8(f)
    lock.unlink()
    (g.root/native.WORKFLOW_SNAPSHOT).write_bytes(b'changed frozen workflow')
    with pytest.raises(BrowserControlRejected): queue8(f)
    assert g.repository.get_runtime_state('acct:one').daily_runs==32


def test_exact_cap_key_no_index_default20_and_expired_history(grant,monkeypatch):
    f,g=grant,grant.g
    for index in (1,2,3):
        with pytest.raises(BrowserControlRejected): queue8(f,quota_attempt_index=index)
    for field,new_value in (('max_daily_runs',34),('active_control_revision',43),('repair_workflow',{'path':str(f.workflow),'sha256':'0'*64})):
        value=deepcopy(f.value); value[field]=new_value
        with pytest.raises(BrowserControlRejected): quota.validate_authorization(write(g.root/(field+'.json'),value),require_registered=False)
    command=queue8(f)
    for changed in (dict(command,idempotency_key='another-key'),dict(command,kind='recovery'),
            dict(command,payload=dict(command['payload'],quota_attempt_index=None))):
        with pytest.raises(BrowserControlRejected):
            quota.authorized_daily_limit(NS(account_id='acct:one',command=changed),
                'identity-recovery' if changed['kind']=='recovery' else 'publish',account_uuid='acct:one',control=quota.control_snapshot('acct:one'))
    assert quota.authorized_daily_limit(NS(command={'kind':'manual'}),'manual-session',account_uuid='acct:one')==20
    assert quota.registered_recovery('one') is None
    f.repair.write_bytes(b'future helper version'); f.workflow.write_bytes(b'future workflow version')
    from src.operations_accounts import publication_scoped_popup_authorization as previous
    class NextDay(datetime):
        @classmethod
        def now(cls,tz=None): return datetime(2026,10,20,tzinfo=timezone.utc)
    for module in (native,previous,quota): monkeypatch.setattr(module,'datetime',NextDay)
    assert quota.validate_authorization(f.parent,allow_expired=True)['max_daily_runs']==33
    with pytest.raises(BrowserControlRejected): queue8(f)
    assert g.repository.get_runtime_state('acct:one').daily_runs==32
