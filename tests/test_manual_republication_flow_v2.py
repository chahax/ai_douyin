"""Private same-Page RPC model; real freshly compiled upload/form leaf helpers."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import manual_republication_flow_v2 as flow
from src.operations_accounts import manual_republication_flow_v1 as v1
from src.platform_adapter.browser_session import Page


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf8")
    return v1._reference(path)


@pytest.fixture
def case(tmp_path, monkeypatch):
    run=tmp_path/"run";run.mkdir();monkeypatch.setattr(flow,"RUN",run)
    media=run/"original.mp4";media.write_bytes(b"private unchanged media fixture")
    account="account:test";key="novel-test"
    binding=NS(account_uuid=account,account_key=key,platform_identity_key="public_uid:75891235130",
        browser_environment_key="original",browser_profile_dir="private-original",storage_state_path="unused",
        confirmed_by="user",created_at="bound",public_uid="75891235130")
    profile=NS(account_uuid=account,profile_version=1);version=v1._binding_version(NS(binding=binding,profile=profile))
    authority=put(run/"AUTH.json",dict(media=v1._reference(media),expected_public_uid=binding.public_uid))
    metadata=dict(schema="manual_republication_metadata/v1",account_uuid=account,account_key=key,media=v1._reference(media),
        title="两分钟新文案",description="推广信息；剧情虚构，非真实事件。",hashtags=["小说推文","穿书","小说剧情","AI短剧","AI生成"],
        ai_generated=True,fictional_story=True,visibility="public")
    metaref=put(run/"METADATA.json",metadata)
    paths={"flow_v1":flow.ROOT/"src/operations_accounts/manual_republication_flow_v1.py",
           "publish_workflow":flow.ROOT/"src/platform_adapter/publish_workflow.py",
           "upload_diagnostic":flow.ROOT/"src/platform_adapter/upload_surface_diagnostic.py"}
    config=dict(account_id=account,account_key=key,owner_id="original-owner",generation=33,binding_version=version,
        tab_id="original-tab",authority=authority,metadata=metaref,sources={k:v1._reference(p) for k,p in paths.items()})
    cref=put(run/"CONFIG.json",config)
    request=dict(schema="manual_republication_operator_request/v2",config=cref,action="prepare_upload")
    request_ref=put(run/"REQUEST.json",request)
    plan_ref=put(run/"action/PLAN.json",dict(schema="manual_republication_runtime_plan/v2",config=cref,request=request_ref))
    claim=dict(schema="manual_republication_upload_claim/v1",plan=plan_ref,request=request_ref,config=cref,
        authority=authority,metadata=metaref,media=metadata["media"],action="prepare_upload",owner_id="original-owner",
        generation=33,tab_id="original-tab",actor_thread_id=threading.get_ident(),submissions_allowed=0)
    claimref=put(run/"UPLOAD_CLAIM.json",claim)
    state=NS(url="about:blank",selected=0,title="",description="",tags=[],file_count=1,drop_selection=False,
             entry=None,clicks=[],commands=[],on_upload_navigation=None,hide_fields=False)
    class Owner:
        active=True;_closed=False
        config=NS(headless=False,timeout_ms=30000)
        _proc=NS(poll=lambda:None)
        def worker_failure(self):return ""
        def get_page(self, tab):
            assert tab=="original-tab";return raw
        def cmd(self,action,**kwargs):
            assert kwargs.pop("tab_id")=="original-tab";state.commands.append((action,deepcopy(kwargs)))
            selector=kwargs.get("selector","")
            if action=="goto":
                state.url=kwargs["url"]
                if state.url==v1.SITES["upload"] and state.on_upload_navigation:state.on_upload_navigation()
                return {"url":state.url}
            if action=="current_url":return {"url":state.url}
            if action=="wait_for_timeout":return {}
            if action=="set_input_files":
                state.selected+=1
                if state.drop_selection:raise RuntimeError("simulated lost selection acknowledgement")
                return {}
            if action=="upload_check_proof":
                return {"proof":{"schema":"upload_check_transition/v2","selection_nonce":kwargs["selection_nonce"],
                    "verified":False,"state":"armed_upload"}}
            if action=="locator_count":
                n=(1 if state.entry else 0) if selector==flow.ENTRY else 1 if state.selected and not state.hide_fields and (selector in flow.TITLE_SELECTORS or selector in flow.EDITORS) else state.file_count if selector=="input[type=file]" else 0
                return {"count":n}
            if action=="fill":
                if selector in flow.TITLE_SELECTORS:state.title=kwargs["value"]
                else:state.description=kwargs["value"]
                return {}
            if action=="click":state.clicks.append(selector);return {}
            if action=="type_hashtag":state.tags.append(kwargs["tag"]);return {}
            if action=="evaluate":
                js=kwargs["js"]
                if js==v1.UID_JS:return {"value":{"origin":"https://www.douyin.com","path":"/user/self","public_uids":[binding.public_uid],"truncated":False,"source":"rendered_public_uid_text","input_values_read":False}}
                if js==flow.UPLOAD_PROBE:return {"value":{"schema":"manual_upload_preselection/v1","origin":"https://creator.douyin.com","path":"/creator-micro/content/upload","file_count":state.file_count,"visible_file_count":state.file_count,"file_disabled":False,"upload_button_count":1,"editor_count":int(state.selected>0),"input_values_read":False}}
                if js==flow.FIELD_PROBE:return {"value":{"schema":"manual_authorized_field/v1","visible":True,"disabled":False,"readonly":False,"tag":"input" if selector in flow.TITLE_SELECTORS else "div","content":state.title if selector in flow.TITLE_SELECTORS else state.description}}
                if "el===document.querySelector" in js:return {"value":True}
                if "manual_editor_declaration_inventory/v1" in js:return {"value":{"schema":"manual_editor_declaration_inventory/v1","location":{"origin":"https://creator.douyin.com","path":"/creator-micro/content/publish"},"visible_text_lines":["添加自主声明"],"controls":[],"input_values_read":False,"hidden_state_read":False,"submission_performed":False}}
                if selector==flow.ENTRY:return {"value":deepcopy(state.entry)}
                if "explicit_topic" in js:return {"value":{"visible":True,"text":state.description+" "+" ".join("#"+x for x in state.tags),"truncated":False,"chips":[{"text":x,"explicit_topic":True} for x in state.tags]}}
                raise AssertionError("unexpected private evaluate")
            raise AssertionError("unexpected private RPC: "+action)
    owner=Owner();raw=Page(owner,"original-tab")
    actor=NS(account_id=account,owner_id="original-owner",generation=33,binding_version=version)
    resource=NS(session=owner,runtime=NS(bindings=NS(get=lambda _:binding),profiles=NS(get=lambda _:profile)))
    import src.operations_accounts as operations
    fake_runtime=NS(validate_live=lambda a,r,c:None)
    monkeypatch.setitem(sys.modules,"src.operations_accounts.manual_republication_runtime_v2",fake_runtime)
    monkeypatch.setattr(operations,"manual_republication_runtime_v2",fake_runtime,raising=False)
    original_load=flow._load_leaves
    def load(c):
        inspect,Workflow=original_load(c)
        # Only server upload-completion edge is synthetic; selection, metadata,
        # hashtags, journaling and the RPC gate use the real pinned leaf code.
        Workflow._wait_for_upload_complete=lambda self,page,**kwargs:True
        return inspect,Workflow
    monkeypatch.setattr(flow,"_load_leaves",load)
    return NS(run=run,media=media,metadata=metadata,config=config,request=request,plan_ref=plan_ref,claimref=claimref,
        actor=actor,resource=resource,out=run/"action/preparation",state=state,owner=owner,load=original_load)


def execute(x,out=None):return flow.run_action(x.actor,x.resource,x.config,x.request,out or x.out)


def test_real_fresh_leaf_selection_and_metadata_never_publish(case):
    x=case;result=execute(x)
    assert x.state.selected==1 and result["upload_ready"] and result["metadata_readback_matched"]
    assert result["submitted"] is False and result["declaration_selected"] is False and result["publication_ready"] is False
    assert x.state.title==x.metadata["title"] and x.state.description==x.metadata["description"]
    assert x.state.tags==x.metadata["hashtags"]
    assert (x.out/"POST_UPLOAD_EDITOR.json").is_file()
    assert all(a not in {"ai_content_declaration","new_tab","api_request","api_download"} for a,_ in x.state.commands)
    assert all(selector!=flow.ENTRY for selector in x.state.clicks)
    before=len(x.state.commands)
    with pytest.raises(flow.PrepareUploadBlocked):execute(x)
    assert x.state.selected==1 and len(x.state.commands)==before


def test_same_global_claim_cannot_be_reused_with_another_output_directory(case):
    x=case
    with pytest.raises(flow.PrepareUploadBlocked):execute(x,x.run/"other/preparation")
    assert x.state.commands==[] and x.state.selected==0


def test_drop_after_one_file_selection_retains_unknown_and_never_reselects(case):
    x=case;x.state.drop_selection=True
    with pytest.raises(flow.PrepareUploadBlocked) as error:execute(x)
    assert error.value.code=="prepare_post_selection_unknown" and x.state.selected==1
    failure=v1._read(v1._reference(x.out/"PREPARE_FAILURE.json"));assert failure["automatic_file_reselection_allowed"] is False
    with pytest.raises(flow.PrepareUploadBlocked):execute(x)
    assert x.state.selected==1


def test_nonunique_actual_upload_ui_stops_before_selection(case):
    x=case;x.state.file_count=2
    with pytest.raises(flow.PrepareUploadBlocked):execute(x)
    assert x.state.selected==0 and not (x.out/"FILE_SELECTION_INTENT.json").exists()


def test_media_changed_during_self_navigation_is_not_selected(case):
    x=case;x.state.on_upload_navigation=lambda:x.media.write_bytes(b"changed media")
    with pytest.raises(flow.PrepareUploadBlocked):execute(x)
    assert x.state.selected==0


@pytest.mark.parametrize("entry",[
    {"visible":True,"tag":"label","role":"","type":"","haspopup":"","expanded":""},
    {"visible":True,"tag":"button","role":"button","type":"submit","haspopup":"dialog","expanded":"false"},
])
def test_unverified_entry_or_submit_button_is_not_clicked(case,entry):
    x=case;x.state.entry=entry;result=execute(x)
    assert flow.ENTRY not in x.state.clicks and result["declaration_entry_expanded"] is False


def test_fresh_class_is_not_a_cached_publish_workflow_object(case,monkeypatch):
    from src.platform_adapter.publish_workflow import PublishWorkflow as cached
    monkeypatch.setattr(cached,"_upload_video_file",lambda *a:pytest.fail("cached helper executed"))
    x=case;assert execute(x)["upload_ready"] and x.state.selected==1


def test_replaced_session_stops_before_any_file_selection(case):
    x=case;x.state.on_upload_navigation=lambda:setattr(x.resource,"session",NS())
    with pytest.raises(flow.PrepareUploadBlocked):execute(x)
    assert x.state.selected==0


def test_unknown_new_editor_keeps_post_upload_inventory_before_any_field_write(case):
    x=case;x.state.hide_fields=True
    with pytest.raises(flow.PrepareUploadBlocked) as error:execute(x)
    assert error.value.code=="prepare_post_selection_unknown" and x.state.selected==1
    assert (x.out/"POST_UPLOAD_EDITOR.json").is_file()
    assert not any(action=="fill" for action,_ in x.state.commands)
    failure=v1._read(v1._reference(x.out/"PREPARE_FAILURE.json"))
    assert failure["cause_code"]=="prepare_editor_not_confirmed"


def test_local_actual_upload_shape_and_declaration_radio_inventory_are_read_only(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(tmp_path/"local-private-profile"),channel="chrome",headless=True,
            args=["--mute-audio","--disable-background-networking"])
        context.route("**/*",lambda route:route.fulfill(status=200,content_type="text/html",body="<html><body></body></html>"))
        page=context.new_page();page.goto(v1.SITES["upload"])
        page.set_content('<button type="button">上传视频</button><input type="file">')
        probe=page.evaluate(flow.UPLOAD_PROBE)
        assert probe["file_count"]==probe["visible_file_count"]==probe["upload_button_count"]==1 and probe["editor_count"]==0
        page.set_content('<fieldset><legend>自主声明（单选）</legend><label><input type="radio" name="声明" checked>AI生成</label>'
            '<label><input type="radio" name="声明">营销推广</label><button type="submit">发布</button></fieldset>')
        page.evaluate("""()=>{window.clicked=0;document.addEventListener('click',()=>window.clicked++,true);Object.defineProperty(HTMLInputElement.prototype,'value',{get(){throw Error('unrelated value read')},set(){throw Error('unexpected value write')}})}""")
        captured=page.evaluate(flow.declaration_inventory_script())
        radios=[c for c in captured["controls"] if c["type"]=="radio"]
        assert len(radios)==2 and [r["checked"] for r in radios]==[True,False]
        assert captured["input_values_read"] is False and captured["submission_performed"] is False
        assert page.evaluate("()=>window.clicked")==0
        context.close()

