"""Read-only production evidence and offline v3 request/gate preview.

No paid dispatcher or media submit command is exposed here. The new reusable
coordinator accepts an evidenced frozen runtime, but current inherited director
capacity is zero. A future production freeze requires a real extra-candidate
grant and inherits all 516 calls; this preview never manufactures that grant.
"""
from pathlib import Path
import argparse
from copy import deepcopy
import html
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_creative_shared_full_production_v1 as previous
from src.content_factory import creative_complete_production_pipeline_v3 as pipeline
from src.content_factory import creative_complete_production_coordinator_v3 as coordinator
from src.content_factory import creative_production_revision_loop_v3 as loop

OUT = PROJECT / "data/qa/shared_full_production_20261012/complete_workflow_v3_final"


def verified_parent():
    rt = previous.runtime()
    ledger = previous.control.read(rt.ledger)
    rt.check(ledger)
    receipts = {row["ordinal"]: rt.effective_receipt(row) for row in ledger["calls"]}
    if set(receipts) != {512, 513, 514, 515, 516}:
        raise ValueError("current exact parent lineage changed; do not infer a fresh allowance")
    source_record = previous.control.read(previous.ROOT / "ADOPTED_SOURCE.json")
    x = previous.control.read(previous.ROOT / "INPUT.json")
    script = source_record["script"]
    writer = loop.normalize_receipt(receipts[512])
    review = loop.normalize_receipt(receipts[513])
    if (not writer["known_complete"] or writer["status"] != "contract_valid"
        or writer["native_document"] != script or not review["known_complete"] or review["status"] != "contract_valid"
        or source_record["script_sha256"] != pipeline.digest(script)
        or source_record.get("machine_text_review_passed") is not True):
        raise ValueError("original complete source or full review is not valid")
    actual = review["actual_input"]
    exact = {"full_script": script, "script_sha256": pipeline.digest(script), "brief": x["brief"],
        "source_catalog": previous.source.catalog(script), "reference_fulltext": x["reference_fulltext"], "casting": x["casting"]}
    if any(actual.get(key) != value for key, value in exact.items()):
        raise ValueError("source full-review actual input differs from this exact source")
    result = previous.validate_review(review["native_document"], previous.review_schema(previous.SCRIPT_CHECKS, list(previous.source.catalog(script))))
    if result["needs_revision"]:
        raise ValueError("current complete source machine review is not passed")
    manifest = previous.control.read(previous.ROOT / "SHARED_MANIFEST.json")
    context = {key: deepcopy(x["brief"][key]) for key in ("characters", "scenes", "initial_state")}
    initial = pipeline.build_initial_state(context, manifest)
    if initial != previous.control.read(previous.ROOT / "PLANNED_INITIAL_STATE.json"):
        raise ValueError("frozen whole-film initial state changed")
    state = loop.initial_loop_state([receipts[i] for i in (514, 515, 516)])
    material = {"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial}
    if state["stable_scope_material"] != material:
        raise ValueError("inherited direction history belongs to another creative scope")
    proof = {"writer_ordinal": 512, "review_ordinal": 513, "script_sha256": pipeline.digest(script),
        "machine_text_review_passed": True, "native_source_unchanged": True,
        "original_actual_review_input_equal": True, "original_request_sha256s": [writer["request_sha256"], review["request_sha256"]],
        "parent_ledger_sha256": previous.control.sha_file(rt.ledger), "parent_frozen_sources_valid": True,
        "human_creative_quality_passed": False, "actual_media_quality_passed": False}
    return x, script, manifest, initial, state, proof


def preview():
    x, script, manifest, initial, state, proof = verified_parent()
    diagnostics = [{"ordinal": event["result"]["result_id"],
        "complete_rejected_native": event["result"]["native_document"],
        "timing_audit": pipeline.ranges.rejected_direction_timing_report(event["result"]["native_document"], script),
        "adopted": False} for event in state["director_events"]]
    inputs = pipeline.build_director_input(script, manifest, initial, x["reference_fulltext"], x["production_preferences"], diagnostics)
    models = previous.control.read(previous.ROOT / "ANCHOR.json")["models"]
    request = pipeline.build_request("whole_direction", inputs, pipeline.whole_direction_schema(script, manifest), models["writer"]["model"])
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in (("DIRECTOR_INPUT.preview.json", inputs), ("DIRECTOR_REQUEST.preview.json", request),
                        ("INHERITED_DIRECTOR_STATE.json", state), ("SOURCE_NATIVE_REVIEW_PROOF.json", proof)):
        previous.control.write(OUT / name, value, True)
    def fail_dispatch(*args, **kwargs):
        raise AssertionError("offline inherited-capacity gate must never invoke a provider")
    def save(value): previous.control.write(OUT / "OFFLINE_GATE_STATE.json", value)
    # The already verified source is immutable; no model/client is instantiated.
    flow = coordinator.CompleteProductionCoordinator(invoke=fail_dispatch, persist_state=save,
        verify_frozen_source=lambda: None,
        opening_context_builder=lambda performance: previous.shared.compile_segment_context(manifest, script,
            previous.bootstrap_dynamic_state(manifest, x), performance["source_refs"], bootstrap=True),
        models={role: model["model"] for role, model in models.items()})
    result = flow.run(script=script, manifest=manifest, initial=initial, reference_fulltext=x["reference_fulltext"],
        preferences=x["production_preferences"], brief=x["brief"], source_review_binding=proof, state=state,
        scope=previous.control.read(previous.ROOT / "USER_SCOPE.json"))
    summary = {"schema": "complete_workflow_v3/offline_gate", "source_title": script["title"],
        "source_proof": proof, "parent_calls": 516, "parent_reported_tokens": 7856107,
        "historical_unknown_reservation_tokens": 93117, "capacity": loop.candidate_capacity(state),
        "gate_status": result["status"], "gate_reason": result["reason"], "new_paid_calls": 0, "new_video_calls": 0,
        "new_candidate_allowance_granted": False, "old_freeze_changed": False, "old_ledger_reset": False,
        "complete_text_handoff_ready": False, "actual_media_quality_passed": False,
        "production_dispatch_entry_integrated": False,
        "reusable_coordinator_with_injected_runtime_implemented": True,
        "director_request_sha256": pipeline.digest(request)}
    previous.control.write(OUT / "ACTUAL_INHERITED_GATE_RESULT.json", summary, True)
    body = ["<!doctype html><meta charset='utf-8'><title>完整流程 v3 请求与边界</title>",
        "<style>body{max-width:1080px;margin:32px auto;padding:0 24px;font:16px/1.65 system-ui;background:#f7f8fc;color:#17202a}h1{font-size:26px}section,details{padding:20px;background:white;border-radius:12px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 Consolas,monospace}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:10px;text-align:left}.warn{background:#fff2d5}</style>",
        "<h1>完整制作流程 v3：可读请求预览</h1>",
        "<section class='warn'><b>当前真实门禁：已有三份导演计划失败，剩余候选 0。</b><p>本页未派发新请求，不增加额度，不修改旧稿或回执。额外候选尚未获批。剧本512/全文复审513有效；导演、逐段表演、完整制作交接和新视频仍未完成。</p></section>",
        "<section><h2>分工与失败回路</h2><table><tr><th>阶段</th><th>负责</th><th>失败处理</th></tr>",
        "<tr><td>整片导演 / MiniMax</td><td>情绪与因果、新增信息、观察对象、切镜理由；选择连续来源与预算</td><td>已知完整合同失败才有界提交完整新计划</td></tr>",
        "<tr><td>局部表演 / MiniMax</td><td>当前刺激反应、真实动作时长、正常对白重叠、计划终态和当前来源</td><td>真实估计超时回到整片导演，不压时或删句</td></tr>",
        "<tr><td>确定性编译</td><td>原文一次覆盖、排时、状态前缀、提示词及实际请求绑定</td><td>改变输入使受影响下游重建</td></tr>",
        "<tr><td>全文制作审查 / DeepSeek</td><td>同源完整正文、所有导演表演与状态、全部提示词和首段实际payload</td><td>明确fail有界完整导演返修；unknown停止；新稿重新全文复审</td></tr>",
        "<tr><td>媒体与用户</td><td>首段建立人物，用户批准后登记具体主体和原尾帧</td><td>助手仅验接口保存；新视频awaiting_human_review</td></tr></table></section>",
        "<section><h2>这次补齐的边界</h2><p>导演不再填写局部表演终态；图表字段名与实际请求一致。当前段导演意图进入视频提示词。局部超窗反馈携带原生全文和重算排时。旧全文审查不能跟随新计划复用。未知结果和中断停点持久保存，重启不能另开请求。</p><p>素材门核对固定角色服装场景进入实际正文，续段原视频/尾帧字节、用户明确批准和具体主体对应。首帧与原视频参考模式不能混用。0.25秒仍只是动作下界；真实演法和人脸稳定性仍需真实生产与人工审核。</p></section>"]
    for title, value in (("导演实际阶段提示", pipeline.DIRECTOR_RULE), ("表演实际阶段提示", pipeline.PERFORMANCE_RULE),
            ("当前完整剧本", script), ("完整逻辑模型请求（未派发）", request), ("真实来源与零派发门禁", summary)):
        txt = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        body.append("<details><summary>" + html.escape(title) + "</summary><pre>" + html.escape(txt) + "</pre></details>")
    (OUT / "WORKFLOW_REVIEW.html").write_text("\n".join(body), encoding="utf-8")
    return {**summary, "review_path": str(OUT / "WORKFLOW_REVIEW.html")}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["preview"])
    parser.parse_args()
    print(json.dumps(preview(), ensure_ascii=False), flush=True)
