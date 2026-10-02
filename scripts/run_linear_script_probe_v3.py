"""Frozen linear script production probe; inherited ledger, complete drafts only."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as base
from scripts import creative_linear_script_v2 as linear
from src.content_factory.creative_workflow_contract import validate_script
from src.content_factory.creative_review_v6 import build_review_prompt,validate_review_v6
VERSION="linear_complete_script_probe_v3"
BINDING=base.ROOT/"LINEAR_OPERATOR_BINDING_v3.json"
ISSUES=[
 {"id":"VERIFIED_DURATION_MISMATCH","source_call":45,"declared_total_seconds":68,"beat_sum_seconds":126,
  "request":"重新创作完整新稿；当前拍填写秒数，整片总时长程序计算，不转换失败旧稿充当新稿。"},
 {"id":"VERIFIED_SPEECH_ORDER","source_call":45,"location":"B7",
  "request":"按steps实际播放顺序先抬头再对白再听后反应，action不重复已经播放的同一次对白。"},
 {"id":"CORRECT_NARRATIVE_CAMERA_BOUNDARY","request":"叙事拍与镜头不是同一种单元。按情绪与因果组织叙事拍，一个拍可含多个必要观察镜头，由后续导演拆镜；不要把每个动作强拆一拍，也不要删除必要观察对象来迁就旧编译器。"},
 {"id":"PHYSICAL_CONTINUITY","request":"票根与便签明确桌面初态与去向；方澄拿包的位置与林屿最后取便签的可达布局写清。不要用镜头变化代替人物移动或道具状态。"}
]
def binding():
    paths=[Path(__file__).resolve(),Path(linear.__file__).resolve()]
    manifest={str(p.relative_to(base.PROJECT)).replace("\\","/"):base.file_hash(p) for p in paths}
    value={"version":VERSION,"source_manifest":manifest}
    if BINDING.exists():
        if base.read(BINDING)!=value:raise RuntimeError("linear operator source binding changed")
    else:
        for p in paths:
            dst=base.ROOT/"operator_sources"/VERSION/p.name
            dst.parent.mkdir(parents=True,exist_ok=True)
            with dst.open("xb") as f:f.write(p.read_bytes())
        base.write(BINDING,value,True)
    for p in paths:
        if base.file_hash(base.ROOT/"operator_sources"/VERSION/p.name)!=base.file_hash(p):
            raise RuntimeError("linear source snapshot changed")
    return value
def dispatched(label,wire,validator,retain=14000):
    wire["operator_binding"]=binding()
    return base.dispatch(label,wire,validator,retain)
def rejected_previous():
    ledger=base.read(base.LEDGER);base.check(ledger)
    row=next(c for c in ledger["calls"] if c["label"]=="draft_v2")
    r=base.read(base.ROOT/row["receipt"])
    if r["status"]!="contract_rejected":raise RuntimeError("known full-draft rejection required")
    return r["output"]
def original():return base.read(base.ROOT/"ORIGINAL_CONTEXT.json")
def derive(raw):
    ctx=original()
    names=[c["name"] for c in ctx["static_visual_manifest"]["characters"]]
    out=linear.accept_linear_script(ctx["script"],raw,character_names=names)
    validate_script(deepcopy(out),ctx["script"]["selected_candidate_id"],"","original")
    return out
def draft():
    ctx=original()
    messages=linear.build_linear_script_messages(ctx,rejected_previous(),ISSUES)
    def validate(raw):
        derived=derive(raw)
        return {"complete_new_model_script":True,"derived_script_sha256":base.digest(derived),
                "total_seconds_computed":derived["duration_seconds"],"narrative_beats":len(derived["beats"]),
                "source_steps_unchanged":True,"semantic_approval":False,"requires_full_review":True}
    return dispatched("linear_draft_v3",base.request("writer",messages,linear.build_linear_script_schema(ctx),4096),validate)
def context():
    binding()
    receipt=base.get_call("linear_draft_v3")
    derived=derive(receipt["output"])
    artifact={"schema":"linear_derived_script/v3","raw_sha256":base.digest(receipt["output"]),
              "adapter_sha256":base.file_hash(linear.__file__),"script":derived}
    path=base.ROOT/"DERIVED_LINEAR_SCRIPT_v3.json"
    if path.exists():
        if base.read(path)!=artifact:raise RuntimeError("derived script changed")
    else:base.write(path,artifact,True)
    ctx=original()
    ctx["script"]=derived
    ctx["raw_linear_script"]=deepcopy(receipt["output"])
    ctx["script_revision_source"]={"label":receipt["label"],"ordinal":receipt["ordinal"],
        "raw_sha256":artifact["raw_sha256"],"adapter_sha256":artifact["adapter_sha256"],
        "complete_model_authored":True,"automatic_semantic_pass":False}
    return ctx
def review():
    ctx=context()
    prompt=build_review_prompt(ctx)+"""
当前完整新稿的真实播放顺序由raw_linear_script.beats.N.steps数组定义，script是程序保持原文生成的兼容投影。before→首句dialogue→during→次句dialogue→after与steps等价；不得把during当成首句对白进行中。
每项pass/fail必须至少引用该行script.beats.N的真实正文叶子。assets若检查全局manifest，也要加本拍正文证据。quote只截必要逐字片段，reason简短具体，避免重复全文。叙事拍可包含多个必要镜头，镜头拆分由后续导演；不要将一拍多观察对象本身列为创作错误。
独立核对票根/便签初态和拿取前提、方澄拿包位置与邻桌可达布局、拒绝前目光准备、说后听者反应、最后主动者及结尾。不能因为顺序/总长由程序导出就忽略正文质量，也不能假定实际图片已生成或被导演看到。
"""
    def validate(value):
        validate_review_v6(value,ctx)
        return {"evidence_valid":True,"story_preserved":value["story_preserved"],
                "requires_assistant_evidence_verification":True,"semantic_approval":False}
    return dispatched("linear_script_review_v3",base.request("director",
        [{"role":"system","content":prompt},{"role":"user","content":json.dumps(ctx,ensure_ascii=False)}],
        None,6000),validate)
def decision(approved,evidence):
    binding();ctx=context();r=base.get_call("linear_script_review_v3")
    if approved and (r["output"]["issues"] or not r["output"]["story_preserved"]):
        raise RuntimeError("unresolved required issues")
    value={"schema":"assistant_linear_script_decision/v3","context_sha256":base.digest(ctx),
        "review_sha256":base.digest(r["output"]),"approved_for_direction":approved,
        "evidence":evidence,"decision_source":"assistant_verified_text_evidence","media_approval":False}
    path=base.ROOT/"LINEAR_SCRIPT_REVIEW_DECISION_v3.json"
    if path.exists():
        if base.read(path)!=value:raise RuntimeError("decision changed")
    else:base.write(path,value,True)
    return value
def preflight(stage):
    if stage=="draft":
        ctx=original();wire=base.request("writer",linear.build_linear_script_messages(ctx,rejected_previous(),ISSUES),
                                         linear.build_linear_script_schema(ctx),4096)
    elif stage=="review":
        raise RuntimeError("review preflight derives context and is handled by inherited dispatch guard")
    else:raise ValueError(stage)
    s=base.summary()
    reserve=len(json.dumps(wire,ensure_ascii=False))+4096+1024+14000
    return {"stage":stage,"reservation_plus_retained_review":reserve,"remaining_reported_tokens":s["remaining_tokens"],
            "within_original_budget":reserve<=s["remaining_tokens"],"automatic_retry":False,
            "reference_pack_in_actual_messages":bool(ctx.get("reference_pack"))}
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd=sys.argv[1]
    if cmd=="draft":r=draft()
    elif cmd=="review":r=review()
    elif cmd=="context":r={"context_sha256":base.digest(context())}
    elif cmd=="preflight":r=preflight("draft")
    else:raise SystemExit("draft | review | context | preflight")
    print(json.dumps({k:r.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")} if cmd in ("draft","review") else r,ensure_ascii=False,indent=2))
    if cmd in ("draft","review"):print(json.dumps(base.summary(),ensure_ascii=False))
