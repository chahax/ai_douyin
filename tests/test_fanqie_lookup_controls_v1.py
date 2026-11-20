import pytest
from src.platform_adapter.fanqie_lookup_controls_v1 import discover


def test_local_discovery_visible_metadata_and_origin_gate_without_values_or_actions():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:
            context=browser.new_context()
            html='''<meta charset="utf-8"><button role="tab" aria-selected="true">别名管理</button>
            <div role="combobox">BookID</div><input id="public-search" class="arco-input" placeholder="公开搜索" value="PRIVATE">
            <input type="password" placeholder="HIDDEN_PASSWORD"><input style="display:none" placeholder="HIDDEN_INPUT">
            <table><thead><tr><th>关键词</th><th>书本信息</th></tr></thead><tbody></tbody></table>
            <table style="display:none"><thead><tr><th>HIDDEN_TABLE</th></tr></thead></table>
            <script>window.reads=window.writes=0;Object.defineProperty(HTMLInputElement.prototype,'value',{
            get(){reads++;throw Error('forbidden')},set(){writes++;throw Error('forbidden')}});
            document.addEventListener('click',()=>writes++);</script>'''
            context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
            page=context.new_page();page.goto('https://kol.fanqieopen.com/page/promotion-list')
            result=discover(page)
            assert result['visible_tables_count']==1 and result['table']['ready']
            assert result['table']['headers']==['关键词','书本信息']
            assert len(result['text_inputs'])==1 and result['text_inputs'][0]['id']=='public-search'
            assert result['comboboxes'][0]['visible_text']=='BookID'
            assert 'PRIVATE'not in str(result) and 'HIDDEN'not in str(result)
            assert page.evaluate('({reads,writes})')==dict(reads=0,writes=0)
            page.goto('https://kol.fanqieopen.com/page/wrong')
            with pytest.raises(ValueError,match='origin_path'):discover(page)
            context.close()
        finally:browser.close()
