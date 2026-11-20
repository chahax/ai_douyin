"""Real isolated Chrome, HTML reconstructed from the actual sanitized card.

The locator receives an RPC-shaped facade without handles/context. All browser
requests are locally fulfilled; no user profile, real platform or API is used.
"""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.shared.original_work_locator_v1 import discover_original_work

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'tests/fixtures/original_work_locator_v1/observed_card.html').read_text(encoding='utf8')
TITLE = '弟弟说出面包的来历，哥哥攥紧了拳头'
MANAGE = 'https://creator.douyin.com/creator-micro/content/manage?enter_from=publish'
URL = 'https://www.douyin.com/video/1234567890123456789'


class LocatorRPC:
    def __init__(self, page, selector):
        self.page, self.locator = page, page.raw.locator(selector)
    def count(self): return self.locator.count()
    def evaluate(self, js):
        if self.page.before_check:
            action, self.page.before_check = self.page.before_check, None; action()
        return self.locator.evaluate(js)
    def click(self, *, timeout):
        if self.page.before_click:
            action, self.page.before_click = self.page.before_click, None; action()
        self.locator.click(timeout=timeout)


class PageRPC:
    def __init__(self, raw, tab_id):
        self.raw, self.tab_id = raw, tab_id
        self.before_check = self.before_click = None
    def evaluate(self, js): return self.raw.evaluate(js)
    def locator(self, selector): return LocatorRPC(self, selector)
    def wait_for_timeout(self, ms): self.raw.wait_for_timeout(ms)
    def goto(self, url, *, wait_until, timeout): self.raw.goto(url,wait_until=wait_until,timeout=timeout)


class Popups:
    def __init__(self, context, main):
        self.context, self.main, self.rows, self.closed = context, main, {main.raw:main}, []
    def snapshot(self):
        for raw in self.context.pages:
            if raw not in self.rows:self.rows[raw]=PageRPC(raw,'popup-'+str(len(self.rows)))
        return [dict(tab_id=p.tab_id,url=raw.url,closed=raw.is_closed()) for raw,p in self.rows.items()]
    def page(self, tab_id):
        assert tab_id!=self.main.tab_id
        return next(p for p in self.rows.values() if p.tab_id==tab_id)
    def close(self, tab_id):
        assert tab_id!=self.main.tab_id
        self.page(tab_id).raw.close(); self.closed.append(tab_id)


@pytest.fixture(scope='module')
def browser(tmp_path_factory):
    with sync_playwright() as pw:
        browser=pw.chromium.launch_persistent_context(str(tmp_path_factory.mktemp('local_chrome')),
            channel='chrome',headless=True,args=['--mute-audio'],viewport={'width':1400,'height':900})
        yield browser
        browser.close()


@pytest.fixture
def case(browser):
    state={'html':'<html><title>Local detail</title></html>','requests':[],'guard_calls':0}
    def route(route):
        state['requests'].append(route.request.url)
        assert route.request.method=='GET'
        route.fulfill(status=200,content_type='text/html; charset=utf-8',body=state['html'])
    browser.route('**/*',route)
    raw=browser.new_page(); raw.goto(MANAGE); raw.set_content(HTML)
    page=PageRPC(raw,'original-task-tab'); popups=Popups(browser,page)
    raw.evaluate('()=>{window.coverClicks=0;window.operationClicks=0;document.querySelector(".ops").addEventListener("click",()=>window.operationClicks++);}')
    def bind_popup(mode='canonical'):
        value = 'window.open('+json.dumps(URL)+')'
        if mode=='zero':value=''
        if mode=='two':value+=';window.open('+json.dumps(URL.replace('6789','6790'))+')'
        if mode=='wrong':value='window.open("https://wrong.example/video/1234567890123456789")'
        if mode=='modal':value='window.open("https://www.douyin.com/user/self?modal_id=1234567890123456789")'
        raw.evaluate('()=>document.querySelector(".video-card-cover-QkeRHf").addEventListener("click",()=>{window.coverClicks++;'+value+'})')
    def guard():state['guard_calls']+=1
    scope=dict(account_uuid='test-account',owner_id='original-owner',generation=31,command_id='original-read',tab_id=page.tab_id)
    def run(title=TITLE, access=True):
        return discover_original_work(page,title,guard=guard,scope=scope,popup_access=popups if access else None)
    yield locals()
    for p in list(browser.pages):p.close()
    browser.unroute('**/*',route)


def test_actual_restriction_card_caption_has_no_published_leaf_but_discovers_native_ID(case):
    x=case; x['bind_popup'](); result=x['run']()
    assert result['verified'] and result['post_id']=='1234567890123456789'
    assert result['restriction_warning']['text']=='流量减少'
    assert result['diagnostic']['review_status_evaluated'] is False
    assert 'review_status' not in result and x['raw'].evaluate('window.coverClicks')==1
    assert x['raw'].evaluate('window.operationClicks')==0 and len(x['popups'].closed)==1


def test_full_two_minute_title_and_normal_status_keep_same_locator(case):
    x=case; title='一袋面包，看清这个家｜两分钟完整版'
    x['raw'].locator('.info-title-text-Zob9RV').evaluate('(n)=>n.innerText='+json.dumps(title+' 剧情虚构，非真实事件。完整版说明'))
    x['raw'].locator('.info-status-QukAhD').evaluate('n=>n.innerText="已发布"')
    x['bind_popup'](); result=x['run'](title)
    assert result['verified'] and result['restriction_warning'] is None


@pytest.mark.parametrize('bad',['duplicate_title','substring','foreign_card','cover_action'])
def test_unsafe_or_ambiguous_card_never_clicks(case,bad):
    x=case; x['bind_popup']()
    script={
        'duplicate_title':'()=>document.body.append(document.querySelector(".video-card-sfaSzz").cloneNode(true))',
        'substring':'()=>document.querySelector(".info-title-text-Zob9RV").innerText="前缀"+document.querySelector(".info-title-text-Zob9RV").innerText',
        'foreign_card':'()=>document.querySelector(".video-card-content-Xt386b").insertAdjacentHTML("beforeend","<article>另一作品</article>")',
        'cover_action':'()=>document.querySelector(".video-card-cover-QkeRHf").insertAdjacentHTML("beforeend","<button>删除作品</button>")',
    }[bad]
    x['raw'].evaluate(script); result=x['run']()
    assert not result['verified'] and x['raw'].evaluate('window.coverClicks')==0


@pytest.mark.parametrize('moment',['before_check','before_click'])
def test_react_replacement_cannot_borrow_bound_nonce_or_click(case,moment):
    x=case; x['bind_popup']()
    setattr(x['page'],moment,lambda:x['raw'].evaluate('()=>{const n=document.querySelector(".video-card-content-Xt386b");const clone=n.cloneNode(true);clone.querySelector(".video-card-cover-QkeRHf").addEventListener("click",()=>window.coverClicks++);n.replaceWith(clone);}'))
    result=x['run']()
    assert not result['verified'] and result['reason']=='bound_card_or_document_changed'
    assert x['raw'].evaluate('window.coverClicks')==0


@pytest.mark.parametrize('bad',['button','disabled','text'])
def test_same_cover_cannot_turn_into_write_action_between_check_and_click(case,bad):
    x=case; x['bind_popup']()
    script={
        'button':'()=>{const c=document.querySelector(".video-card-cover-QkeRHf");c.insertAdjacentHTML("beforeend",\'<button style="position:absolute;inset:0" onmousedown="window.operationClicks++" onclick="window.operationClicks++">删除作品</button>\');}',
        'disabled':'()=>document.querySelector(".video-card-cover-QkeRHf").setAttribute("aria-disabled","true")',
        'text':'()=>document.querySelector(".video-card-cover-QkeRHf").insertAdjacentHTML("beforeend","<span>删除作品</span>")',
    }[bad]
    x['page'].before_click=lambda:x['raw'].evaluate(script)
    result=x['run']()
    assert not result['verified'] and result['reason']=='bound_card_or_document_changed'
    assert x['raw'].evaluate('window.operationClicks')==0
    assert x['raw'].evaluate('window.coverClicks')==0


def test_renderer_receives_only_opaque_scope_digest_and_cannot_rebind_it(case):
    x=case; x['bind_popup']()
    def mutate():
        state=x['raw'].evaluate('()=>{const r=window.__originalWorkLocatorV1;return {nonce:r.nonce,scope_digest:r.scope_digest,keys:Object.keys(r)}}')
        assert len(state['scope_digest'])==64 and 'scope' not in state['keys']
        assert all(value not in json.dumps(state) for value in ('test-account','original-owner','original-read','original-task-tab'))
        x['raw'].evaluate('()=>window.__originalWorkLocatorV1.scope_digest="bad"')
    x['page'].before_check=mutate
    result=x['run']()
    assert not result['verified'] and result['reason']=='bound_card_or_document_changed'
    assert x['raw'].evaluate('window.coverClicks')==0


@pytest.mark.parametrize('mode,reason',[('zero','detail_popup_missing'),('two','detail_pages_ambiguous'),('wrong','detail_origin_unexpected')])
def test_popup_absence_ambiguity_and_wrong_origin_do_not_invent_ID(case,mode,reason):
    x=case; x['bind_popup'](mode); result=x['run']()
    assert not result['verified'] and result['post_id']=='' and result['reason']==reason


def test_popup_challenge_is_retained_without_pretending_verified(case):
    x=case; x['state']['html']='<html><span>请完成安全验证</span></html>'; x['bind_popup']()
    result=x['run']()
    assert not result['verified'] and result['human_required']
    assert not x['popups'].closed


def test_native_modal_URL_requires_real_public_caption_and_player_scope(case):
    x=case; x['state']['html']='''<html><div data-e2e="video-detail"><article>
        <div data-e2e="player-container" class="video_1234567890123456789"><video style="width:100px;height:100px"></video></div>
        <div data-e2e="detail-video-info"><h1>'''+TITLE+''' 剧情虚构，非真实事件。</h1></div>
        <span>内容由AI生成</span></article></div></html>'''
    x['bind_popup']('modal'); result=x['run']()
    assert result['verified'] and result['reason']=='original_native_modal_id_and_caption'
    assert result['diagnostic']['native_modal_identity']['player_id_matches']


def test_native_modal_cannot_borrow_caption_from_wrong_work(case):
    x=case; x['state']['html']='<html><article><video></video><h1>别的作品</h1></article></html>'
    x['bind_popup']('modal'); result=x['run']()
    assert not result['verified'] and result['reason']=='canonical_identity_unverified'


def test_wrong_manage_origin_and_missing_popup_capability_are_readonly(case):
    x=case; x['bind_popup']()
    result=x['run'](access=False)
    assert result['reason']=='popup_observation_capability_missing' and not result['verified']
    x['raw'].goto('https://wrong.example/creator-micro/content/manage'); x['raw'].set_content(HTML)
    assert x['run']()['reason']=='manage_route_or_title_invalid'
