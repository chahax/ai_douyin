"""One exact native declaration and once submit; local DOM, synthetic transport."""
import json
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import draft,native,put
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v7 as v7
from src.operations_accounts import manual_republication_flow_v10 as flow


@pytest.fixture
def publish(draft):
    x=draft;x.drop_publish=False;x.old_only=False;x.claim_calls=0
    x.page.locator('#title').fill(x.metadata['title'])
    x.page.locator('#editor').fill('\u200b'+x.metadata['description']+' '+ ' '.join('#'+t for t in x.metadata['hashtags'])+'\u200b')
    x.page.evaluate("""labels=>{
      const section=document.createElement('section');section.className='wrapper-MLZdnB';section.innerHTML='<div class="labelWrapper-p6osJm"><div class="title-cnbkZe">自主声明</div></div><div class="controlWrapper-Kt_9Xm"><div class="selectBox-buZRzi"><div class="selectText-XSrMFZ">请选择自主声明</div></div></div>';document.body.append(section);
      const settings=document.createElement('section');settings.innerHTML='<div><h3>谁可以看</h3><label><input type="checkbox" id="public" checked>公开</label><label><input type="checkbox">好友可见</label><label><input type="checkbox">仅自己可见</label></div><div><h3>发布时间</h3><label><input type="checkbox" checked>立即发布</label><label><input type="checkbox">定时发布</label></div>';document.body.append(settings);
      const modal=document.createElement('div');modal.className='semi-modal semi-modal-small';modal.style='position:fixed;top:10px;left:50px;width:500px;background:white;z-index:100';modal.innerHTML='<h2>对作品内容添加声明</h2><p>请选择声明类型（单选）</p>';
      labels.forEach((text,index)=>{const label=document.createElement('label');label.className='semi-radio';label.style.display='block';const input=document.createElement('input');input.type='radio';input.name='default';input.style='opacity:0;position:absolute;width:1px;height:1px';const span=document.createElement('span');span.className='semi-radio-addon';span.textContent=text;label.append(input,span);modal.append(label);
        input.addEventListener('change',()=>{window.statementChanges++;for(const l of modal.querySelectorAll('label.semi-radio'))l.classList.toggle('semi-radio-checked',l.control.checked);modal.querySelector('#native-confirm').disabled=!modal.querySelector('input').checked;});
        Object.defineProperty(input,'value',{get(){throw Error('radio value read')},set(){throw Error('radio value write')}});});
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';modal.append(cancel);
      const confirm=document.createElement('button');confirm.id='native-confirm';confirm.type='button';confirm.disabled=true;confirm.textContent='确定';confirm.onclick=()=>{window.confirmCount++;document.querySelector('.selectText-XSrMFZ').textContent='内容由AI生成';modal.remove()};modal.append(confirm);document.body.append(modal);
      window.statementChanges=window.confirmCount=window.publishCount=0;
      const submit=document.querySelector('#publish');submit.style='position:fixed;right:10px;bottom:10px;z-index:5';
      submit.onclick=()=>{window.publishCount++;for(const id of ['7709043480894524722',...(window.oldOnly?[]:['7709999000000000001'])]){const card=document.createElement('div');card.className='video-card-sfaSzz';card.setAttribute('data-video-id',id);card.innerHTML='<span class="info-title-text-test"></span><a>作品链接</a><span>2026-11-18 12:00 02:01 审核中</span>';card.querySelector('span').textContent=document.querySelector('#title').value;card.querySelector('a').href='https://www.douyin.com/video/'+id;document.body.append(card)};history.pushState({},'', '/creator-micro/content/manage');};
    }""",flow.KNOWN_LABELS)
    controls=x.page.evaluate(flow.modal_controls_script());assert controls['render_complete'] and controls['native_associations_complete']
    config=dict(x.config,sources=dict(x.config['sources'],flow_v5=v5.reference(v5.__file__),flow_v7=v5.reference(v7.__file__)))
    cfgref=put(x.run/'CONFIG_PUBLISH.json',config);controls_ref=put(x.run/'ACTUAL_CONTROLS.json',controls)
    oldresult=put(x.run/'STAGE1_RESULT.json',{});receipt=put(x.run/'STAGE1_RECEIPT.json',{})
    requirements=put(x.run/'VERIFICATION_REQUIREMENTS.json',dict(schema='republication_verification_requirements/v1',authority=config['authority'],metadata=config['metadata'],
        excluded_old_post_ids=['7709043480894524722','7708948487446056192'],no_submit_retry=True))
    contract=put(x.run/'CHOICE_CONTRACT.json',dict(schema='native_statement_selection_contract/v1',inspection_result=oldresult,inspection_receipt=receipt,
        native_controls=controls_ref,metadata=config['metadata'],file_selection_claim=x.fileclaim,selected_label=flow.KNOWN_LABELS[0],required_final_statement=flow.KNOWN_LABELS[0],
        selection_semantics='single',expected_all_other_labels=list(flow.KNOWN_LABELS[1:]),caption_must_remain_unchanged=True,no_file_selection_allowed=True,no_navigation_before_submission=True,
        native_marketing_also_selected=False,new_publication_limit=1,new_backfill_limit=1,native_label=controls['labels'][0],native_radio=controls['native_controls'][0],
        native_confirmation=dict(tag='button',type='button',text='确定'),post_submit_verification_requirements=requirements))
    request=dict(schema='manual_republication_operator_request/v10',config=cfgref,action=flow.PUBLISH_ACTION,controls_result=oldresult,controls_receipt=receipt,
        declaration_contract=contract,submission_authority=config['authority'])
    reqref=put(x.run/'REQUEST_PUBLISH.json',request);prior=v5.read(v5.reference(x.run/'v5/PLAN.json'))['prior'];prior['file_selection_claim']=x.fileclaim
    planref=put(x.run/'publish_001/PLAN.json',dict(config=cfgref,request=reqref,prior=prior))
    action=put(x.run/'publish_001/ACTION_CLAIM.json',dict(schema='manual_republication_publish_action_claim/v10',plan=planref,config=cfgref,request=reqref,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=flow.PUBLISH_ACTION,
        navigation_allowed=False,file_selection_allowed=False,selections_allowed=1,confirmations_allowed=1,submissions_allowed=1))
    oldcmd=x.resource.session.cmd
    def cmd(kind,**kw):
        if kind=='screenshot':x.page.screenshot(path=kw['path'],full_page=False);return {'status':'ok'}
        result=oldcmd(kind,**kw)
        if kind=='click' and kw.get('selector')==flow.PUBLISH_SELECTOR and x.drop_publish:raise RuntimeError('synthetic lost publish acknowledgement')
        return result
    x.resource.session.cmd=cmd
    def claim_submission(actor,resource,cfg,req,preflight_ref):
        x.claim_calls+=1;preflight=v5.read(preflight_ref)
        assert preflight['action_claim']==action and preflight['declaration_confirmed'] and preflight['modal_closed']
        assert v5.read(preflight['settings'])['public_verified'] and v5.read(preflight['settings'])['immediate_verified']
        assert x.page.evaluate('()=>[window.statementChanges,window.confirmCount,window.publishCount]')==[1,1,0]
        return v5.once(x.run/'SUBMIT_CLAIM.json',dict(schema='private-once-submission',preflight=preflight_ref,allowed_publish_clicks=1))
    x.runtime_bridge=NS(reference=v5.reference,_read=v5.read,_once=v5.once,validate_live=lambda *args:None,claim_submission=claim_submission)
    x.config,x.request,x.out=config,request,x.run/'publish_001/publication'
    return x


def run(x):return flow.run_action(x.actor,x.resource,x.config,x.request,x.out,runtime_bridge=x.runtime_bridge)


def test_real_native_single_ai_confirmation_late_once_click_and_new_id_candidate(publish):
    x=publish;x.page.locator('#publish').evaluate("el=>{el.style.position='absolute';el.style.top='1800px';el.style.bottom='auto';window.originalPublishButton=el}")
    result=run(x)
    assert x.page.evaluate('()=>[window.statementChanges,window.confirmCount,window.publishCount]')==[1,1,1]
    assert result['submitted'] and result['publish_clicked'] and x.claim_calls==1
    assert result['status']=='submitted_verification_pending' and not result['post_verified'] and not result['native_publication_time_verified']
    assert [c['id'] for c in result['new_post_candidates']]==['7709999000000000001']
    assert v5.read(result['last_publish_probe'])['state']['settings']['immediate_verified']
    assert result['publish_scroll_performed'] and v5.read(result['publish_viewport_after_scroll'])['same']
    assert x.page.evaluate('()=>originalPublishButton===document.querySelector("#publish")')
    observed=v5.read(result['post_submit_observations'])['observations'][-1]
    assert 'safe_visible_body' in observed and 'visible_modals' in observed
    assert not any(a in {'goto','new_tab','fill','type_hashtag','set_input_files'} for a,_ in x.commands)


def test_unknown_public_setting_stops_before_any_selection_or_submit_claim(publish):
    x=publish;x.page.locator('#public').evaluate('el=>el.checked=false')
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_settings_unconfirmed' and x.claim_calls==0
    assert x.page.evaluate('()=>[window.statementChanges,window.confirmCount,window.publishCount]')==[0,0,0]
    assert not (x.run/'SUBMIT_CLAIM.json').exists() and (x.out/'INITIAL_PUBLIC_SETTINGS_AND_FORM.json').exists()


def test_publish_ack_unknown_keeps_once_claim_and_cannot_repeat_click(publish):
    x=publish;x.drop_publish=True
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_submission_unknown' and x.claim_calls==1
    assert (x.run/'SUBMIT_CLAIM.json').exists() and x.page.evaluate('()=>window.publishCount')==1
    before=len(x.commands)
    with pytest.raises((flow.DeclarationControlsBlocked,FileExistsError)):run(x)
    assert len(x.commands)==before and x.claim_calls==1 and x.page.evaluate('()=>window.publishCount')==1


def test_same_title_old_id_only_remains_verification_pending(publish):
    x=publish;x.page.evaluate('()=>window.oldOnly=true');result=run(x)
    assert result['submitted'] and result['new_post_candidates']==[] and result['post_verified'] is False
    assert x.page.evaluate('()=>window.publishCount')==1
