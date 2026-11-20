"""One-call single-record probe; original modules remain unchanged."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_single_scope_probe_v2 as flow
from scripts import creative_single_scope_probe_spend_anchor_v2 as spend
from src.content_factory.creative_counted_execution_v1 import CountedExecution

REAL = Path(__file__).resolve().parents[1]
DATA = REAL / "data/qa/creative_source624_diagnosis_20261015"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("Only offline MockTransport permitted")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(flow.clients, "role_config", lambda role: SimpleNamespace(model="deepseek-flash",
        base_url="https://api.deepseek.com/v1", api_key="offline-single-scope-not-real"))


def setup_probe(tmp_path, monkeypatch, *, fault=None, parent_used=1):
    monkeypatch.setattr(flow, "PROJECT", tmp_path); monkeypatch.setattr(spend, "PROJECT", tmp_path)
    copies = ((flow, "scripts/creative_single_scope_probe_v2.py"), (spend, "scripts/creative_single_scope_probe_spend_anchor_v2.py"),
        (flow.policy, "scripts/creative_scope_probe_execution_policy_v1.py"), (flow.scope, "src/content_factory/creative_legal_speech_scope_v2.py"))
    for module, name in copies:
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REAL / name).read_bytes()); monkeypatch.setattr(module, "__file__", str(target))
    profile = tmp_path / "PROFILE.json"; profile.write_bytes((REAL / "config/creative_legal_scope_probe_profile_v1.json").read_bytes())
    blind = flow.read(DATA / "BLINDED_CASES_v2.json"); private = flow.read(DATA / "BOUNDARY_CASES_PRIVATE_EXPECTATIONS_v2.json")
    flow.write(tmp_path / "BLIND.json", blind); flow.write(tmp_path / "PRIVATE.json", private)
    inherited = {"calls_started": 17, "reported_tokens": 1000, "calls_with_known_usage": 15,
        "pending_ordinals": [3, 7], "unknown_token_reservations": 91}
    parent = tmp_path / "settled_parent"; parent.mkdir()
    for name, value in (("ORIGINAL_BLIND", blind), ("ORIGINAL_PRIVATE", private), ("ORIGINAL_PROFILE", flow.read(profile))):
        flow.write(parent / (name + ".json"), value)
    flow.write(parent / "PROBE_CONFIG.json", {"blinded_cases_path": str(parent / "ORIGINAL_BLIND.json"),
        "private_expectations_path": str(parent / "ORIGINAL_PRIVATE.json"), "profile_path": str(parent / "ORIGINAL_PROFILE.json")})
    flow.write(parent / "PREPARED_PROBE.json", {"requests": [flow.first._prepared(blind, flow.read(profile), case_frame=True)]})
    for name in ("STATE", "CALL_LEDGER", "PRODUCTION_FREEZE"): flow.write(parent / (name + ".json"), {"offline": True})
    identity = {"root": str(parent), "terminal_state_sha256": flow.sha_file(parent / "STATE.json"),
        "native_ledger_sha256": flow.sha_file(parent / "CALL_LEDGER.json"),
        "production_freeze_sha256": flow.sha_file(parent / "PRODUCTION_FREEZE.json"), "end_ordinal": 17}
    anchor = {"schema": spend.prior.VERSION, "root": str(parent), "inherited": inherited, "scope_probe_calls_used": parent_used,
        "parent_identity": identity, "parent_identity_sha256": flow.digest(identity), "whole_goal_candidates_used": 3,
        "inherited_whole_goal_candidates_used": 32, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "latest_native_goal_receipt": {"root": str(parent), "receipt": "native_goal.json", "ordinal": 16, "native_goal_sha256": "0" * 64}}
    flow.write(tmp_path / "PARENT.json", anchor)
    def verify(value, *, expected_anchor_sha256, ancestors=()):
        assert flow.digest(value) == expected_anchor_sha256
        if value.get("schema") == spend.VERSION:
            return spend.verify_probe_spend_anchor(value, expected_anchor_sha256=expected_anchor_sha256, _ancestors=ancestors)
        return {"verified": True, "inherited": deepcopy(value["inherited"])}
    monkeypatch.setattr(spend, "verify_parent_anchor", verify)
    for name in ("AUTHORIZATION_AND_CADENCE_v1", "USER_COUNT_UNIT_CONFIRMATION_v1"):
        flow.write(tmp_path / (name + ".json"), {"offline": True})
    counter = CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("single-scope-round", "offline single-record scope diagnostic")
    config = flow.ProbeConfig(str(tmp_path / "run"), str(tmp_path / "PARENT.json"), flow.digest(anchor),
        str(tmp_path / "BLIND.json"), str(tmp_path / "PRIVATE.json"), str(tmp_path), "single-scope-round",
        "offline-single-scope", str(tmp_path / "AUTH.json"), str(profile))
    seen = []
    def factory(request):
        def respond(outgoing):
            seen.append(json.loads(outgoing.read()))
            if fault == "transport": raise httpx.ReadTimeout("offline unknown", request=outgoing)
            p = request["structured_schema"]["properties"]
            output = {k: p[k]["const"] for k in ("schema", "frame_kind", "input_sha256", "scope_context_sha256")}
            expected = {r["input"]["case_id"]: r["private_expectation"] for r in private["cases"]}
            records = {}
            for case in blind["cases"]:
                ref = case["source_ref"]; preference = expected[private["blind_case_mapping"][ref]]
                legal = preference["hard_gate"] and preference["law_route"] == "legal_or_uncertain"
                records[ref] = {"act": "L", "detail": {"quote": case["text"], "proposition": "只用于离线结构验证的法律命题",
                    "assertion_scope": "case_application", "expression": "explicit", "reason": "不证明法律真伪或语义可靠"}} if legal else {"act": "F"}
            if fault == "route":
                ref = "T20"; quote = next(c["text"] for c in blind["cases"] if c["source_ref"] == ref)
                records[ref] = {"act": "U", "detail": {"quote": quote, "nonlegal_reading": "主观担忧", "legal_reading": "旁白宣告法律效果",
                    "ambiguity_reason": "刻意测试错误路由", "context_evidence": [{"source_ref": ref, "quote": quote}]}}
            if fault == "contract": records["T01"]["detail"] = {"quote": "ordinary must have no detail"}
            output["records_by_ref"] = records
            if fault == "old_native":
                output.pop("records_by_ref"); output.update(speech_act_by_ref={k: r["act"] for k, r in records.items()}, scope_observations=[])
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-single", "type": "function",
                "function": {"name": flow.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]}
            if fault == "missing_tool": message = {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            if fault == "wrong_tool": message["tool_calls"][0]["function"]["name"] = "wrong_function"
            response = {"id": "offline-single-1", "model": request["model"], "choices": [{"index": 0, "message": message,
                "finish_reason": "length" if fault == "truncated" else "stop" if fault == "missing_tool" else "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            if fault == "usage_unknown": response.pop("usage")
            return httpx.Response(200, content=json.dumps(response, ensure_ascii=False).encode())
        return flow.clients.make_client_factory(request,
            http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(respond), verify=False, **kw))
    return flow.Probe(config, parent_verifier=verify, client_factory_builder=factory), seen, counter


def prepare(probe):
    preview = probe.prepare_preview(); flow.write(probe.config.authorization_path, probe.authorization_template(preview), True)
    probe.prepare(); return preview


def test_single_native_record_request_one_call_exact_remaining_spend_and_no_full132(tmp_path, monkeypatch):
    probe, seen, counter = setup_probe(tmp_path, monkeypatch); preview = probe.prepare_preview()
    assert not probe.root.exists() and not probe.claim.exists() and not seen
    assert preview["scope_probe_calls_used"] == preview["remaining_scope_probe_calls"] == preview["new_deepseek_calls_limit"] == 1
    assert len(preview["requests"]) == 1 and preview["full_goal_calls_limit"] == 0
    payload = json.loads(preview["requests"][0]["request"]["messages"][1]["content"])
    assert payload["blinded_cases"] == flow.read(probe.config.blinded_cases_path)
    assert "private_expectation" not in json.dumps(payload) and "hard_gate" not in json.dumps(payload)
    prepare(probe); result = probe.run()
    assert result["status"] == "diagnostic_completed_not_creative" and len(seen) == 1
    assert result["spend"]["effective_calls_started"] == 18 and result["spend"]["effective_reported_tokens"] == 1100
    assert result["spend"]["stage_limits"] == flow.LIMITS and result["spend"]["historical_pending_ordinals"] == [3, 7]
    assert seen[0]["model"] == "deepseek-flash" and seen[0]["max_tokens"] == 16000
    assert "strict" not in seen[0]["tools"][0]["function"]
    ledger = flow.read(probe.root / "CALL_LEDGER.json"); receipt = flow.read(probe.root / ledger["calls"][0]["receipt"])
    assert receipt["output"]["schema"] == flow.scope.VERSION and "speech_act_by_ref" not in receipt["output"]
    assert probe.runtime().summary() == flow.policy.accounting_summary(preview["inherited"], [receipt], stage_limits=flow.LIMITS, unknown_reservations=0)
    gate = flow.read(probe.root / "CASE_GATE.json")
    assert (gate["hard_correct"], gate["hard_total"], gate["observational_total"]) == (17, 17, 3)
    proof = tmp_path / "COMPLETE.json"; flow.write(proof, {"offline": True})
    counter.complete_round("single-scope-round", action="offline", conclusion="done", evidence_paths=[proof])
    anchor = spend.build_probe_spend_anchor(probe.root)
    assert anchor["scope_probe_calls_used"] == 2 and anchor["remaining_scope_probe_calls"] == 0
    assert anchor["inherited"] == {"calls_started": 18, "reported_tokens": 1100, "calls_with_known_usage": 16,
        "pending_ordinals": [3, 7], "unknown_token_reservations": 91}
    assert spend.verify_probe_spend_anchor(anchor, expected_anchor_sha256=flow.digest(anchor))["verified"]
    flow.write(tmp_path / "SPENT.json", anchor)
    next_probe = flow.Probe(replace(probe.config, root=str(tmp_path / "next"), parent_anchor_path=str(tmp_path / "SPENT.json"),
        parent_anchor_sha256=flow.digest(anchor)), parent_verifier=spend.verify_parent_anchor)
    with pytest.raises(ValueError, match="original two"): next_probe.prepare_preview()
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()
    with pytest.raises(ValueError, match="existing"): probe.prepare()


@pytest.mark.parametrize("fault,status,settles", [("contract", "halt_case_contract_rejected", True),
    ("old_native", "halt_case_contract_rejected", True), ("route", "halt_case_routing_mismatch", True),
    ("missing_tool", "halt_protocol_requires_diagnosis", True), ("wrong_tool", "halt_protocol_requires_diagnosis", True),
    ("transport", "halt_interface_or_unknown", False), ("usage_unknown", "halt_interface_or_unknown", False),
    ("truncated", "halt_interface_or_unknown", False)])
def test_complete_known_failure_consumes_last_call_unknown_or_truncation_not_settled(tmp_path, monkeypatch, fault, status, settles):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch, fault=fault); prepare(probe); result = probe.run()
    assert result["status"] == status and len(seen) == 1
    assert result["spend"]["effective_calls_started"] == 18 and not result["text_ready_for_director"]
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn: row = conn.execute("SELECT status,result FROM attempts").fetchone()
    if settles:
        anchor = spend.build_probe_spend_anchor(probe.root)
        assert anchor["scope_probe_calls_used"] == 2 and anchor["inherited"]["reported_tokens"] == 1100
        if fault in ("missing_tool", "wrong_tool"):
            assert row[0] == "protocol_rejected" and json.loads(row[1])["output"]["native_output"] is None
    else:
        with pytest.raises(ValueError, match="settled"): spend.build_probe_spend_anchor(probe.root)
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()


@pytest.mark.parametrize("used", [0, 2, True])
def test_parent_used_count_must_be_explicitly_one_not_reset(tmp_path, monkeypatch, used):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch, parent_used=used)
    with pytest.raises(ValueError, match="original two"): probe.prepare_preview()
    assert not seen and not probe.root.exists()


def test_different_root_and_anchor_digest_cannot_reclaim_parent(tmp_path, monkeypatch):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    value = flow.read(probe.config.parent_anchor_path); value["another_verifier_version"] = True
    path = tmp_path / "OTHER_PARENT.json"; flow.write(path, value)
    other = flow.Probe(replace(probe.config, root=str(tmp_path / "other"), grant_id="other-scope", parent_anchor_path=str(path),
        parent_anchor_sha256=flow.digest(value), authorization_path=str(tmp_path / "OTHER_AUTH.json")),
        parent_verifier=probe.parent_verifier, client_factory_builder=probe.client_factory_builder)
    flow.write(other.config.authorization_path, other.authorization_template(other.prepare_preview()))
    with pytest.raises(ValueError, match="already consumed"): other.prepare()
    assert not other.root.exists() and not other.claim.exists() and not seen


def test_round_gate_inside_dispatch_lock_retains_original_dag_claim(tmp_path, monkeypatch):
    probe, seen, counter = setup_probe(tmp_path, monkeypatch); prepare(probe)
    original = flow.policy.tasks.TaskStore.claim
    def stop(*a, **k):
        result = original(*a, **k); proof = tmp_path / "STOP.json"; flow.write(proof, {"offline": True})
        counter.stop("offline after claim", proof); return result
    monkeypatch.setattr(flow.policy.tasks.TaskStore, "claim", stop)
    with pytest.raises(ValueError, match="execution stopped"): probe.run()
    assert not seen and not flow.read(probe.root / "CALL_LEDGER.json")["calls"]
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn:
        assert conn.execute("SELECT status FROM attempts").fetchone()[0] == "claimed"
    assert flow.read(probe.root / "STATE.json")["status"] == "halt_execution_reconciliation"


@pytest.mark.parametrize("target", ["task_output", "run_pid", "config"])
def test_original_task_run_and_config_binding_are_checked(tmp_path, monkeypatch, target):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    if target == "config":
        rebound = flow.Probe(replace(probe.config, private_expectations_path=str(tmp_path / "other.json")),
            parent_verifier=probe.parent_verifier, client_factory_builder=probe.client_factory_builder)
        with pytest.raises(ValueError, match="config"): rebound._guard()
        assert not seen; return
    probe.run()
    if target == "run_pid":
        value = flow.read(probe.root / "RUN_CLAIM.json"); value["pid"] += 1; flow.write(probe.root / "RUN_CLAIM.json", value)
    else:
        with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn:
            row = conn.execute("SELECT result FROM attempts").fetchone(); value = json.loads(row[0])
            value["output"]["native_output"]["records_by_ref"]["T01"] = {"act": "L"}
            conn.execute("UPDATE attempts SET result=?,result_sha=?", (json.dumps(value), flow.digest(value)))
    with pytest.raises(ValueError): spend.build_probe_spend_anchor(probe.root)


@pytest.mark.parametrize("change", ["target", "role_context"])
def test_changed_cases_even_with_rehashed_private_gate_refused_before_claim(tmp_path, monkeypatch, change):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch)
    blind = flow.read(probe.config.blinded_cases_path); private = flow.read(probe.config.private_expectations_path)
    if change == "target":
        blind["cases"][0]["text"] += "这是被替换的新目标句。"
        cid = private["blind_case_mapping"][blind["cases"][0]["source_ref"]]
        next(r for r in private["cases"] if r["input"]["case_id"] == cid)["input"]["target_quote"] = blind["cases"][0]["text"]
    else: blind["cases"][0]["role_context"] += "新说话归属。"
    private["blinded_input_canonical_sha256"] = flow.digest(blind)
    flow.write(probe.config.blinded_cases_path, blind); flow.write(probe.config.private_expectations_path, private)
    with pytest.raises(ValueError, match="controlled comparison"): probe.prepare_preview()
    assert not seen and not probe.root.exists() and not probe.claim.exists()


@pytest.mark.parametrize("mismatch", ["root", "policy", "bool_policy"])
def test_shared_helper_rejects_runtime_root_or_policy_mismatch_before_claim(tmp_path, monkeypatch, mismatch):
    probe, seen, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    runtime = probe.runtime(); item = flow.read(probe.root / "PREPARED_PROBE.json")["requests"][0]
    root = tmp_path / "wrong" if mismatch == "root" else probe.root
    limits = deepcopy(flow.LIMITS)
    if mismatch == "policy": limits["goal_audit"] = 2
    if mismatch == "bool_policy": limits["goal_audit"] = True
    with pytest.raises(ValueError, match="runtime"):
        flow.policy.dispatch_claimed(runtime, flow.LABELS[0], item, lambda x: x, root=root,
            grant_id=probe.config.grant_id, stage_limits=limits, current_round_root=probe.config.counter_root,
            current_round_key=probe.config.round_key, guard=probe._guard)
    assert not seen and not (probe.root / "TASKS.sqlite3").exists() and not (root / "requests").exists()
