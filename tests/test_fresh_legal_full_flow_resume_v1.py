from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from scripts import run_fresh_legal_full_flow_resume_v1 as resume

control = resume.control


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(resume, "PROJECT", tmp_path)
    root = tmp_path / "data/production_trials/job/round_01"
    collection = root / "collection_live_01"
    helper = root / "verification_window_03"
    plan = root / "seed/PLAN.json"
    for path in (collection, helper, plan.parent, tmp_path / "data/trend_research_runs"):
        path.mkdir(parents=True, exist_ok=True)
    for path in resume._CODE:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# code source\n", encoding="utf-8")
    control.write(plan, {"core": "劳动争议"}, True)
    scope = {"grant_id": resume.original.GRANT_ID, "new_source_required": True,
        "old_512_director_count_preserved": 7,
        "native_limits": {"theme": 3, "plan": 3, "draft": 3, "new_director": 3},
        "max_local_content_revisions": 2, "single_format_recovery_per_phase": True,
        "max_total_tokens": None, "new_media_submissions": 0, "old_budget_reset": False,
        "publishing_authorized": False, "automatic_transport_retry": False}
    control.write(root / "USER_SCOPE.json", scope, True)
    control.write(root / "RESOURCE_CONFIG.json", {"core_plan_path": str(plan)}, True)
    files = {str(p): control.sha_file(p) for p in (root / "USER_SCOPE.json", root / "RESOURCE_CONFIG.json", plan)}
    base = {"schema": "fresh_legal_job_freeze/v1", "files": files,
        "inherited": {"calls_started": 520, "reported_tokens": 7964215,
            "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]},
        "models": {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-flash"}},
        "raw_parent_ordinals": [518, 519, 520], "new_generation_calls": 0}
    control.write(root / "JOB_FREEZE.json", base, True)
    control.write(root / "JOB_FREEZE_v2.json", base, True)
    control.write(root / "PRE_DISPATCH_FREEZE_REVISION.json", {"test": "loader is independently tested"}, True)
    monkeypatch.setattr(resume.original, "load_job_freeze", lambda _: deepcopy(base))
    control.write(root / "RUN_CLAIM.json", {"pid": 112,
        "job_freeze_sha256": control.sha_file(root / "JOB_FREEZE_v2.json"), "automatic_restart": False}, True)
    collection_claim = {"at_utc": "2026-10-12T10:00:00+00:00", "account_key": "account01",
        "plan_path": str(plan), "plan_sha256": control.sha_file(plan), "metadata_only": True,
        "no_model_calls": True, "no_media_calls": True, "automatic_retry": False}
    control.write(collection / "COLLECTION_CLAIM.json", collection_claim, True)
    control.write(collection / "LIVE_IDENTITY_CHECK.json", {"healthy": True, "account_key": "account01",
        "expected_public_id": "dy4qyzku18yu", "actual_public_id": "dy4qyzku18yu", "profile_version": 1}, True)
    payload = {"workflow_run_id": "research:" + "a" * 32, "account_uuid": "account:legal",
        "account_key": "account01", "profile_version": 1, "status": "failed", "stopped_reason": "human_required",
        "collection_run_id": "", "video_records": [], "finished_at": "2026-10-12T10:01:00+00:00"}
    payload.update({k: 0 for k in ("collected_observations", "unique_videos", "tag_relations", "tag_traffic_snapshots",
        "clusters", "briefs", "content_analyses", "opportunities")})
    authority = tmp_path / "data/trend_research_runs" / (payload["workflow_run_id"].replace(":", "_") + ".json")
    control.write(authority, payload, True)
    stdout = collection / "COLLECTION.stdout.log"
    stdout.write_text("Browser session stopped\n" + json.dumps(payload), encoding="utf-8")
    control.write(collection / "COLLECTION_RESULT.json", {"status": "stopped_exception", "exception_type": "JSONDecodeError"}, True)
    evidence = {str(p): control.sha_file(p) for p in (stdout, authority, plan,
        collection / "COLLECTION_CLAIM.json", collection / "LIVE_IDENTITY_CHECK.json")}
    rec_path = collection / "COLLECTION_RECONCILIATION.json"
    rec = {"status": "human_required", "observed_research_status": "failed", "reason": "human_required",
        "authoritative_full_result_equal": True, "account_key": "account01", "account_uuid": "account:legal",
        "profile_version": 1, "original_request_redispatched": False, "automatic_retry": False,
        "eligible_for_creative_source": False, "new_model_calls": 0, "new_media_calls": 0,
        "result": payload, "workflow_run_id": payload["workflow_run_id"], "evidence_sha256": evidence,
        "claim_sha256": control.sha_file(collection / "COLLECTION_CLAIM.json"), "plan_sha256": control.sha_file(plan)}
    control.write(rec_path, rec, True)
    control.write(helper / "HUMAN_VERIFICATION_BROWSER_STATE.json", {"status": "closed_after_operator_marker",
        "verification_passed": None, "new_collection_requests": 0, "new_model_calls": 0}, True)
    control.write(helper / "PROCESS.json", {"pid": 113}, True)
    control.write(helper / "HUMAN_VERIFICATION_BROWSER_CLOSE.json", {"save_and_close": True}, True)
    confirmation = {"schema": "fresh_legal_user_login_confirmation/v1", "user_statement": "已登录",
        "at_utc": "2026-10-12T10:02:00+00:00", "account_key": "account01", "expected_public_id": "dy4qyzku18yu",
        "profile_version": 1, "machine_identity_verified": False, "permits_one_post_verification_collection": True,
        "original_request_redispatch": False, "model_scope_changed": False, "media_allowed": False, "budget_reset": False,
        "original_reconciliation_path": str(rec_path), "original_reconciliation_sha256": control.sha_file(rec_path),
        "verification_window_root": str(helper)}
    control.write(root / resume.CONFIRMATION_NAME, confirmation, True)
    control.write(root / "STATE.json", {"status": "preparing_known_human_continuation"})
    return SimpleNamespace(root=root, base=base, rec_path=rec_path, confirmation=confirmation,
        collection=collection, helper=helper, authority=authority)


def test_additive_prepare_keeps_original_records_and_spend(prepared_inputs):
    p = prepared_inputs
    before = {f.name: f.read_bytes() for f in p.root.glob("*.json")}
    value = resume.prepare(p.root, process_alive=lambda _: False)
    assert value["inherited"] == p.base["inherited"]
    assert value["models"] == p.base["models"]
    assert value["new_generation_calls"] == 0 and value["new_media_submissions"] == 0
    assert value["budget_reset"] is False
    assert set(p.base["files"]).issubset(value["files"])
    for name, raw in before.items():
        assert (p.root / name).read_bytes() == raw
    assert not (p.root / resume.CLAIM_NAME).exists()
    assert resume.verify_resume_freeze(p.root) == value
    assert resume.prepare(p.root, process_alive=lambda _: False) == value


@pytest.mark.parametrize("field,value", [("budget_reset", True), ("user_statement", "继续"),
    ("machine_identity_verified", True), ("permits_one_post_verification_collection", False),
    ("media_allowed", True), ("expected_public_id", "other"), ("profile_version", 2),
    ("at_utc", "2026-10-12T09:00:00+00:00")])
def test_login_confirmation_cannot_widen_scope(prepared_inputs, field, value):
    p = prepared_inputs
    confirmation = deepcopy(p.confirmation)
    confirmation[field] = value
    control.write(p.root / resume.CONFIRMATION_NAME, confirmation)
    with pytest.raises(ValueError):
        resume.prepare(p.root, process_alive=lambda _: False)
    assert not (p.root / resume.FREEZE_NAME).exists()


@pytest.mark.parametrize("field,value", [("status", "result_unknown"), ("authoritative_full_result_equal", False),
    ("new_model_calls", 1), ("eligible_for_creative_source", True), ("automatic_retry", True)])
def test_unknown_or_nonzero_old_result_never_continues(prepared_inputs, field, value):
    p = prepared_inputs
    rec = control.read(p.rec_path)
    rec[field] = value
    control.write(p.rec_path, rec)
    confirmation = deepcopy(p.confirmation)
    confirmation["original_reconciliation_sha256"] = control.sha_file(p.rec_path)
    control.write(p.root / resume.CONFIRMATION_NAME, confirmation)
    with pytest.raises(ValueError):
        resume.prepare(p.root, process_alive=lambda _: False)


@pytest.mark.parametrize("pid", [112, 113])
def test_active_original_worker_or_helper_stops(prepared_inputs, pid):
    with pytest.raises(ValueError, match="active|release"):
        resume.prepare(prepared_inputs.root, process_alive=lambda found: found == pid)


@pytest.mark.parametrize("name", ["CALL_LEDGER.json", "TEXT_STATE.json", "TASKS.sqlite3", "source", "call_521_foo.json"])
def test_existing_runtime_evidence_is_never_reset(prepared_inputs, name):
    root = prepared_inputs.root
    (root / name).write_text("original evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="execution exists"):
        resume.prepare(root, process_alive=lambda _: False)
    assert (root / name).read_text(encoding="utf-8") == "original evidence"


def test_existing_collection_cannot_be_reissued(prepared_inputs):
    root = prepared_inputs.root
    (root / resume.COLLECTION_NAME).mkdir()
    with pytest.raises(ValueError, match="collection already exists"):
        resume.prepare(root, process_alive=lambda _: False)


@pytest.mark.parametrize("missing", ["scripts/run_fresh_legal_full_flow_resume_v1.py",
    "scripts/run_fresh_legal_collection_resume_v1.py", "src/content_factory/creative_collection_cli_result_v1.py",
    "confirmation", "reconciliation", "original_claim", "close_marker"])
def test_freeze_requires_all_added_evidence_members(prepared_inputs, missing):
    p = prepared_inputs
    value = resume.prepare(p.root, process_alive=lambda _: False)
    paths = {"confirmation": p.root / resume.CONFIRMATION_NAME, "reconciliation": p.rec_path,
        "original_claim": p.root / "RUN_CLAIM.json", "close_marker": p.helper / "HUMAN_VERIFICATION_BROWSER_CLOSE.json"}
    target = paths.get(missing, resume.PROJECT / missing)
    value["files"].pop(str(target.resolve()))
    control.write(p.root / resume.FREEZE_NAME, value)
    with pytest.raises(ValueError, match="additive freeze"):
        resume.verify_resume_freeze(p.root)


@pytest.mark.parametrize("field", ["login_confirmation_sha256", "original_reconciliation_sha256", "original_freeze_sha256"])
def test_freeze_metadata_hashes_cannot_disagree(prepared_inputs, field):
    root = prepared_inputs.root
    value = resume.prepare(root, process_alive=lambda _: False)
    value[field] = "f" * 64
    control.write(root / resume.FREEZE_NAME, value)
    with pytest.raises(ValueError, match="additive freeze"):
        resume.verify_resume_freeze(root)


def test_duplicate_claim_preserves_active_state_and_never_dispatches(prepared_inputs, monkeypatch):
    root = prepared_inputs.root
    resume.prepare(root, process_alive=lambda _: False)
    control.write(root / resume.CLAIM_NAME, {"pid": 999}, True)
    control.write(root / "STATE.json", {"status": "running", "pid": 999})
    monkeypatch.setattr(resume.subprocess, "run", lambda *a, **k: pytest.fail("no duplicate dispatch"))
    for operation in (resume.prepare, resume.run):
        with pytest.raises(resume.OriginalResumeExists):
            operation(root, process_alive=lambda _: False)
    assert control.read(root / "STATE.json") == {"status": "running", "pid": 999}


@pytest.mark.parametrize("status", ["human_required", "result_unknown", "stopped_exception"])
def test_collector_stop_does_not_start_text_or_models(prepared_inputs, monkeypatch, status):
    p = prepared_inputs
    resume.prepare(p.root, process_alive=lambda _: False)
    monkeypatch.setattr(resume.original, "wait_for_account_gate", lambda *a, **k: None)
    calls = []
    def fake_child(argv, **_):
        calls.append(argv)
        new = p.root / resume.COLLECTION_NAME
        new.mkdir()
        control.write(new / "COLLECTION_RESULT.json", {"status": status, "exit_code": 1}, True)
        return SimpleNamespace(stdout="saved", stderr="", returncode=1)
    monkeypatch.setattr(resume.subprocess, "run", fake_child)
    monkeypatch.setattr(resume, "run_text_and_production", lambda *a: pytest.fail("source gate stopped"))
    resume.run(p.root, process_alive=lambda _: False)
    assert len(calls) == 1 and "run_fresh_legal_collection_resume_v1.py" in calls[0][1]
    assert str(p.root / resume.COLLECTION_NAME) in calls[0]
    assert (p.root / "RUN_CLAIM.json").is_file()
    assert control.read(p.root / resume.CLAIM_NAME)["original_request_redispatch"] is False
    assert control.read(p.root / "STATE.json")["new_model_calls"] == 0
    assert not (p.root / "CALL_LEDGER.json").exists()
    with pytest.raises(resume.OriginalResumeExists):
        resume.run(p.root, process_alive=lambda _: False)
    assert len(calls) == 1


def test_completed_collector_passes_actual_new_directory_to_same_pipeline(prepared_inputs, monkeypatch):
    p = prepared_inputs
    resume.prepare(p.root, process_alive=lambda _: False)
    monkeypatch.setattr(resume.original, "wait_for_account_gate", lambda *a, **k: None)
    def fake_child(argv, **_):
        new = p.root / resume.COLLECTION_NAME
        new.mkdir()
        control.write(new / "COLLECTION_RESULT.json", {"status": "completed", "exit_code": 0}, True)
        return SimpleNamespace(stdout="completed", stderr="", returncode=0)
    monkeypatch.setattr(resume.subprocess, "run", fake_child)
    seen = []
    monkeypatch.setattr(resume, "run_text_and_production", lambda *args: seen.append(args))
    resume.run(p.root, process_alive=lambda _: False)
    assert len(seen) == 1 and seen[0][0] == p.root and seen[0][2] == p.root / resume.COLLECTION_NAME
    assert seen[0][1]["inherited"] == p.base["inherited"]
    assert resume.verify_resume_freeze(p.root)["models"] == p.base["models"]


def test_post_collection_unexpected_model_evidence_stops_before_source_or_pipeline(prepared_inputs):
    root = prepared_inputs.root
    (root / "TEXT_STATE.json").write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="execution exists"):
        resume.run_text_and_production(root, {}, root / resume.COLLECTION_NAME)


def test_actual_child_exit_must_match_saved_collection_exit(prepared_inputs, monkeypatch):
    p = prepared_inputs
    resume.prepare(p.root, process_alive=lambda _: False)
    monkeypatch.setattr(resume.original, "wait_for_account_gate", lambda *a, **k: None)
    def fake_child(*args, **kwargs):
        new = p.root / resume.COLLECTION_NAME
        new.mkdir()
        control.write(new / "COLLECTION_RESULT.json", {"status": "completed", "exit_code": 0}, True)
        return SimpleNamespace(stdout="", stderr="", returncode=1)
    monkeypatch.setattr(resume.subprocess, "run", fake_child)
    monkeypatch.setattr(resume, "run_text_and_production", lambda *a: pytest.fail("must stop before source"))
    with pytest.raises(ValueError, match="exit code differs"):
        resume.run(p.root, process_alive=lambda _: False)


def test_original_authoritative_result_must_remain_identical(prepared_inputs):
    p = prepared_inputs
    control.write(p.authority, {"status": "unknown"})
    with pytest.raises(ValueError, match="FROZEN_FILE_CHANGED"):
        resume.prepare(p.root, process_alive=lambda _: False)
