"""Offline contract and one-attempt tests; no platform/model traffic."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_fresh_legal_collection_resume_v1 as job


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / "project"
    monkeypatch.setattr(job, "PROJECT", project)
    root = project / "data/production_trials/fixture/collection_live_02"
    plan_path = project / "data/production_trials/fixture/LEGAL_CORE_PLAN.json"
    plan = {"schema": "legal_core_topic_plan/v1", "plan_id": "legal-core:fixture",
        "account_uuid": "account:fixture", "account_key": "account01", "profile_version": 1,
        "core_tag": "劳动争议", "related_tags": ["劳动仲裁"], "estimated_pages": 6}
    write(plan_path, plan)
    sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    claim = {"at_utc": "2026-10-12T14:00:00+00:00", "account_key": "account01",
        "plan_path": str(plan_path), "plan_sha256": sha, "metadata_only": True,
        "no_model_calls": True, "no_media_calls": True, "automatic_retry": False}
    identity = {"at_utc": "2026-10-12T14:00:05+00:00", "healthy": True, "status": "active",
        "account_key": "account01", "profile_version": 1,
        "expected_public_id": job.PUBLIC_ID, "actual_public_id": job.PUBLIC_ID}
    log = project / "data/trend_research_runs/research_{}.json".format("2" * 32)
    payload = {"workflow_run_id": "research:" + "2" * 32, "account_uuid": "account:fixture",
        "account_key": "account01", "profile_version": 1, "status": "awaiting_media_analysis",
        "started_at": "2026-10-12T14:00:10+00:00", "finished_at": "2026-10-12T14:00:20+00:00",
        "collection_run_id": "new_batch", **{key: 0 for key in job.COUNTERS},
        "collected_observations": 25, "unique_videos": 25, "tag_relations": 8,
        "stopped_reason": "incomplete_source_media_analysis", "warnings": ["来源音画未分析"],
        "stages": [{"stage": "trend_collection", "status": "succeeded", "message": "allowed"}],
        "log_path": str(log.relative_to(project)),
        "video_records": [{"video_id": str(index), "run_id": "new_batch"} for index in range(25)],
        "sample_gate": {"passed": True},
        "legal_core_plan": job._plan_binding(plan_path, plan, sha)}
    write(log, payload)
    return SimpleNamespace(project=project, root=root, plan_path=plan_path, plan=plan, sha=sha,
        claim=claim, identity=identity, payload=payload, log=log)


def validate(case, *, stdout=None):
    return job.validate_result(stdout=("Browser session stopped\n" + json.dumps(case.payload)) if stdout is None else stdout,
        native_result=case.payload, claim=case.claim, identity=case.identity,
        plan_path=case.plan_path, plan=case.plan, plan_sha=case.sha,
        expected_account_uuid="account:fixture", observed_at="2026-10-12T14:01:00+00:00")


def test_unique_terminal_json_with_plain_logs_and_exact_full_authority(case):
    before = {p: p.read_bytes() for p in case.project.rglob("*") if p.is_file()}
    proof = validate(case)
    assert proof["authoritative_full_result_equal"] is True
    assert proof["eligible_for_source_validation"] is True
    assert proof["known_research_result"] is True
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_completed_success_preserves_sample_contract(case):
    case.payload.update(status="completed", stopped_reason="")
    write(case.log, case.payload)
    assert validate(case)["eligible_for_source_validation"] is True


def test_known_human_result_is_accepted_evidence_but_never_source(case):
    case.payload.update(status="failed", stopped_reason="human_required", collection_run_id="",
        **{key: 0 for key in job.COUNTERS}, video_records=[], sample_gate={},
        stages=[{"stage": "trend_collection", "status": "failed", "message": "human_required"}])
    write(case.log, case.payload)
    proof = validate(case)
    assert proof["known_research_result"] is True and proof["eligible_for_source_validation"] is False


@pytest.mark.parametrize("key,value", [
    ("status", "result_unknown"), ("status", "partial"), ("status", "running"),
    ("profile_version", True), ("profile_version", 2), ("account_key", "account02"),
    ("account_uuid", "account:other"), ("workflow_run_id", "research:wrong"),
    ("started_at", "2026-10-11T14:00:10+00:00"), ("started_at", "2026-10-12T14:00:10"),
    ("finished_at", "2026-10-12T14:00:01+00:00"),
    ("unique_videos", True), ("unique_videos", -1), ("unique_videos", "25"),
    ("collection_run_id", ""), ("collection_run_id", None), ("sample_gate", {"passed": 1}),
    ("sample_gate", {}), ("sample_gate", []), ("video_records", [{"run_id": "old_batch"}]),
    ("stopped_reason", "human_required"), ("stopped_reason", ""),
    ("legal_core_plan", {}), ("log_path", "../outside.json"),
])
def test_bad_or_old_or_incomplete_result_never_source(case, key, value):
    case.payload[key] = value
    write(case.log, case.payload)
    with pytest.raises((job.ResultBindingError, ValueError)):
        validate(case)


@pytest.mark.parametrize("bad", ["", '{"half":', '{}\n{}', '[]\n{}',
    'log {"inline":1}\n{}', '{}\npost log', '{"duplicate":1,"duplicate":2}', '{"x":NaN}'])
def test_ambiguous_output_is_unknown_and_not_adopted(case, bad):
    with pytest.raises(ValueError):
        validate(case, stdout=bad)


@pytest.mark.parametrize("fault", ["claim_scope", "claim_plan_hash", "plan_hash", "identity", "identity_type",
    "plan_identity", "stdout_extra", "authority_extra", "different_workflow_path"])
def test_full_binding_not_just_selected_fields(case, fault):
    stdout = None
    if fault == "claim_scope":
        case.claim["no_media_calls"] = False
    elif fault == "claim_plan_hash":
        case.claim["plan_sha256"] = "0" * 64
    elif fault == "plan_hash":
        write(case.plan_path, {**case.plan, "extra": True})
    elif fault == "identity":
        case.identity["actual_public_id"] = "wrong"
    elif fault == "identity_type":
        case.identity["profile_version"] = True
    elif fault == "plan_identity":
        case.plan["account_uuid"] = "wrong"
    elif fault == "stdout_extra":
        stdout = json.dumps({**case.payload, "extra": 1})
    elif fault == "authority_extra":
        write(case.log, {**case.payload, "extra": 1})
    elif fault == "different_workflow_path":
        case.payload["log_path"] = str(case.log.parent / "research_{}.json".format("3" * 32))
    with pytest.raises((job.ResultBindingError, ValueError)):
        validate(case, stdout=stdout)


def setup_main(case, monkeypatch, *, healthy=True, outcome=None, problem=None):
    events = []
    clock = iter(["2026-10-12T14:00:00+00:00", "2026-10-12T14:00:05+00:00", "2026-10-12T14:01:00+00:00"])
    monkeypatch.setattr(job, "now_utc", lambda: next(clock))
    monkeypatch.setattr(job, "verify_continuation_parent", lambda root, plan: {"original_grant_id": "fixture-grant"})
    session = SimpleNamespace(stop=lambda: events.append("stop"))
    context = SimpleNamespace(account_key="account01", account_uuid="account:fixture",
        profile=SimpleNamespace(profile_version=1), binding=SimpleNamespace(public_uid=job.PUBLIC_ID),
        create_browser_session=lambda **kwargs: (events.append(("browser", kwargs)) or session))
    class Service:
        def resolve(self, account):
            assert account == "account01"
            events.append("resolve")
            return context
        @contextmanager
        def operation_lease(self, ctx, **kwargs):
            assert ctx is context and kwargs["lock_seconds"] == 4200
            assert kwargs["operation"] == "fresh_legal_resume_collection"
            events.append("lease")
            try:
                yield
            except Exception:
                events.append("lease_failure")
                raise
            else:
                events.append("lease_success")
        def verify_identity(self, ctx, *, session):
            assert ctx is context
            events.append("identity")
            return SimpleNamespace(healthy=healthy, status="active" if healthy else "login_expired",
                actual=SimpleNamespace(public_uid=job.PUBLIC_ID) if healthy else None)
    def request(plan, profile, **kwargs):
        assert kwargs == {"headless": False, "manual_verification_seconds": 600}
        return SimpleNamespace(headless=False)
    monkeypatch.setattr(job, "AccountRuntimeService", Service)
    monkeypatch.setattr(job, "request_from_legal_core_plan", request)
    monkeypatch.setattr(job, "estimate_douyin_planned_pages", lambda _: 6)
    class Workflow:
        def run(self, profile, provider, request, **kwargs):
            events.append("research")
            assert provider.session_factory(False) is session
            assert kwargs["max_content_candidates"] == 60
            assert kwargs["content_analysis_implementation"] == "metadata_heuristic"
            assert kwargs["resume_collection_run_id"] == ""
            assert kwargs["local_media_manifest"] is None and kwargs["run_local_toolchain"] is False
            if problem:
                raise problem
            native = deepcopy(outcome or case.payload)
            native.pop("legal_core_plan", None)
            write(case.log, native)
            session.stop()
            print("Browser session stopped")
            return SimpleNamespace(to_dict=lambda: native)
    monkeypatch.setattr(job, "AccountVideoResearchWorkflow", Workflow)
    return events, context


def main(case):
    return job.main([str(case.root), str(case.plan_path)])


def result(case):
    return json.loads((case.root / "COLLECTION_RESULT.json").read_text(encoding="utf-8"))


def test_visible_verified_browser_reused_and_metadata_only(case, monkeypatch):
    events, _ = setup_main(case, monkeypatch)
    assert main(case) == 1  # Exact native metadata-only waiting status, not false completed.
    proof = result(case)
    assert proof["status"] == "awaiting_media_analysis" and proof["authoritative_full_result_equal"]
    assert proof["new_model_calls"] == proof["new_media_calls"] == 0
    assert proof["automatic_retry"] is False
    assert events.count("research") == 1 and events.count("identity") == 1
    assert ("browser", {"headless": False}) in events and "lease_success" in events
    assert json.loads((case.root / "COLLECTION_CLAIM.json").read_text(encoding="utf-8"))["same_verified_browser_reused"]
    assert job.extract_terminal_research_json((case.root / "COLLECTION.stdout.log").read_text(encoding="utf-8")) == proof["result"]


def test_second_execution_never_resolves_identity_or_research_again(case, monkeypatch):
    events, _ = setup_main(case, monkeypatch)
    main(case)
    before = list(events)
    files = {p: p.read_bytes() for p in case.root.iterdir() if p.is_file()}
    with pytest.raises(FileExistsError):
        main(case)
    assert before == events
    assert all(p.read_bytes() == raw for p, raw in files.items())


def test_unhealthy_identity_never_collects_and_lease_records_failure(case, monkeypatch):
    events, _ = setup_main(case, monkeypatch, healthy=False)
    assert main(case) == 1
    assert "research" not in events and "lease_failure" in events and "lease_success" not in events
    assert result(case)["status"] == "human_required" and result(case)["collection_submitted"] is False


def test_exact_public_identity_even_healthy_flag_is_required(case, monkeypatch):
    events, ctx = setup_main(case, monkeypatch)
    ctx.binding.public_uid = "other"
    assert main(case) == 1
    assert "identity" not in events and "research" not in events
    assert result(case)["status"] == "human_required"


def test_failed_search_keeps_failure_history_and_full_result(case, monkeypatch):
    failed = deepcopy(case.payload)
    failed.update(status="failed", stopped_reason="human_required", collection_run_id="",
        **{key: 0 for key in job.COUNTERS}, video_records=[], sample_gate={},
        stages=[{"stage": "trend_collection", "status": "failed", "message": "human_required"}])
    events, _ = setup_main(case, monkeypatch, outcome=failed)
    assert main(case) == 1
    proof = result(case)
    assert proof["known_research_result"] is True and proof["eligible_for_source_validation"] is False
    assert proof["result"]["stopped_reason"] == "human_required"
    assert "lease_failure" in events and "lease_success" not in events


def test_timeout_after_dispatch_is_unknown_and_cannot_repeat(case, monkeypatch):
    events, _ = setup_main(case, monkeypatch, problem=TimeoutError("not logged private url"))
    assert main(case) == 1
    proof = result(case)
    assert proof["status"] == "result_unknown" and proof["exception_type"] == "TimeoutError"
    assert proof["collection_submitted"] is True and proof["automatic_retry"] is False
    assert "lease_failure" in events
    with pytest.raises(FileExistsError):
        main(case)
    assert events.count("research") == 1


def test_authoritative_finalization_cannot_rewrite_old_research(case):
    before = case.log.read_bytes()
    native = deepcopy(case.payload)
    native.pop("legal_core_plan")
    native["started_at"] = "2026-10-11T14:00:10+00:00"
    with pytest.raises(job.ResultBindingError, match="NEW_NATIVE"):
        job._bind_authoritative(native, plan_path=case.plan_path, plan=case.plan,
                                plan_sha=case.sha, identity=case.identity)
    assert case.log.read_bytes() == before


def test_existing_evidence_without_claim_is_not_overwritten(case, monkeypatch):
    events, _ = setup_main(case, monkeypatch)
    write(case.root / "COLLECTION_RESULT.json", {"status": "old"})
    with pytest.raises(FileExistsError):
        main(case)
    assert not events and result(case)["status"] == "old"


def test_lease_covers_global_challenge_wait_and_browser_stop_is_idempotent():
    assert job.LEASE_SECONDS > job.WAIT_SECONDS + 30 * 60
    from src.platform_adapter.browser_session import BrowserSession
    instance = object.__new__(BrowserSession)
    instance._proc = None
    instance.stop()
    instance.stop()


def test_whole_second_runner_begins_after_true_microsecond_identity(case):
    verified = datetime(2026, 10, 12, 14, 0, 10, 800000, tzinfo=timezone.utc)
    clock = [verified]
    slept = []
    def advance(seconds):
        slept.append(seconds)
        clock[0] += timedelta(seconds=seconds)
    job.wait_for_research_clock_boundary(verified.isoformat(), utc_now=lambda: clock[0], sleep=advance)
    assert slept == [0.2]
    assert clock[0].replace(microsecond=0) >= verified
    case.identity["at_utc"] = verified.isoformat()
    case.payload["started_at"] = clock[0].isoformat(timespec="seconds")
    write(case.log, case.payload)
    assert validate(case)["known_research_result"] is True
    assert case.identity["at_utc"] == verified.isoformat()


def test_clock_move_back_stops_before_submission():
    verified = "2026-10-12T14:00:10.800000+00:00"
    with pytest.raises(job.ResultBindingError, match="CLOCK_BOUNDARY"):
        job.wait_for_research_clock_boundary(verified,
            utc_now=lambda: datetime(2026, 10, 12, 14, 0, 8, tzinfo=timezone.utc),
            sleep=lambda _: pytest.fail("must not sleep through clock error"))


def parent_case(case):
    parent = case.root.parent
    freeze = {"collection_directory": "collection_live_02", "original_grant_id": "fixture-grant",
              "login_confirmation_sha256": "1" * 64}
    write(parent / "RESUME_FREEZE_01.json", freeze)
    claim = {"schema": "fresh_legal_known_human_resume_claim/v1", "pid": 123,
             "resume_freeze_sha256": hashlib.sha256((parent / "RESUME_FREEZE_01.json").read_bytes()).hexdigest(),
             "original_grant_id": "fixture-grant", "login_confirmation_sha256": "1" * 64,
             "automatic_restart": False, "budget_reset": False, "original_request_redispatch": False}
    write(parent / "RESUME_CLAIM_01.json", claim)
    write(parent / "RESOURCE_CONFIG.json", {"core_plan_path": str(case.plan_path)})
    return parent, freeze, claim


def test_exact_live_parent_claim_and_frozen_plan_required_before_browser(case):
    _, freeze, _ = parent_case(case)
    proof = job.verify_continuation_parent(case.root, case.plan_path,
        verifier=lambda parent: freeze, process_alive=lambda pid: pid == 123, parent_pid=123)
    assert proof["original_grant_id"] == "fixture-grant"


@pytest.mark.parametrize("fault", ["missing_claim", "dead_parent", "other_parent", "claim_schema", "claim_hash",
    "login_binding", "grant_binding", "automatic_restart", "budget_reset", "redispatch", "plan_binding", "other_root"])
def test_normal_cli_cannot_bypass_one_continuation_scope(case, fault):
    parent, freeze, claim = parent_case(case)
    root, plan_path, live_pid, parent_pid = case.root, case.plan_path, 123, 123
    if fault == "missing_claim":
        (parent / "RESUME_CLAIM_01.json").unlink()
    elif fault == "dead_parent":
        live_pid = 456
    elif fault == "other_parent":
        parent_pid = 456
    elif fault == "claim_schema":
        claim["schema"] = "different"
    elif fault == "claim_hash":
        claim["resume_freeze_sha256"] = "0" * 64
    elif fault == "login_binding":
        claim["login_confirmation_sha256"] = "0" * 64
    elif fault == "grant_binding":
        claim["original_grant_id"] = "different"
    elif fault == "automatic_restart":
        claim["automatic_restart"] = True
    elif fault == "budget_reset":
        claim["budget_reset"] = True
    elif fault == "redispatch":
        claim["original_request_redispatch"] = True
    elif fault == "plan_binding":
        plan_path = case.plan_path.parent / "OTHER_PLAN.json"
    elif fault == "other_root":
        root = root.parent / "collection_live_03"
    if fault != "missing_claim":
        write(parent / "RESUME_CLAIM_01.json", claim)
    with pytest.raises((job.ResultBindingError, FileNotFoundError)):
        job.verify_continuation_parent(root, plan_path, verifier=lambda _: freeze,
            process_alive=lambda pid: pid == live_pid, parent_pid=parent_pid)
