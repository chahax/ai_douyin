"""Exact observed UI lookup, no account/profile/network; local DOM is opt-in."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.platform_adapter import fanqie_exact_book_locator_v1 as m
from src.platform_adapter import fanqie_promotion_preflight_v1 as pre

BOOK='7302660145530539062'
NAME='你敢惹我？我有六个反派儿子'


class Locator:
    def __init__(self,page,selector):self.page,self.selector=page,selector
    def count(self):return 1
    def inner_text(self):assert self.selector==m.TAB_SELECTOR;return '全部内容'
    def click(self,**kwargs):assert self.selector==m.TAB_SELECTOR;self.page.actions.append(('tab',kwargs))
    def fill(self,value):assert self.selector==m.INPUT_SELECTOR;self.page.actions.append(('fill',value));self.page.value=value
    def press(self,key):assert self.selector==m.INPUT_SELECTOR;self.page.actions.append(('press',key));self.page.entered=True


class Page:
    url=pre.CONTENT_URL
    def __init__(self,*,titles=None,controls=None,delay=0,found=True,fresh=True):
        self.titles=titles or [];self.controls=controls or dict(tab_count=1,tab_usable=True,
            input_count=1,input_type='text',input_usable=True)
        self.delay=delay;self.found=found;self.fresh=fresh;self.actions=[];self.entered=False;self.value=None;self.reads=0
    def locator(self,selector):return Locator(self,selector)
    def wait_for_timeout(self,ms):assert 0<ms<=250
    def evaluate(self,js):
        if 'fanqie_exact_search_arm/v2' in js:return dict(armed=True)
        if 'fanqie_exact_search_observation/v2' in js:
            self.reads+=1
            ready=self.reads>self.delay
            return dict(valid=True,entered=self.entered,query_matches=self.value==NAME,
                result_root_count=1,fresh=self.fresh and ready,render_revision=1,
                view=dict(book_titles=[NAME] if ready and self.found else self.titles,visible_modal_count=0))
        if 'disposed:true' in js:return dict(disposed=True)
        if js==pre.VIEW_JS:
            return dict(book_titles=self.titles,visible_modal_count=0,search_controls=[],filter_buttons=['全部内容'])
        if js==m.CONTROL_STATE_JS:return self.controls
        assert 'value_matches' in js
        return dict(unique=True,value_matches=self.value==NAME)


def locate(page,**kwargs):
    steps=[]
    result=m.locate_exact_book(page,book_id=BOOK,book_name=NAME,guard=lambda:None,
        checkpoint=lambda stage,value:steps.append((stage,value)),search_allowed=kwargs.pop('search_allowed',True),**kwargs)
    return result,steps


def test_normal_query_uses_real_fill_then_enter_once_and_waits_for_async_render():
    page=Page(delay=3)
    # Managed wrapper has no locator: selection must go through its same raw Page.
    wrapped=NS(page=page,url=page.url,evaluate=page.evaluate,wait_for_timeout=page.wait_for_timeout)
    result,steps=locate(wrapped)
    assert result['status']=='located_after_exact_search' and result['search_count']==1
    assert page.actions==[('tab',dict(timeout=5000)),('fill',NAME),('press','Enter')]
    assert page.reads==5 and [s for s,v in steps].count('view_ready')==1
    assert result['result_freshness_verified'] and result['book_id_verification']=='requires_exact_modal_identity'
    assert not result['alias_filled'] and not result['promotion_submitted'] and result['api_requests_issued']==0


def test_wrong_or_multiple_controls_never_fill_or_press_and_empty_result_is_not_unavailable():
    for changed in [dict(input_count=0),dict(input_count=2),dict(input_type='password'),
                    dict(input_usable=False),dict(tab_count=2),dict(tab_usable=False)]:
        page=Page();page.controls.update(changed)
        result,_=locate(page)
        assert result['status']=='exact_search_controls_unavailable' and page.actions==[]
    page=Page(found=False);result,_=locate(page)
    assert result['status']=='book_not_in_current_view' and result['platform_book_availability'] is None
    assert page.reads==20 and result['search_count']==1


def test_default_and_existing_exact_card_do_not_search_and_guard_blocks_DOM():
    page=Page();result,_=locate(page,search_allowed=False)
    assert result['status']=='book_not_in_current_view' and not page.actions
    page=Page(titles=[NAME]);result,_=locate(page,search_allowed=False)
    assert result['status']=='located_current_view' and not page.actions
    page=Page(titles=[NAME,NAME]);result,_=locate(page,search_allowed=False)
    assert result['status']=='book_ambiguous_in_current_view' and not page.actions
    page=Page()
    def fenced():raise ValueError('owner fenced')
    with pytest.raises(ValueError,match='owner fenced'):
        m.locate_exact_book(page,book_id=BOOK,book_name=NAME,guard=fenced,checkpoint=lambda *a:None,search_allowed=True)
    assert not page.actions


def test_old_exact_result_without_new_generation_is_never_reused():
    page=Page(titles=[NAME],fresh=False)
    result,_=locate(page)
    assert result['status']=='search_results_not_fresh' and result['search_count']==1
    assert page.actions[-2:]==[('fill',NAME),('press','Enter')]
    assert not result['result_freshness_verified']


def test_observed_input_and_result_scope_do_not_require_missing_outer_tab():
    page=Page();page.controls['tab_count']=0
    result,_=locate(page)
    assert result['status']=='located_after_exact_search' and not result['all_content_clicked']
    assert page.actions==[('fill',NAME),('press','Enter')]


def test_preflight_explicit_lookup_passes_location_then_keeps_existing_modal_ID_gate(monkeypatch):
    from test_fanqie_promotion_preflight_v1 import Page as FormPage
    calls=[]
    def lookup(page,**kwargs):
        calls.append(kwargs);kwargs['guard']()
        return dict(status='located_after_exact_search',enter_pressed=True,view_ready=page.view)
    monkeypatch.setattr(m,'locate_exact_book',lookup)
    page=FormPage(wrong=True)
    result=pre.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=lambda:None,checkpoint=lambda *a:None,locate=True)
    assert calls[0]['search_allowed'] is True and result['search_executed']
    assert result['status']=='modal_book_identity_mismatch' and page.closed==1
    assert not result['alias_filled'] and not result['promotion_submitted']


def test_queue_and_CLI_locate_is_preflight_only_default_payload_unchanged(tmp_path,monkeypatch,capsys):
    from test_fanqie_managed_promotion_v1 import accounts
    a,env=accounts.__wrapped__(tmp_path)
    for kind in ['fanqie_promotion_apply','fanqie_promotion_list','fanqie_backfill_reconcile','fanqie_login']:
        with pytest.raises(ValueError):a.queue(env['resource_id'],kind,locate=True)
    with pytest.raises(ValueError):a.queue(env['resource_id'],'fanqie_promotion_preflight',book_id=BOOK,book_name=NAME,locate=1)
    cmd=a.queue(env['resource_id'],'fanqie_promotion_preflight',book_id=BOOK,book_name=NAME,locate=True)
    assert cmd['payload']==dict(environment_key=env['environment_key'],book_id=BOOK,book_name=NAME,locate=True)
    from scripts import run_fanqie_account as cli
    calls=[]
    class Accounts:
        def queue(self,*args,**kwargs):calls.append((args,kwargs));return {}
    monkeypatch.setattr(cli,'FanqieAccounts',lambda **kw:Accounts())
    monkeypatch.setattr(cli,'launch_worker',lambda *a:{})
    monkeypatch.setattr(sys,'argv',['prog','promotion-preflight','--resource','r','--book-id',BOOK,'--book-name',NAME,'--locate'])
    cli.main();assert calls[-1][1]['locate'] is True
    monkeypatch.setattr(sys,'argv',['prog','promotion-apply','--resource','r','--locate'])
    with pytest.raises(SystemExit):cli.main()
    assert len(calls)==1


def test_apply_uses_same_locator_on_current_CONTENT_each_attempt_before_any_alias_or_submit(tmp_path,monkeypatch):
    from test_fanqie_managed_promotion_v1 import accounts,Session,request
    from src.operations_accounts.fanqie_account_control import run_owner
    a,env=accounts.__wrapped__(tmp_path);calls=[]
    def missing(page,**kwargs):
        kwargs['guard']();calls.append((page.url,kwargs))
        kwargs['checkpoint']('view_ready',dict(book_titles=[],visible_modal_count=0))
        return dict(status='book_not_in_current_view',enter_pressed=True,search_count=1)
    monkeypatch.setattr(m,'locate_exact_book',missing)
    cmd=a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=request(a,env))
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='failed' and len(calls)==1 and calls[0][0]==pre.CONTENT_URL
    assert calls[0][1]['search_allowed'] is True and not Session.submit_count
    folder=a.folder(cmd['command_id'])
    assert not (folder/'FORM_PREPARED.json').exists() and not(folder/'SUBMIT_CLAIM.json').exists()


@pytest.mark.skipif(os.environ.get('RUN_LOCAL_PREFLIGHT_DOM_TEST')!='1',reason='Fresh isolated local DOM opt-in')
def test_real_DOM_Enter_exact_controls_delay_empty_and_modal_wrong_ID():
    from playwright.sync_api import sync_playwright
    def html(*,kind='ok',nested=False):
        placeholder=m.PLACEHOLDER if kind!='wrongcontrol' else '搜索关键词'
        actual='8302660145530539062'if kind=='wrongid' else BOOK
        search=f'<input id="search" placeholder="{placeholder}" type="text">'
        tab='<span>全部内容</span>'if nested else '全部内容'
        return f'''<meta charset="utf-8"><script>window.queryCount=window.tabCount=window.aliasWrites=window.submits=0;</script>
        <div class="task-menu-second"><span class="task-menu-second-item" onclick="window.tabCount++">{tab}</span></div>
        {search}{search if kind=='multiple' else ''}<div id="books" class="books-YEBPOv"></div>
        <div class="arco-modal" id="modal" style="display:none"><button class="arco-modal-close-icon" onclick="document.querySelector('#modal').style.display='none';document.querySelector('#options').style.display='none'">关闭</button>
        <div class="arco-modal-content"><div>{NAME}（{actual}）</div><input class="alias-input-EBp1Sw" oninput="window.aliasWrites++">
        <div class="arco-form-item"><label class="arco-form-item-label">发文类型</label><div class="arco-select" onclick="document.querySelector('#options').style.display='block'">请选择</div></div>
        <button onclick="window.submits++">提交</button></div></div><div id="options" style="display:none"><div role="option">AIGC</div></div>
        <script>document.querySelectorAll('#search').forEach(e=>e.addEventListener('keydown',event=>{{
        if(event.key!=='Enter')return;window.queryCount++;window.query=event.target.value;
        if(event.target.value!=={json.dumps(NAME)})return;
        if({json.dumps(kind)}==='empty'){{setTimeout(()=>{{const old=document.querySelector('#books');old.replaceWith(old.cloneNode(false));}},5);return;}}
        setTimeout(()=>{{document.querySelector('#books').innerHTML=`<div class="book-hQ7GYr"><span class="book-title-txt-_CIhYa">{NAME}</span><button onclick="document.querySelector('#modal').style.display='block'">别名推广</button></div>`;}},{800 if kind=='delay' else 5});
        }}));</script>'''
    with sync_playwright()as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking',
            '--disable-component-update','--no-first-run','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:
            for kind,nested,status in [('ok',False,'form_options_verified'),('delay',True,'form_options_verified'),
                    ('empty',False,'book_not_in_current_view'),('wrongcontrol',False,'exact_search_controls_unavailable'),
                    ('multiple',False,'exact_search_controls_unavailable'),('wrongid',False,'modal_book_identity_mismatch')]:
                context=browser.new_context();page=context.new_page()
                context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html(kind=kind,nested=nested)))
                page.goto(pre.CONTENT_URL)
                result=pre.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=lambda:None,checkpoint=lambda *a:None,locate=True)
                assert result['status']==status,(kind,result)
                state=page.evaluate('({queries:queryCount,tabs:tabCount,alias:aliasWrites,submits:window.submits,query:window.query||null})')
                assert state['alias']==state['submits']==0 and result['chapters_read']==0
                assert state['queries']==state['tabs']==(0 if kind in ['wrongcontrol','multiple']else 1)
                if state['queries']:assert state['query']==NAME
                if kind=='wrongid':
                    from src.operations_accounts.fanqie_managed_promotion_v1 import _form_js
                    page.evaluate("document.querySelector('#modal').style.display='block'")
                    gate=page.evaluate(_form_js(dict(book_id=BOOK,book_name=NAME,alias='unused',
                        promotion_path='别名推广',publish_type='AIGC')))
                    assert gate['ready'] is False and gate['reason']=='modal_exact_book_unconfirmed'
                    assert page.evaluate('window.aliasWrites+window.submits')==0
                context.close()
        finally:browser.close()
