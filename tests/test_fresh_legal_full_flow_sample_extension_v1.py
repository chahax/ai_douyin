"""Offline full result, SQL, single-claim and additive-dispatch contracts."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sqlite3
import sys

import pytest

from scripts import run_fresh_legal_full_flow_sample_extension_v1 as job

REAL_PROJECT = Path(__file__).resolve().parents[1]
REAL_ROOT = REAL_PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01"
control = job.control


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("no network"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no network"))


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = project / "data/production_trials/fixture/round_01"
    root.mkdir(parents=True)
    for module in (job, job.resume, job.collector):
        monkeypatch.setattr(module, "PROJECT", project)
    # The established 1097-file verifier is tested independently; this fixture
    # supplies its immutable output while exercising all new qualification.
    old_file = root / "OLD_FROZEN_CODE.py"
    old_file.write_bytes(b"old frozen byte proof")
    base = {"files": {str(old_file): control.sha_file(old_file)},
        "login_confirmation_sha256": "1" * 64, "new_generation_calls": 0,
        "inherited": {"calls_started": 520, "reported_tokens": 7964215,
            "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]},
        "models": {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-flash"}},
        "raw_parent_ordinals": [70, 160]}
    def verify_base(_):
        job.original.verify_files(base["files"])
        return deepcopy(base)
    monkeypatch.setattr(job.local, "verify_local_recovery_freeze", verify_base)
    for name, pid in (("RUN_CLAIM.json", 101), (job.resume.CLAIM_NAME, 102), (job.local.CLAIM_NAME, 103)):
        write(root / name, {"pid": pid, "started_at_utc": "2026-10-12T14:39:59+00:00"})
    write(root / job.local.FREEZE_NAME, {"schema": "old_freeze_fixture", "inherited": base["inherited"]})
    process = {"exit_code": 1, "finished_at_utc": "2026-10-12T14:41:40.405639+00:00",
        "original_request_redispatch": False, "automatic_retry": False}
    write(root / "LOCAL_DISPATCH_COLLECTION_PROCESS_RESULT_01.json", process)
    original_resources = control.read(REAL_ROOT / "RESOURCE_CONFIG.json")
    old_plan = control.read(original_resources["core_plan_path"])
    old_plan_path = root / "ORIGINAL_PLAN.json"
    write(old_plan_path, old_plan)
    write(root / "RESOURCE_CONFIG.json", {"core_plan_path": str(old_plan_path)})
    new_plan = control.read(REAL_ROOT / job.PLAN_NAME)
    write(root / job.PLAN_NAME, new_plan)
    collection = root / job.resume.COLLECTION_NAME
    collection.mkdir()
    for name in job._COLLECTION_FILES:
        (collection / name).write_bytes((REAL_ROOT / job.resume.COLLECTION_NAME / name).read_bytes())
    claim = control.read(collection / "COLLECTION_CLAIM.json")
    claim.update(plan_path=str(old_plan_path), plan_sha256=control.sha_file(old_plan_path))
    write(collection / "COLLECTION_CLAIM.json", claim)
    wrapper = control.read(collection / "COLLECTION_RESULT.json")
    native = wrapper["result"]
    native["legal_core_plan"] = job.collector._plan_binding(old_plan_path, old_plan, claim["plan_sha256"])
    authority = project / native["log_path"]
    write(authority, native)
    wrapper.update(authoritative_result_sha256=control.sha_file(authority), plan_sha256=claim["plan_sha256"])
    write(collection / "COLLECTION_RESULT.json", wrapper)
    (collection / "COLLECTION.stdout.log").write_text(json.dumps(native, ensure_ascii=False), encoding="utf-8")
    rec = control.read(REAL_ROOT / job.RECONCILIATION_NAME)
    rec.update(authoritative_result_sha256=control.sha_file(authority), plan_sha256=claim["plan_sha256"],
        evidence_sha256={str(p): control.sha_file(p) for p in (authority, collection / "COLLECTION_RESULT.json",
            collection / "COLLECTION.stdout.log", root / "LOCAL_DISPATCH_COLLECTION_PROCESS_RESULT_01.json")})
    write(root / job.RECONCILIATION_NAME, rec)
    for name in job._CODE:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REAL_PROJECT / name).read_bytes())
    exe = project / ".venv/Scripts/python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fixture interpreter")
    symbols = {"allowed_python_executables": [str(exe)], "sample_extension_worker_script": str(project / job._CODE[0])}
    monkeypatch.setattr(job, "execution_resource_symbols", lambda: deepcopy(symbols))
    profile = new_plan["inputs"]["profile"]
    db = project / "data/douyin.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE douyin_accounts(account_uuid,account_key,status)")
        conn.execute("CREATE TABLE account_strategy_versions(account_uuid,profile_version,domain_strategy_id,strategy_version,profile_json,is_active)")
        conn.execute("CREATE TABLE account_runtime_bindings(account_uuid,account_key,platform,public_uid,status)")
        conn.execute("INSERT INTO douyin_accounts VALUES(?,?,?)", (profile["account_uuid"], "account01", "active"))
        conn.execute("INSERT INTO account_strategy_versions VALUES(?,?,?,?,?,1)", (profile["account_uuid"], 1,
            "legal_services", "v1", json.dumps(profile, ensure_ascii=False)))
        conn.execute("INSERT INTO account_runtime_bindings VALUES(?,?,?,?,?)", (profile["account_uuid"], "account01",
            "douyin", job.collector.PUBLIC_ID, "active"))
    trend_db = project / "data/trend_intelligence.db"
    observations = new_plan["inputs"]["observations"]
    scalar = [k for k in observations[0] if k not in {"item_id", "video_id", "url", "title", "author",
        "root_keywords", "hashtags", "relevance_terms"}]
    columns = scalar + [k + "_json" for k in ("root_keywords", "hashtags", "relevance_terms")]
    with sqlite3.connect(trend_db) as conn:
        conn.execute("CREATE TABLE trend_collection_runs(run_id,status,account_uuid,profile_version,domain_strategy_id,strategy_version)")
        conn.execute("INSERT INTO trend_collection_runs VALUES(?,?,?,?,?,?)", (native["collection_run_id"], "completed",
            profile["account_uuid"], 1, "legal_services", "v1"))
        conn.execute("CREATE TABLE trend_items(item_id PRIMARY KEY,video_id,url,title,author)")
        conn.execute("CREATE TABLE trend_observations(item_id," + ",".join(columns) + ")")
        for obs in observations:
            conn.execute("INSERT OR REPLACE INTO trend_items VALUES(?,?,?,?,?)", tuple(obs[k] for k in (
                "item_id", "video_id", "url", "title", "author")))
            values = [obs["item_id"]] + [obs[k] for k in scalar] + [json.dumps(obs[k], ensure_ascii=False) for k in (
                "root_keywords", "hashtags", "relevance_terms")]
            conn.execute("INSERT INTO trend_observations VALUES(" + ",".join("?" for _ in values) + ")", values)
    return SimpleNamespace(project=project, root=root, base=base, collection=collection, native=native,
        rec=rec, authority=authority, plan=new_plan, profile=profile, trend_db=trend_db, symbols=symbols)


def qualify(case):
    return job.validate_known_insufficient_stop(case.root, process_alive=lambda _: False)


def test_full_native_sql_preview_is_readonly_and_does_not_reset(case):
    before = {p: p.read_bytes() for p in case.project.rglob("*") if p.is_file()}
    result = job.preview(case.root, process_alive=lambda _: False)
    assert result["seed"]["estimated_pages"] == 21 and result["seed"]["seed_observations"] == 208
    assert result["policy"]["min_confirmed_likes_or_views"] == 1000000
    assert result["inherited"] == case.base["inherited"] and result["new_dispatches"] == 0
    assert result["creative_quality_passed"] is False
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not (case.root / job.FREEZE_NAME).exists() and not (case.root / job.CLAIM_NAME).exists()


@pytest.mark.parametrize("name", list(job.resume._GENERATED) + ["call_521_unknown.json"])
def test_any_existing_text_source_or_runtime_stops_before_claim(case, name):
    (case.root / name).write_text("old evidence", encoding="utf-8")
    for method in (job.preview, job.prepare, job.run):
        with pytest.raises(ValueError, match="execution exists"):
            method(case.root, process_alive=lambda _: False)
    assert not (case.root / job.CLAIM_NAME).exists() and not (case.root / job.COLLECTION_NAME).exists()


@pytest.mark.parametrize("pid", [101, 102, 103])
def test_any_prior_worker_active_prevents_new_coverage(case, pid):
    with pytest.raises(ValueError, match="worker still active"):
        job.prepare(case.root, process_alive=lambda p: p == pid)


def process_fixture(claim, *, created_delta=-.5, running=True):
    started = job.resume._time(claim["started_at_utc"]).timestamp()
    return SimpleNamespace(create_time=lambda: started + created_delta, is_running=lambda: running)


@pytest.mark.parametrize("created_delta,running,expected", [(-.5, True, True), (0, True, True),
    (-.5, False, False), (1, True, False)])
def test_old_worker_instance_liveness_is_distinct_from_reused_pid(created_delta, running, expected):
    claim = {"pid": 50968, "started_at_utc": "2026-10-12T14:39:59.224907+00:00"}
    result = job.previous_worker_instance_active(claim, process_factory=lambda _: process_fixture(claim,
        created_delta=created_delta, running=running), observed_at="2026-10-12T15:28:00+00:00")
    assert result is expected


def test_actual_observed_windows_reuse_time_is_new_instance():
    claim = {"pid": 50968, "started_at_utc": "2026-10-12T14:39:59.224907+00:00"}
    created = job.resume._time("2026-10-12T15:27:04.542802+00:00").timestamp()
    node = SimpleNamespace(create_time=lambda: created, is_running=lambda: True)
    assert job.previous_worker_instance_active(claim, process_factory=lambda _: node,
        observed_at="2026-10-12T15:28:00+00:00") is False


@pytest.mark.parametrize("fault", ["pid_bool", "pid_zero", "pid_missing", "pid_string", "time_missing",
    "time_naive", "time_bad", "time_future", "created_none", "created_bool", "created_nan",
    "created_future", "running_unknown", "access_denied", "create_access_denied"])
def test_unknown_process_identity_or_claim_time_never_proves_old_worker_stopped(fault):
    import psutil
    claim = {"pid": 123, "started_at_utc": "2026-10-12T14:39:59+00:00"}
    node = process_fixture(claim)
    if fault == "pid_bool": claim["pid"] = True
    elif fault == "pid_zero": claim["pid"] = 0
    elif fault == "pid_missing": claim.pop("pid")
    elif fault == "pid_string": claim["pid"] = "123"
    elif fault == "time_missing": claim.pop("started_at_utc")
    elif fault == "time_naive": claim["started_at_utc"] = "2026-10-12T14:39:59"
    elif fault == "time_bad": claim["started_at_utc"] = "bad"
    elif fault == "time_future": claim["started_at_utc"] = "2026-10-12T16:00:00+00:00"
    elif fault == "created_none": node.create_time = lambda: None
    elif fault == "created_bool": node.create_time = lambda: True
    elif fault == "created_nan": node.create_time = lambda: float("nan")
    elif fault == "created_future": node.create_time = lambda: job.resume._time("2026-10-12T16:00:00+00:00").timestamp()
    elif fault == "running_unknown": node.is_running = lambda: None
    elif fault == "create_access_denied":
        def denied(): raise psutil.AccessDenied(123)
        node.create_time = denied
    def factory(_):
        if fault == "access_denied": raise psutil.AccessDenied(123)
        return node
    with pytest.raises(ValueError): job.previous_worker_instance_active(claim, process_factory=factory,
        observed_at="2026-10-12T15:28:00+00:00")


def test_absent_old_process_is_stopped_without_signal():
    import psutil
    claim = {"pid": 123, "started_at_utc": "2026-10-12T14:39:59+00:00"}
    def absent(_): raise psutil.NoSuchProcess(123)
    assert job.previous_worker_instance_active(claim, process_factory=absent,
        observed_at="2026-10-12T15:28:00+00:00") is False


def test_new_instances_allow_preparation_but_old_instance_still_blocks(case):
    def new_factory(pid):
        claim = {"started_at_utc": "2026-10-12T14:39:59+00:00"}
        return process_fixture(claim, created_delta=60)
    value = job.preview(case.root, process_factory=new_factory)
    assert value["status"] == "sample_extension_eligible" and value["new_dispatches"] == 0
    def mixed_factory(pid):
        claim = {"started_at_utc": "2026-10-12T14:39:59+00:00"}
        return process_fixture(claim, created_delta=-.5 if pid == 103 else 60)
    with pytest.raises(ValueError, match="worker still active"):
        job.prepare(case.root, process_factory=mixed_factory)
    assert not (case.root / job.FREEZE_NAME).exists() and not (case.root / job.CLAIM_NAME).exists()


@pytest.mark.parametrize("field,value", [("result_unknown", True), ("old_budget_reset", True),
    ("new_model_calls", 1), ("new_media_calls", True), ("actual_console_encoding", "utf-8"),
    ("identity_verified", False), ("known_research_result", False), ("status", "running")])
def test_reconciliation_cannot_turn_unknown_or_consumed_result_into_scope(case, field, value):
    rec = deepcopy(case.rec)
    rec[field] = value
    write(case.root / job.RECONCILIATION_NAME, rec)
    with pytest.raises(ValueError): qualify(case)


@pytest.mark.parametrize("field,value", [("status", "result_unknown"), ("exit_code", True),
    ("authoritative_full_result_equal", False), ("new_model_calls", 1), ("new_media_calls", 1)])
def test_wrapper_changes_rejected_without_new_browser(case, field, value):
    path = case.collection / "COLLECTION_RESULT.json"
    wrapped = control.read(path)
    wrapped[field] = value
    write(path, wrapped)
    with pytest.raises(ValueError): qualify(case)


def test_actual_sql_seed_mismatch_rejected_despite_self_consistent_plan(case):
    with sqlite3.connect(case.trend_db) as conn:
        conn.execute("UPDATE trend_items SET title='different actual SQL'")
    with pytest.raises(ValueError, match="actual same-batch SQL"):
        job.prepare(case.root, process_alive=lambda _: False)


def test_sql_batch_identity_changed_stops_seed(case):
    with sqlite3.connect(case.trend_db) as conn:
        conn.execute("UPDATE trend_collection_runs SET account_uuid='other'")
    with pytest.raises(ValueError, match="same-account SQL"):
        qualify(case)


def test_prepare_and_verifier_keep_all_old_proof_and_spend(case):
    before = {p: p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    freeze = job.prepare(case.root, process_alive=lambda _: False)
    assert freeze["inherited"] == case.base["inherited"] and freeze["models"] == case.base["models"]
    assert freeze["policy"]["max_content_candidates"] == 200 and freeze["budget_reset"] is False
    assert job.verify_sample_extension_freeze(case.root) == freeze
    assert job.prepare(case.root, process_alive=lambda _: False) == freeze
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not (case.root / job.CLAIM_NAME).exists()


@pytest.mark.parametrize("fault", ["missing_member", "policy_gate", "policy_typed", "old_spend", "new_model",
    "seed", "interpreter", "new_code", "old_code", "reconciliation"])
def test_additive_freeze_cannot_expand_scope_or_hide_changed_resources(case, fault):
    freeze = job.prepare(case.root, process_alive=lambda _: False)
    if fault == "missing_member": freeze["files"].pop(str(case.root / job.PLAN_NAME))
    elif fault == "policy_gate": freeze["policy"]["min_confirmed_likes_or_views"] = 400000
    elif fault == "policy_typed": freeze["policy"]["max_additional_batches"] = True
    elif fault == "old_spend": freeze["inherited"]["reported_tokens"] = 0
    elif fault == "new_model": freeze["models"]["writer"]["model"] = "other"
    elif fault == "seed": freeze["seed"]["estimated_pages"] = 30
    elif fault == "interpreter": Path(case.symbols["allowed_python_executables"][0]).write_bytes(b"changed")
    elif fault == "new_code": (case.project / job._CODE[0]).write_bytes(b"changed")
    elif fault == "old_code": (case.root / "OLD_FROZEN_CODE.py").write_bytes(b"changed")
    elif fault == "reconciliation": write(case.root / job.RECONCILIATION_NAME, {"status": "passed"})
    write(case.root / job.FREEZE_NAME, freeze)
    with pytest.raises((ValueError, RuntimeError)):
        job.verify_sample_extension_freeze(case.root)


def make_claim(case, freeze, pid=None):
    write(case.root / job.CLAIM_NAME, {"schema": "fresh_legal_sample_extension_claim/v1", "started_at_utc": control.now(),
        "pid": os.getpid() if pid is None else pid, "sample_extension_freeze_sha256": control.sha_file(case.root / job.FREEZE_NAME),
        "original_local_claim_sha256": freeze["original_local_claim_sha256"], "original_grant_id": job.original.GRANT_ID,
        "reconciliation_sha256": freeze["reconciliation_sha256"], "login_confirmation_sha256": freeze["login_confirmation_sha256"],
        "collection_directory": str(case.root / job.COLLECTION_NAME), "plan_sha256": freeze["seed"]["plan_sha256"],
        "original_request_redispatch": False, "automatic_restart": False, "budget_reset": False, "new_source_coverage_only": True})


def test_duplicate_claim_keeps_state_and_never_dispatches(case, monkeypatch):
    freeze = job.prepare(case.root, process_alive=lambda _: False)
    make_claim(case, freeze)
    write(case.root / "STATE.json", {"status": "running"})
    monkeypatch.setattr(job, "collect_once", lambda *a: pytest.fail("duplicate dispatch"))
    for method in (job.preview, job.prepare, job.run):
        with pytest.raises(job.SampleExtensionExists): method(case.root, process_alive=lambda _: False)
    assert control.read(case.root / "STATE.json") == {"status": "running"}


@pytest.mark.parametrize("fault", ["pid", "entry", "interpreter", "dead", "reused", "old_instance", "c_argument", "later_argument"])
def test_current_worker_pid_entry_and_process_instance_are_required(case, fault, monkeypatch):
    freeze = job.prepare(case.root, process_alive=lambda _: False)
    make_claim(case, freeze)
    claim = control.read(case.root / job.CLAIM_NAME)
    exe = Path(sys._base_executable).resolve()
    symbols = {"allowed_python_executables": [str(exe)], "sample_extension_worker_script": str(case.project / job._CODE[0])}
    freeze["execution_resource_symbols"] = symbols
    node = SimpleNamespace(is_running=lambda: True, exe=lambda: str(exe),
        create_time=lambda: job.resume._time(claim["started_at_utc"]).timestamp() - .5,
        cmdline=lambda: [str(exe), str(case.project / job._CODE[0]), "run"])
    if fault == "pid": claim["pid"] += 1; write(case.root / job.CLAIM_NAME, claim)
    elif fault == "entry": node.cmdline = lambda: [str(exe), "other.py"]
    elif fault == "interpreter": node.exe = lambda: str(case.project / "unfrozen.exe")
    elif fault == "dead": node.is_running = lambda: False
    elif fault == "reused": node.create_time = lambda: job.resume._time(claim["started_at_utc"]).timestamp() + .5
    elif fault == "old_instance": node.create_time = lambda: job.resume._time(claim["started_at_utc"]).timestamp() - 301
    elif fault == "c_argument": node.cmdline = lambda: [str(exe), "-c", "print('other')", str(case.project / job._CODE[0])]
    elif fault == "later_argument": node.cmdline = lambda: [str(exe), "other.py", str(case.project / job._CODE[0])]
    with pytest.raises(ValueError): job.verify_current_worker(case.root, freeze, process_factory=lambda _: node)


def test_runtime_guard_checks_old_new_freezes_and_current_worker(case, monkeypatch):
    seen = []
    monkeypatch.setattr(job, "verify_sample_extension_freeze", lambda root: seen.append("newfreeze") or {})
    monkeypatch.setattr(job, "verify_current_worker", lambda root, freeze: seen.append("worker"))
    runtime = job.SampleExtensionRuntime(case.project, case.root, [], case.base["inherited"], case.base["models"],
        inherited_guard=lambda: seen.append("oldfreeze"))
    runtime.inherited_guard()
    assert seen == ["oldfreeze", "newfreeze", "worker"]


def test_pythonw_absent_stdout_does_not_touch_business_state(tmp_path, monkeypatch):
    before = {"status": "known_collection_stopped", "known_collection_result": True}
    write(tmp_path / "STATE.json", before)
    monkeypatch.setattr(job.sys, "stdout", None)
    assert job.emit_optional(before, diagnostic_path=tmp_path / "diagnostic.json") is False
    assert control.read(tmp_path / "STATE.json") == before
    assert not (tmp_path / "diagnostic.json").exists()


def test_display_error_keeps_business_terminal_and_saves_diagnostic(tmp_path, monkeypatch):
    before = {"status": "known_collection_stopped", "known_collection_result": True}
    write(tmp_path / "STATE.json", before)
    def fail(*a): raise BrokenPipeError("display closed")
    monkeypatch.setattr(job.sys, "stdout", SimpleNamespace(write=fail, flush=lambda: None))
    assert job.emit_optional(before, diagnostic_path=tmp_path / "diagnostic.json") is False
    assert control.read(tmp_path / "STATE.json") == before
    diag = control.read(tmp_path / "diagnostic.json")
    assert diag["exception_type"] == "BrokenPipeError" and diag["business_state_modified"] is False


def fake_collection(case, monkeypatch, *, status="blocked", problem=None, close_problem=False, lease_problem=False, insert_execution=False):
    freeze = job.prepare(case.root, process_alive=lambda _: False)
    make_claim(case, freeze)
    monkeypatch.setattr(job, "verify_current_worker", lambda *a: {"pid": os.getpid(), "same_worker_process": True})
    monkeypatch.setattr(job.collector, "wait_for_research_clock_boundary", lambda *a: None)
    events = []
    session = SimpleNamespace()
    def stop():
        events.append("stop")
        if close_problem: raise OSError("close error")
    session.stop = stop
    profile = job._profile(case.root)
    context = SimpleNamespace(account_key="account01", account_uuid=profile.account_uuid, profile=profile,
        binding=SimpleNamespace(public_uid=job.collector.PUBLIC_ID),
        create_browser_session=lambda headless: events.append(("browser", headless)) or session)
    @contextmanager
    def lease(*a, **kwargs):
        events.append(("lease", kwargs["lock_seconds"]))
        try:
            yield
            if lease_problem: raise OSError("lease release")
        except Exception:
            events.append("lease_failed")
            if lease_problem: raise OSError("lease release")
            raise
    def identify(*a, **kw):
        events.append("identity")
        if insert_execution: (case.root / "TEXT_STATE.json").write_bytes(b"in-flight text")
        return SimpleNamespace(healthy=True, status="active", actual=SimpleNamespace(public_uid=job.collector.PUBLIC_ID))
    service = SimpleNamespace(resolve=lambda _: context, operation_lease=lease, verify_identity=identify)
    monkeypatch.setattr(job.collector, "AccountRuntimeService", lambda: service)
    monkeypatch.setattr(job.collector, "DouyinWebTrendProvider", lambda session_factory: (
        events.append(("provider_same_session", session_factory(False) is session)) or SimpleNamespace()))
    def research(*args, **kwargs):
        events.append(("research", kwargs))
        if problem: raise problem
        now = datetime.now(timezone.utc).isoformat()
        native = deepcopy(case.native)
        native.pop("legal_core_plan")
        native.update(workflow_run_id="research:" + "a" * 32, collection_run_id="new_only_batch",
            started_at=now, finished_at=now, status=status,
            log_path="data/trend_research_runs/research_" + "a" * 32 + ".json")
        for row in native["video_records"]: row["run_id"] = "new_only_batch"
        native["sample_gate"]["run_id"] = "new_only_batch"
        if status == "completed":
            native.update(stopped_reason="", sample_gate={"passed": True})
        write(case.project / native["log_path"], native)
        return SimpleNamespace(to_dict=lambda: native)
    monkeypatch.setattr(job.collector, "AccountVideoResearchWorkflow", lambda: SimpleNamespace(run=research))
    return freeze, events


def test_direct_collection_reuses_visible_identity_session_and_keeps_known_insufficient(case, monkeypatch):
    freeze, events = fake_collection(case, monkeypatch)
    collection, exit_code = job.collect_once(case.root, freeze)
    wrapped = control.read(collection / "COLLECTION_RESULT.json")
    assert wrapped["status"] == "blocked" and wrapped["known_research_result"] is True and exit_code == 1
    assert "lease_failed" in events and ("browser", False) in events and ("provider_same_session", True) in events
    arguments = next(event[1] for event in events if isinstance(event, tuple) and event[0] == "research")
    assert arguments["max_content_candidates"] == 200 and arguments["local_media_manifest"] is None
    assert arguments["run_local_toolchain"] is False and arguments["resume_collection_run_id"] == ""
    assert "Browser" not in (collection / "COLLECTION.stdout.log").read_text(encoding="utf-8")
    with pytest.raises(job.SampleExtensionExists): job.collect_once(case.root, freeze)
    assert sum(isinstance(e, tuple) and e[0] == "research" for e in events) == 1


def test_timeout_after_submission_stops_unknown_without_repeat(case, monkeypatch):
    freeze, events = fake_collection(case, monkeypatch, problem=TimeoutError("no result"))
    collection, _ = job.collect_once(case.root, freeze)
    wrapped = control.read(collection / "COLLECTION_RESULT.json")
    assert wrapped["status"] == "result_unknown" and wrapped["collection_submitted"] is True
    assert wrapped["automatic_retry"] is False
    with pytest.raises(job.SampleExtensionExists): job.collect_once(case.root, freeze)
    assert sum(isinstance(e, tuple) and e[0] == "research" for e in events) == 1


@pytest.mark.parametrize("insert_at_identity", [True, False])
def test_execution_appearing_after_wait_is_rechecked_before_browser_or_search(case, monkeypatch, insert_at_identity):
    freeze, events = fake_collection(case, monkeypatch, insert_execution=insert_at_identity)
    if not insert_at_identity: (case.root / "CALL_LEDGER.json").write_bytes(b"started meanwhile")
    if insert_at_identity:
        collection, _ = job.collect_once(case.root, freeze)
        assert control.read(collection / "COLLECTION_RESULT.json")["collection_submitted"] is False
    else:
        with pytest.raises(ValueError, match="execution exists"): job.collect_once(case.root, freeze)
        assert not (case.root / job.COLLECTION_NAME).exists()
    assert not any(isinstance(e, tuple) and e[0] == "research" for e in events)


@pytest.mark.parametrize("status", ["blocked", "completed"])
def test_close_failure_never_erases_known_full_result(case, monkeypatch, status):
    freeze, events = fake_collection(case, monkeypatch, status=status, close_problem=True)
    collection, exit_code = job.collect_once(case.root, freeze)
    wrapped = control.read(collection / "COLLECTION_RESULT.json")
    assert wrapped["status"] == status and wrapped["known_research_result"] is True
    assert exit_code == (0 if status == "completed" else 1)
    diag = control.read(collection / "BROWSER_CLOSE_DIAGNOSTIC.json")
    assert diag["native_result_already_validated"] is True and diag["diagnostic_only"] is True


@pytest.mark.parametrize("status", ["blocked", "completed"])
def test_lease_teardown_failure_also_preserves_known_result_and_stops(case, monkeypatch, status):
    freeze, _ = fake_collection(case, monkeypatch, status=status, lease_problem=True)
    collection, exit_code = job.collect_once(case.root, freeze)
    wrapped = control.read(collection / "COLLECTION_RESULT.json")
    assert wrapped["status"] == status and wrapped["known_research_result"] is True
    assert exit_code == (0 if status == "completed" else 1)
    diag = control.read(collection / "COLLECTION_RESOURCE_CLEANUP_DIAGNOSTIC.json")
    assert diag["native_result_already_validated"] is True


@pytest.mark.parametrize("outcome", ["result_unknown", "human_required", "known_human_required", "blocked", "close_failed"])
def test_run_routes_terminal_collection_once_without_text_dispatch(case, monkeypatch, outcome):
    freeze = job.prepare(case.root, process_alive=lambda _: False)
    monkeypatch.setattr(job.original, "wait_for_account_gate", lambda *a: None)
    calls = []
    def collect(root, freeze):
        calls.append(1)
        folder = root / job.COLLECTION_NAME
        folder.mkdir()
        value = {"status": "failed" if outcome == "known_human_required" else outcome if outcome != "close_failed" else "completed",
            "reason": outcome, "known_research_result": outcome in {"blocked", "close_failed", "known_human_required"},
            "result": {"workflow_run_id": "research:" + "a" * 32}}
        write(folder / "COLLECTION_RESULT.json", value)
        if outcome == "close_failed": write(folder / "BROWSER_CLOSE_DIAGNOSTIC.json", {"diagnostic_only": True})
        return folder, 1
    monkeypatch.setattr(job, "collect_once", collect)
    real_reconcile = job.reconcile_collection_durable_result
    def reconcile(**kwargs):
        if Path(kwargs["collection_root"]).name != job.COLLECTION_NAME:
            return real_reconcile(**kwargs)
        return {"may_run_source_validation": outcome == "close_failed",
            "reason": "human_required" if outcome == "known_human_required" else "insufficient_research_sample"}
    monkeypatch.setattr(job, "reconcile_collection_durable_result", reconcile)
    monkeypatch.setattr(job, "run_text_and_production", lambda *a: pytest.fail("no model dispatch on stopped collection"))
    value = job.run(case.root, process_alive=lambda _: False)
    assert value["status"] == ("awaiting_account_verification" if outcome in {"human_required", "known_human_required"} else
        "resource_cleanup_stopped" if outcome == "close_failed" else "collection_stopped")
    assert value["new_model_calls"] == 0 and value["new_media_calls"] == 0
    if outcome == "result_unknown": assert value["result_unknown"] is True
    assert value["known_collection_result"] is (outcome in {"blocked", "close_failed", "known_human_required"})
    with pytest.raises(job.SampleExtensionExists): job.run(case.root, process_alive=lambda _: False)
    assert calls == [1]
