"""Observed Slate placeholder lifecycle; existing draft only, no platform."""
import sys
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import native,put
from test_manual_republication_flow_v6 import draft,repair
from src.operations_accounts import manual_republication_flow_v6 as v6
from src.operations_accounts import manual_republication_flow_v7 as flow


@pytest.fixture
def complete(repair,monkeypatch):
    x=repair;v6plan=flow.read(flow.reference(x.run/'v6/PLAN.json'))
    v6plan['prior']['file_selection_claim']=x.fileclaim
    prior=put(x.run/'V6_PRIOR_PLAN.json',v6plan)
    config=dict(x.config,sources=dict(x.config['sources'],flow_v6=flow.reference(v6.__file__)))
    cfgref=put(x.run/'CONFIG_V7.json',config)
    image=x.run/'V6_FAILURE_SCREENSHOT.png';x.page.screenshot(path=str(image))
    request=dict(schema='manual_republication_operator_request/v7',config=cfgref,action='complete_existing_form',
        prior_repair_plan=prior,prior_repair_action=flow.reference(x.run/'v6/ACTION_CLAIM.json'),prior_unknown=x.request['prior_unknown'],
        prior_failure=x.request['prior_failure'],initial_field_projection=x.request['field_projection'],failure_screenshot=flow.reference(image))
    reqref=put(x.run/'REQUEST_V7.json',request)
    planref=put(x.run/'v7/PLAN.json',dict(config=cfgref,request=reqref,prior=v6plan['prior']))
    put(x.run/'v7/ACTION_CLAIM.json',dict(schema='manual_republication_complete_form_action_claim/v7',plan=planref,config=cfgref,request=reqref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),
        action='complete_existing_form',navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))
    x.config,x.request,x.out=config,request,x.run/'v7/preparation'
    import src.operations_accounts as ops
    runtime=NS(validate_live=lambda *args:None)
    monkeypatch.setitem(sys.modules,'src.operations_accounts.manual_republication_runtime_v7',runtime)
    monkeypatch.setattr(ops,'manual_republication_runtime_v7',runtime,raising=False)
    return x


@pytest.mark.parametrize('lifecycle',['already_filled_no_placeholder','remove_placeholder_on_native_fill'])
def test_observed_stable_slate_survives_placeholder_lifecycle_and_completes_tags(complete,lifecycle):
    x=complete;x.page.locator('#title').fill(x.metadata['title'])
    if lifecycle=='already_filled_no_placeholder':
        x.page.locator('#editor').fill(x.metadata['description'])
        x.page.locator('#editor').evaluate("el=>el.removeAttribute('data-placeholder')")
    else:
        x.page.locator('#editor').evaluate("el=>el.addEventListener('input',()=>el.removeAttribute('data-placeholder'))")
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert result['metadata_readback_matched'] and result['hashtag_readback_verified']
    assert result['title_fill_skipped'] and result['description_fill_skipped']==(lifecycle=='already_filled_no_placeholder')
    assert x.page.locator('#editor').get_attribute('data-placeholder') is None
    actual=flow.read(result['form_readback']);assert set(actual['hashtag_tokens'])==set(x.metadata['hashtags'])
    assert not any(a in {'goto','set_input_files','new_tab','ai_content_declaration'} for a,_ in x.commands)
    assert all(not result[k] for k in ('submitted','declaration_selected','navigation_performed','file_selected','publication_ready'))


def test_two_visible_stable_slate_roots_block_all_form_writes(complete):
    x=complete;x.page.locator('#editor').evaluate('el=>el.after(el.cloneNode())')
    with pytest.raises(flow.ExistingDraftRepairBlocked):flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert not any(a in {'fill','type_hashtag'} for a,_ in x.commands)
    assert (x.out/'INITIAL_FIELD_PROJECTION.json').is_file()
