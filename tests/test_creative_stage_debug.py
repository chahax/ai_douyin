from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from src.content_factory.creative_stage_debug import (
    CreativeStageCommandService,
    compare_stage_versions,
    record_stage_artifact,
)
from src.content_factory.creative_workflow import CreativeWorkflow
from test_creative_workflow import FakeClients, _answers, _bundle


def _hash(value):
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_breakpoint_and_next_stage_reuse_saved_budget_and_artifacts(tmp_path):
    run_dir = tmp_path / "run"
    clients = FakeClients(_answers())
    bundle = _bundle(tmp_path)

    first = CreativeWorkflow(
        run_dir,
        clients=clients,
        stop_after_stage="writer_analysis",
    ).run(bundle)

    assert first["status"] == "debug_breakpoint"
    assert first["debug_breakpoint"]["stage_id"] == "writer_analysis"
    assert first["calls_started"] == 1
    snapshot = CreativeStageCommandService(run_dir).inspect()
    assert [row["stage_id"] for row in snapshot["stages"]] == ["writer_analysis"]
    assert snapshot["stages"][0]["artifact_verified"] is True

    second = CreativeWorkflow(
        run_dir,
        clients=clients,
        max_new_stages=1,
    ).run(bundle)

    assert second["status"] == "debug_breakpoint"
    assert second["debug_breakpoint"]["stage_id"] == "director_brief"
    assert second["calls_started"] == 2
    assert len(clients.calls) == 2
    snapshot = CreativeStageCommandService(run_dir).inspect()
    assert [row["stage_id"] for row in snapshot["stages"]] == [
        "writer_analysis", "director_brief",
    ]


def test_feedback_binds_current_hash_and_invalidates_only_downstream_debug_view(tmp_path):
    run_dir = tmp_path / "run"
    clients = FakeClients(_answers())
    bundle = _bundle(tmp_path)
    CreativeWorkflow(
        run_dir,
        clients=clients,
        stop_after_stage="director_brief",
    ).run(bundle)
    service = CreativeStageCommandService(run_dir)

    receipt = service.feedback(
        "writer_analysis",
        "候选动机证据不足，应回到故事分析阶段修订。",
        disposition="must_fix",
    )
    snapshot = service.inspect()

    assert receipt["stage_id"] == "writer_analysis"
    assert receipt["output_sha256"] == snapshot["stages"][0]["output_sha256"]
    assert snapshot["feedback_status"] == "revision_required"
    assert snapshot["stages"][0]["validity"] == "needs_revision"
    assert snapshot["stages"][1]["validity"] == "invalidated"
    assert snapshot["calls_started"] == 2


def test_immutable_versions_have_deterministic_diff(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    first = {"title": "旧版", "beats": [{"id": "B01"}]}
    second = {"title": "新版", "beats": [{"id": "B01"}, {"id": "B02"}]}
    state = {
        "writer_prompt_version": "fixture",
        "model_profile": "fixture",
        "review_policy_version": "fixture",
        "budget_policy_version": "fixture",
        "max_calls": 20,
        "max_total_tokens": 1000,
        "stages": [{
            "name": "writer_script", "role": "writer",
            "input_sha256": "input-1", "output_sha256": _hash(first),
        }],
    }
    record_stage_artifact(run_dir, state, "writer_script", "writer", first)
    state["stages"][0] = {
        **state["stages"][0],
        "input_sha256": "input-2",
        "output_sha256": _hash(second),
    }
    record_stage_artifact(run_dir, state, "writer_script", "writer", second)

    result = compare_stage_versions(run_dir, "writer_script")

    assert result["base_sha256"] == _hash(first)
    assert result["target_sha256"] == _hash(second)
    assert '-  "title": "旧版"' in result["diff"]
    assert '+  "title": "新版"' in result["diff"]


def test_noninitial_must_fix_resume_replays_valid_upstream_and_reaches_target(tmp_path):
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    original = FakeClients(_answers())
    first = CreativeWorkflow(
        run_dir, clients=original, stop_after_stage="director_brief",
    ).run(bundle)
    assert first["calls_started"] == 2
    feedback = CreativeStageCommandService(run_dir).feedback(
        "director_brief", "必须补足视觉表达与表演节奏。", disposition="must_fix",
    )
    revised_brief = deepcopy(_answers()[1])
    revised_brief["visual_strategy"] = "修订版：补足视觉表达递进与表演节奏。"
    resumed = FakeClients([revised_brief])

    result = CreativeWorkflow(
        run_dir, clients=resumed, stop_after_stage="director_brief",
    ).run(bundle)

    assert result["status"] == "debug_breakpoint"
    assert result["debug_breakpoint"]["stage_id"] == "director_brief"
    assert result["calls_started"] == 3
    assert len(resumed.calls) == 1
    snapshot = CreativeStageCommandService(run_dir).inspect()
    assert snapshot["feedback_status"] == "resolved"
    saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert saved_state["debug_feedback"][0]["resolved_by_output_sha256"] != feedback["output_sha256"]


def test_resolved_repair_context_replays_then_rebuilds_invalidated_downstream(tmp_path):
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    initial = FakeClients(_answers())
    first = CreativeWorkflow(
        run_dir, clients=initial, stop_after_stage="writer_script",
    ).run(bundle)
    assert first["calls_started"] == 3
    original_brief = json.loads((run_dir / "director_brief.json").read_text(encoding="utf-8"))
    feedback = CreativeStageCommandService(run_dir).feedback(
        "director_brief", "必须修订导演表达。", disposition="must_fix",
    )

    revised_brief = deepcopy(_answers()[1])
    revised_brief["visual_strategy"] = "修订后视觉策略"
    repair_clients = FakeClients([revised_brief])
    repaired = CreativeWorkflow(
        run_dir, clients=repair_clients, stop_after_stage="director_brief",
    ).run(bundle)
    assert repaired["status"] == "debug_breakpoint"
    assert repaired["calls_started"] == 4
    assert repaired["debug_feedback_status"] == "resolved"
    assert repaired["debug_stage_validity"]["writer_script"] == "invalidated"
    archive = run_dir / f"director_brief__before_feedback_{feedback['feedback_id']}.json"
    assert json.loads(archive.read_text(encoding="utf-8"))["output_sha256"] == original_brief["output_sha256"]

    revised_script = deepcopy(_answers()[2])
    revised_script["title"] = "下游重建后的剧本"
    downstream_clients = FakeClients([revised_script])
    resumed = CreativeWorkflow(
        run_dir, clients=downstream_clients, stop_after_stage="writer_script",
    ).run(bundle)
    assert resumed["status"] == "debug_breakpoint"
    assert resumed["debug_breakpoint"]["stage_id"] == "writer_script"
    assert resumed["calls_started"] == 5
    assert len(downstream_clients.calls) == 1
    assert resumed["debug_stage_validity"]["director_brief"] == "current"
    assert resumed["debug_stage_validity"]["writer_script"] == "current"


# Regression scenarios use the production runner and shared CLI/UI command service.
def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _resume(run, bundle, answers, stop="writer_script", *, single_step=False, expect_failure=False):
    clients = FakeClients(answers)
    saved = _read_json(run / "state.json")
    runner = CreativeWorkflow(
        run, clients=clients,
        **{key: saved[key] for key in ("budget_policy_version", "max_calls", "max_total_tokens",
                                     "max_revisions", "max_contract_repairs")},
        stop_after_stage=None if single_step else stop,
        max_new_stages=1 if single_step else None,
    )
    if expect_failure:
        with pytest.raises((RuntimeError, ValueError)):
            runner.run(bundle)
        result = _read_json(run / "state.json")
    else:
        result = runner.run(bundle)
    return result, clients


def _rebuilt_run(tmp_path, *, max_calls=20):
    run = tmp_path / "run"
    bundle = _bundle(tmp_path)
    initial = CreativeWorkflow(
        run, clients=FakeClients(_answers()), stop_after_stage="writer_script",
        budget_policy_version="v5_20261001", max_calls=max_calls,
        max_total_tokens=500000, max_revisions=5, max_contract_repairs=8,
    ).run(bundle)
    assert initial["calls_started"] == 3
    service = CreativeStageCommandService(run)
    feedback = service.feedback("director_brief", "FIXTURE repair the director")
    brief = deepcopy(_answers()[1])
    brief["visual_strategy"] = "FIXTURE repaired director"
    repaired, _ = _resume(run, bundle, [brief], "director_brief")
    assert repaired["status"] == "debug_breakpoint"
    script = deepcopy(_answers()[2])
    script["title"] = "FIXTURE rebuilt script"
    rebuilt, _ = _resume(run, bundle, [script])
    assert rebuilt["status"] == "debug_breakpoint" and rebuilt["calls_started"] == 5
    return run, bundle, script, feedback


def test_two_successive_script_repairs_select_current_keep_history_and_budget(tmp_path):
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    service = CreativeStageCommandService(run)
    upstream = (run / "writer_analysis.json").read_bytes()
    initial_history = {
        path: path.read_bytes() for path in (run / ".creative_debug").rglob("*.json")
        if path.name != "index.json"
    }
    original_stages = deepcopy(_read_json(run / "state.json")["stages"])
    for calls in (6, 7):
        current = _read_json(run / "writer_script.json")
        feedback = service.feedback("writer_script", f"FIXTURE script repair {calls}")
        assert feedback["output_sha256"] == current["output_sha256"]
        assert _read_json(run / "state.json")["debug_stage_validity"]["director_brief"] == "current"
        script = {**script, "title": f"FIXTURE script version {calls}"}
        state, clients = _resume(run, bundle, [script])
        assert state["status"] == "debug_breakpoint" and len(clients.calls) == 1
        assert state["calls_started"] == calls
        assert state["debug_feedback_status"] == "resolved"
        assert sum(row["usage"]["total_tokens"] for row in state["stages"]) == calls
        assert (state["max_calls"], state["max_total_tokens"], state["max_revisions"],
                state["max_contract_repairs"], state["budget_policy_version"]) == (20, 500000, 5, 8, "v5_20261001")
        replay, clients = _resume(run, bundle, [])
        assert replay["status"] == "debug_breakpoint" and replay["calls_started"] == calls
        assert not clients.calls
    snapshot = service.inspect()
    assert [row["stage_id"] for row in snapshot["stages"]] == ["writer_analysis", "director_brief", "writer_script"]
    assert len(snapshot["history"]) == 7
    assert sum(row["validity"] == "historical" for row in snapshot["history"]) == 4
    assert snapshot["stages"][-1]["output_sha256"] == _read_json(run / "writer_script.json")["output_sha256"]
    assert _read_json(run / "state.json")["stages"][:5] == original_stages
    assert all(path.read_bytes() == content for path, content in initial_history.items())
    assert (run / "writer_analysis.json").read_bytes() == upstream
    assert service.compare("writer_script")["target_sha256"] == snapshot["stages"][-1]["output_sha256"]


@pytest.mark.parametrize("reverse_feedback_order", [False, True])
def test_multiple_pending_stages_follow_dependencies_not_feedback_order(tmp_path, reverse_feedback_order):
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    service = CreativeStageCommandService(run)
    stages = ["director_brief", "writer_script"]
    if reverse_feedback_order:
        stages.reverse()
    receipts = {stage: service.feedback(stage, f"FIXTURE second round {stage}") for stage in stages}
    state = _read_json(run / "state.json")
    assert state["debug_stage_validity"]["director_brief"] == "needs_revision"
    assert state["debug_stage_validity"]["writer_script"] == "needs_revision"
    brief = deepcopy(_answers()[1])
    brief["visual_strategy"] = "FIXTURE director repaired again"
    first, clients = _resume(run, bundle, [brief], "director_brief")
    assert first["status"] == "debug_breakpoint" and first["calls_started"] == 6
    assert len(clients.calls) == 1 and first["debug_feedback_status"] == "revision_required"
    assert first["debug_stage_validity"]["writer_script"] == "needs_revision"
    script["title"] = "FIXTURE second round both stages"
    second, clients = _resume(run, bundle, [script])
    assert second["status"] == "debug_breakpoint" and second["calls_started"] == 7
    assert len(clients.calls) == 1 and second["debug_feedback_status"] == "resolved"
    for stage, feedback in receipts.items():
        archive = run / f"{stage}__before_feedback_{feedback['feedback_id']}.json"
        assert _read_json(archive)["output_sha256"] == feedback["output_sha256"]
    replay, clients = _resume(run, bundle, [])
    assert replay["calls_started"] == 7 and not clients.calls


def test_second_round_budget_exhaustion_keeps_pending_feedback_and_counters(tmp_path):
    run, bundle, script, _ = _rebuilt_run(tmp_path, max_calls=5)
    service = CreativeStageCommandService(run)
    feedback = service.feedback("writer_script", "FIXTURE repair after budget exhaustion")
    state, clients = _resume(run, bundle, [{**script, "title": "unreachable"}], expect_failure=True)
    assert state["status"] == "needs_attention" and not clients.calls
    assert state["calls_started"] == 5 and state["max_calls"] == 5
    assert state["debug_feedback_status"] == "revision_required"
    assert not state["debug_feedback"][-1].get("resolved_by_output_sha256")
    assert _read_json(run / f"writer_script__before_feedback_{feedback['feedback_id']}.json")["output_sha256"] == feedback["output_sha256"]


@pytest.mark.parametrize("damage", ["prompt_sha256", "input_sha256", "output_sha256", "resolution"])
def test_resolved_upstream_tampering_with_pending_downstream_stops_before_call(tmp_path, damage):
    run, bundle, script, old_feedback = _rebuilt_run(tmp_path)
    CreativeStageCommandService(run).feedback("writer_script", "FIXTURE pending downstream")
    path = run / "director_brief.json"
    if damage == "resolution":
        row = next(row for row in _read_json(run / "state.json")["debug_feedback"]
                   if row["feedback_id"] == old_feedback["feedback_id"])
        path = run / row["resolution_receipt"]
        damage = "resolved_by_output_sha256"
    value = _read_json(path)
    value[damage] = "0" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    state, clients = _resume(run, bundle, [script], expect_failure=True)
    assert state["status"] == "needs_attention" and not clients.calls
    assert state["calls_started"] == 5
    assert state["debug_feedback_status"] == "revision_required"


def test_feedback_rejects_mismatched_current_receipt(tmp_path):
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    path = run / "writer_script.json"
    value = _read_json(path)
    value["output_sha256"] = "0" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    before = (run / "state.json").read_bytes()
    with pytest.raises(ValueError, match="current stage receipt verification failed"):
        CreativeStageCommandService(run).feedback("writer_script", "FIXTURE wrong current")
    assert (run / "state.json").read_bytes() == before


def test_single_step_counts_repaired_version_and_pauses_at_target(tmp_path):
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    CreativeStageCommandService(run).feedback("writer_script", "FIXTURE single step repair")
    script["title"] = "FIXTURE single step revised"
    state, clients = _resume(run, bundle, [script], single_step=True)
    assert state["status"] == "debug_breakpoint" and len(clients.calls) == 1
    assert state["debug_breakpoint"]["stage_id"] == "writer_script"
    assert state["debug_breakpoint"]["reason"] == "next_stage_completed"



def test_pending_late_stage_rebuilds_invalidated_intermediates_after_upstream_repair(tmp_path):
    run = tmp_path / "run"
    bundle = _bundle(tmp_path)
    initial = CreativeWorkflow(run, clients=FakeClients(_answers()),
                               stop_after_stage="writer_check__00").run(bundle)
    assert initial["status"] == "debug_breakpoint"
    service = CreativeStageCommandService(run)
    late_feedback = service.feedback("writer_check__00", "FIXTURE revise cross-check")
    service.feedback("director_brief", "FIXTURE revise upstream director")
    before = _read_json(run / "state.json")
    assert before["debug_stage_validity"]["writer_script"] == "invalidated"
    assert before["debug_stage_validity"]["director_shots"] == "invalidated"
    assert before["debug_stage_validity"]["writer_check__00"] == "needs_revision"
    brief = deepcopy(_answers()[1])
    brief["visual_strategy"] = "FIXTURE revised for late check"
    repaired, clients = _resume(run, bundle, [brief], "director_brief")
    assert repaired["status"] == "debug_breakpoint" and len(clients.calls) == 1
    script = deepcopy(_answers()[2])
    script["title"] = "FIXTURE intermediate script"
    shots = deepcopy(_answers()[3])
    shots["shots"][0]["camera"] = "FIXTURE intermediate close-up"
    check = deepcopy(_answers()[4])
    check["calibration_focus"] = ["FIXTURE revised cross-check"]
    state, clients = _resume(run, bundle, [script, shots, check], "writer_check__00")
    assert state["status"] == "debug_breakpoint" and len(clients.calls) == 3
    assert state["calls_started"] == initial["calls_started"] + 4
    assert state["debug_feedback_status"] == "resolved"
    assert _read_json(run / f"writer_check__00__before_feedback_{late_feedback['feedback_id']}.json")["output_sha256"] == late_feedback["output_sha256"]
    replay, clients = _resume(run, bundle, [], "writer_check__00")
    assert replay["calls_started"] == state["calls_started"] and not clients.calls


def test_legacy_graph_bootstrap_uses_first_traversal_after_revision_history(tmp_path):
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    path = run / "state.json"
    state = _read_json(path)
    state.pop("debug_stage_dependencies")
    path.write_text(json.dumps(state), encoding="utf-8")
    service = CreativeStageCommandService(run)
    service.feedback("writer_script", "FIXTURE legacy graph bootstrap")
    assert _read_json(path)["debug_stage_validity"]["director_brief"] == "current"
    script["title"] = "FIXTURE legacy repair"
    result, clients = _resume(run, bundle, [script])
    assert result["status"] == "debug_breakpoint" and len(clients.calls) == 1


def test_explicit_dependency_graph_does_not_invalidate_independent_stage(tmp_path):
    run, bundle, script, _ = _rebuilt_run(tmp_path)
    path = run / "state.json"
    state = _read_json(path)
    # An explicit graph with two independent branches; command-layer propagation
    # must respect the declared prerequisites, not the order of these records.
    state["debug_stage_dependencies"] = {
        "writer_analysis": [], "director_brief": ["writer_analysis"],
        "writer_script": ["writer_analysis"],
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    CreativeStageCommandService(run).feedback("director_brief", "FIXTURE independent branch")
    validity = _read_json(path)["debug_stage_validity"]
    assert validity["director_brief"] == "needs_revision"
    assert validity["writer_script"] == "current"
    assert validity["writer_analysis"] == "current"
