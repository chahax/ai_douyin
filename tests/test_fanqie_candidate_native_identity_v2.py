"""Real P0 schema migration and native alias identity integration."""
import sqlite3
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.services.fanqie_h3_candidate_v1 import migrate,CandidateLedger,CandidateBlocked
from test_fanqie_h3_candidate_v1 import case,browser_receipt
from test_fanqie_promotion_identity_v2 import make_case,prepare


def native_snapshot(x,folder,identity='uid:synthetic',**updates):
    data=make_case(folder,identity=identity,native_updates=dict(book_id='123',book_name='test book',alias_name='keyword',**updates),
        dom_updates=dict(book_id='123',book_name='test book',alias='keyword'))
    snap=prepare(data,folder)
    binding={**x['binding'],**{k:snap[k] for k in ('resource_id','binding_version','platform_identity_key','environment_key')}}
    x['store'].clock=lambda:data['at']+2
    return snap,binding


def extra_candidate(x,name):
    media=x['save'](name+'.mp4',name+' synthetic media')
    h=dict(x['h'],media_binding=media)
    result=json.loads(Path(x['result']['path']).read_text());result['file']=media
    h['assembly_receipt_binding']=x['save'](name+'result.json',result)
    p=json.loads(Path(x['provenance']['path']).read_text());p.update(media=media,assembly_result=h['assembly_receipt_binding'])
    qa=json.loads(Path(x['qa']['path']).read_text());qa.update(file=media,result=h['assembly_receipt_binding'])
    return x['store'].register_pending(x['save'](name+'handoff.json',h),provenance_ref=x['save'](name+'provenance.json',p),
        technical_review_ref=x['save'](name+'qa.json',qa),account_binding=x['account'])


def baseline(path):
    with sqlite3.connect(path) as db:
        db.executescript(Path('tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text('utf8'))
        db.execute("INSERT INTO fanqie_books(book_uuid,fanqie_book_id,book_name) VALUES('book','123','test book')")
        db.execute("INSERT INTO fanqie_promotion_tasks(task_uuid,book_id,platform_task_id,promotion_alias,publish_type,status) VALUES('old',1,'old-platform-task','same-keyword','AIGC','verified')")


def test_migration_preserves_old_rows_backup_and_legacy_alias_uniqueness(tmp_path):
    path=tmp_path/'p0.db';baseline(path)
    with sqlite3.connect(path) as db:before=db.execute('SELECT * FROM fanqie_promotion_tasks').fetchall()
    backup=tmp_path/'before.db';migrate(path,backup)
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT * FROM fanqie_promotion_tasks').fetchall()==before
        assert 'native_identity_scope' not in [r[1] for r in db.execute('PRAGMA table_info(fanqie_promotion_tasks)')]
    with sqlite3.connect(path) as db:
        after=db.execute('SELECT * FROM fanqie_promotion_tasks').fetchall()
        assert [r[:-1] for r in after]==before and all(r[-1] is None for r in after)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fanqie_promotion_tasks(task_uuid,book_id,promotion_alias,publish_type,status) VALUES('duplicate',1,'same-keyword','AIGC','verified')")
    CandidateLedger(path)


def test_wrong_legacy_index_refused_before_backup_or_migration(tmp_path):
    path=tmp_path/'p0.db';baseline(path)
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX uq_fanqie_task_active_alias')
        db.execute('CREATE UNIQUE INDEX uq_fanqie_task_active_alias ON fanqie_promotion_tasks(book_id,promotion_alias)')
    backup=tmp_path/'before.db'
    with pytest.raises(CandidateBlocked):migrate(path,backup)
    assert not backup.exists()
    with sqlite3.connect(path) as db:
        assert 'native_identity_scope' not in [r[1] for r in db.execute('PRAGMA table_info(fanqie_promotion_tasks)')]


def test_partial_native_mapping_refused_without_repair(tmp_path):
    path=tmp_path/'p0.db';baseline(path)
    migrate(path,tmp_path/'before.db')
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE fanqie_native_promotion_identities')
        db.execute('CREATE TABLE fanqie_native_promotion_identities(task_id INTEGER)')
    with pytest.raises(CandidateBlocked,match='mapping_incompatible'):CandidateLedger(path)
    with pytest.raises(CandidateBlocked):migrate(path,tmp_path/'second_backup.db')
    assert not (tmp_path/'second_backup.db').exists()


def test_index_changed_after_backup_is_rechecked_inside_transaction(tmp_path,monkeypatch):
    path=tmp_path/'p0.db';baseline(path)
    real_connect=sqlite3.connect
    class ChangedAfterBackup(sqlite3.Connection):
        def backup(self,target,**kwargs):
            super().backup(target,**kwargs)
            with real_connect(path) as other:
                other.execute('DROP INDEX uq_fanqie_task_active_alias')
                other.execute('CREATE UNIQUE INDEX uq_fanqie_task_active_alias ON fanqie_promotion_tasks(book_id,promotion_alias)')
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**kw:real_connect(*a,**dict(kw,factory=ChangedAfterBackup)))
    with pytest.raises(CandidateBlocked):migrate(path,tmp_path/'backup.db')
    with real_connect(path) as db:
        assert 'native_identity_scope' not in [r[1] for r in db.execute('PRAGMA table_info(fanqie_promotion_tasks)')]
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='uq_fanqie_task_active_alias'").fetchone()[0]=='CREATE UNIQUE INDEX uq_fanqie_task_active_alias ON fanqie_promotion_tasks(book_id,promotion_alias)'


def test_native_same_alias_multiple_media_and_cross_identity_separate_tasks(case,tmp_path):
    x=case;s,b=native_snapshot(x,tmp_path/'a');row=s['rows'][0]
    first=x['store'].bind_promotion(x['cid'],s,row,b)
    same=x['store'].bind_promotion(extra_candidate(x,'second'),s,row,b)
    assert same['task_id']==first['task_id'] and same['video_job_id']!=first['video_job_id']
    other,ob=native_snapshot(x,tmp_path/'b',identity='uid:other')
    different=x['store'].bind_promotion(extra_candidate(x,'third'),other,other['rows'][0],ob)
    assert different['task_id']!=first['task_id']
    with sqlite3.connect(x['db']) as db:
        records=db.execute('SELECT platform_task_id,native_identity_scope,promotion_alias FROM fanqie_promotion_tasks ORDER BY id').fetchall()
        assert len(records)==2 and all(r[0] is None and r[2]=='keyword' for r in records)
        assert records[0][1]!=records[1][1]
    facts=x['store'].verify_native_task(first['task_id'],snapshot=s,row=row)
    assert facts['native_identity']['native_record_id']==row['native_record_id']
    with pytest.raises(CandidateBlocked):x['store'].verify_native_task(first['task_id'],snapshot=other,row=other['rows'][0])


def test_native_authorization_subject_version_and_mode_are_exact(case,tmp_path):
    from src.services.fanqie_h3_candidate_v1 import digest,task_identity
    from src.platform_adapter.models import PublishRequest
    x=case;s,b=native_snapshot(x,tmp_path/'a');row=s['rows'][0]
    x['store'].bind_promotion(x['cid'],s,row,b);x['review']()
    request=PublishRequest(video_path=x['media']['path'],title=x['metadata']['title'],description=x['metadata']['description'],
        hashtags=x['metadata']['hashtags'],extra_metadata={'account_uuid':'account:test'})
    auth=dict(schema='fanqie_publication_authorization/v2',candidate_id=x['cid'],media=x['media'],account_uuid='account:test',publish_authorized=True,
        decision_source='explicit_user_statement',user_statement='Publish exact synthetic fixture',metadata_sha256=digest(asdict(request)),
        promotion_subject_sha256=digest({'row':task_identity(row,s),'binding':b}))
    def call(value):return x['store'].prepare_publish(x['cid'],snapshot=s,row=row,resource_binding=b,metadata=x['metadata'],authorization_ref=x['save']('auth'+str(len(value))+value.get('schema','') .replace('/','_')+'.json',value))
    with pytest.raises(CandidateBlocked,match='version_required'):call({**auth,'schema':'fanqie_publication_authorization/v1'})
    prepared=call(auth)
    assert prepared['promotion']['row']['identity']['native_record_id']==row['native_record_id']
    changed,cb=native_snapshot(x,tmp_path/'changed',task_type=7)
    with pytest.raises(CandidateBlocked,match='promotion_changed'):
        x['store'].prepare_publish(x['cid'],snapshot=changed,row=changed['rows'][0],resource_binding=cb,metadata=x['metadata'],authorization_ref=x['save']('oldauth.json',auth))
    calls=[]
    def queue(*args,**kwargs):calls.append(args);return {'command_id':'cmd1'}
    assert x['store'].dispatch(x['cid'],snapshot=s,row=row,resource_binding=b,queue=queue)=='cmd1'
    assert x['store'].dispatch(x['cid'],snapshot=s,row=row,resource_binding=b,queue=queue)=='cmd1'
    assert len(calls)==1
    payload=dict(request=prepared['request'],authorization=prepared['authorization'],video_sha256=x['media']['sha256'],account_key='novel')
    browser=browser_receipt(x,payload,published_at=None)
    with sqlite3.connect(browser) as db:
        db.execute('INSERT INTO browser_control_commands(command_id,account_id,binding_version,state,kind,result,payload) VALUES(?,?,?,?,?,?,?)',
            ('sync1','account:test','dv1','succeeded','read',json.dumps({'read_result':{'success':True,'videos':[
                {'video_id':'123456789012345','account_uuid':'account:test','account_key':'novel','publish_time':'2026年11月16日 14:30'}]}}),json.dumps({'method':'sync_videos'})))
    handoff=x['store'].attach_publication(x['cid'],command_id='cmd1',browser_db=browser,evidence_directory=tmp_path/'evidence',metadata_command_id='sync1')
    assert handoff['schema']=='fanqie_h3_publication_handoff/v2'
    assert handoff['promotion_subject']==prepared['promotion']['row']
    assert handoff['published_at']=='2026-11-16T14:30:00+08:00'
    assert json.loads(Path(handoff['publication_evidence']['path']).read_text(encoding='utf8'))['schema']=='fanqie_h3_publication_evidence/v2'
    assert x['store'].attach_publication(x['cid'],command_id='cmd1',browser_db=browser,evidence_directory=tmp_path/'evidence',metadata_command_id='sync1')==handoff
    with sqlite3.connect(x['db']) as db:assert db.execute('SELECT count(*) FROM fanqie_publish_records').fetchone()[0]==1


def test_actual_five_expired_aliases_do_not_create_tasks_for_current_candidate(case,tmp_path):
    from src.services import fanqie_promotion_identity_v2 as shared
    x=case;folder=shared.ROOT/'data/fanqie_account_control/commands/7615ae93b01140d7aa96e5aba9f7ed50'
    observation=shared._ref(folder/'observer_diagnostic/OBSERVATION.json')
    legacy=shared._ref(folder/'PROMOTION_SNAPSHOT.json')
    snap=shared._read(shared.prepare_snapshot(legacy,observation,tmp_path/'actual_readonly',
        managed_subject=shared._read(observation)['subject']))
    x['store'].clock=lambda:snap['observed_at']+1
    binding={**x['binding'],**{k:snap[k] for k in ('resource_id','binding_version','platform_identity_key','environment_key')}}
    assert len(snap['rows'])==5
    for row in snap['rows']:
        assert row['publishable'] is False
        with pytest.raises((CandidateBlocked,ValueError)):
            x['store'].bind_promotion(x['cid'],snap,row,binding)
    with sqlite3.connect(x['db']) as db:
        assert db.execute('SELECT count(*) FROM fanqie_promotion_tasks').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM fanqie_native_promotion_identities').fetchone()[0]==0
