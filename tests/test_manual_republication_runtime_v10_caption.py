"""Current-caption reader protocol; immutable legacy rejection is retained."""
import json
from pathlib import Path
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from test_manual_republication_runtime_v8 import put
from test_manual_republication_runtime_v10_verify import test_exact_new_candidate_verify_caches_without_publication_or_second_navigation as build_verify
from test_manual_republication_runtime_v10_publish import ACTUAL
from src.operations_accounts import manual_republication_runtime_v10 as bridge

FLOW='''class DeclarationControlsBlocked(ValueError):pass
SAFE_REASONS=frozenset()
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True);plan=r._read(r._read(r.reference(outdir.parent/'ACTION_CLAIM.json'))['plan']);p=plan['prior']
 with (outdir/'SCOPE_ONCE').open('x') as f:f.write('private read-only protocol')
 native=r._once(outdir/'NATIVE.json',dict(verified=True,full_caption_verified=True,hashtags_verified=True,ai_label_visible=True,fiction_notice_visible=True,expected_post_id=p['post_id'],url=p['canonical_url']))
 video=r._once(outdir/'VIDEO.json',dict(origin='https://www.douyin.com',path='/video/'+p['post_id'],visible_video_count=1,duration=p['source_duration_seconds']+.016,ready_state=4))
 image=outdir/'SCREENSHOT.png';image.write_bytes(b'private synthetic screenshot protocol')
 return dict(schema='manual_republication_public_caption/v10',action=r.CAPTION_ACTION,post_id=p['post_id'],canonical_url=p['canonical_url'],scoped_read_count=1,canonical_navigations_count=0,api_request_count=0,
 published_evidence=native,video_probe=video,screenshot=dict(status='saved',file=r.reference(image)),post_verified=True,numeric_duration_verified=True,
 input_performed=False,selection_performed=False,declaration_confirmed=False,publish_clicked=False,file_selected=False,submitted=False,navigation_performed=False)
'''


def test_current_caption_exact_scope_preserves_legacy_false_and_original_submission(v7_case,monkeypatch):
    c=v7_case;build_verify(c,monkeypatch)
    folder=c.run/'manual_runtime_v10/verify_new_001';oldplan=bridge.reference(folder/'PLAN.json');oldstatus=bridge.status(oldplan);result=bridge._read(oldstatus['result'])
    oldconfig=bridge._read(bridge._read(oldplan)['config']);prior=bridge._read(oldplan)['prior'];video=bridge._read(result['verification']['video_probe'])
    legacy=dict(verified=False,reason='native_caption_title_mismatch',scope_kind='observed_video_detail',expected_post_id=prior['post_id'],url=prior['canonical_url'],
        player_id_matches=True,detail_nodes=1,player_nodes=1,caption_nodes=1)
    legacy_ref=put(folder/'verification/LEGACY_FALSE.json',legacy)
    result.update(status='submitted_candidate_not_verified',external_publication_verified=False)
    result['verification'].update(post_verified=False,published_evidence=legacy_ref)
    result_ref=put(Path(oldstatus['result']['path']),result);receipt=bridge._read(oldstatus['receipt']);receipt['result']=result_ref;receipt_ref=put(Path(oldstatus['receipt']['path']),receipt)
    player=dict(schema='native_public_player_observed/v1',verification_result=result_ref,verification_receipt=receipt_ref,strict_scope_evidence=legacy_ref,native_probe=result['verification']['video_probe'],
        numeric_duration_verified=True,full_caption_scope_verified=False,post_id=prior['post_id'],canonical_url=prior['canonical_url'],native_created_epoch=prior['native_created_epoch'],
        published_at=prior['native_created_iso'],duration_seconds=video['duration'])
    player_ref=put(c.run/'PLAYER_OBSERVED.json',player)
    paths=dict(bridge.SOURCE_PATHS);paths['runtime_v10'].write_text('# reviewed current-caption runtime protocol',encoding='utf8');paths['flow_v10'].write_text(FLOW,encoding='utf8')
    shared=bridge.ROOT/'src/shared';shared.mkdir(parents=True,exist_ok=True)
    helper=shared/'published_work_metadata_scope_v1.py';helper.write_text('# pinned explicit-metadata helper protocol',encoding='utf8')
    base=shared/'published_work_scope.py';base.write_text('# unchanged old default scope protocol',encoding='utf8');snapshot=c.run/'BASE_SCOPE_SNAPSHOT.py';snapshot.write_bytes(base.read_bytes())
    cfg=dict(oldconfig,sources={k:bridge.reference(p) for k,p in paths.items()});cfgref=put(c.run/'CAPTION_CONFIG.json',cfg)
    intent=json.loads((ACTUAL/'CURRENT_PUBLIC_CAPTION_READ_INTENT_DRAFT.json').read_text(encoding='utf8'))
    intent.update(authority=cfg['authority'],operator_authority=cfg['operator_authority'],metadata=cfg['metadata'],submission_claim=bridge.reference(bridge.SUBMIT_CLAIM),candidate=prior['candidate'],
        legacy_verification_result=result_ref,legacy_verification_receipt=receipt_ref,legacy_scope_evidence=legacy_ref,public_player_observed=player_ref,
        terminal_review=put(c.run/'TERMINAL_PROTOCOL_REVIEW.json',dict(scope='private synthetic protocol only')),helper_ref=bridge.reference(helper),planned_helper_path=str(helper),
        base_scope_source=bridge.reference(base),base_scope_snapshot=bridge.reference(snapshot),post_id=prior['post_id'],canonical_url=prior['canonical_url'],draft_only=False)
    iref=put(c.run/'CAPTION_INTENT.json',intent);req=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action=bridge.CAPTION_ACTION,caption_read_intent=iref)
    before={ref['path']:Path(ref['path']).read_bytes() for ref in (result_ref,receipt_ref,legacy_ref,intent['submission_claim'],intent['base_scope_source'])}
    draft=put(c.run/'DRAFT_CAPTION_INTENT.json',dict(intent,draft_only=True))
    with pytest.raises(ValueError,match='final_scoped_helper'):bridge.prepare(cfgref,put(c.run/'BAD_CAPTION_REQUEST.json',dict(req,caption_read_intent=draft)),c.run/'manual_runtime_v10/caption_scope001')
    plan=bridge.prepare(cfgref,put(c.run/'CAPTION_REQUEST.json',req),c.run/'manual_runtime_v10/caption_scope001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=plan))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    status=bridge.status(plan);assert status['status']=='current_caption_verified';assert bridge.install_if_armed()['status']==status['status']
    value=bridge._read(status['result']);assert value['external_publication_verified'] and value['full_metadata_verified'] and value['caption']['full_metadata_verified']
    assert value['legacy_scope_evidence']==legacy_ref and value['scoped_evidence']==value['caption']['published_evidence']
    action=bridge._read(bridge.reference(Path(plan['path']).parent/'ACTION_CLAIM.json'))
    assert action['scoped_reads_allowed']==action['screenshots_allowed']==1
    assert action['canonical_navigations_allowed']==action['requests_allowed']==action['selections_allowed']==action['confirmations_allowed']==action['submissions_allowed']==0
    assert not action['navigation_allowed']
    assert all(Path(path).read_bytes()==raw for path,raw in before.items())
    assert bridge.status(oldplan)['status']=='submitted_candidate_not_verified'
