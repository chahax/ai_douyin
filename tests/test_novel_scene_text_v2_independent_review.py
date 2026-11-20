"""Independent provider and durable-dispatch probes; all calls are fake."""
from copy import deepcopy
import json
import shutil

import pytest

from src.content_factory import novel_scene_text_v2 as scene
from src.content_factory.creative_workflow_roles import RoleResult
from tests.test_novel_scene_text_v2 import prepared as imported_prepared, Clients as BaseClients

prepared = imported_prepared


class Clients(BaseClients):
    """Always provide production-valid identity for unrelated failure probes."""

    def call(self, role, messages, **kwargs):
        result = super().call(role, messages, **kwargs)
        model = scene._provider_protocol()["roles"][role]["model"]
        text = result.text
        if role == "writer":
            value = json.loads(text)

            def strings(item):
                if isinstance(item, str):
                    return [item]
                if isinstance(item, dict):
                    return [part for key, child in item.items() if key != "screenplay_markdown" for part in strings(child)]
                if isinstance(item, list):
                    return [part for child in item for part in strings(child)]
                return []

            # A complete fake readable projection isolates provider/lock faults
            # from changes to the implementation agent's content fixture.
            value["screenplay_markdown"] += "\n" + "\n".join(strings(value))
            text = json.dumps(value, ensure_ascii=False)
        return RoleResult(text, {**result.metadata, "response_model": model},
                          {**result.response_payload, "model": model})


@pytest.mark.parametrize("native_fault", ["usage_missing", "usage_mismatch", "finish_mismatch", "no_choices"])
def test_native_envelope_disagreement_halts_without_review_or_redispatch(prepared, native_fault):
    run, _ = prepared

    class Disagrees(Clients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            native = deepcopy(result.response_payload)
            if native_fault == "usage_missing":
                native["usage"] = {}
            elif native_fault == "usage_mismatch":
                native["usage"]["total_tokens"] = 999
            elif native_fault == "finish_mismatch":
                native["choices"][0]["finish_reason"] = "length"
            else:
                native["choices"] = []
            return RoleResult(result.text, result.metadata, native)

    clients = Disagrees()
    try:
        result = scene.execute(run, clients=clients)
    except (ValueError, RuntimeError):
        result = scene.inspect(run)
    assert result["status"] != "machine_text_complete"
    assert len(clients.calls) == 1
    receipt = json.loads((run / "CALL_010.json").read_text(encoding="utf-8"))
    assert receipt["response_payload"]
    try:
        scene.execute(run, clients=clients)
    except (ValueError, RuntimeError):
        pass
    assert len(clients.calls) == 1


def test_returned_response_write_failure_keeps_pending_id_and_stops_resume(prepared, monkeypatch):
    run, _ = prepared
    clients = Clients()
    original = scene._write

    def disk_failure(path, value):
        if path.name == "CALL_010.json" and value.get("status") != "pending":
            raise OSError("simulated response save failure")
        return original(path, value)

    monkeypatch.setattr(scene, "_write", disk_failure)
    with pytest.raises(OSError, match="save failure"):
        scene.execute(run, clients=clients)
    monkeypatch.setattr(scene, "_write", original)
    record = json.loads((run / "CALL_010.json").read_text(encoding="utf-8"))
    assert record["status"] == "pending"
    assert len(clients.calls) == 1
    with pytest.raises(RuntimeError):
        scene.execute(run, clients=clients)
    assert len(clients.calls) == 1


def test_old_v1_entry_is_locked_during_every_v2_provider_call(prepared):
    from scripts import run_novel_platform_text_trial_v1 as old_entry
    run, parent = prepared

    class ChecksParentLock(Clients):
        def call(self, role, messages, **kwargs):
            assert (parent / ".novel_trial_execution.lock").exists()
            with pytest.raises(RuntimeError, match="执行锁"):
                old_entry.execute(parent, clients=Clients())
            return super().call(role, messages, **kwargs)

    clients = ChecksParentLock()
    assert scene.execute(run, clients=clients)["status"] == "machine_text_complete"
    assert len(clients.calls) == 2


def test_existing_old_run_lock_cannot_be_stolen_or_removed(prepared):
    run, parent = prepared
    lock = parent / ".novel_trial_execution.lock"
    evidence = b'{"owner":"old-request-is-inflight"}'
    lock.write_bytes(evidence)
    clients = Clients()
    with pytest.raises((RuntimeError, ValueError, FileExistsError)):
        scene.execute(run, clients=clients)
    assert clients.calls == []
    assert lock.read_bytes() == evidence


@pytest.mark.parametrize("unknown", [False, True])
def test_old_v1_cannot_restart_after_v2_completion_or_unknown_result(prepared, unknown):
    from scripts import run_novel_platform_text_trial_v1 as old_entry
    run, parent = prepared
    clients = Clients(tokens=None) if unknown else Clients()
    if unknown:
        with pytest.raises(RuntimeError):
            scene.execute(run, clients=clients)
    else:
        assert scene.execute(run, clients=clients)["status"] == "machine_text_complete"
    # Old frozen state is still 9 calls; a durable takeover must prevent that
    # entry from consuming its apparently remaining budget after the new work.
    with pytest.raises(RuntimeError, match="执行锁"):
        old_entry.execute(parent, clients=Clients())
    assert (parent / ".novel_trial_execution.lock").exists()


def test_parent_spend_change_between_snapshot_and_takeover_is_not_lost(prepared, tmp_path, monkeypatch):
    _, original_parent = prepared
    parent = tmp_path / "parent_before_takeover"
    shutil.copytree(original_parent, parent, ignore=shutil.ignore_patterns(".novel_trial_execution.lock"))
    original_snapshot = scene._parent_snapshot
    changed = False

    def old_entry_finishes_call(*args, **kwargs):
        nonlocal changed
        snapshot = original_snapshot(*args, **kwargs)
        if not changed:
            changed = True
            state_path = parent / "creative/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update(calls_started=10, reported_tokens=94917)
            scene._write(state_path, state)
            scene._write(parent / "creative/NATIVE_RESPONSE_010.json", {
                "call_ordinal": 10, "status": "response_received",
                "response_metadata": {"total_tokens": 7, "finish_reason": "stop"},
                "response_payload": {"usage": {"total_tokens": 7}, "choices": [{"finish_reason": "stop"}]},
            })
        return snapshot

    monkeypatch.setattr(scene, "_parent_snapshot", old_entry_finishes_call)
    run = tmp_path / "changed_parent_continuation"
    try:
        scene.prepare(parent, run, continuation_registry=tmp_path / "fresh_continuation_registry")
    except (ValueError, RuntimeError):
        return  # A changed parent must either stop or be fully re-snapshotted.
    view = scene.preview(run)
    assert view["state"]["calls_started"] == 10
    assert view["state"]["reported_tokens"] == 94917
