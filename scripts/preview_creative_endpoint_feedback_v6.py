"""Read-only replay and full request preview; never grants or dispatches calls."""
from copy import deepcopy
from pathlib import Path
import argparse
import hashlib
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_creative_capability_production_v5 as frozen
from scripts import creative_capability_role_clients_v2 as clients
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from src.content_factory import creative_complete_production_coordinator_v4 as coordinator
from src.content_factory import creative_endpoint_revision_feedback_v5 as adapter
from src.content_factory import creative_production_revision_loop_v3 as loop
from src.content_factory import creative_video_trial_contract_v1 as source

VERSION = "creative_endpoint_feedback_preview/v6"
QA_ROOT = PROJECT / "data/qa/creative_capability_production_adapter_20261012/endpoint_diagnostic_repair"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_preview():
    """Verify actual frozen lineage and replay originals without reserving work."""
    rt = frozen.runtime()
    ledger = read(rt.ledger)
    rt.check(ledger)
    inputs = read(frozen.ROOT / "INPUT.json")
    state = frozen.verify_loop_history(rt)
    capacity = loop.candidate_capacity(state)
    if (capacity["candidate_limit"] != 7 or capacity["attempts_including_claims"] != 7
        or capacity["remaining"] != 0 or capacity["unresolved_claims"]
        or capacity["unresolved_result_ids"]):
        raise ValueError("this read-only preview requires the exact completed 7/7 trial")
    script, manifest = inputs["script"], inputs["manifest"]
    originals, audits, evidence_rows = {}, [], []
    if [row["ordinal"] for row in ledger["calls"]] != [518, 519, 520]:
        raise ValueError("exact three original service receipts required")
    for row in ledger["calls"]:
        path = frozen.ROOT / row["receipt"]
        receipt = read(path)
        evidence = loop.normalize_receipt(receipt)
        if not loop._compatible_evidence(state, evidence):
            raise ValueError("original receipt source differs from the inherited stable scope")
        if (not evidence["known_complete"] or not evidence["usage_known"]
            or evidence["status"] != "contract_rejected"
            or evidence["actual_input"]["full_current_script"] != script
            or evidence["actual_input"]["shared_manifest"] != manifest):
            raise ValueError("original complete known rejected source required")
        originals[str(path)] = sha(path)
        detail = adapter.describe_endpoint_failure(evidence["native_document"], script, manifest)
        audits.append({"ordinal": row["ordinal"], "receipt_path": str(path),
            "receipt_file_sha256": sha(path), "original_result_identity": {
                key: evidence[key] for key in ("result_id", "request_sha256", "native_sha256",
                    "receipt_sha256", "reported_tokens")},
            "diagnostic": detail, "original_plan_adopted": False})
        evidence_rows.append(evidence)
    last = evidence_rows[-1]
    # This is a diagnostic document, not route_failure permission or a new claim.
    # The real exhausted route remains unchanged in the original production root.
    feedback = {
        "revision_kind": "complete_native_whole_direction", "failure_code": loop.DIRECTOR_FAILURE,
        "prior_complete_native_direction": deepcopy(last["native_document"]),
        "failed_complete_native_result": deepcopy(last["native_document"]),
        "diagnostic": {"validation_error": audits[-1]["diagnostic"]["validation_error"]},
        "original_result_identity": {key: deepcopy(last[key]) for key in
            ("result_id", "request_sha256", "native_sha256", "receipt_sha256", "reported_tokens")},
        "instruction": "提交完整新的原生整片导演计划；保留全文与共用初态，不拼接旧计划、不由程序修改切点，不压缩原对白或提速。重新安排范围及预算，并给出全片叙事理由。",
    }
    enriched = adapter.enrich_director_revision_input(feedback, script, manifest, result_evidence=last)
    original = inputs["original_input"]
    context = coordinator.production_context_digest(original["brief"],
        original["reference_fulltext"], original["production_preferences"])
    stop = {"previous_stop_summary": {"reason": "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED",
        "capacity": capacity, "last_result_id": last["result_id"]},
        "complete_stop_preserved_in_history": True, "adopted": False}
    future_input = pipeline.build_director_input(script, manifest, inputs["initial"],
        original["reference_fulltext"], original["production_preferences"], [stop, enriched])
    future_input["brief"] = deepcopy(original["brief"])
    future_input["production_context_binding"] = {"production_context_sha256": context,
        "binding_kind": "external_frozen_input_identity", "prior_semantic_review_claim": False}
    request = pipeline.build_request("whole_direction", future_input,
        pipeline.whole_direction_schema(script, manifest), ledger["model_configs"]["writer"]["model"])
    wire = clients.expected_wire_request(request)
    for path in (frozen.ROOT / name for name in
        ("CALL_LEDGER.json", "LOOP_STATE.json", "INPUT.json", "ANCHOR.json", "PRODUCTION_RESULT.json")):
        originals[str(path)] = sha(path)
    report = {"schema": VERSION, "preview_only": True, "dispatched": False,
        "dispatch_allowed": False, "calls_authorized": False,
        "block_reason": "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED", "director_capacity": capacity,
        "new_calls": 0, "new_media_calls": 0, "candidate_or_budget_reset": False,
        "production_root": str(frozen.ROOT), "original_file_hashes": originals,
        "script_sha256": source.digest(script), "manifest_sha256": source.digest(manifest),
        "reference_fulltext_sha256": source.digest(original["reference_fulltext"]),
        "original_512_513_source_preserved": True, "complete_source_in_request": True,
        "original_failed_native_kept_once": "prior_complete_native_direction" not in enriched,
        "original_failed_native_sha256": last["native_sha256"], "model_request_sha256": source.digest(request),
        "wire_body_sha256": source.digest(wire), "audits": audits,
        "implementation_is_offline_only": True, "real_quality_passed": False,
        "native_plan_adopted": False, "semantic_action_feasibility_proven": False}
    if any(sha(path) != value for path, value in originals.items()):
        raise ValueError("read-only replay changed an original file")
    return report, enriched, request, wire


def write_preview(output_dir):
    out = Path(output_dir).resolve()
    out.relative_to(QA_ROOT.resolve())
    if out.exists() and any(out.iterdir()):
        raise ValueError("preserve prior previews; choose a new empty output directory")
    report, feedback, request, wire = build_preview()
    out.mkdir(parents=True, exist_ok=True)
    for name, document in (("READ_ONLY_PREVIEW.json", report), ("COMPLETE_REVISION_FEEDBACK.json", feedback),
        ("FULL_MODEL_REQUEST.json", request), ("SDK_WIRE_BODY_PREVIEW.json", wire)):
        (out / name).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 结构化诊断修复后的只读请求预览", "",
        "当前真实候选7/7，剩余0。本目录没有新增调用、授权、采用或预算重置；新适配尚未生产验证。", "",
        "正文仍为512《桌面那张纸》、513同源全文审查。公司要求离开却递上写着个人原因的自愿离职表；小林顶住公司口径和个人劝说，周姐收走未签纸笔独自离开，小林留坐，争议未结束。", "",
        "以下只复算原518–520的错误；不替模型改端点或档位。", "",
        "| 原调用 | 镜段 | 推导起点 → 所选终点 | 所选档位需时 | 当前范围可用档位 |", "| --- | --- | --- | --- | --- |"]
    for audit in report["audits"]:
        for row in audit["diagnostic"]["invalid_segments"]:
            tiers = ", ".join(row["legal_budget_tiers_for_selected_range"]) or "无；需重新安排范围"
            lines.append(f"| {audit['ordinal']} | {row['segment_id']} | {row['derived_start_source_ref']} → {row['selected_end_source_ref']} | {row['requested_budget_tier']} / {row['required_seconds_for_requested_tier']:.6f}s | {tiers} |")
    lines += ["", "完整原生520失败计划在新反馈中保留一次，原回执仍在生产目录。下一完整请求包含全文、初态、完整参考、人物场景manifest和原端点图；具体诊断新增源下界、单段上限、合法档位及合法后继范围。", "",
        "`FULL_MODEL_REQUEST.json`：完整逻辑请求。`SDK_WIRE_BODY_PREVIEW.json`：同一客户端的序列化前body预览，未发送。`READ_ONLY_PREVIEW.json`：原文件哈希、三份诊断和真实耗尽容量。", "",
        "接口调用成功与排时、实际表演、制作交接、人工创作及视频质量分别验收。当前无可采用整片导演、逐段表演、制作交接或新视频。"]
    (out / "READABLE_REQUEST_PREVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "read_only_preview_saved", "output_dir": str(out), "new_calls": 0,
        "dispatch_allowed": False, "director_capacity": report["director_capacity"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=QA_ROOT / "preview_r1")
    args = parser.parse_args()
    print(json.dumps(write_preview(args.output_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
