"""Repair one proven local pre-dispatch failure without restarting old claims.

The failed collector rejected its process parent before creating its collection
claim or browser. A separate claim/freeze permits the first actual collection;
unknown, remote, model and already-claimed results are ineligible.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_fresh_legal_full_flow_resume_v1 as resume

original = resume.original
control = resume.control
DEFAULT_ROOT = resume.DEFAULT_ROOT
FREEZE_NAME = "LOCAL_DISPATCH_RECOVERY_FREEZE_01.json"
CLAIM_NAME = "LOCAL_DISPATCH_RECOVERY_CLAIM_01.json"
_CODE = ("scripts/run_fresh_legal_full_flow_local_recovery_v1.py",
    "scripts/run_fresh_legal_collection_local_recovery_v1.py")
_PROOF = ("RESUME_FREEZE_01.json", "RESUME_CLAIM_01.json",
    "RESUME_COLLECTION_PROCESS_RESULT_01.json", "RESUME_COLLECTION.stdout.log", "RESUME_COLLECTION.stderr.log",
    "LOCAL_DISPATCH_FAILURE_RECONCILIATION_01.json", "ORIGINAL_STOP_STATE_BEFORE_LOCAL_RECONCILIATION_01.json")


class LocalDispatchRecoveryExists(RuntimeError):
    pass


def execution_resource_symbols():
    """Both console/windowed variants use the same checked Windows venv chain."""
    folders = {(PROJECT / ".venv/Scripts").resolve(), Path(sys._base_executable).resolve().parent}
    executables = sorted(str(p.resolve()) for folder in folders for name in ("python.exe", "pythonw.exe")
        if (p := folder / name).is_file())
    if not executables:
        raise ValueError("known Python execution resources unavailable")
    return {"allowed_python_executables": executables,
        "recovery_worker_script": str((PROJECT / _CODE[0]).resolve())}


def _extra_paths(root):
    reconciliation = control.read(root / "LOCAL_DISPATCH_FAILURE_RECONCILIATION_01.json")
    return [root / p for p in _PROOF] + [PROJECT / p for p in _CODE] + [Path(p) for p in reconciliation["evidence_sha256"]]


def validate_local_dispatch_stop(root, *, process_alive=resume._process_alive):
    root = resume._root(root)
    # Reuse the read-only original known human stop, including source/spend and
    # no-runtime-evidence checks. It does not re-enter or remove either claim.
    resume.validate_known_human_stop(root, process_alive=process_alive)
    base = resume.verify_resume_freeze(root)
    claim = control.read(root / resume.CLAIM_NAME)
    if process_alive(claim.get("pid")):
        raise ValueError("previous continuation worker still active")
    result = control.read(root / "RESUME_COLLECTION_PROCESS_RESULT_01.json")
    if (type(result.get("exit_code")) is not int or result["exit_code"] != 1
        or result.get("original_request_redispatch") is not False or result.get("automatic_retry") is not False):
        raise ValueError("known local child exit required")
    started = resume._time(claim["started_at_utc"])
    finished = resume._time(result["finished_at_utc"])
    if not 0 <= (finished - started).total_seconds() <= 60:
        raise ValueError("local pre-dispatch failure chronology outside bound")
    stdout = (root / "RESUME_COLLECTION.stdout.log").read_text(encoding="utf-8-sig")
    stderr = (root / "RESUME_COLLECTION.stderr.log").read_text(encoding="utf-8-sig")
    expected_script = str((PROJECT / "scripts/run_fresh_legal_collection_resume_v1.py").resolve())
    if (stdout.strip() or not stderr.startswith("Traceback (most recent call last):\n")
        or not stderr.rstrip().endswith("ResultBindingError: ACTIVE_PARENT_CONTINUATION_CLAIM_REQUIRED")
        or "verify_continuation_parent" not in stderr or expected_script not in stderr
        or stderr.count("Traceback (most recent call last):") != 1):
        raise ValueError("exact pre-browser local parent rejection evidence required")
    # Frozen v1 collector invokes this rejecting guard before mkdir/claim and
    # all account/session work. Its absence is required, not inferred from an
    # empty model ledger or from an exception that happened after dispatch.
    if (root / resume.COLLECTION_NAME).exists():
        raise ValueError("collection already claimed or started; inspect original only")
    reconciliation = control.read(root / "LOCAL_DISPATCH_FAILURE_RECONCILIATION_01.json")
    if (reconciliation.get("schema") != "fresh_legal_local_dispatch_failure_reconciliation/v1"
        or reconciliation.get("status") != "known_local_prerequisite_rejected"
        or reconciliation.get("failure_code") != "ACTIVE_PARENT_CONTINUATION_CLAIM_REQUIRED"
        or reconciliation.get("stage") != "collector_parent_binding_before_directory_and_claim"
        or reconciliation.get("child_exit_code") != 1 or reconciliation.get("original_worker_pid") != claim["pid"]
        or reconciliation.get("original_worker_running") is not False
        or reconciliation.get("collection_submitted") is not False or reconciliation.get("browser_started") is not False
        or reconciliation.get("result_unknown") is not False or reconciliation.get("old_budget_reset") is not False
        or reconciliation.get("original_claims_preserved") is not True
        or any(type(reconciliation.get(k)) is not int or reconciliation[k] != 0 for k in (
            "new_model_calls", "new_media_calls", "new_collected_videos"))):
        raise ValueError("explicit zero-dispatch local failure reconciliation required")
    evidence = reconciliation.get("evidence_sha256", {})
    proof = {str((root / p).resolve()) for p in _PROOF[:5]}
    if (not proof.issubset(evidence) or any(not Path(p).resolve().is_relative_to(PROJECT) for p in evidence)):
        raise ValueError("complete original local failure evidence required")
    original.verify_files(evidence)
    paths = _extra_paths(root)
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise ValueError("local repair code or original proof incomplete")
    return base


def process_smoke(output):
    """Run the actual Windows venv child chain without any browser or client."""
    output = Path(output).resolve()
    if not output.is_relative_to(PROJECT / "data/qa"):
        raise ValueError("local process smoke output must stay inside project QA")
    if output.exists():
        raise ValueError("process smoke output already exists; use another artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    symbols = execution_resource_symbols()
    smoke_claim = {"pid": os.getpid(), "started_at_utc": control.now()}
    child_code = (
        "import json,sys; from scripts.run_fresh_legal_collection_local_recovery_v1 import verify_worker_ancestry; "
        "v=json.loads(sys.stdin.read()); print(json.dumps({'child_pid':__import__('os').getpid(),"
        "'direct_parent_pid':__import__('os').getppid(),'verified_ancestry':verify_worker_ancestry(v['claim'],v['symbols'])}))"
    )
    child = subprocess.run([sys.executable, "-c", child_code],
        input=json.dumps({"claim": smoke_claim, "symbols": symbols}), cwd=PROJECT,
        capture_output=True, text=True, encoding="utf-8")
    value = {"schema": "local_recovery_windows_venv_guard_smoke/v1", "at_utc": control.now(),
        "worker_pid": os.getpid(), "worker_entry": symbols["recovery_worker_script"],
        "worker_claim": smoke_claim, "execution_resource_symbols": symbols, "exit_code": child.returncode,
        "child_stdout": child.stdout, "child_stderr": child.stderr,
        "network_calls": 0, "browser_started": False, "model_calls": 0, "production_claims_created": 0}
    control.write(output, value, True)
    if child.returncode != 0:
        raise ValueError("actual Windows local child guard smoke failed; inspect saved proof")
    result = control.strict_json(child.stdout)
    if not result.get("verified_ancestry"):
        raise ValueError("actual child did not return verified worker ancestry")
    return value


def prepare(root, *, process_alive=resume._process_alive):
    root = resume._root(root)
    if (root / CLAIM_NAME).exists():
        raise LocalDispatchRecoveryExists("existing local recovery claim; inspect original results only")
    base = validate_local_dispatch_stop(root, process_alive=process_alive)
    files = deepcopy(base["files"])
    for path in _extra_paths(root):
        files[str(path.resolve())] = control.sha_file(path)
    symbols = execution_resource_symbols()
    value = {"schema": "fresh_legal_local_dispatch_recovery_freeze/v1", "original_grant_id": original.GRANT_ID,
        "original_resume_freeze_sha256": control.sha_file(root / resume.FREEZE_NAME),
        "original_resume_claim_sha256": control.sha_file(root / resume.CLAIM_NAME),
        "login_confirmation_sha256": base["login_confirmation_sha256"],
        "inherited": deepcopy(base["inherited"]), "models": deepcopy(base["models"]),
        "raw_parent_ordinals": deepcopy(base["raw_parent_ordinals"]), "new_generation_calls": 0,
        "collection_directory": resume.COLLECTION_NAME, "files": files,
        "execution_resource_symbols": symbols,
        "external_resource_hashes": {p: control.sha_file(p) for p in symbols["allowed_python_executables"]},
        "original_request_redispatch": False, "automatic_restart": False, "budget_reset": False,
        "local_pre_dispatch_repair_only": True, "new_media_submissions": 0}
    control.write(root / FREEZE_NAME, value, True)
    return value


def verify_local_recovery_freeze(root):
    root = resume._root(root)
    value = control.read(root / FREEZE_NAME)
    base = resume.verify_resume_freeze(root)
    members = set(base["files"]) | {str(p.resolve()) for p in _extra_paths(root)}
    symbols = execution_resource_symbols()
    if (value.get("schema") != "fresh_legal_local_dispatch_recovery_freeze/v1"
        or value.get("original_grant_id") != original.GRANT_ID
        or value.get("original_resume_freeze_sha256") != control.sha_file(root / resume.FREEZE_NAME)
        or value.get("original_resume_claim_sha256") != control.sha_file(root / resume.CLAIM_NAME)
        or value.get("login_confirmation_sha256") != base["login_confirmation_sha256"]
        or any(value.get(k) != base[k] for k in ("inherited", "models", "raw_parent_ordinals", "new_generation_calls"))
        or value.get("collection_directory") != resume.COLLECTION_NAME
        or value.get("original_request_redispatch") is not False or value.get("automatic_restart") is not False
        or value.get("budget_reset") is not False or value.get("local_pre_dispatch_repair_only") is not True
        or value.get("new_media_submissions") != 0 or set(value.get("files", {})) != members
        or any(value["files"][p] != sha for p, sha in base["files"].items())
        or value.get("execution_resource_symbols") != symbols
        or set(value.get("external_resource_hashes", {})) != set(symbols["allowed_python_executables"])):
        raise ValueError("local additive freeze cannot change scope, source or execution resources")
    original.verify_files(value["files"])
    original.verify_files(value["external_resource_hashes"])
    if (root / CLAIM_NAME).exists():
        claim = control.read(root / CLAIM_NAME)
        if (claim.get("schema") != "fresh_legal_local_dispatch_recovery_claim/v1"
            or claim.get("local_recovery_freeze_sha256") != control.sha_file(root / FREEZE_NAME)
            or claim.get("original_resume_claim_sha256") != value["original_resume_claim_sha256"]
            or claim.get("original_grant_id") != original.GRANT_ID
            or claim.get("login_confirmation_sha256") != value["login_confirmation_sha256"]
            or claim.get("collection_directory") != str(root / resume.COLLECTION_NAME)
            or claim.get("original_request_redispatch") is not False
            or claim.get("automatic_restart") is not False or claim.get("budget_reset") is not False
            or claim.get("local_pre_dispatch_repair_only") is not True):
            raise ValueError("local recovery claim no longer binds its freeze")
    return value


class LocalRecoveryRuntime(control.ContinuationRuntime):
    """Every runtime call checks both immutable generations of local bindings."""
    def __init__(self, project, root, sources, inherited, models, **kwargs):
        provided_guard = kwargs.pop("inherited_guard", lambda: None)
        def guard():
            provided_guard()
            verify_local_recovery_freeze(Path(root))
        super().__init__(project, root, sources, inherited, models, inherited_guard=guard, **kwargs)


def run_text_and_production(root, freeze, collection):
    """Same production tail with an explicit local-frozen runtime subclass."""
    resume._assert_no_original_model_execution(root)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    requested_after = control.read(collection / "COLLECTION_CLAIM.json")["at_utc"]
    bundle = original.source_prepare.prepare_source_bundle(collect_result=collection / "COLLECTION_RESULT.json",
        trend_db=PROJECT / "data/trend_intelligence.db", profile_db=PROJECT / "data/douyin.db",
        reference_fulltext_path=resources["reference_path"], standards_path=resources["standards_path"],
        verified_legal_context_path=resources["legal_context_path"], now=control.now(), requested_after=requested_after,
        identity_check=collection / "LIVE_IDENTITY_CHECK.json")
    original.source_prepare.write_source_bundle(root / "source", bundle)
    verify_local_recovery_freeze(root)
    sources = [Path(p) for p in freeze["files"]]
    sources += [root / FREEZE_NAME, root / CLAIM_NAME]
    sources += [p for folder in (root / "source", collection) for p in folder.iterdir() if p.is_file()]
    runtime = LocalRecoveryRuntime(PROJECT, root, sources, freeze["inherited"], freeze["models"],
        inherited_guard=lambda: resume.verify_resume_freeze(root), quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")
    runtime.prepare()
    invoke = original.make_invoke(root, runtime)
    reference = Path(resources["reference_path"]).read_bytes().decode("utf-8-sig")
    legal = control.read(resources["legal_context_path"])
    preferences, policy = resources["production_preferences"], resources["provider_evidence"]
    source_binding = control.digest(control.read(runtime.ledger)["source_manifest"])
    original.state(root, "fresh_theme_plan_script_running", selected_core=bundle["selected_core"],
        spend=original.spend_summary(runtime), active_entry="local_dispatch_recovery/v1")
    pipeline = original.text_pipeline.FreshLegalTextPipeline(invoke=invoke,
        persist_state=lambda value: control.write(root / "TEXT_STATE.json", value),
        format_recovery_authorization={"authorized": True, "source_binding_sha256": source_binding,
            "evidence_ref": str(root / "USER_SCOPE.json"), "evidence_sha256": control.sha_file(root / "USER_SCOPE.json")})
    result = pipeline.run(packet=bundle["packet"], legal_context=legal, reference_fulltext=reference,
        expression_standards=control.read(resources["standards_path"]), production_preferences=preferences,
        provider_evidence=policy, source_binding_sha256=source_binding)
    control.write(root / "TEXT_RESULT.json", result, True)
    if result["status"] != "text_ready_for_director":
        return original.state(root, result["status"], stage="full_script", spend=original.spend_summary(runtime),
            selected_core=bundle["selected_core"], active_entry="local_dispatch_recovery/v1")
    accepted = root / "ACCEPTED_TEXT_PENDING_DIRECTOR"
    accepted.mkdir(exist_ok=False)
    (accepted / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
    material = {"full_current_script": result["script"], "shared_manifest": result["manifest"], "planned_initial_state": result["initial"]}
    loop = original.revisions.initial_loop_state([], source_binding_sha256=source_binding,
        default_limit=3, stable_scope_material=material)
    control.write(root / "INITIAL_LOOP_STATE.json", loop, True)
    original.state(root, "whole_direction_performance_running", title=result["script"]["title"],
        spend=original.spend_summary(runtime), active_entry="local_dispatch_recovery/v1")
    coordinator = original.directors.EndpointFeedbackCoordinator(invoke=invoke,
        persist_state=lambda value: control.write(root / "LOOP_STATE.json", value),
        verify_frozen_source=lambda: verify_local_recovery_freeze(root),
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
    return original.state(root, full["status"], reason=full.get("reason"), title=result["script"]["title"],
        spend=original.spend_summary(runtime), complete_text_handoff_ready=full.get("complete_text_handoff_ready", False),
        new_media_calls=0, user_video_review_required=True, active_entry="local_dispatch_recovery/v1",
        deliverable=str(root / "DELIVERABLE") if (root / "DELIVERABLE").exists() else None)


def run(root, *, process_alive=resume._process_alive):
    root = resume._root(root)
    if (root / CLAIM_NAME).exists():
        raise LocalDispatchRecoveryExists("existing local recovery claim; inspect original results only")
    validate_local_dispatch_stop(root, process_alive=process_alive)
    freeze = verify_local_recovery_freeze(root)
    try:
        with (root / CLAIM_NAME).open("x", encoding="utf-8") as handle:
            json.dump({"schema": "fresh_legal_local_dispatch_recovery_claim/v1", "started_at_utc": control.now(),
                "pid": os.getpid(), "local_recovery_freeze_sha256": control.sha_file(root / FREEZE_NAME),
                "original_resume_claim_sha256": freeze["original_resume_claim_sha256"],
                "original_grant_id": original.GRANT_ID, "login_confirmation_sha256": freeze["login_confirmation_sha256"],
                "collection_directory": str(root / resume.COLLECTION_NAME), "original_request_redispatch": False,
                "automatic_restart": False, "budget_reset": False, "local_pre_dispatch_repair_only": True}, handle, indent=2)
    except FileExistsError as exc:
        raise LocalDispatchRecoveryExists("another local recovery claim already exists; no dispatch") from exc
    original.wait_for_account_gate(root, freeze)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    collection = root / resume.COLLECTION_NAME
    original.state(root, "collecting_fresh_legal_metadata", new_model_calls=0, new_media_calls=0,
        active_entry="local_dispatch_recovery/v1", collection_directory=str(collection), original_claims_preserved=True)
    child = subprocess.run([sys.executable, _CODE[1], str(collection), resources["core_plan_path"]],
        cwd=PROJECT, capture_output=True, text=True, encoding="utf-8")
    control.write(root / "LOCAL_DISPATCH_COLLECTION_PROCESS_RESULT_01.json", {"exit_code": child.returncode,
        "finished_at_utc": control.now(), "original_request_redispatch": False, "automatic_retry": False}, True)
    for name, text in (("LOCAL_DISPATCH_COLLECTION.stdout.log", child.stdout), ("LOCAL_DISPATCH_COLLECTION.stderr.log", child.stderr)):
        with (root / name).open("x", encoding="utf-8") as handle:
            handle.write(text)
    if not (collection / "COLLECTION_RESULT.json").is_file():
        raise ValueError("collector stopped before a durable result; inspect original process proof")
    collected = control.read(collection / "COLLECTION_RESULT.json")
    if collected.get("status") not in ("completed", "awaiting_media_analysis"):
        return original.state(root, "awaiting_account_verification" if collected.get("status") == "human_required" else "collection_stopped",
            reason=collected.get("reason", collected.get("status")), original_collection_result=str(collection / "COLLECTION_RESULT.json"),
            new_model_calls=0, new_media_calls=0, active_entry="local_dispatch_recovery/v1",
            automatic_restart=False, original_claims_preserved=True)
    if child.returncode != collected.get("exit_code"):
        raise ValueError("saved collection exit code differs from actual child process")
    return run_text_and_production(root, freeze, collection)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status", "process-smoke"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "process-smoke":
        if args.output is None:
            parser.error("process-smoke needs --output inside project data/qa")
        value = process_smoke(args.output)
        print(json.dumps({"status": "local_process_smoke_passed", "exit_code": value["exit_code"],
            "network_calls": 0, "output": str(args.output)}, ensure_ascii=False))
        return
    if args.command == "status":
        print(json.dumps(control.read(args.root / "STATE.json"), ensure_ascii=False, indent=2))
        return
    try:
        if args.command == "prepare":
            value = prepare(args.root)
            print(json.dumps({"status": "local_dispatch_recovery_prepared", "frozen_files": len(value["files"]),
                "new_dispatches": 0}, ensure_ascii=False))
        else:
            run(args.root)
    except LocalDispatchRecoveryExists:
        print(json.dumps({"status": "original_local_recovery_exists", "no_new_dispatch": True}))
        raise SystemExit(2)
    except Exception as exc:
        if args.command == "run" and (args.root / CLAIM_NAME).exists():
            original.state(args.root, "stopped_exception", exception_type=type(exc).__name__,
                reason=str(exc)[:1200] if isinstance(exc, (ValueError, RuntimeError)) else "original local exception preserved by type",
                new_media_calls=0, active_entry="local_dispatch_recovery/v1", inspect_original_request_only=True)
        raise


if __name__ == "__main__":
    main()
