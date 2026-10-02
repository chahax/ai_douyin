"""Production state/command boundaries; fake providers and explicit fixture feedback."""

from copy import deepcopy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import pytest
from test_creative_workflow import FakeClients, _answers, _bundle
from src.content_factory.creative_workflow import CreativeWorkflow
from src.content_factory.creative_stage_debug import (
    CreativeStageCommandService,
    pending_must_fix_feedback,
)
from src.content_factory.creative_execution_control import command
from src.content_factory.creative_stage_contracts import read, persist, digest
from src.content_factory import creative_state_store as store


def initialized(tmp_path, stage="director_brief"):
    root = tmp_path / "run"
    bundle = _bundle(tmp_path)
    state = CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage=stage
    ).run(bundle)
    return root, bundle, state


def feedback(root, stage, message):
    service = CreativeStageCommandService(root)
    current = next(x for x in service.inspect()["stages"] if x["stage_id"] == stage)
    return service.feedback(
        stage,
        message,
        expected_input_sha256=current["input_sha256"],
        expected_output_sha256=current["output_sha256"],
    )


def blocked_downstream(root, state):
    clients = FakeClients([])
    w = CreativeWorkflow(root, clients=clients)
    w.state = deepcopy(state)
    if state.get("execution_control", {}).get("action") == "stop":
        from src.content_factory.creative_stage_debug import (
            CreativeStageBreakpointReached,
        )

        expected = CreativeStageBreakpointReached
        match = "breakpoint"
    else:
        expected = RuntimeError
        match = "must_fix"
    with pytest.raises(expected, match=match):
        w._stage("director_shots", "director", {}, lambda x: None)
    assert not clients.calls


def test_two_concurrent_feedbacks_during_call_preserve_history_budget_and_block_downstream(
    tmp_path,
):
    root, bundle, original = initialized(tmp_path)

    class Inflight(FakeClients):
        def call(self, *args, **kwargs):
            with ThreadPoolExecutor(max_workers=2) as pool:
                receipts = list(
                    pool.map(
                        lambda n: feedback(
                            root, "director_brief", "[fixture] concurrent " + str(n)
                        ),
                        range(2),
                    )
                )
            assert len({x["feedback_id"] for x in receipts}) == 2
            return super().call(*args, **kwargs)

    clients = Inflight([_answers()[2]])
    state = CreativeWorkflow(
        root, clients=clients, stop_after_stage="writer_script"
    ).run(bundle)
    assert len(pending_must_fix_feedback(state)) == 2 and state["calls_started"] == 3
    assert state["debug_stage_validity"]["director_brief"] == "needs_revision"
    assert state["debug_stage_validity"]["writer_script"] == "invalidated"
    assert read(root / "writer_script.json")["status"] == "validated"
    assert state["stages"][:2] == original["stages"] and len(clients.calls) == 1
    blocked_downstream(root, state)
    repaired = deepcopy(_answers()[1])
    repaired["summary"] = "[fixture] both issues repaired"
    repaired_state = CreativeWorkflow(
        root, clients=FakeClients([repaired]), stop_after_stage="director_brief"
    ).run(bundle)
    assert (
        not pending_must_fix_feedback(repaired_state)
        and repaired_state["calls_started"] == 4
    )
    revised_script = deepcopy(_answers()[2])
    revised_script["title"] = "[fixture] source-consistent script"
    rebuilt = CreativeWorkflow(
        root, clients=FakeClients([revised_script]), stop_after_stage="writer_script"
    ).run(bundle)
    assert rebuilt["calls_started"] == 5 and len(rebuilt["stages"]) == 5
    assert list(root.glob("writer_script__invalidated_*.json"))


@pytest.mark.parametrize(
    "actions",
    [("stop", "feedback"), ("feedback", "stop"), ("stop", "feedback", "resume")],
)
def test_stop_feedback_interleavings_keep_all_commands(tmp_path, actions):
    root, bundle, _ = initialized(tmp_path)

    class Inflight(FakeClients):
        def call(self, *args, **kwargs):
            for action in actions:
                if action == "feedback":
                    feedback(root, "director_brief", "[fixture] feedback with control")
                else:
                    command(root, action)
            return super().call(*args, **kwargs)

    state = CreativeWorkflow(
        root, clients=Inflight([_answers()[2]]), stop_after_stage="writer_script"
    ).run(bundle)
    assert len(pending_must_fix_feedback(state)) == 1 and state["calls_started"] == 3
    assert len(state["applied_state_command_ids"]) == len(actions)
    assert state["debug_breakpoint"]["reason"] == (
        "requested_stage" if actions[-1] == "resume" else "user_stop"
    )
    assert state["execution_control"]["action"] == (
        "resume" if actions[-1] == "resume" else "stop"
    )
    blocked_downstream(root, state)


def test_feedback_arriving_during_same_stage_repair_is_not_resolved_by_unconsumed_response(
    tmp_path,
):
    root, bundle, _ = initialized(tmp_path, "writer_analysis")
    first = feedback(root, "writer_analysis", "[fixture] first issue")
    late = {}

    class Inflight(FakeClients):
        def call(self, *args, **kwargs):
            late.update(
                feedback(
                    root, "writer_analysis", "[fixture] second issue during repair"
                )
            )
            return super().call(*args, **kwargs)

    revised = deepcopy(_answers()[0])
    revised["summary"] = "[fixture] first issue repaired"
    state = CreativeWorkflow(
        root, clients=Inflight([revised]), stop_after_stage="writer_analysis"
    ).run(bundle)
    pending = pending_must_fix_feedback(state)
    assert len(pending) == 1 and pending[0]["feedback_id"] == late["feedback_id"]
    assert pending[0]["output_sha256"] == first["output_sha256"]
    assert pending[0]["repair_base_output_sha256"] == digest(revised)
    assert state["debug_stage_validity"]["writer_analysis"] == "needs_revision"
    resolved = next(
        x for x in state["debug_feedback"] if x["feedback_id"] == first["feedback_id"]
    )
    assert resolved["resolved_by_output_sha256"] == digest(revised)
    second = deepcopy(revised)
    second["summary"] = "[fixture] both issues repaired"
    clients = FakeClients([second])
    final = CreativeWorkflow(
        root, clients=clients, stop_after_stage="writer_analysis"
    ).run(bundle)
    assert (
        len(clients.calls) == 1
        and final["calls_started"] == 3
        and len(final["stages"]) == 3
    )
    assert not pending_must_fix_feedback(final)
    cached = FakeClients([])
    replay = CreativeWorkflow(
        root, clients=cached, stop_after_stage="writer_analysis"
    ).run(bundle)
    assert not cached.calls and replay["calls_started"] == 3


@pytest.mark.parametrize("crash", ["before_command", "after_command", "after_state"])
def test_command_crash_recovery_is_idempotent_and_preserves_stale_runner_budget(
    tmp_path, monkeypatch, crash
):
    root, bundle, original = initialized(tmp_path)
    w = CreativeWorkflow(root, clients=FakeClients([]))
    w.state = deepcopy(original)

    def failed(*args, **kwargs):
        raise OSError("[fixture] crash")

    with monkeypatch.context() as patch:
        if crash == "before_command":
            patch.setattr(store, "append_command_locked", failed)
        elif crash == "after_command":
            patch.setattr(store, "commit_state_locked", failed)
        else:
            commit = store.commit_state_locked

            def after(*args, **kwargs):
                commit(*args, **kwargs)
                failed()

            patch.setattr(store, "commit_state_locked", after)
        with pytest.raises(OSError):
            feedback(root, "director_brief", "[fixture] crash-proof intent")
    w._save()
    w._save()
    state = read(root / "state.json")
    assert (
        len(pending_must_fix_feedback(state)) == 1
        and state["calls_started"] == original["calls_started"]
    )
    assert state["stages"] == original["stages"]
    retry = feedback(root, "director_brief", "[fixture] crash-proof intent")
    assert retry["feedback_id"] == state["debug_feedback"][0]["feedback_id"]
    assert len(list((root / ".creative_debug/state_commands").glob("*.json"))) == 1
    assert len(read(root / "state.json")["applied_state_command_ids"]) == 1
    blocked_downstream(root, state)


def test_resolution_receipt_before_state_commit_recovers_without_an_extra_call(
    tmp_path, monkeypatch
):
    root, bundle, _ = initialized(tmp_path, "writer_analysis")
    feedback(root, "writer_analysis", "[fixture] resolution crash")
    revised = deepcopy(_answers()[0])
    revised["summary"] = "[fixture] revised before crash"
    w = CreativeWorkflow(
        root, clients=FakeClients([revised]), stop_after_stage="writer_analysis"
    )
    real = w._save

    def crashed():
        if list(
            (root / ".creative_debug/feedback/writer_analysis").glob(
                "*.resolution.json"
            )
        ):
            raise OSError("[fixture] crash after resolution")
        real()

    monkeypatch.setattr(w, "_save", crashed)
    with pytest.raises(OSError):
        w.run(bundle)
    before = read(root / "state.json")["calls_started"]
    clients = FakeClients([])
    state = CreativeWorkflow(
        root, clients=clients, stop_after_stage="writer_analysis"
    ).run(bundle)
    assert not clients.calls and state["calls_started"] == before == 2
    assert not pending_must_fix_feedback(state) and len(state["stages"]) == 2
    assert (
        len(
            list(
                (root / ".creative_debug/feedback/writer_analysis").glob(
                    "*.resolution.json"
                )
            )
        )
        == 1
    )


def test_feedback_accepted_after_budget_reservation_blocks_provider_and_rebuilds_after_repair(
    tmp_path, monkeypatch
):
    root, bundle, _ = initialized(tmp_path)
    clients = FakeClients([_answers()[2]])
    w = CreativeWorkflow(root, clients=clients, stop_after_stage="writer_script")
    reserve = w._reserve_tokens

    def inject(*args, **kwargs):
        result = reserve(*args, **kwargs)
        feedback(root, "director_brief", "[fixture] accepted before actual dispatch")
        return result

    monkeypatch.setattr(w, "_reserve_tokens", inject)
    with pytest.raises(RuntimeError, match="must_fix"):
        w.run(bundle)
    assert not clients.calls
    state = read(root / "state.json")
    record = read(root / "writer_script.json")
    assert (
        record["status"] == "blocked_before_dispatch"
        and record["provider_dispatch_started"] is False
    )
    assert (
        state["calls_started"] == 3
        and state["debug_feedback_status"] == "revision_required"
    )
    revised = deepcopy(_answers()[1])
    revised["summary"] = "[fixture] repair before retry"
    CreativeWorkflow(
        root, clients=FakeClients([revised]), stop_after_stage="director_brief"
    ).run(bundle)
    final_clients = FakeClients([_answers()[2]])
    final = CreativeWorkflow(
        root, clients=final_clients, stop_after_stage="writer_script"
    ).run(bundle)
    assert len(final_clients.calls) == 1 and final["calls_started"] == 5
    assert list(root.glob("writer_script__blocked_*.json"))


def test_cross_process_feedback_and_kernel_lock_crash_do_not_need_manual_unlock(
    tmp_path,
):
    root, _, original = initialized(tmp_path)
    code = "from pathlib import Path; import sys; from src.content_factory.creative_stage_debug import CreativeStageCommandService; CreativeStageCommandService(Path(sys.argv[1])).feedback('director_brief',sys.argv[2])"
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda n: subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        code,
                        str(root),
                        "[fixture] process " + str(n),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                ),
                range(3),
            )
        )
    assert all(x.returncode == 0 for x in results), [x.stderr for x in results]
    state = read(root / "state.json")
    assert (
        len(pending_must_fix_feedback(state)) == 3
        and state["calls_started"] == original["calls_started"]
    )
    death = "from src.content_factory.creative_state_store import state_lock; import sys,os; lock=state_lock(sys.argv[1]); lock.__enter__(); os._exit(0)"
    assert (
        subprocess.run([sys.executable, "-c", death, str(root)], timeout=30).returncode
        == 0
    )
    feedback(root, "director_brief", "[fixture] command after owner crash")
    assert len(pending_must_fix_feedback(read(root / "state.json"))) == 4


def test_feedback_reopens_prior_handoff_without_reset_or_reading_stale_handoff(
    tmp_path,
):
    root, bundle, state = initialized(tmp_path)
    state["status"] = "media_handoff_pending_capability"
    persist(root / "state.json", state)
    feedback(root, "director_brief", "[fixture] revise prior handoff")
    current = read(root / "state.json")
    assert current["status"] == "debug_revision_required"
    assert current["status_before_debug_feedback"] == "media_handoff_pending_capability"
    revised = deepcopy(_answers()[1])
    revised["summary"] = "[fixture] revised handoff source"
    clients = FakeClients([revised])
    result = CreativeWorkflow(
        root, clients=clients, stop_after_stage="director_brief"
    ).run(bundle)
    assert len(clients.calls) == 1 and result["calls_started"] == 3
    assert not pending_must_fix_feedback(result)


def test_media_submit_blocks_pending_text_but_original_id_query_remains_available(
    tmp_path,
):
    from test_creative_remaining_refactor import media_fixture, FakeMedia
    from src.content_factory.creative_segment_execution import execute_segment
    import shutil

    text = tmp_path / "text"
    text.mkdir()
    source, _, _ = initialized(text)
    root, _, _, _, plan = media_fixture(tmp_path)
    # Copy a real validated fixture stage/index into the media source task so the
    # real feedback command performs its full artifact and dual-hash checks.
    shutil.copyfile(source / "state.json", root / "state.json")
    for stage in ("writer_analysis", "director_brief"):
        shutil.copyfile(source / (stage + ".json"), root / (stage + ".json"))
    shutil.copytree(
        source / ".creative_debug", root / ".creative_debug", dirs_exist_ok=True
    )
    client = FakeMedia()
    first = execute_segment(plan, root / "first", "submit", client)
    feedback(
        root, "director_brief", "[fixture] late text correction after media submission"
    )
    with pytest.raises(RuntimeError, match="must_fix"):
        execute_segment(plan, root / "another", "submit", client)
    queried = execute_segment(plan, root / "first", "query", client)
    assert len(client.created) == 1 and queried["task_id"] == first["task_id"]
    assert queried["content_status"] == "awaiting_human_review"


def test_noop_state_save_preserves_revision_and_all_existing_fields(tmp_path):
    root, _, state = initialized(tmp_path)
    before = (root / "state.json").read_bytes()
    w = CreativeWorkflow(root, clients=FakeClients([]))
    w.state = deepcopy(state)
    w._save()
    assert before == (root / "state.json").read_bytes() and w.state == state


def test_legacy_feedback_without_input_hash_recovers_its_original_identity(tmp_path):
    root, _, state = initialized(tmp_path)
    current = next(x for x in state["stages"] if x["name"] == "director_brief")
    payload = {
        "stage_id": "director_brief",
        "output_sha256": current["output_sha256"],
        "disposition": "must_fix",
        "message": "[fixture] legacy feedback",
        "evidence": [],
    }
    identifier = digest(payload)[:20]
    receipt = {
        **payload,
        "schema": "creative_stage_feedback/v1",
        "feedback_id": identifier,
        "recorded_at": "2026-10-01T01:00:00+00:00",
    }
    path = root / ".creative_debug/feedback/director_brief" / (identifier + ".json")
    persist(path, receipt, immutable=True)
    before = path.read_bytes()
    w = CreativeWorkflow(root, clients=FakeClients([]))
    w.state = deepcopy(state)
    w._save()
    assert path.read_bytes() == before and len(pending_must_fix_feedback(w.state)) == 1
    assert w.state["debug_feedback"][0]["feedback_id"] == identifier
    assert "input_sha256" not in w.state["debug_feedback"][0]
    blocked_downstream(root, w.state)


def test_assistant_review_sync_cannot_clear_pending_user_feedback(tmp_path):
    from src.content_factory.creative_calibration import (
        record_review,
        synchronize_review_state,
    )

    root = tmp_path / "run"
    bundle = _bundle(tmp_path)
    original = CreativeWorkflow(root, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "assistant_fixture.md"
    evidence.write_text(
        "[fixture assistant text review] "
        + ("人物、动机、因果和情绪反应的文本复核夹具。" * 12),
        encoding="utf-8",
    )
    record_review(
        root, category="campus_novel", outcome="passed", evidence_file=evidence
    )
    accepted = feedback(
        root, "director_brief", "[fixture] pending despite old text review"
    )
    before = (root / "state.json").read_bytes()
    with pytest.raises(ValueError, match="运行尚未完成文本交接"):
        synchronize_review_state(root)
    assert before == (root / "state.json").read_bytes()
    current = read(root / "state.json")
    assert current["status"] == "debug_revision_required"
    assert current["calls_started"] == original["calls_started"]
    assert (
        pending_must_fix_feedback(current)[0]["feedback_id"] == accepted["feedback_id"]
    )


def test_command_publication_interruption_recovers_complete_feedback_once(
    tmp_path, monkeypatch
):
    root, _, original = initialized(tmp_path)
    replace = Path.replace

    def interrupted(path, target):
        if Path(target).parent.name == "state_commands":
            raise OSError("[fixture] process interrupted before command publication")
        return replace(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            feedback(
                root,
                "director_brief",
                "[fixture] receipt survived publication interruption",
            )
    commands = root / ".creative_debug/state_commands"
    assert not list(commands.glob("*.json")) and list(commands.glob("*.tmp"))
    w = CreativeWorkflow(root, clients=FakeClients([]))
    w.state = deepcopy(original)
    w._save()
    w._save()
    assert len(list(commands.glob("*.json"))) == 1
    assert len(pending_must_fix_feedback(w.state)) == 1
    assert w.state["calls_started"] == original["calls_started"]
    assert w.state["stages"] == original["stages"]
    blocked_downstream(root, w.state)
