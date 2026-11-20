"""Local deterministic React-like rebuilds, no account or platform requests."""
import ast
import json
import os
from pathlib import Path

import pytest

from src.operations_accounts import fanqie_managed_promotion_v1 as m

BOOK='7302660145530539062'
NAME='本地精确测试书'
INTENT=dict(book_id=BOOK,book_name=NAME,alias='本地测试推广词',promotion_path='别名推广',publish_type='AIGC')
ENTRY=dict(clicked=True,book_name=NAME,entry_label='别名推广')


def test_script_fresh_resolves_all_intent_and_keeps_submit_after_stable_readback():
    js=m._form_js(INTENT,submit=True,entry_evidence=ENTRY)
    assert js.index('current=await stable(')<js.index('buttons[0].click();')
    assert js.index('current=read();record(current,\'final_fresh\')')<js.index('buttons[0].click();')
    assert "book_identity_verified:ids.length===1" in js and "alias_input_count:inputs.length" in js
    assert 'stable_required:2' in js and 'max_polls_per_stage:20' in js
    assert 'observations.length<80' in js and 'input.value.slice(0,200)' in js
    assert 'if(!true)' in js # submit cannot enter the input/selection branch


def test_original_claim_and_authorization_order_has_not_moved_before_prepare():
    import inspect
    source=inspect.getsource(m.make_handlers)
    assert source.index("prepared=page.evaluate(_form_js")<source.index("with once.open('x'")
    assert source.index("with once.open('x'")<source.index("_form_js(intent,submit=True")
    assert "application_request(payload['request'],env,identity())" in source


def local_html(mode):
    # Public fixed test data. Entire modal is replaced after the chosen option
    # click, so retaining the old select/input pointer deterministically fails.
    return '''<meta charset="utf-8"><div id="host"></div><div id="options" style="display:none"></div>
    <script>
    window.state={book:'''+json.dumps(BOOK)+''',alias:'',selected:'请选择',mode:'''+json.dumps(mode)+'''};
    window.events={alias:0,control:0,option:0,submit:0};
    window.render=()=>{
      document.querySelector('#host').innerHTML=`<div class="arco-modal-content"><h2>'''+NAME+'''（${state.book}）</h2>
        <input class="alias-input-EBp1Sw"><div class="arco-form-item"><label class="arco-form-item-label">发文类型</label>
        <div class="arco-select">${state.selected}</div></div><button class="submit">提交申请</button></div>`;
      const input=document.querySelector('.alias-input-EBp1Sw');input.value=state.alias;
      input.addEventListener('input',e=>{events.alias++;state.alias=e.target.value;});
      document.querySelector('.arco-select').onclick=()=>{
        events.control++;const popup=document.querySelector('#options');popup.style.display='block';popup.innerHTML='<div role="option">AIGC</div>';
        popup.firstElementChild.onclick=()=>{events.option++;popup.style.display='none';
          if(state.mode==='never')return;
          setTimeout(()=>{
            state.selected='AIGC';
            if(state.mode==='wrongbook')state.book='8302660145530539062';
            if(state.mode==='lostalias')state.alias='';
            render();
            if(state.mode==='duplicate')document.querySelector('#host').insertAdjacentHTML('beforeend',document.querySelector('.arco-modal-content').outerHTML);
          },350);
        };
      };
      document.querySelector('.submit').onclick=()=>{events.submit++;document.body.insertAdjacentHTML('beforeend','<div class="title-azi_qL">申请成功</div>');};
    };render();</script>'''


@pytest.fixture(scope='module')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright()as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking',
            '--disable-component-update','--no-first-run','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:yield browser
        finally:browser.close()


@pytest.fixture
def page(browser):
    context=browser.new_context();page=context.new_page()
    context.route('**/*',lambda route:route.abort())
    try:yield page
    finally:context.close()


local=pytest.mark.skipif(os.environ.get('RUN_LOCAL_FANQIE_FORM_TEST')!='1',reason='Fresh isolated local DOM opt-in')


@local
def test_archived_original_fails_same_delayed_rebuild_that_new_form_handles(page):
    before=Path('data/flow_development/fanqie_application_readback_20261116/fanqie_managed_promotion_v1.py.before')
    node=next(n for n in ast.parse(before.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)and n.name=='_form_js')
    namespace={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),str(before),'exec'),namespace)
    page.set_content(local_html('replace'))
    old=page.evaluate(namespace['_form_js'](INTENT,entry_evidence=ENTRY))
    assert old==dict(ready=False,reason='form_readback_mismatch')
    assert page.evaluate('events.submit')==0
    page.wait_for_timeout(400) # Finish the old page's pending fixture callback.
    page.set_content(local_html('replace'))
    current=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert current['ready'] is True and current['submitted'] is False
    observations=current['readback']['observations']
    assert any(o['publish_type_text']=='请选择'for o in observations)
    assert observations[-1]['publish_type_text']=='AIGC' and observations[-1]['alias_value']==INTENT['alias']
    assert page.evaluate('events')==dict(alias=1,control=1,option=1,submit=0)


@local
@pytest.mark.parametrize('mode,reason,field',[('never','form_readback_mismatch','publish_type'),
    ('lostalias','form_readback_mismatch','alias'),('wrongbook','modal_exact_book_unconfirmed',None),
    ('duplicate','unique_modal_required',None)])
def test_actual_current_values_or_identity_failure_stays_closed_before_submit(page,mode,reason,field):
    page.set_content(local_html(mode));result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert result['ready'] is False and result['reason']==reason
    last=result['readback']['observations'][-1]
    if field:assert field in last['mismatch_fields']
    assert page.evaluate('events')==dict(alias=1,control=1,option=1,submit=0)
    assert 'alias_attached' in last and 'publish_type_attached'in last
    if mode=='duplicate':assert last['modal_count']==2 and last['alias_input_count']==0
    else:assert last['alias_input_count']==1


@local
def test_submit_fresh_check_never_refills_or_selects_and_refuses_changed_intent(page):
    page.set_content(local_html('replace'));prepared=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert prepared['ready']
    page.evaluate("state.alias='changed after prepare';render()")
    refused=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert refused['ready']is False and refused['reason']=='form_readback_mismatch'
    assert 'alias'in refused['readback']['observations'][-1]['mismatch_fields']
    assert page.evaluate('events')==dict(alias=1,control=1,option=1,submit=0)


@local
def test_submit_rechecks_exact_full_intent_then_one_submit_only(page):
    page.set_content(local_html('replace'));assert page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))['ready']
    result=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert result['ready']and result['submitted']and result['result']=='success_message_observed'
    assert page.evaluate('events')==dict(alias=1,control=1,option=1,submit=1)
    obs=result['readback']['observations']
    assert obs[-1]['phase']=='final_fresh'and obs[-1]['mismatch_fields']==[]
    assert len([o for o in obs if o['phase'].startswith('pre_submit_')])>=2
