"""Native v2/v3 synthetic-valid full public chain, real P0 and identity validators.

Only browser I/O and the remote publisher are substituted. Ledgers, identity
fences, snapshots, manifests, evidence readers, actors and coordinators are real.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
import uuid
from types import SimpleNamespace
import zipfile
import xml.etree.ElementTree as ET

import pytest

from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor
from src.operations_accounts.fanqie_account_control import FanqieAccounts
from src.operations_accounts import fanqie_managed_promotion_v1 as promotion
from src.operations_accounts.fanqie_backfill_control import build_managed_backfill_handlers
from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace
from src.platform_adapter.fanqie_backfill import parse_promotion_html
from src.platform_adapter.fanqie_list_filter_inventory_v1 import LIST_FILTER_INVENTORY_JS
from test_fanqie_managed_promotion_v1 import visible_list_filters


BOOK='7302660145530539062'
POST='1234567890123456789'
URL='https://www.douyin.com/video/'+POST
ROOT=Path(__file__).resolve().parents[1]


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def html():
    heads=['关键词','书本信息','发文类型','别名状态','书籍状态','发文详情','有效期']
    cells=['测试关键词','<span class="book-name-iHil3A">测试小说</span> id: '+BOOK,'AIGC','生效中','可用','未填写','2026-01-01 ~ 2030-01-01']
    return '<table><thead><tr>'+''.join('<th>'+v+'</th>' for v in heads)+'</tr></thead><tbody><tr>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr></tbody></table>'


@pytest.fixture
def native_chain(tmp_path,monkeypatch,request):
    def forbidden(*a,**kw):raise AssertionError('No external process/network in workspace chain')
    class NoProcess(subprocess.Popen):
        def __init__(self,*a,**kw):forbidden()
    monkeypatch.setattr(subprocess,'Popen',NoProcess)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket.socket,'connect_ex',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    assert tmp_path.resolve().is_relative_to(ROOT/'data')
    runtime=tmp_path/'runtime.db'
    fields=dict(account_uuid='account:test',account_key='novel_test',platform_identity_key='douyin:test',
        browser_environment_key='douyin:env',browser_profile_dir=str(tmp_path/'unused_douyin_profile'),
        storage_state_path=str(tmp_path/'unused_state.json'),confirmed_by='fixture-user',created_at='2026-01-01',profile_version=1)
    dv=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()
    with sqlite3.connect(runtime) as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,account_key TEXT,platform_identity_key TEXT,browser_environment_key TEXT,browser_profile_dir TEXT,storage_state_path TEXT,confirmed_by TEXT,created_at TEXT,status TEXT,platform TEXT,public_uid TEXT)')
        db.execute('CREATE TABLE account_strategy_versions(account_uuid TEXT,profile_version INTEGER,is_active INTEGER)')
        db.execute('CREATE TABLE douyin_accounts(account_uuid TEXT,status TEXT)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?,?,?,?,?,?,?,?,?,?)',(*[v for k,v in fields.items() if k!='profile_version'],'active','douyin','actual_douyin_display_id'))
        db.execute("INSERT INTO account_strategy_versions VALUES('account:test',1,1)")
        db.execute("INSERT INTO douyin_accounts VALUES('account:test','active')")
    control=BrowserControlStore(tmp_path/'control.db')
    accounts=FanqieAccounts(db=control.path,profiles=tmp_path/'fanqie_profiles',evidence=tmp_path/'evidence',douyin_db=runtime)
    accounts.install();env=accounts.create('local fixture','novel_test');resource=env['resource_id']
    def probe(*args):return dict(schema='platform_identity_probe/v1',platform='fanqie',verified=True,challenge=False,
        platform_identity_key='fanqie:uid:test',environment_key=env['environment_key'],identity_source='platform_account_id',observed_at=time.time())
    pr=put(accounts.evidence/'identity_probe.json',probe())
    confirmation=put(accounts.evidence/'identity_confirmation.json',dict(schema='platform_identity_confirmation/v1',
        platform='fanqie',resource_id=resource,platform_identity_key='fanqie:uid:test',binding_version=env['binding_version'],
        environment_key=env['environment_key'],profile_dir=env['profile_dir'],decision_source='explicit_user_confirmation',
        user_statement='Isolated test fixture identity',probe_evidence=pr))
    accounts.bindings().confirm(confirmation)
    p0=tmp_path/'p0.db'
    with sqlite3.connect(p0) as db:db.executescript((ROOT/'tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text(encoding='utf8'))
    ws=PromotionWorkspace(p0,accounts=accounts,launcher=lambda command,accounts:dict(queued_only=True),
        account_resolver=lambda key:dict(account_uuid='account:test',account_key='novel_test',binding_version=dv))
    ws.migrate(tmp_path/'backups')
    visible=[]
    from src.platform_adapter import fanqie_promotion_observer_v1 as observer
    from src.services import fanqie_promotion_identity_v2 as native
    class LocalListPage:
        url=observer.ORIGIN+'/page/promotion-list'
        def __init__(self):self.main_frame=object();self.listeners={};self.observers={}
        def evaluate(self,script):
            if script==observer.RESOURCE_JS:
                return [dict(origin=observer.ORIGIN,path=p,initiator_type='fetch') for p in (native.PROMOTION_ENDPOINT,native.ENUM_ENDPOINT)]
            if script==LIST_FILTER_INVENTORY_JS:return visible_list_filters()
            assert script==promotion.LIST_JS
            data=parse_promotion_html(html());data['items'][0]['published_links']=list(visible)
            return dict(data,has_next=False,loading=False,empty_state=False,pagination_ambiguous=False)
        def on(self,event,callback):self.listeners[event]=callback
        def remove_listener(self,event,callback):del self.listeners[event]
        def fanqie_promotion_observer(self,mode,**kwargs):
            return observer.worker_action(self,self.observers,'local-native-tab',mode=mode,**kwargs)
        def goto(self,url,**kwargs):
            assert url==self.url
            record=dict(alias_id='1234567890123456789',book_id=BOOK,book_name='测试小说',alias_name='测试关键词',
                task_type=1,alias_post_type=29,alias_status=3,book_status=1,alias_start_time='2026-01-01',alias_end_time='2030-01-01')
            responses=[(native.PROMOTION_ENDPOINT,dict(code=0,data=dict(total=1,promotion_list=[record]))),
                (native.ENUM_ENDPOINT,dict(code=0,data=dict(kol_alias_post_type=[dict(text='AIGC',value=29)])))]
            for path,body in responses:
                raw=json.dumps(body,ensure_ascii=False).encode()
                response=SimpleNamespace(url=observer.ORIGIN+path,status=200,header_value=lambda key:'application/json',body=lambda raw=raw:raw)
                request=SimpleNamespace(url=response.url,frame=self.main_frame,resource_type='fetch',method='GET',
                    response=lambda response=response:response,sizes=lambda raw=raw:dict(responseBodySize=len(raw)))
                response.request=request
                self.listeners['requestfinished'](request)
        def wait_for_timeout(self,milliseconds):pass
    def run_handlers(handlers):
        actor=BrowserControlActor(control,resource,env['binding_version'],'local-owner:'+uuid.uuid4().hex,handlers)
        try:
            outcome=actor.run_next()
            assert outcome is not None
            return outcome,actor.generation
        finally:actor.close()
    def sync():
        queued=ws.sync(resource,snapshot_version='v2')
        out,_=run_handlers(promotion.make_handlers(accounts,env,page_provider=lambda *a:LocalListPage(),probe_provider=probe))
        assert out['state']=='succeeded' and out['command_id']==queued['command_id']
        assert promotion._read(out['result']['visible_list_filters'])['observation']==visible_list_filters()
        return ws.latest_snapshot(resource)
    media=put(tmp_path/'media.mp4','protocol media bytes; no codec invoked')
    script=put(tmp_path/'script.md','existing script');selection=put(tmp_path/'selection.json',{})
    source_case=put(tmp_path/'case.json',{'shots':[{'authoritative_script':script,'script_selection':selection}]})
    generation=put(tmp_path/'generation.json',{'segments':[{'source_case':source_case}]})
    code=put(tmp_path/'source.py','existing code');plan=put(tmp_path/'plan.json',{'code':[code]})
    proof=put(tmp_path/'proof.json',{'protocol':True});result=put(tmp_path/'result.json',dict(file=media,proof=proof,plan=plan))
    book=put(tmp_path/'book.json',dict(book_id=BOOK));known=put(tmp_path/'known.json',dict(visual_issues=True))
    h=put(tmp_path/'handoff.json',dict(schema='novel_promotion_local_candidate/v1',book_id=BOOK,book_name='测试小说',
        account_key='novel_test',media_binding=media,source_manifest=book,source_generation_manifest=generation,
        technical_proof_binding=proof,assembly_receipt_binding=result,known_visual_finding=known,
        overall_video_quality_passed=False,publish_allowed=False))
    pv=put(tmp_path/'provenance.json',dict(schema='fanqie_candidate_provenance/v1',book_id=BOOK,media=media,script=script,
        script_selections=[selection],source_cases=[source_case],source_code=[code],book_manifest=book,assembly_result=result))
    qa=put(tmp_path/'qa.json',dict(status='technical_cache_review_passed',file=media,result=result,proof=proof,
        all_frame_pixels_and_PTS_cache_revalidated=True,audio_PCM_and_AAC_metrics_cache_revalidated=True,original_sources_SHA_revalidated=True))
    cid=ws.register_candidate(h,pv,qa,account_key='novel_test')
    snapshot_ref=sync();snapshot=promotion._read(snapshot_ref);promotion_key=native.selection_key(snapshot,snapshot['rows'][0])
    ws.bind_candidate(cid,resource,promotion_key=promotion_key)
    ws.record_review(cid,user_statement='Accept this exact fixture media and disclosed defects')
    metadata=dict(title='测试小说片段',hashtags=['小说推文','AI生成'])
    metadata.update(getattr(request,'param',{'description':'AI生成虚构故事'}))
    sync()
    publication=ws.prepare_publish(cid,resource,promotion_key=promotion_key,metadata=metadata,
        user_statement='Approve this exact publication copy and promotion')
    from src.operations_accounts import browser_control_runtime as runtime_module
    queued_publications=[]
    def enqueue(key,kind,payload,idempotency,priority):
        assert key=='novel_test'
        return control.submit('account:test',dv,kind,idempotency,dict(payload,account_key=key,account_uuid='account:test'),priority=priority)
    def publisher(key,request,*,authorization):
        queued_publications.append(asdict(request))
        return enqueue(key,'publish',dict(request=asdict(request),authorization=authorization,video_sha256=media['sha256']),
            'publish:'+media['sha256'],100)
    monkeypatch.setattr(runtime_module,'queue_publish_request',publisher)
    monkeypatch.setattr(runtime_module,'_submit',enqueue)
    sync();command=ws.dispatch_publish(cid,resource,promotion_key=promotion_key)
    assert ws.dispatch_publish(cid,resource,promotion_key=promotion_key)==command and len(queued_publications)==1
    def settle(account,version,cid,result):
        owner='fixture-result:'+uuid.uuid4().hex;owned=control.acquire_owner(account,version,owner)
        assert control.claim_next(account,version,owner,owned['generation'])['command_id']==cid
        control.transition(cid,owner,owned['generation'],'succeeded',result=result)
        control.release_owner(account,owner,owned['generation'])
    settle('account:test',dv,command,dict(status='published',success=True,post_id=POST,publish_url=URL,publish_evidence=dict(post_verified=True)))
    meta=ws.request_publication_metadata(cid)
    settle('account:test',dv,meta['command_id'],dict(read_result=dict(success=True,videos=[dict(video_id=POST,
        account_uuid='account:test',account_key='novel_test',publish_time='2026年11月16日 11:00')])))
    published=ws.attach_publication(cid,command,metadata_command_id=meta['command_id'])
    template=tmp_path/'official.xlsx'
    with zipfile.ZipFile(template,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="发文回填" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="str"><v>别名</v></c><c r="B1" t="str"><v>发文日期</v></c><c r="C1" t="str"><v>发文链接</v></c><c r="D1" t="str"><v>抖音号</v></c></row></sheetData></worksheet>')
    sync();prepared=ws.prepare_backfill(published,resource,template,tmp_path/'backfill')
    bid=prepared['binding_uuid'];ledger=ws._backfill();manifest_sha=ledger.get(bid)['manifest_sha']
    manifest=json.loads(Path(prepared['manifest']['path']).read_text(encoding='utf8'))
    # Independent OOXML package traversal; no optional Excel library/download.
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(manifest['workbook']) as z:
        assert '[Content_Types].xml' in z.namelist() and '_rels/.rels' in z.namelist()
        workbook=ET.fromstring(z.read('xl/workbook.xml'));sheet=workbook.find('s:sheets/s:sheet',ns)
        relation_id=sheet.attrib['{'+ns['r']+'}id']
        relations=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        target=next(r.attrib['Target'] for r in relations if r.attrib['Id']==relation_id)
        sheet_xml=ET.fromstring(z.read('xl/'+target))
        rows=sheet_xml.findall('s:sheetData/s:row',ns)
        header=[c.findtext('s:v',namespaces=ns) for c in rows[0]]
        data=[c.findtext('s:is/s:t',namespaces=ns) for c in rows[1]]
        assert header==['别名','发文日期','发文链接','抖音号']
        assert data[2]==URL and data[1]=='2026/11/16'
    ws.authorize_backfill(bid,manifest_sha256=manifest_sha,user_statement='Approve this exact spreadsheet and original URL')
    observation_count=[0]
    def native_provider(ctx,*,phase='preflight',force_refresh=False):
        observation_count[0]+=1
        subject=dict(resource_id=resource,binding_version=env['binding_version'],environment_key=env['environment_key'],
            platform_identity_key=probe()['platform_identity_key'],owner_id=ctx.actor.owner_id,generation=ctx.actor.generation,task_id=ctx.task_id)
        return promotion.capture_native_snapshot(LocalListPage(),env=env,managed_subject=subject,
            identity=probe,guard=ctx.check_dispatch,evidence_directory=accounts.folder(ctx.task_id)/('native_'+str(observation_count[0])))
    assert promotion._read(published)['schema']=='fanqie_h3_publication_handoff/v2'
    assert manifest['promotion_contract_schema']=='fanqie_backfill_contract/v3'
    return locals()


@pytest.mark.parametrize('native_chain', [{'story_hook':'她为什么把钥匙还给了陌生人？'}, {}], indirect=True)
def test_novel_copy_bound_from_preview_through_dispatch_and_receipt(native_chain):
    from src.platform_adapter.publish_verification import FICTION_NOTICE, declared_description
    x=native_chain
    prepared=x['publication']
    comment='想看后续，打开番茄小说搜「测试关键词」。原著是《测试小说》📖'
    caption=prepared['request']['description']
    hook=x['metadata'].get('story_hook',x['metadata']['title'])
    assert hook in caption and '可能获益' in caption and 'AI' in caption
    assert caption.count(FICTION_NOTICE)==1 and declared_description(caption,True)==caption
    assert '测试关键词' not in caption and '打开番茄' not in caption
    assert prepared['comment']==comment
    authority=promotion._read(prepared['authorization'])
    assert authority['comment']==comment and authority['candidate_id']==x['cid']
    with sqlite3.connect(x['control'].path) as db:
        raw=db.execute('SELECT payload FROM browser_control_commands WHERE command_id=?',(x['command'],)).fetchone()[0]
    payload=json.loads(raw)
    assert payload['authorization']=={**prepared['authorization'],'comment':comment}
    assert payload['request']==prepared['request']
    preview={**x['metadata'],'description':caption,'comment':comment}
    for changed in ({'comment':'其他作品'},{'description':'另一段文案'}):
        with pytest.raises(ValueError,match='重新核对发布预览'):
            x['ws'].prepare_publish(x['cid'],x['resource'],promotion_key=x['promotion_key'],
                metadata={**preview,**changed},user_statement='Confirm the displayed copy')


@pytest.mark.parametrize('scenario',['confirmed','unknown_then_readonly','changed_media'])
def test_public_native_workspace_full_chain(native_chain,monkeypatch,scenario):
    x=native_chain;uploads=[];submits=[];visible=x["visible"]
    class LocalPlatformAdapter:
        def __init__(self,*a,**k):pass
        def _check(self,binding):assert binding.fanqie_account=='fanqie:uid:test'
        def observe(self,binding):
            data=parse_promotion_html(html());data['items'][0]['published_links']=list(visible)
            return dict(data,account='fanqie:uid:test',identity_verified=True,challenge=False,observed_at=time.time())
        def upload(self,path,binding):uploads.append(str(path));return dict(upload_ready=True)
        def submit(self,binding):
            submits.append(binding.alias)
            if scenario=='unknown_then_readonly':raise TimeoutError('remote response lost after submit')
            visible.append(URL)
    import src.platform_adapter.fanqie_backfill as adapter_module
    monkeypatch.setattr(adapter_module,'FanqieBatchPageAdapter',LocalPlatformAdapter)
    handlers=build_managed_backfill_handlers(x['accounts'],x['env'],page_provider=lambda *a:object(),
        probe_provider=x['probe'],ledger_path=x['p0'],native_snapshot_provider=x['native_provider'])
    if scenario=='changed_media':Path(x['media']['path']).write_bytes(b'changed media')
    queued=x['ws'].dispatch_backfill(x['bid'])
    outcome,generation=x['run_handlers'](handlers)
    assert queued['command']['command_id']==outcome['command_id']
    if scenario=='changed_media':
        assert outcome['state']=='failed' and uploads==submits==[]
        assert x['ledger'].get(x['bid'])['status']=='ready'
    elif scenario=='confirmed':
        assert outcome['state']=='succeeded' and x['ws'].backfill_status(x['bid'])['business_status']=='confirmed'
        assert len(uploads)==len(submits)==1
    else:
        assert outcome['state']=='succeeded' and x['ws'].backfill_status(x['bid'])['business_status']=='outcome_unknown'
        original=x['ledger'].get(x['bid']);visible.append(URL);uploads.clear();submits.clear()
        x['ws'].reconcile_backfill(x['resource'],x['bid'],x['manifest_sha'])
        final,new_generation=x['run_handlers'](handlers)
        assert new_generation>generation and final['state']=='succeeded'
        assert x['ledger'].get(x['bid'])['status']=='confirmed' and uploads==submits==[]
        assert original['status']=='outcome_unknown' and x['ledger'].get(x['bid'])['attempt_count']==original['attempt_count']
    with sqlite3.connect(x['p0']) as d:
        assert d.execute('SELECT count(*) FROM fanqie_video_jobs').fetchone()[0]==1
        assert d.execute('SELECT count(*) FROM fanqie_publish_records').fetchone()[0]==1
    assert json.loads(Path(x['h']['path']).read_text(encoding='utf8'))['overall_video_quality_passed'] is False
