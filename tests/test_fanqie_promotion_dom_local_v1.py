"""Actual JS/selector black-box on local HTML in installed Chrome, no platform."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.operations_accounts import fanqie_managed_promotion_v1 as module
from src.platform_adapter.fanqie_backfill import normalize_promotion_rows


BOOK_ID='7302660145530539062'
INTENT=dict(book_id=BOOK_ID,book_name='本地测试书',alias='本地别名',promotion_path='别名推广',publish_type='AIGC')


@pytest.fixture(scope='module')
def browser(tmp_path_factory):
    profile=tmp_path_factory.mktemp('local_dom_chrome_profile')
    assert profile.resolve().is_relative_to(Path('D:/IT/ai_douyin').resolve())
    with sync_playwright() as p:
        # Installed browser only. Never install/download or borrow account data.
        context=p.chromium.launch_persistent_context(str(profile),channel='chrome',headless=True,args=['--mute-audio'])
        context.route('**/*',lambda route:route.abort())
        try:yield context
        finally:context.close()


@pytest.fixture
def page(browser):
    page=browser.new_page()
    try:yield page
    finally:page.close()


def form_html(*,book_id=BOOK_ID,with_path=False,duplicate_option=False,duplicate_modal=False):
    path='<div class="arco-form-item"><label class="arco-form-item-label">推广路径</label><div class="arco-select" data-values="别名推广|其他路径">请选择路径</div></div>' if with_path else ''
    modal=f'''<div class="arco-modal-content"><h2>本地测试书（{book_id}）</h2>
        <input class="alias-input-EBp1Sw"><div class="arco-form-item"><label class="arco-form-item-label">发文类型</label>
        <div class="arco-select" data-values="AIGC|图文">请选择类型</div></div>{path}<button id="submit">提交申请</button></div>'''
    return '''<style>.arco-modal-content{padding:12px}.arco-select,.arco-select-option{display:block;min-width:80px;min-height:20px}</style>
      <div class="book-hQ7GYr"><div class="book-title-txt-_CIhYa">本地测试书</div><div class="c-promotions"><button id="open">别名推广</button></div></div>
      <div id="host"></div><script>
      window.submitCount=0;window.openCount=0;window.inputCount=0;
      const modalHtml='''+json.dumps(modal,ensure_ascii=False)+''';
      document.querySelector('#open').onclick=()=>{window.openCount++;document.querySelector('#host').innerHTML=modalHtml'''+(' + modalHtml' if duplicate_modal else '')+''';
        document.querySelectorAll('input').forEach(e=>e.addEventListener('input',()=>window.inputCount++));
        document.querySelectorAll('.arco-select').forEach(el=>el.onclick=()=>{
          document.querySelectorAll('.popup').forEach(e=>e.remove());const popup=document.createElement('div');popup.className='popup';
          let values=el.dataset.values.split('|');'''+('values.push("AIGC");' if duplicate_option else '')+'''
          values.forEach(value=>{const o=document.createElement('div');o.className='arco-select-option';o.textContent=value;
            o.onclick=(event)=>{event.stopPropagation();el.textContent=value;popup.remove()};popup.appendChild(o)});document.body.appendChild(popup);
        });
        document.querySelectorAll('#submit').forEach(b=>b.onclick=()=>{window.submitCount++;const e=document.createElement('div');e.className='title-azi_qL';e.textContent='申请成功';document.body.appendChild(e)});
      };
      </script>'''


@pytest.mark.parametrize('with_path',[False,True])
def test_actual_js_exact_book_prepares_aigc_and_submits_once(page,with_path):
    page.set_content(form_html(with_path=with_path))
    entry=page.evaluate(module._open_book_js(INTENT))
    assert entry=={'clicked':True,'book_name':INTENT['book_name'],'entry_label':'别名推广'}
    prepared=page.evaluate(module._form_js(INTENT,entry_evidence=entry))
    assert {k:prepared[k]for k in ('ready','submitted')}=={'ready':True,'submitted':False}
    assert page.evaluate('window.submitCount')==0
    assert page.locator('input').input_value()==INTENT['alias']
    result=page.evaluate(module._form_js(INTENT,submit=True,entry_evidence=entry))
    assert {k:result[k] for k in ('ready','submitted','result')}=={'ready':True,'submitted':True,'result':'success_message_observed'}
    assert page.evaluate('window.submitCount')==1 and page.evaluate('window.openCount')==1


@pytest.mark.parametrize('kwargs,reason',[
    ({'book_id':'9999999999999999999'},'modal_exact_book_unconfirmed'),
    ({'duplicate_modal':True},'unique_modal_required'),
    ({'duplicate_option':True},'exact_option_missing_or_ambiguous'),
])
def test_actual_form_refuses_wrong_book_modal_or_ambiguous_option(page,kwargs,reason):
    page.set_content(form_html(**kwargs));entry=page.evaluate(module._open_book_js(INTENT))
    result=page.evaluate(module._form_js(INTENT,entry_evidence=entry))
    assert {k:result[k]for k in ('ready','reason')}=={'ready':False,'reason':reason}
    assert page.evaluate('window.submitCount')==0


def test_actual_entry_refuses_duplicate_exact_title_and_wrong_path(page):
    page.set_content(form_html())
    page.evaluate("document.body.appendChild(document.querySelector('.book-hQ7GYr').cloneNode(true))")
    assert page.evaluate(module._open_book_js(INTENT))['clicked'] is False
    assert page.evaluate('window.openCount')==0
    page.set_content(form_html());entry=page.evaluate(module._open_book_js(INTENT))
    assert page.evaluate(module._form_js({**INTENT,'promotion_path':'其他路径'},entry_evidence=entry))['ready'] is False
    assert page.evaluate('window.submitCount')==0


def table_html(*,conflict=False):
    task='conflicting-task' if conflict else 'native-task'
    return f'''<table><thead><tr><th>关键词</th><th>书本信息</th><th>发文类型</th><th>别名状态</th><th>书籍状态</th><th>发文详情</th><th>推广任务ID</th><th>别名ID</th><th>推广路径</th></tr></thead>
    <tbody><tr data-task-id="native-task" data-alias-id="native-alias" data-promotion-path="别名推广">
    <td>本地别名</td><td><span class="book-name-iHil3A">本地测试书</span> ID：{BOOK_ID}</td><td>AIGC</td><td>生效中</td><td>可用</td><td>待填写</td><td>native-task</td><td>native-alias</td><td>别名推广</td>
    <td><a href="https://kol.fanqieopen.com/page/detail?task_id={task}&amp;alias_id=native-alias&amp;promotion_path=别名推广">详情</a></td>
    <td><a href="https://www.douyin.com/video/123456789012345">作品</a></td></tr></tbody></table>
    <button class="arco-pagination-item-next" aria-label="下一页" onclick="window.nextCount++;this.disabled=true">下一页</button>
    <script>window.nextCount=0</script>'''


@pytest.mark.parametrize('conflict',[False,True])
def test_actual_table_extracts_native_ids_and_conflict(page,conflict):
    page.set_content(table_html(conflict=conflict))
    raw=page.evaluate(module.LIST_JS)
    assert raw['table_ready'] is True and raw['has_next'] is True
    assert raw['items'][0]['book_id']==BOOK_ID
    assert raw['items'][0]['published_links']==['https://www.douyin.com/video/123456789012345']
    rows=normalize_promotion_rows(raw,now=1000)['items']
    if conflict:
        assert 'platform_task_id' in rows[0]['conflicting_identity_fields']
        assert 'platform_task_id' not in rows[0]
    else:assert rows[0]['platform_task_id']=='native-task' and rows[0]['stable_identity_status']=='verified'
    assert page.evaluate(module.NEXT_JS)=={'clicked':True}
    assert page.evaluate(module.LIST_JS)['has_next'] is False
    assert page.evaluate(module.NEXT_JS)=={'clicked':False}
    assert page.evaluate('window.nextCount')==1


def test_actual_pagination_ambiguous_never_clicks(page):
    page.set_content(table_html())
    page.evaluate("document.body.appendChild(document.querySelector('.arco-pagination-item-next').cloneNode(true))")
    assert page.evaluate(module.LIST_JS)['pagination_ambiguous'] is True
    assert page.evaluate(module.NEXT_JS)=={'clicked':False}
    assert page.evaluate('window.nextCount')==0
