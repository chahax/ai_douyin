"""One real Chrome offscreen disclosure, original RPC shape; no account."""
import json
import threading
from pathlib import Path
import pytest
from test_manual_republication_flow_v5 import native,draft,put
from test_manual_republication_flow_v8 import disclosure
from src.operations_accounts import manual_republication_flow_v9 as flow
from src.operations_accounts import manual_republication_runtime_v9 as runtime


def test_offscreen_same_native_node_scroll_then_one_disclosure_only(disclosure,monkeypatch):
    x=disclosure;original_request=x.request;original_plan=json.loads((x.run/'v8/PLAN.json').read_text(encoding='utf8'))
    request=dict(schema=runtime.REQUEST_SCHEMA,config=original_request['config'],action=runtime.ACTION,
        prior_inspection_plan=put(x.run/'V8_PLAN.json',{}),prior_inspection_action=put(x.run/'V8_ACTION.json',{}),
        prior_unknown=put(x.run/'V8_UNKNOWN.json',{}),prior_failure=put(x.run/'V8_FAILURE.json',{}),trigger_before=put(x.run/'V8_TRIGGER_BEFORE.json',{}))
    reqref=put(x.run/'V9_REQUEST.json',request)
    prior=dict(original_plan['prior'],**{k:original_request[k] for k in ('prepared_result','prepared_receipt','form_readback','file_selection_claim','trigger_projection')})
    pref=put(x.run/'v9/PLAN.json',dict(config=request['config'],request=reqref,prior=prior))
    put(x.run/'v9/ACTION_CLAIM.json',dict(schema='manual_republication_declaration_action_claim/v9',plan=pref,config=request['config'],request=reqref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=runtime.ACTION,
        navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))
    monkeypatch.setattr(runtime,'validate_live',lambda *a:None)
    x.page.locator('section.wrapper-MLZdnB').evaluate("e=>{e.style.marginTop='1800px';window.originalNativeTrigger=e.querySelector('.selectBox-buZRzi')}")
    x.page.evaluate('()=>scrollTo(0,0)')
    result=flow.run_action(x.actor,x.resource,x.config,request,x.run/'v9/inspection')
    before=runtime._read(result['viewport_before_scroll']);after=runtime._read(result['viewport_after_scroll'])
    assert before['located'] and not before['center_hit'] and before['rect']['y']>before['viewport']['inner_height']
    assert after['scroll_count']==1 and after['samples'][-1]['same'] and after['samples'][-1]['eligible']
    assert x.page.evaluate('()=>originalNativeTrigger===document.querySelector(".selectBox-buZRzi")')
    assert x.page.evaluate('()=>[nativeDisclosureClicks,valueWrites,confirmClicks]')==[1,0,0]
    assert result['scroll_performed'] and result['options_observed'] and result['screenshot']['status']=='saved'
    assert not any(k in {'goto','new_tab','fill','type_hashtag','set_input_files'} for k,_ in x.commands)
    assert all(result[k] is False for k in ('declaration_selected','confirmed','submitted','fields_written','file_selected','navigation_performed'))
