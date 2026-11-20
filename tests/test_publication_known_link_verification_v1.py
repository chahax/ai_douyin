"""Private real broker/core protocol; browser IO edges are fixed read-only fakes."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from test_publication_verification_recovery import incident,valid_evidence
from src.operations_accounts import publication_known_link_verification_v1 as api
from src.operations_accounts import publication_verification_recovery as core
from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlRejected,_json


@pytest.fixture
def case(incident,monkeypatch):
    i=incident;root=i.journal.parents[2];monkeypatch.setattr(api,'ROOT',root)
    monkeypatch.setattr('src.operations_accounts.browser_control_runtime.binding_version',lambda _: 'binding')
    i.context.binding.public_uid='12345678';i.runtime=NS(resolve=lambda *args,**kw:i.context)
    path=root/'data/approved_full.mp4';path.write_bytes(b'approved full two-minute media identity')
    media=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    payload=copy.deepcopy(i.original['payload']);payload['video_sha256']=media['sha256'];payload['request']['video_path']=str(path)
    with i.store._db(write=True) as db:
        sha=hashlib.sha256(_json([i.context.account_uuid,'binding','publish',payload,100]).encode()).hexdigest()
        db.execute('UPDATE browser_control_commands SET payload=?,request_sha=? WHERE command_id=?',(_json(payload),sha,i.original['command_id']))
    i.original=i.store.get(i.original['command_id'])
    key=hashlib.sha256(json.dumps(dict(platform_identity_key='platform:a',video_sha256=media['sha256']),sort_keys=True).encode()).hexdigest()
    i.rows[0]['video_sha256']=media['sha256'];i.rows[0]['video_path']=str(path);i.journal=i.journal.with_name(key+'.native.jsonl')
    i.journal.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in i.rows)+'\n',encoding='utf8')
    i.lock=i.lock.with_name(key+'.submitted.json');i.lock.write_text(json.dumps(dict(journal=str(i.journal),status='submission_started')),encoding='utf8')
    for _ in range(3):
        command=core.queue_due(i.store,i.context,'binding');assert command
        claimed=i.store.claim_next(i.context.account_uuid,'binding','backend:123:abc',1);assert claimed['command_id']==command['command_id']
        i.store.transition(command['command_id'],'backend:123:abc',1,'failed',result=dict(status='verification_pending',reason='detail_popup_missing'))
        i.now[0]+=301
        with i.store._db(write=True) as db:db.execute('UPDATE browser_control_owners SET heartbeat=?,updated_at=?',(i.now[0],i.now[0]))
    def save(name,value):
        p=root/'data'/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return api.reference(p)
    assembly=save('assembly.json',dict(file=media,clock=dict(frames=2896,fps=24)))
    provenance=save('provenance.json',dict(assembly_result=assembly))
    frozen=dict(media=media,provenance=provenance,account=dict(account_uuid=i.context.account_uuid,account_key=i.context.account_key,binding_version='binding'))
    i.candidate=dict(command_id=i.original['command_id'],frozen_json=json.dumps(frozen));monkeypatch.setattr(api,'_candidate',lambda cid:i.candidate)
    evidence=save('native_AX_excerpt.json',{'native_UI_link':'https://www.douyin.com/video/1234567890123456789'})
    i.observed=dict(schema=api.OBSERVATION,observation_source='agent_native_CUA_AX',original_publish_command_id=i.original['command_id'],
        account_uuid=i.context.account_uuid,account_key=i.context.account_key,binding_version='binding',platform_identity_key='platform:a',
        observed_public_uid='12345678',observed_title=i.original['payload']['request']['title'],
        canonical_url='https://www.douyin.com/video/1234567890123456789',observed_at=i.now[0],evidence=[evidence],
        observed_published_at='1900-01-01 00:00',observed_duration_seconds=121,observed_AI_label='内容由AI生成')
    i.observation=save('observation.json',i.observed)
    i.authority_value=dict(schema='fanqie_production_trial_user_authorization/v1',user_statement='发布完整两分钟后回填',
        authorized_target=dict(media=media,douyin_account_key=i.context.account_key))
    i.authority=save('parent.json',i.authority_value);i.save=save;i.root=root
    i.identities=[]
    i.resource=NS(context=i.context,runtime=NS(verify_identity=lambda *a,**kw:i.identities.append('fresh_UID') or NS(healthy=True)))
    i.technical=dict(origin='https://www.douyin.com',path='/video/1234567890123456789',visible_video_count=1,
        actual_seconds=120.6666666667,publication_time_candidates=1,publication_time_raw='发布时间：2026-11-17 15:46')
    i.visits=[];i.stopped=[];i.detail=valid_evidence(i)
    class Page:
        def locator(self,selector):assert selector=='html';return self
        def evaluate(self,script):return dict(i.technical)
    class Session:
        def open_page(self,url):i.visits.append(url);return Page()
        def stop(self):i.stopped.append(True)
    i.session=Session()
    def detail(*args,**kwargs):i.detail_kwargs=kwargs;return copy.deepcopy(i.detail)
    monkeypatch.setattr('src.platform_adapter.publish_verification.wait_for_published_video',detail)
    return i


def prepare(i,**kwargs):return api.prepare(i.observation,authority_ref=i.authority,candidate_id='new-candidate',
    output_directory=i.root/'data/known_link',store=i.store,runtime=i.runtime,**kwargs)
def enqueue(i,ref):return api.enqueue(ref,store=i.store,runtime=i.runtime)
def run(i):
    actor=BrowserControlActor(i.store,i.context.account_uuid,'binding','backend:123:abc',
        {core.KIND:lambda ctx,payload:api.run(ctx,i.session)},context=i.resource)
    actor.generation=1;actor._thread_id=__import__('threading').get_ident()
    return actor.run_next()


def test_one_explicit_known_link_read_keeps_three_auto_budget_and_no_seed_success(case):
    i=case;original=i.original;lock=i.lock.read_bytes();journal=i.journal.read_bytes()
    p=prepare(i);first=enqueue(i,p);second=enqueue(i,p)
    assert first['command_id']==second['command_id'] and second['reused']
    command=i.store.get(first['command_id'])
    assert command['payload']['attempt']==4 and command['payload']['known_link_read_index']==1
    assert command['idempotency_key'].startswith('known-link:') and core.MAX_ATTEMPTS==3
    assert i.store.get(original['command_id'])==original and not i.visits and not i.identities
    assert i.lock.read_bytes()==lock and i.journal.read_bytes()==journal


def test_real_actor_strict_detail_atomically_settles_original_without_adopting_seed_date(case):
    i=case;p=prepare(i);cid=enqueue(i,p)['command_id'];result=run(i)
    assert result['command_id']==cid and result['state']=='succeeded'
    original=i.store.get(i.original['command_id']);evidence=original['result']['publish_evidence']
    assert original['state']=='succeeded' and original['result']['original_unknown_snapshot']==i.original
    assert 'published_at' not in evidence
    assert evidence['public_page_time_text_observation']['publication_time_raw']=='发布时间：2026-11-17 15:46'
    assert evidence['numeric_duration_verified'] and evidence['actual_seconds']==i.technical['actual_seconds']
    assert i.visits==[i.observed['canonical_url']] and i.identities==['fresh_UID'] and i.stopped
    assert i.detail_kwargs['expected_title']==i.original['payload']['request']['title']
    assert json.loads(i.lock.read_text())['status']=='submission_started'


@pytest.mark.parametrize('field',['canonical_url','observed_title','observed_public_uid','observation_source'])
def test_bad_observation_cannot_prepare_or_enqueue(case,field):
    i=case;bad=dict(i.observed);bad[field]='https://wrong.example/video/123' if field=='canonical_url' else 'wrong'
    i.observation=i.save('bad-observation.json',bad)
    with pytest.raises(BrowserControlRejected):prepare(i)


@pytest.mark.parametrize('change',['source','parent','candidate','live'])
def test_changed_inputs_reject_before_new_read(case,change):
    i=case;p=prepare(i)
    if change=='source':i.journal.write_text('{}\n')
    elif change=='parent':
        bad=dict(i.authority_value);bad['schema']='other'
        request=api.read(p);request['parent_authority']=i.save('other-parent.json',bad);p=i.save('forged-request.json',request)
    elif change=='candidate':i.candidate['command_id']='another'
    else:
        command=i.store.submit(i.context.account_uuid,'binding','manual','new-manual',{},10)
        with i.store._db(write=True) as db:db.execute("UPDATE browser_control_commands SET state='waiting_human' WHERE command_id=?",(command['command_id'],))
    with pytest.raises((BrowserControlRejected,ValueError,KeyError)):enqueue(i,p)
    assert i.store.get(i.original['command_id'])['state']=='outcome_unknown'


def test_different_observation_same_original_baseline_cannot_create_second_read(case):
    i=case;p=prepare(i)
    other=dict(i.observed,canonical_url='https://www.douyin.com/video/9999999999999999999')
    i.observation=i.save('another-observation.json',other)
    q=api.prepare(i.observation,authority_ref=i.authority,candidate_id='new-candidate',output_directory=i.root/'data/another_request',store=i.store,runtime=i.runtime)
    assert api.read(q)['idempotency_key']==api.read(p)['idempotency_key']
    first=enqueue(i,p)
    with pytest.raises(BrowserControlRejected):enqueue(i,q)
    assert enqueue(i,p)['command_id']==first['command_id']


@pytest.mark.parametrize('bad',['duration','review','identity'])
def test_seed_never_overrides_wrong_duration_review_or_identity(case,bad):
    i=case;p=prepare(i);enqueue(i,p)
    if bad=='duration':i.technical['actual_seconds']=60.333
    elif bad=='review':i.detail['review_status']='not_clear'
    else:i.resource.runtime.verify_identity=lambda *a,**kw:NS(healthy=False)
    result=run(i)
    assert result['state']!='succeeded' and i.store.get(i.original['command_id'])['state']=='outcome_unknown'


def test_unique_caption_or_comment_time_text_cannot_be_promoted_to_publication_date(case):
    i=case;i.technical.update(publication_time_candidates=1,publication_time_raw='发布时间：1900-01-01 00:00',
                            publication_time_native_field_verified=False)
    enqueue(i,prepare(i));run(i)
    evidence=i.store.get(i.original['command_id'])['result']['publish_evidence']
    assert 'published_at' not in evidence
