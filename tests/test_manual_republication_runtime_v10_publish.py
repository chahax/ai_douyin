"""Exact manual publication protocol with private actor/stores, no platform."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
from test_manual_republication_runtime_v8 import put
from test_manual_republication_runtime_v9 import test_zero_click_successor_preserves_records_and_same_read_capability as build_v9
from src.operations_accounts import manual_republication_runtime_v10 as bridge

ACTUAL_ROOT=Path(__file__).resolve().parents[1]
ACTUAL=ACTUAL_ROOT/'data/production_trials/fanqie_declared_republication_20261117_v1'
READ_BODY='''import json
class DeclarationControlsBlocked(ValueError):pass
SAFE_REASONS=frozenset()
CONTROLS=CONTROL_LITERAL
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True)
 controls=r._once(outdir/'CURRENT_DECLARATION_CONTROLS.json',CONTROLS)
 return {'schema':'manual_republication_declaration_controls/v10','action':r.ACTION,'action_claim':r.reference(outdir.parent/'ACTION_CLAIM.json'),
 'render_complete':True,'modal_controls':controls,'same_tab':config['tab_id'],'input_performed':False,'selection_performed':False,'declaration_confirmed':False,
 'publish_clicked':False,'navigation_performed':False,'file_selected':False,'submitted':False}
'''
PUBLISH_BODY='''import json,time
class DeclarationControlsBlocked(ValueError):
 def __init__(self,code):self.code=code;super().__init__(code)
SAFE_REASONS=frozenset({'publish_settings_unconfirmed'})
MODE=MODE_LITERAL
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True);action=r.reference(outdir.parent/'ACTION_CLAIM.json');plan=r._read(r._read(action)['plan']);p=plan['prior'];m=r._read(config['metadata'])
 if MODE=='settings_unknown':
  r._once(outdir/'SUBMISSION_FAILURE.json',{'phase':'settings_probe','selection_performed':False,'publish_click_dispatched':False,'submission_claimed':False})
  raise DeclarationControlsBlocked('publish_settings_unconfirmed')
 form=r._once(outdir/'FORM.json',{'title':{'content':m['title']},'description_core':'\\u200b'+m['description'],'description_exact':True,'hashtag_tokens':m['hashtags']})
 settings=r._once(outdir/'SETTINGS.json',{'public_verified':MODE!='bad_settings','immediate_verified':True})
 rows=[json.loads(line) for line in open(p['upload_journal']['path'],encoding='utf8') if line.strip()]
 proof=[e['proof'] for e in rows if e.get('stage')=='upload_check_transition_observed'][-1]
 proof=dict(proof,schema='upload_check_transition/v2',selection_nonce=p['selection_nonce'])
 fence=r._once(outdir/'FENCE.json',{'native_upload_proof':proof,'video':{'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video','visible_video_count':1,'duration':p['source_duration_seconds'],'ready_state':4}})
 preflight=r._once(outdir/'PUBLISH_PREFLIGHT.json',{'schema':'manual_republication_publish_preflight/v10','action_claim':action,'declaration_contract':request['declaration_contract'],
  'file_selection_claim':p['file_selection_claim'],'metadata':config['metadata'],'observed_at':time.time(),'selected_label':p['selected_label'],'declaration_confirmed':True,'modal_closed':True,
  'settings':settings,'form_readback':form,'draft_fence':fence,'publish_button':{'unique_count':1,'text':'发布','visible':True,'enabled':True,'center_hit':True}})
 r._once(outdir/'SUBMISSION_FAILURE.json',{'phase':'publish_boundary','selection_performed':True,'declaration_confirmed':True,'publish_click_dispatched':MODE=='lost_ack'})
 try:claim=r.claim_submission(actor,resource,config,request,preflight)
 except Exception as e:
  r._once(outdir/'HELPER_REJECTION.json',{'error_type':type(e).__name__,'reason':str(e)})
  raise
 with (outdir/'PUBLISH_RPC_ONCE').open('x') as f:f.write('protocol only')
 if MODE=='lost_ack':raise RuntimeError('lost native acknowledgement')
 post=r._once(outdir/'POST_SUBMIT.json',{'old_title_alone_does_not_verify_new_link':True,'new_post_candidates':[]})
 return {'schema':'manual_republication_publish_once/v10','action':r.PUBLISH_ACTION,'status':'submitted_verification_pending',
 'publish_clicked':True,'submitted':True,'selection_performed':True,'declaration_confirmed':True,'navigation_performed':False,'file_selected':False,
 'submission_claim':claim,'preflight':preflight,'post_submit_observations':post,'new_post_candidates':[]}
'''


@pytest.fixture
def publication(v7_case,monkeypatch,request):
    c=v7_case;build_v9(c,monkeypatch);v9=bridge.base
    p9=v9.reference(c.run/'inspect_v9/PLAN.json');r9=v9.status(p9)['result'];result=v9._read(r9);options_ref=result['inspection']['options_inventory']
    options=v9._read(options_ref);options.update(schema='manual_native_declaration_options/v9',location={'origin':'https://creator.douyin.com','path':'/creator-micro/content/post/video'},visible_text='请选择声明类型（单选）')
    options_ref=put(Path(options_ref['path']),options)
    events=put(c.run/'inspect_v9/inspection/DISCLOSURE_EVENTS.json',dict(allowed_clicks=1,blocked_events=0))
    result['inspection'].update(options_inventory=options_ref,disclosure_events=events,action=v9.ACTION,schema='manual_republication_declaration_inspection/v9',
        same_tab=c.config['tab_id'],scroll_performed=True,trigger_click_count=1,metadata_readback_matched=True,options_observed=True)
    result['inspection'].update({k:False for k in ('submitted','declaration_selected','confirmed','navigation_performed','file_selected','fields_written','publication_ready')})
    r9=put(Path(r9['path']),result);receipt_path=c.run/'inspect_v9/RESULT_BINDING.json';rec=v9._read(v9.reference(receipt_path));rec['result']=r9;put(receipt_path,rec)
    monkeypatch.setattr(bridge,'ROOT',v9.ROOT);monkeypatch.setattr(bridge,'RUN',c.run);monkeypatch.setattr(bridge,'ARM',c.run/'runtime_v10/ARM.json');monkeypatch.setattr(bridge,'SUBMIT_CLAIM',c.run/'SUBMIT_CLAIM.json')
    controls=json.loads((ACTUAL/'manual_runtime_v10/inspect_001/inspection/CURRENT_DECLARATION_CONTROLS.json').read_text(encoding='utf8'))
    paths=dict(v9.SOURCE_PATHS)
    for key in ('runtime_v10','flow_v10'):
        path=v9.ROOT/'src/operations_accounts'/f'{key}.py';path.write_text(READ_BODY.replace('CONTROL_LITERAL',repr(controls)) if key=='flow_v10' else '# sealed read-stage protocol runtime',encoding='utf8');paths[key]=path
    monkeypatch.setattr(bridge,'SOURCE_PATHS',paths)
    cfg1=dict(v9._read(v9._read(p9)['config']),schema=bridge.CONFIG_SCHEMA,sources={k:bridge.reference(p) for k,p in paths.items()})
    cfg1ref=put(c.run/'READ_CONFIG.json',cfg1);readreq=put(c.run/'READ_REQUEST.json',dict(schema=bridge.REQUEST_SCHEMA,config=cfg1ref,action=bridge.ACTION,prior_result=r9,prior_receipt=bridge.reference(receipt_path),options_inventory=options_ref))
    readplan=bridge.prepare(cfg1ref,readreq,c.run/'controls_001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=readplan))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    controls_result=bridge.status(readplan)['result'];controls_value=bridge._read(controls_result);controls_receipt=bridge.reference(c.run/'controls_001/RESULT_BINDING.json')
    mode=request.param;paths['runtime_v10'].write_text('# separately reviewed writer-stage protocol runtime',encoding='utf8')
    paths['flow_v10'].write_text(PUBLISH_BODY.replace('MODE_LITERAL',repr(mode)),encoding='utf8')
    cfg=dict(cfg1,sources={k:bridge.reference(p) for k,p in paths.items()});cfgref=put(c.run/'PUBLISH_CONFIG.json',cfg);authority=bridge._read(cfg['authority']);metadata=bridge._read(cfg['metadata'])
    priority=json.loads((ACTUAL/'NATIVE_STATEMENT_PRIORITY_DECISION.json').read_text(encoding='utf8'));pref=put(c.run/'PRIORITY.json',priority)
    requirements=json.loads((ACTUAL/'REPUBLICATION_VERIFICATION_REQUIREMENTS.json').read_text(encoding='utf8'))
    requirements.update(authority=cfg['authority'],metadata=cfg['metadata'],statement_priority=pref,expected_public_uid=authority['expected_public_uid'],excluded_old_post_ids=[authority['old_post_id']])
    vref=put(c.run/'VERIFICATION_REQUIREMENTS.json',requirements)
    contract=json.loads((ACTUAL/'NATIVE_STATEMENT_SELECTION_CONTRACT.json').read_text(encoding='utf8'))
    contract.update(inspection_result=controls_result,inspection_receipt=controls_receipt,native_controls=controls_value['inspection']['modal_controls'],metadata=cfg['metadata'],
        file_selection_claim=controls_value['file_selection_claim'],priority_decision=pref,post_submit_verification_requirements=vref)
    req=dict(schema=bridge.REQUEST_SCHEMA,config=cfgref,action=bridge.PUBLISH_ACTION,controls_result=controls_result,controls_receipt=controls_receipt,
        declaration_contract=put(c.run/'DECLARATION_CONTRACT.json',contract),submission_authority=cfg['authority'])
    reqref=put(c.run/'PUBLISH_REQUEST.json',req)
    before={ref['path']:Path(ref['path']).read_bytes() for ref in (controls_result,controls_receipt,result['file_selection_claim'],r9)}
    return NS(**{**vars(c),'config':cfg,'config_ref':cfgref,'request':req,'request_ref':reqref,'before':before,'readplan':readplan,'mode':mode})


@pytest.mark.parametrize('publication',['success','settings_unknown','bad_settings','lost_ack'],indirect=True)
def test_late_once_submission_unknown_and_preclaim_failure_boundaries(publication):
    c=publication
    with pytest.raises(ValueError,match='unique_new_intent_slot'):bridge.prepare(c.config_ref,c.request_ref,c.run/'manual_runtime_v10/publish_002')
    plan=bridge.prepare(c.config_ref,c.request_ref,c.run/'manual_runtime_v10/publish_001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=plan))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    status=bridge.status(plan)
    if c.mode in {'settings_unknown','bad_settings'}:
        assert status['status']=='blocked_no_submission' and not bridge.SUBMIT_CLAIM.exists()
        assert bridge._read(status['result'])['submission_not_attempted'] is True
    else:
        assert bridge.SUBMIT_CLAIM.is_file()
        assert status['status']==('publication_submitted_verification_pending' if c.mode=='success' else 'outcome_unknown')
        claim=bridge._read(bridge.reference(bridge.SUBMIT_CLAIM));assert claim['allowed_publish_clicks']==1 and not claim['automatic_replay_allowed']
        if c.mode=='success':
            assert bridge._read(status['result'])['external_publication_verified'] is False
            with pytest.raises(FileExistsError):bridge.claim_submission(c.actor,c.resource,c.config,c.request,claim['preflight'])
    assert bridge.install_if_armed()['status']==status['status']
    assert all(Path(path).read_bytes()==raw for path,raw in c.before.items())
    assert bridge.status(c.readplan)['status']=='declaration_controls_observed'  # Immutable stage-one producer survives the delta.
