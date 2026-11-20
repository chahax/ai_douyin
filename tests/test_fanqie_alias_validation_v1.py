"""Known current naming conflict, actual local form actions and owner bindings."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from src.platform_adapter.fanqie_form_feedback_v1 import validate_alias_validation,confirmed_alias_validation
from src.operations_accounts import fanqie_managed_promotion_v1 as m
from test_fanqie_application_readback_v1 import BOOK,NAME,INTENT,ENTRY,local_html,browser,page

MESSAGE='与热门书籍/短剧/作者相似度高'
local=pytest.mark.skipif(os.environ.get('RUN_LOCAL_FANQIE_FORM_TEST')!='1',reason='Fresh isolated local DOM opt-in')


def initial(page,*,selected=False):
    page.set_content(local_html('replace'))
    if selected:page.evaluate("state.selected='AIGC';render()")


def on_fill_error(page,message=MESSAGE,*,disabled=False):
    page.evaluate('''({message,disabled})=>{document.querySelector('.alias-input-EBp1Sw').addEventListener('input',()=>{
     document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend','<div class="err-list-h4mOz7"></div>');
     document.querySelector('.err-list-h4mOz7').textContent=message;
     document.querySelector('.submit').disabled=disabled;});}''',dict(message=message,disabled=disabled))


def actual_pre_failure(page,*,disabled=False):
    initial(page);on_fill_error(page,disabled=disabled)
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    validate_alias_validation(result,INTENT)
    return result


@local
@pytest.mark.parametrize('disabled',[False,True])
def test_actual_known_conflict_blocks_enabled_or_disabled_submit_before_any_click(page,disabled):
    result=actual_pre_failure(page,disabled=disabled)
    assert result['result']=='alias_validation_failed'and result['retry_with_new_alias']is True
    assert result['alias_reusable']is False and result['submitted']is False
    assert result['alias_validation']['stage']=='after_fill'
    assert result['alias_validation']['known_message']==MESSAGE
    assert result['form_feedback']['baseline']['current_alias']==''
    sample=result['alias_validation']['observation']
    assert sample['current_alias']==INTENT['alias']and sample['submit_buttons'][0]['disabled']is disabled
    assert page.evaluate('events.submit')==0


@local
def test_disabled_empty_input_is_not_combined_with_another_time_screenshot_alias(page):
    initial(page)
    page.evaluate('''message=>{document.querySelector('input').disabled=true;
     document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend','<div class="err-list-h4mOz7"></div>');
     document.querySelector('.err-list-h4mOz7').textContent=message;}''',MESSAGE)
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert result['reason']=='alias_input_not_editable'and not result['retry_with_new_alias']
    assert not confirmed_alias_validation(result,INTENT)
    sample=result['form_feedback']['baseline']
    assert sample['current_alias']==''and sample['same_alias']is False and sample['alias_input_disabled']
    assert page.evaluate('events')==dict(alias=0,control=0,option=0,submit=0)


@local
@pytest.mark.parametrize('message',[MESSAGE+'\n网络异常，请稍后再试','填写说明：请按规则申请别名'])
def test_unknown_or_mixed_validation_blocks_without_authorizing_another_alias(page,message):
    initial(page);on_fill_error(page,message)
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert result['reason']=='form_validation_unconfirmed'and not result['retry_with_new_alias']
    assert not confirmed_alias_validation(result,INTENT)and page.evaluate('events.submit')==0


@local
def test_unchanged_old_alias_warning_is_not_borrowed_for_new_alias(page):
    initial(page,selected=True)
    page.evaluate('''message=>{state.alias='另一条旧别名';render();
     document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend','<div class="err-list-h4mOz7"></div>');
     document.querySelector('.err-list-h4mOz7').textContent=message;}''',MESSAGE)
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert result['reason']=='form_validation_unconfirmed'and not result['retry_with_new_alias']
    assert result['form_feedback']['baseline']['current_alias']=='另一条旧别名'
    assert page.evaluate('events.submit')==0


def prepared(page):
    initial(page)
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert result['ready']and not result['submitted']
    return result


def post_action(page,*,clear_alias=False,wrong_book=False,message=MESSAGE):
    page.evaluate('''({clear_alias,wrong_book,message})=>{
     document.querySelector('.submit').onclick=()=>{events.submit++;
      setTimeout(()=>{if(clear_alias)state.alias='';if(wrong_book)state.book='8302660145530539062';
       render();document.querySelector('.submit').disabled=true;
       document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend','<div class="err-list-h4mOz7"></div>');
       document.querySelector('.err-list-h4mOz7').textContent=message;},100);};}''',
        dict(clear_alias=clear_alias,wrong_book=wrong_book,message=message))


@local
def test_fresh_postclick_exact_subject_is_terminal_UI_validation_only(page):
    prepared(page);post_action(page)
    result=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert result['submitted']is True and page.evaluate('events.submit')==1
    value=validate_alias_validation(result,INTENT)
    assert value['stage']=='post_click'and value['freshness']=='new_post_click_validation'
    assert not value['server_response_evidence']and not value['platform_business_outcome_verified']
    assert result['form_feedback']['pre_click']['messages']==[]
    assert result['form_feedback']['post_click'][-1]==value['observation']


@local
def test_late_preclick_hint_prevents_click_and_generic_disabled_keeps_evidence(page):
    prepared(page)
    page.evaluate('''message=>{document.querySelector('.arco-modal-content').insertAdjacentHTML('beforeend',
     '<div class="err-list-h4mOz7"></div>');document.querySelector('.err-list-h4mOz7').textContent=message;}''',MESSAGE)
    result=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert validate_alias_validation(result,INTENT)['stage']=='pre_click'
    assert result['submitted']is False and page.evaluate('events.submit')==0
    initial(page,selected=True);page.evaluate("document.querySelector('.submit').disabled=true")
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    assert result['reason']=='unique_submit_not_enabled'and not confirmed_alias_validation(result,INTENT)
    assert result['form_feedback']['latest']['submit_buttons'][0]['disabled']


@local
def test_postclick_cleared_alias_has_separate_submitted_binding_while_wrong_book_stays_unknown(page):
    prepared(page);post_action(page,clear_alias=True)
    cleared=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert cleared['submitted']and confirmed_alias_validation(cleared,INTENT)
    assert cleared['form_feedback']['latest']['current_alias']==''
    assert cleared['retry_with_new_alias']is True and cleared['alias_validation']['same_alias']is False
    prepared(page);post_action(page,wrong_book=True)
    other=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert other['submitted']and not confirmed_alias_validation(other,INTENT)
    assert other['form_feedback']['latest']['same_book']is False


@local
def test_pure_validator_rejects_bare_legacy_or_stale_and_wrong_subject_documents(page):
    prepared(page);post_action(page)
    valid=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert confirmed_alias_validation(valid,INTENT)
    assert not confirmed_alias_validation(dict(result='server_rejection_observed',submitted=True),INTENT)
    variants=[]
    wrong=deepcopy(valid);wrong['alias_validation']['alias']='其他别名';variants.append(wrong)
    wrong=deepcopy(valid);wrong['form_feedback']['clicked']=False;variants.append(wrong)
    wrong=deepcopy(valid)
    wrong['form_feedback']['pre_click']['messages']=deepcopy(wrong['alias_validation']['observation']['messages'])
    wrong['alias_validation']['reference']=deepcopy(wrong['form_feedback']['pre_click']);variants.append(wrong)
    wrong=deepcopy(valid);wrong['alias_validation']['known_message']='未观察过的类似提示';variants.append(wrong)
    for variant in variants:
        with pytest.raises(ValueError):validate_alias_validation(variant,INTENT)


@local
@pytest.mark.parametrize('submitted',[False,True])
def test_owner_terminal_failure_returns_exact_evidence_and_preserves_once_claim(tmp_path,page,monkeypatch,submitted):
    from test_fanqie_managed_promotion_v1 import accounts,Session,request
    from src.operations_accounts.fanqie_account_control import run_owner
    from src.platform_adapter import fanqie_exact_book_locator_v1 as locator
    a,env=accounts.__wrapped__(tmp_path);ref=request(a,env,promotion_path='别名推广');intent=json.loads(Path(ref['path']).read_bytes())
    body=local_html('replace').replace(BOOK,intent['book_id']).replace(NAME,intent['book_name'])
    entry=dict(clicked=True,book_name=intent['book_name'],entry_label='别名推广')
    page.set_content(body)
    if submitted:
        good=page.evaluate(m._form_js(intent,entry_evidence=entry));assert good['ready']
        post_action(page);bad=page.evaluate(m._form_js(intent,submit=True,entry_evidence=entry))
    else:
        on_fill_error(page);bad=page.evaluate(m._form_js(intent,entry_evidence=entry));good=None
    validate_alias_validation(bad,intent)
    class ValidationSession(Session):
        def evaluate(self,js):
            if 'fanqie_application_form_readback/v1'in js:
                return bad if ('const submissionMode=true;'in js or not submitted)else good
            return super().evaluate(js)
    monkeypatch.setattr(locator,'locate_exact_book',lambda page,**kw:dict(status='located_after_exact_search'))
    command=a.queue(env['resource_id'],'fanqie_promotion_apply',promotion_request=ref)
    outcome=run_owner(env['resource_id'],a,session_factory=ValidationSession)
    result=outcome['result'];assert outcome['state']=='failed'and result['application_status']=='alias_validation_failed'
    assert result['submitted']is submitted and result['retry_with_new_alias']and result['alias_reusable']is False
    evidence=m._read(result['feedback_ref']);validate_alias_validation(evidence,intent)
    folder=a.folder(command['command_id']);assert (folder/'SUBMIT_CLAIM.json').exists()is submitted
    global_claim=a.evidence/'promotion_application_claims'/m._intent_key(intent)/'CLAIM.json'
    assert global_claim.exists()is submitted
    assert result['feedback_ref']==result['submit_response'if submitted else'form_prepared']
