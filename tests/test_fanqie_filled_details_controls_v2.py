"""Local native DOM only. No real Fanqie account, queue, business DB or API."""
from types import SimpleNamespace as NS

import pytest

from src.platform_adapter import fanqie_filled_details_controls_v2 as flow

TARGET=dict(book_id='7302660145530539062',book_name='你敢惹我？我有六个反派儿子',alias='从旧饭桌开始改命')


@pytest.fixture(scope='module')
def context():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--disable-background-networking','--mute-audio'])
        context=browser.new_context();context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body='<html><body></body></html>'))
        yield context
        context.close();browser.close()


@pytest.fixture
def sample(context):
    native=context.new_page();native.goto('https://kol.fanqieopen.com/page/promotion-list')
    native.set_content('''<input id="unrelated" value="never-read"><table><thead><tr><th>关键词</th><th>书本信息</th><th>发文详情</th><th>操作</th></tr></thead>
      <tbody><tr><td id="alias">从旧饭桌开始改命</td><td><div class="book-name">你敢惹我？我有六个反派儿子</div><div>BookID：7302660145530539062</div></td>
      <td><span id="filled">已填写（1条）</span></td><td><div class="link" id="view" style="cursor:pointer">查看</div><button id="delete" type="button">删除</button></td></tr></tbody></table>
      <div hidden>https://www.douyin.com/video/1111111111111111111</div>
      <script>window.views=0;window.deletes=0;window.statusClicks=0;
      document.querySelector('#unrelated').value='protected';
      Object.defineProperty(HTMLInputElement.prototype,'value',{get(){throw Error('no input values')},set(){throw Error('no inputs')}});
      document.querySelector('#delete').onclick=()=>window.deletes++;
      document.querySelector('#filled').onclick=()=>window.statusClicks++;
      document.querySelector('#view').onclick=()=>{window.views++;let section=document.createElement('section');section.id='roleless';
        section.innerHTML='<h2>发文详情</h2><span>抖音作品</span><a href="https://www.douyin.com/video/7709043480894524722?tracking=never-save#secret">查看作品原链接</a>';document.body.append(section)};</script>''')
    owner=NS();events=[];checks=[];hook=[None]
    class Page:
        _session=owner;tab_id='caller-owned'
        def _cmd(self,action):assert action=='current_url';events.append(action);return dict(url=native.url)
        def evaluate(self,script):events.append('evaluate');return native.evaluate(script)
        def locator(self,selector):return native.locator(selector)
        def wait_for_timeout(self,ms):events.append('wait');return None
    page=Page()
    def guard():checks.append('guard')
    def checkpoint(stage,value):
        events.append(('checkpoint',stage,value))
        if hook[0] and stage=='view_click_intent':hook[0]()
    yield NS(native=native,page=page,guard=guard,checkpoint=checkpoint,events=events,checks=checks,hook=hook)
    native.close()


def run(x):return flow.inspect_filled_details_controls(x.page,**TARGET,guard=x.guard,checkpoint=x.checkpoint)


def test_roleless_view_opens_and_captures_public_links_without_values_or_delete(sample):
    x=sample
    x.native.evaluate("""()=>{const row=document.createElement('tr');row.hidden=true;row.innerHTML='<td>private</td>';document.querySelector('tbody').prepend(row);
      Object.defineProperty(row.querySelector('td'),'innerText',{get(){throw Error('hidden row read')}})}""")
    result=run(x)
    assert result['status']=='visible_change_observed' and result['view_clicks']==1
    assert x.native.evaluate('()=>[window.views,window.deletes,window.statusClicks]')==[1,0,0]
    assert result['body_after']['public_links']==[dict(origin='https://www.douyin.com',path='/video/7709043480894524722',source='visible_anchor',text='查看作品原链接')]
    assert not result['append_capability_verified'] and not result['uploaded'] and not result['submitted'] and not result['deleted']
    import json
    encoded=json.dumps(result,ensure_ascii=False)
    assert 'tracking=' not in encoded and 'secret' not in encoded and 'protected' not in encoded and '1111111111111111111' not in encoded
    row=result['row']['row'];assert row['status_cell']['text']=='已填写（1条）' and row['operation_cell']['text']=='查看 删除'
    assert any(e[0]=='checkpoint' and e[1]=='view_click_intent' for e in x.events if isinstance(e,tuple))


def test_plain_view_label_is_inventory_only_and_never_uses_filled_or_delete(sample):
    x=sample;x.native.locator('#view').evaluate("el=>{el.className='';el.style.cursor='auto'}")
    result=run(x)
    assert result['status']=='view_control_not_confirmed' and result['view_clicks']==0
    assert x.native.evaluate('()=>[window.views,window.deletes,window.statusClicks]')==[0,0,0]
    assert not any(e[0]=='checkpoint' and e[1]=='view_click_intent' for e in x.events if isinstance(e,tuple))


def test_exact_row_changed_after_checkpoint_stops_before_native_click(sample):
    x=sample;x.hook[0]=lambda:x.native.locator('#alias').evaluate("el=>el.textContent='另一本别名'")
    with pytest.raises(flow.DetailsControlsNotConfirmed):run(x)
    assert x.native.evaluate('()=>[window.views,window.deletes,window.statusClicks]')==[0,0,0]


def test_observed_arco_span_view_leaf_only_in_bound_operation_cell(sample):
    x=sample
    x.native.evaluate("""()=>{const op=document.querySelector('#view').closest('td');
      op.innerHTML='<div class="arco-table-cell"><span class="arco-table-cell-wrap-value"><div class="arco-space arco-space-horizontal arco-space-align-center btn-group-kPbBSw">'+
        '<div class="arco-space-item"><span id="view-span" class="arco-link" style="cursor:pointer;pointer-events:auto">查看</span></div>'+
        '<div class="arco-space-item"><span id="delete-span" class="arco-link" style="cursor:pointer;pointer-events:auto">删除</span></div></div></span></div>';
      document.querySelector('#view-span').onclick=()=>{window.views++;const d=document.createElement('section');d.innerHTML='<h2>已有发文</h2><a href="https://www.douyin.com/video/7709043480894524722">原作品</a>';document.body.append(d)};
      document.querySelector('#delete-span').onclick=()=>window.deletes++;
      const other=document.createElement('span');other.className='arco-link';other.style.cursor='pointer';other.textContent='查看';other.onclick=()=>window.deletes++;document.body.append(other)}""")
    result=run(x)
    assert result['status']=='visible_change_observed' and result['view_clicks']==1
    assert x.native.evaluate('()=>[window.views,window.deletes,window.statusClicks]')==[1,0,0]
    controls=result['row']['row']['view_controls']
    assert [(c['text'],c['eligible']) for c in controls]==[('查看',True),('删除',False)]
    assert not result['append_capability_verified'] and result['body_after']['public_links'][0]['path']=='/video/7709043480894524722'
