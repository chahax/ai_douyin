"""Versioned operator continuation; original dispatched sources stay frozen."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_modular_bd_probe as base
from src.content_factory.creative_full_script_revision import PROMPT,accept_full_script
from src.content_factory.creative_workflow_contract import WRITER_TOOL_SCHEMAS,validate_script
from src.content_factory.creative_review_v6 import build_review_prompt,validate_review_v6

OPERATOR_VERSION="modular_bd_explicit_source_review_v2"
SOURCE_FINDING={
    "id":"SOURCE_DUPLICATE_SPEECH_TIMING","location":"B3",
    "rule":"播放顺序为before→首句dialogue→during→次句dialogue→after。",
    "evidence_refs":[{"path":"script.beats.2.dialogue.0.text","quote":"这次我先走，你自己对吧。"},
                     {"path":"script.beats.2.during","quote":"方澄中近景抬头看着林屿，清楚地说出拒绝。"}],
    "contradiction":"首句拒绝已经说完，during却再次写抬头说出拒绝，正文安排与event描述的先抬头再开口不一致。",
    "request":"生成完整新稿，将开口前的抬头及目光准备放在实际台词前，during明确为听到台词后的表演，不重复同一次说话；保留两人的情绪重点及需要的观察镜头。不要手工补丁。"
}
ADDITIONAL_FINDINGS=[
    {"id":"OBSERVATION_COMPILATION_BOUNDARY","category":"compilation","location":"B1/B3/B4",
     "request":"当前编译合同每拍一个镜头，原稿有明确机位切换。请按真实观察对象变化合理拆成相邻拍，完整新稿可调整拍数和时长；保留桌面证据、说话者与听者反应、门口余白，不能删除这些观察需求来迁就编译器，也不能把多个镜头藏在camera文字里。"},
    {"id":"PHYSICAL_CONTINUITY_TO_CONFIRM","category":"state_contract","location":"B1/B2/B5",
     "request":"完整新稿明确方澄从林屿桌边到自己工位拿包的叙事衔接；林屿取方澄桌角便签时交代所依赖的可达布局或动作，不能只借切机位改变人物位置。邻桌不自动意味着必须站起；由新稿具体安排，不由程序补动作。"}
]
def binding():
    path=Path(__file__).resolve(); h=base.file_hash(path)
    dst=base.ROOT/"operator_sources"/(OPERATOR_VERSION+"_"+h[:12]+".py")
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        if base.file_hash(dst)!=h:
            raise RuntimeError("operator source changed")
    else:
        with dst.open("xb") as f:
            f.write(path.read_bytes())
    return {"version":OPERATOR_VERSION,"source_path":str(path),"source_sha256":h,"snapshot":str(dst)}
def dispatch(label,wire,validator,retain=14000):
    wire["operator_binding"]=binding()
    return base.dispatch(label,wire,validator,retain)
def revise():
    old=base.get_call("draft_v1")
    context=base.read(base.ROOT/"ORIGINAL_CONTEXT.json")
    findings={"schema":"assistant_verified_script_findings/v1","script_call":43,
         "script_sha256":base.digest(old["output"]),"issues":[SOURCE_FINDING,*ADDITIONAL_FINDINGS],
        "rejected_review_call":44,"review_evidence_gate_failed":True,
        "automatic_semantic_pass":False}
    path=base.ROOT/"ASSISTANT_SOURCE_FINDINGS_v1.json"
    if path.exists():
        if base.read(path)!=findings:raise RuntimeError("source findings differ")
    else:base.write(path,findings,True)
    schema=deepcopy(WRITER_TOOL_SCHEMAS["writer_script"])
    schema["description"]="完整剧本对象，beats直接为数组。播放顺序before→第一句对白→during→第二句对白→after；event/trigger仅摘要。对白每拍最多两句。不要在during重复已经完成的首句对白。"
    payload={"context":context,"previous_script":old["output"],"issues":findings["issues"],
             "previous_review_evidence_status":"rejected_missing_current_beat_asset_evidence",
             "revision_mode":"full_script"}
    messages=[{"role":"system","content":PROMPT+" 用指定工具提交完整新稿，不写分析。保留真实参考全文、主题和关系要求。"},
              {"role":"user","content":json.dumps(payload,ensure_ascii=False)}]
    def validate(value):
        accepted=accept_full_script(context["script"],value)
        validate_script(deepcopy(accepted),context["script"]["selected_candidate_id"],"","original")
        return {"complete_new_script":True,"semantic_approval":False,"requires_full_review":True}
    return dispatch("draft_v2",base.request("writer",messages,schema,4096),validate)
def review(index):
    context=base.revised_context(index)
    instruction=build_review_prompt(context)+"""
本次明确证据规则：coverage每拍每项pass/fail都至少引用该拍script.beats.N.下的一个真实正文叶子。assets即使已有static_visual_manifest定义引用，也必须加该拍实际人物/道具描写的正文证据，两者对照；不可只引用全局ID。quote截必要逐字片段即可，reason简短具体，不重复整段正文。严格按before→首句dialogue→during→次句dialogue→after判断；对照event摘要，不让during重新说出已完成的同一句台词。多机位要求保留在审查中，不因旧编译器一拍一镜而直接当成创作错误。
"""
    messages=[{"role":"system","content":instruction},{"role":"user","content":json.dumps(context,ensure_ascii=False)}]
    def validate(value):
        validate_review_v6(value,context)
        return {"evidence_valid":True,"story_preserved":value["story_preserved"],
                "requires_assistant_evidence_verification":True,"semantic_approval":False}
    return dispatch(f"script_review_v{index}",base.request("director",messages,None,6000),validate)
if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1]=="revise": r=revise()
    elif sys.argv[1]=="review": r=review(int(sys.argv[2]))
    else:raise SystemExit("revise | review N")
    print(json.dumps({k:r.get(k) for k in ("ordinal","label","status","response_metadata","validation","failure","validation_error")},ensure_ascii=False,indent=2))
    print(json.dumps(base.summary(),ensure_ascii=False))
