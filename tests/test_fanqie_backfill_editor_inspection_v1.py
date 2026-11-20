"""Native local DOM + private owner protocol; no live account or platform I/O."""
from types import SimpleNamespace as NS
import json
from pathlib import Path
import pytest
from src.platform_adapter import fanqie_backfill_editor_inspection_v1 as flow

TARGET=dict(book_id='7302660145530539062',book_name='你敢惹我？我有六个反派儿子',alias='从旧饭桌开始改命')
URL='https://www.douyin.com/video/7709043480894524722'


@pytest.fixture(scope='module')
def context():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b=pw.chromium.launch(channel='chrome',headless=True,args=['--disable-background-networking','--mute-audio'])
        c=b.new_context();c.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body='<html><body></body></html>'))
        yield c
        c.close();b.close()


@pytest.fixture
def sample(context):
    n=context.new_page();n.goto('https://kol.fanqieopen.com/page/promotion-list')
    n.set_content('''<input id="outside" value="never-read"><input type="password" value="secret">
      <button id="bulk" type="button">批量回填发文</button><div class="arco-modal" id="detail">
      <h2>推广计划</h2><h3>基础信息</h3><p>书名 你敢惹我？我有六个反派儿子</p><p>别名 从旧饭桌开始改命</p><p>发文类型 AIGC</p>
      <h3>抖音发文</h3><p>发文 1</p><p>发文时间 2026.11.17</p><p>发文链接 <span id="old">https://www.douyin.com/video/7709043480894524722</span></p>
      <button id="open" type="button">回填发文</button></div><script>
      window.opens=0;window.bulk=0;window.submits=0;window.deletes=0;
      Object.defineProperty(document.querySelector('#outside'),'value',{get(){throw Error('unrelated value')}});
      document.querySelector('#bulk').onclick=()=>window.bulk++;
      document.querySelector('#open').onclick=()=>{window.opens++;document.querySelector('#detail').innerHTML=
        '<h2>推广计划</h2><p>你敢惹我？我有六个反派儿子</p><p>从旧饭桌开始改命</p><p>AIGC</p>'+
        '<input readonly value="https://www.douyin.com/video/7709043480894524722"><input placeholder="新发文链接" value="">'+
        '<button id="delete" type="button">删除</button><button id="save" type="button">提交</button>';
        document.querySelector('#save').onclick=()=>window.submits++;document.querySelector('#delete').onclick=()=>window.deletes++;};
      </script>''')
    class Page:
        _session=object();tab_id='owned-tab'
        def evaluate(self,script):return n.evaluate(script)
        def locator(self,selector):return n.locator(selector)
        def wait_for_timeout(self,ms):return None
    stages=[];hook=[None]
    def checkpoint(stage,value):
        assert stage not in [s for s,v in stages]
        stages.append((stage,value))
        if hook[0] and stage=='editor_open_intent':hook[0]()
    yield NS(native=n,page=Page(),stages=stages,hook=hook,checkpoint=checkpoint)
    n.close()


def run(x):
    return flow.inspect_open_editor_from_details(x.page,**TARGET,retained_url=URL,guard=lambda:None,checkpoint=x.checkpoint)


def test_native_editor_opens_once_without_data_entry_or_submit(sample):
    x=sample;result=run(x)
    assert x.native.evaluate('()=>[window.opens,window.bulk,window.submits,window.deletes]')==[1,0,0,0]
    assert result['status']=='editor_controls_observed' and result['stable']
    assert result['observation']['controls']['exact_editor_scope_count']==1
    fields=result['observation']['controls']['inputs']
    assert len(fields)==2 and fields[0]['public_value']==URL and fields[0]['read_only']
    assert fields[1]['public_value']=='' and x.native.locator('input[placeholder="新发文链接"]').input_value()==''
    encoded=json.dumps(result,ensure_ascii=False)
    assert 'secret' not in encoded and 'never-read' not in encoded
    assert not result['submitted'] and not result['append_capability_verified'] and not result['fields_written']


def test_retained_detail_changed_after_durable_intent_blocks_native_opener(sample):
    x=sample;x.hook[0]=lambda:x.native.locator('#old').evaluate("e=>e.textContent='another link'")
    with pytest.raises(flow.BackfillEditorNotConfirmed):run(x)
    assert x.native.evaluate('()=>[window.opens,window.bulk,window.submits,window.deletes]')==[0,0,0,0]


def test_private_owner_routes_new_editor_inspection_only(tmp_path,monkeypatch):
    from test_fanqie_managed_promotion_v1 import accounts,Session
    from src.operations_accounts.fanqie_account_control import run_owner
    a,env=accounts.__wrapped__(tmp_path);calls=[]
    def reader(page,*,book_id,book_name,alias,retained_url,guard,checkpoint):
        guard();assert retained_url==URL and (book_id,book_name,alias)==tuple(TARGET.values())
        calls.append(page);checkpoint('editor_open_intent',dict(opener_click_limit=1))
        return dict(schema='fanqie_backfill_editor_inspection/v1',status='editor_controls_observed',submitted=False,append_capability_verified=False)
    monkeypatch.setattr(flow,'inspect_backfill_editor',reader)
    target=dict(book_id=TARGET['book_id'],book_name=TARGET['book_name'],lookup_alias=TARGET['alias'],retained_url=URL)
    kind='fanqie_backfill_editor_inspect'
    for extra in [dict(promotion_request={}),dict(lookup_request={}),dict(locate=True),dict(chapters=1),dict(observer_request={}),dict(snapshot_version='v2'),dict(binding_uuid='wrong')]:
        with pytest.raises(ValueError):a.queue(env['resource_id'],kind,**target,**extra)
    cmd=a.queue(env['resource_id'],kind,**target)
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and len(calls)==1 and Session.submit_count==0
    evidence=json.loads(Path(result['result']['backfill_editor_inspection']['path']).read_text(encoding='utf8'))
    assert evidence['managed_subject']['task_id']==cmd['command_id']
    assert evidence['managed_subject']['platform_identity_key']=='uid:12345'
    assert result['result']['backfill_submitted'] is False and result['result']['automatic_retry'] is False


def test_cli_routes_exact_editor_target_and_no_write_request(monkeypatch):
    import sys
    from scripts import run_fanqie_account as cli
    calls=[]
    class Accounts:
        def queue(self,*args,**kw):calls.append((args,kw));return {'command_id':'private-cid'}
    monkeypatch.setattr(cli,'FanqieAccounts',lambda *a,**kw:Accounts())
    monkeypatch.setattr(cli,'launch_worker',lambda *a,**kw:{'fixture':True})
    argv=['prog','backfill-editor-inspect','--resource','private-resource','--book-id',TARGET['book_id'],
          '--book-name',TARGET['book_name'],'--lookup-alias',TARGET['alias'],'--retained-url',URL]
    monkeypatch.setattr(sys,'argv',argv);cli.main()
    assert calls==[(('private-resource','fanqie_backfill_editor_inspect'),dict(book_name=TARGET['book_name'],chapters=0,
                  book_id=TARGET['book_id'],lookup_alias=TARGET['alias'],retained_url=URL))]
    for extra in (['--request','unused.json'],['--lookup-request','unused.json'],['--identity','different'],['--chapters','1']):
        monkeypatch.setattr(sys,'argv',argv+extra)
        with pytest.raises(SystemExit) as error:cli.main()
        assert error.value.code==2
    assert len(calls)==1
