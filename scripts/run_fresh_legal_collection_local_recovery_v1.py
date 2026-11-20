"""One first collection after a proved local pre-dispatch launch failure.

The enclosing local-recovery entry verifies the known human-required stop,
the user's login confirmation and the prior zero-dispatch local failure.
This collector uses the still-unused collection claim and
one identity-verified visible browser for both identity and search. It reuses
the existing research workflow, request and source policy; no source media or
model request is enabled.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.run_account_video_research import _build_policy
from src.content_factory.creative_collection_cli_result_v1 import extract_terminal_research_json
from src.operations_accounts import AccountRuntimeService
from src.trend_intelligence.collection.legal_core import request_from_legal_core_plan
from src.trend_intelligence.providers import DouyinWebTrendProvider, estimate_douyin_planned_pages
from src.trend_intelligence.research_workflow import AccountVideoResearchWorkflow

ACCOUNT_KEY = "account01"
PROFILE_VERSION = 1
PUBLIC_ID = "dy4qyzku18yu"
WAIT_SECONDS = 600
LEASE_SECONDS = 4200
USER_QUOTE = "可以测试剧本完整流程了可以再次获取下平台信息了再后台运行"
AUTHORIZATION = "用户2026-10-12明确授权采集法律号新数据后后台测试完整剧本流程，人工完成登录后续采一次"
COUNTERS = ("collected_observations", "unique_videos", "tag_relations", "tag_traffic_snapshots",
            "clusters", "briefs", "content_analyses", "opportunities")


class ResultBindingError(ValueError):
    pass


class IdentityFailed(RuntimeError):
    pass


class KnownCollectionFailed(RuntimeError):
    """Raise inside the account lease so a failed search remains a failure."""


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _instant(value):
    if not isinstance(value, str):
        raise ResultBindingError("BOUND_TIME_INVALID")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ResultBindingError("BOUND_TIME_INVALID") from None
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ResultBindingError("BOUND_TIME_NAIVE")
    return instant.astimezone(timezone.utc)


def wait_for_research_clock_boundary(verified_at, *, utc_now=None, sleep=None):
    """Preserve exact identity time when the existing runner emits whole seconds.

    Waiting below 1.1 seconds avoids a freshly emitted runner timestamp being
    rounded before the identity check. No saved timestamp is altered.
    """
    verified = _instant(verified_at)
    boundary = verified.replace(microsecond=0) + (timedelta(seconds=1) if verified.microsecond else timedelta())
    observed = (utc_now or (lambda: datetime.now(timezone.utc)))()
    remaining = (boundary - observed).total_seconds()
    if remaining > 1.1:
        raise ResultBindingError("CLOCK_BOUNDARY_WAIT_OUTSIDE_BOUND")
    if remaining > 0:
        (sleep or time.sleep)(remaining)


def _inside_project(path):
    value = Path(path)
    if not value.is_absolute():
        value = PROJECT / value
    value = value.resolve()
    if not value.is_relative_to(PROJECT):
        raise ResultBindingError("EVIDENCE_OUTSIDE_PROJECT")
    return value


def _plan_binding(plan_path, plan, plan_sha):
    return {"path": str(plan_path), "file_sha256": plan_sha, "plan_id": plan["plan_id"],
            "core_tag": plan["core_tag"], "related_tags": plan["related_tags"],
            "estimated_pages": plan["estimated_pages"], "metadata_only": True,
            "script_generation_submitted": False}


def verify_continuation_parent(root, plan_path, *, verifier=None, process_alive=None, parent_pid=None):
    """Bind the one local recovery through a bounded real process ancestry.

    Windows venv executables can insert a Python proxy process between this
    interpreter and its worker. The authorized worker must be an actual live
    ancestor with a frozen interpreter and entry point, rather than merely any
    live PID or an assumed immediate parent. No existing claim is changed.
    """
    if root.name != "collection_live_02":
        raise ResultBindingError("EXACT_CONTINUATION_COLLECTION_REQUIRED")
    if verifier is None:
        from scripts import run_fresh_legal_full_flow_local_recovery_v1 as resume
        verifier = resume.verify_local_recovery_freeze
    parent = root.parent
    freeze = verifier(parent)
    claim_path = parent / "LOCAL_DISPATCH_RECOVERY_CLAIM_01.json"
    claim = extract_terminal_research_json(claim_path.read_text(encoding="utf-8-sig"))
    if (freeze.get("collection_directory") != root.name
            or claim.get("schema") != "fresh_legal_local_dispatch_recovery_claim/v1"
            or type(claim.get("pid")) is not int or claim["pid"] <= 0
            or claim.get("local_recovery_freeze_sha256") != hashlib.sha256((parent / "LOCAL_DISPATCH_RECOVERY_FREEZE_01.json").read_bytes()).hexdigest()
            or claim.get("collection_directory") != str(root)
            or claim.get("local_pre_dispatch_repair_only") is not True
            or claim.get("original_grant_id") != freeze.get("original_grant_id")
            or claim.get("login_confirmation_sha256") != freeze.get("login_confirmation_sha256")
            or claim.get("automatic_restart") is not False or claim.get("budget_reset") is not False
            or claim.get("original_request_redispatch") is not False):
        raise ResultBindingError("ACTIVE_LOCAL_RECOVERY_CLAIM_REQUIRED")
    ancestry = verify_worker_ancestry(claim, freeze.get("execution_resource_symbols"),
        process_alive=process_alive, parent_pid=parent_pid)
    resources = extract_terminal_research_json((parent / "RESOURCE_CONFIG.json").read_text(encoding="utf-8-sig"))
    if Path(resources.get("core_plan_path", "")).resolve() != plan_path:
        raise ResultBindingError("FROZEN_CONTINUATION_PLAN_REQUIRED")
    return {"parent_local_recovery_claim_sha256": hashlib.sha256(claim_path.read_bytes()).hexdigest(),
            "parent_local_recovery_freeze_sha256": claim["local_recovery_freeze_sha256"],
            "original_grant_id": claim["original_grant_id"],
            "login_confirmation_sha256": claim["login_confirmation_sha256"],
            "verified_worker_ancestry": ancestry}


def verify_worker_ancestry(claim, symbols, *, process_factory=None, process_alive=None,
                           parent_pid=None, max_depth=2, proxy_executable=None, worker_executable=None):
    """Accept a direct worker parent or one verified local venv Python proxy.

    The two-level maximum follows the actual offline Windows process smoke;
    it does not allow a generic sequence of Python ancestor processes.
    """
    import psutil
    process_factory = process_factory or psutil.Process
    if (not isinstance(symbols, dict) or not isinstance(symbols.get("allowed_python_executables"), list)
            or not symbols["allowed_python_executables"]
            or not all(isinstance(value, str) and value and Path(value).is_absolute()
                       for value in symbols["allowed_python_executables"])
            or not isinstance(symbols.get("recovery_worker_script"), str)
            or not Path(symbols["recovery_worker_script"]).is_absolute()
            or type(max_depth) is not int or not 1 <= max_depth <= 2):
        raise ResultBindingError("FROZEN_EXECUTION_RESOURCE_SYMBOLS_REQUIRED")
    allowed = {Path(value).resolve() for value in symbols["allowed_python_executables"]
               if isinstance(value, str) and value}
    if len(allowed) != len(set(symbols["allowed_python_executables"])):
        raise ResultBindingError("FROZEN_EXECUTION_RESOURCE_SYMBOLS_INVALID")
    expected_script = Path(symbols["recovery_worker_script"]).resolve()
    expected_proxy = Path(proxy_executable or sys.executable).resolve()
    expected_worker = Path(worker_executable or sys._base_executable).resolve()
    if not expected_script.is_relative_to(PROJECT):
        raise ResultBindingError("FROZEN_WORKER_SCRIPT_OUTSIDE_PROJECT")
    pid = os.getppid() if parent_pid is None else parent_pid
    seen = []
    for _ in range(max_depth):
        if type(pid) is not int or pid <= 0 or pid in seen:
            raise ResultBindingError("AUTHORIZED_WORKER_NOT_IN_ANCESTRY")
        seen.append(pid)
        try:
            process = process_factory(pid)
            if not process.is_running() or Path(process.exe()).resolve() not in allowed:
                raise ResultBindingError("ANCESTOR_INTERPRETER_NOT_FROZEN")
            if pid == claim["pid"]:
                if Path(process.exe()).resolve() != expected_worker:
                    raise ResultBindingError("AUTHORIZED_WORKER_INTERPRETER_DIFFERENT")
                if process_alive is not None and not process_alive(pid):
                    raise ResultBindingError("AUTHORIZED_WORKER_NOT_ACTIVE")
                created = process.create_time()
                claimed = _instant(claim.get("started_at_utc")).timestamp()
                if type(created) not in (int, float) or not 0 <= claimed - created <= 300:
                    raise ResultBindingError("WORKER_PROCESS_INSTANCE_DIFFERENT")
                args = process.cmdline()[1:]
                if not any(_argument_path(arg) == expected_script for arg in args):
                    raise ResultBindingError("WORKER_ENTRY_POINT_DIFFERENT")
                return {"ancestor_pids": seen, "authorized_worker_pid": pid,
                        "authorized_worker_executable": str(Path(process.exe()).resolve()),
                        "authorized_worker_script": str(expected_script),
                        "bounded_depth": max_depth, "process_instance_verified": True}
            if Path(process.exe()).resolve() != expected_proxy or len(seen) != 1:
                raise ResultBindingError("ONLY_ONE_LOCAL_VENV_PROXY_ALLOWED")
            pid = process.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            raise ResultBindingError("ANCESTRY_PROCESS_UNAVAILABLE") from None
    raise ResultBindingError("AUTHORIZED_WORKER_ANCESTRY_BOUND_EXCEEDED")


def _argument_path(value):
    if not isinstance(value, str) or not value or value.startswith("-"):
        return None
    try:
        path = Path(value)
        return (path if path.is_absolute() else PROJECT / path).resolve()
    except (OSError, ValueError):
        return None


def validate_result(*, stdout, native_result, claim, identity, plan_path, plan, plan_sha,
                    expected_account_uuid, observed_at=None):
    """Read-only full result validation; SQL sample/source gates remain downstream."""
    result = extract_terminal_research_json(stdout)
    if _canonical(result) != _canonical(native_result):
        raise ResultBindingError("STDOUT_NATIVE_RESULT_DIFFERENT")
    workflow_id = native_result.get("workflow_run_id")
    if not isinstance(workflow_id, str) or not re.fullmatch(r"research:[0-9a-f]{32}", workflow_id):
        raise ResultBindingError("WORKFLOW_ID_INVALID")
    expected_log = (PROJECT / "data/trend_research_runs" /
                    (workflow_id.replace(":", "_") + ".json")).resolve()
    log_path = _inside_project(result.get("log_path", ""))
    if log_path != expected_log:
        raise ResultBindingError("AUTHORITATIVE_WORKFLOW_PATH_DIFFERENT")
    authoritative_raw = log_path.read_bytes()
    authoritative = extract_terminal_research_json(authoritative_raw.decode("utf-8-sig"))
    if _canonical(authoritative) != _canonical(result):
        raise ResultBindingError("CLI_AUTHORITATIVE_RESULT_DIFFERENT")
    if (claim.get("account_key") != ACCOUNT_KEY or claim.get("automatic_retry") is not False
            or any(claim.get(k) is not True for k in ("metadata_only", "no_model_calls", "no_media_calls"))
            or claim.get("plan_path") != str(plan_path) or claim.get("plan_sha256") != plan_sha
            or hashlib.sha256(plan_path.read_bytes()).hexdigest() != plan_sha):
        raise ResultBindingError("CLAIM_OR_PLAN_BINDING_DIFFERENT")
    if (identity.get("healthy") is not True or identity.get("status") != "active"
            or identity.get("account_key") != ACCOUNT_KEY
            or type(identity.get("profile_version")) is not int
            or identity["profile_version"] != PROFILE_VERSION
            or identity.get("expected_public_id") != PUBLIC_ID
            or identity.get("actual_public_id") != PUBLIC_ID):
        raise ResultBindingError("LIVE_IDENTITY_DIFFERENT")
    for value in (result, plan):
        if (value.get("account_key") != ACCOUNT_KEY or value.get("account_uuid") != expected_account_uuid
                or type(value.get("profile_version")) is not int
                or value["profile_version"] != PROFILE_VERSION):
            raise ResultBindingError("RESULT_OR_PLAN_IDENTITY_DIFFERENT")
    if result.get("legal_core_plan") != _plan_binding(plan_path, plan, plan_sha):
        raise ResultBindingError("LEGAL_PLAN_BINDING_DIFFERENT")
    claimed, identified, started, finished, observed = map(_instant, (
        claim.get("at_utc"), identity.get("at_utc"), result.get("started_at"),
        result.get("finished_at"), observed_at or now_utc()))
    if not claimed <= identified <= started <= finished <= observed:
        raise ResultBindingError("RESEARCH_ATTEMPT_TIME_DIFFERENT")
    if (finished - claimed).total_seconds() > LEASE_SECONDS:
        raise ResultBindingError("RESEARCH_ATTEMPT_TOO_LONG")
    if (any(type(result.get(k)) is not int or result[k] < 0 for k in COUNTERS)
            or not isinstance(result.get("video_records"), list)
            or not isinstance(result.get("collection_run_id"), str)):
        raise ResultBindingError("RESULT_COUNTS_OR_COLLECTION_INVALID")
    if not result["collection_run_id"] and (any(result[k] != 0 for k in COUNTERS) or result["video_records"]):
        raise ResultBindingError("EMPTY_COLLECTION_CONTRADICTS_DATA")
    if any(not isinstance(row, dict) or row.get("run_id") != result["collection_run_id"]
           for row in result["video_records"]):
        raise ResultBindingError("RESULT_CONTAINS_OTHER_BATCH")
    status = result.get("status")
    if status not in {"completed", "awaiting_media_analysis", "failed", "blocked"}:
        raise ResultBindingError("RESEARCH_RESULT_UNKNOWN_OR_PARTIAL")
    eligible = status in {"completed", "awaiting_media_analysis"}
    if eligible and (not result["collection_run_id"] or result["unique_videos"] < 1
                     or not isinstance(result.get("sample_gate"), dict)
                     or result["sample_gate"].get("passed") is not True):
        raise ResultBindingError("COMPLETE_RESULT_SAMPLE_NOT_PASSED")
    if status != "completed" and not isinstance(result.get("stopped_reason"), str):
        raise ResultBindingError("KNOWN_STOP_REASON_REQUIRED")
    if status != "completed" and not result["stopped_reason"].strip():
        raise ResultBindingError("KNOWN_STOP_REASON_REQUIRED")
    if status == "awaiting_media_analysis" and result["stopped_reason"] != "incomplete_source_media_analysis":
        raise ResultBindingError("MEDIA_WAIT_REASON_DIFFERENT")
    if result.get("stopped_reason") == "human_required" and not any(
            isinstance(stage, dict) and stage.get("stage") == "trend_collection"
            and stage.get("status") == "failed" and stage.get("message") == "human_required"
            for stage in result.get("stages", [])):
        raise ResultBindingError("HUMAN_REQUIRED_STAGE_NOT_CONFIRMED")
    if log_path.read_bytes() != authoritative_raw:
        raise ResultBindingError("AUTHORITATIVE_CHANGED_DURING_READ")
    return {"authoritative_full_result_equal": True,
            "authoritative_result_sha256": hashlib.sha256(authoritative_raw).hexdigest(),
            "plan_sha256": plan_sha, "workflow_run_id": workflow_id,
            "eligible_for_source_validation": eligible, "known_research_result": True}


def _bind_authoritative(native, *, plan_path, plan, plan_sha, identity):
    """Add the same final plan binding as the existing CLI, only to this new run."""
    workflow_id = native.get("workflow_run_id")
    if not isinstance(workflow_id, str) or not re.fullmatch(r"research:[0-9a-f]{32}", workflow_id):
        raise ResultBindingError("WORKFLOW_ID_INVALID")
    path = _inside_project(native.get("log_path", ""))
    expected = (PROJECT / "data/trend_research_runs" / (workflow_id.replace(":", "_") + ".json")).resolve()
    if path != expected or _instant(native.get("started_at")) < _instant(identity.get("at_utc")):
        raise ResultBindingError("NEW_NATIVE_RESEARCH_IDENTITY_INVALID")
    prior_raw = path.read_bytes()
    prior = extract_terminal_research_json(prior_raw.decode("utf-8-sig"))
    if _canonical(prior) != _canonical(native):
        raise ResultBindingError("NATIVE_AUTHORITATIVE_RESULT_DIFFERENT")
    final = {**native, "legal_core_plan": _plan_binding(plan_path, plan, plan_sha)}
    # The research workflow's newly created log is finalized once, as in the
    # original metadata CLI. Never write a different workflow or old batch.
    path.write_text(json.dumps(final, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return final, prior_raw


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        raise ValueError("usage: run_fresh_legal_collection_local_recovery_v1.py ROOT PLAN")
    root, plan_path = [Path(value).resolve() for value in args]
    if (not root.is_relative_to(PROJECT / "data/production_trials")
            or root == PROJECT / "data/production_trials"):
        raise ValueError("independent trial directory required")
    plan_path = _inside_project(plan_path)
    parent_binding = verify_continuation_parent(root, plan_path)
    plan_raw = plan_path.read_bytes()
    plan = extract_terminal_research_json(plan_raw.decode("utf-8-sig"))
    plan_sha = hashlib.sha256(plan_raw).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise FileExistsError("collection attempt directory already contains evidence")
    claim = {"at_utc": now_utc(), "user_quote": USER_QUOTE,
             "user_clarification": "是，采集法律号新数据后跑完整流程", "user_login_confirmation": "已登录",
             "account_key": ACCOUNT_KEY, "plan_path": str(plan_path), "plan_sha256": plan_sha,
             "historical_plan_is_search_seed_only": True, "metadata_only": True,
             "no_model_calls": True, "no_media_calls": True, "automatic_retry": False,
             "headless": False, "same_verified_browser_reused": True,
             "manual_verification_timeout_seconds": WAIT_SECONDS, "lease_seconds": LEASE_SECONDS,
             **parent_binding}
    # Exclusive creation precedes any browser/network action. A repeated call
    # cannot perform a second identity check or collection.
    save(root / "COLLECTION_CLAIM.json", claim)
    captured_out, captured_err = io.StringIO(), io.StringIO()
    submitted, native_result, validation, identity = False, None, None, None
    exit_code, terminal_stdout = 1, ""
    try:
        with redirect_stdout(captured_out), redirect_stderr(captured_err):
            service = AccountRuntimeService()
            context = service.resolve(ACCOUNT_KEY)
            if (context.account_key != ACCOUNT_KEY or context.profile.profile_version != PROFILE_VERSION
                    or context.binding.public_uid != PUBLIC_ID or context.account_uuid != plan.get("account_uuid")):
                raise IdentityFailed("bound_account_changed")
            request = request_from_legal_core_plan(plan, context.profile, headless=False,
                                                  manual_verification_seconds=WAIT_SECONDS)
            pages = estimate_douyin_planned_pages(request)
            if pages != plan["estimated_pages"] or not 1 <= pages <= 30:
                raise ResultBindingError("PLAN_PAGE_BOUND_DIFFERENT")
            with service.operation_lease(context, operation="fresh_legal_resume_collection",
                    daily_limit=90, cooldown_seconds=0, lock_seconds=LEASE_SECONDS):
                session = context.create_browser_session(headless=False)
                try:
                    checked = service.verify_identity(context, session=session)
                    identity = {"healthy": checked.healthy, "status": checked.status,
                                "account_key": context.account_key, "profile_version": context.profile.profile_version,
                                "expected_public_id": context.binding.public_uid,
                                "actual_public_id": checked.actual.public_uid if checked.actual else None,
                                "at_utc": now_utc(), "headless": False}
                    save(root / "LIVE_IDENTITY_CHECK.json", identity)
                    if (checked.healthy is not True or checked.status != "active"
                            or identity["actual_public_id"] != PUBLIC_ID):
                        raise IdentityFailed(checked.status)
                    provider = DouyinWebTrendProvider(session_factory=lambda _headless: session)
                    workflow = AccountVideoResearchWorkflow()
                    wait_for_research_clock_boundary(identity["at_utc"])
                    submitted = True
                    research = workflow.run(context.profile, provider, request,
                        policy=_build_policy(AUTHORIZATION, planned_pages=pages), max_content_candidates=60,
                        content_analysis_implementation="metadata_heuristic", resume_collection_run_id="",
                        local_media_manifest=None, run_local_toolchain=False)
                    native = research.to_dict()
                    save(root / "ORIGINAL_NATIVE_RESEARCH_RESULT.json", native)
                    native_result, original_raw = _bind_authoritative(native, plan_path=plan_path,
                        plan=plan, plan_sha=plan_sha, identity=identity)
                    with (root / "ORIGINAL_RESEARCH_LOG.json").open("xb") as handle:
                        handle.write(original_raw)
                    terminal_stdout = json.dumps(native_result, ensure_ascii=False, indent=2) + "\n"
                    validation = validate_result(stdout=terminal_stdout, native_result=native_result,
                        claim=claim, identity=identity, plan_path=plan_path, plan=plan, plan_sha=plan_sha,
                        expected_account_uuid=context.account_uuid)
                    if not validation["eligible_for_source_validation"]:
                        raise KnownCollectionFailed(native_result["stopped_reason"])
                    exit_code = 0 if native_result["status"] == "completed" else 1
                finally:
                    # Provider.stop and this owner cleanup are safe: the real
                    # BrowserSession.stop returns immediately when _proc is None.
                    session.stop()
    except KnownCollectionFailed:
        pass
    except IdentityFailed as exc:
        validation = None
        save(root / "COLLECTION_RESULT.json", {"status": "human_required", "reason": str(exc),
            "identity": identity, "new_model_calls": 0, "new_media_calls": 0,
            "collection_submitted": False, "automatic_retry": False})
    except Exception as exc:
        validation = None
        save(root / "COLLECTION_RESULT.json", {"status": "result_unknown" if submitted else "blocked",
            "reason": str(exc) if isinstance(exc, ResultBindingError) else type(exc).__name__,
            "exception_type": type(exc).__name__, "new_model_calls": 0, "new_media_calls": 0,
            "collection_submitted": submitted, "known_research_result": False,
            "automatic_retry": False, "original_request_redispatched": False})
    finally:
        (root / "COLLECTION.stdout.log").write_text(terminal_stdout, encoding="utf-8")
        (root / "COLLECTION.console.stdout.log").write_text(captured_out.getvalue(), encoding="utf-8")
        (root / "COLLECTION.stderr.log").write_text(captured_err.getvalue(), encoding="utf-8")
    if validation is not None:
        save(root / "COLLECTION_RESULT.json", {"status": native_result["status"], "exit_code": exit_code,
             "result": native_result, **validation, "new_model_calls": 0, "new_media_calls": 0,
             "collection_submitted": True, "original_request_redispatched": False, "automatic_retry": False})
    status = json.loads((root / "COLLECTION_RESULT.json").read_text(encoding="utf-8"))["status"]
    print(json.dumps({"root": str(root), "status": status,
                      "collection_run_id": native_result.get("collection_run_id") if native_result else None,
                      "new_model_calls": 0, "new_media_calls": 0}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
