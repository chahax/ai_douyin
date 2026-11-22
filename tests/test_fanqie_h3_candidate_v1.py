import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from src.services.fanqie_h3_candidate_v1 import (
    CandidateLedger, CandidateBlocked, migrate, digest, task_identity,
)
from src.operations_accounts.fanqie_managed_promotion_v1 import normalise_snapshot
from src.platform_adapter.models import PublishRequest


@pytest.fixture
def case(tmp_path):
    def save(name, value):
        p=tmp_path/name
        p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
        import hashlib
        return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    db=tmp_path/'p0.db'
    with sqlite3.connect(db) as c:
        c.executescript(Path('tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text(encoding='utf8'))
        c.execute("INSERT INTO fanqie_douyin_accounts(account_uuid,account_key) VALUES('account:test','novel')")
    migrate(db,tmp_path/'backup.db')
    store=CandidateLedger(db,clock=lambda:1000)
    media=save('media.mp4','synthetic bytes, no codec execution')
    script=save('script.md','fiction script')
    proof=save('proof.json',{'cached':True})
    code=save('code.py','frozen code')
    plan=save('plan.json',{'code':[code]})
    result=save('result.json',{'file':media,'proof':proof,'plan':plan})
    book=save('book.json',{'book_id':'123'})
    selection=save('selection.json',{})
    source_case=save('case.json',{'shots':[{'authoritative_script':script,'script_selection':selection}]})
    source=save('source.json',{'segments':[{'source_case':source_case}]})
    h=dict(schema='novel_promotion_local_candidate/v1',book_id='123',book_name='test book',account_key='novel',
        media_binding=media,source_manifest=book,source_generation_manifest=source,
        technical_proof_binding=proof,assembly_receipt_binding=result,overall_video_quality_passed=False,
        publish_allowed=False,known_visual_finding=save('visual.json',{'known_issue':True}))
    hr=save('handoff.json',h)
    provenance=save('provenance.json',dict(schema='fanqie_candidate_provenance/v1',book_id='123',media=media,
        script=script,source_code=[code],book_manifest=book,assembly_result=result,
        script_selections=[selection],source_cases=[source_case]))
    qa=save('qa.json',dict(status='technical_cache_review_passed',file=media,result=result,proof=proof,
        all_frame_pixels_and_PTS_cache_revalidated=True,audio_PCM_and_AAC_metrics_cache_revalidated=True,
        original_sources_SHA_revalidated=True))
    account=dict(account_uuid='account:test',account_key='novel',binding_version='dv1')
    cid=store.register_pending(hr,provenance_ref=provenance,technical_review_ref=qa,account_binding=account)
    binding=dict(resource_id='fanqie:test',binding_version='fv1',platform_identity_key='fid',
        environment_key='fenv',douyin_account_uuid='account:test',account_link_version='linkhash')
    row=dict(platform_task_id='task9',book_id='123',book_name='test book',alias_id='alias9',alias='keyword',
        promotion_path='path',publish_type='AIGC',alias_status='生效中',book_status='可用',
        valid_from='1970-01-01T00:00:00+00:00',valid_until='2100-01-01T00:00:00+00:00',
        published_links=[],fill_status='not_filled')
    def snapshot(at=1000,changes=None,version="v1.1"):
        item={**row,**(changes or {})}
        item['identity_attributes']=[{'name':name,'value':item.get(key)} for name,key in [('data-task-id','platform_task_id'),('data-alias-id','alias_id'),('data-promotion-path','promotion_path')]]
        raw=dict(items=[item],table_ready=True,pagination_complete=True)
        subject={k:binding[k] for k in ('resource_id','binding_version','platform_identity_key','environment_key')}
        subject.update(observed_at=at,identity_verified=True,challenge=False)
        evidence=dict(schema='fanqie_promotion_DOM_evidence/v1',subject=subject,raw=raw)
        if version!='legacy_v1':evidence['normalizer_version']=version
        ref=save('snapshot-'+str(at)+str(len(list(tmp_path.iterdir())))+'.json',evidence)
        return normalise_snapshot(raw,**subject,evidence_ref=ref,normalizer_version=version)
    def bind():
        sn=snapshot();store.bind_promotion(cid,sn,sn['rows'][0],binding);return sn
    def review():
        ref=save('review.json',dict(schema='fanqie_candidate_user_review/v1',media=media,
            decision_source='explicit_user_statement',user_statement='Accept this media with disclosed issues',
            accepted_for_publication=True,known_findings=h['known_visual_finding']))
        store.record_user_review(cid,ref)
    metadata=dict(title='fiction excerpt',description='AI-generated fiction',hashtags=['小说','AI生成'],ai_generated=True,fictional_story=True)
    def prepare(sn=None):
        sn=sn or snapshot()
        req=PublishRequest(video_path=media['path'],title=metadata['title'],description=metadata['description'],
            hashtags=metadata['hashtags'],extra_metadata={'account_uuid':'account:test'})
        auth=save('auth.json',dict(candidate_id=cid,media=media,account_uuid='account:test',publish_authorized=True,
            decision_source='explicit_user_statement',user_statement='Publish this exact request',
            metadata_sha256=digest(asdict(req)),promotion_subject_sha256=digest({'row':task_identity(sn['rows'][0]),'binding':binding})))
        return store.prepare_publish(cid,snapshot=sn,row=sn['rows'][0],resource_binding=binding,metadata=metadata,authorization_ref=auth)
    return locals()


def test_constructor_readonly_missing(tmp_path):
    p=tmp_path/'missing.db'
    with pytest.raises(sqlite3.OperationalError):CandidateLedger(p)
    assert not p.exists()


def test_pending_no_fake_task_and_idempotent(case):
    x=case;c=x['store'].get(x['cid'])
    assert c['task_id'] is None and c['publish_id'] is None
    assert x['store'].register_pending(x['hr'],provenance_ref=x['provenance'],technical_review_ref=x['qa'],account_binding=x['account'])==x['cid']
    with sqlite3.connect(x['db']) as db:
        assert db.execute('SELECT count(*) FROM fanqie_promotion_tasks').fetchone()[0]==0
    with pytest.raises(CandidateBlocked,match='promotion_and_user_review'):x['prepare']()


@pytest.mark.parametrize('changes',[{'book_id':'wrong'},{'alias_id':None},{'alias_status':'审核中'},
    {'valid_until':'1970-01-01T00:00:01Z'},{'publish_type':'other'}])
def test_unusable_task_rejected(case,changes):
    x=case;s=x['snapshot'](changes=changes)
    with pytest.raises((CandidateBlocked,ValueError)):
        x['store'].bind_promotion(x['cid'],s,s['rows'][0],x['binding'])


def test_evidence_row_tamper_rejected(case):
    x=case;s=x['snapshot']();s['rows'][0]['alias']='forged'
    with pytest.raises(CandidateBlocked,match='rows_changed'):
        x['store'].bind_promotion(x['cid'],s,s['rows'][0],x['binding'])


def test_freshness_and_new_observation_not_immutable_intent(case):
    x=case;x['bind']();x['review']();p=x['prepare']()
    x['store'].clock=lambda:1100
    stale=x['snapshot'](at=1000)
    with pytest.raises(CandidateBlocked,match='stale'):
        x['store'].dispatch(x['cid'],snapshot=stale,row=stale['rows'][0],resource_binding=x['binding'],queue=lambda *a,**k:pytest.fail())
    fresh=x['snapshot'](at=1100)
    assert x['prepare'](fresh)==p
    calls=[]
    def queue(*a,**kw):calls.append(a);return {'command_id':'cmd1'}
    for _ in range(2):
        assert x['store'].dispatch(x['cid'],snapshot=fresh,row=fresh['rows'][0],resource_binding=x['binding'],queue=queue)=='cmd1'
    assert len(calls)==1


def test_dispatch_unknown_no_replay(case):
    x=case;s=x['bind']();x['review']();x['prepare']()
    calls=[]
    def queue(*a,**kw):calls.append(1);raise TimeoutError()
    with pytest.raises(TimeoutError):x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'],queue=queue)
    with pytest.raises(CandidateBlocked,match='unknown_no_replay'):
        x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'],queue=queue)
    assert calls==[1]


def test_legacy_caption_only_preparation_never_sends_extra_authorization_notes(case):
    x=case
    sn=x['bind']()
    x['review']()
    prepared=x['prepare']()
    # Before comment support the ledger stored only the file reference and
    # request, even when an external authorizer supplied additional JSON fields.
    old_auth=json.loads(Path(prepared['authorization']['path']).read_text(encoding='utf8'))
    prepared['authorization']=x['save']('legacy-authority.json',{**old_auth,'comment':'旧记录附言'})
    with sqlite3.connect(x['db']) as db:
        db.execute('UPDATE fanqie_h3_candidates SET prepared_json=? WHERE candidate_id=?',
                   (json.dumps(prepared),x['cid']))
    sent=[]
    def queue(key,request,*,authorization):
        sent.append(authorization)
        return {'command_id':'original'}
    assert x['store'].dispatch(x['cid'],snapshot=sn,row=sn['rows'][0],resource_binding=x['binding'],queue=queue)=='original'
    assert sent==[prepared['authorization']]


def browser_receipt(x,payload,**changes):
    db=x['tmp_path']/'browser.db'
    result=dict(status='published',success=True,post_id='123456789012345',publish_url='https://www.douyin.com/video/123456789012345',
        published_at='2026-11-16T12:00:00+08:00',publish_evidence={'post_verified':True})
    result.update(changes)
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE browser_control_commands(command_id TEXT,account_id TEXT,binding_version TEXT,state TEXT,kind TEXT,result TEXT,payload TEXT,idempotency_key TEXT UNIQUE,created_at REAL DEFAULT 0)')
        c.execute('INSERT INTO browser_control_commands(command_id,account_id,binding_version,state,kind,result,payload) VALUES(?,?,?,?,?,?,?)',('cmd1','account:test','dv1','succeeded','publish',json.dumps(result),json.dumps(payload)))
    return db


def test_full_p0_bridge_original_receipt_and_repeat(case):
    x=case;x['bind']();x['review']();p=x['prepare']()
    db=browser_receipt(x,dict(request=p['request'],authorization=p['authorization'],video_sha256=x['media']['sha256']))
    a=x['store'].attach_publication(x['cid'],command_id='cmd1',browser_db=db,evidence_directory=x['tmp_path']/'evidence')
    b=x['store'].attach_publication(x['cid'],command_id='cmd1',browser_db=db,evidence_directory=x['tmp_path']/'evidence')
    assert a==b and a['schema']=='fanqie_h3_publication_handoff/v1'
    with sqlite3.connect(x['db']) as c:
        assert c.execute('SELECT count(*) FROM fanqie_publish_records').fetchone()[0]==1
        assert c.execute('SELECT published_at FROM fanqie_publish_records').fetchone()[0]=='2026-11-16T12:00:00+08:00'
    assert json.loads(Path(x['hr']['path']).read_text())['overall_video_quality_passed'] is False


@pytest.mark.parametrize('bad', ['media','metadata','missing_date'])
def test_wrong_original_receipt_blocked(case,bad):
    x=case;x['bind']();x['review']();p=x['prepare']()
    payload=dict(request=p['request'],authorization=p['authorization'],video_sha256=x['media']['sha256'])
    if bad=='media':payload['video_sha256']='wrong'
    if bad=='metadata':payload['request']['ai_generated']=False
    db=browser_receipt(x,payload,**({'published_at':None} if bad=='missing_date' else {}))
    with pytest.raises(CandidateBlocked):
        x['store'].attach_publication(x['cid'],command_id='cmd1',browser_db=db,evidence_directory=x['tmp_path']/'evidence')


def test_incompatible_extension_not_accepted(case):
    x=case
    with sqlite3.connect(x['db']) as db:
        db.execute('DROP TABLE fanqie_h3_candidates')
        db.execute('CREATE TABLE fanqie_h3_candidates(candidate_id TEXT)')
    with pytest.raises(CandidateBlocked,match='schema_incompatible'):CandidateLedger(x['db'])


def test_runtime_account_registration_and_conflict(case):
    import hashlib
    x=case;db=x['tmp_path']/'runtime.db'
    r=dict(account_uuid='account:new',account_key='novel2',platform_identity_key='uid:test',browser_environment_key='env',
        browser_profile_dir='D:/testprofile',storage_state_path='D:/teststate.json',confirmed_by='user',created_at='2026-01-01',profile_version=1)
    version=hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()
    with sqlite3.connect(db) as d:
        d.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,account_key TEXT,platform_identity_key TEXT,browser_environment_key TEXT,browser_profile_dir TEXT,storage_state_path TEXT,confirmed_by TEXT,created_at TEXT,status TEXT,platform TEXT,public_uid TEXT)')
        d.execute('CREATE TABLE account_strategy_versions(account_uuid TEXT,profile_version INTEGER,is_active INTEGER)')
        d.execute('CREATE TABLE douyin_accounts(account_uuid TEXT,status TEXT)')
        d.execute('INSERT INTO account_runtime_bindings VALUES(?,?,?,?,?,?,?,?,?,?,?)',(*[r[k] for k in r if k!='profile_version'],'active','douyin','public123'))
        d.execute('INSERT INTO account_strategy_versions VALUES(?,?,1)',('account:new',1))
        d.execute("INSERT INTO douyin_accounts VALUES('account:new','active')")
    a=dict(account_uuid='account:new',account_key='novel2',binding_version=version)
    first=x['store'].ensure_runtime_account(a,runtime_db=db)
    assert x['store'].ensure_runtime_account(a,runtime_db=db)==first
    with sqlite3.connect(x['db']) as d:d.execute("UPDATE fanqie_douyin_accounts SET account_uuid='other' WHERE id=?",(first,))
    with pytest.raises(CandidateBlocked,match='p0_account_conflict'):x['store'].ensure_runtime_account(a,runtime_db=db)


def test_recover_lost_broker_receipt_without_redispatch(case):
    x=case;s=x['bind']();x['review']();p=x['prepare']()
    payload=dict(request=p['request'],authorization=p['authorization'],video_sha256=x['media']['sha256'])
    db=browser_receipt(x,payload)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE browser_control_commands SET state='queued',idempotency_key=?",('publish:'+x['media']['sha256'],))
    def lost(*a,**k):raise TimeoutError('receipt lost after persistent submission')
    with pytest.raises(TimeoutError):x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'],queue=lost)
    assert x['store'].recover_dispatch_receipt(x['cid'],browser_db=db)=={'status':'queued','command_id':'cmd1'}
    assert x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'],queue=lambda *a,**k:pytest.fail())=='cmd1'


def test_different_script_selection_or_code_rejected(case):
    x=case
    p=json.loads(Path(x['provenance']['path']).read_text())
    p['script_selections']=[x['save']('unrelated-selection.json',{})]
    bad=x['save']('bad-provenance.json',p)
    with pytest.raises(CandidateBlocked,match='selections_case_mismatch'):
        x['store'].register_pending(x['hr'],provenance_ref=bad,technical_review_ref=x['qa'],account_binding=x['account'])


def test_another_media_reuses_exact_task_and_creates_distinct_job(case):
    x=case;s=x['bind']();first=x['store'].get(x['cid'])
    media=x['save']('second.mp4','second synthetic media')
    h=dict(x['h'],media_binding=media)
    result=json.loads(Path(x['result']['path']).read_text());result['file']=media
    h['assembly_receipt_binding']=x['save']('result2.json',result)
    p=json.loads(Path(x['provenance']['path']).read_text());p.update(media=media,assembly_result=h['assembly_receipt_binding'])
    qa=json.loads(Path(x['qa']['path']).read_text());qa.update(file=media,result=h['assembly_receipt_binding'])
    cid=x['store'].register_pending(x['save']('handoff2.json',h),provenance_ref=x['save']('provenance2.json',p),
        technical_review_ref=x['save']('qa2.json',qa),account_binding=x['account'])
    second=x['store'].bind_promotion(cid,s,s['rows'][0],x['binding'])
    assert second['task_id']==first['task_id'] and second['video_job_id']!=first['video_job_id']


def test_bridge_reads_actual_sync_date_and_metadata_request_is_read_only(case):
    x=case;s=x['bind']();x['review']();p=x['prepare']()
    x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'],queue=lambda *a,**k:{'command_id':'cmd1'})
    payload=dict(request=p['request'],authorization=p['authorization'],video_sha256=x['media']['sha256'],account_key='novel')
    db=browser_receipt(x,payload,published_at=None)
    seen=[]
    def queue(*args):seen.append(args);return {'command_id':'sync1'}
    assert x['store'].request_publication_metadata(x['cid'],browser_db=db,queue=queue)=={'command_id':'sync1'}
    assert seen[0][0:2]==('novel','read') and seen[0][2]=={'method':'sync_videos','params':{},'operation_profile':None}
    with sqlite3.connect(db) as c:
        c.execute('INSERT INTO browser_control_commands(command_id,account_id,binding_version,state,kind,result,payload) VALUES(?,?,?,?,?,?,?)',('sync1','account:test','dv1','succeeded','read',
            json.dumps({'read_result':{'success':True,'videos':[{'video_id':'123456789012345','account_uuid':'account:test','account_key':'novel','publish_time':'2026年11月16日 14:30'}]}}),json.dumps({'method':'sync_videos'})))
    handoff=x['store'].attach_publication(x['cid'],command_id='cmd1',browser_db=db,evidence_directory=x['tmp_path']/'evidence',metadata_command_id='sync1')
    assert handoff['published_at']=='2026-11-16T14:30:00+08:00'
    assert handoff['time_evidence']['source_command_id']=='sync1'


def test_live_dispatch_requires_runtime_binding_recheck_before_intent(case):
    x=case;s=x['bind']();x['review']();x['prepare']()
    with pytest.raises(CandidateBlocked,match='runtime_binding_recheck_required'):
        x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'])
    assert x['store'].get(x['cid'])['dispatch_state']=='not_started'


def test_metadata_refresh_after_terminal_missing_post_preserves_pending_and_valid_receipt(case):
    x=case;s=x['bind']();x['review']();p=x['prepare']()
    x['store'].dispatch(x['cid'],snapshot=s,row=s['rows'][0],resource_binding=x['binding'],queue=lambda *a,**k:{'command_id':'cmd1'})
    payload=dict(request=p['request'],authorization=p['authorization'],video_sha256=x['media']['sha256'],account_key='novel')
    db=browser_receipt(x,payload,published_at=None);calls=[]
    def queue(key,kind,payload,idempotency,priority):
        calls.append(idempotency);cid='read'+str(len(calls))
        with sqlite3.connect(db) as d:
            d.execute('INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?,?,?,?)',
                (cid,'account:test','dv1','queued','read','{}',json.dumps(payload),idempotency,len(calls)))
        return {'command_id':cid,'state':'queued'}
    first=x['store'].request_publication_metadata(x['cid'],browser_db=db,queue=queue)
    assert x['store'].request_publication_metadata(x['cid'],browser_db=db,queue=queue)['command_id']==first['command_id']
    with sqlite3.connect(db) as d:
        d.execute("UPDATE browser_control_commands SET state='succeeded',result=? WHERE command_id=?",
            (json.dumps({'read_result':{'success':True,'videos':[]}}),first['command_id']))
    second=x['store'].request_publication_metadata(x['cid'],browser_db=db,queue=queue)
    assert second['command_id']!=first['command_id'] and calls[-1].endswith(':after:'+first['command_id'])
    assert x['store'].request_publication_metadata(x['cid'],browser_db=db,queue=queue)['command_id']==second['command_id']
    with sqlite3.connect(db) as d:
        d.execute("UPDATE browser_control_commands SET state='succeeded',result=? WHERE command_id=?",(json.dumps({'read_result':{'success':True,
            'videos':[{'video_id':'123456789012345','account_uuid':'account:test','account_key':'novel','publish_time':'2026年11月16日 14:30'}]}}),second['command_id']))
    assert x['store'].request_publication_metadata(x['cid'],browser_db=db,queue=queue)['command_id']==second['command_id']
    assert len(calls)==2


def test_legacy_snapshot_stays_pending_and_new_version_explicitly_parses_fullwidth_range(case):
    x=case
    changes=dict(valid_from=None,valid_until=None,valid_range='1970-01-01 ～ 2100-01-01')
    old=x['snapshot'](changes=changes,version='legacy_v1')
    old_bytes=Path(old['evidence_ref']['path']).read_bytes()
    assert 'normalizer_version' not in old and old['rows'][0]['status']=='pending'
    with pytest.raises(CandidateBlocked,match='complete_task'):
        x['store'].bind_promotion(x['cid'],old,old['rows'][0],x['binding'])
    new=x['snapshot'](changes=changes)
    assert new['normalizer_version']=='v1.1' and new['rows'][0]['status']=='ready'
    assert x['store'].bind_promotion(x['cid'],new,new['rows'][0],x['binding'])['task_id']
    assert Path(old['evidence_ref']['path']).read_bytes()==old_bytes
