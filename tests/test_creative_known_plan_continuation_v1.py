"""Offline known-result continuation; mocks do not establish creative quality."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_known_plan_continuation_v1 as continuation
from tests import test_creative_fresh_legal_text_pipeline_v1 as fixtures


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("no network"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no network"))


def serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def identity(receipt):
    return {"ordinal": receipt["ordinal"], "label": receipt["label"],
        "request_sha256": receipt["request_sha256"], "source_binding_sha256": receipt["source_binding_sha256"],
        "role": receipt["request"]["role"], "model": receipt["request"]["model"]}


def native_missing(receipt):
    result = deepcopy(receipt)
    content = json.dumps(result.pop("output"), ensure_ascii=False)
    result["status"] = "interface_rejected"
    result["failure"] = {"code": "REQUIRED_TOOL_MISSING", "category": "interface", "response_received": True,
        "provider_outcome_known": True, "cause_code": "REQUIRED_TOOL_MISSING"}
    result["response_text"] = None
    role, model = result["request"]["role"], result["request"]["model"]
    result["response_payload"] = {"id": "fixture", "model": model, "choices": [{"finish_reason": "stop",
        "message": {"content": content, "role": "assistant"}}], "usage": {"total_tokens": 100},
        "base_resp": {"status_code": 0}}
    result["response_metadata"].update(finish_reason="stop", provider_status_code=0,
        role=role, requested_model=model, response_model=model, provider="minimax" if role == "writer" else "deepseek",
        response_fault_code="REQUIRED_TOOL_MISSING", raw_body_sha256=hashlib.sha256(serialize(result["response_payload"])).hexdigest())
    result["call_evidence"] = {"identity_sha256": continuation.digest(identity(result))}
    return result


@pytest.fixture
def original(tmp_path):
    def theme_bad(value):
        value["characters"][0]["profile"].pop("wardrobe")
        return value
    def plan_bad(value):
        value["source_obligations"][0]["actor_id"] = ["", ""]
        return value
    case = fixtures.inputs()
    service = fixtures.Service(case, {"fresh_theme_01": theme_bad, "fresh_plan_01": plan_bad,
        "receipt:fresh_plan_02": native_missing})
    state = fixtures.fresh.FreshLegalTextPipeline(invoke=service.invoke, persist_state=service.persist).run(**case)
    assert state["status"] == "halt_required_tool_missing" and state["versions"] == {"theme": 2, "plan": 2, "draft": 0}
    receipt = state["receipts"][-1]
    directory = tmp_path / "original_evidence"
    directory.mkdir()
    wire = {"model": "MiniMax-M3", "messages": deepcopy(receipt["request"]["messages"]),
        "tools": [{"name": "fixture_tool", "schema": receipt["request"]["structured_schema"]}]}
    ident = identity(receipt)
    (directory / "IDENTITY.json").write_bytes(serialize({"identity": ident, "identity_sha256": continuation.digest(ident)}))
    for prefix, body in (("REQUEST", wire), ("RESPONSE", receipt["response_payload"])):
        raw = serialize(body)
        (directory / (prefix.lower() + "_body.raw")).write_bytes(raw)
        manifest = {"identity_sha256": continuation.digest(ident), "body_file": prefix.lower() + "_body.raw",
            "body_complete": True, "raw_bytes_preserved": True, "credential_redacted": False,
            "bytes": len(raw), "original_sha256": hashlib.sha256(raw).hexdigest(), "stored_sha256": hashlib.sha256(raw).hexdigest(),
            "http_metadata": {"http_status_code": 200}}
        (directory / (prefix + "_BODY_MANIFEST.json")).write_bytes(serialize(manifest))
    raw_receipt = serialize(receipt)
    kwargs = {"receipt_bytes": raw_receipt, "evidence_directory": directory,
        "expected_receipt_sha256": hashlib.sha256(raw_receipt).hexdigest(),
        "expected_source_binding_sha256": fixtures.BINDING, "expected_wire": wire}
    return {"case": case, "state": state, "receipt": receipt, "directory": directory, "seed_kwargs": kwargs,
        "seed": continuation.compile_missing_tool_seed(receipt, **kwargs)}


OPERATOR = {"operator_freeze_sha256": "d" * 64, "projection_sha256": "e" * 64}


def project(payload):
    value = deepcopy(payload)
    value["source_packet"] = {"schema": "offline_compact/v1", "source_sha": fixtures.BINDING,
        "candidate": deepcopy(value["source_packet"]["candidate"])}
    return value


class Service(fixtures.Service):
    def invoke(self, label, request, validate):
        assert self.states[-1]["format_recovery_claims"]["plan"]["original_ordinal"] == 524
        result = super().invoke(label, request, validate)
        result["ordinal"] = 524 + len(self.calls)
        result["call_evidence"] = {"identity_sha256": continuation.digest(identity(result))}
        return result


def execute(original, modifications=None, projector=project, guard=lambda: None, seed_factory=None):
    service = Service(original["case"], modifications)
    pipeline = continuation.KnownPlanContinuation(invoke=service.invoke, persist_state=service.persist,
        payload_projector=projector, operator_binding=OPERATOR, format_recovery_authorization=fixtures.format_auth(),
        resume_guard=guard, format_seed_factory=seed_factory)
    result = pipeline.run_from_known_plan(resume_state=original["state"], format_seed=original["seed"], **original["case"])
    return result, service


def evidence_for(receipt, directory, wire):
    directory.mkdir(exist_ok=True)
    ident = identity(receipt)
    (directory / "IDENTITY.json").write_bytes(serialize({"identity":ident,"identity_sha256":continuation.digest(ident)}))
    for prefix, value in (("REQUEST",wire),("RESPONSE",receipt["response_payload"])):
        raw = serialize(value)
        (directory / (prefix.lower() + "_body.raw")).write_bytes(raw)
        (directory / (prefix + "_BODY_MANIFEST.json")).write_bytes(serialize({
            "identity_sha256":continuation.digest(ident),"body_file":prefix.lower()+"_body.raw",
            "body_complete":True,"raw_bytes_preserved":True,"credential_redacted":False,
            "bytes":len(raw),"original_sha256":hashlib.sha256(raw).hexdigest(),
            "stored_sha256":hashlib.sha256(raw).hexdigest(),"http_metadata":{"http_status_code":200}}))
    raw = serialize(receipt)
    return dict(receipt_bytes=raw,evidence_directory=directory,
        expected_receipt_sha256=hashlib.sha256(raw).hexdigest(),expected_source_binding_sha256=fixtures.BINDING,
        expected_wire=wire)


@pytest.mark.parametrize("case,accepted", [("deepseek_absent",True),("deepseek_zero",True),
    ("writer_absent",False),("provider_error",False),("bool_status",False),
    ("absent_body_present_metadata",False),("wrong_response_model",False),("wrong_request_model",False)])
def test_provider_specific_known_outcome_and_exact_model_binding(original,case,accepted):
    receipt = deepcopy(original["receipt"])
    request,body,meta = receipt["request"],receipt["response_payload"],receipt["response_metadata"]
    if case != "writer_absent":
        request.update(role="director",model="deepseek-flash")
        request["input_provenance"]["phase"] = "review"
        body["model"] = "deepseek-v4.1-flash"
        meta.update(role="director",provider="deepseek",requested_model="deepseek-flash",response_model=body["model"])
    if case in ("deepseek_absent","writer_absent","absent_body_present_metadata"):
        body.pop("base_resp")
        if case != "absent_body_present_metadata": meta.pop("provider_status_code")
    if case == "provider_error": body["base_resp"]["status_code"] = meta["provider_status_code"] = 17
    if case == "bool_status": body["base_resp"]["status_code"] = meta["provider_status_code"] = False
    if case == "wrong_response_model": body["model"] = meta["response_model"] = "other-model"
    if case == "wrong_request_model": request["model"] = meta["requested_model"] = "other-model"
    meta["raw_body_sha256"] = hashlib.sha256(serialize(body)).hexdigest()
    receipt["request_sha256"] = continuation.digest(request)
    receipt["call_evidence"]["identity_sha256"] = continuation.digest(identity(receipt))
    kwargs = evidence_for(receipt,original["directory"],{"model":request["model"],"messages":request["messages"]})
    if accepted:
        seed = continuation.compile_missing_tool_seed(receipt,**kwargs)
        assert seed["original_reported_tokens"] == 100 and seed["plain_content_adopted_as_tool"] is False
    else:
        with pytest.raises(ValueError): continuation.compile_missing_tool_seed(receipt,**kwargs)


def test_actual_frozen_524_raw_compiles_separate_seed_without_receipt_mutation():
    from scripts import run_fresh_legal_full_flow_v1 as root_module
    root = root_module.DEFAULT_ROOT
    ledger = root_module.control.read(root / "CALL_LEDGER.json")
    row = next(r for r in ledger["calls"] if r["ordinal"] == 524)
    path = root / row["receipt"]
    before = path.read_bytes()
    receipt = root_module.control.read(path)
    runtime = object.__new__(root_module.control.ContinuationRuntime)
    runtime.root = root
    seed = continuation.compile_missing_tool_seed(receipt, receipt_bytes=before,
        evidence_directory=runtime.evidence_path(524), expected_receipt_sha256=row["receipt_sha256"],
        expected_source_binding_sha256=receipt["source_binding_sha256"],
        expected_wire=root_module.clients.expected_wire_request(receipt["request"]),
        verifier=lambda r, q: root_module.verify_receipt_evidence(runtime, r, q))
    assert len(seed["original_response_text"]) == 5801 and receipt["response_text"] is None
    assert seed["plain_content_adopted_as_tool"] is False and path.read_bytes() == before


@pytest.mark.parametrize("fault", ["receipt_sha", "source", "wire", "response_bytes", "request_bytes", "identity", "redacted", "manifest_sha"])
def test_raw_seed_rejects_changed_binding_or_evidence(original, fault):
    kwargs = deepcopy(original["seed_kwargs"])
    directory = original["directory"]
    if fault == "receipt_sha": kwargs["expected_receipt_sha256"] = "f" * 64
    elif fault == "source": kwargs["expected_source_binding_sha256"] = "f" * 64
    elif fault == "wire": kwargs["expected_wire"]["model"] = "other"
    elif fault in ("response_bytes", "request_bytes"):
        path = directory / ("response_body.raw" if fault == "response_bytes" else "request_body.raw")
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "identity": (directory / "IDENTITY.json").write_bytes(serialize({"identity": {}, "identity_sha256": "f" * 64}))
    else:
        path = directory / "RESPONSE_BODY_MANIFEST.json"
        value = json.loads(path.read_bytes())
        value["credential_redacted" if fault == "redacted" else "stored_sha256"] = True if fault == "redacted" else "f" * 64
        path.write_bytes(serialize(value))
    with pytest.raises(ValueError): continuation.compile_missing_tool_seed(original["receipt"], **kwargs)


@pytest.mark.parametrize("field,value", [("finish_reason", "length"), ("total_tokens", None), ("total_tokens", True), ("response_body_complete", False)])
def test_unknown_or_truncated_original_never_becomes_recovery_seed(original, field, value):
    receipt = deepcopy(original["receipt"])
    receipt["response_metadata"][field] = value
    kwargs = deepcopy(original["seed_kwargs"])
    kwargs.update(receipt_bytes=serialize(receipt), expected_receipt_sha256=hashlib.sha256(serialize(receipt)).hexdigest())
    with pytest.raises(ValueError): continuation.compile_missing_tool_seed(receipt, **kwargs)


def test_format_claim_precedes_new_dispatch_and_counters_are_not_reset(original):
    before = deepcopy(original["state"])
    result, service = execute(original)
    assert result["status"] == "text_ready_for_director" and len(service.calls) == 3
    assert result["versions"] == {"theme": 2, "plan": 2, "draft": 1}
    assert result["receipts"][:4] == before["receipts"] and result["new_model_calls"] == 7
    assert result["known_reported_tokens"] == 700 and result["human_quality_approved"] is False
    assert result["continuation_new_model_calls"] == 3 and result["continuation_known_reported_tokens"] == 300
    assert result["receipts"][4]["label"] == "fresh_plan_02_format_recovery"
    assert any(s["status"] == "format_recovery_claimed" and len(s["events"]) == len(before["events"]) for s in service.states)
    request = service.calls[0]
    old = before["receipts"][-1]["request"]
    assert request["structured_schema"] == old["structured_schema"] and request["parameters"] == old["parameters"]
    a, b = json.loads(old["messages"][1]["content"]), json.loads(request["messages"][1]["content"])
    assert {k:v for k,v in a.items() if k != "source_packet"} == {k:v for k,v in b.items() if k != "source_packet"}
    assert json.loads(request["messages"][-1]["content"])["format_recovery_original_response"] == original["seed"]["original_response_text"]
    assert request["input_provenance"]["additive_operator_scope"] == OPERATOR
    assert original["state"] == before


@pytest.mark.parametrize("fault", ["claim", "versions", "receipt", "event", "brief", "seed"])
def test_restart_changed_or_consumed_state_stops_without_dispatch(original, fault):
    if fault == "claim": original["state"]["format_recovery_claims"]["plan"] = {"original_ordinal":524}
    elif fault == "versions": original["state"]["versions"]["plan"] = 0
    elif fault == "receipt": original["state"]["receipts"][0]["request_sha256"] = "f" * 64
    elif fault == "event": original["state"]["events"].append({"event":"claim","label":"unresolved"})
    elif fault == "brief": original["state"]["brief"]["audience_feeling"] += "edited"
    elif fault == "seed": original["seed"]["original_response_text"] += "edited"
    with pytest.raises(ValueError): execute(original)


def test_native_documents_cannot_be_edited_by_source_projector(original):
    def bad(payload):
        value = project(payload)
        value["brief"]["audience_feeling"] += "edited"
        return value
    with pytest.raises(ValueError, match="native creative"): execute(original, projector=bad)


def test_format_failure_is_terminal_without_using_third_native_plan(original):
    result, service = execute(original, {"receipt:fresh_plan_02_format_recovery": native_missing})
    assert result["status"] == "halt_format_recovery_failed" and len(service.calls) == 1
    assert result["versions"] == {"theme":2,"plan":2,"draft":0}
    assert result["format_recovery_claims"]["plan"]["original_ordinal"] == 524


def test_unknown_new_usage_stops_without_repeat(original):
    def unknown(receipt):
        receipt["response_metadata"]["total_tokens"] = None
        return receipt
    result, service = execute(original, {"receipt:fresh_plan_02_format_recovery": unknown})
    assert result["status"] == "halt_result_or_usage_unknown" and len(service.calls) == 1
    assert result["versions"]["plan"] == 2 and result["format_recovery_claims"]["plan"]


def test_external_resume_guard_blocks_before_service(original):
    def blocked(): raise ValueError("durable continuation claim already consumed")
    result, service = execute(original, guard=blocked)
    assert result["status"] == "halt_additive_preflight_failed" and service.calls == []
    assert result["format_recovery_claims"]["plan"]


def test_review_failure_generates_complete_new_script_then_full_review(original):
    def fail(review):
        fixtures.fail_dialogue(review)
        return review
    result, service = execute(original, {"fresh_full_review_01":fail})
    assert result["status"] == "text_ready_for_director" and result["versions"]["draft"] == 2
    assert [r["label"] for r in result["receipts"][4:]] == ["fresh_plan_02_format_recovery","fresh_draft_01","fresh_full_review_01","fresh_draft_02","fresh_full_review_02"]
    revised = json.loads(service.calls[3]["messages"][1]["content"])
    assert revised["previous_complete_document"]["beats"] == result["script"]["beats"]
    assert revised["revision_requirements"]


def test_three_full_draft_limit_is_not_extended_by_repair_entry(original):
    def fail(review):
        fixtures.fail_dialogue(review)
        return review
    result, service = execute(original, {"fresh_full_review_0" + str(i):fail for i in (1,2,3)})
    assert result["status"] == "creative_stalled" and result["versions"]["draft"] == 3
    assert len(service.calls) == 7 and not any(r["label"] == "fresh_draft_04" for r in result["receipts"])


def test_plan_semantic_failure_uses_only_remaining_third_complete_native_plan(original):
    def reject(review):
        review["plan_support"][0].update(status="fail",required_revision="完整新计划纠正源义务。")
        return review
    result,service = execute(original,{"fresh_full_review_01":reject})
    assert result["status"] == "text_ready_for_director" and result["versions"] == {"theme":2,"plan":3,"draft":2}
    assert [r["label"] for r in result["receipts"][4:]] == ["fresh_plan_02_format_recovery","fresh_draft_01",
        "fresh_full_review_01","fresh_plan_03","fresh_draft_02","fresh_full_review_02"]
    payload = json.loads(service.calls[3]["messages"][1]["content"])
    assert payload["previous_complete_document"] == result["receipts"][4]["output"]
    assert payload["revision_requirements"][0]["target"] == "plan"


def test_plan_capacity_exhaustion_cannot_add_fourth_plan_after_format_recovery(original):
    def reject(review):
        review["plan_support"][0].update(status="fail",required_revision="完整新计划纠正源义务。")
        return review
    result,service = execute(original,{"fresh_full_review_01":reject,"fresh_full_review_02":reject})
    assert result["status"] == "plan_stalled" and result["versions"] == {"theme":2,"plan":3,"draft":2}
    assert len(service.calls) == 6 and not any(r["label"] == "fresh_plan_04" for r in result["receipts"])


def test_future_parser_none_uses_verified_seed_factory_without_reprojecting_compact_packet(original):
    seen = []
    def factory(receipt):
        seen.append(receipt["label"])
        directory = original["directory"].parent / ("future_" + str(receipt["ordinal"]))
        wire = {"fixture":True,"request_sha256":receipt["request_sha256"]}
        return continuation.compile_missing_tool_seed(receipt,**evidence_for(receipt,directory,wire))
    result, service = execute(original,{"receipt:fresh_draft_01":native_missing},seed_factory=factory)
    assert result["status"] == "text_ready_for_director" and result["versions"]["draft"] == 1
    assert seen == ["fresh_draft_01"] and set(result["format_recovery_claims"]) == {"plan","draft"}
    assert [r["label"] for r in result["receipts"][4:]] == ["fresh_plan_02_format_recovery","fresh_draft_01","fresh_draft_01_format_recovery","fresh_full_review_01"]
    assert service.calls[2]["input_provenance"]["single_format_recovery_of"] == 526


def test_review_parser_none_without_provider_status_supports_single_same_phase_format_recovery(original):
    def review_missing(receipt):
        value = native_missing(receipt)
        value["response_payload"].pop("base_resp")
        value["response_metadata"].pop("provider_status_code")
        value["response_metadata"]["raw_body_sha256"] = hashlib.sha256(serialize(value["response_payload"])).hexdigest()
        return value
    seen = []
    def factory(receipt):
        seen.append(receipt["ordinal"])
        return continuation.compile_missing_tool_seed(receipt,**evidence_for(receipt,
            original["directory"].parent / "review_evidence",{"request_sha256":receipt["request_sha256"]}))
    result,service = execute(original,{"receipt:fresh_full_review_01":review_missing},seed_factory=factory)
    assert result["status"] == "text_ready_for_director" and seen == [527]
    assert set(result["format_recovery_claims"]) == {"plan","review"}
    assert len(service.calls) == 4 and result["versions"] == {"theme":2,"plan":2,"draft":1}
    assert result["source_review_binding"]["review_ordinal"] == 528


def test_future_evidence_read_failure_persists_stop_without_format_dispatch(original):
    def unavailable(receipt): raise OSError("raw evidence unavailable")
    result,service = execute(original,{"receipt:fresh_draft_01":native_missing},seed_factory=unavailable)
    assert result["status"] == "halt_format_seed_invalid" and len(service.calls) == 2
    assert set(result["format_recovery_claims"]) == {"plan"}


def test_unknown_source_packet_is_blocked_before_format_claim(original):
    original["case"]["packet"]["sample_gate"]["passed"] = False
    with pytest.raises(ValueError): execute(original)
