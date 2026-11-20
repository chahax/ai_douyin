"""Scope diagnostic evidence tests. SDK requests use only MockTransport."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_legal_scope_probe_v1 as flow
from scripts import creative_scope_probe_spend_anchor_v1 as spend
from src.content_factory import creative_legal_speech_scope_v1 as scope
from src.content_factory.creative_counted_execution_v1 import CountedExecution

REAL = Path(__file__).resolve().parents[1]
DATA = REAL / "data/qa/creative_source624_diagnosis_20261015"
GOAL_RECEIPT = REAL / "data/production_trials/fresh_source_text_session_20261015/round_02/call_623_whole_plan_03.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("No real network in scope diagnostic tests")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(flow.clients, "role_config", lambda role: SimpleNamespace(
        model="deepseek-flash", base_url="https://api.deepseek.com/v1", api_key="offline-only-not-real"))


def native_output(request, private, *, full_ambiguity=False):
    p = request["structured_schema"]["properties"]
    payload = json.loads(request["messages"][1]["content"])
    result = {k: p[k]["const"] for k in ("schema", "frame_kind", "input_sha256", "scope_context_sha256")}
    acts = {ref: "F" for ref in p["speech_act_by_ref"]["properties"]}
    if payload["frame_kind"] == "case_batch":
        expected = {r["input"]["case_id"]: r["private_expectation"] for r in private["cases"]}
        catalog = {r["source_ref"]: {"quote": r["text"]} for r in payload["blinded_cases"]["cases"]}
        for ref, cid in private["blind_case_mapping"].items():
            if expected[cid]["hard_gate"] and expected[cid]["law_route"] == "legal_or_uncertain": acts[ref] = "L"
            # Three real ambiguities deliberately choose ordinary readings:
            # observing a different reading cannot fail the hard gate.
    else:
        from src.content_factory import creative_goal_evidence_view_v1 as views
        goal = views.reconstruct_goal(payload["native_goal_evidence_view"], expected_native_goal_sha256=payload["native_goal_sha256"])
        catalog = scope.evidence.build_evidence_catalog(goal)
        for claim in goal["claims"]:
            if claim["kind"] == "verified_legal": acts["C:" + claim["id"]] = "L"
        if full_ambiguity: acts["G055"] = "U"
    result.update(speech_act_by_ref=acts, scope_observations=[])
    for ref, act in acts.items():
        quote = catalog[ref]["quote"]
        if act == "L":
            content = {"kind": "legal_assertion", "quote": quote, "proposition": "离线合同样例的法律命题",
                "assertion_scope": "case_application", "expression": "explicit", "reason": "只测试运输和结构，不证明语义"}
        elif act == "U":
            content = {"kind": "textual_ambiguity", "quote": quote, "nonlegal_reading": "虚构人物的交易说法",
                "legal_reading": "文件具有法律效力的作者宣告", "ambiguity_reason": "两读法离线样例",
                "context_evidence": [{"source_ref": ref, "quote": quote}]}
        else: continue
        result["scope_observations"].append({"source_ref": ref, "content": content})
    return result


def setup_probe(tmp_path, monkeypatch, *, fault=None, full_ambiguity=False):
    monkeypatch.setattr(flow, "PROJECT", tmp_path); monkeypatch.setattr(spend, "PROJECT", tmp_path)
    # Freeze only real code copies within this independent offline workspace.
    for module, relative in ((flow, "scripts/creative_legal_scope_probe_v1.py"),
        (spend, "scripts/creative_scope_probe_spend_anchor_v1.py"),
        (scope, "src/content_factory/creative_legal_speech_scope_v1.py")):
        target = tmp_path / relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REAL / relative).read_bytes()); monkeypatch.setattr(module, "__file__", str(target))
    for name in ("creative_legal_scope_probe_profile_v1.json", "creative_fresh_source_session_profile_v2.json"):
        target = tmp_path / "config" / name; target.parent.mkdir(exist_ok=True)
        target.write_bytes((REAL / "config" / name).read_bytes())
    monkeypatch.setattr(flow, "DEFAULT_PROFILE", tmp_path / "config/creative_legal_scope_probe_profile_v1.json")
    blind = flow.read(DATA / "BLINDED_CASES_v2.json"); private = flow.read(DATA / "BOUNDARY_CASES_PRIVATE_EXPECTATIONS_v2.json")
    flow.write(tmp_path / "BLIND.json", blind); flow.write(tmp_path / "PRIVATE.json", private)
    parent = tmp_path / "parent"; parent.mkdir()
    receipt = flow.read(GOAL_RECEIPT); receipt["ordinal"] = 16
    flow.write(parent / "native_goal.json", receipt)
    for name in ("STATE", "CALL_LEDGER", "PRODUCTION_FREEZE"): flow.write(parent / (name + ".json"), {"offline": True})
    inherited = {"calls_started": 17, "reported_tokens": 1000, "calls_with_known_usage": 15,
        "pending_ordinals": [3, 7], "unknown_token_reservations": 91}
    identity = {"root": str(parent), "terminal_state_sha256": flow.sha_file(parent / "STATE.json"),
        "native_ledger_sha256": flow.sha_file(parent / "CALL_LEDGER.json"),
        "production_freeze_sha256": flow.sha_file(parent / "PRODUCTION_FREEZE.json"), "end_ordinal": 17}
    anchor = {"schema": spend.session.VERSION, "root": str(parent), "inherited": inherited,
        "parent_identity": identity, "parent_identity_sha256": flow.digest(identity), "whole_goal_candidates_used": 3,
        "inherited_whole_goal_candidates_used": 29, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "latest_native_goal_receipt": {"root": str(parent), "receipt": "native_goal.json", "ordinal": 16,
            "request_sha256": receipt["request_sha256"], "native_goal_sha256": flow.digest(receipt["output"])}}
    flow.write(tmp_path / "PARENT_ANCHOR.json", anchor)
    def verify(value, *, expected_anchor_sha256, ancestors=()):
        if value.get("schema") == spend.VERSION:
            return spend.verify_probe_spend_anchor(value, expected_anchor_sha256=expected_anchor_sha256, _ancestors=ancestors)
        assert flow.digest(value) == expected_anchor_sha256
        return {"verified": True, "inherited": deepcopy(value["inherited"])}
    monkeypatch.setattr(spend, "verify_parent_anchor", verify)
    for name in ("AUTHORIZATION_AND_CADENCE_v1", "USER_COUNT_UNIT_CONFIRMATION_v1"):
        flow.write(tmp_path / (name + ".json"), {"offline": True})
    counter = CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("scope-round", "offline scope diagnostic")
    config = flow.ProbeConfig(str(tmp_path / "run"), str(tmp_path / "PARENT_ANCHOR.json"), flow.digest(anchor),
        str(tmp_path / "BLIND.json"), str(tmp_path / "PRIVATE.json"), str(parent / "native_goal.json"), str(tmp_path),
        "scope-round", "offline-scope", str(tmp_path / "SCOPE_AUTH.json"), str(flow.DEFAULT_PROFILE))
    seen = []
    def factory(request):
        def respond(outgoing):
            seen.append(json.loads(outgoing.read()))
            mode = fault if len(seen) == 1 else None
            if mode == "transport": raise httpx.ReadTimeout("offline unknown", request=outgoing)
            output = native_output(request, private, full_ambiguity=full_ambiguity)
            if mode == "contract": output["speech_act_by_ref"].pop("T01")
            if mode == "route":
                ordinary = next(k for k, v in output["speech_act_by_ref"].items() if v == "F" and k not in ("T02", "T05", "T06"))
                output["speech_act_by_ref"][ordinary] = "L"
                quote = next(r["text"] for r in blind["cases"] if r["source_ref"] == ordinary)
                content = deepcopy(output["scope_observations"][0]["content"]); content["quote"] = quote
                output["scope_observations"].append({"source_ref": ordinary, "content": content})
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-tool", "type": "function",
                "function": {"name": flow.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]}
            if mode == "missing_tool": message = {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            if mode == "wrong_tool": message["tool_calls"][0]["function"]["name"] = "different_tool"
            response = {"id": "offline-scope-" + str(len(seen)), "model": request["model"], "choices": [{"index": 0,
                "message": message, "finish_reason": "length" if mode == "truncated" else "stop" if mode == "missing_tool" else "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            if mode == "usage_unknown": response.pop("usage")
            return httpx.Response(200, content=json.dumps(response, ensure_ascii=False).encode())
        return flow.clients.make_client_factory(request,
            http_client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(respond), **kwargs))
    probe = flow.Probe(config, parent_verifier=verify, client_factory_builder=factory)
    return probe, seen, counter


def prepare(probe):
    preview = probe.prepare_preview()
    flow.write(probe.config.authorization_path, probe.authorization_template(preview), True)
    probe.prepare(); return preview


def test_two_actual_sdk_calls_task_claims_full132_and_parameterized_anchor(tmp_path, monkeypatch):
    probe, seen, counter = setup_probe(tmp_path, monkeypatch)
    preview = probe.prepare_preview()
    assert not probe.root.exists() and not seen
    prepare(probe); result = probe.run()
    assert result["status"] == "diagnostic_completed_not_creative", result
    assert len(seen) == 2 and result["spend"]["effective_calls_started"] == 19
    assert result["spend"]["effective_reported_tokens"] == 1200
    assert result["spend"]["historical_pending_ordinals"] == [3, 7]
    gate = flow.read(probe.root / "CASE_GATE.json")
    assert (gate["hard_total"], gate["hard_correct"], gate["observational_total"]) == (17, 17, 3)
    assert all(r["hard_routing_correct"] is None for r in gate["results"] if r["observational_only"])
    assert preview["requests"][1]["manifest"]["source_ref_count"] == 132
    assert all(w["model"] == "deepseek-flash" and w["max_tokens"] == 16000 for w in seen)
    assert all("strict" not in w["tools"][0]["function"] for w in seen)
    assert all(json.loads(w["messages"][1]["content"])["frame_kind"] in ("case_batch", "native_goal") for w in seen)
    wire = json.dumps(seen[0], ensure_ascii=False)
    assert "private_expectation" not in wire and "hard_gate" not in wire and "provenance_kind" not in wire
    ledger = flow.read(probe.root / "CALL_LEDGER.json")
    receipts = [flow.read(probe.root / row["receipt"]) for row in ledger["calls"]]
    assert probe.runtime().summary() == flow.accounting_summary(preview["inherited"], receipts, unknown_reservations=0) == result["spend"]
    proof = tmp_path / "ROUND_COMPLETE.json"; flow.write(proof, {"offline": True})
    counter.complete_round("scope-round", action="offline", conclusion="complete", evidence_paths=[proof])
    anchor = spend.build_probe_spend_anchor(probe.root)
    assert anchor["inherited"] == {"calls_started": 19, "reported_tokens": 1200, "calls_with_known_usage": 17,
        "pending_ordinals": [3, 7], "unknown_token_reservations": 91}
    assert anchor["scope_probe_calls_used"] == 2 and anchor["whole_goal_candidates_used"] == 3
    assert str(probe.root / "TASKS.sqlite3") in anchor["verified_files"]
    assert spend.verify_probe_spend_anchor(anchor, expected_anchor_sha256=flow.digest(anchor))["verified"]
    flow.write(tmp_path / "SPENT_ANCHOR.json", anchor)
    second = flow.Probe(replace(probe.config, root=str(tmp_path / "another"), parent_anchor_path=str(tmp_path / "SPENT_ANCHOR.json"),
        parent_anchor_sha256=flow.digest(anchor)), parent_verifier=spend.verify_parent_anchor)
    with pytest.raises(ValueError, match="already consumed"): second.prepare_preview()
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()


@pytest.mark.parametrize("fault,status,calls", [("route", "halt_case_routing_mismatch", 1),
    ("contract", "halt_case_contract_rejected", 1), ("missing_tool", "halt_protocol_requires_diagnosis", 1),
    ("wrong_tool", "halt_protocol_requires_diagnosis", 1), ("transport", "halt_interface_or_unknown", 1),
    ("usage_unknown", "halt_interface_or_unknown", 1), ("truncated", "halt_interface_or_unknown", 1)])
def test_known_and_unknown_branches_no_second_dispatch_or_reset(tmp_path, monkeypatch, fault, status, calls):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch, fault=fault); preview = prepare(probe)
    result = probe.run()
    assert result["status"] == status, result
    assert len(seen) == calls and result["spend"]["effective_calls_started"] == 18
    assert result["spend"]["old_budget_reset"] is False
    ledger = flow.read(probe.root / "CALL_LEDGER.json")
    receipt = flow.read(probe.root / ledger["calls"][0]["receipt"])
    unknown = ledger["calls"][0]["token_reservation"] if fault in ("transport", "usage_unknown") else 0
    assert probe.runtime().summary() == flow.accounting_summary(preview["inherited"], [receipt], unknown_reservations=unknown)
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn:
        attempt = conn.execute("SELECT status,result FROM attempts").fetchone()
    assert attempt is not None
    if fault in ("transport", "usage_unknown", "truncated"):
        with pytest.raises(ValueError, match="settled"): spend.build_probe_spend_anchor(probe.root)
    else:
        anchor = spend.build_probe_spend_anchor(probe.root)
        assert anchor["inherited"]["reported_tokens"] == 1100 and anchor["scope_probe_calls_used"] == 1
        if fault in ("wrong_tool", "missing_tool"):
            assert attempt[0] == "protocol_rejected" and receipt.get("output") is None
            assert json.loads(attempt[1])["output"]["native_output"] is None


def test_full_known_text_ambiguity_is_cost_not_creative_approval(tmp_path, monkeypatch):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch, full_ambiguity=True); prepare(probe)
    result = probe.run()
    assert result["status"] == "halt_scope_textual_ambiguity" and len(seen) == 2
    assert spend.build_probe_spend_anchor(probe.root)["inherited"]["calls_started"] == 19
    assert result["creative_quality_passed"] is False


@pytest.mark.parametrize("target", ["task_status", "task_native", "task_identity", "run_root", "run_pid", "run_other_pid", "sdk_raw", "terminal"])
def test_original_task_sdk_and_run_identity_tamper_rejected(tmp_path, monkeypatch, target):
    probe, _, _ = setup_probe(tmp_path, monkeypatch); prepare(probe); probe.run()
    if target.startswith("task"):
        with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn:
            if target == "task_status": conn.execute("UPDATE attempts SET status='protocol_rejected' WHERE rowid=1")
            elif target == "task_identity": conn.execute("UPDATE attempts SET identity_sha=? WHERE rowid=1", ("0" * 64,))
            else:
                row = conn.execute("SELECT result FROM attempts WHERE rowid=1").fetchone()
                value = json.loads(row[0]); value["output"]["native_output"]["speech_act_by_ref"]["T01"] = "M"
                conn.execute("UPDATE attempts SET result=?,result_sha=? WHERE rowid=1", (json.dumps(value), flow.digest(value)))
    elif target.startswith("run"):
        value = flow.read(probe.root / "RUN_CLAIM.json"); value["root" if target == "run_root" else "pid"] = "wrong" if target == "run_root" else value["pid"] + 1 if target == "run_other_pid" else True
        flow.write(probe.root / "RUN_CLAIM.json", value)
    elif target == "terminal":
        value = flow.read(probe.root / "STATE.json"); value["status"] = "halt_scope_textual_ambiguity"
        flow.write(probe.root / "STATE.json", value)
    else:
        file = next((probe.root / "call_evidence").rglob("response_body.raw")); file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises((ValueError, AssertionError)): spend.build_probe_spend_anchor(probe.root)


def test_frozen_config_rebinding_and_constructor_failure_preserve_stop(tmp_path, monkeypatch):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    rebound = flow.Probe(replace(probe.config, private_expectations_path=str(tmp_path / "OTHER_PRIVATE.json")),
        parent_verifier=probe.parent_verifier, client_factory_builder=probe.client_factory_builder)
    with pytest.raises(ValueError, match="configuration"): rebound._guard()
    monkeypatch.setattr(probe, "runtime", lambda: (_ for _ in ()).throw(ValueError("offline constructor failed")))
    with pytest.raises(ValueError, match="constructor"): probe.run()
    state = flow.read(probe.root / "STATE.json")
    assert state["status"] == "halt_execution_reconciliation" and state["spend_verification_pending"] is True and not seen
    assert (probe.root / "EXECUTION_ERROR.json").exists() and (probe.root / "RUN_CLAIM.json").exists()


def test_parent_root_claim_cannot_be_regranted_by_different_anchor_digest(tmp_path, monkeypatch):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    parent = flow.read(probe.config.parent_anchor_path); parent["different_verifier_version"] = True
    path = tmp_path / "NEW_PARENT_ANCHOR.json"; flow.write(path, parent)
    other = flow.Probe(replace(probe.config, root=str(tmp_path / "different_root"), grant_id="different-grant",
        parent_anchor_path=str(path), parent_anchor_sha256=flow.digest(parent), authorization_path=str(tmp_path / "OTHER_AUTH.json")),
        parent_verifier=probe.parent_verifier, client_factory_builder=probe.client_factory_builder)
    flow.write(other.config.authorization_path, other.authorization_template(other.prepare_preview()))
    with pytest.raises(ValueError, match="already consumed"): other.prepare()
    assert not other.root.exists() and not other.claim.exists() and not seen


def test_round_gate_rechecked_inside_sdk_lock_after_real_task_claim(tmp_path, monkeypatch):
    probe, seen, counter = setup_probe(tmp_path, monkeypatch); prepare(probe)
    original = flow.tasks.TaskStore.claim
    def stop(*a, **k):
        result = original(*a, **k); proof = tmp_path / "STOP.json"; flow.write(proof, {"offline": True})
        counter.stop("offline stop between task claim and dispatch", proof); return result
    monkeypatch.setattr(flow.tasks.TaskStore, "claim", stop)
    with pytest.raises(ValueError, match="execution stopped"): probe.run()
    assert not seen and not flow.read(probe.root / "CALL_LEDGER.json")["calls"]
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn:
        assert conn.execute("SELECT status FROM attempts").fetchone()[0] == "claimed"
    assert flow.read(probe.root / "STATE.json")["status"] == "halt_execution_reconciliation"


def test_private_gate_shape_checked_before_any_claim_or_model(tmp_path, monkeypatch):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch)
    value = flow.read(probe.config.private_expectations_path)
    value["cases"][0]["private_expectation"]["allowed_speech_acts"] = ["unsupported"]
    flow.write(probe.config.private_expectations_path, value)
    with pytest.raises(ValueError, match="designation"): probe.prepare_preview()
    assert not probe.root.exists() and not probe.claim.exists() and not seen
