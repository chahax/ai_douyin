"""One coverage batch after a complete, known insufficient legal sample.

The prior collection is never redispatched or combined with this new batch.
Collection and identity share one visible browser in this worker. Console logs
are diagnostic text; the native durable result is the sole business result.
"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import argparse
import io
import json
import math
import os
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_fresh_legal_full_flow_local_recovery_v1 as local
from scripts import run_fresh_legal_collection_local_recovery_v1 as collector
from src.content_factory.creative_subprocess_result_capture_v1 import reconcile_collection_durable_result
from src.operations_accounts.models import AccountProfile
from src.trend_intelligence.sample_gate import evaluate_sample

resume, original, control = local.resume, local.original, local.control
DEFAULT_ROOT = local.DEFAULT_ROOT
FREEZE_NAME = "SAMPLE_EXTENSION_FREEZE_01.json"
CLAIM_NAME = "SAMPLE_EXTENSION_CLAIM_01.json"
COLLECTION_NAME = "collection_live_03"
RECONCILIATION_NAME = "COLLECTION02_TERMINAL_RECONCILIATION_01.json"
PLAN_NAME = "sample_extension_seed_01/LEGAL_CORE_PLAN.json"
_CODE = ("scripts/run_fresh_legal_full_flow_sample_extension_v1.py",
    "src/content_factory/creative_subprocess_result_capture_v1.py",
    "tests/test_fresh_legal_full_flow_sample_extension_v1.py")
_COLLECTION_FILES = ("COLLECTION_CLAIM.json", "LIVE_IDENTITY_CHECK.json", "COLLECTION_RESULT.json",
    "COLLECTION.stdout.log", "COLLECTION.console.stdout.log", "COLLECTION.stderr.log",
    "ORIGINAL_NATIVE_RESEARCH_RESULT.json", "ORIGINAL_RESEARCH_LOG.json")
_POLICY = {"max_additional_batches": 1, "max_related_tags": 6, "max_planned_pages": 21,
    "max_content_candidates": 200, "min_unique_videos": 20, "min_primary_tags": 2,
    "min_confirmed_likes_or_views": 1000000, "same_batch_only": True,
    "automatic_retry": False, "new_media_submissions": 0}
AUTHORIZATION = "用户授权法律号新数据完整文本流程；完整已知不足后，按追加冻结一次新来源覆盖，不重派原采集"


class SampleExtensionExists(RuntimeError):
    pass


def record_state(root, status, **fields):
    original.state(root, status, **fields)
    return control.read(Path(root) / "STATE.json")


def _inside(value):
    path = Path(value)
    path = (path if path.is_absolute() else PROJECT / path).resolve()
    if not path.is_relative_to(PROJECT):
        raise ValueError("extension evidence outside project")
    return path


def _evidence_paths(root):
    rec = control.read(root / RECONCILIATION_NAME)
    return [root / local.FREEZE_NAME, root / local.CLAIM_NAME,
        root / "LOCAL_DISPATCH_COLLECTION_PROCESS_RESULT_01.json", root / RECONCILIATION_NAME,
        root / PLAN_NAME] + [root / resume.COLLECTION_NAME / name for name in _COLLECTION_FILES] + [
        _inside(p) for p in rec.get("evidence_sha256", {})] + [PROJECT / p for p in _CODE]


def _profile(root):
    resources = control.read(root / "RESOURCE_CONFIG.json")
    old_plan = control.read(resources["core_plan_path"])
    profile, binding = original.source_prepare._current_account(PROJECT / "data/douyin.db",
        collector.ACCOUNT_KEY, old_plan["account_uuid"])
    if (type(profile.get("profile_version")) is not int or profile["profile_version"] != collector.PROFILE_VERSION
        or binding["public_uid"] != collector.PUBLIC_ID):
        raise ValueError("current legal account identity changed")
    return AccountProfile(**profile)


def _sql_observations(run_id, profile):
    """Same fields/order as repository.list_observations, with no constructor writes."""
    with original.source_prepare._ro(PROJECT / "data/trend_intelligence.db") as conn:
        run = conn.execute("SELECT * FROM trend_collection_runs WHERE run_id=?", (run_id,)).fetchone()
        if (run is None or run["status"] != "completed" or any(run[k] != getattr(profile, k) for k in (
            "account_uuid", "profile_version", "domain_strategy_id", "strategy_version"))):
            raise ValueError("completed same-account SQL seed batch required")
        rows = conn.execute("""SELECT i.item_id,i.video_id,i.url,i.title,i.author,o.*
            FROM trend_observations o JOIN trend_items i ON i.item_id=o.item_id
            JOIN trend_collection_runs r ON r.run_id=o.run_id
            WHERE o.run_id=? AND r.account_uuid=? ORDER BY o.collected_at DESC,o.rank ASC LIMIT 100000""",
            (run_id, profile.account_uuid)).fetchall()
    scalar = ("item_id", "video_id", "url", "title", "author", "keyword", "sort_key", "sort_label", "rank",
        "run_id", "metric_text", "metric_value", "metric_kind", "collected_at", "published_at", "published_at_text",
        "raw_text", "query_kind", "query_value", "query_depth", "duration_seconds", "relevance_score")
    observations = []
    for row in rows:
        value = {k: row[k] for k in scalar}
        value["video_id"] = value["video_id"] or ""
        value["query_value"] = value["query_value"] or value["keyword"]
        for k in ("root_keywords", "hashtags", "relevance_terms"):
            # The shared strict_json intentionally only accepts objects;
            # SQL collection fields are arrays of strings.
            parsed = json.loads(row[k + "_json"])
            if not isinstance(parsed, list) or not all(isinstance(s, str) for s in parsed):
                raise ValueError("SQL observation list fields malformed")
            value[k] = parsed
        observations.append(value)
    return observations


def validate_seed(root, *, check_sql=True):
    root = resume._root(root)
    plan = control.read(root / PLAN_NAME)
    profile = _profile(root)
    request = collector.request_from_legal_core_plan(plan, profile, headless=False,
        manual_verification_seconds=collector.WAIT_SECONDS)
    pages = collector.estimate_douyin_planned_pages(request)
    bounds = plan.get("inputs", {}).get("bounds", {})
    if (plan.get("core_tag") != "劳动法" or type(pages) is not int or not 1 <= pages <= 21
        or plan.get("estimated_pages") != pages or bounds.get("max_related_tags") != 6
        or bounds.get("max_pages") != 21 or len(plan.get("related_tags", [])) > 6
        or plan.get("inputs", {}).get("profile") != asdict(profile)):
        raise ValueError("native coverage plan outside frozen 6-tag/21-page scope")
    old = control.read(root / resume.COLLECTION_NAME / "COLLECTION_RESULT.json")["result"]
    observations = plan.get("inputs", {}).get("observations")
    if (not isinstance(observations, list) or not observations
        or any(not isinstance(row, dict) or row.get("run_id") != old["collection_run_id"] for row in observations)
        or len(observations) != old["collected_observations"]):
        raise ValueError("seed observations must be exactly the completed old SQL batch")
    if check_sql and collector._canonical(observations) != collector._canonical(_sql_observations(old["collection_run_id"], profile)):
        raise ValueError("native seed inputs differ from actual same-batch SQL observations")
    return {"plan_sha256": control.sha_file(root / PLAN_NAME), "plan_id": plan["plan_id"],
        "core_tag": plan["core_tag"], "related_tags": plan["related_tags"], "estimated_pages": pages,
        "seed_collection_run_id": old["collection_run_id"], "seed_observations": len(observations),
        "seed_observations_sha256": control.digest(observations), "account_uuid": profile.account_uuid,
        "profile_sha256": control.digest(asdict(profile)), "sql_checked_before_collection": check_sql}


def previous_worker_instance_active(claim, *, process_factory=None, observed_at=None):
    """A reused Windows PID is not the process that consumed the old claim.

    Only an observed creation time later than that claim proves a new instance.
    Unavailable identity/time evidence stops the caller; no process is changed.
    """
    import psutil
    pid = claim.get("pid")
    if type(pid) is not int or pid <= 0:
        raise ValueError("previous worker PID invalid")
    try:
        claimed = resume._time(claim["started_at_utc"]).timestamp()
        observed = resume._time(observed_at or control.now()).timestamp()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError("previous worker claim time unknown or invalid") from None
    if not math.isfinite(claimed) or claimed > observed:
        raise ValueError("previous worker claim time outside observed chronology")
    try:
        process = (process_factory or psutil.Process)(pid)
        created = process.create_time()
        if type(created) not in (int, float) or not math.isfinite(created) or not 0 < created <= observed:
            raise ValueError("previous worker process creation time unknown or invalid")
        if created > claimed:
            return False
        active = process.is_running()
        if type(active) is not bool:
            raise ValueError("previous worker process liveness unknown")
        return active
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        raise ValueError("previous worker process identity unavailable") from None


def validate_known_insufficient_stop(root, *, process_alive=None, process_factory=None, check_sql=True):
    """Never infer permission from mutable STATE or from the old console exception."""
    root = resume._root(root)
    base = local.verify_local_recovery_freeze(root)
    resume._assert_no_original_model_execution(root)
    if (root / COLLECTION_NAME).exists():
        raise SampleExtensionExists("coverage batch already exists; inspect original only")
    for name in ("RUN_CLAIM.json", resume.CLAIM_NAME, local.CLAIM_NAME):
        old_claim = control.read(root / name)
        # The bool hook remains solely an explicit offline fixture seam. CLI
        # and production defaults always compare the actual OS process instance.
        active = (process_alive(old_claim.get("pid")) if process_alive is not None else
            previous_worker_instance_active(old_claim, process_factory=process_factory))
        if type(active) is not bool:
            raise ValueError("previous worker process liveness unknown")
        if active:
            raise ValueError("previous worker still active")
    process = control.read(root / "LOCAL_DISPATCH_COLLECTION_PROCESS_RESULT_01.json")
    if (type(process.get("exit_code")) is not int or process["exit_code"] != 1
        or process.get("original_request_redispatch") is not False or process.get("automatic_retry") is not False):
        raise ValueError("known original collection exit1 required")
    claim = control.read(root / local.CLAIM_NAME)
    if not resume._time(claim["started_at_utc"]) <= resume._time(process["finished_at_utc"]) <= resume._time(control.now()):
        raise ValueError("original worker chronology differs")
    rec = control.read(root / RECONCILIATION_NAME)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    old_plan_path = _inside(resources["core_plan_path"])
    old_plan = control.read(old_plan_path)
    verified = reconcile_collection_durable_result(project_root=PROJECT, collection_root=root / resume.COLLECTION_NAME,
        observed_exit_code=process["exit_code"], expected_account_key=collector.ACCOUNT_KEY,
        expected_account_uuid=old_plan["account_uuid"], expected_profile_version=collector.PROFILE_VERSION,
        expected_public_id=collector.PUBLIC_ID, expected_workflow_run_id=rec.get("workflow_run_id"),
        expected_plan_path=old_plan_path, expected_plan_sha256=control.sha_file(old_plan_path))
    native = verified["result"]
    if (verified["status"] != "known_collection_stop" or native.get("status") != "blocked"
        or native.get("stopped_reason") != "insufficient_research_sample"
        or not isinstance(native.get("sample_gate"), dict) or native["sample_gate"].get("passed") is not False
        or not native.get("collection_run_id") or verified.get("may_run_source_validation") is not False):
        raise ValueError("only complete known insufficient sample may extend coverage")
    # Recompute the original first60 gate; do not promote the full90 total.
    gate = evaluate_sample(native["video_records"][:60]).to_dict()
    if collector._canonical(gate) != collector._canonical(native["sample_gate"]):
        raise ValueError("original native sample gate inconsistent")
    if (rec.get("schema") != "fresh_legal_known_collection_stop_reconciliation/v1"
        or rec.get("status") != "collection_stopped" or rec.get("stopped_reason") != "insufficient_research_sample"
        or rec.get("collection_run_id") != native["collection_run_id"] or rec.get("sample_gate") != native["sample_gate"]
        or rec.get("identity_verified") is not True or rec.get("result_unknown") is not False
        or rec.get("old_budget_reset") is not False or rec.get("original_claims_preserved") is not True
        or rec.get("console_raw_bytes_lost_in_original_text_reader") is not True
        or rec.get("actual_console_encoding") != "unknown"
        or any(type(rec.get(k)) is not int or rec[k] != 0 for k in ("new_model_calls", "new_media_calls"))
        or any(rec.get(k) != verified["full_native_collection_validation"][k] for k in (
            "authoritative_full_result_equal", "authoritative_result_sha256", "plan_sha256", "workflow_run_id",
            "eligible_for_source_validation", "known_research_result"))):
        raise ValueError("complete native collection stop reconciliation required")
    evidence = {_inside(p): sha for p, sha in rec.get("evidence_sha256", {}).items()}
    required = {root / resume.COLLECTION_NAME / "COLLECTION_RESULT.json",
        root / resume.COLLECTION_NAME / "COLLECTION.stdout.log", root / "LOCAL_DISPATCH_COLLECTION_PROCESS_RESULT_01.json",
        _inside(native["log_path"])}
    if not required.issubset(evidence):
        raise ValueError("old native stop evidence incomplete")
    original.verify_files({str(p): sha for p, sha in evidence.items()})
    return base, verified, validate_seed(root, check_sql=check_sql)


def execution_resource_symbols():
    symbols = local.execution_resource_symbols()
    return {"allowed_python_executables": symbols["allowed_python_executables"],
        "sample_extension_worker_script": str((PROJECT / _CODE[0]).resolve())}


def preview(root, *, process_alive=None, process_factory=None):
    root = resume._root(root)
    if (root / CLAIM_NAME).exists():
        raise SampleExtensionExists("coverage claim consumed; inspect existing results only")
    base, known, seed = validate_known_insufficient_stop(root, process_alive=process_alive, process_factory=process_factory)
    return {"status": "sample_extension_eligible", "original_grant_id": original.GRANT_ID,
        "old_complete_stop": known["reason"], "seed": seed, "policy": deepcopy(_POLICY),
        "inherited": deepcopy(base["inherited"]), "models": deepcopy(base["models"]),
        "new_dispatches": 0, "creative_quality_passed": False}


def prepare(root, *, process_alive=None, process_factory=None):
    root = resume._root(root)
    if (root / CLAIM_NAME).exists():
        raise SampleExtensionExists("coverage claim consumed; inspect existing results only")
    base, known, seed = validate_known_insufficient_stop(root, process_alive=process_alive, process_factory=process_factory)
    files = deepcopy(base["files"])
    for path in _evidence_paths(root):
        files[str(path.resolve())] = control.sha_file(path)
    symbols = execution_resource_symbols()
    value = {"schema": "fresh_legal_sample_extension_freeze/v1", "original_grant_id": original.GRANT_ID,
        "original_local_freeze_sha256": control.sha_file(root / local.FREEZE_NAME),
        "original_local_claim_sha256": control.sha_file(root / local.CLAIM_NAME),
        "login_confirmation_sha256": base["login_confirmation_sha256"],
        "reconciliation_sha256": control.sha_file(root / RECONCILIATION_NAME),
        "inherited": deepcopy(base["inherited"]), "models": deepcopy(base["models"]),
        "raw_parent_ordinals": deepcopy(base["raw_parent_ordinals"]), "new_generation_calls": 0,
        "collection_directory": COLLECTION_NAME, "plan_path": str(root / PLAN_NAME), "seed": seed,
        "policy": deepcopy(_POLICY), "files": files, "execution_resource_symbols": symbols,
        "external_resource_hashes": {p: control.sha_file(p) for p in symbols["allowed_python_executables"]},
        "old_complete_workflow_run_id": known["workflow_run_id"], "old_complete_collection_run_id": known["result"]["collection_run_id"],
        "original_request_redispatch": False, "automatic_restart": False, "budget_reset": False,
        "new_media_submissions": 0, "new_source_coverage_only": True}
    control.write(root / FREEZE_NAME, value, True)
    return value


def verify_sample_extension_freeze(root):
    root = resume._root(root)
    value = control.read(root / FREEZE_NAME)
    base = local.verify_local_recovery_freeze(root)
    members = set(base["files"]) | {str(p.resolve()) for p in _evidence_paths(root)}
    symbols = execution_resource_symbols()
    if (value.get("schema") != "fresh_legal_sample_extension_freeze/v1"
        or value.get("original_grant_id") != original.GRANT_ID
        or value.get("original_local_freeze_sha256") != control.sha_file(root / local.FREEZE_NAME)
        or value.get("original_local_claim_sha256") != control.sha_file(root / local.CLAIM_NAME)
        or value.get("login_confirmation_sha256") != base["login_confirmation_sha256"]
        or value.get("reconciliation_sha256") != control.sha_file(root / RECONCILIATION_NAME)
        or any(value.get(k) != base[k] for k in ("inherited", "models", "raw_parent_ordinals", "new_generation_calls"))
        or value.get("collection_directory") != COLLECTION_NAME or value.get("plan_path") != str(root / PLAN_NAME)
        or collector._canonical(value.get("policy")) != collector._canonical(_POLICY)
        or value.get("original_request_redispatch") is not False
        or value.get("automatic_restart") is not False or value.get("budget_reset") is not False
        or value.get("new_source_coverage_only") is not True or type(value.get("new_media_submissions")) is not int
        or value["new_media_submissions"] != 0 or set(value.get("files", {})) != members
        or any(value["files"][p] != sha for p, sha in base["files"].items())
        or value.get("execution_resource_symbols") != symbols
        or set(value.get("external_resource_hashes", {})) != set(symbols["allowed_python_executables"])):
        raise ValueError("additive coverage freeze changed scope, source or execution resources")
    original.verify_files(value["files"])
    original.verify_files(value["external_resource_hashes"])
    seed = validate_seed(root, check_sql=False)
    expected_seed = {**seed, "sql_checked_before_collection": True}
    if value.get("seed") != expected_seed:
        raise ValueError("native seed or current profile changed")
    rec = control.read(root / RECONCILIATION_NAME)
    if (value.get("old_complete_workflow_run_id") != rec["workflow_run_id"]
        or value.get("old_complete_collection_run_id") != rec["collection_run_id"]):
        raise ValueError("original complete native batch changed")
    if (root / CLAIM_NAME).exists():
        claim = control.read(root / CLAIM_NAME)
        if (claim.get("schema") != "fresh_legal_sample_extension_claim/v1"
            or claim.get("sample_extension_freeze_sha256") != control.sha_file(root / FREEZE_NAME)
            or claim.get("original_local_claim_sha256") != value["original_local_claim_sha256"]
            or claim.get("original_grant_id") != original.GRANT_ID
            or claim.get("reconciliation_sha256") != value["reconciliation_sha256"]
            or claim.get("login_confirmation_sha256") != value["login_confirmation_sha256"]
            or claim.get("collection_directory") != str(root / COLLECTION_NAME)
            or claim.get("plan_sha256") != value["seed"]["plan_sha256"]
            or claim.get("new_source_coverage_only") is not True
            or claim.get("original_request_redispatch") is not False
            or claim.get("automatic_restart") is not False or claim.get("budget_reset") is not False
            or type(claim.get("pid")) is not int or claim["pid"] <= 0):
            raise ValueError("coverage claim no longer binds its frozen one-batch scope")
        resume._time(claim["started_at_utc"])
    return value


def verify_current_worker(root, freeze, *, process_factory=None):
    import psutil
    claim = control.read(root / CLAIM_NAME)
    if claim["pid"] != os.getpid():
        raise ValueError("current worker differs from coverage claim")
    process = (process_factory or psutil.Process)(os.getpid())
    symbols = freeze["execution_resource_symbols"]
    args = process.cmdline()
    if (not process.is_running() or str(Path(process.exe()).resolve()) not in symbols["allowed_python_executables"]
        or Path(process.exe()).resolve() != Path(sys._base_executable).resolve()
        or not 0 <= resume._time(claim["started_at_utc"]).timestamp() - process.create_time() <= 300
        or len(args) < 2 or collector._argument_path(args[1]) != Path(symbols["sample_extension_worker_script"])):
        raise ValueError("current worker entry/interpreter/process instance not frozen")
    return {"pid": claim["pid"], "executable": str(Path(process.exe()).resolve()),
        "entry": symbols["sample_extension_worker_script"], "same_worker_process": True}


def process_smoke(output):
    """Real console/windowed entry proof in QA; no production claim or browser."""
    output = Path(output).resolve()
    if not output.is_relative_to(PROJECT / "data/qa") or output.exists():
        raise ValueError("new process smoke artifact inside project QA required")
    root = output.parent / (output.stem + "_artifacts")
    root.mkdir(parents=True, exist_ok=False)
    claim = {"pid": os.getpid(), "started_at_utc": control.now(), "qa_process_smoke_only": True}
    control.write(root / CLAIM_NAME, claim, True)
    symbols = execution_resource_symbols()
    proof = verify_current_worker(root, {"execution_resource_symbols": symbols})
    value = {"schema": "sample_extension_real_process_smoke/v1", "at_utc": control.now(),
        "verified_current_worker": proof, "execution_resource_symbols": symbols,
        "sys_executable": sys.executable, "sys_base_executable": sys._base_executable,
        "network_calls": 0, "browser_started": False, "model_calls": 0,
        "production_claims_created": 0, "qa_claim_path": str(root / CLAIM_NAME)}
    control.write(output, value, True)
    return value


def collect_once(root, freeze):
    """One in-process native metadata request; no child log decoding contract."""
    verify_sample_extension_freeze(root)
    worker = verify_current_worker(root, freeze)
    resume._assert_no_original_model_execution(root)
    collection, plan_path = root / COLLECTION_NAME, root / PLAN_NAME
    if collection.exists():
        raise SampleExtensionExists("coverage directory already used")
    collection.mkdir()
    plan, plan_sha = control.read(plan_path), freeze["seed"]["plan_sha256"]
    claim = {"at_utc": collector.now_utc(), "account_key": collector.ACCOUNT_KEY,
        "plan_path": str(plan_path), "plan_sha256": plan_sha, "metadata_only": True,
        "no_model_calls": True, "no_media_calls": True, "automatic_retry": False,
        "headless": False, "same_verified_browser_reused": True,
        "manual_verification_timeout_seconds": collector.WAIT_SECONDS, "lease_seconds": collector.LEASE_SECONDS,
        "parent_sample_extension_claim_sha256": control.sha_file(root / CLAIM_NAME),
        "parent_sample_extension_freeze_sha256": control.sha_file(root / FREEZE_NAME),
        "original_grant_id": original.GRANT_ID, "max_content_candidates": 200,
        "new_source_coverage_only": True, "original_request_redispatch": False, "verified_current_worker": worker}
    collector.save(collection / "COLLECTION_CLAIM.json", claim)
    captured_out, captured_err = io.StringIO(), io.StringIO()
    submitted, native_result, validation, identity = False, None, None, None
    exit_code, terminal_stdout = 1, ""
    try:
        with redirect_stdout(captured_out), redirect_stderr(captured_err):
            service = collector.AccountRuntimeService()
            context = service.resolve(collector.ACCOUNT_KEY)
            if (context.account_key != collector.ACCOUNT_KEY or context.profile.profile_version != collector.PROFILE_VERSION
                or context.binding.public_uid != collector.PUBLIC_ID or context.account_uuid != plan["account_uuid"]):
                raise collector.IdentityFailed("bound_account_changed")
            request = collector.request_from_legal_core_plan(plan, context.profile, headless=False,
                manual_verification_seconds=collector.WAIT_SECONDS)
            pages = collector.estimate_douyin_planned_pages(request)
            if type(pages) is not int or pages != plan["estimated_pages"] or not 1 <= pages <= 21:
                raise collector.ResultBindingError("PLAN_PAGE_BOUND_DIFFERENT")
            with service.operation_lease(context, operation="fresh_legal_sample_extension_collection",
                daily_limit=90, cooldown_seconds=0, lock_seconds=collector.LEASE_SECONDS):
                session = context.create_browser_session(headless=False)
                try:
                    checked = service.verify_identity(context, session=session)
                    identity = {"healthy": checked.healthy, "status": checked.status,
                        "account_key": context.account_key, "profile_version": context.profile.profile_version,
                        "expected_public_id": context.binding.public_uid,
                        "actual_public_id": checked.actual.public_uid if checked.actual else None,
                        "at_utc": collector.now_utc(), "headless": False}
                    collector.save(collection / "LIVE_IDENTITY_CHECK.json", identity)
                    if checked.healthy is not True or checked.status != "active" or identity["actual_public_id"] != collector.PUBLIC_ID:
                        raise collector.IdentityFailed(checked.status)
                    provider = collector.DouyinWebTrendProvider(session_factory=lambda _headless: session)
                    workflow = collector.AccountVideoResearchWorkflow()
                    collector.wait_for_research_clock_boundary(identity["at_utc"])
                    verify_sample_extension_freeze(root)
                    resume._assert_no_original_model_execution(root)
                    submitted = True
                    research = workflow.run(context.profile, provider, request,
                        policy=collector._build_policy(AUTHORIZATION, planned_pages=pages),
                        max_content_candidates=200, content_analysis_implementation="metadata_heuristic",
                        resume_collection_run_id="", local_media_manifest=None, run_local_toolchain=False)
                    native = research.to_dict()
                    collector.save(collection / "ORIGINAL_NATIVE_RESEARCH_RESULT.json", native)
                    old = control.read(root / resume.COLLECTION_NAME / "COLLECTION_RESULT.json")["result"]
                    if native["workflow_run_id"] == old["workflow_run_id"] or (native["collection_run_id"]
                        and native["collection_run_id"] == old["collection_run_id"]):
                        raise collector.ResultBindingError("EXTENSION_CANNOT_REUSE_ORIGINAL_BATCH")
                    native_result, original_raw = collector._bind_authoritative(native, plan_path=plan_path,
                        plan=plan, plan_sha=plan_sha, identity=identity)
                    with (collection / "ORIGINAL_RESEARCH_LOG.json").open("xb") as handle:
                        handle.write(original_raw)
                    terminal_stdout = json.dumps(native_result, ensure_ascii=False, indent=2) + "\n"
                    validation = collector.validate_result(stdout=terminal_stdout, native_result=native_result,
                        claim=claim, identity=identity, plan_path=plan_path, plan=plan, plan_sha=plan_sha,
                        expected_account_uuid=context.account_uuid)
                    if not validation["eligible_for_source_validation"]:
                        raise collector.KnownCollectionFailed(native_result["stopped_reason"])
                    exit_code = 0 if native_result["status"] == "completed" else 1
                finally:
                    try:
                        session.stop()
                    except Exception as close_exc:
                        # A cleanup error cannot erase a complete native result.
                        collector.save(collection / "BROWSER_CLOSE_DIAGNOSTIC.json", {
                            "exception_type": type(close_exc).__name__, "at_utc": control.now(),
                            "native_result_already_validated": validation is not None,
                            "diagnostic_only": True, "automatic_retry": False})
    except collector.KnownCollectionFailed:
        pass
    except collector.IdentityFailed as exc:
        validation = None
        collector.save(collection / "COLLECTION_RESULT.json", {"status": "human_required", "reason": str(exc),
            "identity": identity, "new_model_calls": 0, "new_media_calls": 0,
            "collection_submitted": False, "automatic_retry": False})
    except Exception as exc:
        if validation is not None:
            # Lease release / capture teardown is separate from native result
            # certainty. Preserve the result, then stop before all text calls.
            collector.save(collection / "COLLECTION_RESOURCE_CLEANUP_DIAGNOSTIC.json", {
                "exception_type": type(exc).__name__, "at_utc": control.now(),
                "native_result_already_validated": True, "diagnostic_only": True, "automatic_retry": False})
        else:
            collector.save(collection / "COLLECTION_RESULT.json", {"status": "result_unknown" if submitted else "blocked",
                "reason": str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__,
                "exception_type": type(exc).__name__, "new_model_calls": 0, "new_media_calls": 0,
                "collection_submitted": submitted, "known_research_result": False,
                "automatic_retry": False, "original_request_redispatched": False})
    finally:
        for name, value in (("COLLECTION.stdout.log", terminal_stdout),
            ("COLLECTION.console.stdout.log", captured_out.getvalue()), ("COLLECTION.stderr.log", captured_err.getvalue())):
            with (collection / name).open("x", encoding="utf-8") as handle:
                handle.write(value)
    if validation is not None:
        collector.save(collection / "COLLECTION_RESULT.json", {"status": native_result["status"], "exit_code": exit_code,
            "result": native_result, **validation, "new_model_calls": 0, "new_media_calls": 0,
            "collection_submitted": True, "original_request_redispatched": False, "automatic_retry": False})
    control.write(root / "SAMPLE_EXTENSION_COLLECTION_COMPLETION_01.json", {"exit_code": exit_code,
        "finished_at_utc": control.now(), "same_worker_process": True,
        "automatic_retry": False, "original_request_redispatch": False}, True)
    return collection, exit_code


class SampleExtensionRuntime(control.ContinuationRuntime):
    """Every model dispatch verifies both generations and the additive scope."""
    def __init__(self, project, root, sources, inherited, models, **kwargs):
        provided_guard = kwargs.pop("inherited_guard", lambda: None)
        def guard():
            provided_guard()
            freeze = verify_sample_extension_freeze(Path(root))
            verify_current_worker(Path(root), freeze)
        super().__init__(project, root, sources, inherited, models, inherited_guard=guard, **kwargs)


def run_text_and_production(root, freeze, collection):
    # This is the same complete production tail with an explicit additive guard.
    resume._assert_no_original_model_execution(root)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    requested_after = control.read(collection / "COLLECTION_CLAIM.json")["at_utc"]
    bundle = original.source_prepare.prepare_source_bundle(collect_result=collection / "COLLECTION_RESULT.json",
        trend_db=PROJECT / "data/trend_intelligence.db", profile_db=PROJECT / "data/douyin.db",
        reference_fulltext_path=resources["reference_path"], standards_path=resources["standards_path"],
        verified_legal_context_path=resources["legal_context_path"], now=control.now(), requested_after=requested_after,
        identity_check=collection / "LIVE_IDENTITY_CHECK.json")
    original.source_prepare.write_source_bundle(root / "source", bundle)
    verify_sample_extension_freeze(root)
    sources = [Path(p) for p in freeze["files"]] + [root / FREEZE_NAME, root / CLAIM_NAME,
        root / "SAMPLE_EXTENSION_COLLECTION_COMPLETION_01.json", root / "SAMPLE_EXTENSION_NATIVE_RECONCILIATION_01.json"]
    sources += [p for folder in (root / "source", collection) for p in folder.iterdir() if p.is_file()]
    runtime = SampleExtensionRuntime(PROJECT, root, sources, freeze["inherited"], freeze["models"],
        inherited_guard=lambda: local.verify_local_recovery_freeze(root), quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")
    runtime.prepare()
    invoke = original.make_invoke(root, runtime)
    reference = Path(resources["reference_path"]).read_bytes().decode("utf-8-sig")
    legal = control.read(resources["legal_context_path"])
    preferences, policy = resources["production_preferences"], resources["provider_evidence"]
    source_binding = control.digest(control.read(runtime.ledger)["source_manifest"])
    record_state(root, "fresh_theme_plan_script_running", selected_core=bundle["selected_core"],
        spend=original.spend_summary(runtime), active_entry="sample_extension/v1")
    pipeline = original.text_pipeline.FreshLegalTextPipeline(invoke=invoke,
        persist_state=lambda value: control.write(root / "TEXT_STATE.json", value),
        format_recovery_authorization={"authorized": True, "source_binding_sha256": source_binding,
            "evidence_ref": str(root / "USER_SCOPE.json"), "evidence_sha256": control.sha_file(root / "USER_SCOPE.json")})
    result = pipeline.run(packet=bundle["packet"], legal_context=legal, reference_fulltext=reference,
        expression_standards=control.read(resources["standards_path"]), production_preferences=preferences,
        provider_evidence=policy, source_binding_sha256=source_binding)
    control.write(root / "TEXT_RESULT.json", result, True)
    if result["status"] != "text_ready_for_director":
        return record_state(root, result["status"], stage="full_script", spend=original.spend_summary(runtime),
            selected_core=bundle["selected_core"], active_entry="sample_extension/v1")
    accepted = root / "ACCEPTED_TEXT_PENDING_DIRECTOR"
    accepted.mkdir(exist_ok=False)
    (accepted / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
    material = {"full_current_script": result["script"], "shared_manifest": result["manifest"], "planned_initial_state": result["initial"]}
    loop = original.revisions.initial_loop_state([], source_binding_sha256=source_binding,
        default_limit=3, stable_scope_material=material)
    control.write(root / "INITIAL_LOOP_STATE.json", loop, True)
    record_state(root, "whole_direction_performance_running", title=result["script"]["title"],
        spend=original.spend_summary(runtime), active_entry="sample_extension/v1")
    coordinator = original.directors.EndpointFeedbackCoordinator(invoke=invoke,
        persist_state=lambda value: control.write(root / "LOOP_STATE.json", value),
        verify_frozen_source=lambda: verify_sample_extension_freeze(root),
        opening_context_builder=lambda performance: original.shared.compile_segment_context(result["manifest"], result["script"],
            result["shared_dynamic_initial"], performance["source_refs"], bootstrap=True),
        models=original.text_pipeline.MODEL_POLICY)
    full = coordinator.run(script=result["script"], manifest=result["manifest"], initial=result["initial"],
        reference_fulltext=reference, preferences=preferences, brief=result["brief"],
        source_review_binding=result["source_review_binding"], state=loop, scope=control.read(root / "USER_SCOPE.json"))
    control.write(root / "PRODUCTION_RESULT.json", full, True)
    if full["status"] == "complete_text_production_handoff_ready":
        out = root / "DELIVERABLE"
        out.mkdir(exist_ok=False)
        (out / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
        control.write(out / "COMPLETE_PRODUCTION.json", full, True)
        lines = ["# 整片导演、表演与制作交接", "", "完整文本机器验收；图片/声线与视频内容仍需各自核实。", ""]
        for segment, prompt in zip(full["direction"]["segments"], full["planned_prompts"]):
            lines += ["## " + segment["segment_id"], json.dumps(segment, ensure_ascii=False, indent=2), "", prompt, ""]
        (out / "DIRECTOR_PERFORMANCE_HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")
    return record_state(root, full["status"], reason=full.get("reason"), title=result["script"]["title"],
        spend=original.spend_summary(runtime), complete_text_handoff_ready=full.get("complete_text_handoff_ready", False),
        new_media_calls=0, user_video_review_required=True, active_entry="sample_extension/v1",
        deliverable=str(root / "DELIVERABLE") if (root / "DELIVERABLE").exists() else None)


def run(root, *, process_alive=None, process_factory=None):
    root = resume._root(root)
    if (root / CLAIM_NAME).exists():
        raise SampleExtensionExists("coverage claim consumed; inspect original results only")
    validate_known_insufficient_stop(root, process_alive=process_alive, process_factory=process_factory)
    freeze = verify_sample_extension_freeze(root)
    claim = {"schema": "fresh_legal_sample_extension_claim/v1", "started_at_utc": control.now(),
        "pid": os.getpid(), "sample_extension_freeze_sha256": control.sha_file(root / FREEZE_NAME),
        "original_local_claim_sha256": freeze["original_local_claim_sha256"],
        "original_grant_id": original.GRANT_ID, "reconciliation_sha256": freeze["reconciliation_sha256"],
        "login_confirmation_sha256": freeze["login_confirmation_sha256"], "collection_directory": str(root / COLLECTION_NAME),
        "plan_sha256": freeze["seed"]["plan_sha256"], "original_request_redispatch": False,
        "automatic_restart": False, "budget_reset": False, "new_source_coverage_only": True}
    try:
        with (root / CLAIM_NAME).open("x", encoding="utf-8") as handle:
            json.dump(claim, handle, ensure_ascii=False, indent=2, allow_nan=False)
    except FileExistsError as exc:
        raise SampleExtensionExists("another coverage claim won the exclusive creation") from exc
    original.wait_for_account_gate(root, freeze)
    record_state(root, "collecting_fresh_legal_metadata", new_model_calls=0, new_media_calls=0,
        active_entry="sample_extension/v1", collection_directory=str(root / COLLECTION_NAME), original_claims_preserved=True)
    collection, exit_code = collect_once(root, freeze)
    collected = control.read(collection / "COLLECTION_RESULT.json")
    if collected.get("status") in ("result_unknown", "human_required") or not collected.get("known_research_result"):
        return record_state(root, "awaiting_account_verification" if collected.get("status") == "human_required" else "collection_stopped",
            reason=collected.get("reason", collected.get("status")), new_model_calls=0, new_media_calls=0,
            known_collection_result=False, result_unknown=collected.get("status") == "result_unknown",
            active_entry="sample_extension/v1", automatic_restart=False, original_claims_preserved=True,
            original_collection_result=str(collection / "COLLECTION_RESULT.json"))
    reconciled = reconcile_collection_durable_result(project_root=PROJECT, collection_root=collection,
        observed_exit_code=exit_code, expected_account_key=collector.ACCOUNT_KEY,
        expected_account_uuid=freeze["seed"]["account_uuid"], expected_profile_version=collector.PROFILE_VERSION,
        expected_public_id=collector.PUBLIC_ID, expected_workflow_run_id=collected["result"]["workflow_run_id"],
        expected_plan_path=root / PLAN_NAME, expected_plan_sha256=freeze["seed"]["plan_sha256"])
    control.write(root / "SAMPLE_EXTENSION_NATIVE_RECONCILIATION_01.json", reconciled, True)
    if any((collection / name).exists() for name in ("BROWSER_CLOSE_DIAGNOSTIC.json", "COLLECTION_RESOURCE_CLEANUP_DIAGNOSTIC.json")):
        return record_state(root, "resource_cleanup_stopped", reason="resource_cleanup_failed_after_known_result",
            known_collection_result=True, result_unknown=False, new_model_calls=0, new_media_calls=0,
            active_entry="sample_extension/v1", original_claims_preserved=True, automatic_restart=False,
            original_collection_result=str(collection / "COLLECTION_RESULT.json"))
    if not reconciled["may_run_source_validation"]:
        return record_state(root, "awaiting_account_verification" if reconciled["reason"] == "human_required" else "collection_stopped",
            reason=reconciled["reason"], new_model_calls=0, new_media_calls=0,
            known_collection_result=True, result_unknown=False,
            active_entry="sample_extension/v1", automatic_restart=False, original_claims_preserved=True,
            original_collection_result=str(collection / "COLLECTION_RESULT.json"))
    return run_text_and_production(root, freeze, collection)


def emit_optional(value, *, diagnostic_path=None):
    """Console display can fail without rewriting a saved business terminal."""
    if sys.stdout is None:
        return False
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
        return True
    except Exception as exc:
        if diagnostic_path is not None:
            try:
                with Path(diagnostic_path).open("x", encoding="utf-8") as handle:
                    json.dump({"schema": "sample_extension_display_diagnostic/v1", "at_utc": control.now(),
                        "exception_type": type(exc).__name__, "display_only": True,
                        "business_state_modified": False, "automatic_retry": False}, handle, indent=2)
            except OSError:
                pass
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status", "preview", "process-smoke"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "process-smoke":
            if args.output is None:
                parser.error("process-smoke needs --output inside project data/qa")
            value = process_smoke(args.output)
        elif args.command == "status":
            value = control.read(args.root / "STATE.json")
        elif args.command == "preview":
            value = preview(args.root)
        elif args.command == "prepare":
            freeze = prepare(args.root)
            value = {"status": "sample_extension_prepared", "frozen_files": len(freeze["files"]), "new_dispatches": 0}
        else:
            value = run(args.root)
    except SampleExtensionExists:
        emit_optional({"status": "original_sample_extension_exists", "no_new_dispatch": True})
        raise SystemExit(2)
    except Exception as exc:
        if args.command == "run" and (args.root / CLAIM_NAME).exists():
            record_state(args.root, "stopped_exception", exception_type=type(exc).__name__,
                reason=str(exc)[:1200] if isinstance(exc, (ValueError, RuntimeError)) else "original local exception preserved by type",
                new_media_calls=0, active_entry="sample_extension/v1", inspect_original_request_only=True)
        raise
    # Deliberately outside the business exception handler, including pythonw.
    emit_optional(value, diagnostic_path=args.root / ("SAMPLE_EXTENSION_DISPLAY_DIAGNOSTIC_" + str(os.getpid()) + ".json")
        if args.command == "run" else None)


if __name__ == "__main__":
    main()
