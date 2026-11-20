"""Historical blinded diagnostics through actual SDK MockTransport; no real calls."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import run_legal_speech_act_probe_v1 as probe
from src.content_factory.creative_counted_execution_v1 import CountedExecution


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**kw):raise AssertionError("probe tests cannot contact providers")
    monkeypatch.setattr(socket.socket,"connect",deny)
    monkeypatch.setattr(socket,"create_connection",deny)
    monkeypatch.setattr(probe.clients,"role_config",lambda role:SimpleNamespace(
        model=probe.clients.REVIEW_MODEL,base_url="https://api.deepseek.com/v1",api_key="offline-probe-not-real"))


def native_response(prepared,*,misclassify=None,empty_positive=False,alternate_nonlegal=False):
    rows={row["case_id"]:row for row in probe.read(probe.CASES)["cases"]}
    code={value:key for key,value in probe.production.workflow.source_audit.SPEECH_ACT_MEANINGS.items()}
    values={}
    for opaque,case_id in prepared["blind_case_mapping"].items():
        expected=rows[case_id]["expected"]
        positive=expected["requires_detailed_legal_or_uncertain_review"]
        label=expected["accepted_speech_acts"][0]
        if alternate_nonlegal and not positive:label="management_motive_or_process" if label!="management_motive_or_process" else "factual_description"
        if case_id==misclassify:label="factual_description" if positive else "legal_assertion"
        values[opaque]={"speech_act":code[label],"asserted_legal_proposition":"Synthetic proposition" if positive and not empty_positive else "",
            "reason":"Synthetic diagnostic only"}
    return {"schema":probe.VERSION,"context_sha256":prepared["context_sha256"],"classifications":values}


def replay(tmp_path,monkeypatch,*,fault=None,misclassify=None):
    project=tmp_path/"project";project.mkdir()
    root=project/"run";sends=[]
    monkeypatch.setattr(probe,"PROJECT",project)
    # Case paths remain the original repository; payload building is read-only.
    original_cases=probe.verify_cases
    actual_project=probe.production.PROJECT
    def cases():
        saved=probe.PROJECT
        try:
            probe.PROJECT=actual_project
            return original_cases()
        finally:probe.PROJECT=saved
    monkeypatch.setattr(probe,"verify_cases",cases)
    monkeypatch.setattr(probe,"ROOT",root)
    counter_root=project/"counter";auth=project/"AUTH.txt";auth.write_text("synthetic only",encoding="utf-8")
    counter=CountedExecution(counter_root);counter.initialize(auth);counter.begin_round("test-probe","historical classification")
    monkeypatch.setattr(probe,"COUNTED_ROOT",counter_root);monkeypatch.setattr(probe,"COUNTED_KEY","test-probe")
    prepared=probe.prepare_probe()
    def handler(outgoing):
        sends.append(json.loads(outgoing.read()))
        if fault=="transport_unknown":raise httpx.ReadTimeout("synthetic transport unknown",request=outgoing)
        value=native_response(prepared,misclassify=misclassify)
        if fault=="contract":value["classifications"].pop(next(iter(value["classifications"])))
        message={"role":"assistant","content":None,"tool_calls":[{"id":"offline","type":"function",
            "function":{"name":probe.clients.TOOL_NAME,"arguments":json.dumps(value,ensure_ascii=False)}}]}
        if fault=="missing_tool":message={"role":"assistant","content":json.dumps(value,ensure_ascii=False)}
        payload={"id":"offline-probe","model":probe.clients.REVIEW_MODEL,"choices":[{"index":0,"message":message,
            "finish_reason":"length" if fault=="truncated" else "stop" if fault=="missing_tool" else "tool_calls"}],
            "usage":{"prompt_tokens":90,"completion_tokens":10,"total_tokens":100}}
        if fault=="usage_unknown":payload.pop("usage")
        return httpx.Response(200,content=json.dumps(payload,ensure_ascii=False).encode("utf-8"))
    def factory(request):
        return probe.clients.make_client_factory(request,http_client_factory=lambda **kwargs:httpx.Client(
            transport=httpx.MockTransport(handler),**kwargs))
    source=project/"source.txt";source.write_text("offline historical diagnostic",encoding="utf-8")
    runtime=probe.adapter.GoalContextRuntime(project,root,[source],deepcopy(probe.INHERITED),
        profile=probe.read(probe.PROFILE),stage_limits=deepcopy(probe.STAGE_LIMITS),
        client_factory_builder=factory,quota_state=None,
        admission=lambda label,request,ledger:CountedExecution(probe.COUNTED_ROOT).assert_dispatch_allowed(probe.COUNTED_KEY))
    runtime.prepare();probe.write(root/"PREPARED_PROBE.json",prepared,True)
    monkeypatch.setattr(probe,"get_runtime",lambda:runtime)
    return runtime,root,sends,counter,prepared


def test_actual_known_cases_blinded_expected_and_history_never_in_wire():
    prepared=probe.prepare_probe();payload=json.loads(prepared["request"]["messages"][1]["content"])
    assert len(payload["cases"])==12 and set(payload["cases"])==set(prepared["blind_case_mapping"])
    assert list(prepared["blind_case_mapping"].values())!=[row["case_id"] for row in probe.read(probe.CASES)["cases"]]
    assert all(set(row)=={"target","same_goal_context"} for row in payload["cases"].values())
    assert "expected" not in payload and "verified_legal_context_snapshot" not in payload
    assert prepared["wire"]==probe.clients.expected_wire_request(prepared["request"])
    assert prepared["request"]["parameters"]["max_completion_tokens"]==8000
    assert prepared["request"]["parameters"]["thinking"]=="disabled"
    assert "strict" not in prepared["wire"]["tools"][0]["function"]
    assert probe.prepare_probe()==prepared


def test_preview_binds_cases_and_wire_without_claiming_full_historical_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,"PREVIEW",tmp_path/"preview_v2.json")
    monkeypatch.setattr(probe,"APPROVAL",tmp_path/"AUTH.json")
    def must_not_run():raise AssertionError("preview must not perform the full historical guard")
    monkeypatch.setattr(probe,"historical_parent_guard",must_not_run)
    assert probe.main(["preview"])==0
    assert probe.read(probe.PREVIEW)["full_historical_guard_not_certified_by_preview"]
    assert not probe.APPROVAL.exists()


def test_register_requires_full_historical_guard_before_writing_authority(tmp_path,monkeypatch):
    monkeypatch.setattr(probe,"PREVIEW",tmp_path/"preview_v2.json")
    monkeypatch.setattr(probe,"APPROVAL",tmp_path/"AUTH.json")
    def blocked_guard():raise ValueError("historical integrity must be established")
    monkeypatch.setattr(probe,"historical_parent_guard",blocked_guard)
    with pytest.raises(ValueError,match="historical integrity"):probe.main(["register"])
    assert not probe.PREVIEW.exists() and not probe.APPROVAL.exists()


def test_all_binary_routes_pass_fine_nonlegal_disagreement_is_separate():
    prepared=probe.prepare_probe()
    result=probe.evaluate(native_response(prepared,alternate_nonlegal=True),prepared)
    assert result["accepted"] and result["positive_routing_correct"]==3 and result["nonlegal_false_positives"]==0
    assert result["fine_class_correct"]<12 and not result["source618_approved"]


@pytest.mark.parametrize("case_id",["SA01","SA02","SA04","SA05","SA12"])
def test_binary_positive_omission_or_nonlegal_false_positive_fails(case_id):
    prepared=probe.prepare_probe()
    decision=probe.evaluate(native_response(prepared,misclassify=case_id),prepared)
    assert not decision["accepted"]


def test_positive_empty_asserted_proposition_does_not_count_as_correct_route():
    prepared=probe.prepare_probe()
    assert not probe.evaluate(native_response(prepared,empty_positive=True),prepared)["accepted"]


def test_nonlegal_label_cannot_hide_invented_legal_proposition():
    prepared=probe.prepare_probe();native=native_response(prepared)
    row=next(row for row in native["classifications"].values() if row["speech_act"] not in ("L","U"))
    row["asserted_legal_proposition"]="A legal proposition not asserted by this nonlegal target"
    result=probe.evaluate(native,prepared)
    assert not result["accepted"] and result["nonlegal_proposition_contradictions"]==1


def test_one_actual_sdk_call_saves_raw_wire_and_inherits619_usage(tmp_path,monkeypatch):
    runtime,root,sends,counter,prepared=replay(tmp_path,monkeypatch)
    result=probe.run()
    assert result["status"]=="historical_probe_routing_passed_not_production",result
    assert len(sends)==1 and sends[0]==prepared["wire"]
    assert result["spend"]["effective_calls_started"]==620
    assert result["spend"]["effective_reported_tokens"]==12931023
    assert result["spend"]["effective_calls_with_known_usage"]==618
    assert result["spend"]["historical_pending_ordinals"]==[70,160]
    assert result["spend"]["unknown_token_reservations"]==93117
    assert not result["current_source_freshness_passed"] and not result["text_ready_for_director"]
    assert result["next_production_must_inherit_probe_consumption"]
    ledger=probe.read(runtime.ledger);old=runtime.ledger.read_bytes()
    directory=runtime.evidence_path(620)
    proof=probe.read(directory/"M31_WIRE_PREFLIGHT.json")
    assert proof["SDK_max_retries"]==0 and proof["HTTP_follow_redirects"] is False
    assert (directory/"request_body.raw").exists() and (directory/"response_body.raw").exists()
    with pytest.raises(FileExistsError):probe.run()
    assert runtime.ledger.read_bytes()==old and len(sends)==1


@pytest.mark.parametrize("fault",["transport_unknown","usage_unknown","truncated","missing_tool","contract"])
def test_probe_failure_is_single_submission_no_recovery_or_full_source(tmp_path,monkeypatch,fault):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,fault=fault)
    result=probe.run()
    assert result["status"]==("halt_probe_contract_requires_diagnosis" if fault=="contract" else "halt_probe_interface_or_unknown"),result
    assert len(sends)==1 and len(probe.read(runtime.ledger)["calls"])==1
    assert not result["source618_approved"] and not (root/"TEXT_HANDOFF.json").exists()
    old=runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):probe.run()
    assert runtime.ledger.read_bytes()==old and len(sends)==1


def test_semantic_fail_saved_no_automatic_new_probe(tmp_path,monkeypatch):
    runtime,root,sends,_,_=replay(tmp_path,monkeypatch,misclassify="SA01")
    result=probe.run()
    assert result["status"]=="halt_historical_probe_routing_failed",result
    assert not probe.read(root/"PROBE_DECISION.json")["accepted"] and len(sends)==1


def test_stopped_counter_prevents_probe_claim_and_send(tmp_path,monkeypatch):
    runtime,root,sends,counter,_=replay(tmp_path,monkeypatch)
    evidence=root/"STOP.txt";evidence.write_text("stop",encoding="utf-8")
    counter.stop("ten_reviews_completed",evidence)
    with pytest.raises(ValueError,match="execution stopped"):probe.run()
    assert not sends and not (root/"RUN_CLAIM.json").exists() and not probe.read(runtime.ledger)["calls"]


def test_probe_counter_stop_inside_runtime_check_blocks_before_budget_claim(tmp_path,monkeypatch):
    runtime,root,sends,counter,_=replay(tmp_path,monkeypatch)
    check=runtime.check
    def stopped_check(ledger):
        check(ledger)
        evidence=root/"STOP_INSIDE_RUNTIME.txt";evidence.write_text("stop at inner dispatch",encoding="utf-8")
        counter.stop("ten_reviews_completed",evidence)
    monkeypatch.setattr(runtime,"check",stopped_check)
    with pytest.raises(ValueError,match="execution stopped"):probe.run()
    assert not sends and not probe.read(runtime.ledger)["calls"]
