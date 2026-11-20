"""One submitted-bound, no-publication metadata-read protocol regression."""
import json
from pathlib import Path
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from test_manual_republication_runtime_v8 import put
from test_manual_republication_runtime_v10_selected import test_selected_continuation_never_replays_original_choice_or_publication as build_submitted
from test_manual_republication_runtime_v10_publish import ACTUAL
from src.operations_accounts import manual_republication_runtime_v10 as bridge

FLOW='''class DeclarationControlsBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True)
 with (outdir/'GET_ONCE').open('x') as f:f.write('read protocol, no network')
 projection=r._once(outdir/'PROJECTION.json',{'api_business_success':True,'rows':[],'candidates':[],'numeric_duration_verified':False,'post_verified':False})
 return {'schema':'manual_republication_work_metadata_read/v10','action':r.METADATA_ACTION,'request_count':1,'api_business_success':True,'projection':projection,'candidates':[],
 'input_performed':False,'selection_performed':False,'declaration_confirmed':False,'publish_clicked':False,'navigation_performed':False,'file_selected':False,'submitted':False,
 'post_verified':False,'numeric_duration_verified':False}
'''


def test_submitted_metadata_is_once_read_only_and_rejects_different_endpoint(v7_case,monkeypatch):
    c=v7_case;build_submitted(c,monkeypatch,'success')
    folder=c.run/'manual_runtime_v10/continuation_selected_001';oldplan=bridge.reference(folder/'PLAN.json');oldvalue=bridge.status(oldplan);result=bridge._read(oldvalue['result'])
    oldrequest=bridge._read(bridge._read(oldplan)['request']);oldconfig=bridge._read(oldrequest['config'])
    paths=dict(bridge.SOURCE_PATHS)
    paths['runtime_v10'].write_text('# reviewed readback runtime protocol',encoding='utf8');paths['flow_v10'].write_text(FLOW,encoding='utf8')
    cfg=dict(oldconfig,sources={k:bridge.reference(p) for k,p in paths.items()});cfgref=put(c.run/'READBACK_CONFIG.json',cfg)
    intent=json.loads((ACTUAL/'SUBMITTED_METADATA_READ_INTENT.json').read_text(encoding='utf8'))
    requirements=bridge._read(bridge._read(oldrequest['declaration_contract'])['post_submit_verification_requirements'])
    intent.update(authority=cfg['authority'],operator_authority=cfg['operator_authority'],publication_result=oldvalue['result'],publication_receipt=oldvalue['receipt'],
        submission_claim=bridge.reference(bridge.SUBMIT_CLAIM),metadata=cfg['metadata'],excluded_old_post_ids=requirements['excluded_old_post_ids'],
        terminal_review=put(c.run/'SUBMITTED_PROTOCOL_REVIEW.json',{'scope':'private synthetic protocol only'}))
    intentref=put(c.run/'READBACK_INTENT.json',intent)
    req=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action=bridge.METADATA_ACTION,metadata_read_intent=intentref)
    before={ref['path']:Path(ref['path']).read_bytes() for ref in (oldvalue['result'],oldvalue['receipt'],intent['submission_claim'],result['claim'])}
    bad=put(c.run/'BAD_ENDPOINT_INTENT.json',dict(intent,url='https://creator.douyin.com/not-authorized'))
    with pytest.raises(ValueError,match='original_submitted_once'):bridge.prepare(cfgref,put(c.run/'BAD_REQUEST.json',dict(req,metadata_read_intent=bad)),c.run/'manual_runtime_v10/readback_001')
    reqref=put(c.run/'METADATA_REQUEST.json',req)
    with pytest.raises(ValueError,match='unique_read_slot'):bridge.prepare(cfgref,reqref,c.run/'manual_runtime_v10/readback_002')
    plan=bridge.prepare(cfgref,reqref,c.run/'manual_runtime_v10/readback_001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=plan))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    status=bridge.status(plan);assert status['status']=='submitted_metadata_observed'
    output=bridge._read(status['result']);assert output['new_submission_actions']==0 and not output['external_publication_verified']
    assert bridge.install_if_armed()['status']=='submitted_metadata_observed'
    claim=bridge._read(bridge.reference(Path(plan['path']).parent/'ACTION_CLAIM.json'))
    assert claim['requests_allowed']==1 and claim['selections_allowed']==claim['confirmations_allowed']==claim['submissions_allowed']==0
    assert all(Path(path).read_bytes()==raw for path,raw in before.items())
    assert bridge.status(oldplan)['status']=='publication_submitted_verification_pending'
