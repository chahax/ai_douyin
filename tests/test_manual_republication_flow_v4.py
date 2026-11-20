"""Same existing RPC model, fresh sealed leaves, synthetic commit readiness."""
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace as NS

import pytest
from test_manual_republication_flow_v2 import case
from src.operations_accounts import manual_republication_flow_v4 as flow
from src.operations_accounts import manual_republication_flow_v1 as v1
from src.operations_accounts import manual_republication_flow_v2 as v2
from src.platform_adapter.browser_session import BrowserNavigationTimeout


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    return flow.reference(path)


@pytest.fixture
def resume(case,monkeypatch):
    x=case;x.state.url=v1.SELF_URL
    config=dict(x.config);config['sources']=dict(config['sources'],flow_v2=flow.reference(Path(v2.__file__)))
    cfgref=put(x.run/'CONFIG_V4.json',config)
    oldfailure=put(x.run/'old/PREPARE_FAILURE.json',dict(upload_attempted=False,submitted=False,error_type='BrowserNavigationTimeout'))
    observation=put(x.run/'V3_RESULT.json',dict(schema='private-fixture',current_uid='75891235130',input_performed=False))
    request=dict(schema='manual_republication_operator_request/v4',config=cfgref,action='resume_prepare_upload',
        prior_upload_claim=x.claimref,prior_failure=oldfailure,observation=observation)
    reqref=put(x.run/'REQUEST_V4.json',request)
    planref=put(x.run/'resume/PLAN.json',dict(schema='manual_republication_runtime_plan/v4',config=cfgref,request=reqref))
    action=put(x.run/'resume/ACTION_CLAIM.json',dict(schema='manual_republication_resume_action_claim/v4',plan=planref,config=cfgref,
        request=reqref,prior_upload_claim=x.claimref,prior_failure=oldfailure,observation=observation,
        owner_id=x.actor.owner_id,generation=x.actor.generation,tab_id='original-tab',actor_thread_id=threading.get_ident(),
        action='resume_prepare_upload',file_selection_limit=1,submit_allowed=False))
    x.config,x.request,x.out=config,request,x.run/'resume/preparation'
    x.navigation_mode='ok';x.late_claims=[]
    original_cmd=x.owner.cmd
    def command(action,**kwargs):
        if action=='evaluate' and 'rendered_public_uid_text' in kwargs.get('js',''):
            kwargs=dict(kwargs,js=v1.UID_JS)
        result=original_cmd(action,**kwargs)
        if action=='goto':
            assert kwargs['url']==v1.SITES['upload'] and kwargs['wait_until']=='commit'
            if x.navigation_mode.startswith('timeout'):
                if x.navigation_mode=='timeout_unready':x.state.file_count=0
                raise BrowserNavigationTimeout(dict(navigation_committed=True,target_matched=True,ready_state='interactive',wait_until='commit',timeout_ms=10000,elapsed_ms=10000))
        return result
    x.owner.cmd=command
    def claim_file_selection(actor,resource,cfg,req,outdir,media,selection_evidence):
        evidence=flow.read(selection_evidence)
        assert evidence['action_claim']==action and evidence['media']==media
        assert evidence['identity']['verified'] and evidence['identity']['actual_public_uid']=='75891235130'
        assert 0<=time.time()-evidence['identity']['observed_at']<=60
        assert evidence['preselection']['file_count']==evidence['preselection']['visible_file_count']==evidence['preselection']['upload_button_count']==1
        assert x.state.selected==0 and (x.run/'UPLOAD_CLAIM.json').exists()
        x.late_claims.append(selection_evidence)
        return flow.once(x.run/'FILE_SELECTION_CLAIM.json',dict(schema='private-file-claim',action_claim=action,media=media,proof=selection_evidence))
    import src.operations_accounts as operations
    runtime=NS(validate_live=lambda *a:None,claim_file_selection=claim_file_selection)
    monkeypatch.setitem(sys.modules,'src.operations_accounts.manual_republication_runtime_v4',runtime)
    monkeypatch.setattr(operations,'manual_republication_runtime_v4',runtime,raising=False)
    original_load=flow._load_base
    def load(config):
        base=original_load(config);leaf_load=base._load_leaves
        def leaves(config):
            reader,Workflow=leaf_load(config)
            Workflow._wait_for_upload_complete=lambda *a,**k:True  # server-completion edge only
            return reader,Workflow
        base._load_leaves=leaves;return base
    monkeypatch.setattr(flow,'_load_base',load)
    return x


def run(x,out=None):return flow.run_action(x.actor,x.resource,x.config,x.request,out or x.out)


def test_current_self_is_not_reloaded_and_file_claim_is_late(resume):
    x=resume;old=Path(x.claimref['path']).read_bytes();result=run(x)
    gotos=[k for a,k in x.state.commands if a=='goto']
    assert len(gotos)==1 and gotos[0]['url']==v1.SITES['upload'] and gotos[0]['wait_until']=='commit'
    assert x.state.selected==len(x.late_claims)==1 and Path(x.claimref['path']).read_bytes()==old
    assert result['upload_ready'] and result['metadata_readback_matched'] and not result['submitted'] and not result['declaration_selected']
    assert (x.out/'POST_UPLOAD_EDITOR.json').exists()


def test_navigation_timeout_with_actual_ready_dom_continues_without_second_goto(resume):
    x=resume;x.navigation_mode='timeout_ready';result=run(x)
    assert result['upload_ready'] and x.state.selected==1 and len(x.late_claims)==1
    assert len([a for a,_ in x.state.commands if a=='goto'])==1
    assert (x.out/'NAVIGATION_TIMEOUT.json').exists()


def test_timeout_without_ready_dom_leaves_file_slot_unclaimed(resume):
    x=resume;x.navigation_mode='timeout_unready'
    with pytest.raises(flow.ResumePrepareBlocked):run(x)
    assert x.state.selected==0 and x.late_claims==[] and not (x.run/'FILE_SELECTION_CLAIM.json').exists()
    assert (x.out/'NAVIGATION_TIMEOUT.json').exists()


def test_ack_unknown_after_selection_never_reselects(resume):
    x=resume;x.state.drop_selection=True
    with pytest.raises(flow.ResumePrepareBlocked) as error:run(x)
    assert error.value.code=='resume_post_selection_unknown' and x.state.selected==1
    with pytest.raises(flow.ResumePrepareBlocked):run(x)
    assert x.state.selected==1 and len(x.late_claims)==1


def test_wrong_output_directory_cannot_reuse_bound_action(resume):
    x=resume
    with pytest.raises((flow.ResumePrepareBlocked,FileNotFoundError)):run(x,x.run/'other/preparation')
    assert x.state.commands==[] and x.late_claims==[]


def test_foreign_current_origin_is_rejected_before_dom_or_navigation(resume):
    x=resume;x.state.url='https://unrelated.invalid/private'
    with pytest.raises(flow.ResumePrepareBlocked):run(x)
    assert not any(a in {'evaluate','goto','set_input_files'} for a,_ in x.state.commands)
    assert x.late_claims==[]
