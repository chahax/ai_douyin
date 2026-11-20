"""Production adapter uses only fake lineage/clients in isolated new roots.

The unchanged ContinuationRuntime performs its original reservation, response
parsing, receipt and ledger checks. No network or media task is submitted.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import run_creative_capability_production_v5 as runner
from scripts import creative_bounded_format_role_clients_v1 as capture
from scripts.creative_call_evidence_v1 import atomic_create
from src.content_factory.creative_workflow_roles import RoleResult
from tests.test_creative_complete_production_coordinator_v3 import fixture, receipt
from tests.test_creative_complete_production_coordinator_v4 import endpoints


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("v5 production adapter tests are offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


class FakeClients:
    def __init__(self, harness, request): self.harness, self.request = harness, deepcopy(request)

    def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
        h, request = self.harness, self.request
        assert role == request["role"] and messages == request["messages"]
        assert max_tokens == request["parameters"]["max_completion_tokens"] and thinking == "disabled"
        state = runner.old.control.read(h.root / "LOOP_STATE.json")
        assert state["stage_dispatch_events"][-1]["event"] == "claim"
        assert state["stage_dispatch_events"][-1]["request_sha256"] == runner.pipeline.digest(request)
        if request["stage"] == "whole_direction": assert state["director_events"][-1]["event"] == "claim"
        wire = runner.clients.expected_wire_request(request)
        raw = json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf8")
        body_sha = hashlib.sha256(raw).hexdigest()
        proof = {"schema": runner.clients.VERSION + "/outbound_capability_proof",
            "status": "capability_preflight_passed", "dispatch_before_verify": False,
            "identity_sha256": evidence.identity_sha256,
            "logical_request_sha256": runner.old.control.digest(request),
            "expected_wire_sha256": runner.old.control.digest(wire), "actual_wire_sha256": runner.old.control.digest(wire),
            "original_body_sha256": body_sha, "actual_request_body_sha256": body_sha,
            "full_wire_equals_mapped_logical_request": True,
            "messages_sha256": runner.old.control.digest(messages),
            "structured_schema_sha256": runner.old.control.digest(structured_schema),
            "SDK_max_retries": 0, "HTTP_follow_redirects": False,
            "logical_capability_report": runner.capability.preflight_text_request(request),
            "wire_capability_report": runner.capability.preflight_text_request(wire)}
        if h.mode == "bad_proof": proof["actual_request_body_sha256"] = "f" * 64
        if h.mode != "missing_proof":
            atomic_create(evidence.root / "CAPABILITY_PREFLIGHT.json", json.dumps(proof, ensure_ascii=False).encode())
        capture.save_request_body(evidence, raw, role=role)
        h.calls.append(deepcopy(request))
        if h.mode == "crash": raise KeyboardInterrupt("offline interruption after original reservation")
        if h.mode == "transport_unknown":
            raise runner.clients.EvidenceCallError("OFFLINE_TIMEOUT", started=True, outcome_known=False)
        inputs = json.loads(messages[1]["content"])
        stage = request["stage"]
        if stage == "whole_direction":
            h.directors += 1
            assert "endpoint_graph" in inputs and "candidate_graph" not in inputs
            native = deepcopy(h.native)
            if h.mode == "all_directors_invalid": native["segments"][-1]["end_source_ref"] = native["segments"][0]["end_source_ref"]
            if h.mode == "director_invalid_first" and h.directors == 1:
                native["segments"][-1]["end_source_ref"] = native["segments"][0]["end_source_ref"]
        elif stage == "local_performance":
            native = deepcopy(h.performances[int(inputs["current_direction"]["segment_id"][1:]) - 1]["native"])
        elif stage == "whole_production_review":
            h.reviews += 1
            assert inputs["whole_direction_native"] == h.native
            assert inputs["full_current_script"] == h.script
            native = {"checks": [{"check": key, "status": "pass", "source_refs": ["B1.S01"],
                "reason": "离线模拟同源全文审查，不是创作或视频质量证据"} for key in runner.old.PRODUCTION_CHECKS],
                "revision_requirements": [], "review_limitations": ["实际素材与用户视频批准未核实"]}
        else: raise AssertionError("unexpected stage " + stage)
        if "output_transport" in request: native = {"payload_json": json.dumps(native, ensure_ascii=False)}
        text = json.dumps(native, ensure_ascii=False)
        payload = {"id": "offline_" + str(evidence.identity["ordinal"]), "model": request["model"],
            "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function",
                "function": {"name": "submit_creative_json", "arguments": text}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
        metadata = {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls",
            "response_id": payload["id"], "raw_body_sha256": runner.old.control.digest(payload),
            "prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20, "output_mode": "tool_call"}
        if h.mode in ("truncated", "usage_unknown", "missing_tool"):
            if h.mode == "truncated": metadata["finish_reason"] = "length"
            if h.mode == "usage_unknown": metadata["total_tokens"] = None
            if h.mode == "missing_tool":
                payload["choices"][0]["message"]["tool_calls"] = []
                metadata["output_mode"] = "content"
        evidence.save_body(json.dumps(payload, ensure_ascii=False).encode(), {"http_status_code": 200})
        return RoleResult(text=text, metadata=metadata, response_payload=payload)


def setup(tmp_path, monkeypatch, mode=None):
    project = tmp_path / "project"
    project.mkdir()
    root = project / "data/production_revisions/fake_capability_v5"
    script, manifest, initial, direction, performances, brief, _ = fixture(tmp_path)
    for beat in script["beats"]:
        beat["event"] = "离线交涉事件"
        beat["trigger"] = "上一项明确要求被接收"
    manifest["script_sha256"] = runner.pipeline.digest(script)
    reference = "离线教学参考全文：刺激先发生，人物才反应；不得机械拆开对白与动作。"
    preferences = {"subtitles": False}
    inputs = runner.pipeline.build_director_input(script, manifest, initial, reference, preferences)
    req = runner.pipeline.build_request("whole_direction", inputs,
        runner.pipeline.whole_direction_schema(script, manifest), "MiniMax-M3")
    attempts = [receipt("whole_direction_old_" + str(i), req, {"old_range_contract": i}, i, "contract_rejected")
        for i in (514, 515, 516, 517)]
    state = runner.loop.initial_loop_state(attempts, "a" * 64, default_limit=3, stable_scope_material={
        "full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial})
    state = runner.loop.authorize_extra_candidate(state, {"authority": "explicit_user", "grant_id": "old_fourth",
        "user_quote": "offline prior fourth authorization", "additional_candidates": 1,
        "source_binding_sha256": "a" * 64})
    parent_file = project / "frozen_parent.json"
    runner.old.control.write(parent_file, {"offline_only": True, "old_limit": 4}, True)
    original_input = {"brief": brief, "reference_fulltext": reference, "production_preferences": preferences}
    sourceproof = {"writer_ordinal": 512, "review_ordinal": 513, "script_sha256": runner.pipeline.digest(script),
        "machine_text_review_passed": True, "production_context_sha256": runner.coordinator.production_context_digest(
            brief, reference, preferences), "production_context_binding_kind": "verified_frozen_input_identity_only",
        "preferences_semantically_reviewed_by_513": False, "offline_fixture_only": True}
    models = {"writer": {"provider": "minimax", "model": "MiniMax-M3", "base_url": "https://api.minimaxi.com/v1"},
        "director": {"provider": "deepseek", "model": "deepseek-flash", "base_url": "https://api.deepseek.com/v1"}}
    lineage = {"original_input": original_input, "script": script, "manifest": manifest, "initial": initial,
        "source_review_binding": sourceproof, "parent_state": state, "models": models,
        "inherited": {"calls_started": 517, "reported_tokens": 7886808, "calls_with_known_usage": 515,
            "pending_ordinals": [70, 160], "unknown_token_reservations": 93117},
        "parent_files": {str(parent_file): runner.old.control.sha_file(parent_file)}}
    h = SimpleNamespace(project=project, root=root, lineage=lineage, parent_file=parent_file,
        script=script, native=endpoints(direction, script, manifest), performances=performances,
        mode=mode, calls=[], directors=0, reviews=0, factories=[])
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "verified_lineage", lambda: deepcopy(h.lineage))
    # Only this new runner is injected; no old runtime method or global is changed.
    def runtime():
        anchor = runner.old.control.read(root / "ANCHOR.json")
        return runner.old.control.ContinuationRuntime(project, root,
            [project / path for path in anchor["runtime_sources"]], anchor["inherited"], anchor["models"],
            inherited_guard=lambda: runner.old.prior.verify_files(anchor["parent_files"]),
            client_factory=lambda: (_ for _ in ()).throw(AssertionError("stage client must bind request")), quota_state=None)
    monkeypatch.setattr(runner, "runtime", runtime)
    monkeypatch.setattr(runner.clients, "role_config", lambda role: SimpleNamespace(**models[role]))
    def factory(request):
        h.factories.append(deepcopy(request))
        return lambda: FakeClients(h, request)
    monkeypatch.setattr(runner.clients, "make_client_factory", factory)
    return h


def test_prepare_inherits_four_attempts_all_spend_and_unknowns_without_dispatch(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    before = h.parent_file.read_bytes()
    status = runner.prepare()
    assert status["director_capacity"]["candidate_limit"] == 7
    assert status["director_capacity"]["attempts_including_claims"] == 4
    assert status["director_capacity"]["remaining"] == 3
    assert status["effective_calls_started"] == 517 and status["effective_reported_tokens"] == 7886808
    assert status["historical_unknown_calls"] == [70, 160] and status["historical_unknown_token_reservations"] == 93117
    assert not status["old_budget_reset"] and status["new_calls"] == 0 and h.calls == []
    assert h.parent_file.read_bytes() == before
    assert runner.prepare() == status
    assert runner.old.control.read(h.root / "USER_SCOPE.json")["trial_scope"] == "text_contract_trial_only"


def test_preview_keeps_full_reference_endpoint_and_latest_native_without_invoking(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    assert runner.preview()["status"] == "not_prepared"
    assert not h.root.exists()
    runner.prepare()
    info = runner.preview()
    preview = runner.old.control.read(Path(info["preview_path"]))
    request = preview["request"]
    inp = json.loads(request["messages"][1]["content"])
    assert inp["reference_fulltext"] == h.lineage["original_input"]["reference_fulltext"]
    assert inp["brief"] == h.lineage["original_input"]["brief"]
    assert "endpoint_graph" in inp and "candidate_graph" not in inp
    assert len(inp["known_complete_failure_diagnostics"]) == 1
    assert inp["known_complete_failure_diagnostics"][0]["prior_complete_native_direction"] == {"old_range_contract": 517}
    assert info["images_in_request"] == 0 and info["new_calls"] == 0 and h.factories == []


def test_complete_fake_service_chain_saves_native_handoff_and_exact_wire_proof(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    result = runner.execute()
    assert result["complete_text_handoff_ready"], result
    assert result["status"] == "complete_text_production_handoff_ready"
    assert result["new_calls"] == 4 and result["effective_calls_started"] == 521
    assert result["effective_reported_tokens"] == 7886888
    assert result["new_video_calls"] == 0 and not result["complete_visual_material_handoff_ready"]
    assert result["historical_unknown_calls"] == [70, 160]
    assert [request["stage"] for request in h.calls] == ["whole_direction", "local_performance", "local_performance", "whole_production_review"]
    assert h.factories == h.calls
    proofs = runner.old.control.read(h.root / "ACTUAL_REQUEST_PROOF.json")
    assert len(proofs) == 4
    assert all(row["actual_capability_preflight_binding_verified"] and row["actual_serialized_reference_equal"]
        and row["actual_request_body_binding_verified"] for row in proofs)
    assert runner.old.control.read(h.root / "DELIVERABLE/NATIVE_ENDPOINT_DIRECTION.json") == h.native
    assert (h.root / "DELIVERABLE/DIRECTOR_PERFORMANCE_HANDOFF.md").is_file()
    ledger_bytes = (h.root / "CALL_LEDGER.json").read_bytes()
    assert runner.execute() == result
    assert runner.status() == result and len(h.calls) == 4
    assert (h.root / "CALL_LEDGER.json").read_bytes() == ledger_bytes


@pytest.mark.parametrize("mode", ["missing_proof", "bad_proof"])
def test_missing_or_wrong_actual_preflight_proof_blocks_successful_handoff(tmp_path, monkeypatch, mode):
    h = setup(tmp_path, monkeypatch, mode)
    result = runner.execute()
    assert result["status"] == "needs_attention" and result["reason"] == "ACTUAL_REQUEST_PROOF_INVALID"
    assert not result["complete_text_handoff_ready"] and not (h.root / "DELIVERABLE").exists()
    assert runner.old.control.read(h.root / "COORDINATOR_RESULT.json")["complete_text_handoff_ready"] is True
    assert all(not row["actual_capability_preflight_binding_verified"] for row in runner.old.control.read(h.root / "ACTUAL_REQUEST_PROOF.json"))
    assert runner.execute() == result and len(h.calls) == 4


def test_known_director_failure_uses_only_three_new_candidates_keeps_original_four(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch, "all_directors_invalid")
    result = runner.execute()
    assert result["status"] == "needs_attention" and result["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    assert result["director_capacity"]["attempts_including_claims"] == 7 and result["new_calls"] == 3
    assert h.directors == 3 and h.reviews == 0
    state = runner.old.control.read(h.root / "LOOP_STATE.json")
    assert state["director_events"][:4] == h.lineage["parent_state"]["director_events"]
    assert runner.execute() == result and len(h.calls) == 3
    for request in h.calls[1:]:
        inp = json.loads(request["messages"][1]["content"])
        assert len(inp["known_complete_failure_diagnostics"]) == 1
        assert "old_range_contract" not in json.dumps(inp["known_complete_failure_diagnostics"])


def test_known_director_revision_runs_complete_new_native_then_full_review(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch, "director_invalid_first")
    result = runner.execute()
    assert result["complete_text_handoff_ready"] and h.directors == 2 and h.reviews == 1
    assert result["director_capacity"]["attempts_including_claims"] == 6
    assert result["new_calls"] == 5


@pytest.mark.parametrize("mode", ["transport_unknown", "truncated", "usage_unknown", "missing_tool"])
def test_unknown_or_incomplete_stops_and_saved_reentry_never_dispatches(tmp_path, monkeypatch, mode):
    h = setup(tmp_path, monkeypatch, mode)
    result = runner.execute()
    assert result["status"] == "needs_attention" and not result["complete_text_handoff_ready"]
    assert result["new_calls"] == 1 and len(h.calls) == 1
    assert (h.root / "COORDINATOR_RESULT.json").is_file()
    assert (h.root / "PRODUCTION_REPORT.md").is_file()
    assert runner.execute() == result and len(h.calls) == 1
    assert result["historical_unknown_token_reservations"] == 93117


def test_crash_after_original_reservation_leaves_claim_and_prevents_reentry(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch, "crash")
    with pytest.raises(KeyboardInterrupt): runner.execute()
    ledger = runner.old.control.read(h.root / "CALL_LEDGER.json")
    assert len(ledger["calls"]) == 1
    assert runner.runtime().effective_receipt(ledger["calls"][0])["status"] == "pending_response"
    h.mode = None
    result = runner.execute()
    assert not result["complete_text_handoff_ready"] and len(h.calls) == 1
    assert result["reason"] == "EXISTING_EXECUTION_RECONCILE_OR_REUSE_SAVED_HANDOFF"


def test_existing_execution_lock_returns_no_new_dispatch(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    runner.prepare()
    (h.root / "COORDINATOR_EXECUTION.lock").write_text("original in flight", encoding="utf8")
    result = runner.execute()
    assert result["status"] == "execution_claimed_reconcile_original" and h.calls == []
    assert (h.root / "COORDINATOR_EXECUTION.lock").read_text() == "original in flight"


@pytest.mark.parametrize("field", ["original_candidate_limit", "additional_candidate_grants", "director_events", "successor_source_bindings"])
def test_mutated_allowance_or_old_history_rejected_before_dispatch(tmp_path, monkeypatch, field):
    h = setup(tmp_path, monkeypatch)
    runner.prepare()
    state = runner.old.control.read(h.root / "LOOP_STATE.json")
    if field == "original_candidate_limit": state[field] += 100
    elif field == "additional_candidate_grants": state[field][0]["additional_candidates"] += 1
    else: state[field] = []
    runner.old.control.write(h.root / "LOOP_STATE.json", state)
    with pytest.raises(ValueError): runner.execute()
    assert h.calls == []


def test_frozen_parent_change_stops_before_claim_or_dispatch(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    runner.prepare()
    h.parent_file.write_text("changed", encoding="utf8")
    with pytest.raises(ValueError): runner.execute()
    assert h.calls == []


def test_model_configuration_change_stops_before_claim_or_dispatch(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.clients, "role_config", lambda role: SimpleNamespace(**{**h.lineage["models"][role], "model": "different"}))
    result = runner.execute()
    assert result["status"] == "needs_attention" and result["reason"] == "COMPLETE_PRODUCTION_GATE_INVALID" and h.calls == []
    assert runner.old.control.read(h.root / "LOOP_STATE.json")["director_events"] == h.lineage["parent_state"]["director_events"]


def test_saved_result_or_output_changed_is_detected_without_dispatch(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    runner.execute()
    path = h.root / "DELIVERABLE/FULL_SCRIPT.md"
    path.write_text("tampered", encoding="utf8")
    with pytest.raises(ValueError): runner.execute()
    assert len(h.calls) == 4


def test_frozen_reference_selection_cannot_be_added_after_prepare(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    runner.prepare()
    with pytest.raises(ValueError): runner.prepare(h.project / "later_selection.json")
    assert h.calls == []


def reference_bundle(h, tmp_path):
    from tests.test_creative_reference_compiler_v4 import create_asset, MODEL, ACCOUNT, NARRATIVE
    folder = tmp_path / "synthetic_assets"
    folder.mkdir()
    assets, mapping, get_records = [], [], {}
    for kind, values in (("actor", h.lineage["manifest"]["actors"]), ("scene", h.lineage["manifest"]["scenes"])):
        for row in values:
            asset, binding, get = create_asset(folder, "synthetic_" + row["id"], "image",
                "first_frame" if kind == "actor" else "reference_image", kind, row["id"], native=kind == "actor")
            asset["role"] = "reference_image"
            get["received_at"] = runner.old.control.now()
            if kind == "actor": get_records[asset["asset_id"]] = get
            assets.append(asset)
            mapping.append(binding)
    required = [{"entity_type": row["entity_type"], "entity_id": row["entity_id"]} for row in mapping]
    contract = {"schema": runner.references.BINDING_SCHEMA, "provider_id": "ark_api", "model": MODEL,
        "mode": "multimodal_reference", "input_account_binding_sha256": ACCOUNT,
        "narrative_text_sha256": hashlib.sha256(NARRATIVE.encode()).hexdigest(),
        "assets": assets, "entity_bindings": mapping, "required_entities": required, "voices": []}
    path = h.project / "OFFLINE_REFERENCE_INTAKE.json"
    runner.old.control.write(path, {"binding_contract": contract, "selected_asset_ids": [row["asset_id"] for row in assets],
        "expected_account_binding_sha256": ACCOUNT, "required_entities": required, "offline_fixture_only": True}, True)
    value = runner.old.control.read(path)
    value["provider_get_evidence"] = get_records
    runner.old.control.write(path, value)
    return path, assets


def test_actual_multimodal_director_keeps_reference_fulltext_and_payload_byte_binding(tmp_path, monkeypatch):
    h = setup(tmp_path, monkeypatch)
    bundle, assets = reference_bundle(h, tmp_path)
    result = runner.execute(bundle)
    assert result["complete_text_handoff_ready"], result
    assert result["trial_scope"] == "approved_visual_material_text_trial"
    assert not result["complete_visual_material_handoff_ready"] and result["new_video_calls"] == 0
    proof = runner.old.control.read(h.root / "ACTUAL_REQUEST_PROOF.json")[0]
    assert proof["image_count"] == len(assets)
    assert proof["actual_image_payloads_equal"] and proof["actual_capability_preflight_binding_verified"]
    assert proof["actual_serialized_reference_equal"] and proof["logical_reference_equal"]
    assert all(part["type"] == "image_url" for part in h.calls[0]["messages"][-1]["content"][1:])
    assert "data:image" not in h.calls[-1]["messages"][1]["content"]
    assert len(h.calls) == 4
    assert runner.execute(bundle) == result and len(h.calls) == 4


@pytest.mark.parametrize("artifact", ["CAPABILITY_PREFLIGHT.json", "request_body.raw"])
def test_saved_actual_outbound_evidence_tamper_is_detected_without_dispatch(tmp_path, monkeypatch, artifact):
    h = setup(tmp_path, monkeypatch)
    assert runner.execute()["complete_text_handoff_ready"]
    path = runner.runtime().evidence_path(518) / artifact
    if artifact.endswith(".json"):
        value = runner.old.control.read(path)
        value["actual_request_body_sha256"] = "0" * 64
        runner.old.control.write(path, value)
    else: path.write_bytes(b"tampered")
    with pytest.raises(ValueError): runner.execute()
    assert len(h.calls) == 4
