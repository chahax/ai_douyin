"""One explicit continuation after a known, zero-sample human verification stop.

The original RUN_CLAIM and all source/call limits remain bound. This entry adds
one login-confirmed collection claim; it cannot restart a text/model run.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_fresh_legal_full_flow_v1 as original
from src.content_factory.creative_collection_cli_result_v1 import extract_terminal_research_json

control = original.control
DEFAULT_ROOT = original.DEFAULT_ROOT
FREEZE_NAME = "RESUME_FREEZE_01.json"
CLAIM_NAME = "RESUME_CLAIM_01.json"
CONFIRMATION_NAME = "USER_LOGIN_CONFIRMATION_01.json"
COLLECTION_NAME = "collection_live_02"
_CODE = ("scripts/run_fresh_legal_full_flow_resume_v1.py", "scripts/run_fresh_legal_collection_resume_v1.py",
    "src/content_factory/creative_collection_cli_result_v1.py")
_GENERATED = ("CALL_LEDGER.json", "AUTHORIZATION.json", "TEXT_STATE.json", "TEXT_RESULT.json",
    "LOOP_STATE.json", "INITIAL_LOOP_STATE.json", "PRODUCTION_RESULT.json", "TASKS.sqlite3",
    "source", "source_at_dispatch", "ACCEPTED_TEXT_PENDING_DIRECTOR", "DELIVERABLE")


class OriginalResumeExists(RuntimeError):
    pass


def _root(value):
    root = Path(value).resolve()
    trials = (PROJECT / "data/production_trials").resolve()
    if root == trials or not root.is_relative_to(trials):
        raise ValueError("independent original trial root required")
    return root


def _process_alive(pid):
    # psutil only reads process status; unlike os.kill on Windows it cannot send
    # a signal to an unrelated process that has reused this old PID.
    import psutil
    if type(pid) is not int or pid <= 0:
        raise ValueError("original process identity missing")
    try:
        return psutil.Process(pid).is_running()
    except psutil.NoSuchProcess:
        return False


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone-bound login confirmation required")
    return result.astimezone(timezone.utc)


def _assert_no_original_model_execution(root):
    unexpected = [name for name in _GENERATED if (root / name).exists()]
    unexpected += [p.name for p in root.glob("call_*.json")]
    if unexpected:
        raise ValueError("original model/source execution exists; inspect original results only")


def _addition_paths(root, confirmation, evidence):
    base_path = root / ("JOB_FREEZE_v2.json" if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists() else "JOB_FREEZE.json")
    helper = Path(confirmation["verification_window_root"]).resolve()
    paths = [root / "JOB_FREEZE.json", base_path, root / "RUN_CLAIM.json", root / CONFIRMATION_NAME,
        root / "collection_live_01/COLLECTION_RECONCILIATION.json", root / "collection_live_01/COLLECTION_RESULT.json",
        helper / "HUMAN_VERIFICATION_BROWSER_STATE.json", helper / "PROCESS.json",
        helper / "HUMAN_VERIFICATION_BROWSER_CLOSE.json"]
    if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists():
        paths.append(root / "PRE_DISPATCH_FREEZE_REVISION.json")
    return paths + [Path(p) for p in evidence]


def validate_known_human_stop(root, *, process_alive=_process_alive):
    """Read-only proof; a human statement does not mark machine identity passed."""
    root = _root(root)
    base = original.load_job_freeze(root)
    original.verify_files(base["files"])
    inherited = base["inherited"]
    if (inherited.get("calls_started") != 520 or inherited.get("reported_tokens") != 7964215
        or inherited.get("unknown_token_reservations") != 93117
        or inherited.get("pending_ordinals") != [70, 160] or base.get("new_generation_calls") != 0):
        raise ValueError("original inherited spend or unresolved history changed")
    scope = control.read(root / "USER_SCOPE.json")
    if (scope.get("grant_id") != original.GRANT_ID or scope.get("new_source_required") is not True
        or scope.get("old_512_director_count_preserved") != 7
        or scope.get("native_limits") != {"theme": 3, "plan": 3, "draft": 3, "new_director": 3}
        or scope.get("max_local_content_revisions") != 2
        or scope.get("single_format_recovery_per_phase") is not True
        or scope.get("max_total_tokens") is not None or scope.get("new_media_submissions") != 0
        or scope.get("old_budget_reset") is not False or scope.get("publishing_authorized") is not False
        or scope.get("automatic_transport_retry") is not False):
        raise ValueError("original user scope cannot change during login continuation")
    claim = control.read(root / "RUN_CLAIM.json")
    base_path = root / ("JOB_FREEZE_v2.json" if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists() else "JOB_FREEZE.json")
    if claim.get("job_freeze_sha256") != control.sha_file(base_path) or claim.get("automatic_restart") is not False:
        raise ValueError("original run claim no longer binds this freeze")
    if process_alive(claim.get("pid")):
        raise ValueError("original worker still active; reconcile instead of continuing")
    _assert_no_original_model_execution(root)
    if (root / COLLECTION_NAME).exists():
        raise ValueError("post-login collection already exists; never redispatch it")
    confirmation_path = root / CONFIRMATION_NAME
    confirmation = control.read(confirmation_path)
    reconciliation_path = root / "collection_live_01/COLLECTION_RECONCILIATION.json"
    if (confirmation.get("schema") != "fresh_legal_user_login_confirmation/v1"
        or confirmation.get("user_statement") != "已登录"
        or confirmation.get("account_key") != "account01"
        or confirmation.get("expected_public_id") != "dy4qyzku18yu"
        or confirmation.get("profile_version") != 1
        or confirmation.get("machine_identity_verified") is not False
        or confirmation.get("permits_one_post_verification_collection") is not True
        or confirmation.get("original_request_redispatch") is not False
        or confirmation.get("model_scope_changed") is not False
        or confirmation.get("media_allowed") is not False
        or confirmation.get("budget_reset") is not False
        or Path(confirmation.get("original_reconciliation_path", "")).resolve() != reconciliation_path.resolve()
        or confirmation.get("original_reconciliation_sha256") != control.sha_file(reconciliation_path)):
        raise ValueError("explicit bound login confirmation required")
    reconciliation = control.read(reconciliation_path)
    payload = reconciliation.get("result", {})
    if (reconciliation.get("status") != "human_required"
        or reconciliation.get("observed_research_status") != "failed"
        or reconciliation.get("reason") != "human_required"
        or reconciliation.get("authoritative_full_result_equal") is not True
        or reconciliation.get("account_key") != "account01"
        or reconciliation.get("profile_version") != 1
        or reconciliation.get("original_request_redispatched") is not False
        or reconciliation.get("automatic_retry") is not False
        or reconciliation.get("eligible_for_creative_source") is not False
        or reconciliation.get("new_model_calls") != 0 or reconciliation.get("new_media_calls") != 0
        or payload.get("status") != "failed" or payload.get("stopped_reason") != "human_required"
        or payload.get("collection_run_id") != "" or payload.get("video_records") != []
        or any(type(payload.get(k)) is not int or payload[k] != 0 for k in (
            "collected_observations", "unique_videos", "tag_relations", "tag_traffic_snapshots",
            "clusters", "briefs", "content_analyses", "opportunities"))):
        raise ValueError("only the known zero-sample human stop can continue")
    evidence = reconciliation.get("evidence_sha256", {})
    if not evidence or any(not Path(p).resolve().is_relative_to(PROJECT) for p in evidence):
        raise ValueError("bound original collection evidence required")
    original.verify_files(evidence)
    collected = root / "collection_live_01"
    stdout_payload = extract_terminal_research_json((collected / "COLLECTION.stdout.log").read_text(encoding="utf-8-sig"))
    workflow = payload.get("workflow_run_id", "")
    if not isinstance(workflow, str) or not re.fullmatch(r"research:[0-9a-f]{32}", workflow):
        raise ValueError("known original workflow identity required")
    authoritative_path = PROJECT / "data/trend_research_runs" / (workflow.replace(":", "_") + ".json")
    if (stdout_payload != payload or control.read(authoritative_path) != payload
        or str(authoritative_path.resolve()) not in evidence
        or reconciliation.get("workflow_run_id") != workflow
        or _time(confirmation["at_utc"]) <= _time(payload["finished_at"])):
        raise ValueError("full original service result or login chronology changed")
    resources = control.read(root / "RESOURCE_CONFIG.json")
    collection_claim_path, identity_path = collected / "COLLECTION_CLAIM.json", collected / "LIVE_IDENTITY_CHECK.json"
    collection_claim, identity = control.read(collection_claim_path), control.read(identity_path)
    plan_path = Path(resources["core_plan_path"]).resolve()
    required_evidence = {str(p.resolve()) for p in (
        authoritative_path, collected / "COLLECTION.stdout.log", collection_claim_path, identity_path, plan_path)}
    if (not required_evidence.issubset(evidence)
        or reconciliation.get("claim_sha256") != control.sha_file(collection_claim_path)
        or reconciliation.get("plan_sha256") != control.sha_file(plan_path)
        or collection_claim.get("plan_sha256") != control.sha_file(plan_path)
        or Path(collection_claim.get("plan_path", "")).resolve() != plan_path
        or collection_claim.get("account_key") != "account01"
        or collection_claim.get("metadata_only") is not True
        or collection_claim.get("no_model_calls") is not True or collection_claim.get("no_media_calls") is not True
        or collection_claim.get("automatic_retry") is not False
        or payload.get("account_uuid") != reconciliation.get("account_uuid")
        or payload.get("account_key") != "account01" or payload.get("profile_version") != 1
        or identity.get("healthy") is not True or identity.get("account_key") != "account01"
        or identity.get("expected_public_id") != "dy4qyzku18yu"
        or identity.get("actual_public_id") != "dy4qyzku18yu" or identity.get("profile_version") != 1):
        raise ValueError("original identity, plan or collection claim changed")
    helper = Path(confirmation.get("verification_window_root", "")).resolve()
    if helper.parent != root or not helper.name.startswith("verification_window_"):
        raise ValueError("login helper must be bound to original trial")
    helper_state_path = helper / "HUMAN_VERIFICATION_BROWSER_STATE.json"
    helper_process_path = helper / "PROCESS.json"
    helper_marker_path = helper / "HUMAN_VERIFICATION_BROWSER_CLOSE.json"
    helper_state = control.read(helper_state_path)
    if (helper_state.get("status") != "closed_after_operator_marker"
        or helper_state.get("verification_passed") is not None
        or helper_state.get("new_collection_requests") != 0
        or helper_state.get("new_model_calls") != 0
        or not helper_marker_path.is_file()
        or process_alive(control.read(helper_process_path).get("pid"))):
        raise ValueError("verification helper must save state and release profile before collection")
    files = deepcopy(base["files"])
    for path in _addition_paths(root, confirmation, evidence):
        files[str(path.resolve())] = control.sha_file(path)
    return base, files


def prepare(root, *, process_alive=_process_alive):
    root = _root(root)
    if (root / CLAIM_NAME).exists():
        raise OriginalResumeExists("existing continuation claim; inspect original results only")
    base, evidence = validate_known_human_stop(root, process_alive=process_alive)
    for name in _CODE:
        path = PROJECT / name
        if not path.is_file():
            raise ValueError("new continuation code not complete")
        evidence[str(path.resolve())] = control.sha_file(path)
    base_path = root / ("JOB_FREEZE_v2.json" if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists() else "JOB_FREEZE.json")
    value = {"schema": "fresh_legal_known_human_resume_freeze/v1", "original_grant_id": original.GRANT_ID,
        "original_freeze_path": str(base_path), "original_freeze_sha256": control.sha_file(base_path),
        "original_file_count": len(base["files"]), "inherited": deepcopy(base["inherited"]),
        "models": deepcopy(base["models"]), "raw_parent_ordinals": deepcopy(base["raw_parent_ordinals"]),
        "new_generation_calls": 0, "files": evidence,
        "login_confirmation_sha256": control.sha_file(root / CONFIRMATION_NAME),
        "original_reconciliation_sha256": control.sha_file(root / "collection_live_01/COLLECTION_RECONCILIATION.json"),
        "collection_directory": COLLECTION_NAME, "original_request_redispatch": False,
        "budget_reset": False, "automatic_restart": False, "new_media_submissions": 0}
    control.write(root / FREEZE_NAME, value, True)
    return value


def verify_resume_freeze(root):
    value = control.read(root / FREEZE_NAME)
    base = original.load_job_freeze(root)
    confirmation = control.read(root / CONFIRMATION_NAME)
    reconciliation_path = root / "collection_live_01/COLLECTION_RECONCILIATION.json"
    reconciliation = control.read(reconciliation_path)
    base_path = root / ("JOB_FREEZE_v2.json" if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists() else "JOB_FREEZE.json")
    required_paths = set(base["files"])
    required_paths.update(str(p.resolve()) for p in _addition_paths(root, confirmation, reconciliation["evidence_sha256"]))
    required_paths.update(str((PROJECT / p).resolve()) for p in _CODE)
    if (value.get("schema") != "fresh_legal_known_human_resume_freeze/v1"
        or value.get("original_grant_id") != original.GRANT_ID
        or Path(value.get("original_freeze_path", "")).resolve() != base_path.resolve()
        or value.get("original_freeze_sha256") != control.sha_file(base_path)
        or value.get("original_file_count") != len(base["files"])
        or any(value.get(k) != base[k] for k in ("inherited", "models", "raw_parent_ordinals", "new_generation_calls"))
        or value.get("collection_directory") != COLLECTION_NAME
        or value.get("original_request_redispatch") is not False or value.get("budget_reset") is not False
        or value.get("automatic_restart") is not False or value.get("new_media_submissions") != 0
        or value.get("login_confirmation_sha256") != control.sha_file(root / CONFIRMATION_NAME)
        or value.get("original_reconciliation_sha256") != control.sha_file(reconciliation_path)
        or set(value.get("files", {})) != required_paths
        or any(value["files"][p] != digest for p, digest in base["files"].items())):
        raise ValueError("additive freeze cannot alter original scope, sources or limits")
    original.verify_files(value["files"])
    if (root / CLAIM_NAME).exists():
        claim = control.read(root / CLAIM_NAME)
        if (claim.get("schema") != "fresh_legal_known_human_resume_claim/v1"
            or claim.get("resume_freeze_sha256") != control.sha_file(root / FREEZE_NAME)
            or claim.get("original_run_claim_sha256") != control.sha_file(root / "RUN_CLAIM.json")
            or claim.get("original_grant_id") != original.GRANT_ID
            or claim.get("login_confirmation_sha256") != value["login_confirmation_sha256"]
            or claim.get("automatic_restart") is not False or claim.get("budget_reset") is not False
            or claim.get("original_request_redispatch") is not False):
            raise ValueError("continuation claim no longer binds its additive freeze")
    return value


def run_text_and_production(root, freeze, collection):
    """Same v1 runtime, validators and coordinator, after the new-source gate."""
    _assert_no_original_model_execution(root)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    requested_after = control.read(collection / "COLLECTION_CLAIM.json")["at_utc"]
    bundle = original.source_prepare.prepare_source_bundle(collect_result=collection / "COLLECTION_RESULT.json",
        trend_db=PROJECT / "data/trend_intelligence.db", profile_db=PROJECT / "data/douyin.db",
        reference_fulltext_path=resources["reference_path"], standards_path=resources["standards_path"],
        verified_legal_context_path=resources["legal_context_path"], now=control.now(), requested_after=requested_after,
        identity_check=collection / "LIVE_IDENTITY_CHECK.json")
    original.source_prepare.write_source_bundle(root / "source", bundle)
    verify_resume_freeze(root)
    sources = [Path(p) for p in freeze["files"]]
    sources += [root / FREEZE_NAME, root / CLAIM_NAME]
    sources += [p for folder in (root / "source", collection) for p in folder.iterdir() if p.is_file()]
    runtime = control.ContinuationRuntime(PROJECT, root, sources, freeze["inherited"], freeze["models"],
        inherited_guard=lambda: verify_resume_freeze(root), quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")
    runtime.prepare()
    invoke = original.make_invoke(root, runtime)
    reference = Path(resources["reference_path"]).read_bytes().decode("utf-8-sig")
    legal = control.read(resources["legal_context_path"])
    preferences, policy = resources["production_preferences"], resources["provider_evidence"]
    source_binding = control.digest(control.read(runtime.ledger)["source_manifest"])
    original.state(root, "fresh_theme_plan_script_running", selected_core=bundle["selected_core"],
        spend=original.spend_summary(runtime), active_entry="known_human_resume/v1")
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
            selected_core=bundle["selected_core"], active_entry="known_human_resume/v1")
    accepted = root / "ACCEPTED_TEXT_PENDING_DIRECTOR"
    accepted.mkdir(exist_ok=False)
    (accepted / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
    material = {"full_current_script": result["script"], "shared_manifest": result["manifest"], "planned_initial_state": result["initial"]}
    loop = original.revisions.initial_loop_state([], source_binding_sha256=source_binding,
        default_limit=3, stable_scope_material=material)
    control.write(root / "INITIAL_LOOP_STATE.json", loop, True)
    original.state(root, "whole_direction_performance_running", title=result["script"]["title"],
        spend=original.spend_summary(runtime), active_entry="known_human_resume/v1")
    coordinator = original.directors.EndpointFeedbackCoordinator(invoke=invoke,
        persist_state=lambda value: control.write(root / "LOOP_STATE.json", value),
        verify_frozen_source=lambda: verify_resume_freeze(root),
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
        new_media_calls=0, user_video_review_required=True, active_entry="known_human_resume/v1",
        deliverable=str(root / "DELIVERABLE") if (root / "DELIVERABLE").exists() else None)


def run(root, *, process_alive=_process_alive):
    root = _root(root)
    if (root / CLAIM_NAME).exists():
        raise OriginalResumeExists("existing continuation claim; inspect original results only")
    validate_known_human_stop(root, process_alive=process_alive)
    freeze = verify_resume_freeze(root)
    # An explicit new claim precedes both account waiting and any network work.
    try:
        with (root / CLAIM_NAME).open("x", encoding="utf-8") as f:
            json.dump({"schema": "fresh_legal_known_human_resume_claim/v1", "started_at_utc": control.now(),
                "pid": os.getpid(), "resume_freeze_sha256": control.sha_file(root / FREEZE_NAME),
                "original_run_claim_sha256": control.sha_file(root / "RUN_CLAIM.json"),
                "original_grant_id": original.GRANT_ID, "login_confirmation_sha256": freeze["login_confirmation_sha256"],
                "original_request_redispatch": False, "automatic_restart": False, "budget_reset": False}, f, indent=2)
    except FileExistsError as exc:
        raise OriginalResumeExists("another continuation claim already exists; no dispatch") from exc
    original.wait_for_account_gate(root, freeze)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    collection = root / COLLECTION_NAME
    original.state(root, "collecting_fresh_legal_metadata", new_model_calls=0, new_media_calls=0,
        active_entry="known_human_resume/v1", collection_directory=str(collection), original_claim_preserved=True)
    child = subprocess.run([sys.executable, "scripts/run_fresh_legal_collection_resume_v1.py",
        str(collection), resources["core_plan_path"]], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8")
    control.write(root / "RESUME_COLLECTION_PROCESS_RESULT_01.json", {"exit_code": child.returncode,
        "finished_at_utc": control.now(), "original_request_redispatch": False, "automatic_retry": False}, True)
    with (root / "RESUME_COLLECTION.stdout.log").open("x", encoding="utf-8") as f:
        f.write(child.stdout)
    with (root / "RESUME_COLLECTION.stderr.log").open("x", encoding="utf-8") as f:
        f.write(child.stderr)
    collected = control.read(collection / "COLLECTION_RESULT.json")
    if collected.get("status") not in ("completed", "awaiting_media_analysis"):
        return original.state(root, "awaiting_account_verification" if collected.get("status") == "human_required" else "collection_stopped",
            reason=collected.get("reason", collected.get("status")), original_collection_result=str(collection / "COLLECTION_RESULT.json"),
            new_model_calls=0, new_media_calls=0, active_entry="known_human_resume/v1",
            automatic_restart=False, original_claim_preserved=True)
    if child.returncode != collected.get("exit_code"):
        raise ValueError("saved collection exit code differs from actual child process")
    return run_text_and_production(root, freeze, collection)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(control.read(args.root / "STATE.json"), ensure_ascii=False, indent=2))
        return
    try:
        if args.command == "prepare":
            value = prepare(args.root)
            print(json.dumps({"status": "known_human_resume_prepared", "root": str(args.root),
                "frozen_files": len(value["files"]), "new_dispatches": 0}, ensure_ascii=False))
        else:
            run(args.root)
    except OriginalResumeExists:
        print(json.dumps({"status": "original_resume_exists", "no_new_dispatch": True}))
        raise SystemExit(2)
    except Exception as exc:
        if args.command == "run" and (args.root / CLAIM_NAME).exists():
            original.state(args.root, "stopped_exception", exception_type=type(exc).__name__,
                reason=str(exc)[:1200] if isinstance(exc, (ValueError, RuntimeError)) else "original local exception preserved by type",
                new_media_calls=0, active_entry="known_human_resume/v1", inspect_original_request_only=True)
        raise


if __name__ == "__main__":
    main()
