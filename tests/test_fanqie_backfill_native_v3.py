"""Temporary real-DDL native-alias backfill protocols; no platform/media calls."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

from src.services import fanqie_promotion_identity_v2 as shared
from src.services.fanqie_h3_candidate_v1 import CandidateLedger, migrate as migrate_candidates
from src.services.fanqie_promotion_ledger import PromotionLedger, migrate_ledger
from src.services.fanqie_backfill_workflow import BackfillBlocked, digest
from src.services.fanqie_backfill_coordinator import BackfillCoordinator, prepare_registered_backfill
from src.services.fanqie_backfill_native_v3 import NativeSnapshotAdapter
from src.operations_accounts.browser_control import BrowserControlStore
from src.platform_adapter.models import PublishRequest
from test_fanqie_promotion_identity_v2 import make_case

ROOT=Path(__file__).resolve().parents[1]
BOOK='7302660145530539062'
POST='1234567890123456789'


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode())
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No real browser/process/network/media in this suite')
    class ForbiddenPopen(subprocess.Popen):
        def __init__(self,*a,**k):forbidden(*a,**k)
    monkeypatch.setattr(subprocess,'Popen',ForbiddenPopen)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket.socket,'connect_ex',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)


@pytest.fixture
def trial(tmp_path):
    fresh_serial=[0]
    def fresh(name,*,links=None,identity='uid:synthetic',expired=False,unrelated=False):
        fresh_serial[0]+=1
        folder=tmp_path/(name+'-'+str(fresh_serial[0]))
        updates=dict(book_id=BOOK,book_name='准确书名',alias_name='准确推广词')
        dom=dict(book_id=BOOK,book_name='准确书名',alias='准确推广词',
            published_links=links or [],fill_status=(links[0] if links else '未填写'))
        if expired:
            updates.update(alias_status=5,alias_end_time='2026-01-02')
            dom.update(alias_status='强制失效',valid_until='2026-01-02')
        extra=[dict(alias_id='2234567890123456789',book_id='9999999999999999999',book_name='Other native book',
            alias_name='Other native keyword',task_type=1,alias_post_type=29,alias_status=3,book_status=1,
            alias_start_time='2026-01-01',alias_end_time='2027-01-01')] if unrelated else None
        data=make_case(folder,identity=identity,native_updates=updates,dom_updates=dom,extra_native=extra)
        if unrelated:
            from src.operations_accounts import fanqie_managed_promotion_v1 as old
            legacy=shared._read(data['legacy_ref']);raw=shared._read(legacy['evidence_ref'])
            raw['raw']['items'].append(dict(book_id='8888888888888888888',book_name='Unrelated unresolved book',
                alias='Unresolved keyword',publish_type='AIGC',alias_status='生效中',book_status='可用',
                valid_from='2026-01-01',valid_until='2027-01-01',published_links=[],fill_status='未填写'))
            raw_ref=put(folder/'DOM_MIXED.json',raw)
            legacy=old.normalise_snapshot(raw['raw'],**raw['subject'],evidence_ref=raw_ref)
            data['legacy_ref']=put(folder/'LEGACY_MIXED.json',legacy)
        return shared.prepare_snapshot(data['legacy_ref'],data['observation_ref'],folder/'derived',managed_subject=data['subject'])
    snapshot_ref=fresh('initial');snapshot=shared._read(snapshot_ref);promotion=snapshot['rows'][0]
    p0=tmp_path/'p0.db'
    with sqlite3.connect(p0)as db:
        db.executescript((ROOT/'tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text(encoding='utf-8'))
        db.execute("INSERT INTO fanqie_douyin_accounts(account_uuid,account_key,status) VALUES('account:test','novel_test','active')")
    migrate_candidates(p0,tmp_path/'before_candidates.db')
    migrate_ledger(p0,tmp_path/'before_backfill.db')
    candidates=CandidateLedger(p0);ledger=PromotionLedger(p0)
    control=BrowserControlStore(tmp_path/'browser.db')
    script=put(tmp_path/'script.md',b'synthetic protocol source script')
    code=put(tmp_path/'code.py',b'# synthetic source binding')
    plan=put(tmp_path/'plan.json',{'code':[code]})
    proof=put(tmp_path/'proof.json',{'fixture_only':True})
    book=put(tmp_path/'book.json',{'book_id':BOOK})
    selection=put(tmp_path/'selection.json',{'fixture_only':True})
    source_case=put(tmp_path/'SOURCE_CASE.json',{'shots':[{'authoritative_script':script,'script_selection':selection}]})
    generation=put(tmp_path/'generation.json',{'segments':[{'source_case':source_case}]})
    finding=put(tmp_path/'visual.json',{'fixture_only':True,'known_issue':True})
    account=dict(account_uuid='account:test',account_key='novel_test',binding_version='dv1')
    resource_binding={k:snapshot[k] for k in shared.SCOPE}
    resource_binding.update(douyin_account_uuid=account['account_uuid'],account_link_version='association')
    metadata=dict(title='Synthetic fiction',description='AIGC fictional test',hashtags=['小说','AI生成'],ai_generated=True,fictional_story=True)

    def publish(name,post_id=POST):
        media=put(tmp_path/(name+'.mp4'),('protocol fixture, never decoded '+name).encode())
        result=put(tmp_path/(name+'_assembly.json'),{'file':media,'proof':proof,'plan':plan})
        local=dict(schema='novel_promotion_local_candidate/v1',book_id=BOOK,book_name='准确书名',account_key='novel_test',
            media_binding=media,source_manifest=book,source_generation_manifest=generation,
            technical_proof_binding=proof,assembly_receipt_binding=result,known_visual_finding=finding)
        provenance=put(tmp_path/(name+'_provenance.json'),dict(schema='fanqie_candidate_provenance/v1',book_id=BOOK,media=media,
            script=script,source_code=[code],book_manifest=book,assembly_result=result,script_selections=[selection],source_cases=[source_case]))
        qa=put(tmp_path/(name+'_qa.json'),dict(status='technical_cache_review_passed',file=media,result=result,proof=proof,
            all_frame_pixels_and_PTS_cache_revalidated=True,audio_PCM_and_AAC_metrics_cache_revalidated=True,original_sources_SHA_revalidated=True))
        cid=candidates.register_pending(put(tmp_path/(name+'_local.json'),local),provenance_ref=provenance,technical_review_ref=qa,account_binding=account)
        bound=candidates.bind_promotion(cid,snapshot,promotion,resource_binding)
        candidates.record_user_review(cid,put(tmp_path/(name+'_review.json'),dict(schema='fanqie_candidate_user_review/v1',media=media,
            decision_source='explicit_user_statement',user_statement='Synthetic test only',accepted_for_publication=True,known_findings=finding)))
        req=PublishRequest(video_path=media['path'],title=metadata['title'],description=metadata['description'],hashtags=metadata['hashtags'],
            ai_generated=True,fictional_story=True,extra_metadata={'account_uuid':account['account_uuid']})
        auth=put(tmp_path/(name+'_auth.json'),dict(schema='fanqie_publication_authorization/v2',candidate_id=cid,media=media,
            account_uuid=account['account_uuid'],publish_authorized=True,decision_source='explicit_user_statement',user_statement='Synthetic test only',
            metadata_sha256=digest(asdict(req)),promotion_subject_sha256=digest({'row':shared.authorization_subject(snapshot,promotion),'binding':resource_binding})))
        prepared=candidates.prepare_publish(cid,snapshot=snapshot,row=promotion,resource_binding=resource_binding,metadata=metadata,authorization_ref=auth)
        payload=dict(account_key='novel_test',account_uuid=account['account_uuid'],video_sha256=media['sha256'],request=prepared['request'],authorization=auth)
        command=control.submit(account['account_uuid'],'dv1','publish','fixture-'+name,payload)
        owner=control.acquire_owner(account['account_uuid'],'dv1','owner-'+name)
        control.claim_next(account['account_uuid'],'dv1','owner-'+name,owner['generation'])
        url='https://www.douyin.com/video/'+post_id
        control.transition(command['command_id'],'owner-'+name,owner['generation'],'succeeded',result=dict(
            status='published',success=True,post_id=post_id,publish_url=url,published_at='2026-11-16T10:00:00+08:00',publish_evidence=dict(post_verified=True)))
        control.release_owner(account['account_uuid'],'owner-'+name,owner['generation'])
        handoff=candidates.attach_publication(cid,command_id=command['command_id'],browser_db=control.path,evidence_directory=tmp_path/'publications')
        return put(tmp_path/(name+'_handoff.json'),handoff),bound,media

    handoff,bound,media=publish('first')
    env={k:snapshot[k] for k in ('resource_id','binding_version','environment_key')};env['douyin_binding_sha256']='association'
    douyin=tmp_path/'douyin.db'
    with sqlite3.connect(douyin)as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid,account_key,status,public_uid)')
        db.execute("INSERT INTO account_runtime_bindings VALUES('account:test','novel_test','active','actual_douyin_id')")
    class Accounts:
        db=control.path;douyin_db=douyin
        def get(self,resource):assert resource==env['resource_id'];return env
        def check_association(self,e):return dict(account_uuid='account:test',account_key='novel_test')
        def bindings(self):return SimpleNamespace(get=lambda r:dict(status='active',platform_identity_key=snapshot['platform_identity_key']))
    template=tmp_path/'official.xlsx'
    with zipfile.ZipFile(template,'w')as z:
        z.writestr('xl/worksheets/sheet1.xml','''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>别名</v></c><c r="B1"><v>发文日期</v></c><c r="C1"><v>发文链接</v></c><c r="D1"><v>抖音号</v></c></row></sheetData></worksheet>''')
    def prepare(ref=handoff,name='prepared',promotion_ref=None):
        return prepare_registered_backfill(ledger,control.path,publication_handoff_binding=ref,accounts=Accounts(),
            resource_id=env['resource_id'],promotion_snapshot_binding=promotion_ref or snapshot_ref,official_template=template,output_directory=tmp_path/name)
    prepared=prepare();bid=prepared['binding_uuid']
    def authorize():ledger.authorize(bid,manifest_sha=ledger.get(bid)['manifest_sha'],reference='Synthetic exact native backfill authorization')
    return locals()


class Base:
    def __init__(self,*,fail=False):self.uploads=0;self.submits=0;self.fail=fail
    def _check(self,binding):pass
    def upload(self,workbook,binding):self.uploads+=1;return {'upload_ready':True}
    def submit(self,binding):
        self.submits+=1
        if self.fail:raise TimeoutError('synthetic unknown')
        return {}


def adapter(x,*,links=None,other_identity=False,readonly=False,fail=False,expired=False):
    calls=[];base=Base(fail=fail)
    def provider(**kwargs):
        calls.append(kwargs)
        final=kwargs['phase'] in {'post_submit','reconcile'}
        return x['fresh']('read'+str(len(calls)),links=links if final else None,
            identity='uid:other' if other_identity else 'uid:synthetic',expired=expired)
    return NativeSnapshotAdapter(base,provider,readonly=readonly),base,calls


def test_native_preparation_version_scope_and_official_fields(trial):
    x=trial;row=x['ledger'].get(x['bid']);contract=json.loads(row['contract_json']);manifest=json.loads(row['manifest_json'])
    assert row['status']=='prepared' and not row['authorization_json']
    assert contract['schema']=='fanqie_backfill_contract/v3'
    assert not {'platform_task_id','promotion_path','alias_id'}&contract.keys()
    assert manifest['promotion_contract_schema']==contract['schema']
    assert manifest['promotion_subject']==contract['promotion_subject']
    assert manifest['promotion_subject']['raw_alias_post_type']==29
    assert manifest['binding']['published_date']=='2026/11/16' # not alias start date
    assert Path(x['prepared']['manifest']['path']).name=='manifest_v3.json'
    with sqlite3.connect(x['p0'])as db:
        assert db.execute('SELECT platform_task_id,native_identity_scope FROM fanqie_promotion_tasks').fetchone()==(None,contract['native_identity_scope'])
    assert BackfillCoordinator(x['ledger'],x['control'].path,require_strict_contract=True).inspect(x['bid'])['native_identity']==contract['native_identity']


def test_fresh_native_execute_calls_all_three_phases_and_confirms_exact_URL(trial):
    x=trial;x['authorize']();a,base,calls=adapter(x,links=['https://www.douyin.com/video/'+POST])
    result=BackfillCoordinator(x['ledger'],x['control'].path,require_strict_contract=True).execute(x['bid'],adapter=a,guard=SimpleNamespace(check=lambda contract:None))
    assert result['status']=='confirmed' and base.uploads==base.submits==1
    assert calls==[{'phase':'preflight','force_refresh':False},{'phase':'pre_submit','force_refresh':True},{'phase':'post_submit','force_refresh':True}]
    assert result['attempt_count']==1


def test_unknown_only_readonly_reconcile_can_use_fresh_same_alias_after_expiry(trial):
    x=trial;x['authorize']();a,base,_=adapter(x,fail=True)
    coordinator=BackfillCoordinator(x['ledger'],x['control'].path,require_strict_contract=True)
    assert coordinator.execute(x['bid'],adapter=a,guard=SimpleNamespace(check=lambda c:None))['status']=='outcome_unknown'
    with pytest.raises(BackfillBlocked):coordinator.execute(x['bid'],adapter=a,guard=SimpleNamespace(check=lambda c:None))
    wrong,wrong_base,_=adapter(x,links=['https://www.douyin.com/video/2234567890123456789'],readonly=True)
    assert coordinator.reconcile(x['bid'],adapter=wrong,guard=SimpleNamespace(check=lambda c:None))['status']=='outcome_unknown'
    assert wrong_base.uploads==wrong_base.submits==0
    read,b,calls=adapter(x,links=['https://www.douyin.com/video/'+POST],readonly=True,expired=True)
    assert coordinator.reconcile(x['bid'],adapter=read,guard=SimpleNamespace(check=lambda c:None))['status']=='confirmed'
    assert b.uploads==b.submits==0 and calls==[{'phase':'reconcile','force_refresh':True}]


def test_other_fanqie_identity_cannot_reuse_alias_before_upload(trial):
    x=trial;x['authorize']();a,base,_=adapter(x,other_identity=True)
    with pytest.raises(BackfillBlocked):BackfillCoordinator(x['ledger'],x['control'].path).execute(x['bid'],adapter=a,guard=SimpleNamespace(check=lambda c:None))
    assert base.uploads==base.submits==0


def test_native_map_tamper_blocks_static_and_preparation_not_old_ids(trial):
    x=trial
    with sqlite3.connect(x['p0'])as db:db.execute("UPDATE fanqie_native_promotion_identities SET native_record_id='999999'")
    with pytest.raises(BackfillBlocked,match='mapping'):
        BackfillCoordinator(x['ledger'],x['control'].path).inspect(x['bid'])


def test_version_manifest_tamper_cannot_borrow_old_authorization(trial):
    x=trial;row=x['ledger'].get(x['bid']);manifest=json.loads(row['manifest_json']);contract=json.loads(row['contract_json'])
    manifest.pop('promotion_contract_schema')
    with pytest.raises(BackfillBlocked,match='version_or_subject'):
        x['ledger'].register(x['bound']['task_id'],json.loads(Path(x['handoff']['path']).read_bytes())['publish_id'],manifest,contract)
    assert x['ledger'].get(x['bid'])['status']=='prepared'


def test_same_book_alias_allows_two_distinct_posts_but_not_same_post_rebinding(trial):
    x=trial;second,bound,_=x['publish']('second','2234567890123456789')
    assert bound['task_id']==x['bound']['task_id']
    other=x['prepare'](second,'prepared-second');assert other['binding_uuid']!=x['bid']
    with pytest.raises(BackfillBlocked,match='publication_already_bound'):
        x['prepare'](x['handoff'],'duplicate-same-post')


def test_reused_snapshot_cannot_serve_later_readback(trial):
    x=trial;calls=[];a=NativeSnapshotAdapter(Base(),lambda **kwargs:(calls.append(kwargs),x['snapshot_ref'])[1])
    manifest=json.loads(x['ledger'].get(x['bid'])['manifest_json'])
    from src.services.fanqie_backfill_workflow import BackfillBinding
    binding=BackfillBinding(**manifest['binding'])
    a.observe(binding)
    with pytest.raises(BackfillBlocked,match='not_refreshed'):a.observe(binding)
    assert calls[-1]=={'phase':'pre_submit','force_refresh':True}


def test_complete_target_with_unrelated_unresolved_row_does_not_block_preparation(trial):
    x=trial;second,_,_=x['publish']('second','2234567890123456789')
    mixed=x['fresh']('mixed',unrelated=True);snapshot=shared.validate_snapshot(shared._read(mixed))
    assert snapshot['rows'][0]['publishable']
    assert snapshot['rows'][1]['identity_status']=='pending' and snapshot['rows'][1]['native_record_id'] is None
    prepared=x['prepare'](second,'prepared-mixed',promotion_ref=mixed)
    assert BackfillCoordinator(x['ledger'],x['control'].path).inspect(prepared['binding_uuid'])['inputs_verified']


def test_populated_native_alias_needs_verified_append_capability_before_upload(trial):
    x=trial;x['authorize']();base=Base()
    a=NativeSnapshotAdapter(base,lambda **kwargs:x['fresh']('populated',links=['https://www.douyin.com/video/2234567890123456789']))
    with pytest.raises(BackfillBlocked,match='append_to_populated'):
        BackfillCoordinator(x['ledger'],x['control'].path).execute(x['bid'],adapter=a,guard=SimpleNamespace(check=lambda c:None))
    assert base.uploads==base.submits==0


def test_missing_managed_native_provider_blocks_before_any_batch_page(trial):
    from src.operations_accounts.fanqie_backfill_control import build_managed_backfill_handlers
    x=trial
    def forbidden(*args,**kwargs):pytest.fail('No page/probe may open before missing native provider notice')
    handler=build_managed_backfill_handlers(x['Accounts'](),x['env'],ledger_path=x['p0'],
        page_provider=forbidden,probe_provider=forbidden)['fanqie_backfill']
    result=handler(SimpleNamespace(),{'binding_uuid':x['bid'],'manifest_sha256':x['ledger'].get(x['bid'])['manifest_sha']})
    assert result.state=='failed' and result.result['reason']=='capability_missing:managed_native_snapshot_provider_required'
