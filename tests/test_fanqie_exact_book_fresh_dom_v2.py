"""Actual Chrome + sanitized user card DOM; every request intercepted locally."""
import json
import os
from pathlib import Path

import pytest

from src.platform_adapter import fanqie_promotion_preflight_v1 as pre

BOOK='7302660145530539062'
NAME='你敢惹我？我有六个反派儿子'
FIXTURE=Path(__file__).with_name('fixtures')/'fanqie_user_book_cards_20261116_v2.html'
pytestmark=pytest.mark.skipif(os.environ.get('RUN_LOCAL_PREFLIGHT_DOM_TEST')!='1',reason='Isolated Chrome DOM opt-in')


@pytest.fixture(scope='module')
def local_chrome(tmp_path_factory):
    from playwright.sync_api import sync_playwright
    folder=tmp_path_factory.mktemp('fresh_fanqie_local_profile')
    holder={'html':''};requests=[]
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(folder/'profile'),channel='chrome',headless=True,
            args=['--mute-audio','--disable-background-networking','--disable-component-update','--no-first-run',
                  '--host-resolver-rules=MAP * ~NOTFOUND'])
        def route(r):
            requests.append(r.request.url)
            if r.request.url==pre.CONTENT_URL:
                r.fulfill(status=200,content_type='text/html; charset=utf-8',body=holder['html'])
            else:r.abort()
        context.route('**/*',route)
        try:yield context,holder,requests
        finally:context.close()


def page_html(mode):
    native=FIXTURE.read_text(encoding='utf8')
    actual=BOOK if mode!='wrong_id' else '8302660145530539062'
    line=NAME+'（'+actual+'）'
    if mode=='wrong_title':line='其他标题'+line
    shell='''<div class="arco-modal" id="test-modal" style="display:none">
    <button class="arco-modal-close-icon" onclick="window.modalClosed++;document.querySelector('#test-modal').style.display='none';document.querySelector('#test-options').style.display='none'">关闭</button>
    <div class="arco-modal-content"><div id="test-book-line"></div><input class="alias-input-EBp1Sw" oninput="window.aliasWrites++">
    <div class="arco-form-item"><label class="arco-form-item-label">发文类型</label><div class="arco-select" onclick="document.querySelector('#test-options').style.display='block'">请选择</div></div>
    <button onclick="window.submits++">提交</button></div></div><div id="test-options" style="display:none"><div role="option">AIGC</div></div>'''
    script=r'''<script>
    const mode=MODE,wanted=NAME;
    window.queryCount=window.aliasWrites=window.submits=window.modalClosed=0;window.opened=[];
    document.querySelector('#test-book-line').textContent=LINE;
    let root=document.querySelector('.books-YEBPOv');
    const originals=Array.from(root.querySelectorAll('.book-hQ7GYr')).map(e=>e.outerHTML);
    const attach=()=>document.querySelectorAll('.book-hQ7GYr button').forEach(b=>{
      if((b.innerText||'').trim()!=='别名推广')return;
      b.addEventListener('click',()=>{window.opened.push(b.closest('.book-hQ7GYr').querySelector('.book-title-txt-_CIhYa').textContent.trim());document.querySelector('#test-modal').style.display='block';});
    });attach();
    if(mode.startsWith('zero_')){
      root.remove();
      const tabs=document.createElement('div');tabs.className='task-menu-second';
      tabs.innerHTML='<span class="task-menu-second-item">全部内容</span>';
      document.querySelector('.kol-page').prepend(tabs);
      tabs.querySelector('span').addEventListener('click',()=>{
        if(mode==='zero_generic_late')setTimeout(()=>{
          root=document.createElement('div');root.className='books-YEBPOv';root.innerHTML=originals.join('');
          document.querySelector('.kol-page').append(root);attach();
        },1500);
      });
    }
    if(mode==='multiple_roots_initial')root.after(root.cloneNode(false));
    document.querySelector('input[placeholder="请输入作者名/书名/BookID"]').addEventListener('keydown',e=>{
      if(e.key!=='Enter')return;
      window.queryCount++;window.lastQuery=e.target.value;
      if(mode==='stale'){setTimeout(()=>document.body.dataset.unrelated='changed',100);return;}
      if(mode==='zero_generic_late')return;
      setTimeout(()=>{
        let cards=originals.slice(1,4).concat(originals[0],originals.slice(4));
        if(mode==='fuzzy'||mode==='body_title')cards=originals.slice(1);
        if(mode==='ambiguous')cards.push(originals[0]);
        if(mode.startsWith('zero_')){
          root=document.createElement('div');root.className='books-YEBPOv';root.id='search-area-scroll-box';
          const scope=document.querySelector('.kol-page');
          if(mode!=='zero_missing_header'){
            const header=document.createElement('div');header.className='kol-page-header-title';header.textContent='搜索结果';scope.prepend(header);
          }
          scope.append(root);
          if(mode==='zero_scope_replaced_input'){
            const input=e.target.cloneNode(true);input.value=wanted;e.target.replaceWith(input);
          }
        }
        root.innerHTML=cards.join('');attach();
        if(mode==='hidden')document.querySelectorAll('.book-hQ7GYr').forEach(c=>{if(c.querySelector('.book-title-txt-_CIhYa').textContent.trim()===wanted)c.style.display='none';});
        if(mode==='query_changed')e.target.value='其他书名';
        if(mode==='body_title'){const n=document.createElement('p');n.textContent=wanted;document.body.append(n);}
      },750);
    });
    </script>'''.replace('MODE',json.dumps(mode)).replace('NAME',json.dumps(NAME)).replace('LINE',json.dumps(line))
    return native+shell+script


@pytest.mark.parametrize('mode,expected',[
    ('fresh','form_options_verified'),('stale','search_results_not_fresh'),
    ('fuzzy','book_not_in_current_view'),('ambiguous','book_ambiguous_in_current_view'),
    ('wrong_id','modal_book_identity_mismatch'),('wrong_title','modal_book_identity_mismatch'),
    ('query_changed','search_results_not_fresh'),('body_title','book_not_in_current_view'),
    ('hidden','book_not_in_current_view'),
])
def test_actual_user_cards_require_fresh_exact_title_and_modal_id(local_chrome,mode,expected):
    context,holder,requests=local_chrome;holder['html']=page_html(mode)
    page=context.new_page();events=[];before=len(requests)
    try:
        page.goto(pre.CONTENT_URL)
        result=pre.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=lambda:None,
            checkpoint=lambda stage,value:events.append((stage,value)),locate=True)
        assert result['status']==expected,(mode,result)
        state=page.evaluate('({queryCount,lastQuery,aliasWrites,submits,opened,closed:window.modalClosed})')
        assert state['queryCount']==1 and state['lastQuery']==NAME
        assert state['aliasWrites']==state['submits']==0 and result['chapters_read']==0
        assert result['platform_book_availability'] is None
        assert not result['book_location']['all_content_clicked']
        if mode=='fresh':
            assert state['opened']==[NAME] and state['closed']==1
            assert result['book_location']['result_freshness_verified']
            assert result['form']['observed_book_ids']==[BOOK]
            observations=[v for k,v in events if k.startswith('search_observation_')]
            assert any(not v.get('fresh') for v in observations)
            assert result['view_ready']['book_titles'][0]!=NAME
        elif mode in ('wrong_id','wrong_title'):
            assert state['opened']==[NAME] and state['closed']==1 and not result['preflight_passed']
        else:assert state['opened']==[]
        assert requests[before:]==[pre.CONTENT_URL]  # All requests fulfilled in memory; no API replay.
    finally:page.close()


@pytest.mark.parametrize('mode,expected',[
    ('zero_scope','form_options_verified'),
    ('zero_scope_replaced_input','form_options_verified'),
    ('zero_generic_late','search_results_not_fresh'),
    ('zero_missing_header','search_results_not_fresh'),
    ('multiple_roots_initial','exact_result_scope_unavailable'),
])
def test_initial_missing_root_waits_only_for_observed_search_scope(local_chrome,mode,expected):
    context,holder,requests=local_chrome;holder['html']=page_html(mode)
    page=context.new_page();events=[];before=len(requests)
    try:
        page.goto(pre.CONTENT_URL)
        result=pre.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=lambda:None,
            checkpoint=lambda stage,value:events.append((stage,value)),locate=True)
        assert result['status']==expected,(mode,result)
        state=page.evaluate('({queryCount,lastQuery:window.lastQuery,aliasWrites,submits,opened,closed:window.modalClosed})')
        assert state['aliasWrites']==state['submits']==0 and result['chapters_read']==0
        armed=next(v for k,v in events if k=='search_observer_armed')
        assert armed['page_location']=={'origin':'https://kol.fanqieopen.com','path':'/page/content'}
        if mode=='multiple_roots_initial':
            assert armed['armed'] is False and armed['result_root_count']==2
            assert state['queryCount']==0 and not state['opened']
        else:
            assert armed['armed'] and armed['result_root_count']==armed['visible_result_root_count']==0
            assert armed['initial_scope']=='await_observed_search_result_scope'
            assert state['queryCount']==1 and state['lastQuery']==NAME
            assert result['book_location']['all_content_clicked']
            if mode in ('zero_scope','zero_scope_replaced_input'):
                assert state['opened']==[NAME] and state['closed']==1
                observed=result['book_location']['search_freshness']
                assert observed['search_scope_verified'] and observed['search_result_id_count']==1
                assert observed['search_header_count']==1 and result['book_location']['result_freshness_verified']
                assert observed['input_replaced']==(mode=='zero_scope_replaced_input')
                assert result['form']['observed_book_ids']==[BOOK]
            else:
                assert not state['opened'] and not result['book_location']['result_freshness_verified']
        assert requests[before:]==[pre.CONTENT_URL]
    finally:page.close()


def test_guard_fence_after_enter_blocks_before_opening_any_card(local_chrome):
    context,holder,_=local_chrome;holder['html']=page_html('fresh');page=context.new_page()
    try:
        page.goto(pre.CONTENT_URL)
        def guarded():
            if page.evaluate('window.queryCount'):
                raise ValueError('original UID/owner guard fenced')
        with pytest.raises(ValueError,match='guard fenced'):
            pre.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=guarded,checkpoint=lambda *a:None,locate=True)
        assert page.evaluate('window.opened.length+window.aliasWrites+window.submits')==0
    finally:page.close()
