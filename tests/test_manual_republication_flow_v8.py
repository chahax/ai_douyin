"""Real isolated Chrome/RPC; observed roleless entry, synthetic choices only."""
import threading
from pathlib import Path

import pytest
from test_manual_republication_flow_v5 import native,draft,put
from src.operations_accounts import manual_republication_flow_v8 as flow


@pytest.fixture
def disclosure(draft,monkeypatch):
    x=draft
    x.page.locator('#entry').evaluate('e=>e.remove()');x.page.locator('#options').evaluate('e=>e.remove()')
    snippet=Path(__file__).with_name('fixtures').joinpath('manual_republication_declaration_trigger_20261118.html').read_text(encoding='utf8')
    x.page.evaluate('(html)=>{const host=document.createElement("div");host.innerHTML=html;document.body.append(host);for(const old of host.querySelectorAll("script")){const s=document.createElement("script");s.textContent=old.textContent;old.replaceWith(s)}}',snippet)
    x.page.locator('#title').fill(x.metadata['title']);x.page.locator('#editor').fill(x.metadata['description']+' '+''.join('#'+tag+' ' for tag in x.metadata['hashtags']))
    x.page.locator('#editor').evaluate('e=>e.removeAttribute("data-placeholder")')
    # The actual parent source is compiled, not a fake flow or alternate locator.
    from src.operations_accounts.manual_republication_runtime_v8 import reference
    x.config['sources']['flow_v7']=reference(flow.ROOT/'src/operations_accounts/manual_republication_flow_v7.py')
    x.config['sources']['flow_v5']=reference(flow.ROOT/'src/operations_accounts/manual_republication_flow_v5.py')
    cref=put(x.run/'CONFIG_V8.json',x.config)
    req=dict(schema='manual_republication_operator_request/v8',config=cref,action='inspect_declaration_options',prepared_result=put(x.run/'V7_RESULT.json',{}),
        prepared_receipt=put(x.run/'V7_BINDING.json',{}),form_readback=put(x.run/'V7_FORM.json',{}),file_selection_claim=x.fileclaim,trigger_projection=put(x.run/'V7_TRIGGER.json',{}))
    rref=put(x.run/'REQUEST_V8.json',req)
    import json
    oldplan=json.loads((x.run/'v5/PLAN.json').read_text(encoding='utf8'))
    pref=put(x.run/'v8/PLAN.json',dict(config=cref,request=rref,prior=dict(oldplan['prior'],file_selection_claim=x.fileclaim)))
    put(x.run/'v8/ACTION_CLAIM.json',dict(schema='manual_republication_declaration_action_claim/v8',plan=pref,config=cref,request=rref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),action='inspect_declaration_options',
        navigation_allowed=False,file_selection_allowed=False,submissions_allowed=0))
    old=x.resource.session.cmd
    def cmd(kind,**kw):
        if kind=='screenshot':
            assert kw.pop('tab_id')=='same-tab';x.commands.append((kind,dict(kw)));x.page.screenshot(path=kw['path']);return {}
        return old(kind,**kw)
    x.resource.session.cmd=cmd
    from src.operations_accounts import manual_republication_runtime_v8 as rt
    monkeypatch.setattr(rt,'validate_live',lambda *a:None)
    x.request=req;x.out=x.run/'v8/inspection'
    return x


def test_native_roleless_disclosure_once_complete_options_no_value_or_publish(disclosure):
    x=disclosure;before=Path(x.fileclaim['path']).read_bytes()
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    from src.operations_accounts.manual_republication_runtime_v8 import _read
    inventory=_read(result['options_inventory'])
    assert inventory['complete_visible_capture'] and not inventory['truncated']
    assert inventory['selection_semantics']=='explicit_multiple'
    assert {node['checked'] for node in inventory['native_nodes'] if node['tag']=='input'}=={True,False}
    assert '测试帮助文本' in inventory['visible_text']
    assert 'HIDDEN_NOT_AN_OPTION' not in str(inventory)
    assert result['screenshot']['status']=='saved' and result['metadata_readback_matched']
    assert x.page.evaluate('()=>[nativeDisclosureClicks,valueWrites,confirmClicks]')==[1,0,0]
    assert len([k for k,_ in x.commands if k=='click'])==1
    assert not any(k in {'fill','type_hashtag','goto','new_tab','set_input_files'} for k,_ in x.commands)
    assert all(result[k] is False for k in ('submitted','declaration_selected','confirmed','navigation_performed','file_selected','fields_written','publication_ready'))
    assert Path(x.fileclaim['path']).read_bytes()==before


def test_same_trigger_dynamic_action_descendant_is_blocked_at_native_event(disclosure):
    x=disclosure;old=x.resource.session.cmd
    def cmd(kind,**kw):
        if kind=='click':
            x.page.locator('.selectBox-buZRzi').evaluate("e=>{const b=document.createElement('button');b.type='button';b.textContent='删除';b.style='position:absolute;inset:0';e.style.position='relative';b.onclick=()=>window.valueWrites++;e.append(b)}")
        return old(kind,**kw)
    x.resource.session.cmd=cmd
    with pytest.raises(flow.DeclarationInspectionBlocked):flow.run_action(x.actor,x.resource,x.config,x.request,x.out)
    assert x.page.evaluate('()=>[nativeDisclosureClicks,valueWrites,confirmClicks]')==[0,0,0]
    assert not any(k in {'fill','type_hashtag','goto','new_tab','set_input_files'} for k,_ in x.commands)
    assert (x.out/'INSPECTION_FAILURE.json').is_file()
