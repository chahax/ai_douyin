"""Native existing strict reader + numeric video getter on isolated local DOM."""
import json
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import draft,native,put
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v7 as v7
from src.operations_accounts import manual_republication_flow_v10 as flow
from src.platform_adapter.publish_verification import inspect_published_video


@pytest.fixture
def verify(draft):
    x=draft;post_id='7709219071845256488';canonical='https://www.douyin.com/video/'+post_id
    operator=put(x.run/'OPERATOR.json',{})
    config=dict(x.config,operator_authority=operator,sources=dict(x.config['sources'],flow_v5=v5.reference(v5.__file__),flow_v7=v5.reference(v7.__file__)))
    cfgref=put(x.run/'CONFIG_VERIFY.json',config)
    submission=put(x.run/'SUBMIT_CLAIM.json',dict(metadata=config['metadata'],media=x.metadata['media'],owner_id=x.actor.owner_id,generation=33,tab_id='same-tab'))
    candidate=put(x.run/'CANDIDATE.json',dict(candidate=dict(aweme_id=post_id,canonical_url=canonical),submission_claim=submission))
    intent=dict(schema='verify_submitted_candidate_intent/v1',authority=config['authority'],operator_authority=operator,candidate=candidate,
        metadata_result=put(x.run/'METADATA_RESULT.json',{}),metadata_receipt=put(x.run/'METADATA_RECEIPT.json',{}),submission_claim=submission,metadata=config['metadata'],
        post_id=post_id,canonical_url=canonical,expected_duration_seconds=2896/24,duration_tolerance_seconds=.5,canonical_navigations_allowed=1,
        new_tabs_allowed=0,publications_allowed=0,selections_allowed=0,confirmations_allowed=0,files_allowed=0,fields_written_allowed=False,
        reuse_existing_strict_published_work_reader=True,required_ai_label='内容由AI生成',require_fiction_notice=True)
    intentref=put(x.run/'VERIFY_INTENT.json',intent)
    request=dict(schema='manual_republication_operator_request/v10',config=cfgref,action=flow.VERIFY_ACTION,verification_intent=intentref)
    reqref=put(x.run/'VERIFY_REQUEST.json',request)
    planref=put(x.run/'verify_new_001/PLAN.json',dict(config=cfgref,request=reqref,prior=dict(source_duration_seconds=2896/24)))
    put(x.run/'verify_new_001/ACTION_CLAIM.json',dict(schema='manual_republication_verify_action_claim/v10',plan=planref,config=cfgref,request=reqref,
        owner_id=x.actor.owner_id,generation=33,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=flow.VERIFY_ACTION,
        navigation_allowed=True,canonical_navigations_allowed=1,file_selection_allowed=False,requests_allowed=0,selections_allowed=0,confirmations_allowed=0,submissions_allowed=0))
    oldcmd=x.resource.session.cmd
    def command(kind,**kw):
        if kind=='goto':
            x.commands.append((kind,dict(kw)));assert kw['url']==canonical and kw['wait_until']=='commit'
            x.page.goto(kw['url'],wait_until=kw['wait_until'],timeout=kw['timeout'])
            x.page.set_content('<article><video style="width:320px;height:480px"></video><figcaption></figcaption><p>作者声明：内容由AI生成</p></article>')
            x.page.locator('figcaption').evaluate('(el,data)=>el.textContent=data',x.metadata['title']+'\n'+x.metadata['description']+' '+ ' '.join('#'+t for t in x.metadata['hashtags']))
            x.page.locator('video').evaluate("""el=>{Object.defineProperty(el,'duration',{get:()=>120.683});Object.defineProperty(el,'readyState',{get:()=>3});
              Object.defineProperty(el,'videoWidth',{get:()=>736});Object.defineProperty(el,'videoHeight',{get:()=>1312});Object.defineProperty(el,'src',{get(){throw Error('signed src read')}})}""")
            return {'url':x.page.url}
        if kind=='inspect_published_video':
            x.commands.append((kind,dict(kw)))
            evidence=inspect_published_video(x.page,kw['post_id'],ai_required=kw['ai_required'],fiction_required=kw['fiction_required'],required_hashtags=kw['required_hashtags'],expected_title=kw['expected_title'])
            return {'evidence':evidence}
        if kind=='screenshot':x.commands.append((kind,dict(kw)));x.page.screenshot(path=kw['path'],full_page=False);return {'status':'ok'}
        return oldcmd(kind,**kw)
    x.resource.session.cmd=command
    x.config,x.request,x.out=config,request,x.run/'verify_new_001/verification';x.intent=intent
    x.bridge=NS(reference=v5.reference,_read=v5.read,_once=v5.once,validate_live=lambda *args:None)
    return x


def run(x):return flow.run_action(x.actor,x.resource,x.config,x.request,x.out,runtime_bridge=x.bridge)


def test_original_strict_reader_and_unique_native_video_duration_pass_without_src_or_extra_navigation(verify):
    x=verify;result=run(x)
    assert result['post_verified'] and result['numeric_duration_verified'] and result['status']=='public_work_verified'
    evidence=v5.read(result['published_evidence']);probe=v5.read(result['video_probe'])
    assert evidence['verified'] and evidence['expected_post_id']==x.intent['post_id']
    assert probe['duration']==120.683 and probe['video_width']==736 and probe['video_height']==1312 and probe['ready_state']==3 and not probe['src_read']
    assert result['canonical_navigations_count']==1 and result['api_request_count']==0
    assert len([a for a,_ in x.commands if a=='goto'])==1 and result['screenshot']['status']=='saved'
    assert not any(a in {'api_request','new_tab','fill','click','set_input_files'} for a,_ in x.commands)
    assert not result['public_author_uid_inferred_from_author_id'] and not result['full_audio_visual_quality_verified']


def test_old_frozen_post_url_is_rejected_before_any_native_rpc(verify):
    x=verify;old='7709043480894524722'
    ref=put(x.run/'WRONG_OLD_INTENT.json',dict(x.intent,post_id=old,canonical_url='https://www.douyin.com/video/'+old))
    x.request=dict(x.request,verification_intent=ref)
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_request_invalid' and x.commands==[]
