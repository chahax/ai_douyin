"""Two real local DOM cases using the pinned original structural scope."""
import json
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v5 import draft,native,put
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v7 as v7
from src.operations_accounts import manual_republication_flow_v10 as flow
from src.shared import published_work_metadata_scope_v1 as helper
from src.shared import published_work_scope as old


POST='7709219071845256488'
CANONICAL='https://www.douyin.com/video/'+POST


def render(x,caption):
    x.page.set_content('''<div data-e2e="video-detail"><section id="work">
      <div data-e2e="player-container" class="video_7709219071845256488"><video style="width:320px;height:480px"></video></div>
      <div data-e2e="detail-video-info"><h1></h1></div><p>作者声明：内容由 AI 生成</p>
      </section></div><aside>unrelated full page text must not repair scoped caption</aside>
      <input type="password" value="private"><script>Object.defineProperty(document.querySelector('input'),'value',{get(){throw Error('private read')}})</script>''')
    x.page.locator('h1').evaluate('(el,text)=>el.textContent=text',caption)
    x.page.locator('video').evaluate('''el=>{for(const [key,val]of Object.entries({duration:120.682653,readyState:4,videoWidth:720,videoHeight:1284}))Object.defineProperty(el,key,{get:()=>val});
      Object.defineProperty(el,'src',{get(){throw Error('signed src read')}});Object.defineProperty(el,'currentSrc',{get(){throw Error('signed currentSrc read')}})}''')


@pytest.fixture
def caption_case(draft):
    x=draft;x.page.goto(CANONICAL)
    metadata=dict(x.metadata,title='一袋面包，看清这个家｜两分钟完整版',description='本视频含小说推广信息，推广者可能获得推广收益。画面与声音由AI生成，剧情虚构，非真实事件。根据《你敢惹我？我有六个反派儿子》的小说剧情制作。番茄小说搜索：从旧饭桌开始改命。')
    mref=put(x.run/'CAPTION_METADATA.json',metadata);operator=put(x.run/'OPERATOR.json',{})
    config=dict(x.config,metadata=mref,operator_authority=operator,sources=dict(x.config['sources'],flow_v5=v5.reference(v5.__file__),flow_v7=v5.reference(v7.__file__)))
    cfgref=put(x.run/'CAPTION_CONFIG.json',config)
    submission=put(x.run/'SUBMIT_CLAIM.json',dict(metadata=mref,media=metadata['media'],owner_id=x.actor.owner_id,generation=33,tab_id='same-tab'))
    candidate=put(x.run/'CANDIDATE.json',dict(candidate=dict(aweme_id=POST,canonical_url=CANONICAL),submission_claim=submission))
    base=v5.reference(old.__file__);snapshot=x.run/'SCOPE_BEFORE.py';snapshot.write_bytes(Path(old.__file__).read_bytes())
    refs={k:put(x.run/(k+'.json'),{}) for k in ('legacy_verification_result','legacy_verification_receipt','public_player_observed','legacy_scope_evidence','terminal_review')}
    intent=dict(schema='current_public_caption_read_intent/v1',draft_only=False,authority=config['authority'],operator_authority=operator,metadata=mref,
        candidate=candidate,submission_claim=submission,**refs,base_scope_source=base,base_scope_snapshot=v5.reference(snapshot),helper_ref=v5.reference(helper.__file__),
        post_id=POST,canonical_url=CANONICAL,scoped_reads_allowed=1,screenshots_allowed=1,navigations_allowed=0,api_requests_allowed=0,new_tabs_allowed=0,
        publications_allowed=0,selections_allowed=0,confirmations_allowed=0,files_allowed=0,fields_written_allowed=False,expected_duration_seconds=2896/24,duration_tolerance_seconds=.5)
    intentref=put(x.run/'CAPTION_INTENT.json',intent)
    request=dict(schema='manual_republication_operator_request/v10',config=cfgref,action=flow.CAPTION_ACTION,caption_read_intent=intentref)
    reqref=put(x.run/'CAPTION_REQUEST.json',request)
    planref=put(x.run/'caption_scope001/PLAN.json',dict(config=cfgref,request=reqref,prior=dict(source_duration_seconds=2896/24)))
    put(x.run/'caption_scope001/ACTION_CLAIM.json',dict(schema='manual_republication_caption_action_claim/v10',plan=planref,config=cfgref,request=reqref,
        owner_id=x.actor.owner_id,generation=33,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=flow.CAPTION_ACTION,
        navigation_allowed=False,canonical_navigations_allowed=0,file_selection_allowed=False,requests_allowed=0,selections_allowed=0,confirmations_allowed=0,submissions_allowed=0))
    oldcmd=x.resource.session.cmd
    def command(kind,**kw):
        if kind=='screenshot':x.commands.append((kind,dict(kw)));x.page.screenshot(path=kw['path'],full_page=False);return {'status':'ok'}
        return oldcmd(kind,**kw)
    x.resource.session.cmd=command
    x.config,x.metadata,x.request,x.intent=config,metadata,request,intent;x.out=x.run/'caption_scope001/caption'
    x.bridge=NS(reference=v5.reference,_read=v5.read,_once=v5.once,validate_live=lambda *args:None)
    return x


def text(metadata):return metadata['title']+'\n\u200b'+metadata['description']+'\u200b\n'+' '.join('#'+t for t in metadata['hashtags'])


def test_promo_first_frozen_full_caption_same_original_scope_passes_without_navigation(caption_case):
    x=caption_case;render(x,text(x.metadata))
    baseline=old.read_observed_work_scope(x.page,POST,x.metadata['title'])
    assert baseline['reason']=='native_caption_title_mismatch' and not baseline['verified']
    before=Path(old.__file__).read_bytes()
    result=flow.run_action(x.actor,x.resource,x.config,x.request,x.out,runtime_bridge=x.bridge)
    evidence=v5.read(result['published_evidence']);video=v5.read(result['video_probe'])
    assert result['post_verified'] and result['numeric_duration_verified'] and result['scoped_read_count']==1
    assert evidence['structure_verified'] and evidence['full_caption_verified'] and evidence['hashtags_verified'] and evidence['ai_label_visible'] and evidence['fiction_notice_visible']
    assert evidence['caption_text']==x.page.locator('h1').inner_text() and sorted(evidence['hashtag_tokens'])==sorted(x.metadata['hashtags'])
    assert video['duration']==120.682653 and video['video_width']==720 and video['video_height']==1284 and video['visible_video_count']==1
    assert result['canonical_navigations_count']==result['api_request_count']==0 and result['screenshot']['status']=='saved'
    assert [kind for kind,_ in x.commands]==['evaluate','screenshot']
    assert not any(result[k] for k in ('input_performed','selection_performed','declaration_confirmed','publish_clicked','navigation_performed','file_selected','submitted','fields_written'))
    assert Path(old.__file__).read_bytes()==before
    def refs(value):
        if isinstance(value,dict):
            if set(value)=={'path','sha256'}:assert v5.reference(value['path'])==value
            else:
                for item in value.values():refs(item)
        elif isinstance(value,list):
            for item in value:refs(item)
    refs(result)


def test_wrong_description_or_tag_cannot_be_repaired_by_global_body_and_retains_scoped_raw(caption_case):
    x=caption_case
    for bad in (text(x.metadata).replace('推广者可能获得推广收益','没有推广收益'),text(x.metadata).replace('#AI生成','#其他标签')):
        render(x,bad);x.page.locator('aside').evaluate('(el,text)=>el.textContent=text',text(x.metadata))
        evidence=helper.inspect_current_metadata_scope(x.page,POST,x.metadata,base_scope_source=x.intent['base_scope_source'],base_scope_snapshot=x.intent['base_scope_snapshot'],
            expected_duration_seconds=2896/24,duration_tolerance_seconds=.5)
        assert evidence['structure_verified'] and evidence['numeric_duration_verified'] and not evidence['verified'] and not evidence['full_caption_verified']
        assert evidence['caption_text']==x.page.locator('h1').inner_text() and evidence['reason']=='frozen_full_caption_mismatch' and not evidence['whole_body_caption_fallback']
