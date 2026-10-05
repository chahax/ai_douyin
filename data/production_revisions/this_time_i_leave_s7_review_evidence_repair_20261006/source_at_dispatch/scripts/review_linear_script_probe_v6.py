"""Compact complete-script review instructions; unchanged v6 evidence validation."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as base
from scripts import revise_linear_script_probe_v5 as prior
from src.content_factory.creative_review_v6 import validate_review_v6
VERSION="compact_complete_script_review_operator_v6"
PROMPT="""你是DeepSeek独立文字审核员，只审核完整剧本；不代写、不评分，不宣称图片、声音、口型或媒体通过。
仅返回JSON，顶层恰为story_preserved(bool)、issues(array)、suggestions(array)、calibration_focus(array)、coverage(array)。有必修issues则story_preserved=false，否则true。
issues项：id、owner(writer/director)、location(现有B编号)、severity(blocking/major)、rule、evidence、contradiction、impact、proposal、evidence_refs。只列有真实正文证据的硬约束或叙事/制作错误，同根因合并；不凭“可能/风险”或主观动作数量发明禁令。审美放suggestions项location/proposal/reason。
coverage逐一覆盖script全部beat且各一次，每行{id,checks}；checks恰含requirements/timing/continuity/dialogue_timing/first_frame/assets。每项恰为{status:pass|fail|not_applicable,reason,evidence_refs,issue_ids}。fail关联已列issues；其他issue_ids=[]；每issue至少有一个fail关联。reason简短具体，不重复全文。
evidence_refs每项{path,quote}，path输入点分到真实字符串/数字叶子，quote必要逐字片段，不引用数组/对象。每条issue引用当前script正文。每个pass/fail须至少一条本拍script.beats.N正文证据；资产对照manifest时也不能只引全局ID。缺证据不能标pass或冒称不适用。
requirements：逐条核对creative_brief、人物关系、主题转折、结尾主动者、道具数量。实际可拍正文优先于premise/event/trigger摘要；多次替同事加班需拒绝前自然对白或可见后果兑现。必须检查。
timing：真实播放顺序before→首句dialogue→during→次句dialogue→after；空槽无新增动作。摘要不是实际刺激。区分预期压力与已听请求后的反应，核对刺激→听到→反应→回应。反应可合法跨拍，不强制重说或塞回同拍，重要表演在正文明确。必须检查。
continuity：核对前拍末与本拍首人物位置、视线、姿态、持物者、落点、布局；有前拍引用双方。owner≠holder，摘要未在动作正文兑现不能当已发生。真正重置已完成动作才是矛盾，合理步行省略和自然小动作不自动失败；首拍核对内部初态。必须检查。
dialogue_timing：有对白列字数、可用秒数、必要串行动作与反应窗口。中文字1、拉丁词2，5单位/秒执行上限；不同人物并行不重复扣时。低于上限有反应空间不能凭偏紧/未声明语速报必修；明确停顿须核对。无对白可not_applicable。
first_frame：本次剧本可not_applicable，实际分镜首态仍待后续动作前状态核查。assets核对当前人物/道具/画风/服装/布局与manifest；剧本可not_applicable，不假定图片已选定、复用成功或被导演看过。
叙事拍可多镜；镜头拆分与确定秒数留后续导演/局部表演，不能把一拍多观察本身当错。尚无state_plan/production_design时不虚构已完成或把待后续的文件列缺失；若给计划仍须与正文对照，程序通过不是正确答案。关键表演可读性和明确停顿须查；未证实问题不变新硬条件。
calibration_focus仅列后续媒体验证项。没有issues/suggestions时相应数组为空，自己独立核查，不复制旧结论。"""
def binding():
    parent=prior.binding()
    path=Path(__file__).resolve();h=base.file_hash(path)
    value={"version":VERSION,"source_path":str(path),"source_sha256":h,"parent_binding":parent}
    bind=base.ROOT/"LINEAR_REVIEW_BINDING_v6.json"
    snap=base.ROOT/"operator_sources"/VERSION/path.name
    if bind.exists():
        if base.read(bind)!=value:raise RuntimeError("v6 review binding changed")
    else:
        snap.parent.mkdir(parents=True,exist_ok=True)
        with snap.open("xb") as f:f.write(path.read_bytes())
        base.write(bind,value,True)
    if base.file_hash(snap)!=h:raise RuntimeError("v6 review snapshot changed")
    return {"version":VERSION,"manifest_path":str(bind),"manifest_sha256":base.file_hash(bind)}
def wire():
    ctx=prior.context()
    cap=6000 if len(ctx["script"]["beats"])<=7 else 11000
    request=base.request("director",[{"role":"system","content":PROMPT},
        {"role":"user","content":json.dumps(ctx,ensure_ascii=False,separators=(",",":"))}],None,cap)
    request["operator_binding"]=binding()
    return ctx,request
def run():
    ctx,request=wire()
    def validate(value):
        validate_review_v6(value,ctx)
        return {"full_script_evidence_valid":True,"story_preserved":value["story_preserved"],
            "requires_assistant_evidence_verification":True,"semantic_approval":False,
            "review_context_sha256":base.digest(ctx),"validation_contract":"unchanged evidence_review_v6"}
    return base.dispatch("linear_script_review_v6",request,validate)
def decision(approved,evidence):
    if not isinstance(evidence,list) or not evidence:raise RuntimeError("explicit verified evidence required")
    ctx,_=wire();r=base.get_call("linear_script_review_v6")
    if approved and (r["output"]["issues"] or not r["output"]["story_preserved"]):
        raise RuntimeError("unresolved required issues")
    v={"schema":"assistant_linear_script_decision/v6","context_sha256":base.digest(ctx),
        "review_sha256":base.digest(r["output"]),"approved_for_direction":approved,
        "evidence":deepcopy(evidence),"media_approval":False,"decision_source":"assistant_verified_text_evidence"}
    path=base.ROOT/"LINEAR_SCRIPT_REVIEW_DECISION_v6.json"
    if path.exists():
        if base.read(path)!=v:raise RuntimeError("v6 decision changed")
    else:base.write(path,v,True)
    return v
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1]=="preflight":
        ctx,w=wire();n=len(json.dumps(w,ensure_ascii=False))+w["parameters"]["max_completion_tokens"]+1024
        print(json.dumps({"review_reservation":n,"remaining_tokens":base.summary()["remaining_tokens"],
            "fits_original_budget":n<=base.summary()["remaining_tokens"],"full_script_beats":len(ctx["script"]["beats"]),
            "full_coverage_checks":len(ctx["script"]["beats"])*6,"max_output_tokens":w["parameters"]["max_completion_tokens"],
            "prompt_chars":len(PROMPT),"contract":"unchanged evidence_review_v6"},ensure_ascii=False))
    elif sys.argv[1]=="review":
        r=run()
        print(json.dumps({k:r.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")},ensure_ascii=False,indent=2))
        print(json.dumps(base.summary(),ensure_ascii=False))
    else:raise SystemExit("preflight | review")
