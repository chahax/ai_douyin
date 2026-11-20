"""Prevented radio default + controlled display, matching the actual Semi UI."""
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import draft,native,put
from test_manual_republication_publish_v10 import publish
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v10 as flow


@pytest.fixture
def continued(publish):
    x=publish
    x.page.evaluate("""()=>{
      const root=document.querySelector('div.semi-modal');const preview=document.createElement('div');preview.className='declaratonBar-v3zoOB';preview.textContent='作者声明：此处显示具体的声明内容';root.insertBefore(preview,root.children[1]);
      window.componentSelectionClicks=0;
      for(const input of root.querySelectorAll('input[type=radio]'))input.addEventListener('click',event=>{
        event.preventDefault();window.componentSelectionClicks++;
        const labels=[...root.querySelectorAll('label.semi-radio')];for(const label of labels)label.classList.toggle('semi-radio-checked',label===input.closest('label'));
        preview.textContent='作者声明：'+input.closest('label').innerText.trim();root.querySelector('#native-confirm').disabled=false;
      });
    }""")
    # This is the one preceding native click, not the continuation action. Its
    # default is prevented; no change event and no checked mirroring is used.
    x.page.locator(flow.LABEL_SELECTOR).nth(0).click()
    actual=x.page.evaluate(flow.modal_controls_script())
    assert x.page.evaluate('()=>componentSelectionClicks')==1 and [c['checked'] for c in actual['native_controls']]==[False]*6
    assert x.page.evaluate('()=>window.statementChanges')==0
    blocked=put(x.run/'BLOCKED_RESULT.json',dict(status='blocked_no_submission',submitted=False,submission_not_attempted=True))
    receipt=put(x.run/'BLOCKED_RECEIPT.json',{})
    failure=put(x.run/'BLOCKED_FAILURE.json',dict(selection_click_dispatched=True,confirmation_click_dispatched=False,publish_click_dispatched=False,submission_claimed=False))
    samples=put(x.run/'BLOCKED_SELECTED_SAMPLES.json',dict(samples=[actual]*12))
    trace=x.run/'BLOCKED_TRACE.jsonl';trace.write_text('native prior selection returned\n',encoding='utf8')
    image=x.run/'BLOCKED_SCREENSHOT.png';x.page.screenshot(path=str(image))
    state_contract=put(x.run/'SELECTED_STATE_CONTRACT.json',dict(schema='semi_radio_selection_display_contract/v1',parent_selection_contract=x.request['declaration_contract'],
        authority=x.config['authority'],blocked_result=blocked,blocked_receipt=receipt,failure=failure,selected_samples=samples,
        rpc_trace=v5.reference(trace),screenshot=v5.reference(image),independent_terminal_review=put(x.run/'PRIVATE_TERMINAL_REVIEW.json',{}),
        expected_selected_label=flow.KNOWN_LABELS[0],observed_native_input_checked=[False]*6,native_checked_must_not_be_falsified=True,
        component_selection_basis=dict(unique_selected_label_class='semi-radio-checked',only_label_index=0,all_other_labels_without_selected_class=True,
            native_label_associations_unchanged=True,exact_preview_text='作者声明：内容由AI生成',unique_confirmation_button=dict(text='确定',type='button',disabled=False),all_12_stable_samples_match=True),
        continuation_selections_allowed=0,continuation_confirmations_allowed=1,continuation_publications_allowed=1,
        no_original_action_replay=True,no_new_upload=True,logical_publication_intent_unchanged=True))
    req=dict(x.request,action=flow.CONTINUE_ACTION,selected_state_contract=state_contract)
    reqref=put(x.run/'CONTINUE_REQUEST.json',req);oldplan=v5.read(v5.reference(x.run/'publish_001/PLAN.json'))
    plan=put(x.run/'continuation_selected_001/PLAN.json',dict(config=req['config'],request=reqref,prior=oldplan['prior']))
    action=put(x.run/'continuation_selected_001/ACTION_CLAIM.json',dict(schema='manual_republication_publish_action_claim/v10',plan=plan,config=req['config'],request=reqref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=flow.CONTINUE_ACTION,
        navigation_allowed=False,file_selection_allowed=False,selections_allowed=0,confirmations_allowed=1,submissions_allowed=1))
    def claim_submission(actor,resource,cfg,request,preflight_ref):
        x.claim_calls+=1;preflight=v5.read(preflight_ref)
        assert preflight['action_claim']==action and preflight['declaration_confirmed'] and request['action']==flow.CONTINUE_ACTION
        assert x.page.evaluate('()=>[componentSelectionClicks,window.confirmCount,window.publishCount]')==[1,1,0]
        assert not any(kind=='click' and kw.get('selector')==flow.LABEL_SELECTOR for kind,kw in x.commands)
        return v5.once(x.run/'SUBMIT_CLAIM.json',dict(preflight=preflight_ref,allowed_publish_clicks=1))
    x.request,x.out=req,x.run/'continuation_selected_001/publication'
    x.runtime_bridge=NS(reference=v5.reference,_read=v5.read,_once=v5.once,validate_live=lambda *a:None,claim_submission=claim_submission)
    return x


def run(x):return flow.run_action(x.actor,x.resource,x.config,x.request,x.out,runtime_bridge=x.runtime_bridge)


def test_actual_controlled_display_continues_without_reselection_or_checked_falsification(continued):
    x=continued;result=run(x)
    assert not result['selection_performed'] and result['selection_reused'] and result['declaration_confirmed'] and result['submitted']
    assert result['selected_state_contract']==x.request['selected_state_contract']
    evidence=v5.read(v5.reference(x.out/'COMPONENT_SELECTED_GROUP.json'))
    assert [n['checked'] for n in evidence['raw_controls']['native_controls']]==[False]*6
    assert evidence['evidence']['native_checked_actual']==[False]*6 and evidence['evidence']['native_checked_falsified'] is False
    assert x.page.evaluate('()=>[componentSelectionClicks,window.confirmCount,window.publishCount]')==[1,1,1]
    assert x.claim_calls==1 and not any(kind=='click' and kw.get('selector')==flow.LABEL_SELECTOR for kind,kw in x.commands)


def test_mixed_component_display_stops_without_confirmation_or_submit_claim(continued):
    x=continued;x.page.locator(flow.LABEL_SELECTOR).nth(3).evaluate("el=>el.classList.add('semi-radio-checked')")
    with pytest.raises(flow.DeclarationControlsBlocked):run(x)
    assert x.page.evaluate('()=>[componentSelectionClicks,window.confirmCount,window.publishCount]')==[1,0,0]
    assert x.claim_calls==0 and not (x.run/'SUBMIT_CLAIM.json').exists()


def test_continuation_publish_ack_unknown_never_reselects_or_reclicks(continued):
    x=continued;x.drop_publish=True
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_submission_unknown'
    assert x.claim_calls==1 and x.page.evaluate('()=>[componentSelectionClicks,window.confirmCount,window.publishCount]')==[1,1,1]
    before=len(x.commands)
    with pytest.raises((flow.DeclarationControlsBlocked,FileExistsError)):run(x)
    assert len(x.commands)==before and x.claim_calls==1
