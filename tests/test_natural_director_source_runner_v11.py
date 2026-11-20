"""Actual frozen file-backed flow with fake native services and bounded recovery."""
from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from src.content_factory import natural_director_source_runner_v11 as runner

H = runpy.run_path(str(Path(__file__).with_name("test_natural_director_pipeline_v10.py")))
pipe, fx, F = H["pipe"], H["fx"], H["F"]
projection_cases = runpy.run_path(str(Path(__file__).with_name("test_known_writer_projection_recovery_v1.py")))
failed_source = projection_cases["failed_source"]


@pytest.fixture
def fresh(tmp_path, monkeypatch, request):
    registry = tmp_path / "canonical"
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", registry)
    monkeypatch.setattr(pipe.parent, "CANONICAL_REGISTRY", registry)
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *a, **kw: [])
    source = tmp_path / "source.txt"
    source.write_text("A fresh story: the listener answers and the author decides.", encoding="utf-8")
    writer, director = tmp_path / "writer", tmp_path / "natural"
    authorization = H["auth"](tmp_path, writer, calls=getattr(request, "param", 20))
    pipe.prepare_source(writer, authorization_path=authorization, source_path=source,
                        source_kind="original", title="Coordinator fresh source",
                        brief={"max_duration_seconds": 23})
    return writer, director, authorization


def _run(fresh, client, **kwargs):
    writer, director, authorization = fresh
    return runner.execute_source(writer, run_dir=director,
                                 authorization_path=authorization, clients=client, **kwargs)


def _all_values():
    return [*F["success_values"]()[:2], *H["values"]()]


def _duplicate_review(*, unlinked=False):
    raw = fx.review("revise")
    raw["adjudication"]["new_issues"] = [deepcopy(raw["full_review"]["issues"][0])]
    if unlinked:
        for check in raw["full_review"]["checks"]:
            check["issue_ids"] = []
    return raw


def _revision_values(*, unlinked=False):
    return [F["success_values"]()[0], fx.result(_duplicate_review(unlinked=unlinked), "director"),
            fx.result("A complete new native screenplay correcting the confirmed causal issue."),
            fx.result(fx.review(), "director"), *H["values"]()]


def _forbid(*args, **kwargs):
    raise AssertionError("unexpected recovery or dispatch")


def _events(writer):
    return [pipe.core._read(path) for path in sorted(writer.glob("SOURCE_RUNNER_V11_EVENT_*.json"))]


def test_real_frozen_source_to_final_native_request_gate_without_recovery(fresh):
    client = fx.FakeClients(_all_values())
    view = _run(fresh, client)
    writer, director, _ = fresh
    assert view["status"] == "text_ready_for_production", view["blockers"]
    assert view["source_runner_schema"] == runner.VERSION
    assert view["combined_calls_started"] == 5 and len(client.calls) == 5
    assert not any(view["automatic_recoveries_used"].values())
    assert [pipe.core._read(path)["stage"] for path in sorted(writer.glob("REQUEST_*.json"))] == ["writer_full", "review_full"]
    assert [pipe.core._read(path)["stage"] for path in sorted(director.glob("REQUEST_*.json"))] == ["natural_director", "extract_review", "final_review"]
    pipe.contracts.validate_handoff_for_dispatch(pipe.core._read(director / "PRODUCTION_HANDOFF.json"))
    before = {path.name: path.read_bytes() for path in writer.glob("REQUEST_*.json")}
    assert _run(fresh, fx.FakeClients([]))["status"] == "text_ready_for_production"
    assert before == {path.name: path.read_bytes() for path in writer.glob("REQUEST_*.json")}


def test_first_writer_windows_projection_recovers_once_and_never_rewrites_writer(fresh, monkeypatch):
    writer, _, _ = fresh
    original, fired = Path.replace, False

    def fail_once(path, target):
        nonlocal fired
        if path.name.startswith(".state-") and Path(target) == writer / "state.json" and not fired:
            if pipe.core._read(path).get("stage") == "review_full":
                fired = True
                raise PermissionError(f"[WinError 5] access denied: {path} -> {target}")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_once)
    client = fx.FakeClients(_all_values())
    view = _run(fresh, client)
    assert view["status"] == "text_ready_for_production", view.get("blockers")
    assert fired and len(client.calls) == 5 and view["combined_calls_started"] == 5
    assert view["automatic_recoveries_used"] == {"writer_projection": True, "complete_review_revision": False}
    assert (writer / "STATE_00005.json").is_file() and (writer / "STATE_00006.json").is_file()
    assert pipe.core._read(writer / "STATE_00005.json")["status"] == "needs_attention"
    assert sum(pipe.core._read(path)["stage"] == "writer_full" for path in writer.glob("REQUEST_*.json")) == 1
    applied = [event for event in _events(writer) if event["kind"] == "recovery_applied"]
    assert len(applied) == 1 and applied[0]["result"]["model_calls_started"] == 0
    assert applied[0]["recovery_kind"] == "writer_projection"
    assert (writer / "SOURCE_RUNNER_V11_WRITER_PROJECTION_PLAN.json").is_file()


def test_existing_projection_recovery_is_inherited_without_second_apply(failed_source, monkeypatch):
    writer = failed_source
    authorization = writer.parent / "AUTHORIZATION.json"
    plan = runner.projection.plan_recovery(writer)
    runner.projection.apply_recovery(writer, reviewed_plan=plan)
    historical = (writer / runner.projection.RECORD).read_bytes()
    monkeypatch.setattr(runner.projection, "apply_recovery", _forbid)
    client = fx.FakeClients([F["success_values"]()[1], *H["values"]()])
    view = runner.execute_source(writer, run_dir=writer.parent / "natural",
                                 authorization_path=authorization, clients=client)
    assert view["status"] == "text_ready_for_production", view.get("blockers")
    assert len(client.calls) == 4 and view["combined_calls_started"] == 5
    assert view["automatic_recoveries_used"]["writer_projection"] is False
    assert view["preexisting_helper_recoveries"]["writer_projection"] is True
    assert (writer / runner.projection.RECORD).read_bytes() == historical
    assert not (writer / "SOURCE_RUNNER_V11_WRITER_PROJECTION_ATTEMPT.json").exists()


@pytest.mark.parametrize("unlinked", [False, True])
def test_known_complete_revise_creates_new_full_writer_and_new_same_source_review(fresh, unlinked):
    client = fx.FakeClients(_revision_values(unlinked=unlinked))
    view = _run(fresh, client)
    writer, director, _ = fresh
    assert view["status"] == "text_ready_for_production", view.get("blockers")
    assert len(client.calls) == 7 and view["combined_calls_started"] == 7
    assert view["automatic_recoveries_used"] == {"writer_projection": False, "complete_review_revision": True}
    state = pipe.parent._verify(writer)[1]
    assert state["revisions_used"] == state["quality_revisions_used"] == 1
    assert not (writer / "REVIEW_BUNDLE_002.json").exists() and (writer / "REVIEW_BUNDLE_004.json").exists()
    native_review_text = pipe.core._read(writer / "RESPONSE_002.json")["response_text"]
    assert json.loads(native_review_text) == _duplicate_review(unlinked=unlinked)
    request = pipe.core._read(writer / "REQUEST_003.json")
    materials = json.loads(request["messages"][-1]["content"])
    assert materials["previous_draft"] == (writer / "DRAFT_001.md").read_text(encoding="utf-8")
    assert materials["review"]["native_review_text"] == native_review_text
    assert materials["review"]["old_review_accepted"] is False
    assert pipe.core._read(writer / "BINDING.json")["budget"]["max_calls"] == 20
    assert pipe.core._read(director / "BINDING.json")["inherited_consumption"]["calls_started"] == 4


def test_both_eligible_failures_recover_once_each_in_one_actual_flow(fresh, monkeypatch):
    writer, _, _ = fresh
    original, fired = Path.replace, False

    def fail_once(path, target):
        nonlocal fired
        if path.name.startswith(".state-") and Path(target) == writer / "state.json" and not fired:
            if pipe.core._read(path).get("stage") == "review_full":
                fired = True
                raise PermissionError(f"[WinError 5] access denied: {path} -> {target}")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_once)
    client = fx.FakeClients(_revision_values(unlinked=True))
    view = _run(fresh, client)
    assert view["status"] == "text_ready_for_production", view.get("blockers")
    assert view["automatic_recoveries_used"] == {"writer_projection": True, "complete_review_revision": True}
    assert len(client.calls) == 7 and view["combined_calls_started"] == 7
    assert len(list(writer.glob("SOURCE_RUNNER_V11_*_ATTEMPT.json"))) == 2
    assert len([row for row in _events(writer) if row["kind"] == "recovery_applied"]) == 2


def test_failed_local_apply_is_durably_awaiting_completion_without_second_apply(failed_source, monkeypatch):
    writer = failed_source
    fresh = writer, writer.parent / "natural", writer.parent / "AUTHORIZATION.json"
    applications = []

    def local_failure(*args, **kwargs):
        applications.append(kwargs["reviewed_plan"])
        raise PermissionError("Known local apply could not complete")

    monkeypatch.setattr(runner.projection, "apply_recovery", local_failure)
    with pytest.raises(PermissionError):
        _run(fresh, fx.FakeClients([]))
    for _ in range(2):
        client = fx.FakeClients([])
        view = _run(fresh, client)
        assert view["status"] == "awaiting_local_completion" and view["dispatch_blocked"]
        assert view["awaiting_local_completion"] == ["writer_projection"]
        assert not any(view["automatic_recoveries_used"].values()) and not client.calls
    assert len(applications) == 1


@pytest.mark.parametrize("fresh", [3], indirect=True)
def test_original_remaining_call_budget_cannot_be_expanded_by_review_recovery(fresh):
    client = fx.FakeClients(_revision_values()[:2])
    with pytest.raises(ValueError, match="duplicated"):
        _run(fresh, client)
    writer, director, _ = fresh
    assert len(client.calls) == 2 and not director.exists()
    assert not list(writer.glob("SOURCE_RUNNER_V11_*_ATTEMPT.json"))
    assert pipe.core._read(writer / "BINDING.json")["budget"]["max_calls"] == 3


@pytest.mark.parametrize("finish,unknown", [("length", False), ("stop", True)])
def test_unknown_or_truncated_writer_never_enters_either_recovery(fresh, finish, unknown, monkeypatch):
    monkeypatch.setattr(runner.projection, "plan_recovery", _forbid)
    monkeypatch.setattr(runner.review_revision, "plan_revision", _forbid)
    client = fx.FakeClients([fx.result("Incomplete or unknown native writer.", finish=finish, unknown=unknown)])
    with pytest.raises(RuntimeError):
        _run(fresh, client)
    writer, director, _ = fresh
    assert len(client.calls) == 1 and pipe.inspect_source(writer)["pending_call"] == 1
    assert not director.exists() and not list(writer.glob("SOURCE_RUNNER_V11_*_ATTEMPT.json"))
    with pytest.raises(RuntimeError, match="未决"):
        _run(fresh, fx.FakeClients([]))


def test_transport_unknown_keeps_original_identity_and_zero_second_call(fresh):
    client = fx.FakeClients([RuntimeError("transport outcome unknown")])
    with pytest.raises(RuntimeError):
        _run(fresh, client)
    writer, director, _ = fresh
    assert len(client.calls) == 1 and pipe.inspect_source(writer)["pending_call"] == 1
    assert len(list(writer.glob("CLAIM_*.json"))) == 1 and not director.exists()


def test_unrelated_complete_review_contract_failure_does_not_create_a_new_draft(fresh):
    rejected = fx.review("revise")
    rejected.pop("scene_ledger")
    client = fx.FakeClients([F["success_values"]()[0], fx.result(rejected, "director")])
    with pytest.raises((ValueError, RuntimeError, KeyError)):
        _run(fresh, client)
    writer, director, _ = fresh
    assert len(client.calls) == 2 and not director.exists()
    assert not list(writer.glob("SOURCE_RUNNER_V11_*_ATTEMPT.json"))
    assert len(list(writer.glob("DRAFT_*.md"))) == 1


def test_wrong_authorization_or_original_history_is_not_migrated(fresh, tmp_path):
    writer, director, _ = fresh
    wrong = tmp_path / "wrong_authorization.json"
    wrong.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="同一专属授权"):
        runner.execute_source(writer, run_dir=director, authorization_path=wrong, clients=fx.FakeClients([]))
    assert not (writer / runner.BINDING).exists()
    old = tmp_path / "old_office"
    old.mkdir()
    (old / "state.json").write_text('{"pending_call": 1}', encoding="utf-8")
    before = {path.name: path.read_bytes() for path in old.iterdir()}
    with pytest.raises(OSError):
        runner.execute_source(old, run_dir=director, authorization_path=wrong, clients=fx.FakeClients([]))
    assert before == {path.name: path.read_bytes() for path in old.iterdir()}


def test_execution_lock_blocks_before_mutable_read_or_wrapper_write(fresh, monkeypatch):
    writer, _, _ = fresh
    (writer / ".execution.lock").touch()
    monkeypatch.setattr(pipe.parent, "_verify", _forbid)
    with pytest.raises(RuntimeError, match="正在执行"):
        _run(fresh, fx.FakeClients([]))
    assert not (writer / runner.BINDING).exists() and not (writer / runner.LOCK).exists()


def test_wrapper_binding_change_blocks_before_another_request(fresh):
    writer, _, _ = fresh
    _run(fresh, fx.FakeClients([F["success_values"]()[0]]), max_steps=1)
    binding = pipe.core._read(writer / runner.BINDING)
    binding["automatic_recovery_limits"]["writer_projection"] = 9
    (writer / runner.BINDING).write_text(json.dumps(binding), encoding="utf-8")
    client = fx.FakeClients([])
    with pytest.raises(ValueError):
        _run(fresh, client)
    assert not client.calls and len(list(writer.glob("REQUEST_*.json"))) == 1


def test_cli_source_execute_uses_recovery_coordinator_while_direct_execute_remains_v10(monkeypatch, tmp_path, capsys):
    from scripts import run_natural_director_v10 as cli
    authorization = tmp_path / "authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "execute_source", lambda **kwargs: calls.append("wrapper") or {"status": "running"})
    monkeypatch.setattr(pipe, "execute", lambda **kwargs: calls.append("v10") or {"status": "running"})
    assert cli.main(["source-execute", "--source-run-dir", "source", "--run-dir", "natural",
                     "--authorization-path", str(authorization)]) == 0
    capsys.readouterr()
    assert cli.main(["execute", "--run-dir", "natural"]) == 0
    capsys.readouterr()
    assert calls == ["wrapper", "v10"]
