"""One native-shaped GET, bounded projection only; no browser/network/DB."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS

import pytest
from src.operations_accounts import manual_republication_flow_v1 as v1
from src.operations_accounts import manual_republication_flow_v5 as v5
from src.operations_accounts import manual_republication_flow_v7 as v7
from src.operations_accounts import manual_republication_flow_v10 as flow


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return v5.reference(path)


@pytest.fixture
def readback(tmp_path):
    run=tmp_path/'run';run.mkdir();media=run/'original.mp4';media.write_bytes(b'unchanged source fixture')
    binding=NS(account_uuid='account:test',account_key='novel-test',platform_identity_key='public_uid:75891235130',
        browser_environment_key='original',browser_profile_dir='private',storage_state_path='unused',confirmed_by='user',created_at='bound',public_uid='75891235130')
    profile=NS(account_uuid=binding.account_uuid,profile_version=1);version=v1._binding_version(NS(binding=binding,profile=profile))
    authority=put(run/'AUTH.json',dict(media=v5.reference(media),expected_public_uid=binding.public_uid));operator=put(run/'OPERATOR.json',{})
    metadata=dict(schema='manual_republication_metadata/v1',account_uuid=binding.account_uuid,account_key=binding.account_key,media=v5.reference(media),
        title='两分钟完整文案',description='推广信息；画面声音由AI生成。剧情虚构，非真实事件。',hashtags=['小说推文','穿书','小说剧情','AI短剧','AI生成'],ai_generated=True,fictional_story=True,visibility='public')
    metaref=put(run/'METADATA.json',metadata);submitted=time.time()-5
    submission=put(run/'SUBMIT_CLAIM.json',dict(metadata=metaref,media=metadata['media'],owner_id='same-owner',generation=33,tab_id='same-tab',at_epoch=submitted))
    intent=put(run/'READ_INTENT.json',dict(schema='submitted_metadata_read_intent/v1',authority=authority,operator_authority=operator,metadata=metaref,
        publication_result=put(run/'PUBLICATION_RESULT.json',{}),publication_receipt=put(run/'PUBLICATION_RECEIPT.json',{}),submission_claim=submission,
        terminal_review=put(run/'TERMINAL_REVIEW.json',{}),method='GET',url=flow.WORK_LIST_URL,request_limit=1,headers={},request_body_allowed=False,
        navigation_allowed=False,new_tab_allowed=False,publication_actions_allowed=0,fields_written_allowed=False,excluded_old_post_ids=['7709043480894524722','7708948487446056192']))
    paths=dict(flow_v1=Path(v1.__file__),flow_v5=Path(v5.__file__),flow_v7=Path(v7.__file__),flow_v2=flow.ROOT/'src/operations_accounts/manual_republication_flow_v2.py',
        publish_workflow=flow.ROOT/'src/platform_adapter/publish_workflow.py',upload_diagnostic=flow.ROOT/'src/platform_adapter/upload_surface_diagnostic.py')
    config=dict(account_id=binding.account_uuid,account_key=binding.account_key,owner_id='same-owner',generation=33,tab_id='same-tab',
        binding_version=version,authority=authority,operator_authority=operator,metadata=metaref,sources={k:v5.reference(p) for k,p in paths.items()})
    cfgref=put(run/'CONFIG.json',config);request=dict(schema='manual_republication_operator_request/v10',config=cfgref,action=flow.METADATA_ACTION,metadata_read_intent=intent)
    reqref=put(run/'REQUEST.json',request);pref=put(run/'readback_001/PLAN.json',dict(config=cfgref,request=reqref,prior=dict(prior_submission_claim=submission,submission_at=submitted)))
    put(run/'readback_001/ACTION_CLAIM.json',dict(schema='manual_republication_metadata_action_claim/v10',plan=pref,config=cfgref,request=reqref,
        owner_id='same-owner',generation=33,tab_id='same-tab',actor_thread_id=threading.get_ident(),action=flow.METADATA_ACTION,
        navigation_allowed=False,file_selection_allowed=False,selections_allowed=0,confirmations_allowed=0,submissions_allowed=0,requests_allowed=1))
    caption=metadata['title']+'\n'+metadata['description']+' '+ ' '.join('#'+t for t in metadata['hashtags'])
    def row(post_id):return dict(aweme_id=post_id,item_title=metadata['title'],caption=caption,create_time=math.ceil(submitted)+1,
        author=dict(uid='internal-not-public-uid'),status=dict(is_private=False,private_status=0),video=dict(duration=120666,play_addr=dict(url_list=['https://signed.example/private?token=SECRET'])))
    data=dict(status_code='0',aweme_list=[row('7709043480894524722'),row('7709999000000000001'),row(7709999000000000002)])
    state=NS(calls=[],fail=False,body=json.dumps(data,ensure_ascii=False))
    class Owner:
        _proc=NS(poll=lambda:None)
        def get_page(self,tab):assert tab=='same-tab';return page
        def cmd(self,kind,**kw):
            state.calls.append((kind,kw));assert kind=='api_request'
            assert kw==dict(tab_id='same-tab',method='GET',url=flow.WORK_LIST_URL,headers={},timeout=30000)
            if state.fail:raise TimeoutError('signed response channel private')
            return dict(response=dict(status=200,body=state.body,text=state.body,headers={'cookie':'SECRET'}))
    owner=Owner()
    class Page:
        _session=owner;tab_id='same-tab'
        def _cmd(self,kind,**kw):return owner.cmd(kind,tab_id=self.tab_id,**kw)
    page=Page();actor=NS(owner_id='same-owner',generation=33)
    resource=NS(session=owner,runtime=NS(bindings=NS(get=lambda _:binding),profiles=NS(get=lambda _:profile)))
    bridge=NS(reference=v5.reference,_read=v5.read,_once=v5.once,validate_live=lambda *args:None)
    return NS(run=run,actor=actor,resource=resource,config=config,request=request,metadata=metadata,submitted=submitted,state=state,
        bridge=bridge,out=run/'readback_001/readback')


def run(x):return flow.run_action(x.actor,x.resource,x.config,x.request,x.out,runtime_bridge=x.bridge)


def test_single_get_projects_old_and_new_rows_without_signed_urls_and_keeps_epoch_units(readback):
    x=readback;result=run(x);projection=v5.read(result['projection'])
    assert result['request_count']==1 and result['api_business_success'] and len(x.state.calls)==1
    assert len(projection['rows'])==3 and projection['business_status']=='0'
    assert [c['aweme_id'] for c in result['candidates']]==['7709999000000000001','7709999000000000002']
    assert projection['rows'][0]['match_reasons']==['excluded_old_post_id']
    assert projection['rows'][2]['aweme_id']=='7709999000000000002'  # Python parsed 19-digit JSON int is exact.
    assert projection['rows'][1]['numeric_duration_fields']==[dict(field='video.duration',value=120666,unit='unknown_not_converted')]
    assert result['body_sha256']==hashlib.sha256(x.state.body.encode('utf8')).hexdigest()
    persisted=''.join(p.read_text(encoding='utf8') for p in x.out.glob('*.json'))
    assert all(secret not in persisted for secret in ('SECRET','signed.example','url_list','internal-not-public-uid'))
    assert not result['post_verified'] and not result['numeric_duration_verified'] and not result['author_uid_equated_to_public_uid']
    invalid=flow.project_work_metadata(dict(status=503,body='{"status_code":0,"aweme_list":[]}'),x.metadata,x.submitted,time.time(),set())
    assert not invalid['api_business_success'] and invalid['response_state']=='http_not_success' and invalid['body_sha256']


def test_native_read_timeout_does_not_retry_or_reenter_same_intent(readback):
    x=readback;x.state.fail=True
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_metadata_read_unknown' and len(x.state.calls)==1
    failure=v5.read(error.value.diagnostics_ref);assert failure['request_count']==1 and not failure['automatic_request_retry']
    with pytest.raises(flow.DeclarationControlsBlocked) as error:run(x)
    assert error.value.code=='controls_request_already_dispatched' and len(x.state.calls)==1
