"""Explicit same-source continuation of a known complete missing-tool plan.

Original source, receipts and spend stay bound. New operator files have their
own additive freeze. This entry cannot restart a claimed worker or submit media.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import base64
import json
import os
import sqlite3
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_fresh_legal_full_flow_v1 as original
from scripts import run_fresh_legal_full_flow_sample_extension_v1 as extension

VERSION = "fresh_legal_compact_continuation/v1"
OPERATOR_DIR = "compact_continuation_01"
FREEZE = "OPERATOR_FREEZE.json"
CLAIM = "RUN_CLAIM.json"
SEED = "VERIFIED_FORMAT_SEED_524.json"
PREFIX_ORDINALS = [521, 522, 523, 524]
SOURCE_BINDING = "50bfa8e7bcecae2348186551d9dcc323115ba02e9dfcfa5ac8cce164f231a181"
OPERATOR_FILES = (
    "scripts/run_fresh_legal_compact_continuation_v1.py",
    "src/content_factory/creative_compact_legal_context_v1.py",
    "src/content_factory/creative_known_plan_continuation_v1.py",
    "docs/CREATIVE_FRESH_LEGAL_COMPACT_CONTINUATION_PLAN_20261012.md",
)


class ContinuationAlreadyClaimed(RuntimeError):
    pass


def location(root):
    root = Path(root).resolve()
    if root != original.DEFAULT_ROOT.resolve():
        raise ValueError("this continuation is bound to the original legal batch")
    return root, root / OPERATOR_DIR


def verified_sdk_evidence(runtime, receipt, request):
    directory = original.verify_receipt_evidence(runtime, receipt, request)
    manifest = control.read(directory / "REQUEST_BODY_MANIFEST.json")
    proof = control.read(directory / "CAPABILITY_PREFLIGHT.json")
    raw_path = directory / manifest["body_file"]
    raw = raw_path.read_bytes()
    ident = receipt["call_evidence"]["identity_sha256"]
    expected = original.clients.expected_wire_request(request)
    actual = control.strict_json(raw.decode("utf-8"))
    if (manifest.get("identity_sha256") != ident or manifest.get("body_complete") is not True
        or manifest.get("raw_bytes_preserved") is not True or manifest.get("credential_redacted") is not False
        or manifest.get("stored_sha256") != control.sha_file(raw_path)
        or manifest.get("original_sha256") != manifest["stored_sha256"]
        or manifest.get("bytes") != len(raw) or manifest.get("original_bytes") != len(raw)
        or actual != expected or proof.get("identity_sha256") != ident
        or proof.get("logical_request_sha256") != control.digest(request)
        or proof.get("expected_wire_sha256") != control.digest(expected)
        or proof.get("actual_wire_sha256") != control.digest(actual)
        or proof.get("original_body_sha256") != control.sha_file(raw_path)
        or proof.get("actual_request_body_sha256") != control.sha_file(raw_path)
        or proof.get("body_bytes") != len(raw)
        or proof.get("full_wire_equals_mapped_logical_request") is not True
        or proof.get("messages_sha256") != control.digest(request["messages"])
        or proof.get("structured_schema_sha256") != control.digest(request["structured_schema"])
        or proof.get("schema") != original.clients.VERSION + "/outbound_capability_proof"
        or proof.get("status") != "capability_preflight_passed"
        or proof.get("dispatch_before_verify") is not False
        or type(proof.get("SDK_max_retries")) is not int or proof["SDK_max_retries"] != 0
        or proof.get("HTTP_follow_redirects") is not False
        or proof.get("endpoint_method") != "POST" or proof.get("endpoint_path") != "/v1/chat/completions"
        or proof.get("provider_endpoint_host_matched") is not True
        or proof.get("automatic_retry") is not False):
        raise ValueError("actual SDK request body or preflight evidence changed")
    return directory


def original_runtime(root, ledger, guard=lambda: None):
    return control.ContinuationRuntime(PROJECT, root,
        [PROJECT / path for path in ledger["source_manifest"]], ledger["starting_spend"],
        ledger["model_configs"], inherited_guard=guard, quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")


def verify_known_task_history(root, receipts):
    """A TaskStore claim without its recorded result must not be replayed."""
    database = (root / "TASKS.sqlite3").resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT graph_id,status,request,result,claim_id,request_sha,result_sha FROM attempts ORDER BY rowid").fetchall()
    if len(rows) != len(receipts):
        raise ValueError("unreconciled or missing durable task attempt")
    for row, receipt in zip(rows, receipts):
        graph, status, request_text, result_text, claim_id, request_sha, result_sha = row
        gid = "call_" + control.digest({"grant_id": original.GRANT_ID, "label": receipt["label"]})[:24]
        if not result_text:
            raise ValueError("durable task result unknown")
        request, result = control.strict_json(request_text), control.strict_json(result_text)
        known, outcome, _ = original.classify_receipt(receipt)
        if (graph != gid or request != {"provider_id": receipt["request"]["model"], "payload": receipt["request"]}
            or request_sha != control.digest(request) or result_sha != control.digest(result)
            or result.get("claim_id") != claim_id or result.get("request_sha256") != request_sha
            or not known or status != outcome or result.get("outcome") != outcome
            or result.get("result_known") is not True or result.get("usage_known") is not True
            or result.get("complete") is not True or result.get("complete_end") is not True
            or result.get("usage") != {"unit": "reported_tokens", "amount": receipt["response_metadata"]["total_tokens"]}
            or result.get("output", {}).get("receipt_sha256") != control.digest(receipt)):
            raise ValueError("durable task result differs from original receipt")


def validate_stop(root, *, check_worker=True):
    root, directory = location(root)
    extension.verify_sample_extension_freeze(root)
    ledger = control.read(root / "CALL_LEDGER.json")
    runtime = original_runtime(root, ledger)
    runtime.check(ledger)
    if ([row["ordinal"] for row in ledger["calls"]] != PREFIX_ORDINALS
        or control.digest(ledger["source_manifest"]) != SOURCE_BINDING
        or ledger["starting_spend"]["calls_started"] != 520
        or ledger["starting_spend"]["reported_tokens"] != 7964215):
        raise ValueError("original ledger stop or inherited consumption changed")
    if check_worker:
        for name in ("RUN_CLAIM.json", "RESUME_CLAIM_01.json", "LOCAL_DISPATCH_RECOVERY_CLAIM_01.json",
                     extension.CLAIM_NAME):
            path = root / name
            if path.exists() and extension.previous_worker_instance_active(control.read(path)):
                raise ValueError("original worker instance still active")
    stopped = control.read(root / "TEXT_STATE.json")
    result = control.read(root / "TEXT_RESULT.json")
    if (stopped != result or stopped.get("status") != "halt_required_tool_missing"
        or stopped.get("original_ordinal") != 524 or stopped.get("source_binding_sha256") != SOURCE_BINDING
        or stopped.get("versions") != {"theme": 2, "plan": 2, "draft": 0}
        or stopped.get("limits") != {"theme": 3, "plan": 3, "draft": 3}
        or stopped.get("format_recovery_claims") != {}):
        raise ValueError("known stopped pipeline contract changed")
    receipts = [control.read(root / row["receipt"]) for row in ledger["calls"]]
    if stopped["receipts"] != receipts:
        raise ValueError("original state receipt prefix differs")
    for receipt in receipts:
        if not original.text_pipeline._known_complete(receipt, receipt["request"], SOURCE_BINDING):
            raise ValueError("known complete original result and usage required")
        verified_sdk_evidence(runtime, receipt, receipt["request"])
    verify_known_task_history(root, receipts)
    if (receipts[-1].get("failure", {}).get("code") != "REQUIRED_TOOL_MISSING"
        or receipts[-1].get("response_metadata", {}).get("finish_reason") != "stop"
        or receipts[1].get("status") != "contract_valid"
        or stopped.get("native_theme") != receipts[1].get("document_output", receipts[1].get("output"))):
        raise ValueError("original accepted theme and known missing-tool stop required")
    for name in ("ACCEPTED_TEXT_PENDING_DIRECTOR", "DELIVERABLE", "INITIAL_LOOP_STATE.json", "LOOP_STATE.json"):
        if (root / name).exists():
            raise ValueError("later production already exists; no new clean start")
    return ledger, stopped, receipts[-1], runtime


def modules():
    from src.content_factory import creative_compact_legal_context_v1 as compact
    from src.content_factory import creative_known_plan_continuation_v1 as continuation
    return compact, continuation


def inputs(root):
    resources = control.read(root / "RESOURCE_CONFIG.json")
    return {"packet": control.read(root / "source/SOURCE_PACKET.json"),
        "legal_context": control.read(resources["legal_context_path"]),
        "reference_fulltext": Path(resources["reference_path"]).read_bytes().decode("utf-8-sig"),
        "expression_standards": control.read(resources["standards_path"]),
        "production_preferences": resources["production_preferences"],
        "provider_evidence": resources["provider_evidence"], "source_binding_sha256": SOURCE_BINDING}


def required_files(root, ledger):
    _, directory = location(root)
    paths = [PROJECT / p for p in OPERATOR_FILES]
    paths += [root / "TEXT_STATE.json", root / "TEXT_RESULT.json", directory / "ORIGINAL_LEDGER_SNAPSHOT.json",
        directory / SEED, directory / "COMPACT_CONTEXT_PREVIEW.json", directory / "COMPACT_PLAN_PAYLOAD_PREVIEW.json",
        directory / "PROJECTION_EVIDENCE.json"]
    runtime = original_runtime(root, ledger)
    for call in ledger["calls"][:4]:
        paths.append(root / call["receipt"])
        paths.extend(p for p in runtime.evidence_path(call["ordinal"]).iterdir() if p.is_file())
    return {str(p.resolve()) for p in paths}


def execution_symbols():
    value = extension.execution_resource_symbols()
    return {"allowed_python_executables": value["allowed_python_executables"],
        "worker_script": str(Path(__file__).resolve())}


def prepare(root):
    root, directory = location(root)
    if (directory / CLAIM).exists():
        raise ContinuationAlreadyClaimed("continuation claim consumed; inspect original result")
    if (directory / FREEZE).exists():
        return verify_operator(root)
    ledger, stopped, failed, runtime = validate_stop(root)
    compact, continuation = modules()
    values = inputs(root)
    context = compact.compact_context(**{k: v for k, v in values.items() if k != "provider_evidence"}, now=control.now())
    seed = continuation.compile_missing_tool_seed(failed,
        receipt_bytes=(root / ledger["calls"][-1]["receipt"]).read_bytes(),
        evidence_directory=runtime.evidence_path(524), expected_receipt_sha256=ledger["calls"][-1]["receipt_sha256"],
        expected_source_binding_sha256=SOURCE_BINDING,
        expected_wire=original.clients.expected_wire_request(failed["request"]),
        verifier=lambda receipt, request: verified_sdk_evidence(runtime, receipt, request))
    directory.mkdir(exist_ok=False)
    control.write(directory / "ORIGINAL_LEDGER_SNAPSHOT.json", ledger, True)
    control.write(directory / SEED, seed, True)
    control.write(directory / "COMPACT_CONTEXT_PREVIEW.json", context, True)
    failed_payload = control.strict_json(failed["request"]["messages"][1]["content"])
    projected_payload = compact.compact_payload(failed_payload, SOURCE_BINDING, now=control.now())
    control.write(directory / "COMPACT_PLAN_PAYLOAD_PREVIEW.json", projected_payload, True)
    control.write(directory / "PROJECTION_EVIDENCE.json",
        compact.payload_projection_evidence(failed_payload, projected_payload, SOURCE_BINDING, now=control.now()), True)
    files = {p: control.sha_file(p) for p in required_files(root, ledger)}
    symbols = execution_symbols()
    freeze = {"schema": VERSION + "/freeze", "at_utc": control.now(), "files": files,
        "original_grant_id": original.GRANT_ID, "source_binding_sha256": SOURCE_BINDING,
        "original_source_manifest": ledger["source_manifest"], "original_calls_prefix": ledger["calls"],
        "original_ledger_static": {k: v for k, v in ledger.items() if k != "calls"},
        "original_versions": stopped["versions"], "original_limits": stopped["limits"],
        "format_recovery_original_ordinal": 524, "format_recovery_maximum": 1,
        "format_recovery_is_additional_to_native_version_limit": True,
        "new_media_calls": 0, "automatic_restart": False, "old_budget_reset": False,
        "execution_resource_symbols": symbols,
        "external_resource_hashes": {p: control.sha_file(p) for p in symbols["allowed_python_executables"]}}
    control.write(directory / FREEZE, freeze, True)
    return freeze


def verify_operator(root):
    root, directory = location(root)
    freeze = control.read(directory / FREEZE)
    extension.verify_sample_extension_freeze(root)
    snapshot = control.read(directory / "ORIGINAL_LEDGER_SNAPSHOT.json")
    symbols = execution_symbols()
    if (set(freeze.get("files", {})) != required_files(root, snapshot)
        or freeze.get("original_source_manifest") != snapshot["source_manifest"]
        or control.digest(snapshot["source_manifest"]) != SOURCE_BINDING
        or [r["ordinal"] for r in snapshot["calls"]] != PREFIX_ORDINALS
        or freeze.get("original_calls_prefix") != snapshot["calls"]
        or freeze.get("original_ledger_static") != {k: v for k, v in snapshot.items() if k != "calls"}
        or freeze.get("original_versions") != {"theme": 2, "plan": 2, "draft": 0}
        or freeze.get("original_limits") != {"theme": 3, "plan": 3, "draft": 3}
        or freeze.get("execution_resource_symbols") != symbols
        or set(freeze.get("external_resource_hashes", {})) != set(symbols["allowed_python_executables"])):
        raise ValueError("additive operator freeze membership, bounds or execution resources changed")
    original.verify_files(freeze["files"])
    original.verify_files(freeze["external_resource_hashes"])
    ledger = control.read(root / "CALL_LEDGER.json")
    if (freeze.get("schema") != VERSION + "/freeze" or freeze.get("source_binding_sha256") != SOURCE_BINDING
        or freeze.get("original_grant_id") != original.GRANT_ID
        or freeze.get("format_recovery_original_ordinal") != 524
        or type(freeze.get("format_recovery_maximum")) is not int or freeze["format_recovery_maximum"] != 1
        or freeze.get("format_recovery_is_additional_to_native_version_limit") is not True
        or freeze.get("new_media_calls") != 0 or freeze.get("automatic_restart") is not False
        or freeze.get("old_budget_reset") is not False
        or {k: v for k, v in ledger.items() if k != "calls"} != freeze["original_ledger_static"]
        or ledger["calls"][:4] != freeze["original_calls_prefix"]
        or len(ledger["calls"]) < 4):
        raise ValueError("same-source operator or immutable ledger prefix changed")
    return freeze


def verify_worker(root, freeze):
    import psutil
    root, directory = location(root)
    claim = control.read(directory / CLAIM)
    symbols = freeze["execution_resource_symbols"]
    if (claim.get("schema") != VERSION + "/claim" or claim.get("pid") != os.getpid()
        or claim.get("operator_freeze_sha256") != control.sha_file(directory / FREEZE)
        or claim.get("source_binding_sha256") != SOURCE_BINDING
        or claim.get("automatic_restart") is not False or claim.get("old_budget_reset") is not False):
        raise ValueError("current worker claim differs")
    process = psutil.Process(os.getpid())
    args = process.cmdline()
    timestamp = datetime.fromisoformat(claim["started_at_utc"]).timestamp()
    if (not process.is_running() or str(Path(process.exe()).resolve()) not in symbols["allowed_python_executables"]
        or Path(process.exe()).resolve() != Path(sys._base_executable).resolve()
        or not 0 <= timestamp - process.create_time() <= 300
        or len(args) < 2 or Path(args[1]).resolve() != Path(symbols["worker_script"])):
        raise ValueError("current worker interpreter/entry/process instance differs")


def stage(label, result_path):
    if label.startswith("performance_"):
        verify_accepted_text_binding(Path(result_path).parent)
        result = control.read(result_path)
        if result.get("status") != "text_ready_for_director":
            raise ValueError("complete accepted text required before local performance")
        refs = len(original.parent.old.source.catalog(result["script"]))
        return "performance", max(1, refs * 3 * 3)
    return original.call_phase(label, Path(result_path).parent)


def verify_accepted_text_binding(directory, expected=None):
    binding = control.read(directory / "ACCEPTED_TEXT_BINDING.json")
    result = control.read(directory / "TEXT_RESULT.json")
    if (binding.get("schema") != VERSION + "/accepted_text_binding"
        or binding.get("source_binding_sha256") != SOURCE_BINDING
        or binding.get("text_result_file_sha256") != control.sha_file(directory / "TEXT_RESULT.json")
        or binding.get("script_sha256") != control.digest(result.get("script"))
        or binding.get("source_review_binding") != result.get("source_review_binding")
        or result.get("status") != "text_ready_for_director"
        or (expected is not None and binding != expected)):
        raise ValueError("accepted complete text binding changed")
    return binding


def bind_accepted_text(root, directory, result):
    values = inputs(root)
    brief, plan, script = result["brief"], result["compiled_plan"], result["script"]
    if (brief.get("prior_story_scope") != values["production_preferences"]["prior_story_scope"]
        or original.text_pipeline.contract.compile_script(result["native_script"], brief) != script):
        raise ValueError("accepted full script or inherited prior story scope changed")
    review = result["full_review"]
    original.text_pipeline.validate_review(review, script, brief, plan, values["legal_context"])
    decision = original.text_pipeline.decide_review(review, script, brief, plan, values["legal_context"])
    if decision != result["automatic_decision"] or decision["status"] != "text_ready_for_director":
        raise ValueError("same-source full review and new-story scope must pass")
    ledger = control.read(root / "CALL_LEDGER.json")
    runtime = original_runtime(root, ledger)
    runtime.check(ledger)
    review_binding = result["source_review_binding"]
    for kind, native_field, phase, role in (("writer", "native_script", "draft", "writer"),
                                           ("review", "full_review", "review", "director")):
        ordinal = review_binding[kind + "_ordinal"]
        rows = [row for row in ledger["calls"] if row["ordinal"] == ordinal]
        if len(rows) != 1:
            raise ValueError("accepted text must bind one actual service result")
        receipt = control.read(root / rows[0]["receipt"])
        if (receipt.get("status") != "contract_valid" or receipt.get("source_binding_sha256") != SOURCE_BINDING
            or not original.text_pipeline._known_complete(receipt, receipt["request"], SOURCE_BINDING)
            or receipt["request"].get("role") != role
            or receipt["request"].get("input_provenance", {}).get("phase") != phase
            or control.digest(receipt) != review_binding[kind + "_receipt_sha256"]
            or receipt.get("document_output", receipt.get("output")) != result[native_field]):
            raise ValueError("accepted text service identity or complete native result changed")
        verified_sdk_evidence(runtime, receipt, receipt["request"])
    if (review_binding["writer_ordinal"] >= review_binding["review_ordinal"]
        or review_binding.get("script_sha256") != control.digest(script)
        or review_binding.get("production_context_sha256") != original.text_pipeline.coordinator.production_context_digest(
            brief, values["reference_fulltext"], values["production_preferences"])
        or review_binding.get("machine_text_review_passed") is not True):
        raise ValueError("accepted whole-text review context binding changed")
    binding = {"schema": VERSION + "/accepted_text_binding", "source_binding_sha256": SOURCE_BINDING,
        "text_result_file_sha256": control.sha_file(directory / "TEXT_RESULT.json"), "script_sha256": control.digest(script),
        "source_review_binding": result["source_review_binding"], "human_adopted": False, "video_content_passed": False}
    control.write(directory / "ACCEPTED_TEXT_BINDING.json", binding, True)
    return binding


def make_invoke(root, runtime, result_path):
    """Same SDK/TaskStore path, with an explicit accepted text result location."""
    store = original.task_store.TaskStore(root / "TASKS.sqlite3")
    scope_path = root / "USER_SCOPE.json"
    def invoke(label, request, validator):
        runtime.inherited_guard()
        ledger = control.read(runtime.ledger)
        runtime.check(ledger)
        verify_known_task_history(root, [control.read(root / row["receipt"]) for row in ledger["calls"]])
        original.clients.expected_wire_request(request)
        phase, maximum = stage(label, result_path)
        gid = "call_" + control.digest({"grant_id": original.GRANT_ID, "label": label})[:24]
        graph = {"schema_version": original.task_store.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
            {"node_id": "source", "kind": "source", "input": {
                "frozen_source_sha256": control.digest(control.read(runtime.ledger)["source_manifest"]),
                "request_sha256": control.digest(request)}, "depends_on": []},
            {"node_id": "result", "kind": "text", "input": {"label": label, "phase": phase}, "depends_on": ["source"]}]}
        store.register_graph(graph)
        auth = {"schema_version": original.task_store.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid,
            "node_ids": ["result"], "scope": "text", "purpose": "dispatch", "source_sha256": store.snapshot(gid)["source_sha256"],
            "max_attempts": maximum, "prior_attempts": 0, "allows_content_revision": False,
            "evidence_ref": str(scope_path) + "#" + phase, "evidence_sha256": control.sha_file(scope_path)}
        attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, auth)
        runtime.client_factory = lambda: original.clients.CapabilityRoleClients(expected_request=deepcopy(request))
        receipt = runtime.dispatch(label, request, validator)
        evidence = verified_sdk_evidence(runtime, receipt, request)
        meta = receipt.get("response_metadata", {})
        raw_path = evidence / "response_body.raw"
        raw = raw_path.read_bytes() if raw_path.exists() else b""
        http, total = meta.get("http_status_code"), meta.get("total_tokens")
        known, outcome, tool_status = original.classify_receipt(receipt)
        store.accept_result(attempt["claim_id"], {"schema_version": original.task_store.RESULT_SCHEMA,
            "claim_id": attempt["claim_id"], "request_sha256": attempt["request_sha256"], "service_task_id": None,
            "outcome": outcome, "result_known": known, "usage_known": type(total) is int and total >= 0,
            "usage": {"unit": "reported_tokens", "amount": total} if type(total) is int and total >= 0 else None,
            "complete": meta.get("response_body_complete") is True,
            "complete_end": meta.get("finish_reason") in ("stop", "tool_calls"), "schema_tool_status": tool_status,
            "contract_valid": receipt["status"] == "contract_valid" if known else None,
            "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode("ascii"),
                "sha256": __import__("hashlib").sha256(raw).hexdigest(), "http_status": http if type(http) is int else None},
            "output": {"original_receipt": str(root / next(row["receipt"] for row in control.read(runtime.ledger)["calls"]
                if row["ordinal"] == receipt["ordinal"])), "receipt_sha256": control.digest(receipt),
                "native_output": receipt.get("document_output", receipt.get("output"))}})
        return receipt
    return invoke


def record(directory, status, **values):
    control.write(directory / "STATE.json", {"schema": VERSION + "/state", "status": status,
        "at_utc": control.now(), "new_media_calls": 0, "creative_quality_passed": False,
        "automatic_transport_retry": False, "old_budget_reset": False, **values})


def production_tail(root, directory, runtime, invoke, result):
    verify_accepted_text_binding(directory)
    values = inputs(root)
    accepted = directory / "ACCEPTED_TEXT_PENDING_DIRECTOR"
    accepted.mkdir(exist_ok=False)
    (accepted / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
    material = {"full_current_script": result["script"], "shared_manifest": result["manifest"], "planned_initial_state": result["initial"]}
    loop = original.revisions.initial_loop_state([], source_binding_sha256=SOURCE_BINDING, default_limit=3, stable_scope_material=material)
    control.write(directory / "INITIAL_LOOP_STATE.json", loop, True)
    record(directory, "whole_direction_performance_running", title=result["script"]["title"], spend=original.spend_summary(runtime))
    coordinator = original.directors.EndpointFeedbackCoordinator(invoke=invoke,
        persist_state=lambda value: control.write(directory / "LOOP_STATE.json", value),
        verify_frozen_source=lambda: verify_operator(root),
        opening_context_builder=lambda performance: original.shared.compile_segment_context(result["manifest"], result["script"],
            result["shared_dynamic_initial"], performance["source_refs"], bootstrap=True), models=original.text_pipeline.MODEL_POLICY)
    full = coordinator.run(script=result["script"], manifest=result["manifest"], initial=result["initial"],
        reference_fulltext=values["reference_fulltext"], preferences=values["production_preferences"], brief=result["brief"],
        source_review_binding=result["source_review_binding"], state=loop, scope=control.read(root / "USER_SCOPE.json"))
    control.write(directory / "PRODUCTION_RESULT.json", full, True)
    if full["status"] == "complete_text_production_handoff_ready":
        out = directory / "DELIVERABLE"
        out.mkdir(exist_ok=False)
        (out / "FULL_SCRIPT.md").write_text(original.text_pipeline.render_script(result["script"], result["brief"]), encoding="utf-8")
        control.write(out / "COMPLETE_PRODUCTION.json", full, True)
        lines = ["# 整片导演、表演与制作交接", "", "完整文本机器验收；视频仍待人工审核。", ""]
        for segment, prompt in zip(full["direction"]["segments"], full["planned_prompts"]):
            lines += ["## " + segment["segment_id"], json.dumps(segment, ensure_ascii=False, indent=2), "", prompt, ""]
        (out / "DIRECTOR_PERFORMANCE_HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")
    record(directory, full["status"], reason=full.get("reason"), title=result["script"]["title"],
        spend=original.spend_summary(runtime), complete_text_handoff_ready=full.get("complete_text_handoff_ready", False),
        deliverable=str(directory / "DELIVERABLE") if (directory / "DELIVERABLE").exists() else None)


def run(root):
    root, directory = location(root)
    if (directory / CLAIM).exists():
        raise ContinuationAlreadyClaimed("already claimed; inspect original results only")
    validate_stop(root)
    freeze = verify_operator(root)
    claim = {"schema": VERSION + "/claim", "started_at_utc": control.now(), "pid": os.getpid(),
        "operator_freeze_sha256": control.sha_file(directory / FREEZE), "source_binding_sha256": SOURCE_BINDING,
        "automatic_restart": False, "old_budget_reset": False, "new_media_calls": 0}
    try:
        with (directory / CLAIM).open("x", encoding="utf-8") as handle:
            json.dump(claim, handle, ensure_ascii=False, indent=2, allow_nan=False)
    except FileExistsError as exc:
        raise ContinuationAlreadyClaimed("another worker won the exclusive claim") from exc
    accepted_binding = None
    def guard():
        checked = verify_operator(root)
        verify_worker(root, checked)
        if accepted_binding is not None:
            verify_accepted_text_binding(directory, accepted_binding)
    runtime = original_runtime(root, control.read(root / "CALL_LEDGER.json"), guard)
    runtime.prepare()
    compact, continuation = modules()
    result_path = directory / "TEXT_RESULT.json"
    invoke = make_invoke(root, runtime, result_path)
    values = inputs(root)
    scope = root / "USER_SCOPE.json"
    operator_binding = {"operator_version": VERSION, "operator_freeze_sha256": control.sha_file(directory / FREEZE),
        "projection_sha256": control.sha_file(directory / "PROJECTION_EVIDENCE.json"),
        "source_binding_sha256": SOURCE_BINDING}
    def format_seed_factory(receipt):
        ledger = control.read(runtime.ledger)
        rows = [row for row in ledger["calls"] if row["ordinal"] == receipt["ordinal"]]
        if len(rows) != 1:
            raise ValueError("one recorded original receipt required for format recovery")
        row = rows[0]
        return continuation.compile_missing_tool_seed(receipt,
            receipt_bytes=(root / row["receipt"]).read_bytes(), evidence_directory=runtime.evidence_path(receipt["ordinal"]),
            expected_receipt_sha256=row["receipt_sha256"], expected_source_binding_sha256=SOURCE_BINDING,
            expected_wire=original.clients.expected_wire_request(receipt["request"]),
            verifier=lambda value, request: verified_sdk_evidence(runtime, value, request))
    pipeline = continuation.KnownPlanContinuation(invoke=invoke,
        persist_state=lambda value: control.write(directory / "TEXT_STATE.json", value),
        payload_projector=lambda payload: compact.compact_payload(payload, SOURCE_BINDING, now=control.now()),
        operator_binding=operator_binding,
        format_recovery_authorization={"authorized": True, "source_binding_sha256": SOURCE_BINDING,
            "evidence_ref": str(scope), "evidence_sha256": control.sha_file(scope)},
        resume_guard=lambda: guard(), format_seed_factory=format_seed_factory)
    record(directory, "known_plan_format_recovery_running", original_ordinal=524, versions=freeze["original_versions"], spend=original.spend_summary(runtime))
    result = pipeline.run_from_known_plan(resume_state=control.read(root / "TEXT_STATE.json"),
        format_seed=control.read(directory / SEED), **values, now=control.now())
    control.write(result_path, result, True)
    if result["status"] != "text_ready_for_director":
        record(directory, result["status"], versions=result.get("versions"), spend=original.spend_summary(runtime), complete_text_handoff_ready=False)
        return
    accepted_binding = bind_accepted_text(root, directory, result)
    production_tail(root, directory, runtime, invoke, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status"))
    parser.add_argument("--root", type=Path, default=original.DEFAULT_ROOT)
    args = parser.parse_args()
    root, directory = location(args.root)
    try:
        if args.command == "prepare":
            value = prepare(root)
            print(json.dumps({"status": "prepared", "operator_files": len(value["files"]), "source_binding_sha256": SOURCE_BINDING,
                "native_versions": value["original_versions"], "remaining_format_recovery": 1, "new_dispatches": 0}, ensure_ascii=False))
        elif args.command == "status":
            print(json.dumps(control.read(directory / "STATE.json"), ensure_ascii=False, indent=2))
        else:
            run(root)
    except ContinuationAlreadyClaimed:
        print(json.dumps({"status": "original_continuation_exists", "new_dispatches": 0}))
        raise SystemExit(2)
    except Exception as exc:
        if args.command == "run" and (directory / CLAIM).exists():
            record(directory, "stopped_exception", exception_type=type(exc).__name__,
                reason=str(exc)[:1200] if isinstance(exc, (ValueError, RuntimeError)) else "inspect original local evidence")
        raise


if __name__ == "__main__":
    main()
