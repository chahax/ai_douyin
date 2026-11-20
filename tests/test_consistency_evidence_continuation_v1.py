"""Independent v1 consistency authorizer recovery; no real authority, provider or run claim."""
from copy import deepcopy
from pathlib import Path
import socket
from unittest.mock import Mock

import pytest

from scripts import creative_resume_dispatch_v3 as control
from scripts import record_consistency_evidence_continuation_v1 as authorizer


@pytest.fixture(autouse=True)
def no_network_or_dispatch(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("offline authorizer must not contact a provider or create a run claim")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(authorizer.run, "prepare", deny)
    monkeypatch.setattr(authorizer.run, "run", deny)
    monkeypatch.setattr(authorizer.run, "get_runtime", deny)
    monkeypatch.setattr(authorizer.run.previous, "get_runtime", deny)


@pytest.fixture
def local_authorizer(tmp_path, monkeypatch):
    run = authorizer.run
    project = tmp_path / "synthetic_project"
    parent = project / "parent"
    authority_path = project / "prior_authority.json"
    approval_path = project / "local_binding/USER_CONTINUATION.json"
    preview_path = project / "data/qa/goal_context_production_repair_20261013/CONSISTENCY_EVIDENCE_REQUEST_PREVIEW_v1.json"
    ledger_path = parent / "CALL_LEDGER.json"
    receipt_path = parent / "native561.json"
    profile_path = project / "profile.json"
    seed = {"schema": "offline/native_goal", "whole_plan": {"premise": "synthetic complete seed561"}}
    diagnostic = {"native_goal_ordinal": 561, "source_root": str(parent),
                  "offline_failure": "complete native content revision"}
    inputs, profile = {"source": "synthetic frozen source"}, {"writer": "synthetic profile"}
    control.write(authority_path, {"human_authorized": True, "user_quote": "minimax随便追加"})
    control.write(parent / "STATE.json", {
        "status": "halt_full_review_contract_requires_pipeline_diagnosis",
        "spend": {"effective_calls_started": 567, "effective_reported_tokens": 10983919,
                  "effective_calls_with_known_usage": 565},
        "cumulative_goal_candidates_used": 15,
    })
    control.write(receipt_path, {"output": seed})
    control.write(ledger_path, {"calls": [{"ordinal": 561, "receipt": receipt_path.name,
        "receipt_sha256": control.sha_file(receipt_path)}]})
    control.write(parent / "INPUTS.json", inputs)
    control.write(profile_path, profile)
    originals = {path: path.read_bytes() for path in (authority_path, parent / "STATE.json",
        receipt_path, ledger_path, parent / "INPUTS.json", profile_path)}
    for name, value in {"PROJECT": project, "PREFLIGHT_PARENT": parent,
                       "APPROVAL": approval_path, "PROFILE": profile_path,
                       "ROOT": project / "new_run", "CLAIM": project / "new_claim/CLAIM.json"}.items():
        monkeypatch.setattr(run, name, value)
    monkeypatch.setattr(run.previous, "APPROVAL", authority_path)
    events = []

    def local_read(path):
        path = Path(path)
        assert path.is_relative_to(project)
        events.append(("read", path))
        return control.read(path)

    def verify(seed_value):
        assert seed_value == control.read(receipt_path)["output"]
        row = control.read(ledger_path)["calls"][0]
        if row["ordinal"] != 561 or row["receipt_sha256"] != control.sha_file(receipt_path):
            raise ValueError("native561 receipt changed")
        events.append(("verify", deepcopy(seed_value)))
        return {"ordinal": 561, "receipt_path": str(receipt_path),
                "receipt_sha256": control.sha_file(receipt_path),
                "native_sha256": control.digest(seed_value), "contract_valid": True,
                "semantic_approved": False, "used_only_for_complete_model_revision": True}

    def revision_inputs(input_value, seed_value, diagnostic_value):
        assert input_value == inputs and diagnostic_value == diagnostic
        return {"source": input_value["source"], "previous_complete_document": deepcopy(seed_value),
                "revision_diagnostics": deepcopy(diagnostic_value)}

    def prepare(prepared_inputs, profile_value):
        assert profile_value == profile
        events.append(("prepare", deepcopy(prepared_inputs)))
        return {"request": {"stage": "goal_plan", "native_seed": deepcopy(prepared_inputs["previous_complete_document"])},
                "actual_payload_prepared": True,
                "native_diagnostics": deepcopy(prepared_inputs["revision_diagnostics"])}

    def local_write(path, value, immutable=False):
        path = Path(path)
        assert path in (preview_path, approval_path)
        assert any(event[0] == "prepare" for event in events), "preview must prepare before any artifact"
        assert immutable is True
        events.append(("write", path))
        return control.write(path, value, immutable)

    monkeypatch.setattr(run, "read", local_read)
    monkeypatch.setattr(run, "write", local_write)
    monkeypatch.setattr(run, "verify_seed_native", Mock(side_effect=verify))
    monkeypatch.setattr(run, "build_revision_diagnostics", Mock(return_value=deepcopy(diagnostic)))
    monkeypatch.setattr(run, "revision_planning_inputs", Mock(side_effect=revision_inputs))
    prepare_mock = Mock(side_effect=prepare)
    monkeypatch.setattr(run.workflow, "prepare_goal_request", prepare_mock)
    monkeypatch.setattr(run, "now", Mock(side_effect=["offline-first-created-at", "offline-later-created-at"] * 4))
    return {"run": run, "project": project, "authority": authority_path, "approval": approval_path,
            "preview": preview_path, "ledger": ledger_path, "receipt": receipt_path,
            "state": parent / "STATE.json", "originals": originals,
            "events": events, "prepare": prepare_mock}


def assert_no_new_grant_or_dispatch(local):
    assert not local["run"].ROOT.exists()
    assert not local["run"].CLAIM.exists()
    for path, original_bytes in local["originals"].items():
        assert path.read_bytes() == original_bytes


def test_preview_failure_leaves_no_authorization_or_preview_artifact(local_authorizer):
    local = local_authorizer
    local["prepare"].side_effect = ValueError("synthetic actual preview rejected")
    with pytest.raises(ValueError, match="actual preview rejected"):
        authorizer.main()
    assert local["prepare"].call_count == 1
    assert not local["approval"].exists() and not local["preview"].exists()
    assert not any(event[0] == "write" for event in local["events"])
    assert_no_new_grant_or_dispatch(local)


def test_successful_reentry_preserves_original_authorization_and_preview_bytes(local_authorizer):
    local = local_authorizer
    authorizer.main()
    originals = {path: path.read_bytes() for path in (local["approval"], local["preview"])}
    authorizer.main()
    assert {path: path.read_bytes() for path in originals} == originals
    binding = control.read(local["approval"])
    preview = control.read(local["preview"])
    assert binding["created_at"] == "offline-first-created-at"
    assert binding["parent_goal_candidates_used"] == 15 and binding["seed_native_identity"]["ordinal"] == 561
    assert binding["parent_ledger_sha256"] == control.sha_file(local["ledger"])
    assert binding["authority_source_sha256"] == control.sha_file(local["authority"])
    assert not binding["old_ledger_reset"] and not binding["media_authorized"] and not binding["publish_authorized"]
    assert preview["provider_calls"] == 0 and not preview["creative_quality_approved"]
    assert preview["old_review_not_converted"] is True
    assert local["prepare"].call_count == 2
    assert [event[0] for event in local["events"]].index("prepare") < [event[0] for event in local["events"]].index("write")
    assert_no_new_grant_or_dispatch(local)


def test_partial_local_preparation_restores_only_missing_preview_without_new_grant(local_authorizer):
    local = local_authorizer
    authorizer.main()
    approval_bytes = local["approval"].read_bytes()
    preview_bytes = local["preview"].read_bytes()
    local["preview"].unlink()
    authorizer.main()
    assert local["approval"].read_bytes() == approval_bytes
    assert local["preview"].read_bytes() == preview_bytes
    assert control.read(local["approval"])["created_at"] == "offline-first-created-at"
    assert local["prepare"].call_count == 2
    assert_no_new_grant_or_dispatch(local)


def test_spent_parent_seed_and_authority_mismatch_stop_without_write_or_regrant(local_authorizer):
    local = local_authorizer
    mutations = [
        (local["state"], lambda value: value["spend"].update(effective_calls_started=559)),
        (local["state"], lambda value: value["spend"].update(effective_reported_tokens=10983918)),
        (local["state"], lambda value: value.update(cumulative_goal_candidates_used=14)),
        (local["state"], lambda value: value.update(status="prepared")),
        (local["ledger"], lambda value: value["calls"][0].update(ordinal=554)),
        (local["receipt"], lambda value: value["output"]["whole_plan"].update(premise="changed native seed")),
        (local["authority"], lambda value: value.update(user_quote="synthetic unauthorized quote")),
        (local["authority"], lambda value: value.update(human_authorized=False)),
    ]
    for path, mutate in mutations:
        original = path.read_bytes()
        changed = control.read(path)
        mutate(changed)
        control.write(path, changed)
        try:
            with pytest.raises((ValueError, StopIteration)):
                authorizer.main()
            assert not local["approval"].exists() and not local["preview"].exists()
            assert not any(event[0] == "write" for event in local["events"])
            assert local["prepare"].call_count == 0
            assert not local["run"].ROOT.exists() and not local["run"].CLAIM.exists()
        finally:
            path.write_bytes(original)
    assert_no_new_grant_or_dispatch(local)

    authorizer.main()
    artifacts = {path: path.read_bytes() for path in (local["approval"], local["preview"])}
    for path in (local["authority"], local["receipt"], local["ledger"]):
        original = path.read_bytes()
        changed = control.read(path)
        if path == local["receipt"]:
            changed["output"]["whole_plan"]["premise"] = "changed native seed"
        else:
            changed["binding_mutation"] = "synthetic changed provenance"
        control.write(path, changed)
        prior_write_count = sum(event[0] == "write" for event in local["events"])
        try:
            with pytest.raises(ValueError, match="existing text authorization differs; never replace or regrant|native561 receipt changed"):
                authorizer.main()
            assert sum(event[0] == "write" for event in local["events"]) == prior_write_count
            assert {artifact: artifact.read_bytes() for artifact in artifacts} == artifacts
            assert not local["run"].ROOT.exists() and not local["run"].CLAIM.exists()
        finally:
            path.write_bytes(original)
    assert local["prepare"].call_count == 3
    assert_no_new_grant_or_dispatch(local)


def test_missing_preview_recovery_rejects_changed_actual_diagnostic_before_restoring(local_authorizer, monkeypatch):
    local = local_authorizer
    authorizer.main()
    approval_bytes = local["approval"].read_bytes()
    prior_write_count = sum(event[0] == "write" for event in local["events"])
    local["preview"].unlink()
    changed = {"native_goal_ordinal": 561, "offline_failure": "different complete diagnosis after authorization"}
    monkeypatch.setattr(local["run"], "build_revision_diagnostics", Mock(return_value=deepcopy(changed)))
    monkeypatch.setattr(local["run"], "revision_planning_inputs", Mock(side_effect=lambda inputs, seed, diagnostic:
        {"source": inputs["source"], "previous_complete_document": deepcopy(seed),
         "revision_diagnostics": deepcopy(diagnostic)}))
    with pytest.raises(ValueError, match="existing text authorization differs; never replace or regrant"):
        authorizer.main()
    assert local["approval"].read_bytes() == approval_bytes and not local["preview"].exists()
    assert sum(event[0] == "write" for event in local["events"]) == prior_write_count
    assert_no_new_grant_or_dispatch(local)


def test_existing_preview_is_immutable_when_recomputed_actual_request_differs(local_authorizer):
    local = local_authorizer
    authorizer.main()
    before = {path: path.read_bytes() for path in (local["approval"], local["preview"])}
    local["prepare"].return_value = {"request": {"stage": "goal_plan", "different_actual_request": True}}
    local["prepare"].side_effect = None
    with pytest.raises((RuntimeError, ValueError)):
        authorizer.main()
    assert {path: path.read_bytes() for path in before} == before
    assert_no_new_grant_or_dispatch(local)
