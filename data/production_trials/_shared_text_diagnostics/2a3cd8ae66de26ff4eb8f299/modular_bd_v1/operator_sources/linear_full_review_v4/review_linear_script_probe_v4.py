"""Full-script v6 review sized for the actual 14-beat new model draft."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as base
from scripts import run_linear_script_probe_v3 as op
from src.content_factory.creative_review_v6 import build_review_prompt,validate_review_v6
VERSION="linear_full_review_v4"
def binding():
    op.binding()
    path=Path(__file__).resolve()
    h=base.file_hash(path)
    manifest={"version":VERSION,"path":str(path),"sha256":h,"linear_operator":base.read(op.BINDING)}
    bind=base.ROOT/"LINEAR_REVIEW_BINDING_v4.json"
    snap=base.ROOT/"operator_sources"/VERSION/path.name
    if bind.exists():
        if base.read(bind)!=manifest:raise RuntimeError("review operator changed")
    else:
        snap.parent.mkdir(parents=True,exist_ok=True)
        with snap.open("xb") as f:f.write(path.read_bytes())
        base.write(bind,manifest,True)
    if base.file_hash(snap)!=h:raise RuntimeError("review snapshot changed")
    return manifest
def review_context():
    # All actual model-authored actions and dialogues are retained in the verified
    # canonical projection. The raw response stays immutable in call 46; it is
    # bound by its hash rather than repeated in the same full review request.
    ctx=op.context()
    ctx.pop("raw_linear_script")
    return ctx
def wire():
    ctx=review_context()
    prompt=build_review_prompt(ctx)+"""
script由完整新模型稿steps顺序无损映射；真实顺序before→首句dialogue→during→次句dialogue→after，空槽“（无新增动作）”不代表追加行动。每项pass/fail至少引用该拍script.beats.N的真实正文叶子；assets若检查manifest，也需本拍正文。quote截必要逐字片段，reason简短具体。
叙事拍可含多个必要镜头，由后续导演分配，不能以一拍多观察对象本身报创作错误。独立检查票根和便签数量/初态/去向、拿包实际位置、拒绝前目光准备和说后听者反应、笔的当前持有与结尾重新写字、结尾主动者。program求和和格式通过不证明内容通过。不可假定实际图片已选定或被导演看到。
"""
    return ctx,base.request("director",[{"role":"system","content":prompt},
        {"role":"user","content":json.dumps(ctx,ensure_ascii=False)}],None,11000)
def run():
    ctx,request=wire();request["operator_binding"]=binding()
    def validate(value):
        validate_review_v6(value,ctx)
        return {"full_script_evidence_valid":True,"story_preserved":value["story_preserved"],
            "requires_assistant_evidence_verification":True,"semantic_approval":False,
            "review_context_sha256":base.digest(ctx)}
    return base.dispatch("linear_script_review_v4",request,validate,8000)
def decision(approved,evidence):
    if not isinstance(evidence,list) or not evidence:
        raise RuntimeError("assistant decision requires explicit verified evidence")
    binding();ctx=review_context();r=base.get_call("linear_script_review_v4")
    if approved and (r["output"]["issues"] or not r["output"]["story_preserved"]):
        raise RuntimeError("unresolved required issues")
    value={"schema":"assistant_linear_script_decision/v4","context_sha256":base.digest(ctx),
        "review_sha256":base.digest(r["output"]),"approved_for_direction":approved,
        "evidence":deepcopy(evidence),"decision_source":"assistant_verified_text_evidence","media_approval":False}
    path=base.ROOT/"LINEAR_SCRIPT_REVIEW_DECISION_v4.json"
    if path.exists():
        if base.read(path)!=value:raise RuntimeError("decision changed")
    else:base.write(path,value,True)
    return value
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1]=="preflight":
        ctx,request=wire()
        remaining=base.summary()["remaining_tokens"]
        n=len(json.dumps(request,ensure_ascii=False))+11000+1024+8000
        print(json.dumps({"reservation_plus_retained_allowance":n,"remaining_reported_tokens":remaining,
                         "within_original_budget":n<=remaining,"max_output_tokens":11000,
                         "coverage_checks":len(ctx["script"]["beats"])*6,"reference_pack_in_actual_request":bool(ctx.get("reference_pack"))}))
    elif sys.argv[1]=="review":
        r=run()
        print(json.dumps({k:r.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")},ensure_ascii=False,indent=2))
        print(json.dumps(base.summary(),ensure_ascii=False))
    else:raise SystemExit("preflight | review")
