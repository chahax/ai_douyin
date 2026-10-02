"""Evidence-specific complete rewrite and full review; no manual content patches."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as base
from scripts import run_linear_script_probe_v3 as old
from scripts import creative_linear_script_v2 as linear
from src.content_factory.creative_review_v6 import build_review_prompt,validate_review_v6
VERSION="evidence_adjudicated_linear_revision_v5"
DISPOSITION=[
 {"id":"I01","disposition":"verified_must_fix","evidence":"上次只指一次；今晚又为本次新请求；三张便签实际只有任务短词，没有不同日期或多次替林屿加班的可见因果。",
  "request":"在拒绝前用自然对白或实际可见后果明确过去多次替同事加班，实际步骤兑现；不要只加event/trigger自述，也不要硬塞讲主题的旁白。保持静态便签既有外观，可通过新稿自然对白兑现。"},
 {"id":"I02","disposition":"partly_verified_summary_step_mismatch","evidence":"steps顺序明确先目光/包带收紧再请求；event抬头请求未在实际步骤，trigger却将先行动作当本次请求的反应。",
  "request":"生成完整新稿时统一真实刺激、预期压力、听后反应的语义和顺序，重要对白获得实际可读表演窗口。不重复同一次台词。"},
 {"id":"I03","disposition":"not_proven_by_review","evidence":"原B7拒绝紧接B8停笔；B8 trigger写把拒绝落到对方手上；审查自己B8 continuity也写承接拒绝。",
  "request":"不要仅为旧审查添加解释性旁白或强迫反应回同拍。若优化则保留真实跨拍拒绝→停笔关系。"},
 {"id":"I04","disposition":"unverified_spatial_risk","evidence":"原steps明确从方澄桌边转身走到自己身后贴墙抽屉柜前，与E03在林屿工位后方的关系未出现明确冲突。",
  "request":"不要凭可能空间混乱新增走位操作；保持可制作的布局与取用前提。"}
]
def binding():
    old.binding()
    paths=[Path(__file__).resolve(),Path(linear.__file__).resolve()]
    manifest={"version":VERSION,"source_manifest":{str(p.relative_to(base.PROJECT)).replace("\\","/"):base.file_hash(p) for p in paths},
              "previous_linear_binding_sha256":base.file_hash(old.BINDING)}
    path=base.ROOT/"LINEAR_REVISION_BINDING_v5.json"
    if path.exists():
        if base.read(path)!=manifest:raise RuntimeError("v5 operator changed")
    else:
        for p in paths:
            snap=base.ROOT/"operator_sources"/VERSION/p.name
            snap.parent.mkdir(parents=True,exist_ok=True)
            with snap.open("xb") as f:f.write(p.read_bytes())
        base.write(path,manifest,True)
    for p in paths:
        if base.file_hash(base.ROOT/"operator_sources"/VERSION/p.name)!=base.file_hash(p):
            raise RuntimeError("v5 source snapshot changed")
    return manifest
def draft_wire():
    original=old.original();ctx=deepcopy(original)
    # Previous complete raw is sent once. The unrelated original script is not
    # duplicated; all brief, asset, material and reference input remains intact.
    ctx.pop("script")
    prior=base.get_call("linear_draft_v3")
    review=base.get_call("linear_script_review_v4")
    issues={"previous_review_issues":[{k:i[k] for k in ("id","rule","evidence")} for i in review["output"]["issues"]],"assistant_verified_disposition":DISPOSITION,
            "request":"提交完整新稿，不能拼接旧稿。按情绪因果组织自然叙事单元，镜头安排留导演；时长可浮动，保留表演时间，删除没有叙事作用的操作。不要仅换格式复交原稿。"}
    messages=linear.build_linear_script_messages(ctx,prior["output"],issues)
    wire=base.request("writer",messages,linear.build_linear_script_schema(original),4096)
    wire["input_provenance"]={"original_context_sha256":base.digest(original),
        "previous_script_sha256":base.digest(prior["output"]),"review_sha256":base.digest(review["output"]),
        "reference_pack_sha256":base.digest(ctx["reference_pack"]),"no_reference_truncation":True,
        "projection":"original context except obsolete script; previous full raw supplied once"}
    return wire
def draft():
    wire=draft_wire();wire["operator_binding"]=binding()
    def validate(raw):
        derived=old.derive(raw)
        return {"complete_new_model_script":True,"derived_script_sha256":base.digest(derived),
                "total_seconds_computed":derived["duration_seconds"],"narrative_beats":len(derived["beats"]),
                "semantic_approval":False,"requires_full_review":True}
    return base.dispatch("linear_draft_v5",wire,validate,14000)
def context():
    binding();r=base.get_call("linear_draft_v5");derived=old.derive(r["output"])
    artifact={"schema":"linear_derived_script/v5","raw_sha256":base.digest(r["output"]),
        "adapter_sha256":base.file_hash(linear.__file__),"script":derived}
    path=base.ROOT/"DERIVED_LINEAR_SCRIPT_v5.json"
    if path.exists():
        if base.read(path)!=artifact:raise RuntimeError("v5 derived script changed")
    else:base.write(path,artifact,True)
    ctx=old.original()
    ctx["script"]=deepcopy(derived)
    # The markdown repeats all actual steps already present in the canonical
    # beats. Review receives each complete action and dialogue exactly once.
    ctx["script"].pop("screenplay_markdown")
    ctx["script_revision_source"]={"label":r["label"],"ordinal":r["ordinal"],"raw_sha256":artifact["raw_sha256"],
        "adapter_sha256":artifact["adapter_sha256"],"complete_model_authored":True}
    return ctx
def review_wire():
    ctx=context()
    prompt=build_review_prompt(ctx)+"""
当前剧本是完整新模型steps无损映射，实际顺序before→首句dialogue→during→次句dialogue→after；空槽不是新增动作。每项pass/fail引用本拍真实正文叶子；assets核对manifest时也加本拍证据。quote截必要逐字片段，reason简短，不重复整段正文。
跨拍可合法承担刺激→反应，必须核对前后实际顺序；不要求同拍再次重演已发生刺激，不凭“可能、风险”创建必修。核对过去多次替同事加班是否在拒绝前实际可见，而非摘要自述；分清对白前的预期压力与实际请求后反应，核对笔/便签/票根当前持有和落点。叙事拍可多镜，拆镜与数秒窗口留后续导演和局部表演，不默认已完成最终视频提示词、图片或媒体。独立核查，不根据旧审查disposition直接宣布通过。
"""
    cap=6000 if len(ctx["script"]["beats"])<=7 else 11000
    wire=base.request("director",[{"role":"system","content":prompt},
        {"role":"user","content":json.dumps(ctx,ensure_ascii=False)}],None,cap)
    wire["input_provenance"]={"raw_sha256":ctx["script_revision_source"]["raw_sha256"],
        "projection":"canonical complete actions and dialogue; omit duplicate screenplay_markdown only",
        "reference_pack_sha256":base.digest(ctx["reference_pack"])}
    return ctx,wire
def review():
    ctx,wire=review_wire();wire["operator_binding"]=binding()
    def validate(value):
        validate_review_v6(value,ctx)
        return {"full_script_evidence_valid":True,"story_preserved":value["story_preserved"],
                "requires_assistant_evidence_verification":True,"semantic_approval":False,
                "review_context_sha256":base.digest(ctx)}
    return base.dispatch("linear_script_review_v5",wire,validate)
def decision(approved,evidence):
    if not isinstance(evidence,list) or not evidence:raise RuntimeError("explicit verified evidence required")
    ctx=context();r=base.get_call("linear_script_review_v5")
    if approved and (r["output"]["issues"] or not r["output"]["story_preserved"]):
        raise RuntimeError("unresolved required issues")
    v={"schema":"assistant_linear_script_decision/v5","context_sha256":base.digest(ctx),
       "review_sha256":base.digest(r["output"]),"approved_for_direction":approved,
       "evidence":deepcopy(evidence),"media_approval":False,"decision_source":"assistant_verified_text_evidence"}
    path=base.ROOT/"LINEAR_SCRIPT_REVIEW_DECISION_v5.json"
    if path.exists():
        if base.read(path)!=v:raise RuntimeError("v5 decision changed")
    else:base.write(path,v,True)
    return v
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd=sys.argv[1]
    if cmd=="preflight":
        w=draft_wire()
        # Actual binding is small immutable provenance, not forwarded to service.
        w["operator_binding"]={"version":VERSION,"source_manifest":{str(Path(__file__).relative_to(base.PROJECT)).replace("\\","/"):"x"*64,
           str(Path(linear.__file__).relative_to(base.PROJECT)).replace("\\","/"):"x"*64},"previous_linear_binding_sha256":"x"*64}
        n=len(json.dumps(w,ensure_ascii=False))+4096+1024+14000
        print(json.dumps({"reservation_plus_retained_review":n,"remaining_tokens":base.summary()["remaining_tokens"],
                         "within_original_budget":n<=base.summary()["remaining_tokens"],
                         "retained_allowance_is_not_guarantee_of_full_review_fit":True}))
    elif cmd in ("draft","review"):
        r=draft() if cmd=="draft" else review()
        print(json.dumps({k:r.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")},ensure_ascii=False,indent=2))
        print(json.dumps(base.summary(),ensure_ascii=False))
    else:raise SystemExit("preflight | draft | review")
