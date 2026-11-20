"""Sanitized public form/UI feedback only, never inferred server rejection."""
import ast
import json
import os
from pathlib import Path

import pytest

from src.platform_adapter import fanqie_form_feedback_v1 as m
from src.platform_adapter import fanqie_promotion_preflight_v1 as pre
from src.operations_accounts import fanqie_managed_promotion_v1 as managed
from test_fanqie_application_readback_v1 import BOOK,NAME,INTENT,ENTRY,local_html,browser,page


def test_only_public_metadata_and_changed_feedback_can_affect_future_result():
    js=managed._form_js(INTENT,submit=True,entry_evidence=ENTRY)
    assert 'server_rejection_observed' not in js and 'unverified_form_feedback' in js
    assert js.index('const baseline=')<js.index('buttons[0].click();')
    assert 'sameBook?fqMessages(fresh.modal):[]' in js and 'fqNewMessages(messages,baseline.messages)' in js
    assert 'server_response_evidence:false' in js and 'platform_business_outcome_verified:false'in js
    assert 'input.value' not in m.PUBLIC_FORM_HELPERS_JS
    assert 'text:fqVisible(e)?fqText(e,500):null' in m.PUBLIC_FORM_HELPERS_JS
    assert 'public_form_inventory' in pre._form_js(BOOK,NAME)


local=pytest.mark.skipif(os.environ.get('RUN_LOCAL_FANQIE_FORM_TEST')!='1',reason='Fresh isolated local DOM opt-in')


def prepared(page):
    page.set_content(local_html('replace'))
    result=page.evaluate(managed._form_js(INTENT,entry_evidence=ENTRY))
    assert result['ready']
    page.evaluate('events.submit=0')


def submit_action(page,body):
    page.evaluate('''body=>{document.querySelector('.submit').onclick=()=>{events.submit++;(new Function(body))();};}''',body)


@local
def test_preflight_inventory_has_visible_rules_and_hidden_message_metadata_without_values(page):
    page.set_content(local_html('never'))
    page.evaluate('''()=>{
     const modal=document.querySelector('.arco-modal-content');
     modal.insertAdjacentHTML('beforeend','<div class="err-list-h4mOz7">别名为公开推广词，须遵守命名规则</div><div class="err-list-h4mOz7" style="display:none">PRIVATE-HIDDEN-MESSAGE</div>');
     const input=modal.querySelector('input');input.value='PRIVATE-INPUT-VALUE';input.maxLength=12;
     const field=document.createElement('div');field.className='arco-form-item';field.innerHTML='<label class="arco-form-item-label">申请别名</label>';
     input.before(field);field.appendChild(input);
     document.body.insertAdjacentHTML('beforeend','<input type="password" value="PRIVATE-AUTH">');
    }''')
    result=page.evaluate(pre._form_js(BOOK,NAME));inventory=result['public_form_inventory']
    assert result['ready']and inventory['messages'][0]['text']=='别名为公开推广词，须遵守命名规则'
    assert inventory['messages'][1]['visible']is False and inventory['messages'][1]['text']is None
    assert any(c['max_length']==12 for f in inventory['fields']for c in f['controls'])
    raw=json.dumps(result,ensure_ascii=False)
    assert all(word not in raw for word in ['PRIVATE-HIDDEN-MESSAGE','PRIVATE-INPUT-VALUE','PRIVATE-AUTH'])
    assert page.evaluate('events')==dict(alias=0,control=1,option=0,submit=0)
    assert inventory['server_response_evidence']is False and inventory['platform_business_outcome_verified']is False


@local
def test_static_help_or_hidden_error_is_not_a_new_rejection_and_archived_logic_mislabels_it(page):
    prepared(page)
    page.evaluate('''document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend',
     '<div class="err-list-h4mOz7">填写说明：请按规则申请别名</div><div class="err-list-h4mOz7" style="display:none">PRIVATE-HIDDEN</div>')''')
    submit_action(page,'')
    before=Path('data/flow_development/fanqie_form_feedback_20261116/fanqie_managed_promotion_v1.py.before')
    node=next(n for n in ast.parse(before.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)and n.name=='_form_js')
    ns={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),str(before),'exec'),ns)
    old=page.evaluate(ns['_form_js'](INTENT,submit=True,entry_evidence=ENTRY))
    assert old['result']=='server_rejection_observed'
    page.evaluate('events.submit=0')
    current=page.evaluate(managed._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert current['submitted']is False and current['result']=='form_validation_unconfirmed'
    assert current['retry_with_new_alias']is False
    feedback=current['form_feedback']
    assert 'PRIVATE-HIDDEN'not in json.dumps(feedback,ensure_ascii=False)
    assert page.evaluate('events.submit')==0


@local
def test_new_visible_feedback_saved_sanitized_without_claiming_server_or_business_rejection(page):
    prepared(page)
    page.evaluate('''document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend',
     '<div class="public-description">填写说明</div>')''')
    submit_action(page,"setTimeout(()=>{document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend','<div class=\"err-list-h4mOz7\"></div>');document.querySelector('.err-list-h4mOz7').textContent='该别名已被使用 https://example.invalid/path?token=PRIVATE-URL token=PRIVATE-TOKEN';},150)")
    result=page.evaluate(managed._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert result['result']=='post_submit_feedback_observed'and result['feedback_classification']=='unverified_form_feedback'
    feedback=result['submission_feedback'];changed=feedback['observations'][-1]['changed_messages']
    assert len(changed)==1 and changed[0]['text'].startswith('该别名已被使用')
    raw=json.dumps(feedback,ensure_ascii=False)
    assert 'PRIVATE-URL'not in raw and 'PRIVATE-TOKEN'not in raw
    assert feedback['baseline']['messages']==[]
    assert '填写说明'in feedback['baseline']['public_form_inventory']['public_text_lines']
    assert not feedback['server_response_evidence']and not feedback['platform_business_outcome_verified']
    assert page.evaluate('events.submit')==1


@local
def test_detached_old_modal_error_and_other_book_message_do_not_become_current_feedback(page):
    prepared(page)
    page.evaluate('''document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend',
     '<div class="public-description">旧表单说明</div>')''')
    submit_action(page,"setTimeout(()=>{state.book='8302660145530539062';render();document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend','<div class=\"err-list-h4mOz7\">另一书的提示</div>');},150)")
    result=page.evaluate(managed._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert result['result']=='confirmation_pending'
    observations=result['submission_feedback']['observations']
    assert all(o['same_book_modal']is False and o['messages']==[] for o in observations)
    assert page.evaluate('events.submit')==1


@local
def test_existing_success_wording_is_not_reused_as_a_fresh_success(page):
    prepared(page)
    page.evaluate("document.body.insertAdjacentHTML('beforeend','<div class=\"title-azi_qL\">申请成功</div>')")
    submit_action(page,'')
    result=page.evaluate(managed._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert result['result']=='confirmation_pending'
    assert all(o['changed_titles']==[]for o in result['submission_feedback']['observations'])
    assert page.evaluate('events.submit')==1
