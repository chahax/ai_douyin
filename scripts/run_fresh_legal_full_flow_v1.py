"""Authorized fresh-law background text run; no video/publish dispatch.

One durable job, one fresh collection, raw-evidenced MiniMax/DeepSeek calls,
and the existing generic director/performance/compiler coordinator. A crash or
unknown call is a reconcile stop, never an automatic restart of this process.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import base64
import json
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_capability_production_v5 as parent
from scripts import creative_capability_role_clients_v2 as clients
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as text_pipeline
from src.content_factory import creative_fresh_legal_source_v1 as source_prepare
from src.content_factory import creative_endpoint_feedback_coordinator_v5 as directors
from src.content_factory import creative_complete_production_coordinator_v4 as context_contract
from src.content_factory import creative_production_revision_loop_v3 as revisions
from src.content_factory import creative_shared_production_contract_v1 as shared
from src.content_factory import creative_studio_task_store_v1 as task_store
from src.operations_accounts import AccountRuntimeService

DEFAULT_ROOT = PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01"
GRANT_ID = "fresh_legal_full_flow_20261012_user_confirmed"
USER_QUOTE = "可以测试剧本完整流程了可以再次获取下平台信息了再后台运行"


class OriginalJobExists(RuntimeError):
    pass


def state(root, status, **value):
    control.write(root / "STATE.json", {"schema": "fresh_legal_background/v1", "status": status,
        "updated_at_utc": control.now(), "root": str(root), "media_dispatch_allowed": False,
        "creative_quality_passed": False, "automatic_transport_retry": False, **value})


def verify_files(files):
    for path, expected in files.items():
        if control.sha_file(path) != expected:
            raise ValueError("FRESH_JOB_FROZEN_FILE_CHANGED: " + str(path))


def load_job_freeze(root):
    """An explicit pre-dispatch code revision preserves the first freeze/scope."""
    original = control.read(root / "JOB_FREEZE.json")
    revision_path = root / "PRE_DISPATCH_FREEZE_REVISION.json"
    if not revision_path.exists():
        return original
    revision = control.read(revision_path)
    revised_path = root / "JOB_FREEZE_v2.json"
    if (revision["original_freeze_sha256"] != control.sha_file(root / "JOB_FREEZE.json")
        or revision["revised_freeze_sha256"] != control.sha_file(revised_path)):
        raise ValueError("pre-dispatch revision evidence changed")
    revised = control.read(revised_path)
    if any(revised[key] != original[key] for key in ("inherited", "models", "raw_parent_ordinals", "new_generation_calls")):
        raise ValueError("code revision cannot change inherited scope or spend")
    allowed = {str((PROJECT / p).resolve()) for p in (
        "src/content_factory/creative_fresh_legal_text_pipeline_v1.py", "scripts/run_fresh_legal_full_flow_v1.py")}
    if set(revised["files"]) != set(original["files"]):
        raise ValueError("code revision cannot change source membership")
    changes = {p for p in original["files"] if original["files"][p] != revised["files"][p]}
    if not changes or not changes.issubset(allowed) or sorted(changes) != revision["changed_paths"]:
        raise ValueError("unexpected pre-dispatch source change")
    return revised


def prepare(root, *, resource_config):
    root = Path(root).resolve()
    if root == PROJECT or not root.is_relative_to(PROJECT / "data/production_trials"):
        raise ValueError("independent trial root required")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "JOB_FREEZE.json").exists():
        freeze = load_job_freeze(root)
        verify_files(freeze["files"])
        return freeze
    rt = parent.runtime()
    ledger = control.read(rt.ledger)
    rt.check(ledger)
    parent.verify_loop_history(rt)
    inherited, original_receipts = parent.old.prior.inherited_known_parent(ledger, parent.ROOT)
    if inherited["calls_started"] != 520 or inherited["reported_tokens"] != 7964215:
        raise ValueError("latest inherited spend requires reconciliation")
    prior = resource_config.get("production_preferences", {}).get("prior_story_scope", {})
    old_script = control.read(parent.ROOT / "INPUT.json")["script"]
    if (prior.get("prior_script_sha256") != control.digest(old_script)
        or prior.get("full_prior_script") != old_script
        or prior.get("director_used") != 7 or prior.get("director_limit") != 7
        or prior.get("director_remaining") != 0):
        raise ValueError("prior 512 story and exhausted allowance must be frozen before fresh generation")
    scope = {"schema": "fresh_legal_background_scope/v1", "grant_id": GRANT_ID,
        "user_quote": USER_QUOTE, "user_clarification": "是，采集法律号新数据后跑完整流程",
        "new_source_required": True, "old_512_director_count_preserved": 7,
        "native_limits": {"theme": 3, "plan": 3, "draft": 3, "new_director": 3},
        "single_format_recovery_per_phase": True, "max_local_content_revisions": 2,
        "max_total_tokens": None, "new_media_submissions": 0, "publishing_authorized": False,
        "old_budget_reset": False, "automatic_transport_retry": False}
    control.write(root / "USER_SCOPE.json", scope, True)
    control.write(root / "RESOURCE_CONFIG.json", resource_config, True)
    grant = PROJECT / "data/creative_fresh_background_claims" / GRANT_ID / "CLAIM.json"
    control.write(grant, {"grant_id": GRANT_ID, "root": str(root),
        "scope_sha256": control.sha_file(root / "USER_SCOPE.json"), "parent_ledger_sha256": control.sha_file(rt.ledger)}, True)
    files = [p for folder in (PROJECT / "src", PROJECT / "scripts") for p in folder.rglob("*.py")]
    files += [root / "USER_SCOPE.json", root / "RESOURCE_CONFIG.json", grant]
    files += [PROJECT / "config/creative_provider_capabilities_20261012.json"]
    files += [Path(resource_config[key]) for key in ("reference_path", "standards_path", "legal_context_path", "provider_refresh_path", "core_plan_path")]
    files += [parent.ROOT / name for name in ("CALL_LEDGER.json", "AUTHORIZATION.json", "ANCHOR.json", "INPUT.json", "LOOP_STATE.json")]
    files += [parent.ROOT / row["receipt"] for row in ledger["calls"]]
    freeze = {"schema": "fresh_legal_job_freeze/v1", "inherited": inherited,
        "models": ledger["model_configs"], "files": {str(p.resolve()): control.sha_file(p) for p in files},
        "raw_parent_ordinals": [r["ordinal"] for r in original_receipts], "new_generation_calls": 0}
    control.write(root / "JOB_FREEZE.json", freeze, True)
    state(root, "prepared_waiting_account_gate", inherited_spend=inherited,
        required_new_source=True, old_director_remaining=0)
    return freeze


def spend_summary(runtime):
    current = runtime.summary()
    current["new_unknown_token_reservations"] = current["unknown_token_reservations"]
    current["inherited_unknown_token_reservations"] = runtime.inherited.get("unknown_token_reservations", 0)
    current["unknown_token_reservations"] += current["inherited_unknown_token_reservations"]
    current["historical_pending_ordinals"] = deepcopy(runtime.inherited.get("pending_ordinals", []))
    return current


def wait_for_account_gate(root, freeze, *, service_factory=AccountRuntimeService, sleeper=time.sleep):
    service = service_factory()
    deadline = time.monotonic() + 6 * 3600
    while True:
        verify_files(freeze["files"])
        context = service.resolve("account01")
        current = service.bindings.get_runtime_state(context.account_uuid)
        now = datetime.now(timezone.utc)
        ends = [datetime.fromisoformat(v) for v in (current.circuit_open_until,
            current.lock_expires_at if current.lock_owner else "") if v]
        future = [value for value in ends if value > now]
        if not future:
            return
        state(root, "waiting_account_protection", eligible_after_utc=max(future).isoformat(),
            new_model_calls=0, collection_submitted=False, failures_preserved=current.consecutive_failures)
        if time.monotonic() >= deadline:
            raise RuntimeError("ACCOUNT_GATE_WAIT_EXPIRED_NO_DISPATCH")
        sleeper(min(30, max(1, (max(future) - now).total_seconds())))


def verify_receipt_evidence(runtime, receipt, request):
    """Reconcile actual SDK capture before pure pipeline/format recovery sees it."""
    if receipt["request"] != request or receipt["request_sha256"] != control.digest(request):
        raise ValueError("actual request identity changed")
    identity_file = runtime.evidence_path(receipt["ordinal"]) / "IDENTITY.json"
    ident = control.read(identity_file)
    if ident["identity_sha256"] != control.digest(ident["identity"]) or ident["identity"] != runtime.evidence_identity(receipt):
        raise ValueError("original SDK identity mismatch")
    if receipt.get("call_evidence", {}).get("identity_sha256") != ident["identity_sha256"]:
        raise ValueError("receipt SDK identity mismatch")
    meta = receipt.get("response_metadata", {})
    if meta.get("response_body_complete") is True:
        manifest = control.read(identity_file.parent / "RESPONSE_BODY_MANIFEST.json")
        raw = (identity_file.parent / manifest["body_file"]).read_bytes()
        if (manifest["identity_sha256"] != ident["identity_sha256"] or manifest["body_complete"] is not True
                or control.sha_file(identity_file.parent / manifest["body_file"]) != manifest["stored_sha256"]
                or manifest["original_sha256"] != manifest["stored_sha256"]
                or manifest["original_sha256"] != meta.get("raw_body_sha256")
                or len(raw) != manifest["bytes"]
                or manifest["http_metadata"]["http_status_code"] != meta.get("http_status_code")):
            raise ValueError("original response manifest mismatch")
        if manifest.get("raw_bytes_preserved") is not True or manifest.get("credential_redacted"):
            raise ValueError("full original result unavailable for automatic acceptance")
        payload = control.strict_json(raw.decode("utf-8"))
        if payload != receipt.get("response_payload"):
            raise ValueError("captured response differs from parsed payload")
        total = meta.get("total_tokens")
        if type(total) is int and payload.get("usage", {}).get("total_tokens") != total:
            raise ValueError("original usage mismatch")
    return identity_file.parent


def call_phase(label, root):
    if label.startswith("fresh_theme_"): return "theme", 4
    if label.startswith("fresh_plan_"): return "plan", 4
    if label.startswith("fresh_draft_"): return "draft", 4
    if label.startswith("fresh_full_review_"): return "review", 4
    if label.startswith("whole_direction_"): return "direction", 3
    if label.startswith("whole_production_review_"): return "production_review", 3
    if label.startswith("performance_"):
        result = control.read(root / "TEXT_RESULT.json")
        refs = len(parent.old.source.catalog(result["script"]))
        return "performance", max(1, refs * 3 * 3)
    raise ValueError("stage outside frozen fresh scope")


def classify_receipt(receipt):
    meta = receipt.get("response_metadata", {})
    http, total = meta.get("http_status_code"), meta.get("total_tokens")
    known = (type(http) is int and 200 <= http < 300 and meta.get("response_body_complete") is True
        and meta.get("finish_reason") in ("stop", "tool_calls") and type(total) is int and total >= 0)
    if not known:
        return False, "unknown", "unknown"
    if receipt.get("status") == "contract_valid" and isinstance(receipt.get("document_output", receipt.get("output")), dict):
        return True, "completed", "accepted"
    failure = receipt.get("failure", {})
    if (receipt.get("status") == "contract_rejected" and failure.get("category") in ("validation", "state_contract")
        and failure.get("response_received") is True and isinstance(receipt.get("document_output", receipt.get("output")), dict)):
        return True, "content_rejected", "accepted"
    return True, "protocol_rejected", "missing" if failure.get("code") == "REQUIRED_TOOL_MISSING" else "rejected"


def make_invoke(root, runtime):
    """SQLite claims mirror actual runtime calls; no second provider dispatcher."""
    store = task_store.TaskStore(root / "TASKS.sqlite3")
    scope_path = root / "USER_SCOPE.json"
    def invoke(label, request, validator):
        clients.expected_wire_request(request)  # validate before recording a service attempt
        phase, maximum = call_phase(label, root)
        gid = "call_" + control.digest({"grant_id": GRANT_ID, "label": label})[:24]
        graph = {"schema_version": task_store.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
            {"node_id": "source", "kind": "source", "input": {"frozen_source_sha256": control.digest(control.read(runtime.ledger)["source_manifest"]),
                "request_sha256": control.digest(request)}, "depends_on": []},
            {"node_id": "result", "kind": "text", "input": {"label": label, "phase": phase}, "depends_on": ["source"]}]}
        store.register_graph(graph)
        auth = {"schema_version": task_store.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid,
            "node_ids": ["result"], "scope": "text", "purpose": "dispatch", "source_sha256": store.snapshot(gid)["source_sha256"],
            "max_attempts": maximum, "prior_attempts": 0, "allows_content_revision": False,
            "evidence_ref": str(scope_path) + "#" + phase, "evidence_sha256": control.sha_file(scope_path)}
        attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, auth)
        runtime.client_factory = lambda: clients.CapabilityRoleClients(expected_request=deepcopy(request))
        receipt = runtime.dispatch(label, request, validator)
        directory = verify_receipt_evidence(runtime, receipt, request)
        meta = receipt.get("response_metadata", {})
        raw_path = directory / "response_body.raw"
        raw = raw_path.read_bytes() if raw_path.exists() else b""
        http = meta.get("http_status_code")
        total = meta.get("total_tokens")
        known, outcome, tool_status = classify_receipt(receipt)
        store.accept_result(attempt["claim_id"], {"schema_version": task_store.RESULT_SCHEMA,
            "claim_id": attempt["claim_id"], "request_sha256": attempt["request_sha256"], "service_task_id": None,
            "outcome": outcome, "result_known": known, "usage_known": type(total) is int and total >= 0,
            "usage": {"unit": "reported_tokens", "amount": total} if type(total) is int and total >= 0 else None,
            "complete": meta.get("response_body_complete") is True,
            "complete_end": meta.get("finish_reason") in ("stop", "tool_calls"),
            "schema_tool_status": tool_status,
            "contract_valid": receipt["status"] == "contract_valid" if known else None,
            "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode("ascii"),
                "sha256": __import__("hashlib").sha256(raw).hexdigest(), "http_status": http if type(http) is int else None},
            "output": {"original_receipt": str(root / next(r["receipt"] for r in control.read(runtime.ledger)["calls"] if r["ordinal"] == receipt["ordinal"])),
                "receipt_sha256": control.digest(receipt), "native_output": receipt.get("document_output", receipt.get("output"))}})
        return receipt
    return invoke


def run(root):
    root = Path(root).resolve()
    freeze = load_job_freeze(root)
    verify_files(freeze["files"])
    # Persist once before waiting or network. Never clear this on a crash.
    try:
        with (root / "RUN_CLAIM.json").open("x", encoding="utf-8") as f:
            json.dump({"started_at_utc": control.now(), "pid": __import__("os").getpid(),
                "job_freeze_sha256": control.sha_file(root / ("JOB_FREEZE_v2.json" if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists() else "JOB_FREEZE.json")),
                "automatic_restart": False}, f)
    except FileExistsError as exc:
        raise OriginalJobExists("existing background run; inspect original result only") from exc
    wait_for_account_gate(root, freeze)
    resources = control.read(root / "RESOURCE_CONFIG.json")
    collection = root / "collection_live_01"
    state(root, "collecting_fresh_legal_metadata", new_model_calls=0)
    child = subprocess.run([sys.executable, "scripts/run_fresh_legal_collection_v1.py", str(collection), resources["core_plan_path"]],
        cwd=PROJECT, capture_output=True, text=True, encoding="utf-8")
    (root / "LIVE_COLLECTION.stdout.log").write_text(child.stdout, encoding="utf-8")
    (root / "LIVE_COLLECTION.stderr.log").write_text(child.stderr, encoding="utf-8")
    collected = control.read(collection / "COLLECTION_RESULT.json")
    if collected.get("status") not in ("completed", "awaiting_media_analysis"):
        return state(root, "awaiting_account_verification" if collected.get("status") == "human_required" else "collection_stopped",
            reason=collected.get("reason", collected.get("status")), original_collection_result=str(collection / "COLLECTION_RESULT.json"),
            new_model_calls=0, new_media_calls=0)
    requested_after = control.read(collection / "COLLECTION_CLAIM.json")["at_utc"]
    bundle = source_prepare.prepare_source_bundle(collect_result=collection / "COLLECTION_RESULT.json",
        trend_db=PROJECT / "data/trend_intelligence.db", profile_db=PROJECT / "data/douyin.db",
        reference_fulltext_path=resources["reference_path"], standards_path=resources["standards_path"],
        verified_legal_context_path=resources["legal_context_path"], now=control.now(), requested_after=requested_after,
        identity_check=collection / "LIVE_IDENTITY_CHECK.json")
    source_prepare.write_source_bundle(root / "source", bundle)
    verify_files(freeze["files"])
    runtime_sources = [Path(p) for p in freeze["files"] if Path(p).is_relative_to(PROJECT)]
    runtime_sources += [root / "JOB_FREEZE.json"] + [p for p in (root / "source").iterdir() if p.is_file()]
    if (root / "PRE_DISPATCH_FREEZE_REVISION.json").exists():
        runtime_sources += [root / "JOB_FREEZE_v2.json", root / "PRE_DISPATCH_FREEZE_REVISION.json"]
    runtime = control.ContinuationRuntime(PROJECT, root, runtime_sources, freeze["inherited"], freeze["models"],
        inherited_guard=lambda: verify_files(freeze["files"]), quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")
    runtime.prepare()
    invoke = make_invoke(root, runtime)
    reference = Path(resources["reference_path"]).read_bytes().decode("utf-8-sig")
    legal_context = control.read(resources["legal_context_path"])
    preferences, policy = resources["production_preferences"], resources["provider_evidence"]
    source_binding = control.digest(control.read(runtime.ledger)["source_manifest"])
    state(root, "fresh_theme_plan_script_running", selected_core=bundle["selected_core"], spend=spend_summary(runtime))
    pipeline = text_pipeline.FreshLegalTextPipeline(invoke=invoke,
        persist_state=lambda value: control.write(root / "TEXT_STATE.json", value),
        format_recovery_authorization={"authorized": True, "source_binding_sha256": source_binding,
            "evidence_ref": str(root / "USER_SCOPE.json"), "evidence_sha256": control.sha_file(root / "USER_SCOPE.json")})
    result = pipeline.run(packet=bundle["packet"], legal_context=legal_context, reference_fulltext=reference,
        expression_standards=control.read(resources["standards_path"]), production_preferences=preferences,
        provider_evidence=policy, source_binding_sha256=source_binding)
    control.write(root / "TEXT_RESULT.json", result, True)
    if result["status"] != "text_ready_for_director":
        return state(root, result["status"], stage="full_script", spend=spend_summary(runtime), selected_core=bundle["selected_core"])
    accepted = root / "ACCEPTED_TEXT_PENDING_DIRECTOR"
    accepted.mkdir(exist_ok=False)
    (accepted / "FULL_SCRIPT.md").write_text(text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
    material = {"full_current_script": result["script"], "shared_manifest": result["manifest"], "planned_initial_state": result["initial"]}
    loop = revisions.initial_loop_state([], source_binding_sha256=source_binding, default_limit=3, stable_scope_material=material)
    control.write(root / "INITIAL_LOOP_STATE.json", loop, True)
    state(root, "whole_direction_performance_running", title=result["script"]["title"], spend=spend_summary(runtime))
    coordinator = directors.EndpointFeedbackCoordinator(invoke=invoke,
        persist_state=lambda value: control.write(root / "LOOP_STATE.json", value),
        verify_frozen_source=lambda: verify_files(freeze["files"]),
        opening_context_builder=lambda performance: shared.compile_segment_context(result["manifest"], result["script"],
            result["shared_dynamic_initial"], performance["source_refs"], bootstrap=True),
        models=text_pipeline.MODEL_POLICY)
    full = coordinator.run(script=result["script"], manifest=result["manifest"], initial=result["initial"],
        reference_fulltext=reference, preferences=preferences, brief=result["brief"],
        source_review_binding=result["source_review_binding"], state=loop, scope=control.read(root / "USER_SCOPE.json"))
    control.write(root / "PRODUCTION_RESULT.json", full, True)
    if full["status"] == "complete_text_production_handoff_ready":
        out = root / "DELIVERABLE"
        out.mkdir(exist_ok=False)
        (out / "FULL_SCRIPT.md").write_text(text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
        control.write(out / "COMPLETE_PRODUCTION.json", full, True)
        lines = ["# 整片导演、表演与制作交接", "", "完整文本机器验收；图片/声线与视频内容仍需各自核实。", ""]
        for segment, prompt in zip(full["direction"]["segments"], full["planned_prompts"]):
            lines += ["## " + segment["segment_id"], json.dumps(segment, ensure_ascii=False, indent=2), "", prompt, ""]
        (out / "DIRECTOR_PERFORMANCE_HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")
    state(root, full["status"], reason=full.get("reason"), title=result["script"]["title"], spend=spend_summary(runtime),
        complete_text_handoff_ready=full.get("complete_text_handoff_ready", False),
        new_media_calls=0, user_video_review_required=True,
        deliverable=str(root / "DELIVERABLE") if (root / "DELIVERABLE").exists() else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--resources", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.resources is None: parser.error("prepare needs --resources")
        result = prepare(args.root, resource_config=control.read(args.resources))
        print(json.dumps({"status": "prepared", "root": str(args.root), "frozen_files": len(result["files"])}, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(control.read(args.root / "STATE.json"), ensure_ascii=False, indent=2))
    else:
        try:
            run(args.root)
        except OriginalJobExists:
            print(json.dumps({"status": "original_job_exists", "no_new_dispatch": True}))
            raise SystemExit(2)
        except Exception as exc:
            state(args.root, "stopped_exception", exception_type=type(exc).__name__,
                reason=str(exc)[:1200] if isinstance(exc, (ValueError, RuntimeError)) else "original local exception preserved by type",
                new_media_calls=0, inspect_original_request_only=True)
            raise


if __name__ == "__main__":
    main()
