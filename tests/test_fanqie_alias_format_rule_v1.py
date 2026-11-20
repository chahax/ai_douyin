"""Only the exact observed formatting message is newly classified."""
import os
import pytest

from src.platform_adapter.fanqie_form_feedback_v1 import validate_alias_validation,confirmed_alias_validation
from src.operations_accounts import fanqie_managed_promotion_v1 as m
from test_fanqie_application_readback_v1 import INTENT,ENTRY,browser,page
from test_fanqie_alias_validation_v1 import prepared,post_action,initial,on_fill_error

FORMAT='仅支持汉字及阿拉伯数字，字数限制为4-8字'
local=pytest.mark.skipif(os.environ.get('RUN_LOCAL_FANQIE_FORM_TEST')!='1',reason='Isolated local DOM opt-in')


@local
def test_exact_format_hint_after_once_click_and_clear_has_full_live_v2_subject(page):
    prepared(page);post_action(page,clear_alias=True,message=FORMAT)
    result=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    value=validate_alias_validation(result,INTENT)
    assert value['schema']=='fanqie_alias_validation/v2'and value['rule_id']=='alias_format_invalid'
    assert value['same_alias']is False and value['current_alias']==''and value['submitted_alias']==INTENT['alias']
    assert value['alias_binding']['evidence_mode']=='live_observation'and page.evaluate('events.submit')==1
    assert not value['server_response_evidence']and not value['platform_business_outcome_verified']


@local
@pytest.mark.parametrize('message',[FORMAT+'\n网络异常，请稍后再试',FORMAT.replace('4-8','4—8')])
def test_mixed_or_unobserved_near_format_hint_keeps_unknown_without_next(page,message):
    prepared(page);post_action(page,clear_alias=True,message=message)
    result=page.evaluate(m._form_js(INTENT,submit=True,entry_evidence=ENTRY))
    assert not confirmed_alias_validation(result,INTENT)and not result.get('retry_with_new_alias',False)
    assert result['submitted']is True and page.evaluate('events.submit')==1


@local
def test_visible_exact_format_hint_before_click_is_v1_current_alias_validation(page):
    initial(page);on_fill_error(page,FORMAT)
    result=page.evaluate(m._form_js(INTENT,entry_evidence=ENTRY))
    value=validate_alias_validation(result,INTENT)
    assert value['schema']=='fanqie_alias_validation/v1'and value['rule_id']=='alias_format_invalid'
    assert result['submitted']is False and page.evaluate('events.submit')==0
