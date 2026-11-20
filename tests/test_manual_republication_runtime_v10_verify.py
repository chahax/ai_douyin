"""Exact new native candidate verification, original submitted chain preserved."""
import json
from pathlib import Path
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from test_manual_republication_runtime_v8 import put
import test_manual_republication_runtime_v10_metadata as support
from test_manual_republication_runtime_v10_publish import ACTUAL
from src.operations_accounts import manual_republication_runtime_v10 as bridge

METADATA_FLOW='''from datetime import datetime,timedelta,timezone
class DeclarationControlsBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True);plan=r._read(r._read(r.reference(outdir.parent/'ACTION_CLAIM.json'))['plan']);p=plan['prior'];epoch=int(p['submission_at'])+5
 item={'aweme_id':'7709219071845256488','canonical_url':'https://www.douyin.com/video/7709219071845256488','creation_second_window':{'start':epoch,'end_exclusive':epoch+1,'submission_at':p['submission_at'],'relation':'after_claim','precision_seconds':1},
 'full_metadata_match':True,'row_index':0,'post_verified':False,'numeric_duration_verified':False}
 projection=r._once(outdir/'PROJECTION.json',{'api_business_success':True,'rows':[{'aweme_id':item['aweme_id'],'create_time':epoch}],'candidates':[item]})
 return {'schema':'manual_republication_work_metadata_read/v10','action':r.METADATA_ACTION,'request_count':1,'api_business_success':True,'projection':projection,'candidates':[item],
 'input_performed':False,'selection_performed':False,'declaration_confirmed':False,'publish_clicked':False,'navigation_performed':False,'file_selected':False,'submitted':False,'post_verified':False,'numeric_duration_verified':False}
'''
VERIFY_FLOW='''class DeclarationControlsBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True);plan=r._read(r._read(r.reference(outdir.parent/'ACTION_CLAIM.json'))['plan']);p=plan['prior']
 with (outdir/'GOTO_ONCE').open('x') as f:f.write('private protocol only')
 native=r._once(outdir/'NATIVE.json',{'verified':True,'expected_post_id':p['post_id'],'url':p['canonical_url']})
 video=r._once(outdir/'VIDEO.json',{'origin':'https://www.douyin.com','path':'/video/'+p['post_id'],'visible_video_count':1,'duration':p['source_duration_seconds']+.016,'ready_state':4})
 image=outdir/'SCREENSHOT.png';image.write_bytes(b'private synthetic screenshot protocol')
 return {'schema':'manual_republication_public_verification/v10','action':r.VERIFY_ACTION,'post_id':p['post_id'],'canonical_url':p['canonical_url'],'canonical_navigations_count':1,'api_request_count':0,
 'post_verified':True,'numeric_duration_verified':True,'published_evidence':native,'video_probe':video,'screenshot':{'status':'saved','file':r.reference(image)},
 'input_performed':False,'selection_performed':False,'declaration_confirmed':False,'publish_clicked':False,'navigation_performed':True,'file_selected':False,'submitted':False}
'''


def test_exact_new_candidate_verify_caches_without_publication_or_second_navigation(v7_case,monkeypatch):
    monkeypatch.setattr(support,'FLOW',METADATA_FLOW);c=v7_case;support.test_submitted_metadata_is_once_read_only_and_rejects_different_endpoint(c,monkeypatch)
    folder=c.run/'manual_runtime_v10/readback_001';pmeta=bridge.reference(folder/'PLAN.json');metadata_status=bridge.status(pmeta);meta=bridge._read(metadata_status['result'])
    oldconfig=bridge._read(bridge._read(pmeta)['config']);oldreq=bridge._read(bridge._read(pmeta)['request']);prior=bridge._metadata_prior(oldconfig,oldreq)
    item=meta['readback']['candidates'][0];epoch=item['creation_second_window']['start'];iso=bridge.datetime.fromtimestamp(epoch,tz=bridge.timezone(bridge.timedelta(hours=8))).isoformat()
    paths=dict(bridge.SOURCE_PATHS);paths['runtime_v10'].write_text('# reviewed verification protocol runtime',encoding='utf8');paths['flow_v10'].write_text(VERIFY_FLOW,encoding='utf8')
    cfg=dict(oldconfig,sources={k:bridge.reference(p) for k,p in paths.items()});cfgref=put(c.run/'VERIFY_CONFIG.json',cfg)
    candidate=dict(schema='submitted_new_publication_candidate/v1',candidate=item,metadata_result=metadata_status['result'],metadata_receipt=metadata_status['receipt'],
        submission_claim=bridge.reference(bridge.SUBMIT_CLAIM),projection=meta['readback']['projection'],native_created_epoch=epoch,native_created_iso=iso,native_epoch_precision_seconds=1)
    cref=put(c.run/'NEW_CANDIDATE.json',candidate)
    intent=json.loads((ACTUAL/'VERIFY_NEW_PUBLICATION_INTENT.json').read_text(encoding='utf8'))
    intent.update(authority=cfg['authority'],operator_authority=cfg['operator_authority'],candidate=cref,metadata_result=metadata_status['result'],metadata_receipt=metadata_status['receipt'],
        submission_claim=bridge.reference(bridge.SUBMIT_CLAIM),metadata=cfg['metadata'],post_id=item['aweme_id'],canonical_url=item['canonical_url'],native_created_epoch=epoch,native_created_iso=iso)
    iref=put(c.run/'VERIFY_INTENT.json',intent);req=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action=bridge.VERIFY_ACTION,verification_intent=iref)
    before={ref['path']:Path(ref['path']).read_bytes() for ref in (metadata_status['result'],metadata_status['receipt'],intent['submission_claim'])}
    bad=put(c.run/'BAD_OLD_ID_INTENT.json',dict(intent,post_id=prior['excluded_old_post_ids'][0],canonical_url='https://www.douyin.com/video/'+prior['excluded_old_post_ids'][0]))
    with pytest.raises(ValueError,match='native_new_candidate'):bridge.prepare(cfgref,put(c.run/'BAD_VERIFY_REQUEST.json',dict(req,verification_intent=bad)),c.run/'manual_runtime_v10/verify_new_001')
    pref=bridge.prepare(cfgref,put(c.run/'VERIFY_REQUEST.json',req),c.run/'manual_runtime_v10/verify_new_001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=pref))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    status=bridge.status(pref);assert status['status']=='submitted_candidate_verified';assert bridge.install_if_armed()['status']==status['status']
    value=bridge._read(status['result']);assert value['external_publication_verified'] and value['new_submission_actions']==0 and value['published_at']==iso
    action=bridge._read(bridge.reference(Path(pref['path']).parent/'ACTION_CLAIM.json'))
    assert action['navigation_allowed'] and action['canonical_navigations_allowed']==1 and action['requests_allowed']==action['selections_allowed']==action['confirmations_allowed']==action['submissions_allowed']==0
    assert all(Path(path).read_bytes()==raw for path,raw in before.items())
    assert bridge.status(pmeta)['status']=='submitted_metadata_observed'
