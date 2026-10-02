"""Offline execution acceptance. All media and human labels below are fixtures."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from test_creative_workflow import FakeClients, _answers, _bundle
from test_creative_seedance_segments import _story, _config
from test_media_user_review import _candidate
from test_publish_verification import Collection
from src.content_factory.creative_workflow import CreativeWorkflow
from src.content_factory.creative_workflow_contract import validate_director_brief
from src.content_factory.creative_stage_debug import CreativeStageCommandService
from src.content_factory.creative_stage_contracts import digest, read, persist
from src.content_factory.creative_execution_control import command
from src.content_factory.creative_media_workbench import (
    file_binding,
    register_preview,
    prepare_segment,
    inspect_media,
    media_feedback,
    approved_predecessor,
    approved_chain,
    assemble_approved,
)
from src.content_factory.creative_segment_execution import execute_segment
from src.content_factory.media_review_policy import (
    record_user_media_decision,
    validate_user_approved_candidate,
)
from src.content_factory.creative_seedance_segments import build_seedance_segment_plan
from src.content_factory.creative_media_capability import audit_creative_executor
from src.content_factory.creative_delivery import (
    prepare_delivery,
    publish_delivery,
    verify_delivery,
    collect_operations,
)
from src.content_factory.creative_quality_evidence import (
    collect_case,
    annotate_case,
    freeze_dataset,
    quality_report,
)


def test_stop_inflight_saves_result_and_resume_preserves_budget(tmp_path):
    root = tmp_path / "run"
    bundle = _bundle(tmp_path)

    class StopClients(FakeClients):
        def call(self, *args, **kwargs):
            result = super().call(*args, **kwargs)
            command(root, "stop")
            return result

    clients = StopClients(_answers())
    first = CreativeWorkflow(root, clients=clients).run(bundle)
    assert first["status"] == "debug_breakpoint" and first["calls_started"] == 1
    assert read(root / "writer_analysis.json")["status"] == "validated"
    paused = FakeClients([])
    assert CreativeWorkflow(root, clients=paused).run(bundle)["calls_started"] == 1
    assert not paused.calls
    command(root, "resume")
    second = CreativeWorkflow(
        root, clients=FakeClients(_answers()[1:]), max_new_stages=1
    ).run(bundle)
    assert (
        second["calls_started"] == 2
        and second["debug_breakpoint"]["stage_id"] == "director_brief"
    )
    assert len(list((root / ".creative_debug/control_history").glob("*.json"))) == 2


def test_actual_field_projection_reuses_unchanged_consumed_request(tmp_path):
    root = tmp_path / "run"
    bundle = _bundle(tmp_path)
    workflow = CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    )
    workflow.run(bundle)
    workflow.stop_after_stage = None
    selected = deepcopy(_answers()[0]["candidates"][0])
    payload = {"selected_candidate": selected}
    workflow._stage("director_brief", "director", payload, validate_director_brief)
    old_calls = workflow.state["calls_started"]
    old = read(root / "director_brief.json")
    CreativeStageCommandService(root).feedback(
        "writer_analysis", "[fixture] revise only the unconsumed summary"
    )
    analysis = deepcopy(_answers()[0])
    analysis["summary"] = "[fixture] changed background summary"
    repair = CreativeWorkflow(
        root, clients=FakeClients([analysis]), stop_after_stage="writer_analysis"
    )
    repair.run(bundle)
    repair.stop_after_stage = None
    repair._debug_new_stages = 0
    assert repair.state["debug_stage_validity"]["director_brief"] == "invalidated"
    repair._stage("director_brief", "director", payload, validate_director_brief)
    assert repair.state["calls_started"] == old_calls + 1
    assert read(root / "director_brief.json") == old
    assert repair._debug_new_stages == 0
    evidence = [
        read(p)
        for p in (root / ".creative_debug/compatibility/director_brief").glob("*.json")
    ]
    assert evidence[-1]["compatible"] is True
    inputs = [
        read(p) for p in (root / ".creative_debug/inputs/director_brief").glob("*.json")
    ]
    assert any(x["parents"][0]["output_field"] == ["candidates", 0] for x in inputs)
    repair.state["debug_stage_validity"]["director_brief"] = "invalidated"
    repair.clients = FakeClients([_answers()[1]])
    repair._stage(
        "director_brief",
        "director",
        {"selected_candidate": {**selected, "conflict": "[fixture] changed"}},
        validate_director_brief,
    )
    assert repair.state["calls_started"] == old_calls + 2
    assert (
        len([x for x in repair.state["stages"] if x["name"] == "director_brief"]) == 2
    )
    # Same validated output under a different consumed input has separate immutable identities.
    index = read(root / ".creative_debug/index.json")["stages"]["director_brief"]
    assert len(index) == 2 and index[0]["artifact"] != index[1]["artifact"]
    compared = CreativeStageCommandService(root).compare("director_brief")
    assert compared["output_identical"] is True and compared["diff"] == ""
    assert (
        compared["input_snapshots_available"] is True
        and "changed" in compared["input_diff"]
    )


def test_response_received_recovery_appends_latest_without_changing_history(tmp_path):
    root = tmp_path / "run"
    bundle = _bundle(tmp_path)
    first = CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    ).run(bundle)
    before = deepcopy(first["stages"][0])
    record = read(root / "writer_analysis.json")
    revised = deepcopy(_answers()[0])
    revised["summary"] = "[fixture] recovered new validated output"
    record.update(status="response_received", response_text=json.dumps(revised))
    persist(root / "writer_analysis.json", record)
    clients = FakeClients([])
    resumed = CreativeWorkflow(
        root, clients=clients, stop_after_stage="writer_analysis"
    ).run(bundle)
    assert resumed["stages"][0] == before and len(resumed["stages"]) == 2
    assert resumed["stages"][-1]["output_sha256"] == digest(revised)
    assert resumed["calls_started"] == 1 and not clients.calls


def test_displayed_stage_hash_must_match_before_feedback(tmp_path):
    root = tmp_path / "run"
    CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    ).run(_bundle(tmp_path))
    with pytest.raises(ValueError, match="displayed stage"):
        CreativeStageCommandService(root).feedback(
            "writer_analysis", "[fixture] stale display", expected_output_sha256="old"
        )
    assert read(root / "state.json").get("debug_feedback", []) == []


def media_fixture(tmp_path):
    root = tmp_path / "media_run"
    root.mkdir()
    script, shots = _story()
    capability = audit_creative_executor(shots, config=_config())
    for name, value in (
        ("SCREENPLAY.json", script),
        ("STORYBOARD.json", shots),
        ("MEDIA_CAPABILITY_AUDIT.json", capability),
    ):
        persist(root / name, value)
    persist(
        root / "state.json",
        {"stages": [], "logical_task_id": "fixture_story", "calls_started": 0},
    )
    compiled = root / "segments.json"
    persist(
        compiled,
        build_seedance_segment_plan(script, shots, capability, config=_config()),
    )
    register_preview(
        root,
        compiled,
        source_paths={
            "script": root / "SCREENPLAY.json",
            "storyboard": root / "STORYBOARD.json",
            "capability": root / "MEDIA_CAPABILITY_AUDIT.json",
        },
        text_gate="text_review_gate_satisfied",
    )
    frame = root / "opening.png"
    frame.write_bytes(b"fixture-opening")
    review = root / "opening.review.json"
    persist(
        review,
        {
            "decision": "passed",
            "first_frame_sha256": file_binding(frame)["sha256"],
            "checks": {"fixture_manual": True},
        },
    )
    plan = root / "SEG001.plan.json"
    prepare_segment(
        root, compiled, "SEG001", plan, first_frame=frame, first_frame_review=review
    )
    return root, compiled, frame, review, plan


class FakeMedia:
    def __init__(self, *, unknown=False, timeout=False):
        self.created = []
        self.queried = []
        self.unknown = unknown
        self.timeout = timeout

    def create_task(self, request):
        self.created.append(request)
        if self.unknown:
            raise TimeoutError("[fixture] unknown submission")
        return {"id": "fixture-task-" + str(len(self.created))}

    def wait_for_task(self, task_id, **kwargs):
        self.queried.append(task_id)
        if self.timeout:
            raise TimeoutError("[fixture] task pending")
        return {"id": task_id, "status": "succeeded"}

    def download_video(self, task, path):
        path.write_bytes(b"fixture-original-video-" + task["id"].encode())
        return path

    def download_last_frame(self, task, path):
        path.write_bytes(b"fixture-provider-tail-" + task["id"].encode())
        return path


def test_full_preview_segment_human_tail_cut_assembly_delivery_chain(tmp_path):
    root, compiled, frame, frame_review, plan = media_fixture(tmp_path)
    client = FakeMedia()
    preview = execute_segment(plan, root / "SEG001", "preview", client)
    first = execute_segment(plan, root / "SEG001", "submit", client)
    assert preview["request"] == first["request"] and len(client.created) == 1
    assert first["content_status"] == "awaiting_human_review"
    candidate = inspect_media(root)["current"][0]
    media_feedback(
        root,
        candidate["candidate_id"],
        "approved",
        "[fixture human approval]",
        video_sha256=first["video_sha256"],
    )
    first_review = root / "SEG001/receipt.human_review.json"
    second_plan = root / "SEG002.plan.json"
    prepare_segment(
        root, compiled, "SEG002", second_plan, predecessor_review=first_review
    )
    assert read(second_plan)["first_frame"]["path"] == first["last_frame"]
    second = execute_segment(second_plan, root / "SEG002", "submit", client)
    record_user_media_decision(
        root / "SEG002/receipt.json", "approved", "[fixture second approval]"
    )
    second_review = root / "SEG002/receipt.human_review.json"
    with pytest.raises(ValueError):
        approved_predecessor(["SEG001", "SEG002", "SEG003"], "SEG003", first_review)
    third_plan = root / "SEG003.plan.json"
    prepare_segment(
        root,
        compiled,
        "SEG003",
        third_plan,
        predecessor_review=second_review,
        first_frame=frame,
        first_frame_review=frame_review,
    )
    assert (
        read(third_plan)["opening_frame_source"] == "reviewed_new_camera_opening_frame"
    )
    execute_segment(third_plan, root / "SEG003", "submit", client)
    record_user_media_decision(
        root / "SEG003/receipt.json", "approved", "[fixture third approval]"
    )
    chain = approved_chain(
        ["SEG001", "SEG002", "SEG003"],
        [first_review, second_review, root / "SEG003/receipt.human_review.json"],
    )
    with pytest.raises(ValueError, match="assembly order"):
        approved_chain(
            ["SEG003", "SEG002", "SEG001"],
            [root / "SEG003/receipt.human_review.json", second_review, first_review],
        )
    chain_path = root / "assembly.chain.json"
    persist(chain_path, chain, immutable=True)
    invocations = []

    def concat_fixture(args, **kwargs):
        invocations.append(args)
        Path(args[-1]).write_bytes(b"fixture-full-film-output")

    assembled = assemble_approved(chain_path, root / "final", runner=concat_fixture)
    assert (
        assembled["content_status"] == "awaiting_human_review"
        and "-map" in invocations[0]
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare_delivery(
            root,
            root / "final/receipt.human_review.json",
            account_key="A",
            account_uuid="A",
            title="fixture",
        )
    record_user_media_decision(
        root / "final/receipt.json", "approved", "[fixture full film approval]"
    )
    final_review = root / "final/receipt.human_review.json"
    assert validate_user_approved_candidate(final_review)["raw_tail"] is None
    delivery = prepare_delivery(
        root,
        final_review,
        account_key="A",
        account_uuid="A",
        title="fixture",
        assembly_chain=chain,
    )
    assert delivery["delivery"]["description"].startswith("剧情虚构，非真实事件。")
    # Re-querying a saved candidate does not erase approval or create another task.
    after = execute_segment(plan, root / "SEG001", "query", client)
    assert after["content_status"] == "approved" and len(client.created) == 3
    assert second["content_status"] == "awaiting_human_review"


@pytest.mark.parametrize(
    "failure", ["unknown_submit", "known_id_timeout", "stale_source", "execution_lock"]
)
def test_media_faults_never_resubmit_unknown_or_known_ids(tmp_path, failure):
    root, compiled, frame, review, plan = media_fixture(tmp_path)
    out = root / "SEG001"
    client = FakeMedia(
        unknown=failure == "unknown_submit", timeout=failure == "known_id_timeout"
    )
    if failure == "execution_lock":
        out.mkdir()
        (out / ".execution.lock").write_text("[fixture retained crash lock]")
        with pytest.raises(FileExistsError):
            execute_segment(plan, out, "submit", client)
        assert not client.created
        return
    if failure in ("unknown_submit", "known_id_timeout"):
        with pytest.raises(TimeoutError):
            execute_segment(plan, out, "submit", client)
        client.timeout = False
        if failure == "unknown_submit":
            with pytest.raises(ValueError, match="without a task ID"):
                execute_segment(plan, out, "query", client)
        else:
            result = execute_segment(plan, out, "query", client)
            assert result["technical_status"] == "succeeded"
        with pytest.raises(ValueError, match="receipt exists"):
            execute_segment(plan, out, "submit", client)
    else:
        execute_segment(plan, out, "submit", client)
        (root / "SCREENPLAY.json").write_text("{}")
        # Existing provider task remains queryable; stale lineage cannot be approved.
        assert (
            execute_segment(plan, out, "query", client)["technical_status"]
            == "succeeded"
        )
        with pytest.raises(ValueError, match="lineage"):
            record_user_media_decision(
                out / "receipt.json", "approved", "[fixture invalid approval]"
            )
    assert len(client.created) == 1


def test_unknown_responsibility_records_feedback_without_regeneration(tmp_path):
    root, _, _, _, plan = media_fixture(tmp_path)
    client = FakeMedia()
    result = execute_segment(plan, root / "SEG001", "submit", client)
    candidate = inspect_media(root)["current"][0]
    rejected = media_feedback(
        root,
        candidate["candidate_id"],
        "rejected",
        "[fixture] unclear responsibility",
        video_sha256=result["video_sha256"],
        time_range=[1, 3],
    )
    assert (
        rejected["next_action"] == "needs_responsibility_evidence"
        and rejected["automatic_regeneration"] is False
    )
    assert len(client.created) == 1 and not read(root / "state.json").get(
        "debug_feedback"
    )
    with pytest.raises(ValueError):
        media_feedback(
            root, candidate["candidate_id"], "rejected", "[fixture]", video_sha256="old"
        )


def test_manual_decision_crash_recovery_reconciles_receipt(tmp_path):
    receipt, _, _ = _candidate(tmp_path)
    before = receipt.read_bytes()
    record_user_media_decision(receipt, "approved", "[fixture] explicit approval")
    receipt.write_bytes(
        before
    )  # Simulate crash after review saved, before source updated.
    record_user_media_decision(receipt, "approved", "[fixture] explicit approval")
    assert (
        validate_user_approved_candidate(
            receipt.with_name("receipt.human_review.json")
        )["decision"]
        == "approved"
    )


def browser_fixture(tmp_path, monkeypatch, *, post_verified=False):
    import src.platform_adapter.publish_workflow as module

    monkeypatch.setattr(
        module, "__file__", str(tmp_path / "src/platform_adapter/publish_workflow.py")
    )
    workflow = module.PublishWorkflow(
        SimpleNamespace(start=lambda: None, is_authenticated=lambda: True)
    )
    descriptions = []

    def declaration(**kwargs):
        Path(kwargs["evidence_path"]).write_bytes(
            b"fixture-browser-declaration-screenshot"
        )
        return {"verified": True, "screenshot": kwargs["evidence_path"]}

    def post(*args, **kwargs):
        Path(kwargs["evidence_path"]).write_bytes(b"fixture-browser-post-screenshot")
        return {"verified": post_verified, "screenshot": kwargs["evidence_path"]}

    page = SimpleNamespace(
        url="https://www.douyin.com/video/123",
        ai_content_declaration=declaration,
        locator=lambda selector: Collection(
            [SimpleNamespace(inner_text=lambda: descriptions[0])]
        ),
        goto=lambda *a, **k: None,
        wait_for_timeout=lambda ms: None,
        inspect_published_video=post,
    )
    workflow._open_upload_page = lambda: page
    for method in (
        "_upload_video_file",
        "_fill_title",
        "_set_visibility",
        "_click_publish",
    ):
        setattr(workflow, method, lambda *a, **k: None)
    workflow._fill_description = lambda page, text: descriptions.append(text)
    workflow._wait_for_upload_complete = lambda *a, **k: True
    workflow._wait_for_publish_result = lambda *a, **k: ("123", page.url)

    def publish(request):
        request.extra_metadata["platform_identity_key"] = "fixture:A"
        return workflow.publish(request)

    adapter = SimpleNamespace(
        runtime_context=SimpleNamespace(account_key="A", account_uuid="A"),
        publish_workflow=workflow,
        publish_video=publish,
        verify_published_video=lambda *a: {"verified": True},
    )
    return adapter


@pytest.mark.parametrize("post_verified", [False, True])
def test_delivery_uses_actual_browser_workflow_lock_and_independent_verification(
    tmp_path, monkeypatch, post_verified
):
    receipt, _, _ = _candidate(tmp_path, "final")
    record_user_media_decision(
        receipt, "approved", "[fixture full film human approval]"
    )
    prepared = prepare_delivery(
        tmp_path,
        receipt.with_name("final.human_review.json"),
        account_key="A",
        account_uuid="A",
        title="fixture",
    )
    adapter = browser_fixture(tmp_path, monkeypatch, post_verified=post_verified)
    result = publish_delivery(prepared["path"], adapter)
    assert result["status"] == (
        "published_verified" if post_verified else "awaiting_publish_verification"
    )
    assert result["evidence"]["ai_selected"] is True
    with pytest.raises(FileExistsError):
        publish_delivery(prepared["path"], adapter)
    if not post_verified:
        assert (
            verify_delivery(prepared["path"], adapter)["status"] == "published_verified"
        )
    video = SimpleNamespace(
        video_id="123", account_uuid="A", creator_metrics={"like_count": 7}
    )
    adapter.sync_videos = lambda **kwargs: SimpleNamespace(success=True, videos=[video])
    recorded = []
    monkeypatch.setattr(
        "src.services.content_performance.record_snapshot", lambda v: recorded.append(v)
    )
    feedback = collect_operations(prepared["path"], adapter)
    assert (
        feedback["metrics"]["like_count"] == 7
        and feedback["metrics"]["play_count"] is None
    )
    assert recorded == [video] and feedback["causal_quality_claim"] is False
    adapter.runtime_context.account_uuid = "other"
    with pytest.raises(ValueError, match="browser account"):
        verify_delivery(prepared["path"], adapter)


def test_quality_candidates_gold_holdout_and_actual_unknown_costs(tmp_path):
    root = tmp_path / "run"
    CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    ).run(_bundle(tmp_path))
    case = collect_case(
        root,
        "writer_analysis",
        category="action",
        source_family="fixture_family",
        independence_group="fixture_story",
    )
    path = root / ".creative_debug/quality/cases" / (case["case_id"] + ".json")
    annotation = {
        "case_id": case["case_id"],
        "source_sha256": case["source"]["sha256"],
        "decision_source": "explicit_human_gold",
        "approved_by": "fixture_human",
        "user_statement": "[fixture gold label]",
        "case_kind": "correct",
        "split": "holdout",
        "expected_issues": [],
    }
    with pytest.raises(ValueError, match="promoted to holdout"):
        annotate_case(path, annotation)
    annotation["split"] = "development"
    annotate_case(path, annotation)
    frozen = freeze_dataset(
        [path.with_name(path.stem + ".gold.json")], root / "fixture_dataset.json"
    )
    assert (
        frozen["readiness"]["approved_case_count"] == 1
        and frozen["readiness"]["qualified"] is False
    )
    report = quality_report(root, dataset_path=root / "fixture_dataset.json")
    assert report["evaluation"]["holdout_repeated_validation_passed"] is False
    assert (
        report["cost"]["model_cost"] is None
        and report["quality_improvement_verified"] is False
    )
    assert report["cost"]["human_active_minutes"] is None


def test_future_context_repair_versions_old_full_body(tmp_path):
    from src.content_factory.creative_segmented_director import _bound_future_context

    workflow = SimpleNamespace(run_dir=tmp_path, state={})
    original = {
        "beats": [
            {"id": "B01"},
            {"id": "B02", "events": [{"kind": "action", "text": "fixture old"}]},
        ]
    }
    first = _bound_future_context(workflow, "director_shots__beat_01", original, 0)
    changed = deepcopy(original)
    changed["beats"][1]["events"][0]["text"] = "fixture revised"
    with pytest.raises(Exception):
        _bound_future_context(workflow, "director_shots__beat_01", changed, 0)
    workflow.state["debug_stage_validity"] = {"director_shots__beat_01": "invalidated"}
    second = _bound_future_context(workflow, "director_shots__beat_01", changed, 0)
    assert first["upcoming_beats"] != second["upcoming_beats"]
    assert len(list(tmp_path.glob("*__superseded_*.json"))) == 1


@pytest.mark.parametrize("saved_status", ["validated", "response_received"])
def test_feedback_repair_crash_reuses_response_and_keeps_original_target(
    tmp_path, monkeypatch, saved_status
):
    root = tmp_path / "run"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    ).run(bundle)
    service = CreativeStageCommandService(root)
    feedback = service.feedback("writer_analysis", "[fixture] explicit repair")
    revised = deepcopy(_answers()[0])
    revised["summary"] = "[fixture] revised after interruption"
    repair = CreativeWorkflow(
        root, clients=FakeClients([revised]), stop_after_stage="writer_analysis"
    )

    def interrupted(*args, **kwargs):
        raise RuntimeError("[fixture] interruption before artifact finalization")

    monkeypatch.setattr(repair, "_finish_debug_stage", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        repair.run(bundle)
    cached = read(root / "writer_analysis.json")
    cached["status"] = saved_status
    persist(root / "writer_analysis.json", cached)
    if saved_status == "response_received":
        state = read(root / "state.json")
        state["stages"].pop()
        persist(root / "state.json", state)
    resume_clients = FakeClients([])
    result = CreativeWorkflow(
        root, clients=resume_clients, stop_after_stage="writer_analysis"
    ).run(bundle)
    assert result["calls_started"] == 2 and not resume_clients.calls
    assert result["debug_feedback"][0]["feedback_id"] == feedback["feedback_id"]
    assert result["debug_feedback"][0]["resolved_by_output_sha256"] == digest(revised)
    assert len(result["stages"]) == 2


def test_same_task_dispatch_lock_blocks_duplicate_budget_use(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / ".creative_execution.lock").write_text("[fixture active dispatcher]")
    clients = FakeClients(_answers())
    with pytest.raises(RuntimeError, match="执行锁"):
        CreativeWorkflow(root, clients=clients).run(_bundle(tmp_path))
    assert not clients.calls and not (root / "state.json").exists()


def test_timed_media_feedback_routes_to_exact_current_upstream(tmp_path):
    root = tmp_path / "run"
    CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    ).run(_bundle(tmp_path))
    candidate_receipt, _, _ = _candidate(root, "SEG001")
    from src.content_factory.creative_media_workbench import register_candidate

    candidate = register_candidate(root, candidate_receipt)
    stage = CreativeStageCommandService(root).inspect()["stages"][0]
    feedback = media_feedback(
        root,
        candidate["candidate_id"],
        "rejected",
        "[fixture] motivation mismatch",
        video_sha256=candidate["video"]["sha256"],
        time_range=[2, 4],
        responsible_stage="writer_analysis",
        stage_output_sha256=stage["output_sha256"],
        evidence=[{"user_reference": "candidates.0.conflict"}],
    )
    assert feedback["stage_feedback"]["output_sha256"] == stage["output_sha256"]
    state = read(root / "state.json")
    assert (
        state["debug_stage_validity"]["writer_analysis"] == "needs_revision"
        and state["calls_started"] == 1
    )
    with pytest.raises(ValueError, match="invalid media feedback time"):
        media_feedback(
            root,
            candidate["candidate_id"],
            "rejected",
            "[fixture]",
            video_sha256=candidate["video"]["sha256"],
            time_range=[0, float("inf")],
        )


def test_quality_holdout_freeze_refuses_source_family_leakage(tmp_path):
    root = tmp_path / "run"
    CreativeWorkflow(
        root, clients=FakeClients(_answers()), stop_after_stage="writer_analysis"
    ).run(_bundle(tmp_path))
    development = collect_case(
        root,
        "writer_analysis",
        category="action",
        source_family="same_fixture_story",
        independence_group="same_group",
    )
    holdout = collect_case(
        root,
        "writer_analysis",
        category="action",
        source_family="same_fixture_story",
        independence_group="same_group",
        split="holdout",
    )
    paths = []
    for case in (development, holdout):
        path = root / ".creative_debug/quality/cases" / (case["case_id"] + ".json")
        annotate_case(
            path,
            {
                "case_id": case["case_id"],
                "source_sha256": case["source"]["sha256"],
                "decision_source": "explicit_human_gold",
                "approved_by": "fixture_human",
                "user_statement": "[fixture gold]",
                "case_kind": "correct",
                "split": case["split"],
                "expected_issues": [],
            },
        )
        paths.append(path.with_name(path.stem + ".gold.json"))
    dataset = freeze_dataset(paths, root / "fixture_leak_dataset.json")
    assert "SOURCE_FAMILY_SPLIT_LEAKAGE" in dataset["readiness"]["failures"]
    assert dataset["readiness"]["approved_independent_count"] == 1


def test_workbench_cli_inspection_and_failure_have_durable_receipts(tmp_path, capsys):
    from scripts.creative_workbench import main

    root, _, _, _, plan = media_fixture(tmp_path)
    execute_segment(plan, root / "SEG001", "submit", FakeMedia())
    assert main([str(root), "inspect-media"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["current"][0]["content_status"] == "awaiting_human_review"
    assert (
        main(
            [
                str(root),
                "review-media",
                "--candidate-id",
                "invalid",
                "--decision",
                "approved",
                "--statement",
                "[fixture]",
                "--video-sha256",
                "bad",
            ]
        )
        == 2
    )
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "failed"
    commands = [read(p) for p in (root / ".creative_debug/commands").glob("*.json")]
    assert {x["status"] for x in commands} == {"failed", "completed"}


def test_focused_feedback_retires_old_review_and_reconstructs_exact_context(tmp_path):
    from test_creative_governed_protocol import workflow, review_fixture
    from src.content_factory.creative_review_packet import build_packet

    context, packet, raw = review_fixture()
    w, clients = workflow(tmp_path, [raw])
    key = "writer_check__state_plan_00"
    first = w._stage(key, "writer", context, lambda value: None)
    assert w._verified_review(key, first, context) is None
    previous_packet = read(tmp_path / (key + "__review_packet.json"))
    feedback = CreativeStageCommandService(tmp_path).feedback(
        key, "[fixture] recheck source evidence"
    )
    repaired_context = {
        **context,
        "debug_must_fix_feedback": [
            {
                "feedback_id": feedback["feedback_id"],
                "message": feedback["message"],
                "evidence": feedback.get("evidence", []),
                "previous_output_sha256": feedback["output_sha256"],
            }
        ],
    }
    next_raw = deepcopy(raw)
    next_raw["context_sha256"] = build_packet(repaired_context)["context_sha256"]
    clients.answers = iter([next_raw])
    w.state = read(tmp_path / "state.json")
    second = w._stage(key, "writer", context, lambda value: None)
    assert len(w.state["stages"]) == 2 and w.state["calls_started"] == 2
    assert w._verified_review(key, second, context) is None
    assert read(tmp_path / (key + "__review_packet.json")) != previous_packet
    assert (
        len(
            list(
                (tmp_path / ".creative_debug/retired" / key).glob(
                    "*__review_packet.json"
                )
            )
        )
        == 1
    )
    assert (
        w.state["debug_feedback_status"] == "resolved"
        and w.state["status"] == "script_review_pending"
    )


def test_changing_output_directory_cannot_resubmit_unknown_or_unreviewed_segment(
    tmp_path,
):
    root, _, _, _, plan = media_fixture(tmp_path)
    client = FakeMedia(unknown=True)
    with pytest.raises(TimeoutError):
        execute_segment(plan, root / "unknown-original", "submit", client)
    with pytest.raises(ValueError, match="unresolved"):
        execute_segment(plan, root / "renamed-output", "submit", client)
    assert len(client.created) == 1
    assert (
        read(root / "renamed-output/receipt.json")["status"] == "blocked_before_submit"
    )
    assert (
        len(
            list(
                (root / ".creative_debug/media/submissions").glob("*.reservation.json")
            )
        )
        == 1
    )


def test_same_script_media_failure_budget_is_preserved_before_paid_dispatch(tmp_path):
    root, _, _, _, plan = media_fixture(tmp_path)
    client = FakeMedia()
    state = read(root / "state.json")
    state["video_failure_limit"] = 1
    persist(root / "state.json", state)
    first = execute_segment(plan, root / "first", "submit", client)
    record_user_media_decision(
        root / "first/receipt.json", "rejected", "[fixture] reject first attempt"
    )
    revised = read(plan)
    revised["seed"] += 1
    second = root / "revised.plan.json"
    persist(second, revised, immutable=True)
    with pytest.raises(ValueError, match="failure budget exhausted"):
        execute_segment(second, root / "second", "submit", client)
    assert len(client.created) == 1 and first["technical_status"] == "succeeded"
    ledger = read(root / ".creative_debug/media/submissions/budget.json")
    assert ledger["failure_limit"] == 1 and ledger["budget_reset_supported"] is False

    assert ledger["confirmed_failed_current_script"] == 1
    assert read(root / "second/receipt.json")["task_created"] is False
