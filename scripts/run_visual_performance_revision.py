"""Source-bound visual-performance revision using existing role clients and shared parent budget."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,sys,argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory.creative_workflow_roles import CreativeRoleClients
from src.content_factory.creative_workflow_contract import parse_json_object
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding="utf-8-sig"))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding="utf-8")
def main():
    ap=argparse.ArgumentParser();ap.add_argument("stage",choices=["writer","director","check"]);ap.add_argument("--run-dir",required=True);ap.add_argument("--prepare-only",action="store_true");ap.add_argument("--attempt");ap.add_argument("--repair-feedback");ap.add_argument("--review-role",choices=["writer","director"],default="writer");a=ap.parse_args()
    run=Path(a.run_dir);parent=ROOT/"data/creative_workflows/reference_benchmark_20260925_v3"
    statepath=parent/"state.json";state=read(statepath)
    src=parent/"ASSISTANT_REVISED_SCREENPLAY.json";ref=run/"REFERENCE_VISUAL_AND_SCRIPT_REVIEW.md"
    bindings={"script":{"path":str(src),"sha256":sha(src)},"visual_review":{"path":str(ref),"sha256":sha(ref)}}
    common="只输出一个完整JSON对象，不使用markdown代码块。只借参考的摄影表演方法，禁止把原片的关心、诈骗、电话剧情移入合同故事。保留陈默/林屿/方澄、续租忽视提醒、两份完整合同各自持有、深夜获知风险、三个月后退出意愿与律师函、携材料去法院窗口的主线；不新增裁决、退款完成或法律效果保证。成年人物年龄沿用30/29/35，发色服装稳定。叙事性动作应有可见刺激和可见结果；不是微动作越多越好。无新增背景人物担任主角。"
    payload={"source_script":read(src),"review":ref.read_text(encoding="utf-8")}
    writer_dir=read(run/"writer_selection.json")["folder"] if (run/"writer_selection.json").exists() else "writer"
    director_dir=read(run/"director_selection.json")["folder"] if (run/"director_selection.json").exists() else "director"
    if a.stage=="writer":
        role="writer"
        instructions=common+"""你是编剧MiniMax M3。重写完整制作剧本，修复问题单全部编剧问题。可压缩冗长停留，不为凑157秒拖慢动作；目标100至135秒，具体服从对白和动作成立。律师函仅表达甲方声称有欠费并要求支付，不推定该诉求合法或已生效。用一条简短画内台词让观众知道具体新冲突。给陈默忽略提醒一个本稿内可见理由（保档期/原租金），不能靠旁白。用真实骑缝印章完成印章动作，禁止拇指变印章。JSON键title,premise,duration_seconds,characters,beats,revision_notes。characters为name,age,hair,outfit。beats为id,duration_seconds,location,trigger,goal,choice,before,during,after,dialogue,emotion_window。dialogue为speaker,text,mode，mode=onscreen或phone_voice。emotion_window为stimulus,pre_seconds,reaction_seconds,visible_change。输出完整可读剧本，跨场景道具不能瞬移；本拍对象位置与动作可及。"""
    elif a.stage=="director":
        role="director";p=run/writer_dir/"candidate.json";rv=run/writer_dir/"assistant_review.json"
        if read(rv).get("decision")!="passed" or read(rv).get("candidate_sha256")!=sha(p):raise ValueError("writer review required")
        payload["revised_script"]=read(p);bindings["revised_script"]={"path":str(p),"sha256":sha(p)}
        instructions=common+"""你是导演DeepSeek。只依据revised_script进行摄影表演设计，不改事件和对白。写实成人比例的2.5D电影绘画风，不改成年年龄与身份。每个生成段4到15整数秒，可以把一个beat拆多段，但必须保留逐字对白、所有动作和顺序。首段不含台词可用4至6秒真实建立，不要无因关心反应。连续镜头不准偷偷叠化单眼特写。尾帧要保留下一段所需人物身份；换场先声明需要独立受审首图。JSON键style,characters,shots,total_seconds,asset_prompts。shots每项id,beat_ids,duration_seconds,location,trigger,performance,dialogue,composition,camera,opening_state,ending_state,gaze_target,props_before,props_after,reaction_window,cut_mode,prompt。cut_mode=continuous或scene_change。reaction_window给区间和可见变化。prompt是逐段完整Seedance中文提示词，必须与本条全部字段一致，明确自然语速、动作顺序和首尾状态。asset_prompts给character_turnarounds列表以及backgrounds列表，每项id,prompt,review_checks。另给opening_frame对象id,prompt,review_checks：首镜起点，动作尚未完成，人物脸部/手/两份合同可见，三人身份服装年龄正确，不把图做成多格。所有资产prompt包含画风/身份/构图/光源/当前状态/约束。"""
    else:
        role=a.review_role;payload["revised_script"]=read(run/writer_dir/"candidate.json");payload["director"]=read(run/director_dir/"candidate.json")
        payload.pop("source_script",None)
        payload.pop("review",None)
        payload["visual_reference_scope"]="只借景别、空间纵深、可见刺激后的表情变化、真实物理动作；不借参考故事。历史问题清单不是当前稿事实，请只引用当前稿中的确切证据。"
        bindings["revised_script"]={"path":str(run/writer_dir/"candidate.json"),"sha256":sha(run/writer_dir/"candidate.json")}
        bindings["director"]={"path":str(run/director_dir/"candidate.json"),"sha256":sha(run/director_dir/"candidate.json")}
        payload["review_boundary"]="只审核本次revised_script和director。旧稿仅为历史，不再提供。相邻末态等于初态是正常连续性；performance与reaction_window可描述同一个动作；场景切换允许省略路程。禁止凭空作法律程序断言。总时长请逐项相加。已交付给角色的律师函由该角色携带不构成逻辑错误。将真正缺动作、状态矛盾、时长不足与正常电影省略区分。"
        instructions=common+"""你是独立上下文的文本审核员，不承认前轮通过。检查修改后的剧本与导演稿：因果、物理动作、道具归属、身份年龄、对白逐字完整、每段4-15秒、无借入参考剧情、表情动作刺激时序、首尾可接续。JSON键decision( passed/needs_revision ),issues(每项location,evidence,impact,fix),limitations。有主要问题必须needs_revision。仅把具体矛盾、动作缺失、确定无法容纳的对白动作列入issues；有依据的执行风险可列observations，不凭可能难生成就无限延长。passed只表示可进入媒体验证，绝不表示画面通过。每项issue增加severity(blocking/major/minor)，引用当前字段；不要把正常前后接续或另一镜才执行的动作当成冲突。"""
    if a.repair_feedback:
        fp=Path(a.repair_feedback);payload["mandatory_repair"]=read(fp);payload["rejected_candidate"]=read(run/(director_dir if a.stage=="director" else writer_dir)/"candidate.json");instructions+=" 必须逐条处理mandatory_repair。输出本阶段要求的完整对象，保留当前稿人物锁与事件；不要复用第一轮旧候选。";bindings["repair_feedback"]={"path":str(fp),"sha256":sha(fp)}
    folder=run/(a.attempt or a.stage);folder.mkdir(exist_ok=True);receipt=folder/"receipt.json"
    if receipt.exists():raise ValueError("stage already reserved; inspect existing outcome")
    total=sum(int(x.get("usage",{}).get("total_tokens",0)) for x in state.get("stages",[]))
    from src.content_factory.performance_revision_gate import check_call_budget
    check_call_budget(state)
    for b in bindings.values():
        if sha(b["path"])!=b["sha256"]:raise ValueError("source changed")
    messages=[{"role":"system","content":instructions},{"role":"user","content":json.dumps(payload,ensure_ascii=False)}]
    save(folder/"request.json",{"role":role,"messages":messages,"bindings":bindings})
    if a.prepare_only:
        print(json.dumps({"stage":a.stage,"status":"prepared_not_sent","request":str(folder/"request.json"),"request_sha256":sha(folder/"request.json")},ensure_ascii=False));return
    rec={"status":"reserved","role":role,"parent_task_id":state["logical_task_id"],"request_sha256":sha(folder/"request.json"),"created_at":datetime.now(timezone.utc).isoformat()}
    save(receipt,rec)
    state["calls_started"]+=1;state.setdefault("performance_revision_calls",[]).append({"stage":a.stage,"receipt":str(receipt),"status":"reserved"});save(statepath,state)
    try:
        result=CreativeRoleClients().call(role,messages,max_tokens=18000,temperature=.35,thinking=None)
        (folder/"raw.txt").write_text(result.text,encoding="utf-8");save(folder/"response_metadata.json",result.metadata)
        if result.metadata.get("finish_reason")=="length":raise ValueError("truncated response")
        value=parse_json_object(result.text);save(folder/"candidate.json",value)
        rec.update(status="candidate_pending_review",usage=result.metadata,candidate_sha256=sha(folder/"candidate.json"))
        state=read(statepath);state.setdefault("stages",[]).append({"name":"performance_revision_"+a.stage,"role":role,"usage":result.metadata,"output_sha256":rec["candidate_sha256"]});save(statepath,state)
    except Exception as exc:
        rec.update(status="failed_or_unknown",error=str(exc));raise
    finally:save(receipt,rec)
    print(json.dumps({"stage":a.stage,"status":rec["status"],"path":str(folder/"candidate.json")},ensure_ascii=False))
if __name__=="__main__":main()
