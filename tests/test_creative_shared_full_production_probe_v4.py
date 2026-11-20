"""Offline production-adapter checks; all roots and dispatches are synthetic.

The real freeze/ledger implementation runs inside tmp_path, never the actual
production ROOT. No clients, paid requests, media or account queries are used.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts import run_creative_shared_full_production_v4 as probe
from src.content_factory import creative_production_revision_loop_v3 as loop
from tests.test_creative_complete_production_pipeline_v2 import v2_fixture
from tests.test_creative_production_revision_loop_v3 import receipt as native_receipt


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    project = tmp_path / "project"
    root = project / "probe"
    parent = project / "parent"
    for name in ("src", "scripts", "parent"):
        (project / name).mkdir(parents=True)
    (project / "src" / "offline_source.py").write_text("offline = True\n", encoding="utf8")
    (project / "scripts" / "offline_runner.py").write_text("network = False\n", encoding="utf8")
    script, manifest, initial, direction, _ = v2_fixture()
    reference = {"R01": "完整参考全文：用刺激、反应和当前观察对象组织叙事。"}
    x = {"brief": {}, "reference_fulltext": reference, "production_preferences": {}}
    material = {"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial}
    parents = [native_receipt(direction["native"], material, ordinal=n, status="contract_rejected")
        for n in (514, 515, 516)]
    state = loop.initial_loop_state(parents)
    proof = {"writer_ordinal": 512, "review_ordinal": 513,
        "script_sha256": probe.pipeline.digest(script), "machine_text_review_passed": True}
    inherited = {"calls_started": 516, "reported_tokens": 7856107,
        "known_calls": 514, "pending_unknown_calls": 2,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    models = {"writer": {"provider": "minimax", "model": "MiniMax-M3", "base_url": "https://offline.invalid/v1"},
        "director": {"provider": "deepseek", "model": "deepseek-flash", "base_url": "https://offline.invalid/v1"}}
    rows = []
    all_parents = [native_receipt({"sample": "source"}, ordinal=n) for n in (512, 513)] + parents
    for row in all_parents:
        name = f"call_{row['ordinal']}_offline.json"
        probe.old.control.write(parent / name, row, True)
        rows.append({"ordinal": row["ordinal"], "receipt": name})
    for name in ("AUTHORIZATION.json", "ANCHOR.json", "INPUT.json", "ADOPTED_SOURCE.json",
            "SHARED_MANIFEST.json", "PLANNED_INITIAL_STATE.json", "USER_SCOPE.json"):
        probe.old.control.write(parent / name, {}, True)
    probe.old.control.write(parent / "CALL_LEDGER.json", {"calls": rows, "model_configs": models}, True)
    parent_before = {p.name: p.read_bytes() for p in parent.iterdir()}
    monkeypatch.setattr(probe, "PROJECT", project)
    monkeypatch.setattr(probe, "ROOT", root)
    monkeypatch.setattr(probe.old, "ROOT", parent)
    monkeypatch.setattr(probe.intake, "verified_parent", lambda: deepcopy((x, script, manifest, initial, state, proof)))
    monkeypatch.setattr(probe.old.prior, "inherited_known_parent", lambda ledger, path: deepcopy((inherited, all_parents)))
    monkeypatch.setattr(probe, "role_config", lambda role: SimpleNamespace(**models[role]))
    calls = []
    controls = {"interrupt": False, "raw_body_defect": None}

    def offline_runtime():
        a = probe.old.control.read(root / "ANCHOR.json")
        def guard():
            probe.old.prior.verify_files(a["parent_files"])
        def forbid_client(*args, **kwargs):
            raise AssertionError("offline adapter must not instantiate any model client")
        return probe.old.control.ContinuationRuntime(project, root,
            [project / p for p in a["runtime_sources"]], a["inherited"], a["models"],
            inherited_guard=guard, client_factory=forbid_client, quota_state=None)

    monkeypatch.setattr(probe, "runtime", offline_runtime)

    def offline_dispatch(rt, label, request, validate):
        assert rt.root == root and rt.project == project
        assert probe.old.control.read(root / "stage_requests" / (label + ".json")) == request
        durable = probe.old.control.read(root / "LOOP_STATE.json")
        claim = durable["director_events"][-1]
        assert claim["event"] == "claim" and claim["request_identity"] == loop.digest(request)
        assert loop.candidate_capacity(durable)["remaining"] == 0
        assert json.loads(request["messages"][1]["content"])["reference_fulltext"] == reference
        ledger = probe.old.control.read(rt.ledger)
        ordinal = rt.inherited["calls_started"] + len(ledger["calls"]) + 1
        calls.append((ordinal, label, deepcopy(request)))
        native = {"availability": "known", "invalid_complete_director": True}
        row = native_receipt(native, ordinal=ordinal, status="contract_rejected")
        row.update(label=label, request=deepcopy(request), request_sha256=loop.digest(request),
            source_binding_sha256=loop.digest(ledger["source_manifest"]), token_reservation=100)
        identity_sha = loop.digest(rt.evidence_identity(row))
        row["call_evidence"] = {"identity_sha256": identity_sha}
        journal = rt.evidence_path(ordinal)
        journal.mkdir(parents=True)
        actual_body = {"model": request["model"], "messages": deepcopy(request["messages"])}
        if controls["raw_body_defect"] == "missing_reference":
            body_input = json.loads(actual_body["messages"][1]["content"])
            body_input.pop("reference_fulltext")
            actual_body["messages"][1]["content"] = json.dumps(body_input, ensure_ascii=False)
        (journal / "request_body.raw").write_text(json.dumps(actual_body, ensure_ascii=False), encoding="utf8")
        raw_sha = probe.old.control.sha_file(journal / "request_body.raw")
        capture = {"body_complete": True, "raw_bytes_preserved": True, "identity_sha256": identity_sha,
            "stored_sha256": raw_sha, "original_sha256": raw_sha}
        if controls["raw_body_defect"] == "wrong_identity": capture["identity_sha256"] = "f" * 64
        if controls["raw_body_defect"] == "wrong_hash": capture["stored_sha256"] = "f" * 64
        probe.old.control.write(journal / "REQUEST_BODY_MANIFEST.json", capture, True)
        if controls["interrupt"]:
            row["status"] = "response_unknown"
            row["response_metadata"]["response_body_complete"] = False
            row["response_metadata"]["total_tokens"] = None
        name = f"call_{ordinal}_{label}.json"
        probe.old.control.write(root / name, row, True)
        ledger["calls"].append({"ordinal": ordinal, "label": label, "receipt": name,
            "receipt_sha256": probe.old.control.sha_file(root / name), "token_reservation": 100})
        probe.old.control.write(rt.ledger, ledger)
        if controls["interrupt"]:
            raise RuntimeError("simulated transport interrupted after original immutable reservation")
        return row

    monkeypatch.setattr(probe.old.control.ContinuationRuntime, "dispatch", offline_dispatch)
    return SimpleNamespace(root=root, project=project, parent=parent, state=state,
        inherited=inherited, calls=calls, controls=controls, parent_before=parent_before)


def test_prepare_inherits_spend_unknowns_three_failures_and_once_only_grant(adapter):
    first = probe.prepare()
    state_before = probe.old.control.read(adapter.root / "LOOP_STATE.json")
    frozen = probe.old.control.read(adapter.root / "CALL_LEDGER.json")
    second = probe.prepare()
    assert first == second
    assert frozen == probe.old.control.read(adapter.root / "CALL_LEDGER.json")
    assert frozen["starting_spend"] == adapter.inherited
    assert first["effective_calls_started"] == 516 and first["effective_reported_tokens"] == 7856107
    assert first["historical_unknown_calls"] == [70, 160]
    assert first["historical_unknown_token_reservations"] == 93117
    assert first["director_capacity"]["attempts_including_claims"] == 3
    assert first["director_capacity"]["candidate_limit"] == 4
    assert first["director_capacity"]["remaining"] == 1
    assert state_before["director_events"] == adapter.state["director_events"]
    assert len(state_before["additional_candidate_grants"]) == 1
    assert len(state_before["successor_source_bindings"]) == 1
    assert probe.verify_loop_history(probe.runtime()) == state_before
    assert not adapter.calls
    assert adapter.parent_before == {p.name: p.read_bytes() for p in adapter.parent.iterdir()}


def test_execute_saves_native_request_before_fake_send_then_reuses_saved_stop_without_dispatch(adapter):
    result = probe.execute()
    assert result["status"] == "needs_attention"
    assert len(adapter.calls) == 1 and adapter.calls[0][0] == 517
    assert result["effective_calls_started"] == 517
    assert result["effective_reported_tokens"] == 7856132
    assert result["director_capacity"]["attempts_including_claims"] == 4
    assert result["director_capacity"]["remaining"] == 0
    proof = probe.old.control.read(adapter.root / "ACTUAL_REFERENCE_PROOF.json")
    assert proof[0]["logical_reference_equal"]
    assert proof[0]["actual_serialized_reference_equal"]
    assert proof[0]["actual_request_body_binding_verified"]
    assert proof[0]["provider_received_request"] is None
    assert probe.execute() == result
    assert len(adapter.calls) == 1
    assert not result["complete_text_handoff_ready"] and result["new_video_calls"] == 0
    assert not (adapter.root / "DELIVERABLE").exists()
    assert adapter.parent_before == {p.name: p.read_bytes() for p in adapter.parent.iterdir()}


@pytest.mark.parametrize("defect", ["missing_reference", "wrong_identity", "wrong_hash"])
def test_reference_proof_uses_serialized_body_and_identity_not_only_logical_input(adapter, defect):
    adapter.controls["raw_body_defect"] = defect
    probe.execute()
    proof = probe.old.control.read(adapter.root / "ACTUAL_REFERENCE_PROOF.json")[0]
    assert proof["logical_reference_equal"]
    assert not proof["actual_serialized_reference_equal"]
    assert proof["actual_request_body_binding_verified"] is (defect == "missing_reference")


@pytest.mark.parametrize("defect", ["limit", "grant", "history", "successor"])
def test_mutable_loop_cannot_raise_allowance_or_drop_inherited_failures(adapter, defect):
    probe.prepare()
    state = probe.old.control.read(adapter.root / "LOOP_STATE.json")
    if defect == "limit": state["original_candidate_limit"] = 30
    elif defect == "grant": state["additional_candidate_grants"][0]["additional_candidates"] = 30
    elif defect == "history": state["director_events"].pop(0)
    else: state["successor_source_bindings"].clear()
    probe.old.control.write(adapter.root / "LOOP_STATE.json", state)
    with pytest.raises(ValueError): probe.verify_loop_history(probe.runtime())
    result = probe.execute()
    assert result["status"] == "execution_interrupted_reconcile_original"
    assert not adapter.calls and not result["new_request_redispatch_allowed"]


def test_appended_director_receipt_without_original_durable_claim_is_rejected(adapter):
    probe.execute()
    state = probe.old.control.read(adapter.root / "LOOP_STATE.json")
    state["director_events"] = [e for e in state["director_events"]
        if not (e["event"] == "claim")]
    probe.old.control.write(adapter.root / "LOOP_STATE.json", state)
    with pytest.raises(ValueError, match="durable claim"):
        probe.verify_loop_history(probe.runtime())
    assert len(adapter.calls) == 1


def test_interruption_is_preserved_and_restart_never_dispatches_another_request(adapter):
    adapter.controls["interrupt"] = True
    first = probe.execute()
    assert first["status"] == "execution_interrupted_reconcile_original"
    assert first["runtime_summary"]["new_calls"] == 1
    assert not first["new_request_redispatch_allowed"]
    assert len(list(adapter.root.glob("INTERRUPTION_*.json"))) == 1
    assert probe.old.control.read(adapter.root / "LOOP_STATE.json")["coordinator_status"] == "running"
    adapter.controls["interrupt"] = False
    second = probe.execute()
    assert second["reason"] == "EXISTING_EXECUTION_RECONCILE_OR_REUSE_SAVED_HANDOFF"
    assert len(adapter.calls) == 1
    assert second["historical_unknown_token_reservations"] == 93117
    assert second["historical_unknown_calls"] == [70, 160]
    assert not (adapter.root / "COORDINATOR_EXECUTION.lock").exists()


def test_changed_actual_model_config_stops_before_dispatch(adapter, monkeypatch):
    monkeypatch.setattr(probe, "role_config", lambda role: SimpleNamespace(provider="minimax",
        model="different-model", base_url="https://offline.invalid/v1"))
    result = probe.execute()
    assert result["status"] == "execution_interrupted_reconcile_original"
    assert "actual role configuration" in result["message"]
    assert not adapter.calls


def test_mutable_baseline_and_progress_cannot_jointly_raise_original_candidate_limit(adapter):
    probe.prepare()
    for name in ("INITIAL_LOOP_STATE.json", "LOOP_STATE.json"):
        value = probe.old.control.read(adapter.root / name)
        value["original_candidate_limit"] = 30
        probe.old.control.write(adapter.root / name, value)
    with pytest.raises(ValueError, match="baseline"):
        probe.verify_loop_history(probe.runtime())
    assert not adapter.calls


def test_original_parent_snapshot_change_stops_before_any_new_dispatch(adapter):
    probe.prepare()
    probe.old.control.write(adapter.parent / "USER_SCOPE.json", {"tampered": True})
    with pytest.raises((RuntimeError, ValueError)):
        probe.execute()
    assert not adapter.calls

