"""Isolated MockTransport diagnostics; no real claim, source refresh or model."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_registered_review_ab_probe_v1 as flow

REAL = Path(__file__).resolve().parents[1]
ROOT636 = REAL / "data/production_trials/legal_paired_drama_diagnostic_20261015/round_01"
ROOT627 = REAL / "data/production_trials/legal_scoped_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("Only isolated MockTransport is permitted")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(flow.shared.clients, "role_config", lambda role: SimpleNamespace(
        model="deepseek-flash", base_url="https://api.deepseek.com/v1", api_key="offline-ab-not-real"))


def setup_probe(tmp_path, monkeypatch, *, fault="contract"):
    monkeypatch.setattr(flow, "PROJECT", tmp_path)
    monkeypatch.setattr(flow.shared, "PROJECT", tmp_path)
    parent = tmp_path / "settled636"; parent.mkdir()
    for name in ("call_636_paired_drama_diagnostic_01.json", "PREPARED_PROBE.json"):
        (parent / name).write_bytes((ROOT636 / name).read_bytes())
    flow.write(parent / "PREPARED_PROBE.json", {"original_source_dir": str(tmp_path / "source")})
    (parent / "call_627_whole_plan_04.json").write_bytes((ROOT627 / "call_627_whole_plan_04.json").read_bytes())
    for name in ("STATE", "CALL_LEDGER", "PRODUCTION_FREEZE"):
        flow.write(parent / (name + ".json"), {"offline_parent": True})
    identity = {"root": str(parent), "terminal_state_sha256": flow.sha_file(parent / "STATE.json"),
        "native_ledger_sha256": flow.sha_file(parent / "CALL_LEDGER.json"),
        "production_freeze_sha256": flow.sha_file(parent / "PRODUCTION_FREEZE.json"), "end_ordinal": 636}
    goal = flow.read(parent / "call_627_whole_plan_04.json")
    anchor = {"schema": flow.parent_spend.VERSION, "root": str(parent), "inherited": deepcopy(flow.BASE_SPEND),
        "verified_files": {str(p): {"sha256": flow.sha_file(p)} for p in parent.iterdir()},
        "parent_identity": identity, "parent_identity_sha256": flow.digest(identity),
        "whole_goal_candidates_used": 4, "old_director_capacity": flow.shared.DIRECTOR,
        "scope_probe_calls_used": 2,
        "paired_drama_probe_calls_used": 1, "paired_drama_probe_call_limit": 1,
        "latest_native_goal_receipt": {"root": str(parent), "receipt": "call_627_whole_plan_04.json", "ordinal": 627,
            "label": "whole_plan_04", "request_sha256": goal["request_sha256"], "native_goal_sha256": flow.digest(goal["output"])}}
    flow.write(tmp_path / "PARENT.json", anchor)
    profile = tmp_path / "PROFILE.json"
    profile.write_bytes((REAL / "config/creative_fresh_source_session_profile_v2.json").read_bytes())
    for name in ("AUTHORIZATION_AND_CADENCE_v1", "USER_COUNT_UNIT_CONFIRMATION_v1"):
        flow.write(tmp_path / (name + ".json"), {"offline": True})
    counter = flow.shared.CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round12", "isolated registered A/B verification")
    verified, seen = [], []
    def verifier(value, *, expected_anchor_sha256):
        assert flow.digest(value) == expected_anchor_sha256
        verified.append(True); return {"verified": True, "inherited": deepcopy(value["inherited"])}
    def source_gate(path, *, now): return {"current_source_freshness_verified": True}
    def factory(request):
        def respond(outgoing):
            seen.append(json.loads(outgoing.read()))
            if fault == "transport": raise httpx.ReadTimeout("offline unknown", request=outgoing)
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-ab-call", "type": "function",
                "function": {"name": flow.shared.clients.TOOL_NAME, "arguments": json.dumps({"explicit_offline_contract_failure": True})}}]}
            if fault == "missing_tool": message = {"role": "assistant", "content": "offline known complete response without requested tool"}
            payload = {"id": "offline-ab-result-" + str(len(seen)), "model": request["model"], "choices": [{"index": 0, "message": message,
                "finish_reason": "length" if fault == "truncated" else "stop" if fault == "missing_tool" else "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            if fault == "usage_unknown": payload.pop("usage")
            return httpx.Response(200, content=json.dumps(payload, ensure_ascii=False).encode())
        return flow.shared.clients.make_client_factory(request,
            http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(respond), verify=False, **kw))
    config = flow.ProbeConfig(str(tmp_path / "run"), str(tmp_path / "PARENT.json"), flow.digest(anchor), str(tmp_path),
        "round12", "offline-ab", str(tmp_path / "AUTH.json"), str(profile))
    return flow.Probe(config, parent_verifier=verifier, source_gate=source_gate, client_factory_builder=factory), seen, counter, verified


def prepare(probe):
    preview = probe.preview(); flow.write(probe.config.authorization_path, probe.authorization_template(preview), True)
    probe.prepare(); return preview


def test_exact_two_representation_preview_is_readonly_and_does_not_send_expectations(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch)
    before = (tmp_path / "EXECUTION.json").read_bytes(); preview = probe.preview()
    assert not probe.root.exists() and not probe.claim.exists() and not seen
    assert (tmp_path / "EXECUTION.json").read_bytes() == before
    assert preview["stage_limits"] == flow.LIMITS and preview["inherited"] == flow.BASE_SPEND
    assert "remaining_scope_probe_calls" not in flow.read(probe.config.parent_anchor_path)
    assert preview["derived_remaining_original_scope_probe_calls"] == 0
    assert [i["label"] for i in preview["registered_requests"]] == list(flow.LABELS)
    for item in preview["registered_requests"]:
        prepared = item["prepared"]
        assert prepared["request_sha256"] == flow.digest(prepared["request"])
        text = json.dumps(prepared["request"], ensure_ascii=False)
        assert "offline_expectations" not in text and "expected_status" not in text
        assert prepared["request"]["parameters"]["max_completion_tokens"] == 16000


def test_known_complete_contract_failure_continues_only_to_other_registered_representation(tmp_path, monkeypatch):
    probe, seen, _, verified = setup_probe(tmp_path, monkeypatch); preview = prepare(probe)
    result = probe.run()
    assert result["status"] == "diagnostic_completed_not_creative" and len(seen) == 2
    assert [i["status"] for i in result["diagnostic_results"]] == ["contract_rejected", "contract_rejected"]
    assert result["spend"]["effective_calls_started"] == 638
    assert result["spend"]["effective_reported_tokens"] == 13409016
    assert result["spend"]["effective_calls_with_known_usage"] == 636
    assert result["spend"]["historical_pending_ordinals"] == [70, 160]
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert result["spend"]["stage_calls"] == {"goal_plan": 0, "goal_audit": 2, "complete_script": 0, "full_review": 0}
    assert len(verified) == 4  # two explicit previews plus each locked actual dispatch, not every guard.
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as db:
        rows = db.execute("SELECT status,result FROM attempts ORDER BY rowid").fetchall()
    assert len(rows) == 2 and all(row[0] == "content_rejected" for row in rows)
    assert all(json.loads(row[1])["outcome"] == "content_rejected" for row in rows)
    for row in flow.read(probe.root / "CALL_LEDGER.json")["calls"]:
        item = preview["registered_requests"][row["ordinal"] - 637]
        receipt = flow.read(probe.root / row["receipt"])
        assert receipt["request"] == item["prepared"]["request"]
        assert (probe.root / receipt["call_evidence"]["directory"] / "response_body.raw").is_file()
    assert not result["creative_quality_passed"] and not result["text_ready_for_director"]
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()


@pytest.mark.parametrize("fault", ["transport", "truncated", "usage_unknown"])
def test_unknown_never_dispatches_the_other_representation_or_retries(tmp_path, monkeypatch, fault):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch, fault=fault); prepare(probe)
    result = probe.run()
    assert result["status"] == "halt_interface_or_unknown" and len(seen) == 1
    assert [row["label"] for row in flow.read(probe.root / "CALL_LEDGER.json")["calls"]] == [flow.LABELS[0]]
    assert not (probe.root / "requests" / (flow.LABELS[1] + ".json")).exists()
    with pytest.raises(ValueError, match="RUN_CLAIM"): probe.run()


def test_same_real_parent_cannot_be_reclaimed_with_another_root_or_grant(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    changed = flow.Probe(replace(probe.config, root=str(tmp_path / "new_root"), grant_id="new-grant",
        authorization_path=str(tmp_path / "AUTH2.json")), parent_verifier=probe.parent_verifier, source_gate=probe.source_gate)
    flow.write(changed.config.authorization_path, changed.authorization_template(changed.preview()), True)
    with pytest.raises(ValueError, match="successor"): changed.prepare()
    assert not changed.root.exists() and not seen


def test_complete_known_missing_tool_counts_but_does_not_bypass_original_protocol_stop(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch, fault="missing_tool"); prepare(probe)
    result = probe.run()
    assert result["status"] == "halt_protocol_requires_diagnosis" and len(seen) == 1
    assert result["spend"]["effective_calls_started"] == 637
    assert result["spend"]["effective_reported_tokens"] == 13408916
    assert result["diagnostic_results"][0]["known"] is True
    assert not (probe.root / "requests" / (flow.LABELS[1] + ".json")).exists()


def test_duplicate_registered_label_is_rejected_before_new_task_or_provider(tmp_path, monkeypatch):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch); preview = prepare(probe)
    runtime = probe.runtime(); item = preview["registered_requests"][0]
    kwargs = {"root": probe.root, "grant_id": probe.config.grant_id, "stage_limits": flow.LIMITS,
        "current_round_root": probe.config.counter_root, "current_round_key": probe.config.round_key, "guard": probe._guard}
    flow.shared.policy.dispatch_claimed(runtime, item["label"], item["prepared"], lambda output: {"valid": False}, **kwargs)
    with pytest.raises(ValueError, match="already dispatched"):
        flow.shared.policy.dispatch_claimed(runtime, item["label"], item["prepared"], lambda output: {"valid": False}, **kwargs)
    assert len(seen) == 1 and len(flow.read(runtime.ledger)["calls"]) == 1
    with sqlite3.connect(probe.root / "TASKS.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_round_stop_after_task_claim_prevents_even_the_first_sdk_call(tmp_path, monkeypatch):
    probe, seen, counter, _ = setup_probe(tmp_path, monkeypatch); prepare(probe)
    original = flow.shared.policy.tasks.TaskStore.claim
    def stop(store, *args, **kwargs):
        claim = original(store, *args, **kwargs)
        path = tmp_path / "STOP_EVIDENCE.json"; flow.write(path, {"offline": True})
        counter.complete_round("round12", action="offline", conclusion="stopped before SDK", evidence_paths=[path])
        return claim
    monkeypatch.setattr(flow.shared.policy.tasks.TaskStore, "claim", stop)
    with pytest.raises(ValueError): probe.run()
    assert not seen and probe.status()["status"] == "halt_execution_reconciliation"
    assert flow.read(probe.root / "CALL_LEDGER.json")["calls"] == []
