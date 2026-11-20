"""Actual known alias input outside Arco form items: metadata, no value/event."""
from src.platform_adapter import fanqie_promotion_preflight_v1 as pre


def test_direct_alias_metadata_without_form_item_never_reads_value_or_presses_key():
    from playwright.sync_api import sync_playwright
    with sync_playwright()as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking',
            '--disable-component-update','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:
            context=browser.new_context();context.route('**/*',lambda route:route.abort())
            page=context.new_page();page.set_content('''<meta charset="utf-8"><div class="arco-modal-content">
             <div>本地精确书（7302660145530539062）</div>
             <input class="alias-input-EBp1Sw" placeholder="请输入推广别名，回车确认" minlength="2" maxlength="12"
              pattern="[一-龥]{2,12}" inputmode="text" enterkeyhint="done" required value="PRIVATE-ALIAS">
             <input class="alias-input-EBp1Sw" style="display:none" placeholder="HIDDEN-PLACEHOLDER" value="PRIVATE-HIDDEN">
             <div class="arco-select" onclick="window.selectClicks++">请选择计划素材类型</div></div>
             <script>window.valueReads=window.inputEvents=window.keys=window.selectClicks=0;
              Object.defineProperty(HTMLInputElement.prototype,'value',{get(){valueReads++;throw Error('forbidden value')},set(){inputEvents++;throw Error('forbidden write')}});
              document.addEventListener('input',()=>inputEvents++);document.addEventListener('keydown',()=>keys++);</script>''')
            result=page.evaluate(pre._form_js('7302660145530539062','本地精确书'))
            assert result['ready']and result['public_form_inventory']['fields']==[]
            inputs=result['public_form_inventory']['known_alias_inputs']
            assert inputs==[dict(tag='input',type='text',placeholder='请输入推广别名，回车确认',min_length=2,max_length=12,
                pattern='[一-龥]{2,12}',input_mode='text',enter_key_hint='done',required=True,disabled=False,read_only=False)]
            assert 'PRIVATE'not in str(result)and 'HIDDEN-PLACEHOLDER'not in str(result)
            assert page.evaluate('({valueReads,inputEvents,keys,selectClicks})')==dict(valueReads=0,inputEvents=0,keys=0,selectClicks=1)
            context.close()
        finally:browser.close()
