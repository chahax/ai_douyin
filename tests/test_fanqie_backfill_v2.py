"""Local HTML, baseline DDL, and in-memory adapters; no browser/platform calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
from types import SimpleNamespace
import zipfile

import pytest

from src.platform_adapter.fanqie_backfill import parse_promotion_html, normalize_promotion_rows, FanqieBatchPageAdapter, PROMOTION_LIST_URL
from src.services.fanqie_backfill_workflow import BackfillBlocked, digest
from src.services.fanqie_promotion_ledger import PromotionLedger, migrate_ledger
from src.services.fanqie_backfill_coordinator import BackfillCoordinator, prepare_registered_backfill
from src.operations_accounts.fanqie_backfill_control import build_managed_backfill_handlers
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected

BOOK = '7302660145530539062'
POST = '1234567890123456789'
URL = 'https://www.douyin.com/video/' + POST
ROOT = Path(__file__).resolve().parents[1]


def html(*, attrs='data-alias-id="alias-7" data-task-id="task-9" data-promotion-path="抖音搜索"',
         href='', extra='', detail='未填写'):
    heads = ['关键词', '书本信息', '发文类型', '别名状态', '书籍状态', '发文详情', '有效期']
    values = ['测试关键词' + href, '书名 id: ' + BOOK, 'AIGC', '生效中', '可用', detail, '2026-01-01 ~ 2027-01-01']
    return '<table><thead><tr>' + ''.join('<th>'+h+'</th>' for h in heads) + '</tr></thead><tbody><tr '+attrs+'>' + ''.join('<td>'+v+'</td>' for v in values) + '</tr></tbody></table>' + extra


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('No real browser/model/process/network in this suite')
    class ForbiddenPopen(subprocess.Popen):
        def __init__(self,*a,**kw):forbidden(*a,**kw)
    monkeypatch.setattr(subprocess, 'Popen', ForbiddenPopen)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def test_real_HTML_explicit_attributes_and_exact_link_evidence():
    row = parse_promotion_html(html())['items'][0]
    assert (row['alias_id'], row['platform_task_id'], row['promotion_path']) == ('alias-7', 'task-9', '抖音搜索')
    assert row['stable_identity_status'] == 'verified'
    row = parse_promotion_html(html(attrs='', href='<a href="/page/detail?alias_id=alias-7&amp;task_id=task-9&amp;promotion_path=search">详情</a>'))['items'][0]
    assert row['promotion_path'] == 'search'
    assert row['stable_identity_evidence']['alias_id'][0]['kind'] == 'href_query'


def test_real_HTML_never_invents_ID_from_row_key_title_or_other_origin():
    row = parse_promotion_html(html(attrs='data-row-key="alias-7"', href='<a href="https://evil.invalid/?alias_id=alias-7&task_id=task-9&promotion_path=x">x</a>'))['items'][0]
    assert row['stable_identity_status'] == 'needs_sync' and set(row['missing_identity_fields']) == {'alias_id','platform_task_id','promotion_path'}
    assert 'alias_id' not in row


def test_conflicting_explicit_identity_is_pending_not_arbitrarily_chosen():
    row = parse_promotion_html(html(href='<a href="?alias_id=other">详情</a>'))['items'][0]
    assert row['stable_identity_status'] == 'needs_sync' and row['conflicting_identity_fields'] == ['alias_id']
    assert 'alias_id' not in row


def test_explicit_column_values_are_a_separate_evidence_type():
    raw = dict(items=[dict(alias='a',book_id=BOOK,publish_type='AIGC',identity_columns=[
        dict(header=k,value=v) for k,v in [('别名ID','id'),('任务ID','task'),('推广路径','搜索')]])])
    row = normalize_promotion_rows(raw)['items'][0]
    assert row['stable_identity_status'] == 'verified'
    assert row['stable_identity_evidence']['alias_id'][0]['kind'] == 'dom_column'


def test_SHA_pinned_platform_response_exact_subject_only(tmp_path):
    ref = put(tmp_path/'native.json', dict(data=dict(list=[dict(book_id=BOOK,alias='测试关键词',publish_type='AIGC',
        alias_id='alias-7',platform_task_id='task-9',promotion_path='抖音搜索')])))
    capture = dict(schema='fanqie_promotion_response_capture/v1',url='https://kol.fanqieopen.com/observed-endpoint',
        http_status=200,observed_at=time.time(),body=ref)
    context=dict(resource_id='fanqie:test',platform_identity_key='uid:test',environment_key='env',owner_id='owner',generation=1)
    capture.update(context)
    row = parse_promotion_html(html(attrs=''),response_capture=capture,response_context=context)['items'][0]
    assert row['stable_identity_status'] == 'verified'
    assert row['stable_identity_evidence']['alias_id'][0]['body'] == ref
    with pytest.raises(BackfillBlocked,match='stale_or_foreign'):
        parse_promotion_html(html(),response_capture=dict(capture,observed_at=0),response_context=context)
    with pytest.raises(BackfillBlocked,match='managed_context'):
        parse_promotion_html(html(),response_capture=dict(capture,resource_id='other'),response_context=context)
    Path(ref['path']).write_text('{}')
    with pytest.raises(BackfillBlocked,match='body_changed'):
        parse_promotion_html(html(),response_capture=capture,response_context=context)


@pytest.fixture
def trial(tmp_path, request):
    assert tmp_path.resolve().is_relative_to(ROOT)
    p0 = tmp_path/'p0.db'
    media = tmp_path/'candidate.mp4';media.write_bytes(b'protocol-only media, never decoded')
    media_ref = dict(path=str(media),sha256=hashlib.sha256(media.read_bytes()).hexdigest())
    with sqlite3.connect(p0) as db:
        db.executescript((ROOT/'tests/fixtures/fanqie_p0_baseline_20261116.sql').read_text(encoding='utf-8'))
        db.execute("INSERT INTO fanqie_books(id,book_uuid,fanqie_book_id,book_name) VALUES(1,'book',?,'测试小说')",(BOOK,))
        db.execute("INSERT INTO fanqie_promotion_tasks(id,task_uuid,book_id,platform_task_id,promotion_alias,publish_type) VALUES(1,'task',1,'task-9','测试关键词','AIGC')")
        db.execute("INSERT INTO fanqie_script_versions(id,script_uuid,task_id,version) VALUES(1,'script',1,1)")
        db.execute("INSERT INTO fanqie_video_jobs(id,job_uuid,task_id,script_id,output_path,output_sha256) VALUES(1,'job',1,1,?,?)",(str(media),media_ref['sha256']))
        db.execute("INSERT INTO fanqie_douyin_accounts(id,account_uuid,account_key,status) VALUES(1,'account:test','novel_test','active')")
    migrate_ledger(p0,tmp_path/'p0.before.db');ledger=PromotionLedger(p0)
    control = BrowserControlStore(tmp_path/'browser.db')
    payload=dict(account_key='novel_test',video_sha256=media_ref['sha256'],request=dict(video_path=str(media)))
    cmd=control.submit('account:test','dv1','publish','fixture-publish',payload)
    owner=control.acquire_owner('account:test','dv1','pub-owner');control.claim_next('account:test','dv1','pub-owner',owner['generation'])
    published_at='2026-11-16T03:00:00+00:00'
    original_result=dict(status='published',success=True,post_id=POST,publish_url=URL,published_at=published_at,
        publish_evidence=dict(post_verified=True))
    use_sync = getattr(request, 'param', None) == 'sync'
    if use_sync:
        original_result.pop('published_at')
    control.transition(cmd['command_id'],'pub-owner',owner['generation'],'succeeded',result=original_result)
    control.release_owner('account:test','pub-owner',owner['generation'])
    metadata_id = None
    if use_sync:
        sync = control.submit('account:test','dv1','read','sync-publication-date',dict(method='sync_videos'))
        sync_owner = control.acquire_owner('account:test','dv1','sync-owner')
        control.claim_next('account:test','dv1','sync-owner',sync_owner['generation'])
        control.transition(sync['command_id'],'sync-owner',sync_owner['generation'],'succeeded',result=dict(
            read_result=dict(success=True,videos=[dict(video_id=POST,account_uuid='account:test',account_key='novel_test',
                publish_time='2026年11月16日 11:00')])))
        control.release_owner('account:test','sync-owner',sync_owner['generation'])
        metadata_id = sync['command_id']
    with sqlite3.connect(p0) as db:
        db.execute("INSERT INTO fanqie_publish_records(id,publish_uuid,task_id,video_job_id,douyin_account_id,status,douyin_video_id,douyin_video_url) VALUES(1,'published',1,1,1,'published',?,?)",(POST,URL))
    from src.services.publication_evidence import PublicationEvidenceReader
    from src.services.publication_time_evidence_v1 import read_publication_time
    publication=PublicationEvidenceReader(control.path).read(cmd['command_id'],'account:test','dv1')
    time_evidence=read_publication_time(control.path,cmd['command_id'],'account:test','dv1',metadata_command_id=metadata_id)
    published_at=time_evidence['published_at']
    native=put(tmp_path/'PUBLICATION.json',dict(schema='fanqie_h3_publication_evidence/v1',
        command_id=cmd['command_id'],account_uuid='account:test',account_key='novel_test',binding_version='dv1',
        book_id=BOOK,media=media_ref,published_at=published_at,time_evidence=time_evidence,request_sha256=digest(payload),**publication))
    handoff=put(tmp_path/'HANDOFF.json',dict(schema='fanqie_h3_publication_handoff/v1',candidate_id='candidate',
        task_id=1,video_job_id=1,publish_id=1,book_id=BOOK,media=media_ref,command_id=cmd['command_id'],
        account_uuid='account:test',account_key='novel_test',binding_version='dv1',published_at=published_at,
        post_id=POST,publish_url=URL,publication_evidence=native,time_evidence=time_evidence))
    env=dict(resource_id='fanqie:test',binding_version='fv1',environment_key='fenv',douyin_binding_sha256='association')
    identity=dict(platform_identity_key='uid:test',status='active')
    subject=dict(resource_id='fanqie:test',binding_version='fv1',environment_key='fenv',
        platform_identity_key='uid:test',identity_verified=True,challenge=False,observed_at=time.time())
    raw_value=dict(parse_promotion_html(html()),pagination_complete=True)
    raw=put(tmp_path/'DOM.json',dict(schema='fanqie_promotion_DOM_evidence/v1',normalizer_version='v1.1',raw=raw_value,subject=subject))
    from src.operations_accounts.fanqie_managed_promotion_v1 import normalise_snapshot
    snapshot=put(tmp_path/'SNAPSHOT.json',normalise_snapshot(raw_value,**subject,evidence_ref=raw))
    douyin=tmp_path/'douyin.db'
    with sqlite3.connect(douyin) as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,account_key TEXT,status TEXT,public_uid TEXT)')
        db.execute("INSERT INTO account_runtime_bindings VALUES('account:test','novel_test','active','actual_douyin_id')")
    class Repo:
        def get(self,r):return identity
        def guard(self,r,v,o,g,probe):
            assert r=='fanqie:test' and v=='fv1'
            if not probe.get('verified') or probe.get('platform_identity_key')!='uid:test' or probe.get('challenge') or time.time()-probe['observed_at']>60:
                raise BrowserControlRejected('identity_stale','identity stale')
            return identity
    class Accounts:
        db=control.path;douyin_db=douyin
        def get(self,r):assert r=='fanqie:test';return env
        def check_association(self,e):return dict(account_uuid='account:test',account_key='novel_test')
        def bindings(self):return Repo()
    template=tmp_path/'official.xlsx'
    with zipfile.ZipFile(template,'w') as z:
        z.writestr('xl/worksheets/sheet1.xml','''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>别名</v></c><c r="B1"><v>发文日期</v></c><c r="C1"><v>发文链接</v></c><c r="D1"><v>抖音号</v></c></row></sheetData></worksheet>''')
    prepared=prepare_registered_backfill(ledger,control.path,publication_handoff_binding=handoff,accounts=Accounts(),
        resource_id='fanqie:test',promotion_snapshot_binding=snapshot,official_template=template,output_directory=tmp_path/'prepared')
    bid=prepared['binding_uuid'];ledger.authorize(bid,manifest_sha=ledger.get(bid)['manifest_sha'],reference='fixture-user-authorization')
    return dict(tmp=tmp_path,ledger=ledger,bid=bid,accounts=Accounts(),env=env,control=control,
        prepared=prepared,media=media_ref,handoff=handoff,snapshot=snapshot,template=template,metadata_id=metadata_id)


class Adapter:
    def __init__(self, *, fail=None, readback=True):self.uploads=self.submits=0;self.fail=fail;self.readback=readback
    def observe(self,b):
        data=parse_promotion_html(html())
        data['items'][0]['published_links']=[URL] if self.submits and self.readback else []
        return dict(data,account=b.fanqie_account,identity_verified=True,challenge=False,observed_at=time.time())
    def upload(self,path,b):
        self.uploads+=1
        if self.fail=='upload':raise TimeoutError('crash after upload began')
        return dict(upload_ready=True)
    def submit(self,b):
        self.submits+=1
        if self.fail=='submit':raise TimeoutError('crash after submit')
        return None


class Guard:
    def check(self,c):pass


def service(t):return BackfillCoordinator(t['ledger'],t['control'].path,require_strict_contract=True)


def test_real_baseline_DDL_standard_builder_and_strict_success(trial):
    t=trial;row=t['ledger'].get(t['bid']);contract=json.loads(row['contract_json'])
    assert contract['schema']=='fanqie_backfill_contract/v2' and contract['account_link_version']=='association'
    assert contract['media']==t['media'] and not t['prepared']['submitted']
    adapter=Adapter();assert service(t).execute(t['bid'],adapter=adapter,guard=Guard())['status']=='confirmed'
    with pytest.raises(BackfillBlocked):service(t).execute(t['bid'],adapter=adapter,guard=Guard())
    assert adapter.uploads==adapter.submits==1


@pytest.mark.parametrize('field',['platform_task_id','alias_id','promotion_path'])
def test_wrong_stable_ID_or_path_never_uploads(trial,field):
    t=trial;a=Adapter();original=a.observe
    def wrong(b):
        data=original(b);data['items'][0][field]='wrong';return data
    a.observe=wrong
    with pytest.raises(BackfillBlocked,match='stable_promotion'):
        service(t).execute(t['bid'],adapter=a,guard=Guard())
    assert a.uploads==0


@pytest.mark.parametrize('phase',['upload','submit'])
def test_unknown_only_readonly_reconciliation_and_different_link_cannot_complete(trial,phase):
    t=trial;a=Adapter(fail=phase,readback=False)
    assert service(t).execute(t['bid'],adapter=a,guard=Guard())['status']=='outcome_unknown'
    counts=(a.uploads,a.submits)
    with pytest.raises(BackfillBlocked):service(t).execute(t['bid'],adapter=a,guard=Guard())
    original=a.observe
    a.observe=lambda b:dict(original(b),items=[dict(original(b)['items'][0],published_links=['https://www.douyin.com/video/9999999999999999999'])])
    assert service(t).reconcile(t['bid'],adapter=a,guard=Guard())['status']=='outcome_unknown'
    a.observe=lambda b:dict(original(b),items=[dict(original(b)['items'][0],published_links=[URL])])
    assert service(t).reconcile(t['bid'],adapter=a,guard=Guard())['status']=='confirmed'
    assert counts==(a.uploads,a.submits)


def test_other_post_on_same_alias_is_capability_gap_not_overwrite(trial):
    t=trial;a=Adapter();original=a.observe
    a.observe=lambda b:dict(original(b),items=[dict(original(b)['items'][0],published_links=['https://www.douyin.com/video/9999999999999999999'])])
    with pytest.raises(BackfillBlocked,match='capability_missing:append'):
        service(t).execute(t['bid'],adapter=a,guard=Guard())
    assert a.uploads==a.submits==0


@pytest.mark.parametrize('tamper',['media','publish_account','video_job','original_payload','book','type'])
def test_strict_publication_chain_fails_before_upload(trial,tamper):
    t=trial;a=Adapter()
    if tamper=='media':Path(t['media']['path']).write_bytes(b'changed')
    elif tamper=='original_payload':
        with sqlite3.connect(t['control'].path) as db:
            db.execute("UPDATE browser_control_commands SET payload='{}' WHERE kind='publish'")
    elif tamper in {'book','type'}:
        with sqlite3.connect(t['ledger'].path) as db:
            db.execute("UPDATE fanqie_promotion_tasks SET " + ("book_id=999" if tamper=='book' else "publish_type='AI数字人'"))
    else:
        with sqlite3.connect(t['ledger'].path) as db:
            db.execute('UPDATE fanqie_publish_records SET '+('douyin_account_id=999' if tamper=='publish_account' else 'video_job_id=999'))
    with pytest.raises(BackfillBlocked):service(t).execute(t['bid'],adapter=a,guard=Guard())
    assert a.uploads==0


def test_lazy_factory_has_no_schema_or_browser_side_effect(tmp_path):
    calls=[]
    handlers=build_managed_backfill_handlers(SimpleNamespace(db=tmp_path/'absent.db'),{},
        page_provider=lambda *a:calls.append('page'),probe_provider=lambda *a:calls.append('probe'),
        ledger_path=tmp_path/'absent_ledger.db')
    assert set(handlers)=={'fanqie_backfill','fanqie_backfill_reconcile'} and not calls
    assert not list(tmp_path.iterdir())
    blocked=handlers['fanqie_backfill'](None,dict(binding_uuid='fixture',manifest_sha256='0'*64))
    assert blocked.state=='failed' and blocked.result['external_write_started'] is False and not calls
    assert not list(tmp_path.iterdir())


def test_stale_adapter_identity_blocks_even_without_network():
    b=SimpleNamespace(fanqie_account='uid:test')
    page=SimpleNamespace(url=PROMOTION_LIST_URL)
    adapter=FanqieBatchPageAdapter(page,identity_probe=lambda p:dict(account='uid:test',verified=True,challenge=False,observed_at=0),require_fresh_identity=True)
    with pytest.raises(BackfillBlocked,match='stale_fanqie_adapter_identity'):adapter.observe(b)


def test_factory_default_ledger_is_the_shared_configured_closed_loop_path(tmp_path,monkeypatch):
    from src.services import fanqie_promotion_ledger as ledger_module, fanqie_review_service as config
    selected=tmp_path/'configured.db';seen=[]
    monkeypatch.setattr(config,'CLOSED_LOOP_DB_PATH',selected)
    def capture(path):seen.append(Path(path));raise BackfillBlocked('fixture_preflight_stop')
    monkeypatch.setattr(ledger_module,'PromotionLedger',capture)
    handlers=build_managed_backfill_handlers(SimpleNamespace(db=tmp_path/'control.db'),{},
        page_provider=lambda *a:pytest.fail('must not open'),probe_provider=lambda *a:pytest.fail('must not probe'))
    result=handlers['fanqie_backfill'](None,dict(binding_uuid='test',manifest_sha256='0'*64))
    assert result.state=='failed' and seen==[selected]


def test_same_book_allows_distinct_post_records_but_never_rebinds_same_post(trial):
    t=trial;store=t['ledger'];first=store.get(t['bid'])
    manifest=json.loads(first['manifest_json']);contract=json.loads(first['contract_json'])
    assert store.register(1,1,manifest,contract)==t['bid']
    other_post='2234567890123456789';other_url='https://www.douyin.com/video/'+other_post
    other_media=t['tmp']/'other.mp4';other_media.write_bytes(b'another same-book episode')
    media=dict(path=str(other_media),sha256=hashlib.sha256(other_media.read_bytes()).hexdigest())
    payload=dict(account_key='novel_test',video_sha256=media['sha256'],request=dict(video_path=str(other_media)))
    command=t['control'].submit('account:test','dv1','publish','another-original-publish',payload)
    owner=t['control'].acquire_owner('account:test','dv1','another-pub-owner')
    t['control'].claim_next('account:test','dv1','another-pub-owner',owner['generation'])
    original_result=dict(status='published',success=True,post_id=other_post,publish_url=other_url,
        published_at='2026-11-16T03:05:00+00:00',publish_evidence=dict(post_verified=True))
    t['control'].transition(command['command_id'],'another-pub-owner',owner['generation'],'succeeded',result=original_result)
    t['control'].release_owner('account:test','another-pub-owner',owner['generation'])
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO fanqie_video_jobs(id,job_uuid,task_id,script_id,output_path,output_sha256) VALUES(2,'job2',1,1,?,?)",(str(other_media),media['sha256']))
        db.execute("INSERT INTO fanqie_publish_records(id,publish_uuid,task_id,video_job_id,douyin_account_id,status,douyin_video_id,douyin_video_url) VALUES(2,'pub2',1,2,1,'published',?,?)",(other_post,other_url))
    from src.services.publication_evidence import PublicationEvidenceReader
    receipt=PublicationEvidenceReader(t['control'].path).read(command['command_id'],'account:test','dv1')
    from src.services.publication_time_evidence_v1 import read_publication_time
    second_time=read_publication_time(t['control'].path,command['command_id'],'account:test','dv1')
    evidence=put(t['tmp']/'OTHER_PUBLICATION.json',dict(schema='fanqie_h3_publication_evidence/v1',
        book_id=BOOK,media=media,command_id=command['command_id'],account_uuid='account:test',account_key='novel_test',
        binding_version='dv1',published_at=original_result['published_at'],time_evidence=second_time,request_sha256=digest(payload),**receipt))
    h=deepcopy(json.loads(Path(t['handoff']['path']).read_text()));h.update(candidate_id='candidate2',publish_id=2,
        video_job_id=2,media=media,command_id=command['command_id'],post_id=other_post,publish_url=other_url,
        published_at=original_result['published_at'],publication_evidence=evidence,time_evidence=second_time)
    second=prepare_registered_backfill(store,t['control'].path,publication_handoff_binding=put(t['tmp']/'HANDOFF2.json',h),
        accounts=t['accounts'],resource_id='fanqie:test',promotion_snapshot_binding=t['snapshot'],
        official_template=t['template'],output_directory=t['tmp']/'second_preparation')
    assert second['binding_uuid']!=t['bid']
    with sqlite3.connect(store.path) as db:
        assert db.execute('SELECT COUNT(*) FROM fanqie_bindings').fetchone()[0]==2
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO fanqie_publish_records(publish_uuid,task_id,douyin_video_id,douyin_video_url) VALUES('duplicate',999,?,?)",(POST,URL))


def test_new_owner_can_readonly_reconcile_persisted_business_unknown_without_resubmit(trial):
    t=trial
    class Page:
        url=PROMOTION_LIST_URL
        uploads=submits=0
        readback=False
        def evaluate(self,js):
            return parse_promotion_html(html(detail='<a href="'+URL+'">已填写</a>' if self.readback else '未填写'))
        def reload(self,**kw):pass
        def wait_for_timeout(self,ms):pass
        def get_by_role(self,role,*,name,exact=False):
            page=self
            class Locator:
                def count(self):return 1
                def is_visible(self):return True
                def is_enabled(self):return True
                def locator(self,selector):return self
                def get_by_role(self,role,*,name,exact=False):return page.get_by_role(role,name=name,exact=exact)
                def set_input_files(self,path):page.uploads+=1
                def click(self):
                    if name=='提交':
                        page.submits+=1
                        raise TimeoutError('reply lost after submit')
            return Locator()
    page=Page()
    probe=lambda ctx:dict(platform='fanqie',platform_identity_key='uid:test',environment_key='fenv',
        verified=True,challenge=False,observed_at=time.time())
    handlers=build_managed_backfill_handlers(t['accounts'],t['env'],page_provider=lambda ctx,url:page,
        probe_provider=probe,ledger_path=t['ledger'].path)
    t['ledger'].enqueue(t['bid']);command=t['ledger'].dispatch(t['bid'],t['control'])
    owner=t['control'].acquire_owner('fanqie:test','fv1','owner1')
    current=t['control'].claim_next('fanqie:test','fv1','owner1',owner['generation'])
    ctx=SimpleNamespace(task_id=current['command_id'],actor=SimpleNamespace(store=t['control'],owner_id='owner1',generation=owner['generation']))
    result=handlers['fanqie_backfill'](ctx,current['payload'])
    assert result.state=='succeeded' and not result.result['confirmed']
    assert result.result['backfill_status']=='outcome_unknown' and result.result['requires_read_only_reconciliation']
    t['control'].transition(current['command_id'],'owner1',owner['generation'],result.state,result=result.result)
    t['control'].release_owner('fanqie:test','owner1',owner['generation'])
    key='fanqie-backfill-reconcile:'+t['ledger'].get(t['bid'])['business_key']+':'+command['command_id']
    c=t['control'].submit('fanqie:test','fv1','fanqie_backfill_reconcile',key,current['payload'])
    owner2=t['control'].acquire_owner('fanqie:test','fv1','owner2')
    newer=t['control'].claim_next('fanqie:test','fv1','owner2',owner2['generation'])
    ctx2=SimpleNamespace(task_id=newer['command_id'],actor=SimpleNamespace(store=t['control'],owner_id='owner2',generation=owner2['generation']))
    page.readback=True;before=(page.uploads,page.submits)
    finished=handlers['fanqie_backfill_reconcile'](ctx2,newer['payload'])
    assert finished.state=='succeeded' and finished.result['confirmed']
    assert before==(page.uploads,page.submits)==(1,1)
    assert owner2['generation']>owner['generation']


def test_actual_hard_crash_keeps_started_claim_and_is_not_turned_into_known_success(trial):
    t=trial;a=Adapter()
    def hard_crash(path,b):a.uploads+=1;raise KeyboardInterrupt('synthetic hard crash')
    a.upload=hard_crash
    with pytest.raises(KeyboardInterrupt):service(t).execute(t['bid'],adapter=a,guard=Guard())
    assert t['ledger'].get(t['bid'])['status']=='upload_started'
    with pytest.raises(BackfillBlocked):service(t).execute(t['bid'],adapter=a,guard=Guard())
    assert a.uploads==1 and a.submits==0


@pytest.mark.parametrize('trial',['sync'],indirect=True)
def test_actual_publish_result_without_date_uses_exact_successful_creator_sync_evidence(trial):
    t=trial
    h=json.loads(Path(t['handoff']['path']).read_text())
    assert h['time_evidence']['source']=='verified_sync_videos'
    assert h['published_at']=='2026-11-16T11:00:00+08:00'
    assert service(t).inspect(t['bid'])['inputs_verified']
    with sqlite3.connect(t['control'].path) as db:
        raw=json.loads(db.execute('SELECT result FROM browser_control_commands WHERE command_id=?',(t['metadata_id'],)).fetchone()[0])
        raw['read_result']['videos'][0]['video_id']='9999999999999999999'
        db.execute('UPDATE browser_control_commands SET result=? WHERE command_id=?',(json.dumps(raw),t['metadata_id']))
    with pytest.raises(BackfillBlocked,match='publication_time'):
        service(t).inspect(t['bid'])


def test_standard_snapshot_rehashed_derived_path_cannot_depart_from_raw_DOM_evidence(trial):
    t=trial
    snapshot=json.loads(Path(t['snapshot']['path']).read_text())
    snapshot['rows'][0]['promotion_path']='another-path'
    changed=put(t['tmp']/'REHASHED_DERIVED_SNAPSHOT.json',snapshot)
    with pytest.raises(BackfillBlocked,match='raw_subject_or_rows_changed'):
        prepare_registered_backfill(t['ledger'],t['control'].path,publication_handoff_binding=t['handoff'],
            accounts=t['accounts'],resource_id='fanqie:test',promotion_snapshot_binding=changed,
            official_template=t['template'],output_directory=t['tmp']/'wrong-prepare')
    assert not (t['tmp']/'wrong-prepare').exists()
