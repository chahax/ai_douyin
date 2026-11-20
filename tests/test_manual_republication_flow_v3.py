"""The observer cannot navigate/input even when the current surface is empty."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
from urllib.parse import urlsplit

import pytest
from src.operations_accounts import manual_republication_flow_v3 as flow
from src.operations_accounts import manual_republication_flow_v1 as v1


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf8")
    return flow.reference(path)


@pytest.fixture
def case(tmp_path,monkeypatch):
    binding=NS(account_uuid="account:test",account_key="novel-test",platform_identity_key="public_uid:75891235130",
        browser_environment_key="original",browser_profile_dir="private-profile",storage_state_path="unused",
        confirmed_by="user",created_at="bound",public_uid="75891235130")
    profile=NS(account_uuid=binding.account_uuid,profile_version=1)
    bv=v1._binding_version(NS(binding=binding,profile=profile))
    auth=put(tmp_path/"AUTH.json",dict(expected_public_uid=binding.public_uid,old_post_id="7709043480894524722"))
    metadata=put(tmp_path/"META.json",dict(title="两分钟原片",media={"sha256":"same-media"}))
    config=dict(schema="manual_republication_runtime_config/v3",account_id=binding.account_uuid,account_key=binding.account_key,
        owner_id="original-owner",generation=33,tab_id="original-tab",binding_version=bv,authority=auth,metadata=metadata,
        sources={"flow_v1":flow.reference(flow.ROOT/"src/operations_accounts/manual_republication_flow_v1.py")})
    cfgref=put(tmp_path/"CONFIG.json",config)
    prior=put(tmp_path/"old/UPLOAD_CLAIM.json",dict(action="prepare_upload",metadata=metadata,authority=auth,
        owner_id="original-owner",generation=33,tab_id="original-tab"))
    failure=put(tmp_path/"old/preparation/PREPARE_FAILURE.json",dict(error_type="BrowserNavigationTimeout",upload_attempted=False,submitted=False))
    request=dict(schema="manual_republication_operator_request/v3",config=cfgref,action="observe_current",
        prior_upload_claim=prior,prior_failure=failure)
    reqref=put(tmp_path/"REQUEST.json",request)
    planref=put(tmp_path/"action/PLAN.json",dict(schema="manual_republication_runtime_plan/v3",config=cfgref,request=reqref))
    put(tmp_path/"action/ACTION_CLAIM.json",dict(schema="manual_republication_observation_claim/v3",plan=planref,request=reqref,
        config=cfgref,prior_upload_claim=prior,prior_failure=failure,actor_thread_id=threading.get_ident(),
        action="observe_current",navigation_allowed=False,input_allowed=False,file_selection_allowed=False))
    state=NS(url="https://www.douyin.com/user/self?token=secret#auth",uids=[binding.public_uid],empty=False,hook=None,events=[])
    owner=NS()
    def location():
        p=urlsplit(state.url);return {"origin":p.scheme+"://"+p.netloc,"path":p.path}
    class Page:
        tab_id="original-tab"
        _session=owner
        def _cmd(self,action):
            assert action=="current_url";state.events.append(action)
            if state.hook:state.hook()
            return {"url":state.url}
        def evaluate(self,script):
            state.events.append("evaluate")
            assert ".goto(" not in script and ".click(" not in script
            if "rendered_public_uid_text" in script:
                return dict(**location(),public_uids=list(state.uids),truncated=False,source="rendered_public_uid_text",input_values_read=False)
            return dict(schema="manual_republication_visible_inventory/v1",location=location(),ready_state="complete",
                controls=[] if state.empty else [{"tag":"button","text":"作品管理"}],visible_text_lines=[] if state.empty else ["作品管理"],
                input_values_read=False,hidden_state_read=False,interaction_performed=False)
        def wait_for_timeout(self,ms):assert ms==250;state.events.append("wait")
        def goto(self,*a,**k):pytest.fail("observe_current must never navigate")
    page=Page();owner.get_page=lambda tab:(state.events.append("get_page") or page)
    actor=NS(owner_id="original-owner",generation=33)
    resource=NS(session=owner,runtime=NS(bindings=NS(get=lambda _:binding),profiles=NS(get=lambda _:profile)))
    import src.operations_accounts as operations
    fake=NS(validate_live=lambda *a:None)
    monkeypatch.setitem(sys.modules,"src.operations_accounts.manual_republication_runtime_v3",fake)
    monkeypatch.setattr(operations,"manual_republication_runtime_v3",fake,raising=False)
    return NS(config=config,request=request,out=tmp_path/"action/observation",actor=actor,resource=resource,
              page=page,owner=owner,state=state,prior=prior,failure=failure)


def run(x,out=None):return flow.run_action(x.actor,x.resource,x.config,x.request,out or x.out)


def test_self_current_uid_is_read_without_refresh_or_any_input(case):
    x=case;before=Path(x.prior["path"]).read_bytes();result=run(x)
    assert result["same_page_rendered_expected_uid_observed"] is True
    assert all(result[k] is False for k in ("uploaded","submitted","navigation_performed","input_performed","file_selected"))
    assert set(x.state.events)<={"get_page","current_url","evaluate","wait"}
    assert Path(x.prior["path"]).read_bytes()==before
    assert "secret" not in json.dumps(result) and "secret" not in Path(result["observation"]["path"]).read_text(encoding="utf8")


def test_creator_without_native_uid_is_not_promoted_from_prior_identity(case):
    x=case;x.state.url="https://creator.douyin.com/creator-micro/content/upload";x.state.uids=[]
    result=run(x)
    assert result["same_page_rendered_expected_uid_observed"] is False
    assert result["creator_identity_verified_for_write"] is False and result["visible_control_count"]==1


def test_empty_current_surface_preserves_empty_evidence_without_navigation(case):
    x=case;x.state.empty=True;result=run(x)
    assert result["visible_control_count"]==0 and result["resume_preparation_authorized"] is False


def test_foreign_origin_is_location_only_without_dom_read(case):
    x=case;x.state.url="https://unrelated.invalid/private?credential=secret"
    result=run(x)
    assert "evaluate" not in x.state.events and result["visible_control_count"]==0
    assert result["location"]=={"origin":"https://unrelated.invalid","path":"/private"}


def test_replaced_original_session_stops_before_reading_dom(case):
    x=case;x.state.hook=lambda:setattr(x.resource,"session",NS())
    with pytest.raises(flow.ObservationBlocked):run(x)
    assert "evaluate" not in x.state.events


def test_wrong_outdir_cannot_reuse_this_read_claim(case):
    x=case
    with pytest.raises((flow.ObservationBlocked,FileNotFoundError)):run(x,x.out.parent/"other/observation")
    assert x.state.events==[]


def test_resume_action_is_not_in_first_readonly_stage(case):
    x=case;x.request["action"]="resume_prepare"
    with pytest.raises(flow.ObservationBlocked):run(x)
    assert x.state.events==[]


def test_prior_failure_tampering_stops_before_page_access(case):
    x=case;Path(x.failure["path"]).write_text("{}",encoding="utf8")
    with pytest.raises(flow.ObservationBlocked):run(x)
    assert x.state.events==[]
