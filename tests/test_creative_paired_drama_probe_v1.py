"""MockTransport only; no fabricated actual story acceptance or live claim."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_paired_drama_probe_v1 as flow
from scripts import creative_paired_drama_probe_spend_anchor_v1 as spend
from src.content_factory.creative_counted_execution_v1 import CountedExecution

REAL = Path(__file__).resolve().parents[1]
ACTUAL = REAL / "data/production_trials/legal_scoped_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("Only offline MockTransport is allowed")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(flow.clients, "role_config", lambda role: SimpleNamespace(
        model="deepseek-flash", base_url="https://api.deepseek.com/v1", api_key="offline-paired-not-real"))


def unknown_mock_native(goal, request):
    """Construct new explicit UNKNOWN rows, never adopt old631 or claim pass."""
    frame = flow.workflow.paired._frame(goal)
    manifest = frame["manifest"]
    pair = {"schema": flow.workflow.paired.VERSION, "frame_kind": "goal", "goal_sha256": flow.digest(goal),
        "input_sha256": manifest["input_sha256"], "context_sha256": manifest["context_sha256"], "records_by_target": {}}
    for target, row in frame["_targets"].items():
        refs = row["required_reading_refs"]
        pair["records_by_target"][target] = {"status": "unknown", "readings": {ref: [{
            "quote": frame["_catalog"][ref]["quote"][:240], "mode": "uncertain", "actor_id": None, "object_id": None,
            "literal_reading": "OFFLINE UNKNOWN: no semantic interpretation or story approval", "state": None}] for ref in refs},
            "evidence": refs, "counterevidence": [], "transition_evidence": [],
            "comparison": "OFFLINE UNKNOWN: validates transport and stop path only", "required_revision": ""}
    first = next(iter(flow.workflow.drama_contract.build_scope_source_catalog(goal)))
    unknown = {"status": "unknown", "reason": "OFFLINE UNKNOWN, not a provider or semantic approval", "required_revision": "",
        "evidence_refs": [first], "counterexample_analysis": "No semantic judgement in this MockTransport fixture", "counterevidence_refs": []}
    result = {"schema": flow.workflow.DRAMA_AUDIT_VERSION, "goal_sha256": flow.digest(goal),
        "audit_context_sha256": request["structured_schema"]["properties"]["audit_context_sha256"]["const"],
        "goal_checks": {key: deepcopy(unknown) for key in flow.workflow.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in flow.workflow.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": [],
        "paired_checks": pair, "revision_target": "none"}
    # This particular row is mechanically coupled to the synthetic empty
    # typed findings; every semantic/paired judgment above remains unknown.
    result["goal_checks"]["closed_production_scope"]["status"] = "pass"
    return result


def setup_probe(tmp_path, monkeypatch, *, fault=None):
    monkeypatch.setattr(flow, "PROJECT", tmp_path); monkeypatch.setattr(spend, "PROJECT", tmp_path)
    parent = tmp_path / "settled635"; parent.mkdir()
    for name in ("INPUTS.json", "call_627_whole_plan_04.json", "call_628_scope_audit_04.json",
                 "call_629_source_audit_04.json", "call_630_commitment_audit_04.json"):
        (parent / name).write_bytes((ACTUAL / name).read_bytes())
    flow.write(parent / "SESSION_CONFIG.json", {"source_dir": str(tmp_path / "source"),
        "preferences_path": str(tmp_path / "prefs"), "user_goals_path": str(tmp_path / "goals")})
    for name in ("STATE", "CALL_LEDGER", "PRODUCTION_FREEZE"): flow.write(parent / (name + ".json"), {"offline": True})
    inventory = {str(p): {"sha256": flow.sha_file(p), "bytes": p.stat().st_size} for p in parent.iterdir()}
    identity = {"root": str(parent), "terminal_state_sha256": flow.sha_file(parent / "STATE.json"),
        "native_ledger_sha256": flow.sha_file(parent / "CALL_LEDGER.json"),
        "production_freeze_sha256": flow.sha_file(parent / "PRODUCTION_FREEZE.json"), "end_ordinal": 635}
    original_goal = flow.read(parent / "call_627_whole_plan_04.json")
    pointer = {"root": str(parent), "receipt": "call_627_whole_plan_04.json", "ordinal": 627, "label": "whole_plan_04",
        "request_sha256": original_goal["request_sha256"], "native_goal_sha256": flow.digest(original_goal["output"])}
    anchor = {"schema": flow.parent_spend.VERSION, "root": str(parent), "inherited": flow.BASE_SPEND,
        "verified_files": inventory, "parent_identity": identity, "parent_identity_sha256": flow.digest(identity),
        "whole_goal_candidates_used": 4, "scope_probe_calls_used": 2, "remaining_scope_probe_calls": 0,
        "old_director_capacity": flow.DIRECTOR, "latest_native_goal_receipt": pointer,
        "stage_calls": {"goal_plan": 3, "goal_audit": 4, "complete_script": 1, "full_review": 1}}
    flow.write(tmp_path / "PARENT.json", anchor)
    expectation = flow.read(REAL / "data/qa/creative_paired_live_diagnostic_20261015/REGISTERED_EXPECTATION_v1.json")
    expectation["original_receipt"]["path"] = str(parent / "call_627_whole_plan_04.json")
    flow.write(tmp_path / "PRIVATE_EXPECTATION.json", expectation)
    profile = tmp_path / "PROFILE.json"; profile.write_bytes((REAL / "config/creative_fresh_source_session_profile_v2.json").read_bytes())
    flow.write(tmp_path / "SOURCE.json", {"offline_source_marker": True})
    for name in ("AUTHORIZATION_AND_CADENCE_v1", "USER_COUNT_UNIT_CONFIRMATION_v1"):
        flow.write(tmp_path / (name + ".json"), {"offline": True})
    counter = CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round11", "offline paired diagnostic validation")
    def verify(value, *, expected_anchor_sha256):
        assert flow.digest(value) == expected_anchor_sha256
        return {"verified": True, "inherited": deepcopy(value["inherited"])}
    monkeypatch.setattr(spend, "verify_parent", verify)
    def builder(*args, **kwargs):
        return {"inputs": flow.read(parent / "INPUTS.json"), "source_files": [str(tmp_path / "SOURCE.json")],
            "evidence": {"source_gate": source_gate(args[0], now=kwargs["now"])}}
    fresh_calls = []
    def source_gate(path, *, now):
        fresh_calls.append(now)
        if fault == "source_stale": raise ValueError("opportunity_outside_validity")
        return {"current_source_freshness_verified": True}
    seen = []
    def factory(request):
        def respond(outgoing):
            seen.append(json.loads(outgoing.read()))
            if fault == "transport": raise httpx.ReadTimeout("offline unknown result", request=outgoing)
            output = unknown_mock_native(original_goal["output"], request)
            if fault == "contract": output.pop("paired_checks")
            if fault == "type": output["paired_checks"]["records_by_target"]["ending"]["status"] = 7
            if fault == "private_mutation": flow.write(tmp_path / "PRIVATE_EXPECTATION.json", {"changed_while_inflight": True})
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-paired-call", "type": "function",
                "function": {"name": flow.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]}
            if fault == "missing_tool": message = {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)}
            if fault == "wrong_tool": message["tool_calls"][0]["function"]["name"] = "foreign_tool"
            payload = {"id": "offline-paired-result", "model": request["model"], "choices": [{"index": 0, "message": message,
                "finish_reason": "length" if fault == "truncated" else "stop" if fault == "missing_tool" else "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            if fault == "usage_unknown": payload.pop("usage")
            return httpx.Response(200, content=json.dumps(payload, ensure_ascii=False).encode())
        return flow.clients.make_client_factory(request,
            http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(respond), verify=False, **kw))
    config = flow.ProbeConfig(str(tmp_path / "run"), str(tmp_path / "PARENT.json"), flow.digest(anchor),
        str(tmp_path / "PRIVATE_EXPECTATION.json"), str(tmp_path), "round11", "offline-paired",
        str(tmp_path / "AUTH.json"), str(profile), (str(tmp_path / "SOURCE.json"),))
    probe = flow.Probe(config, parent_verifier=verify, input_builder=builder, source_gate=source_gate, client_factory_builder=factory)
    return probe, seen, counter, fresh_calls


def prepare(probe):
    preview = probe.preview(); flow.write(probe.config.authorization_path, probe.authorization_template(preview), True)
    probe.prepare(); return preview


def test_preview_is_readonly_exact_full_native_r01_and_no_private_expectations(tmp_path, monkeypatch):
    probe, seen, counter, _ = setup_probe(tmp_path, monkeypatch)
    before = (tmp_path / "EXECUTION.json").read_bytes()
    preview = probe.preview(); text = preview["request"]["request"]["messages"][1]["content"]
    assert not probe.root.exists() and not probe.claim.exists() and not seen
    assert (tmp_path / "EXECUTION.json").read_bytes() == before
    assert preview["inherited"] == flow.BASE_SPEND and preview["stage_limits"] == flow.LIMITS
    assert "expected_status" not in text and "expectation_authority" not in text and "PRIVATE_EXPECTATION" not in text
    assert json.loads(text)["native_goal_document"] == probe._seed(flow.read(probe.config.parent_anchor_path))["goal"]
    assert preview["request"]["manifest"]["reference_occurrences"] == 1


def test_one_unknown_semantic_diagnostic_uses_original_sql_sdk_and_cost_anchor(tmp_path, monkeypatch):
    probe, seen, counter, fresh = setup_probe(tmp_path, monkeypatch); prepare(probe)
    result = probe.run()
    assert result["status"] == "diagnostic_inconclusive_not_creative" and len(seen) == 1
    assert result["spend"]["effective_calls_started"] == 636 and result["spend"]["effective_reported_tokens"] == 13368322
    assert seen[0]["model"] == "deepseek-flash" and seen[0]["max_tokens"] == 16000 and fresh
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as conn:
        rows = conn.execute("SELECT status,result FROM attempts").fetchall()
    assert len(rows) == 1 and rows[0][0] == "completed"
    anchor = spend.build_anchor(probe.root)
    assert anchor["inherited"]["calls_started"] == 636 and anchor["inherited"]["calls_with_known_usage"] == 634
    assert anchor["inherited"]["pending_ordinals"] == [70, 160] and anchor["inherited"]["unknown_token_reservations"] == 93117
    assert anchor["whole_goal_candidates_used"] == 4 and anchor["old_director_capacity"] == flow.DIRECTOR
    assert not anchor["authorizes_new_dispatch"] and not anchor["new_native_goal_created"]
    assert spend.verify_anchor(anchor, expected_anchor_sha256=flow.digest(anchor))["verified"]
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()


@pytest.mark.parametrize("fault,status,settles", [("contract", "halt_drama_contract_rejected", True), ("type", "halt_drama_contract_rejected", True),
    ("missing_tool", "halt_protocol_requires_diagnosis", True), ("wrong_tool", "halt_protocol_requires_diagnosis", True),
    ("transport", "halt_interface_or_unknown", False), ("truncated", "halt_interface_or_unknown", False),
    ("usage_unknown", "halt_interface_or_unknown", False)])
def test_known_faults_count_once_unknowns_never_settle_or_retry(tmp_path, monkeypatch, fault, status, settles):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch, fault=fault); prepare(probe); result = probe.run()
    assert result["status"] == status and len(seen) == 1 and not result["text_ready_for_director"]
    if settles:
        anchor = spend.build_anchor(probe.root)
        assert anchor["inherited"]["reported_tokens"] == 13368322
    else:
        with pytest.raises(ValueError, match="settled"): spend.build_anchor(probe.root)
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()


def test_different_grant_or_root_cannot_reuse_the_same_real_parent(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    changed = flow.Probe(replace(probe.config, root=str(tmp_path / "second"), grant_id="second", authorization_path=str(tmp_path / "AUTH2.json")),
        parent_verifier=probe.parent_verifier, input_builder=probe.input_builder, source_gate=probe.source_gate)
    flow.write(changed.config.authorization_path, changed.authorization_template(changed.preview()), True)
    with pytest.raises(ValueError, match="successor"): changed.prepare()
    assert not seen


def test_stale_current_source_stops_without_client_or_dispatch(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch, fault="source_stale")
    with pytest.raises(ValueError, match="opportunity_outside_validity"): prepare(probe)
    assert not seen


def test_counter_rechecked_after_task_claim_before_provider(tmp_path, monkeypatch):
    probe, seen, counter, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    original_claim = flow.policy.tasks.TaskStore.claim
    def stopped(store, *args, **kwargs):
        value = original_claim(store, *args, **kwargs)
        path = tmp_path / "ROUND_STOP.json"; flow.write(path, {"offline": True})
        counter.complete_round("round11", action="offline", conclusion="stopped before SDK", evidence_paths=[path])
        return value
    monkeypatch.setattr(flow.policy.tasks.TaskStore, "claim", stopped)
    with pytest.raises(ValueError): probe.run()
    assert not seen and probe.status()["status"] == "halt_execution_reconciliation"


def test_local_preference_mismatch_is_not_a_declared_semantic_error():
    expectation = {"target": "ending", "expected_status": "fail"}
    output = {"paired_checks": {"records_by_target": {"ending": {"status": "pass", "comparison": "An alternative reading"}}}}
    before = deepcopy(output); result = flow.evaluate_expectation(output, expectation)
    assert not result["expectation_match"] and not result["mismatch_proves_semantic_error"]
    assert not result["intention_requires_success"] and output == before


def test_unprepared_run_does_not_create_a_root_or_run_claim(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="separately prepared"): probe.run()
    assert not probe.root.exists() and not seen


def test_full_parent_reverified_at_locked_admission_not_only_flat_inventory(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    def changed(*args, **kwargs): raise ValueError("historical_leaf_changed")
    probe.parent_verifier = changed
    with pytest.raises(ValueError, match="historical_leaf_changed"): probe.run()
    assert not seen and probe.status()["status"] == "halt_execution_reconciliation"


def test_changed_local_expectation_inflight_cannot_be_used_or_anchored(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch, fault="private_mutation"); prepare(probe)
    with pytest.raises(ValueError, match="expectation changed"): probe.run()
    assert len(seen) == 1 and not (probe.root / "DIAGNOSTIC_COMPARISON.json").exists()
    with pytest.raises(ValueError, match="settled"): spend.build_anchor(probe.root)
