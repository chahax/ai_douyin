"""Current modal completeness and native label/control relation; local DOM only."""
import sys
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import draft,native,put
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v7 as v7
from src.operations_accounts import manual_republication_flow_v10 as flow


@pytest.fixture
def controls(draft,monkeypatch):
    x=draft
    config=dict(x.config,sources=dict(x.config['sources'],flow_v5=v5.reference(v5.__file__),flow_v7=v5.reference(v7.__file__)))
    cfgref=put(x.run/'CONFIG_V10.json',config)
    request=dict(schema='manual_republication_operator_request/v10',config=cfgref,action=flow.ACTION,
        prior_result=put(x.run/'V9_RESULT.json',{}),prior_receipt=put(x.run/'V9_RECEIPT.json',{}),options_inventory=put(x.run/'V9_OPTIONS.json',{}))
    reqref=put(x.run/'REQUEST_V10.json',request);prior=v5.read(v5.reference(x.run/'v5/PLAN.json'))['prior'];prior['file_selection_claim']=x.fileclaim
    planref=put(x.run/'v10/PLAN.json',dict(config=cfgref,request=reqref,prior=prior))
    put(x.run/'v10/ACTION_CLAIM.json',dict(schema='manual_republication_controls_action_claim/v10',plan=planref,config=cfgref,request=reqref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=flow.ACTION,
        navigation_allowed=False,file_selection_allowed=False,selections_allowed=0,confirmations_allowed=0,submissions_allowed=0))
    x.config,x.request,x.out=config,request,x.run/'v10/inspection'
    oldcmd=x.resource.session.cmd
    def cmd(kind,**kw):
        if kind=='screenshot':x.page.screenshot(path=kw['path'],full_page=False);x.commands.append((kind,kw));return {'status':'ok'}
        return oldcmd(kind,**kw)
    x.resource.session.cmd=cmd
    import src.operations_accounts as ops
    runtime=NS(reference=v5.reference,_read=v5.read,_once=v5.once,validate_live=lambda *args:None)
    monkeypatch.setitem(sys.modules,'src.operations_accounts.manual_republication_runtime_v10',runtime)
    monkeypatch.setattr(ops,'manual_republication_runtime_v10',runtime,raising=False)
    x.runtime_bridge=runtime
    def add_modal(mode='native'):
        x.page.evaluate("""data=>{const root=document.createElement('div');root.className='semi-modal semi-modal-small';
          root.innerHTML='<h2>对作品内容添加声明</h2><p>可在作品发布前添加声明，帮助他人减少困惑</p><p>请选择声明类型（单选）</p>';
          data.labels.forEach((text,index)=>{let label=document.createElement(data.mode==='native'?'label':'div');
            if(data.mode==='native'){let input=document.createElement('input');input.type='radio';input.name='native-statement';input.id='statement-'+index;
              input.style='position:absolute;opacity:0;width:1px;height:1px';label.htmlFor=input.id;root.append(input);}
            else {label.setAttribute('role','radio');label.setAttribute('aria-checked','false');}
            const span=document.createElement('span');span.textContent=text;label.append(span);root.append(label);});
          root.innerHTML+='<button type="button" onclick="window.confirmed++">确定</button><button type="button" onclick="window.cancelled++">取消</button>';
          window.confirmed=window.cancelled=window.inputEvents=0;document.body.append(root);
          document.addEventListener('input',()=>window.inputEvents++,true);
          Object.defineProperty(HTMLInputElement.prototype,'value',{get(){throw Error('private value read')},set(){throw Error('value write')}});}
        """,dict(labels=flow.KNOWN_LABELS,mode=mode))
    x.add_modal=add_modal
    return x


def run(x):return flow.run_action(x.actor,x.resource,x.config,x.request,x.out)


def test_current_modal_reads_hidden_associated_native_checked_without_values_or_effects(controls):
    x=controls;x.add_modal()
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out,runtime_bridge=x.runtime_bridge)
    data=v5.read(result['modal_controls'])
    assert data['render_complete'] and data['native_associations_complete']
    assert len(data['labels'])==len(data['native_controls'])==6
    assert all(c['checked_read_allowed'] and c['checked'] is False and c['native_visible'] is False for c in data['native_controls'])
    assert data['semantics']['same_nonempty_native_radio_name'] and data['semantics']['all_associated_controls_are_native_radio']
    assert data['input_values_read'] is False and data['private_state_read'] is False
    assert x.page.evaluate('()=>[window.confirmed,window.cancelled,window.inputEvents]')==[0,0,0]
    assert all(result[k] is False for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','navigation_performed','file_selected','submitted','publication_ready','stage2_implemented'))
    assert not any(a in {'fill','click','type_hashtag','set_input_files','goto','new_tab'} for a,_ in x.commands)


def test_custom_radio_text_is_captured_without_fabricating_native_association(controls):
    x=controls;x.add_modal('custom');result=run(x);data=v5.read(result['modal_controls'])
    assert data['render_complete'] and not data['native_associations_complete']
    assert data['native_controls']==[] and len(data['role_controls'])==6
    assert not data['semantics']['all_associated_controls_are_native_radio'] and not result['stage2_implemented']


def test_ambiguous_current_modal_fails_closed_with_actual_projection_saved(controls):
    x=controls;x.add_modal();x.page.locator('div.semi-modal').evaluate('el=>el.after(el.cloneNode(true))')
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_modal_unconfirmed'
    data=v5.read(v5.reference(x.out/'CURRENT_DECLARATION_CONTROLS.json'))
    assert data['visible_modal_count']==2 and data['render_complete'] is False
    assert not any(a in {'fill','click','set_input_files','goto'} for a,_ in x.commands)
