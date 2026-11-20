"""Bounded real v3 coordinator probe, inheriting the original complete source.

User requested testing after the one-candidate proposal and offline completion.
Exactly one additional director candidate; no network/media retries or media
submit entry. Old 512--516 receipts, code freezes and spend remain unchanged.
"""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_creative_shared_full_production_v3 as intake
from scripts import run_creative_shared_full_production_v1 as old
from scripts.creative_bounded_format_role_clients_v1 import role_config
from src.content_factory import creative_complete_production_pipeline_v3 as pipeline
from src.content_factory import creative_complete_production_coordinator_v3 as coordinator
from src.content_factory import creative_production_revision_loop_v3 as loop

ROOT = PROJECT / "data/production_revisions/shared_full_production_20261012/probe_v4"
USER_QUOTE = "可以测试了吧"
GRANT_ID = "shared_full_production_20261012_v3_after_preview_one_director"


def grant_for(state):
    return {"authority": "explicit_user", "grant_id": GRANT_ID,
        "user_quote": USER_QUOTE, "additional_candidates": 1,
        "source_binding_sha256": state["source_binding_sha256"],
        "context": "此前明确提出追加一份导演；用户先看预览、要求补齐，补齐后请求测试。按该已展示方案限定一次，不另领三次。",
        "automatic_retry": False, "old_budget_reset": False}


def runtime():
    a = old.control.read(ROOT / "ANCHOR.json")
    def guard():
        old.prior.verify_files(a["parent_files"])
        old.runtime().check(old.control.read(old.ROOT / "CALL_LEDGER.json"))
    return old.control.ContinuationRuntime(PROJECT, ROOT,
        [PROJECT / p for p in a["runtime_sources"]], a["inherited"], a["models"],
        inherited_guard=guard, client_factory=old.BoundedFormatRoleClients, quota_state=None)


def verify_loop_history(rt):
    """Mutable progress may append events, never grant itself extra capacity."""
    baseline = old.control.read(ROOT / "INITIAL_LOOP_STATE.json")
    inherited = old.control.read(ROOT / "INHERITED_DIRECTOR_STATE.json")
    ledger = old.control.read(rt.ledger)
    expected = loop.register_successor_binding(inherited, old.control.digest(ledger["source_manifest"]),
        inherited["stable_scope_material"], old.control.digest(inherited))
    if baseline != expected:
        raise ValueError("derived successor baseline differs from frozen inherited state")
    state = old.control.read(ROOT / "LOOP_STATE.json")
    for key in ("schema", "source_binding_sha256", "stable_scope_material", "stable_scope_sha256",
            "successor_source_bindings", "original_candidate_limit", "additional_candidate_grants",
            "budget_reset", "history_preserved", "automatic_transport_retry"):
        if state.get(key) != baseline[key]:
            raise ValueError("persisted loop inherited scope or allowance changed: " + key)
    prefix = baseline["director_events"]
    if state["director_events"][:len(prefix)] != prefix:
        raise ValueError("original three director failures changed")
    suffix = state["director_events"][len(prefix):]
    claims = [e for e in suffix if e["event"] == "claim"]
    results = [e for e in suffix if e["event"] == "result"]
    if len(claims) > 1 or len(results) > 1 or len(suffix) != len(claims) + len(results):
        raise ValueError("single extra director history exceeded or malformed")
    directors = [r for r in ledger["calls"] if r["label"].startswith("whole_direction_v3_")]
    if len(directors) > 1:
        raise ValueError("single extra director ledger exceeded")
    if directors:
        receipt = rt.effective_receipt(directors[0])
        if len(claims) != 1 or claims[0]["request_identity"] != receipt["request_sha256"]:
            raise ValueError("director call has no exact durable claim")
    if results:
        if not directors or results[0]["result"] != loop.normalize_receipt(receipt):
            raise ValueError("director progress differs from original immutable receipt")
        if results[0]["request_identity"] != claims[0]["request_identity"]:
            raise ValueError("director result bound to another claim")
    return state


def prepare():
    if not (ROOT / "ANCHOR.json").exists():
        x, script, manifest, initial, state, proof = intake.verified_parent()
        parent_ledger = old.control.read(old.ROOT / "CALL_LEDGER.json")
        inherited, receipts = old.prior.inherited_known_parent(parent_ledger, old.ROOT)
        if [r["ordinal"] for r in receipts] != [512, 513, 514, 515, 516]:
            raise ValueError("exact original complete lineage required")
        if inherited["calls_started"] != 516 or inherited["reported_tokens"] != 7856107:
            raise ValueError("actual inherited spend changed; reconcile before freezing")
        state = loop.authorize_extra_candidate(state, grant_for(state))
        if loop.candidate_capacity(state)["remaining"] != 1:
            raise ValueError("one extra candidate must inherit all three prior attempts")
        inp = {"original_input": x, "script": script, "manifest": manifest, "initial": initial,
            "source_review_binding": proof}
        scope = deepcopy(old.control.read(old.ROOT / "USER_SCOPE.json"))
        scope.update(probe_schema="complete_workflow_v3_real_probe/v4", test_user_statement=USER_QUOTE,
            additional_director_candidates=1, original_director_candidates_consumed=3,
            reused_native_script_ordinal=512, reused_full_review_ordinal=513,
            media_dispatch_in_this_entry=False, old_text_spend_preserved=True)
        for name, value in (("INPUT.json", inp), ("USER_SCOPE.json", scope),
                ("INHERITED_DIRECTOR_STATE.json", state), ("EXTRA_CANDIDATE_GRANT.json", grant_for(state))):
            old.control.write(ROOT / name, value, True)
        claim_path = PROJECT / "data/creative_continuation_stages" / old.control.digest({
            "grant_id": GRANT_ID, "original_binding": state["source_binding_sha256"]}) / "CLAIM.json"
        old.control.write(claim_path, {"grant_id": GRANT_ID, "root": str(ROOT),
            "additional_candidates": 1, "parent_ledger_sha256": old.control.sha_file(old.ROOT / "CALL_LEDGER.json"),
            "user_quote": USER_QUOTE, "budget_reset": False}, True)
        parent_files = [old.ROOT / n for n in ("CALL_LEDGER.json", "AUTHORIZATION.json", "ANCHOR.json",
            "INPUT.json", "ADOPTED_SOURCE.json", "SHARED_MANIFEST.json", "PLANNED_INITIAL_STATE.json", "USER_SCOPE.json")]
        parent_files += [old.ROOT / r["receipt"] for r in parent_ledger["calls"]]
        parent_files += [p for p in (old.ROOT / "call_evidence").rglob("*") if p.is_file()]
        parent_files += [claim_path]
        sources = [p for folder in (PROJECT / "src", PROJECT / "scripts") for p in folder.rglob("*.py")]
        sources += [ROOT / n for n in ("INPUT.json", "USER_SCOPE.json", "ANCHOR.json",
            "INHERITED_DIRECTOR_STATE.json", "EXTRA_CANDIDATE_GRANT.json")]
        old.control.write(ROOT / "ANCHOR.json", {"inherited": inherited, "models": parent_ledger["model_configs"],
            "parent_files": {str(p): old.control.sha_file(p) for p in parent_files},
            "runtime_sources": [p.relative_to(PROJECT).as_posix() for p in sources]}, True)
    rt = runtime()
    rt.prepare()
    original = old.control.read(ROOT / "INHERITED_DIRECTOR_STATE.json")
    bound = loop.register_successor_binding(original,
        old.control.digest(old.control.read(rt.ledger)["source_manifest"]),
        original["stable_scope_material"], old.control.digest(original))
    old.control.write(ROOT / "INITIAL_LOOP_STATE.json", bound, True)
    if not (ROOT / "LOOP_STATE.json").exists():
        old.control.write(ROOT / "LOOP_STATE.json", bound, True)
    return status()


def summary_result(result, rt):
    a = old.control.read(ROOT / "ANCHOR.json")
    state = result["loop_state"]
    return {"schema": "complete_workflow_v3_real_probe/v4", "status": result["status"],
        "reason": result.get("reason"), **rt.summary(), "director_capacity": loop.candidate_capacity(state),
        "historical_unknown_token_reservations": a["inherited"]["unknown_token_reservations"],
        "historical_unknown_calls": a["inherited"]["pending_ordinals"],
        "complete_text_handoff_ready": result["complete_text_handoff_ready"],
        "actual_media_quality_passed": False, "human_creative_quality_passed": False,
        "new_video_calls": 0, "result_path": str(ROOT / "PRODUCTION_RESULT.json"),
        "report_path": str(ROOT / "PRODUCTION_REPORT.md")}


def status():
    rt = runtime()
    state = old.control.read(ROOT / "LOOP_STATE.json")
    if (ROOT / "PRODUCTION_RESULT.json").exists():
        return summary_result(old.control.read(ROOT / "PRODUCTION_RESULT.json"), rt)
    a = old.control.read(ROOT / "ANCHOR.json")
    return {"status": "prepared_not_dispatched", **rt.summary(),
        "director_capacity": loop.candidate_capacity(state), "coordinator_status": state.get("coordinator_status"),
        "historical_unknown_token_reservations": a["inherited"]["unknown_token_reservations"],
        "historical_unknown_calls": a["inherited"]["pending_ordinals"], "new_video_calls": 0}


def render_report(result, rt, script):
    summary = summary_result(result, rt)
    lines = ["# 新流程真实生产测试", "", "完整正文沿用512《" + script["title"] + "》及513全文复审。",
        "当前状态：" + result["status"] + "；停止原因：" + str(result.get("reason")),
        "本次只追加一份导演，原514—516及累计消耗承接；没有自动运输重试、视频派发或发布。",
        "", "## 实际调用"]
    ledger = old.control.read(rt.ledger)
    for row in ledger["calls"]:
        receipt = rt.effective_receipt(row)
        meta = receipt.get("response_metadata", {})
        lines += ["", f"- {receipt['ordinal']} / {receipt['label']} / {receipt['status']} / "
            f"reported tokens={meta.get('total_tokens')} / finish={meta.get('finish_reason')}"]
        if receipt.get("validation_error"):
            lines.append("  验收：" + str(receipt["validation_error"].get("message")))
        if receipt.get("failure"):
            lines.append("  分流：" + str(receipt["failure"].get("code")))
    lines += ["", "## 结果边界", "", "离线通过、接口返回和文本合同通过分别记录；尚无新视频内容批准。",
        "历史70/160未知及93117预留保留，不按当前运行的零未知解释为历史已结清。",
        "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines)


def save_artifacts(result, rt, inp):
    old.control.write(ROOT / "PRODUCTION_RESULT.json", result, True)
    ledger = old.control.read(rt.ledger)
    reference = inp["original_input"]["reference_fulltext"]
    proof = []
    for row in ledger["calls"]:
        receipt = rt.effective_receipt(row)
        wire_input = loop.normalize_receipt(receipt)["actual_input"]
        journal_root = rt.evidence_path(row["ordinal"])
        body_manifest_path = journal_root / "REQUEST_BODY_MANIFEST.json"
        capture = old.control.read(body_manifest_path) if body_manifest_path.exists() else None
        raw_path = journal_root / "request_body.raw"
        capture_valid = bool(capture and capture.get("body_complete") is True and capture.get("raw_bytes_preserved") is True
            and capture.get("identity_sha256") == receipt.get("call_evidence", {}).get("identity_sha256")
            and raw_path.exists() and old.control.sha_file(raw_path) == capture.get("stored_sha256") == capture.get("original_sha256"))
        actual = json.loads(raw_path.read_bytes()) if capture_valid else None
        users = [m.get("content") for m in actual.get("messages", []) if m.get("role") == "user"] if actual else []
        # Exact original reference value occurs in the actual user JSON, rather
        # than merely being present in a local input description.
        actual_inputs = [json.loads(v) for v in users if isinstance(v, str) and v.startswith("{")]
        outgoing_reference_equal = any(v.get("reference_fulltext") == reference for v in actual_inputs)
        proof.append({"ordinal": row["ordinal"], "logical_reference_equal": bool(wire_input and wire_input.get("reference_fulltext") == reference),
            "actual_serialized_reference_equal": outgoing_reference_equal,
            "actual_request_body_binding_verified": capture_valid,
            "request_body_manifest": str(body_manifest_path), "request_body_sha256": capture.get("stored_sha256") if capture else None,
            "reference_sha256": old.control.digest(reference), "provider_received_request": None})
    old.control.write(ROOT / "ACTUAL_REFERENCE_PROOF.json", proof, True)
    (ROOT / "PRODUCTION_REPORT.md").write_text(render_report(result, rt, inp["script"]), encoding="utf-8")
    if not result["complete_text_handoff_ready"]:
        return
    out = ROOT / "DELIVERABLE"
    for name, value in (("FULL_SCRIPT.json", inp["script"]), ("WHOLE_DIRECTION.json", result["direction"]),
            ("ALL_LOCAL_PERFORMANCES.json", result["performances"]), ("COMPLETE_PRODUCTION_COMPILED.json", result["complete_compilation"]),
            ("OPENING_REQUEST_PREVIEW.json", result["opening_actual_preview"]),
            ("REVIEWED_REQUEST_PROOF.json", result["reviewed_request_identity_proof"])):
        old.control.write(out / name, value, True)
    (out / "FULL_SCRIPT.md").write_text(old.source_text(inp["script"]), encoding="utf-8")
    lines = [old.source_text(inp["script"]), "## 整片导演与逐段表演", "机器全文制作复审通过；后续媒体由用户审核。"]
    for p, prompt in zip(result["performances"], result["planned_prompts"]):
        lines += ["### " + p["segment_id"], "```json\n" + json.dumps(p, ensure_ascii=False, indent=2) + "\n```", "```text\n" + prompt + "\n```"]
    (out / "DIRECTOR_PERFORMANCE_HANDOFF.md").write_text("\n\n".join(lines), encoding="utf-8")


def execute():
    prepare()
    if (ROOT / "PRODUCTION_RESULT.json").exists():
        return status()  # never rerun a saved completed/failed execution
    rt = runtime()
    # Independent full-run lock; per-call runtime lock remains responsible for
    # reserving immutable request/receipt identities before any HTTP send.
    lock_path = ROOT / "COORDINATOR_EXECUTION.lock"
    with lock_path.open("x", encoding="utf-8") as lock:
        lock.write(json.dumps({"started_at": old.control.now(), "user_quote": USER_QUOTE}))
    try:
        inp = old.control.read(ROOT / "INPUT.json")
        x, script, manifest, initial = inp["original_input"], inp["script"], inp["manifest"], inp["initial"]
        def verify():
            rt.check(old.control.read(rt.ledger))
            verify_loop_history(rt)
            for role, expected in rt.models.items():
                cfg = role_config(role)
                if any(getattr(cfg, key) != expected[key] for key in ("provider", "model", "base_url")):
                    raise ValueError("actual role configuration differs from inherited frozen model")
        def invoke(label, request, validate):
            old.control.write(ROOT / "stage_requests" / (label + ".json"), request, True)
            return rt.dispatch(label, request, validate)
        flow = coordinator.CompleteProductionCoordinator(invoke=invoke,
            persist_state=lambda state: old.control.write(ROOT / "LOOP_STATE.json", state),
            verify_frozen_source=verify,
            opening_context_builder=lambda p: old.shared.compile_segment_context(manifest, script,
                old.bootstrap_dynamic_state(manifest, x), p["source_refs"], bootstrap=True),
            models={role: cfg["model"] for role, cfg in rt.models.items()})
        result = flow.run(script=script, manifest=manifest, initial=initial,
            reference_fulltext=x["reference_fulltext"], preferences=x["production_preferences"], brief=x["brief"],
            source_review_binding=inp["source_review_binding"], state=old.control.read(ROOT / "LOOP_STATE.json"),
            scope=old.control.read(ROOT / "USER_SCOPE.json"))
        save_artifacts(result, rt, inp)
        return summary_result(result, rt)
    except Exception as exc:
        try:
            runtime_summary = rt.summary()
        except Exception as summary_error:
            runtime_summary = {"status": "unavailable_guard_failure", "error_type": type(summary_error).__name__}
        evidence = {"status": "execution_interrupted_reconcile_original", "error_type": type(exc).__name__,
            "message": str(exc), "new_request_redispatch_allowed": False, "automatic_retry": False,
            "timestamp": old.control.now(), "runtime_summary": runtime_summary}
        path = ROOT / ("INTERRUPTION_" + old.control.digest(evidence)[:16] + ".json")
        old.control.write(path, evidence, True)
        if not (ROOT / "PRODUCTION_REPORT.md").exists():
            (ROOT / "PRODUCTION_REPORT.md").write_text("# 新流程测试中断\n\n"
                + "状态或保存环节中断，保留原请求与原始证据；没有重新派发。\n\n"
                + json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return evidence
    finally:
        lock_path.unlink()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "text", "status"))
    args = parser.parse_args()
    print(json.dumps({"prepare": prepare, "text": execute, "status": status}[args.operation](), ensure_ascii=False), flush=True)
