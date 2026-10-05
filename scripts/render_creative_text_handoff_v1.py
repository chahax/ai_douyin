"""Read-only deterministic presentation of an already finalized text handoff."""
from pathlib import Path
import json,math,sys,hashlib


def read(p):return json.loads(p.read_text(encoding="utf-8-sig"))


def render(root):
    root=Path(root).resolve()
    handoff=read(root/"PRODUCTION_HANDOFF.json")
    if not handoff.get("text_production_handoff_complete"):
        raise ValueError("complete reviewed text handoff required")
    raw=read(root/"FULL_SCRIPT.json");d=read(root/"WHOLE_FILM_DIRECTION.json")
    c=read(root/"COMPILED_PERFORMANCE.json");assets=read(root/"STATIC_ASSET_DEFINITIONS.json")
    display=read(root/"REVIEWED_EXECUTION_VIEW.json") if (root/"REVIEWED_EXECUTION_VIEW.json").exists() else c['storyboard']
    shots=[s for b in d["beats"] for s in b["shots"]]
    steps={f"raw_linear_script.beats.{i}.steps.{j}":s for i,b in enumerate(raw["beats"]) for j,s in enumerate(b["steps"])}
    lines=[f"# 《{raw['title']}》完整导演与表演审阅版", "",f"{len(shots)}镜，实际文本编译{c['total_duration_seconds']:.2f}秒。", "",
        "全文文本审查与状态编译已完成；创作质量等待用户确认。人物、场景样板和实际视频尚未生成。", "", "## 整片情绪与结尾", "",str(d["emotional_arc"]), "",str(d["ending_intent"]), ""]
    timing=[];offset=0
    for index,(s,cs) in enumerate(zip(shots,display["shots"]),1):
        end=offset+cs["duration_seconds"]
        lines += [f"## 第{index}镜：{offset:.2f}–{end:.2f}秒", "", "新增信息："+s["new_information"], "", "观察对象："+s["observation_object"], "", "画面："+s["composition"]+"；"+s["camera"], "", "切镜理由："+s["cut_reason"], "", "| 全片时间 | 原文与实际表演 |", "| --- | --- |"]
        seen=set()
        for e in [e for e in c["source_trace"] if e["shot_id"]==s["shot_id"]]:
            step=steps[e["source_ref"]]
            original=(step["speaker"]+"：“"+step["text"]+"”") if step["kind"]=="dialogue" else (step["text"] if e["source_ref"] not in seen else "原动作继续")
            seen.add(e["source_ref"])
            perf=e["actual_scheduled_payload"]["performance"]
            text=(original+"<br>表演："+perf).replace("|","\\|").replace("\n","<br>")
            lines.append(f"| {e['start']:.2f}–{e['end']:.2f}秒 | {text} |")
        windows=[w for w in c["performance_checks"] if any(q["id"]==w["requirement_id"] for q in s["performance_requirements"])]
        for w in windows:
            lines += ["",f"声明反应窗口 {w['requirement_id']}：{w['start']:.2f}–{w['end']:.2f}秒（{w['end']-w['start']:.2f}秒）。"]
        lines += ["", "跨镜首态："+cs["start_state"], "", "跨镜尾态："+cs["end_state"], ""]
        timing.append({"shot":s["shot_id"],"start":offset,"end":end,"duration":cs["duration_seconds"],"integer_provider_seconds":math.ceil(cs["duration_seconds"]),"configured_seedance_2_0_max15_exceeded":math.ceil(cs["duration_seconds"])>15,"below_configured_min4":cs["duration_seconds"]<4})
        offset=end
    lines += ["## 用户确认与后续", "", "请确认故事、拒绝前后的情绪、他接回工作和她离开的结尾是否成立。实际确认后保存用户原话、本文SHA、范围及待修问题。", "", "随后先确定少量人物/场景审美样板，用户选定的实际图片回传导演，重验构图与时长适配；视频每段生成保存后等用户人工审核。"]
    media=["# 资产与视频制作交接条件", "", "这是完整文本交接的后续执行条件，尚未授权或派发媒体请求。", "", "## 静态资产定义", ""]
    for category in ["characters","props"]:
        media += ["### "+("人物" if category=="characters" else "道具"), ""]
        for row in assets[category]:media.append("- "+json.dumps(row,ensure_ascii=False))
        media.append("")
    media += ["### 场景", "",json.dumps(assets["scene"],ensure_ascii=False,indent=2), "", "## 每镜时长适配", "", "| 镜 | 文本实际秒数 | 最少整数秒 | 本地2.0配置15秒上限 |", "| --- | --- | --- | --- |"]
    for t in timing:media.append(f"| {t['shot']} | {t['duration']:.2f} | {t['integer_provider_seconds']} | {'超过，待确定连续对白承载方案' if t['configured_seedance_2_0_max15_exceeded'] else '范围内；未验证实际服务'} |")
    media += ["", "config/seedance_models.json在本地给2.0系列4–15秒、2.5为4–30秒；本地配置不是服务端能力或生产质量证明。长句不能为适配15秒偷偷删字、加快或拆开，需先验证可承载时长的媒体方案。小于4秒的镜也需在实际段落方案中处理，不能自动塞无意义等待。", "", "## 执行顺序", "", "1. 用户确认这份完整文本与情绪安排，记录真实原话、版本和SHA。", "2. 核对媒体授权后只出少量审美样板，确认画风/人物/办公室；选定后生成或复用资产。", "3. 保存实际选定图片的文件、SHA和来源，回传导演实际请求，重验画面、动作、跨镜状态和段长。", "4. 生成当前视频段，核对接口成功及文件完整保存，状态awaiting_human_review。", "5. 用户明确通过该段后，才用服务返回的原始尾帧继续；不通过则修正并重生成当前段。", "6. 整片合成仍交用户审核；发布另行授权与核验。", "", "当前选定图片0、媒体调用0，助手不抽帧、听看、ASR或调用音画审核模型；原70未知结果和64010预留继续保留。"]
    extra={"schema":"text_handoff_media_requirements/v1","text_handoff_sha256":hashlib.sha256((root/"PRODUCTION_HANDOFF.json").read_bytes()).hexdigest(),"shot_timings":timing,"actual_selected_images":[],"selected_images_returned_to_director":False,"duration_capability_status":"pending_media_plan_validation","user_content_confirmation":None,"user_aesthetic_confirmation":None,"media_calls":0,"no_automatic_media_dispatch":True}
    outputs={"CREATIVE_REVIEW_COPY.md":"\n".join(lines)+"\n","MEDIA_HANDOFF_REQUIREMENTS.md":"\n".join(media)+"\n","MEDIA_HANDOFF_REQUIREMENTS.json":json.dumps(extra,ensure_ascii=False,indent=2)+"\n"}
    for name,value in outputs.items():
        p=root/name
        if p.exists() and p.read_text(encoding="utf-8")!=value:raise ValueError("existing output differs: "+name)
        if not p.exists():p.write_text(value,encoding="utf-8")
    return {"paths":[str(root/n) for n in outputs],"source_model_content_changed":False,"media_calls":0}


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(render(sys.argv[1]),ensure_ascii=False,indent=2))
