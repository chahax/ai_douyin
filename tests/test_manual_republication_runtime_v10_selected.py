"""No-reselection continuation from an immutable known pre-confirmation stop."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_manual_republication_runtime_v7 import v2_case,v3_case,v4_case,v5_case,v6_case,case as v7_case
import test_manual_republication_runtime_v10_publish as support
from test_manual_republication_runtime_v8 import put
from src.operations_accounts import manual_republication_runtime_v10 as bridge

SELECTED='''class DeclarationControlsBlocked(ValueError):
 def __init__(self,code):self.code=code;super().__init__(code)
SAFE_REASONS=frozenset({'controls_selection_unconfirmed'})
SAMPLES=SAMPLES_LITERAL
def run_action(actor,resource,config,request,outdir,runtime_bridge=None):
 r=runtime_bridge;outdir.mkdir(parents=True,exist_ok=True)
 r._once(outdir/'NATIVE_SELECTED_GROUP.json',SAMPLES)
 trace=outdir/'RPC_TRACE.jsonl';trace.write_text('{"event":"rpc_dispatched","action":"click","phase":"native_select_ai_label","selector":"div.semi-modal:visible label.semi-radio","index":0}\\n',encoding='utf8')
 image=outdir/'FAILURE_SCREENSHOT.png';image.write_bytes(b'private synthetic screenshot protocol')
 state=r._once(outdir/'FAILURE_NATIVE_STATE.json',SAMPLES['samples'][-1])
 r._once(outdir/'SUBMISSION_FAILURE.json',{'schema':'manual_declaration_publication_failure/v10','phase':'read_selected_native_group','reason_code':'controls_selection_unconfirmed',
 'selection_click_dispatched':True,'selection_performed':False,'confirmation_click_dispatched':False,'declaration_confirmed':False,'publish_click_dispatched':False,
 'submission_claimed':False,'submission_claim':None,'file_selected':False,'navigation_performed':False,'fields_written':False,'rpc_trace':r.reference(trace),
 'native_diagnostics':{'native_state':state,'screenshot':r.reference(image)}})
 raise DeclarationControlsBlocked('controls_selection_unconfirmed')
'''


@pytest.mark.parametrize('mode',['success','lost_ack'])
def test_selected_continuation_never_replays_original_choice_or_publication(v7_case,monkeypatch,mode):
    samples=json.loads((support.ACTUAL/'manual_runtime_v10/publish_001/publication/NATIVE_SELECTED_GROUP.json').read_text(encoding='utf8'))
    selected_body=SELECTED.replace('SAMPLES_LITERAL',repr(samples))
    original_body=support.PUBLISH_BODY
    monkeypatch.setattr(support,'PUBLISH_BODY',selected_body)
    c=support.publication.__wrapped__(v7_case,monkeypatch,NS(param='selected_pending'))
    oldplan=bridge.prepare(c.config_ref,c.request_ref,c.run/'manual_runtime_v10/publish_001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=oldplan))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    oldstatus=bridge.status(oldplan);assert oldstatus['status']=='blocked_no_submission' and not bridge.SUBMIT_CLAIM.exists()
    oldresult=bridge._read(oldstatus['result']);folder=Path(oldplan['path']).parent
    # Same version, new reviewed flow; the previous producer snapshots remain
    # unchanged and authorize no replay of that prior action.
    paths=dict(bridge.SOURCE_PATHS)
    paths['runtime_v10'].write_text('# separately reviewed selected-state continuation',encoding='utf8')
    body=original_body.replace('MODE_LITERAL',repr(mode)).replace("'action':r.PUBLISH_ACTION","'action':request['action']")
    body=body.replace("'selection_performed':True,'declaration_confirmed':True,'navigation_performed'","'selection_performed':False,'selection_reused':True,'selected_state_contract':request['selected_state_contract'],'declaration_confirmed':True,'navigation_performed'")
    paths['flow_v10'].write_text(body,encoding='utf8')
    cfg=dict(c.config,sources={k:bridge.reference(p) for k,p in paths.items()});cfgref=put(c.run/'CONTINUE_CONFIG.json',cfg)
    sem=json.loads((support.ACTUAL/'SEMI_RADIO_SELECTION_DISPLAY_CONTRACT.json').read_text(encoding='utf8'))
    sem.update(parent_selection_contract=c.request['declaration_contract'],authority=cfg['authority'],blocked_result=oldstatus['result'],blocked_receipt=oldstatus['receipt'],
        failure=bridge.reference(folder/'publication/SUBMISSION_FAILURE.json'),selected_samples=bridge.reference(folder/'publication/NATIVE_SELECTED_GROUP.json'),
        rpc_trace=bridge.reference(folder/'publication/RPC_TRACE.jsonl'),screenshot=bridge.reference(folder/'publication/FAILURE_SCREENSHOT.png'),
        independent_terminal_review=put(c.run/'TERMINAL_PROTOCOL_REVIEW.json',{'scope':'private synthetic protocol only'}))
    semref=put(c.run/'SELECTED_UI_CONTRACT.json',sem)
    req=dict(c.request,config=cfgref,action=bridge.CONTINUE_ACTION,selected_state_contract=semref);reqref=put(c.run/'CONTINUE_REQUEST.json',req)
    before={ref['path']:Path(ref['path']).read_bytes() for ref in (oldstatus['result'],oldstatus['receipt'],sem['failure'],sem['selected_samples'],sem['rpc_trace'],oldresult['claim'])}
    bad=put(c.run/'BAD_CONTRACT.json',dict(sem,continuation_selections_allowed=1))
    with pytest.raises(ValueError,match='known_preconfirmation'):bridge.prepare(cfgref,put(c.run/'BAD_CONTINUE.json',dict(req,selected_state_contract=bad)),c.run/'manual_runtime_v10/continuation_selected_001')
    with pytest.raises(ValueError,match='unique_new_intent_slot'):bridge.prepare(cfgref,reqref,c.run/'manual_runtime_v10/continuation_selected_002')
    plan=bridge.prepare(cfgref,reqref,c.run/'manual_runtime_v10/continuation_selected_001');put(bridge.ARM,dict(schema='manual_republication_runtime_arm/v10',plan=plan))
    assert bridge.install_if_armed()['status'].startswith('callback_registered');c.namespace['_poll_manual_windows'](c.actor,c.resource)
    value=bridge.status(plan)
    assert value['status']==('publication_submitted_verification_pending' if mode=='success' else 'outcome_unknown')
    action=bridge._read(bridge.reference(Path(plan['path']).parent/'ACTION_CLAIM.json'))
    assert action['selections_allowed']==0 and action['confirmations_allowed']==action['submissions_allowed']==1
    assert bridge.SUBMIT_CLAIM.is_file() and bridge.install_if_armed()['status']==value['status']
    assert all(Path(path).read_bytes()==raw for path,raw in before.items())
    assert bridge.status(oldplan)['status']=='blocked_no_submission'
