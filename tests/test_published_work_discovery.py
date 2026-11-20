import json
from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from src.shared.published_work_discovery import discover_published_work,is_manage_url
from src.platform_adapter.publish_verification import inspect_published_video

TITLE='这份申请，我没提｜离职原因别写反'
MANAGE='https://creator.douyin.com/creator-micro/content/manage?enter_from=publish'
URL='https://www.douyin.com/video/123456'


@pytest.fixture(scope='module')
def context(tmp_path_factory):
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(tmp_path_factory.mktemp('discovery')),channel='chrome',headless=True,args=['--mute-audio'])
        context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body='<html></html>')
            if route.request.url in (MANAGE,URL) else route.abort())
        yield context
        context.close()


@pytest.fixture
def page(context):
    page=context.new_page();page.goto(MANAGE)
    yield page
    page.close()


def card(title=TITLE,url=URL):return f'<article><span>{title}</span><a href="{url}">查看作品</a></article>'


def test_exact_manage_redirect_title_card_and_canonical_id(page):
    page.set_content(card())
    result=discover_published_work(page,TITLE)
    assert result['verified'] and result['post_id']=='123456' and result['publish_url']==URL
    assert not is_manage_url(MANAGE+'&unexpected=1')


def test_outer_title_cannot_borrow_id_from_another_nested_work_card(page):
    page.set_content(f'<div><span>{TITLE}</span><article><span>OtherTitle</span><a href="{URL}">查看作品</a></article></div>')
    assert not discover_published_work(page,TITLE)['verified']


def test_legitimate_work_tag_list_items_are_not_other_work_cards(page):
    page.set_content(card().replace('</article>','<ul><li>#劳动法</li><li>#AI剧情</li></ul></article>'))
    assert discover_published_work(page,TITLE)['verified']


@pytest.mark.parametrize('html,reason',[(card()+card(),'title_not_unique'),
    (f'<article>{TITLE}</article>','canonical_id_missing'),
    (card()+f'<a href="{URL}">Unrelated</a>','ok'),
    (f'<article><span>{TITLE}</span><a href="{URL}">一</a><a href="https://www.douyin.com/video/999">二</a></article>','card_video_id_ambiguous')])
def test_title_only_ambiguity_and_unrelated_links_do_not_create_id(page,html,reason):
    page.set_content(html);result=discover_published_work(page,TITLE)
    assert result['verified']==(reason=='ok')
    if reason!='ok':assert result['reason']==reason


def test_native_unique_detail_click_observes_exact_url_without_publishing(page):
    page.set_content(f'<article><span>{TITLE}</span><button onclick="location.href=\'{URL}\'">查看详情</button></article>')
    assert discover_published_work(page,TITLE)['publish_url']==URL


def test_exact_work_caption_tags_and_player_metadata_are_required(page):
    page.goto(URL)
    page.set_content(f'<article><video></video><figcaption>{TITLE} 剧情虚构，非真实事件。#劳动法 #劳动权益 #离职避坑 #普法知识 #AI剧情</figcaption><span>内容由AI生成</span></article>')
    page.locator('video').evaluate('v=>{Object.defineProperty(v,"readyState",{value:2});Object.defineProperty(v,"duration",{value:60})}')
    result=inspect_published_video(page,'123456',required_hashtags=['劳动法','劳动权益','离职避坑','普法知识','AI剧情'],expected_title=TITLE)
    assert result['verified'] and result['hashtags_verified']
    page.locator('figcaption').evaluate('n=>n.textContent=n.textContent.replace("#劳动法 ","#劳动法律 ")')
    assert not inspect_published_video(page,'123456',required_hashtags=['劳动法'],expected_title=TITLE)['verified']


def test_unknown_work_layout_returns_bounded_structure_not_static_success(page):
    page.goto(URL);page.set_content('<main><video></video><span>内容由AI生成</span></main>')
    result=inspect_published_video(page,'123456',required_hashtags=['劳动法'])
    assert not result['verified'] and result['layout']['visibleVideos']==1


def test_workflow_manage_route_without_toast_uses_exact_discovery(tmp_path,monkeypatch):
    import src.platform_adapter.publish_workflow as module
    workflow=module.PublishWorkflow(SimpleNamespace());workflow._last_publish_title=TITLE
    page=SimpleNamespace(url=MANAGE)
    workflow._confirm_publish_in_manage_page=lambda *_a,**_k:URL
    assert workflow._wait_for_publish_result(page,timeout=1)==('123456',URL)


def test_initial_exact_canonical_url_is_immediate_and_wrong_host_or_query_id_never_final():
    from src.platform_adapter.publish_workflow import PublishWorkflow
    workflow=PublishWorkflow(SimpleNamespace());workflow._last_publish_title=TITLE
    assert workflow._wait_for_publish_result(SimpleNamespace(url=URL),timeout=1)==('123456',URL)
    for url in ['https://evil.example/video/123456',MANAGE+'&aweme_id=123456','https://www.douyin.com/status/123456']:
        assert not workflow._is_final_video_url(url)


@pytest.mark.parametrize('mode',['verified','pending','comment_unknown','active_missing'])
def test_reconciliation_precise_evidence_and_comment_once(tmp_path,monkeypatch,mode):
    import src.operations_accounts.publication_reconciliation as module
    import src.operations_accounts.publication_reconciliation_authorization as auth
    import src.operations_accounts.publication_comment as comment
    root=tmp_path;monkeypatch.setattr(module,'ROOT',root)
    prepared={'title':TITLE,'hashtags':['劳动法'],'comment':'原批准评论'}
    from pathlib import Path
    prior=[json.loads(row) for row in (Path(__file__).resolve().parents[1]/'data/development_checkpoints/publication_reconciliation_browser_20261019/ORIGINAL_JOURNAL.jsonl').read_text(encoding='utf-8').splitlines()]
    if mode=='active_missing':prior=[r for r in prior if r.get('set_selected') is not True]
    original_auth={'path':'original-PREPARED','sha256':'frozen','comment':'原批准评论'}
    monkeypatch.setattr(auth,'get_verified_reconciliation_inputs',lambda _:dict(prepared=prepared,
        authorization={'frozen':True},journal_rows=prior,original_command={'payload':{'authorization':original_auth}}))
    calls=[]
    native_receipt={'status':'outcome_unknown' if mode=='comment_unknown' else 'sent_visible','identity':{'account_uuid':'a','post_id':'123456','comment_sha256':'fixed'}}
    def send(_adapter,command,_id):
        assert command['authorization'] is original_auth
        calls.append(True);return native_receipt
    monkeypatch.setattr(comment,'post_authorized_publication_comment',send)
    page=SimpleNamespace(url=URL,wait_for_timeout=lambda _:None,discover_published_work=lambda _:dict(verified=True,post_id='123456',publish_url=URL),
        _cmd=lambda *_a,**_k:None,goto=lambda _:None,
        inspect_published_video=lambda *_a,**_k:dict(verified=mode!='pending',ai_label_visible=True,fiction_notice_visible=True,
            hashtags_verified=True,player={'ready':True,'error':False,'duration':True},review_status='clear'))
    session=SimpleNamespace(open_page=lambda _:page)
    context=SimpleNamespace(account_key='account01',account_uuid='a')
    resource=SimpleNamespace(account_uuid='a',account_key='account01',context=context,reconciliation_session=session,
        runtime=SimpleNamespace(verify_identity=lambda *_a,**_k:SimpleNamespace(healthy=True)))
    ctx=SimpleNamespace(task_id='a'*32,resource=resource,check_dispatch=lambda:None)
    payload={'account_uuid':'a','account_key':'account01','original_command_id':'b'*32}
    result=module.run_reconciliation(ctx,payload)
    expected='verified_published' if mode=='verified' else ('outcome_unknown' if mode=='comment_unknown' else 'verification_pending')
    assert result['status']==expected
    assert module.run_reconciliation(ctx,payload)==result
    assert calls==([True] if mode in ('verified','comment_unknown') else [])
    saved=json.loads(__import__('pathlib').Path(result['evidence_ref']['path']).read_text(encoding='utf-8'))
    assert saved['schema']=='publication_reconciliation_evidence/20261019/v1'


def test_actual_worker_discovery_and_exact_caption_verification(tmp_path,monkeypatch):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    from src.platform_adapter import browser_session as browser_module
    import test_upload_check_transition_dom as fixture
    markup=f'<meta charset="utf-8"><article><h2>{TITLE}</h2><a href="{URL}">查看作品</a><video></video><figcaption>剧情虚构，非真实事件。#劳动法</figcaption><span>内容由AI生成</span></article>'
    markup+='''<script>const v=document.querySelector('video');Object.defineProperty(v,'readyState',{value:2});Object.defineProperty(v,'duration',{value:60});</script>'''
    owner=BrowserSession(BrowserSessionConfig('http://127.0.0.1','http://127.0.0.1',
        str(tmp_path/'state.json'),str(tmp_path/'profile'),headless=True,timeout_ms=5000))
    monkeypatch.setattr(fixture,'HTML',markup);fixture.intercept_test_worker(monkeypatch,owner)
    source=browser_module._PW_SCRIPT.replace('_fixture_urls='+repr((fixture.UPLOAD_URL,fixture.EDITOR_URL)),
        '_fixture_urls='+repr((MANAGE,URL)),1)
    monkeypatch.setattr(browser_module,'_PW_SCRIPT',source)
    try:
        page=owner.get_page();page.goto(MANAGE)
        result=page.discover_published_work(TITLE)
        assert result['verified'] and result['publish_url']==URL
        page.goto(URL)
        assert page.inspect_published_video('123456',ai_required=True,fiction_required=True,
            required_hashtags=['劳动法'],expected_title=TITLE)['verified']
    finally:owner.stop()


def test_original_journal_final_ai_read_after_reserve_before_single_native_click():
    from pathlib import Path
    from src.operations_accounts.publication_reconciliation import _active_ai_source
    rows=[json.loads(row)for row in (Path(__file__).resolve().parents[1]/'data/development_checkpoints/publication_reconciliation_browser_20261019/ORIGINAL_JOURNAL.jsonl').read_text(encoding='utf-8').splitlines()]
    assert _active_ai_source(rows)
    reserve=next(i for i,row in enumerate(rows)if row['stage']=='submission_started')
    final=next(i for i,row in enumerate(rows)if i>reserve and row['stage']=='ai_declaration_verified')
    assert not _active_ai_source(rows[:final]+rows[final+1:])
