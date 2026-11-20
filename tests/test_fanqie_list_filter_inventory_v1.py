from src.platform_adapter.fanqie_list_filter_inventory_v1 import LIST_FILTER_INVENTORY_JS


def test_local_visible_filter_evidence_does_not_read_values_or_mutate():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:
            context=browser.new_context()
            context.route('**/*',lambda route:route.abort())
            page=context.new_page()
            page.set_content('''<meta charset="utf-8"><div class="arco-form-item">
              <label class="arco-form-item-label">状态</label><div class="arco-select" role="combobox">全部</div></div>
              <button role="tab" aria-selected="true">申词记录</button>
              <input type="radio" checked value="PRIVATE_VALUE" aria-label="全部状态">
              <div role="radio" aria-checked="true">审核中</div>
              <div role="tab" style="display:none">HIDDEN_SECRET</div>
              <div class="arco-form-item"><label class="arco-form-item-label" style="display:none">HIDDEN_LABEL</label><div class="arco-select">公开选择</div></div>
              <script>window.reads=window.writes=0;Object.defineProperty(HTMLInputElement.prototype,'value',{
              get(){reads++;throw Error('value forbidden')},set(){writes++;throw Error('write forbidden')}});
              document.addEventListener('click',()=>writes++);</script>''')
            result=page.evaluate(LIST_FILTER_INVENTORY_JS)
            assert result['visible_control_count']==5
            assert result['all_statuses_included'] is None and result['completeness']=='unknown'
            assert any(x['aria_selected']=='true'for x in result['controls'])
            assert any(x['checked'] is True for x in result['controls'])
            assert any(x['field_label']=='状态'and x['visible_text']=='全部'for x in result['controls'])
            assert 'PRIVATE_VALUE'not in str(result) and 'HIDDEN_SECRET'not in str(result)
            assert 'HIDDEN_LABEL'not in str(result)
            assert page.evaluate('({reads,writes})')==dict(reads=0,writes=0)
            context.close()
        finally:
            browser.close()
