"""Private broker/P0 SQLite only; no actor, browser, network or platform."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace as NS

import pytest

from test_publication_verification_recovery import incident
from src.operations_accounts import publication_abandonment_v1 as api
from src.operations_accounts import publication_verification_recovery as core
from src.operations_accounts.browser_control import BrowserControlRejected, _json


def ref(path):return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def case(incident,monkeypatch):
    i=incident; root=i.journal.parents[2]; monkeypatch.setattr(api,'ROOT',root)
    monkeypatch.setattr('src.operations_accounts.browser_control_runtime.binding_version',lambda context:'binding')
    i.runtime=NS(resolve=lambda *args,**kw:i.context)
    source=core._source(i.context,i.original)
    for attempt in range(1,6):
        command=i.store.submit(i.context.account_uuid,'binding','publication_verify','read:'+str(attempt),
            dict(original_command_id=i.original['command_id'],original_snapshot_sha256=core._digest(i.original),
                 source=source,attempt=attempt),100)
        # Local fixture emulates known completed reads without running a handler.
        with i.store._db(write=True) as db:
            db.execute("UPDATE browser_control_commands SET state='failed',result=?,updated_at=? WHERE command_id=?",
                (_json({'status':'verification_pending','reason':'independent_card_unbound'}),i.now[0],command['command_id']))
    def save(name,value):
        path=root/'data'/name;path.parent.mkdir(exist_ok=True,parents=True)
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return ref(path)
    media_path=root/'data/new_two_minutes.mp4';media_path.write_bytes(b'private media identity, no codec process')
    media=ref(media_path); authorization=save('new_publish_auth.json',{'media':media,'publish_authorized':True})
    payload=dict(i.original['payload'],video_sha256=media['sha256'],authorization=authorization,
                 request={**i.original['payload']['request'],'video_path':str(media_path),'title':'完整两分钟新视频'})
    replacement=i.store.submit(i.context.account_uuid,'binding','publish','new:'+media['sha256'],payload,100)
    account=dict(account_uuid=i.context.account_uuid,account_key=i.context.account_key,binding_version='binding')
    candidate=dict(candidate_id='new-candidate',media_sha=media['sha256'],command_id=replacement['command_id'],
        frozen_json=json.dumps(dict(media=media,account=account)),prepared_json=json.dumps(dict(request=payload['request'],authorization=authorization)))
    candidate_db=root/'data/p0.db'
    with sqlite3.connect(candidate_db) as db:
        db.execute('CREATE TABLE fanqie_h3_candidates(candidate_id TEXT,media_sha TEXT,command_id TEXT,frozen_json TEXT,prepared_json TEXT)')
        db.execute('INSERT INTO fanqie_h3_candidates VALUES(?,?,?,?,?)',tuple(candidate.values()))
    preceding='合并前后两分钟，发布完整版本后回填'
    scope=save('new_scope.json',dict(user_statement=preceding,authorized_target=dict(media=media,douyin_account_key=i.context.account_key)))
    authority=dict(schema=api.AUTH,decision_source='explicit_user_statement',
        user_statement='之前的视频可以放弃应该是需要上传一个2分钟的新链接的吧',preceding_user_statement=preceding,
        original_command_id=i.original['command_id'],replacement_command_id=replacement['command_id'],
        replacement_candidate_id=candidate['candidate_id'],replacement_media=media,replacement_scope_authority=scope,
        expected_prior_verification_count=5,created_at=i.now[0],**account,
        **{k:True for k in api.RETAIN},**{k:False for k in api.DENY})
    authority_ref=save('abandon_authority.json',authority)
    code_dir=root/'src/operations_accounts';code_dir.mkdir(parents=True)
    real=Path(api.__file__).parent
    for name in ('publication_abandonment_v1.py','browser_control.py'):shutil.copyfile(real/name,code_dir/name)
    i.plan_dir=root/'data/new_abandonment'
    i.candidate_db=candidate_db;i.authority=authority_ref;i.authority_value=authority
    i.replacement=replacement;i.save=save;i.candidate=candidate;i.root=root
    return i


def prepare(i):return api.prepare(i.authority,output_directory=i.plan_dir,store=i.store,runtime=i.runtime,candidate_db=i.candidate_db)
def execute(i,p):return api.execute(p,store=i.store,runtime=i.runtime,requested_by='operator:authorized-user-request')
def prior(i):
    with i.store._db() as db:return core._attempts(i.store,db,i.original['command_id'])


def test_prepare_is_readonly_and_public_operator_abandons_once_retaining_unknown(case):
    i=case; original=i.store.get(i.original['command_id']); reads=prior(i)
    lock,journal=i.lock.read_bytes(),i.journal.read_bytes()
    with i.store._db() as db:owner=dict(db.execute('SELECT * FROM browser_control_owners').fetchone())
    candidate_bytes=i.candidate_db.read_bytes()
    p=prepare(i)
    assert i.store.get(original['command_id'])==original and i.store.get(i.replacement['command_id'])==i.replacement
    result=execute(i,p)
    assert result['state']=='failed' and result['error_code']==api.ERROR
    r=result['result']
    assert r['before_snapshot']==original and r['original_unknown_result']==original['result']
    assert r['original_outcome_known'] is False and r['original_platform_work_deleted'] is False
    assert r['superseded_by']==i.replacement['command_id']
    assert execute(i,p)==result
    assert i.store.get(i.replacement['command_id'])==i.replacement and prior(i)==reads
    assert i.lock.read_bytes()==lock and i.journal.read_bytes()==journal and i.candidate_db.read_bytes()==candidate_bytes
    with i.store._db() as db:assert dict(db.execute('SELECT * FROM browser_control_owners').fetchone())==owner


@pytest.mark.parametrize('change',['original','source','lock','prior','replacement','candidate','binding','owner_expired','owner_generation','other_manual','other_unknown','authority','code'])
def test_execute_rechecks_every_frozen_subject_and_leaves_original_unknown(case,monkeypatch,change):
    i=case;p=prepare(i)
    if change=='source':i.journal.write_text('{}\n')
    elif change=='lock':i.lock.write_text('{}')
    elif change=='authority':Path(i.authority['path']).write_text('{}')
    elif change=='code':(i.root/'src/operations_accounts/publication_abandonment_v1.py').write_text('# changed')
    elif change=='binding':monkeypatch.setattr('src.operations_accounts.browser_control_runtime.binding_version',lambda _: 'new-binding')
    elif change=='candidate':
        with sqlite3.connect(i.candidate_db) as db:db.execute("UPDATE fanqie_h3_candidates SET media_sha='wrong'")
    else:
        with i.store._db(write=True) as db:
            if change=='original':db.execute('UPDATE browser_control_commands SET updated_at=updated_at+1 WHERE command_id=?',(i.original['command_id'],))
            elif change=='prior':db.execute("UPDATE browser_control_commands SET result='{}' WHERE command_id=?",(prior(i)[0]['command_id'],))
            elif change=='replacement':db.execute("UPDATE browser_control_commands SET state='running' WHERE command_id=?",(i.replacement['command_id'],))
            elif change=='owner_expired':db.execute('UPDATE browser_control_owners SET heartbeat=0')
            elif change=='owner_generation':db.execute('UPDATE browser_control_owners SET generation=2')
        if change in ('other_manual','other_unknown'):
            extra=i.store.submit(i.context.account_uuid,'binding','manual' if change=='other_manual' else 'read',change,{},10)
            with i.store._db(write=True) as db:db.execute('UPDATE browser_control_commands SET state=? WHERE command_id=?',
                ('waiting_human' if change=='other_manual' else 'outcome_unknown',extra['command_id']))
    with pytest.raises((BrowserControlRejected,KeyError,ValueError)):execute(i,p)
    assert i.store.get(i.original['command_id'])['state']=='outcome_unknown'


@pytest.mark.parametrize('field',['decision_source','retain_platform_work','retain_submission_lock','delete_platform_work','preceding_user_statement'])
def test_missing_explicit_abandonment_retention_or_replacement_scope_cannot_prepare(case,field):
    i=case;value=dict(i.authority_value)
    value[field]= 'inferred' if field=='decision_source' else 'different' if field=='preceding_user_statement' else False if field.startswith('retain_') else True
    i.authority=i.save('bad_authority.json',value)
    with pytest.raises(BrowserControlRejected):prepare(i)
    assert not (i.plan_dir/'PLAN.json').exists()


def test_operator_does_not_impersonate_live_browser_owner(case):
    i=case;p=prepare(i)
    with pytest.raises(BrowserControlRejected):
        i.store.operator_abandon_unknown_publication(p,requested_by='backend:123:abc',runtime=i.runtime)
    assert i.store.get(i.original['command_id'])['state']=='outcome_unknown'


def test_unentered_queued_maintenance_is_frozen_and_preserved_without_cancel(case):
    i=case
    maintenance=i.store.submit(i.context.account_uuid,'binding','maintenance','daily-existing',{'mode':'recommend_feed'},20)
    p=prepare(i)
    data=json.loads(Path(p['path']).read_text(encoding='utf8'))
    assert data['retained_queued_maintenance'][0]['command']==maintenance
    assert data['retained_queued_maintenance'][0]['execution']['current'] is None
    result=execute(i,p)
    assert result['state']=='failed' and result['error_code']==api.ERROR
    assert i.store.get(maintenance['command_id'])==maintenance


@pytest.mark.parametrize('change',['running','row_changed','handler_evidence'])
def test_queued_maintenance_is_not_idle_if_dispatched_changed_or_historically_entered(case,change):
    i=case
    maintenance=i.store.submit(i.context.account_uuid,'binding','maintenance','daily-existing',{'mode':'recommend_feed'},20)
    p=prepare(i)
    with i.store._db(write=True) as db:
        if change=='running':db.execute("UPDATE browser_control_commands SET state='running' WHERE command_id=?",(maintenance['command_id'],))
        elif change=='row_changed':db.execute('UPDATE browser_control_commands SET updated_at=updated_at+1 WHERE command_id=?',(maintenance['command_id'],))
        else:
            from src.operations_accounts.browser_execution_journal import record
            record(db,{**maintenance,'owner_id':'backend:123:abc','generation':1},'handler_entered',i.now[0],entered=True)
    with pytest.raises(BrowserControlRejected):execute(i,p)
    assert i.store.get(i.original['command_id'])['state']=='outcome_unknown'
