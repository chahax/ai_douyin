"""New session wiring through SDK MockTransport; historical fixture clock only."""
from copy import deepcopy
from datetime import datetime,timezone
from dataclasses import replace
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_fresh_source_session_v1 as flow
from src.content_factory.creative_counted_execution_v1 import CountedExecution
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario,prior_scenario
from tests.test_creative_goal_legal_usage_source_audit_v6 import synthetic_source
from tests.test_creative_goal_commitment_audit_v1 import synthetic as synthetic_commitment
from tests.test_creative_opening_setup_contract_v4 import synthetic_v4
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as full_helpers


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k):raise AssertionError("session tests must not call providers")
    monkeypatch.setattr(socket.socket,"connect",deny);monkeypatch.setattr(socket,"create_connection",deny)
    from scripts import preview_goal_context_workflow_v2 as preview
    packet=flow.read(preview.SOURCE_ROOT/"source/SOURCE_PACKET.json")
    sampled=datetime.fromisoformat(packet["prepared_at"].replace("Z","+00:00"))
    class FixtureClock:
        @staticmethod
        def now(tz=None):return sampled.astimezone(tz or timezone.utc)
    monkeypatch.setattr(preview,"datetime",FixtureClock)
    def config(role):return SimpleNamespace(model=flow.ordinary.WRITER_MODEL if role=="writer" else flow.ordinary.REVIEW_MODEL,
        base_url=flow.ordinary.WRITER_BASE_URL if role=="writer" else "https://api.deepseek.com/v1",api_key="offline-session-not-real")
    monkeypatch.setattr(flow.ordinary,"role_config",config);monkeypatch.setattr(flow.strict,"role_config",config)


def setup_session(tmp_path,monkeypatch,scenario,*,fault=None,source_blocked=False):
    inputs,_,goal,opening,bundle,ids,script=deepcopy(scenario)
    fixed=flow.workflow.fixed_legal_claim_catalog(inputs)
    for claim in goal["claims"]:
        if claim["kind"]=="verified_legal":
            ref=next(ref for ref in claim["origin_ids"] if ref in fixed)
            claim.update(origin_ids=[ref],text=fixed[ref]["text"])
    source_file=tmp_path/"SOURCE.json";flow.write(source_file,{"offline_fixture_only":True})
    for name in ("PREFERENCES","GOALS","AUTHORIZATION_AND_CADENCE_v1","USER_COUNT_UNIT_CONFIRMATION_v1"):
        flow.write(tmp_path/(name+".json"),{"offline_fixture_only":True})
    anchor=tmp_path/"ANCHOR.json";flow.write(anchor,{"schema":"offline_anchor","inherited":flow.spend.INHERITED})
    counter=CountedExecution(tmp_path);counter.initialize(tmp_path/"AUTHORIZATION_AND_CADENCE_v1.json");counter.begin_round("new-round","offline fresh source session")
    config=flow.SessionConfig(str(tmp_path/"run"),str(tmp_path/"source"),str(tmp_path/"PREFERENCES.json"),str(tmp_path/"GOALS.json"),
        str(anchor),flow.digest(flow.read(anchor)),str(tmp_path),"new-round","offline_"+tmp_path.name,str(tmp_path/"AUTH.json"))
    seen=[];builders=[];source_reads=[]
    def build(*args,now):
        if source_blocked:raise ValueError("opportunity_outside_validity")
        return {"inputs":deepcopy(inputs),"evidence":{"offline_fixture_only":True},"source_files":[str(source_file)]}
    def gate(*args,now):
        source_reads.append(now)
        if source_blocked:raise ValueError("opportunity_outside_validity")
        return {"blockers":[],"offline_fixture_only":True}
    def anchor_verify(value,*,expected_anchor_sha256):
        if flow.digest(value)!=expected_anchor_sha256:raise ValueError("anchor mismatch")
        return {"verified":True,"inherited":deepcopy(flow.spend.INHERITED)}
    def factory(request):
        builders.append(request)
        schema=request["structured_schema"];body=json.loads(request["messages"][1]["content"])
        version=schema.get("properties",{}).get("schema",{}).get("const")
        phase=("source" if version==flow.workflow.SOURCE_AUDIT_VERSION else "commitment" if version==flow.workflow.commitment_audit.VERSION
            else "drama" if version==flow.workflow.DRAMA_AUDIT_VERSION else "setup" if version==flow.workflow.OPENING_SETUP_VERSION
            else "plan" if request["stage"]=="goal_plan" else request["input_provenance"].get("review_part",request["stage"]))
        def respond(outgoing):
            seen.append((phase,json.loads(outgoing.read())))
            if phase=="plan":value=deepcopy(goal)
            elif phase=="source":value=synthetic_source(goal,{key:deepcopy(body[key]) for key in ("verified_legal_context","origin_catalog")},schema["properties"]["audit_context_sha256"]["const"])
            elif phase=="commitment":
                value=synthetic_commitment(goal)
                for key in ("schema","goal_sha256","audit_context_sha256"):value[key]=schema["properties"][key]["const"]
                for row in value["commitment_checks"].values():
                    for usage in row["actual_usages"].values():usage.update(requirement_scope="local_event",comparison_refs=[])
            elif phase=="drama":
                value=deepcopy(bundle["native_drama_audit"]);value.pop("commitment_checks",None)
                for key in ("schema","goal_sha256","audit_context_sha256"):value[key]=schema["properties"][key]["const"]
                value["closed_scope_findings"]=[]
                value["scope_observations"]={ref:{"audible_speakers":[],"operated_props":[]} for ref in schema["properties"]["scope_observations"]["properties"]}
            elif phase=="setup":value=synthetic_v4(deepcopy(opening));value["goal_sha256"]=flow.digest(goal)
            elif phase=="complete_script":value=deepcopy(script)
            else:
                views=flow.workflow.compile_native_views(goal,body["native_opening_setup_document"],**ids)
                compiled=flow.text.contract.compile_script(body["native_script_document"],views["brief"])
                legal=flow.workflow.prepare_full_review_part_request(inputs,session.profile,body["native_script_document"],views,phase)["review_legal_context"]
                full=full_helpers.full_review({"full_current_script":compiled,"brief":views["brief"],"creative_scene_plan":views["plan"],"native_goal_document":goal,"verified_legal_context":legal})
                full.update(opening_setup_sha256=flow.digest(views["opening_setup"]))
                if phase=="semantic":full.update(synthetic_consistency(compiled,views["brief"],views["plan"],goal_contract=goal))
                value={key:deepcopy(full[key]) for key in schema["properties"] if key in full}
                for key in ("schema","part","context_sha256"):value[key]=schema["properties"][key]["const"]
                if "revision_target" in schema["properties"]:value["revision_target"]="none"
            mode=fault.get(phase) if fault else None
            if mode=="transport":raise httpx.ReadTimeout("offline unknown",request=outgoing)
            if mode=="type":value["whole_plan"]=[]
            if mode=="source_fail":next(iter(value["claim_checks"].values())).update(status="fail",required_revision="Complete native new plan")
            message={"role":"assistant","content":None,"tool_calls":[{"id":"offline","type":"function","function":{"name":flow.ordinary.TOOL_NAME,"arguments":json.dumps(value,ensure_ascii=False)}}]}
            if mode=="missing_tool":message={"role":"assistant","content":json.dumps(value,ensure_ascii=False)}
            response={"id":"offline-"+str(len(seen)),"model":request["model"],"choices":[{"index":0,"message":message,"finish_reason":"length" if mode=="truncated" else "stop" if mode=="missing_tool" else "tool_calls"}],"usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
            if mode=="usage_unknown":response.pop("usage")
            return httpx.Response(200,content=json.dumps(response,ensure_ascii=False).encode("utf-8"))
        return flow.strict.make_client_factory(request,source_strict=flow.strict_source(request),http_client_factory=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(respond),**kwargs))
    session=flow.Session(config,input_builder=build,source_gate=gate,anchor_verifier=anchor_verify,client_factory_builder=factory)
    monkeypatch.setattr(session,"claim",tmp_path/"CLAIM.json")
    monkeypatch.setattr(session,"successor",tmp_path/"SUCCESSOR.json")
    return session,inputs,seen,builders,counter,source_reads


def prepare(session):
    preview=session.preview();flow.write(session.config.authorization_path,session.authorization_template(preview),True)
    return session.prepare()


def test_fresh_source_plan_through_full_script_eight_actual_sdk_requests_no_legacy_root(tmp_path,monkeypatch,causal_scenario):
    session,inputs,seen,builders,counter,source_reads=setup_session(tmp_path,monkeypatch,causal_scenario)
    prepared=prepare(session)
    assert prepared["spend"]["effective_calls_started"]==620 and not builders
    result=session.run()
    assert result["status"]=="text_ready_for_director",result
    assert [phase for phase,_ in seen]==["plan","source","commitment","drama","setup","complete_script","semantic","physical"]
    assert result["spend"]["effective_calls_started"]==628 and result["spend"]["effective_reported_tokens"]==12942324
    assert result["spend"]["historical_pending_ordinals"]==[70,160]
    assert flow.read(session.root/"TEXT_HANDOFF.json")["native_script"]
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    assert len(source_reads)>=8 and counter.read()["active_round"]["key"]=="new-round"
    old=(session.root/"CALL_LEDGER.json").read_bytes()
    with pytest.raises(FileExistsError):session.run()
    assert (session.root/"CALL_LEDGER.json").read_bytes()==old and len(seen)==8


@pytest.mark.parametrize("fault,status",[("transport","halt_interface_or_unknown"),("usage_unknown","halt_interface_or_unknown"),("truncated","halt_interface_or_unknown"),("missing_tool","halt_interface_or_unknown"),("type","halt_contract_requires_pipeline_diagnosis")])
def test_first_plan_failure_stops_without_source_retry_or_capacity_reset(tmp_path,monkeypatch,causal_scenario,fault,status):
    session,_,seen,_,_,_=setup_session(tmp_path,monkeypatch,causal_scenario,fault={"plan":fault})
    prepare(session);result=session.run()
    assert result["status"]==status,result
    assert [phase for phase,_ in seen]==["plan"] and result["spend"]["effective_calls_started"]==621
    assert not (session.root/"TEXT_HANDOFF.json").exists()


def test_source_native_content_failure_stops_no_plan2_or_body(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_=setup_session(tmp_path,monkeypatch,causal_scenario,fault={"source":"source_fail"})
    prepare(session);result=session.run()
    assert result["status"]=="halt_goal_content_requires_pipeline_diagnosis",result
    assert [phase for phase,_ in seen]==["plan","source"]


def test_expired_source_has_no_prepare_claim_or_client(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,builders,_,_=setup_session(tmp_path,monkeypatch,causal_scenario,source_blocked=True)
    with pytest.raises(ValueError,match="opportunity_outside_validity"):session.prepare()
    assert not session.claim.exists() and not session.root.exists() and not seen and not builders


def test_stop_between_task_claim_and_locked_admission_has_no_provider(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,counter,_=setup_session(tmp_path,monkeypatch,causal_scenario)
    prepare(session);claim=flow.tasks.TaskStore.claim
    def stop_claim(*args,**kwargs):
        result=claim(*args,**kwargs);proof=tmp_path/"STOP.json";flow.write(proof,{"stop":True});counter.stop("ten_reviews_completed",proof);return result
    monkeypatch.setattr(flow.tasks.TaskStore,"claim",stop_claim)
    with pytest.raises(ValueError,match="execution stopped"):session.run()
    assert not seen and not flow.read(session.root/"CALL_LEDGER.json")["calls"]


def test_protocol_rejected_dict_never_becomes_complete_native_content_revision():
    receipt={"ordinal":621,"status":"interface_rejected","output":{"looks":"complete"},
        "request":{"model":"MiniMax-M3.1-Flash-Preview"},
        "failure":{"category":"interface","response_received":True,"code":"UNEXPECTED_TOOL_CALL"},
        "response_metadata":{"http_status_code":200,"response_body_complete":True,"finish_reason":"tool_calls",
            "total_tokens":10,"output_mode":"tool_call","requested_model":"MiniMax-M3.1-Flash-Preview","response_model":"MiniMax-M3.1-Flash-Preview"}}
    with pytest.raises(flow.Halt,match="") as result:flow.Session.known(receipt,"complete_script",require_valid=False)
    assert result.value.status=="halt_protocol_requires_diagnosis"


def test_compile_rejection_and_taskstore_agree_on_content_revision(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_=setup_session(tmp_path,monkeypatch,causal_scenario)
    prepare(session);original=flow.workflow.validate_script_document;attempts=[]
    def validation(*args,**kwargs):
        attempts.append(True)
        if len(attempts)==1:
            error=ValueError("EXPRESSION_TEST_WINDOW: native complete document requires revision");error.code="EXPRESSION_TEST_WINDOW";error.detail={"case":"offline compile rejection"};raise error
        return original(*args,**kwargs)
    monkeypatch.setattr(flow.workflow,"validate_script_document",validation)
    result=session.run()
    assert result["status"]=="text_ready_for_director",result
    assert [phase for phase,_ in seen].count("complete_script")==2
    import sqlite3
    with sqlite3.connect(session.root/"TASKS.sqlite3") as db:
        entries=[json.loads(row[0]) for row in db.execute("SELECT result FROM attempts ORDER BY rowid")]
    first=next(row for row in entries if row.get("output",{}).get("ordinal")==626)
    assert first["outcome"]=="content_rejected" and first["schema_tool_status"]=="accepted"


@pytest.mark.parametrize("module",[flow.strict,flow.source_runtime])
def test_actual_sdk_and_source_runtime_dependencies_frozen_before_dispatch(tmp_path,monkeypatch,causal_scenario,module):
    session,_,seen,builders,_,_=setup_session(tmp_path,monkeypatch,causal_scenario)
    prepare(session);path=Path(module.__file__).resolve()
    assert str(path) in flow.read(session.root/"PRODUCTION_FREEZE.json")["files"]
    original_sha=flow.sha
    monkeypatch.setattr(flow,"sha",lambda candidate:"f"*64 if Path(candidate).resolve()==path else original_sha(candidate))
    with pytest.raises(ValueError,match="frozen session source changed"):session.run()
    terminal=flow.read(session.root/"STATE.json")
    assert terminal["status"]=="halt_execution_exception_requires_reconciliation" and not seen and not builders
    assert terminal["spend_verification_pending"] and terminal["spend"] is None
    assert terminal["last_saved_spend_checkpoint"]["not_current_verified_spend"]


def test_expired_during_run_saves_terminal_and_pending_spend_without_restarting(tmp_path,monkeypatch,causal_scenario):
    session,_,seen,_,_,_=setup_session(tmp_path,monkeypatch,causal_scenario);prepare(session)
    def expired(*args,**kwargs):raise ValueError("opportunity_outside_validity")
    monkeypatch.setattr(session,"source_gate",expired)
    with pytest.raises(ValueError,match="opportunity_outside_validity"):session.run()
    result=flow.read(session.root/"STATE.json")
    assert result["status"]=="halt_execution_exception_requires_reconciliation" and not seen
    assert result["spend"] is None and result["spend_verification_pending"]
    with pytest.raises(FileExistsError):session.run()


def test_canonical620_anchor_has_only_one_successor_across_roots_and_grants(tmp_path,monkeypatch,causal_scenario):
    first,_,seen,builders,counter,_=setup_session(tmp_path,monkeypatch,causal_scenario)
    prepare(first);before=counter.read()
    second=flow.Session(replace(first.config,root=str(tmp_path/"other_root"),grant_id="another_grant",authorization_path=str(tmp_path/"OTHER_AUTH.json")),
        input_builder=first.input_builder,source_gate=first.source_gate,anchor_verifier=first.anchor_verifier,client_factory_builder=first.client_factory_builder)
    monkeypatch.setattr(second,"claim",tmp_path/"OTHER_CLAIM.json");monkeypatch.setattr(second,"successor",first.successor)
    with pytest.raises(FileExistsError,match="anchor already has a successor"):second.prepare()
    assert not second.root.exists() and not second.claim.exists() and not seen and not builders
    assert flow.read(first.successor)["root"]==str(first.root) and counter.read()==before
    # Read-only status does not initialize or reclaim either global claim.
    from scripts.run_fresh_source_session_v1 import main
    assert main(["status","--root",str(first.root)])==0
    assert counter.read()==before
