"""Fail closed before preparing media from a visual-performance revision."""
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[2]

def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def validate_authorized_failure_cycle(cycle_record, plan, ledger, parent_ledger=None):
    """Validate either the legacy one-shot S08 reset or an approved shared repair cycle."""
    if cycle_record.get("schema")=="authorized_video_failure_continuation/v1":
        valid=(cycle_record.get("script_family")==ledger.get("script_family")
            and cycle_record.get("authorized_limit")==ledger.get("limit")==10
            and cycle_record.get("authorization")=="可以清空之前的10次再次测试10次吗"
            and cycle_record.get("target_shot")==plan.get("shot_id"))
        if parent_ledger is not None:
            valid=valid and bool(parent_ledger.get("path")) and sha(parent_ledger["path"])==parent_ledger.get("sha256")
        return valid
    if cycle_record.get("schema")=="authorized_video_revision_cycle/v1":
        shots=cycle_record.get("authorized_shots")
        parent=cycle_record.get("previous_ledger",{})
        return (cycle_record.get("script_family")==ledger.get("script_family")
            and cycle_record.get("authorized_limit")==ledger.get("limit")==10
            and cycle_record.get("user_authorization")=="允许：新增10次失败上限"
            and isinstance(shots,list) and plan.get("shot_id") in shots
            and bool(parent.get("path")) and sha(parent["path"])==parent.get("sha256"))
    return False

def validate_text(script, director):
    beats=script["beats"];shots=director["shots"]
    if sum(x["duration_seconds"] for x in beats)!=script["duration_seconds"]:
        raise ValueError("script duration mismatch")
    if sum(x["duration_seconds"] for x in shots)!=director["total_seconds"]:
        raise ValueError("director duration mismatch")
    if director["total_seconds"]!=script["duration_seconds"]:
        raise ValueError("script/director total mismatch")
    if director["characters"]!=script["characters"]:
        raise ValueError("character identity changed")
    ids=[s["id"] for s in shots]
    if len(set(ids))!=len(ids):
        raise ValueError("duplicate shot")
    allocations={b["id"]:0 for b in beats}
    dialogue=[]
    for s in shots:
        duration=s["duration_seconds"]
        if type(duration) is not int or not 4<=duration<=15:
            raise ValueError("invalid shot duration")
        if len(s["beat_ids"])!=1 or s["beat_ids"][0] not in allocations:
            raise ValueError("ambiguous beat allocation")
        allocations[s["beat_ids"][0]]+=duration
        window=s["reaction_window"]
        if not 0<=window["start_seconds"]<window["end_seconds"]<=duration:
            raise ValueError("reaction window outside shot")
        for q in s["dialogue"]:
            if q["text"] not in s["prompt"]:
                raise ValueError("prompt lost dialogue")
        dialogue.extend(s["dialogue"])
    if allocations!={b["id"]:b["duration_seconds"] for b in beats}:
        raise ValueError("beat timing changed")
    if dialogue!=[q for b in beats for q in b["dialogue"]]:
        raise ValueError("dialogue changed")
    return {"shots":len(shots),"seconds":director["total_seconds"]}

def validate_accepted(run):
    run=Path(run).resolve()
    final=read(run/"TEXT_ACCEPTANCE.json")
    if final.get("decision")!="passed":
        raise ValueError("text not accepted")
    paths={}
    for key in ("script","director","independent_review","review_request","assistant_review"):
        b=final["bindings"][key];p=Path(b["path"]).resolve()
        p.relative_to(run)
        if sha(p)!=b["sha256"]:
            raise ValueError("accepted source changed: "+key)
        paths[key]=p
    reviewer=read(paths["independent_review"])
    if reviewer.get("decision")!="passed":
        raise ValueError("independent review did not pass")
    request=read(paths["review_request"])
    for k,target in (("revised_script","script"),("director","director")):
        b=request["bindings"][k]
        if Path(b["path"]).resolve()!=paths[target] or b["sha256"]!=sha(paths[target]):
            raise ValueError("review targets wrong revision")
    assistant=read(paths["assistant_review"])
    if assistant.get("decision")!="passed" or assistant.get("director_sha256")!=sha(paths["director"]) or assistant.get("script_sha256")!=sha(paths["script"]):
        raise ValueError("assistant review wrong version")
    return validate_text(read(paths["script"]),read(paths["director"]))


def check_call_budget(state, reserve_tokens=35000):
    """Disable only the authorized local call cap; never reset usage."""
    enabled=state.get("performance_revision_call_limit_enabled",True)
    limit=state.get("max_calls")
    if enabled and limit is not None and state["calls_started"]>=limit:
        raise ValueError("local call count limit reached")
    used=sum(int(row.get("usage",{}).get("total_tokens",0)) for row in state.get("stages",[]))
    if used+reserve_tokens>state["max_total_tokens"]:
        raise ValueError("shared token budget reached")
    return {"calls_started":state["calls_started"],"tokens_used":used,"call_limit_enabled":enabled}



def visual_preview_allowed(plan, review, prior_plan):
    binding=plan.get("visual_first_authorization")
    if not binding or prior_plan.get("visual_first_authorization")!=binding:
        return False
    if sha(binding["path"])!=binding["sha256"]:
        raise ValueError("visual-first authorization changed")
    auth=read(binding["path"])
    series=Path(auth["series_directory"]).resolve()
    if plan.get("first_frame"):
        Path(plan["first_frame"]["path"]).resolve().relative_to(series)
    else:
        for item in plan.get("references",[]):
            Path(item["image"]["path"]).resolve().relative_to(series)
    if (auth.get("authorization")!="允许本片先完成画面，声音口型留待整片审查"
        or auth.get("story_sha256")!=plan["sources"]["screenplay"]["sha256"]
        or prior_plan["sources"]["screenplay"]!=plan["sources"]["screenplay"]
        or auth.get("style")!="photorealistic_cinema"):
        return False
    required=("identity","spatial_layout","props_and_hands","action_pace","cut_continuity","visual_storytelling")
    checks=review.get("checks",{})
    return (review.get("decision")=="visual_passed_audio_pending"
            and all(checks.get(k) is True for k in required)
            and all(k in checks and checks[k] in (None,True) for k in ("voice","speech_pace","lip_sync"))
            and not any(v is False for v in checks.values()))

def validate_performance_video_plan(plan):
    run=Path(plan["performance_run"]).resolve()
    validate_accepted(run)
    accepted=read(run/"TEXT_ACCEPTANCE.json")
    direction=read(accepted["bindings"]["director"]["path"])
    shots=direction["shots"]
    matches=[(i,s) for i,s in enumerate(shots) if s["id"]==plan["shot_id"]]
    if len(matches)!=1:
        raise ValueError("shot not in accepted director plan")
    index,shot=matches[0]
    expected_prompt=shot["prompt"]
    assets_path=run/"ASSETS_ACCEPTED.json"
    if plan.get("style_revision"):
        binding=plan["style_revision"]
        revision_path=Path(binding["path"]).resolve()
        revision_path.relative_to(run)
        if sha(revision_path)!=binding["sha256"]:
            raise ValueError("style revision changed")
        revision=read(revision_path)
        if revision.get("decision")!="passed" or revision.get("authorization")!="改成写实电影风":
            raise ValueError("style revision not authorized and reviewed")
        if revision.get("director_sha256")!=accepted["bindings"]["director"]["sha256"]:
            raise ValueError("style revision wrong director")
        old=revision["old_prefix"];new=revision["new_prefix"]
        if not old or not new or not expected_prompt.startswith(old):
            raise ValueError("style replacement must match original prefix")
        expected_prompt=new+expected_prompt[len(old):]
        if revision["shot_prompts"].get(shot["id"])!=expected_prompt:
            raise ValueError("style amendment altered shot content")
        asset_binding=revision["assets_accepted"]
        assets_path=Path(asset_binding["path"]).resolve()
        assets_path.relative_to(revision_path.parent)
        if sha(assets_path)!=asset_binding["sha256"] or read(assets_path).get("decision")!="passed":
            raise ValueError("style assets not accepted")
        if plan["sources"].get("assets_accepted")!=asset_binding:
            raise ValueError("plan uses wrong style assets")
    if plan["prompt"]!=expected_prompt or plan["duration_seconds"]!=shot["duration_seconds"]:
        raise ValueError("video prompt/timing differs from accepted shot")
    for key,source in (("screenplay","script"),("storyboard","director")):
        if plan["sources"][key]!=accepted["bindings"][source]:
            raise ValueError("video source differs from text acceptance")
    for row in read(assets_path)["assets"]:
        for key in ("image","review"):
            if sha(row[key]["path"])!=row[key]["sha256"]:
                raise ValueError("accepted asset changed")
        review=read(row["review"]["path"])
        if review.get("decision")!="passed" or review.get("image_sha256")!=row["image"]["sha256"]:
            raise ValueError("asset not passed")
    if index:
        previous=plan.get("previous_segment")
        if not previous:
            raise ValueError("previous segment approval required")
        for key in ("receipt","review"):
            if sha(previous[key]["path"])!=previous[key]["sha256"]:
                raise ValueError("previous segment record changed")
        receipt=read(previous["receipt"]["path"]);review=read(previous["review"]["path"])
        oldplan=read(receipt["plan"])
        if oldplan["shot_id"]!=shots[index-1]["id"]:
            raise ValueError("not immediate predecessor")
        video=receipt.get("video_path") or receipt.get("video")
        required=("identity","spatial_layout","props_and_hands","action_pace","cut_continuity","visual_storytelling","voice","speech_pace","lip_sync")
        fully_passed=review.get("decision")=="passed" and all(review.get("checks",{}).get(k) is True for k in required)
        preview_passed=visual_preview_allowed(plan,review,oldplan)
        if receipt.get("status")!="succeeded" or sha(video)!=receipt["video_sha256"] or review.get("video_sha256")!=receipt["video_sha256"] or not (fully_passed or preview_passed):
            raise ValueError("previous video has incomplete or failed actual review")
        if shot["cut_mode"]=="continuous" and (plan["first_frame"]["sha256"]!=receipt["last_frame_sha256"] or sha(receipt["last_frame"])!=receipt["last_frame_sha256"]):
            raise ValueError("continuous segment requires original approved tail")
    return {"shot_index":index,"shot_id":shot["id"]}


def validate_performance_reference_video_plan(plan):
    run=Path(plan["performance_run"]).resolve()
    validate_accepted(run)
    accepted=read(run/"TEXT_ACCEPTANCE.json")
    direction=read(accepted["bindings"]["director"]["path"])
    matches=[(i,s) for i,s in enumerate(direction["shots"]) if s["id"]==plan["shot_id"]]
    if len(matches)!=1:
        raise ValueError("shot not in accepted director plan")
    index,shot=matches[0]
    style_binding=plan["style_revision"]
    style_path=Path(style_binding["path"]).resolve()
    style_path.relative_to(run)
    if sha(style_path)!=style_binding["sha256"]:
        raise ValueError("reference style revision changed")
    revision=read(style_path)
    if (revision.get("decision")!="passed"
        or revision.get("director_sha256")!=accepted["bindings"]["director"]["sha256"]):
        raise ValueError("reference style revision is not authorized")
    original=shot["prompt"]
    old_prefix=revision.get("old_prefix")
    new_prefix=revision.get("new_prefix")
    if not old_prefix or not new_prefix or not original.startswith(old_prefix):
        raise ValueError("reference style replacement does not match accepted shot")
    expected_base=new_prefix+original[len(old_prefix):]
    correction=revision.get("targeted_correction")
    if correction and correction.get("shot_id")==shot["id"]:
        old_text=correction.get("old_text")
        new_text=correction.get("new_text")
        if not old_text or not new_text or expected_base.count(old_text)!=1:
            raise ValueError("targeted correction is not a single exact replacement")
        expected_base=expected_base.replace(old_text,new_text,1)
    if revision["shot_prompts"].get(shot["id"])!=expected_base:
        raise ValueError("reference style or targeted correction changed other shot content")
    reference_prefix=plan.get("reference_prompt_prefix",revision.get("reference_prompt_prefix"))
    if not isinstance(reference_prefix,str) or not reference_prefix:
        raise ValueError("missing reviewed reference prompt prefix")
    framework_binding=plan.get("prompt_framework")
    framework_text=""
    if framework_binding:
        framework_path=Path(framework_binding["path"]).resolve()
        framework_path.relative_to(ROOT)
        if sha(framework_path)!=framework_binding.get("sha256"):
            raise ValueError("Seedance action prompt framework changed")
        framework_text=framework_path.read_text(encoding="utf-8").strip()+"\n本镜头已审核剧情："
    expected_prompt=reference_prefix+framework_text+expected_base
    amended_base=expected_base
    amendment=plan.get("user_authorized_visual_amendment")
    visual_guards={
        "S03":"构图硬约束：三人从头到腰始终同时在画面内，桌面补充栏位于画面下方且完整可见，不切掉人物肩肘；林屿右手从她自己可见的右肩和肘部连续伸出，手腕、手掌、食指全程清楚属于林屿。食指指腹明确落在主合同空白补充栏的纸面内，指尖停在空白栏中部，不碰签名栏、不碰陈默的笔、不落在桌面或纸张边缘；用一个能同时看清林屿脸、完整手臂、指尖接触点和合同栏位的中近景。绝不从画面边缘、桌底或画外伸入任何手臂或手。陈默和方澄双手保持各自身体附近，不指向文件。镜头不切成仅有文件的极近景，不新增第四人、摄影师手或无主手。动作链硬约束：以相邻镜头真实画面为准。林屿指向空白补充栏时，陈默只用眼神和面部回应，不落笔。最后1秒内，陈默将笔水平平放在木桌上、紧靠主合同边缘的纸外区域；笔尖朝左下，整支笔平贴桌面，任何部分都不压在合同或其他纸张上。陈默的手松开笔后停在笔旁。最后0.5秒保持笔横放于桌上、合同未签，陈默的手从上方准备再次拿笔，匹配 S04 实际首帧。严禁笔尖接触任何纸面、落笔、书写或留下墨迹。",
        "S08":"家具与动作证据优先：以@image4的长边木桌为准，桌子近侧正面必须在第一帧清楚出现；在陈默正前方、桌沿下方明确呈现一个有把手的木抽屉，抽屉面板和把手在手开始动作前就可见。竖屏斜侧中景同时保留三张脸、桌沿、该抽屉和陈默双手，抽屉不得被椅背遮住；不要沿用@video1里与参考背景不同的桌面结构，@video1只锁定人物身份服装和三人起始座位。该镜头唯一主动作是陈默取收据并亲手关抽屉，方澄和林屿全程保持坐姿和双手静止。顺序连续完成：陈默右手抓住可见把手拉开抽屉并停住；左手从抽屉内取出一张押金收据并单独放在桌面；左手离开后，右手继续握住把手，将抽屉平稳推到与桌面齐平，停住并松手；确认抽屉保持关闭后，陈默再把桌上的收据与主合同放进账本袋并拉上拉链，最后起身。手与把手的接触、抽屉滑动的完整路径及关闭后的齐平状态均要在画面中可见；抽屉不自动移动，收据不跳变、不复制、不提前进袋。稳定机位，不切镜、不推拉、不裁掉抽屉面板或操作手。"
    }
    if plan.get("base_prompt")!=expected_base or plan.get("prompt")!=expected_prompt:
        guard=visual_guards.get(shot["id"])
        guarded=(isinstance(amendment,dict)
            and amendment.get("reason")=="user_requested_visual_defect_correction"
            and amendment.get("authorization")=="先修改下画面吧"
            and amendment.get("shot_id")==shot["id"]
            and guard
            and plan.get("base_prompt")==expected_base+guard
            and amendment.get("accepted_base_prompt_sha256")==hashlib.sha256(expected_base.encode("utf-8")).hexdigest()
            and amendment.get("amended_base_prompt_sha256")==hashlib.sha256(plan["base_prompt"].encode("utf-8")).hexdigest())
        rewrite=False
        if isinstance(amendment,dict) and amendment.get("rewrite_binding"):
            binding=amendment["rewrite_binding"]; rewrite_path=Path(binding["path"]).resolve()
            rewrite_path.relative_to(Path(plan["performance_run"]).resolve())
            if sha(rewrite_path)!=binding.get("sha256"):
                raise ValueError("visual prompt rewrite changed")
            rewrite_record=read(rewrite_path); rewritten=rewrite_record.get("prompt")
            rewrite=(rewrite_record.get("schema")=="authorized_visual_prompt_rewrite/v1"
                and rewrite_record.get("shot_id")==shot["id"]=="S08"
                and rewrite_record.get("accepted_prompt_sha256")==hashlib.sha256(expected_base.encode("utf-8")).hexdigest()
                and rewrite_record.get("authorization")=="先修改下画面吧"
                and isinstance(rewritten,str)
                and plan.get("base_prompt")==rewritten
                and amendment.get("accepted_base_prompt_sha256")==rewrite_record.get("accepted_prompt_sha256")
                and amendment.get("amended_base_prompt_sha256")==hashlib.sha256(rewritten.encode("utf-8")).hexdigest())
        if not (guarded or rewrite):
            raise ValueError("reference directives changed accepted shot content")
        amended_base=plan["base_prompt"]
    elif amendment:
        raise ValueError("unused visual amendment metadata")
    cycle=plan.get("failure_budget_cycle")
    if cycle:
        cycle_path=Path(cycle["path"]).resolve()
        if sha(cycle_path)!=cycle.get("sha256"):
            raise ValueError("failure-budget continuation cycle changed")
        cycle_record=read(cycle_path)
        ledger_for_cycle=read(plan["video_failure_ledger"])
        if not validate_authorized_failure_cycle(cycle_record,plan,ledger_for_cycle):
            raise ValueError("failure-budget continuation lacks exact user authorization")
    if plan["duration_seconds"]!=shot["duration_seconds"]:
        raise ValueError("reference video duration differs from accepted shot")
    for key,source in (("screenplay","script"),("storyboard","director")):
        if plan["sources"][key]!=accepted["bindings"][source]:
            raise ValueError("reference video source differs from text acceptance")
    asset_binding=revision["assets_accepted"]
    if plan["sources"].get("assets_accepted")!=asset_binding:
        raise ValueError("reference plan uses wrong accepted assets")
    assets_path=Path(asset_binding["path"]).resolve()
    assets_path.relative_to(style_path.parent)
    if sha(assets_path)!=asset_binding["sha256"]:
        raise ValueError("reference asset acceptance changed")
    accepted_assets=read(assets_path)
    if accepted_assets.get("decision")!="passed":
        raise ValueError("reference assets are not accepted")
    rows=accepted_assets.get("assets",[])
    refs=plan.get("references",[])
    if not 1<=len(refs)<=9:
        raise ValueError("reference list is empty or exceeds provider limits")
    accepted_by_id={row.get("asset_id"):row for row in rows}
    if len(accepted_by_id)!=len(rows):
        raise ValueError("accepted asset ids are not unique")
    now=datetime.now(timezone.utc).timestamp()
    for ref in refs:
        row=accepted_by_id.get(ref.get("asset_id"))
        if row is None:
            raise ValueError("plan references an unaccepted asset")
        for key in ("image","review","receipt"):
            binding=row[key]
            if ref.get(key)!=binding or sha(binding["path"])!=binding["sha256"]:
                raise ValueError("reference asset binding changed")
        review=read(row["review"]["path"])
        receipt=read(row["receipt"]["path"])
        if (review.get("decision")!="passed"
            or review.get("image_sha256")!=row["image"]["sha256"]
            or any(v is not True for v in review.get("checks",{}).values())):
            raise ValueError("reference image did not pass actual inspection")
        created=receipt.get("provider_created")
        if (receipt.get("status")!="downloaded"
            or receipt.get("model")!="doubao-seedream-5-0-pro-260628"
            or receipt.get("image_sha256")!=row["image"]["sha256"]
            or receipt.get("usage",{}).get("input_images")!=0
            or not str(receipt.get("original_url","")).startswith("https://")
            or not isinstance(created,(int,float))
            or not 0<=now-created<=30*24*3600):
            raise ValueError("reference image is not a fresh trusted text-to-image original")
    if index:
        previous=plan.get("previous_segment")
        if not previous:
            raise ValueError("previous segment approval required")
        for key in ("receipt","review"):
            if sha(previous[key]["path"])!=previous[key]["sha256"]:
                raise ValueError("previous reference segment record changed")
        prior_receipt=read(previous["receipt"]["path"])
        prior_review=read(previous["review"]["path"])
        prior_plan=read(prior_receipt["plan"])
        if prior_plan.get("shot_id")!=direction["shots"][index-1]["id"]:
            raise ValueError("previous reference segment is not the immediate predecessor")
        visual=("identity","spatial_layout","props_and_hands","action_pace","cut_continuity","visual_storytelling")
        if (prior_receipt.get("status")!="succeeded"
            or sha(prior_receipt["video_path"])!=prior_receipt.get("video_sha256")
            or prior_review.get("video_sha256")!=prior_receipt.get("video_sha256")
            or prior_review.get("decision")!="visual_passed_audio_pending"
            or any(prior_review.get("checks",{}).get(k) is not True for k in visual)):
            raise ValueError("previous reference segment lacks an actual visual pass")
        expected_video_reference=(shot.get("cut_mode")=="continuous" or shot.get("id") in {"S11","S16"})
        actual_video_reference=bool(plan.get("use_previous_video_reference"))
        if actual_video_reference!=expected_video_reference:
            override=plan.get("previous_video_reference_override")
            allowed_override=(shot.get("id") in {"S03","S08","S10","S16"} and not actual_video_reference and isinstance(override,dict))
            if not allowed_override:
                raise ValueError("previous video reference does not match the reviewed cut mode")
            failed_review_binding=override.get("failed_review",{})
            failed_review_path=failed_review_binding.get("path")
            if (override.get("reason") not in {"previous_video_prevented_required_scene_change","previous_video_conflicted_with_S08_composition","previous_video_conflicted_with_S03_opening_frame","previous_video_conflicted_with_S10_composition"}
                or not failed_review_path
                or sha(failed_review_path)!=failed_review_binding.get("sha256")):
                raise ValueError("scene-change retry override is not hash-bound")
            failed_review=read(failed_review_path)
            valid_s16=(shot.get("id")=="S16" and override.get("reason")=="previous_video_prevented_required_scene_change" and failed_review.get("segment_id")=="S16" and failed_review.get("decision")=="failed" and failed_review.get("checks",{}).get("spatial_layout") is False)
            valid_s08=(shot.get("id")=="S08" and override.get("reason")=="previous_video_conflicted_with_S08_composition" and failed_review.get("segment_id")=="S08" and failed_review.get("decision")=="failed" and failed_review.get("checks",{}).get("cut_continuity") is False)
            valid_s03=(shot.get("id")=="S03" and override.get("reason")=="previous_video_conflicted_with_S03_opening_frame" and failed_review.get("segment_id")=="S03" and failed_review.get("decision")=="failed" and failed_review.get("checks",{}).get("spatial_layout") is False)
            valid_s10=(shot.get("id")=="S10" and override.get("reason")=="previous_video_conflicted_with_S10_composition" and failed_review.get("segment_id")=="S10" and failed_review.get("decision")=="failed" and failed_review.get("checks",{}).get("spatial_layout") is False)
            if not ((valid_s16 or valid_s08 or valid_s03 or valid_s10) and failed_review.get("next_state")=="retry_current_segment"):
                raise ValueError("reference override lacks a qualifying visual failure")
        if expected_video_reference:
            url=prior_receipt.get("final",{}).get("content",{}).get("video_url")
            if not isinstance(url,str) or not url.startswith("https://"):
                raise ValueError("previous segment lacks a provider video URL")
        first_frame=plan.get("first_frame")
        if first_frame:
            if plan.get("reference_mode")!="exclusive_first_frame" or plan.get("use_previous_video_reference"):
                raise ValueError("first-frame media role must be exclusive under Seedance reference rules")
            if (shot.get("cut_mode")!="continuous"
                or Path(first_frame.get("path","")).resolve()!=Path(prior_receipt.get("last_frame","")).resolve()
                or first_frame.get("sha256")!=prior_receipt.get("last_frame_sha256")
                or sha(first_frame["path"])!=first_frame.get("sha256")):
                raise ValueError("first-frame reference must equal the approved immediate predecessor tail")
        elif shot.get("cut_mode")=="continuous" and plan.get("require_source_bound_first_frame"):
            raise ValueError("continuous revision requires the source-bound first frame")
    elif plan.get("previous_segment") or plan.get("use_previous_video_reference"):
        raise ValueError("opening shot must not bind a previous segment")
    return {"shot_index":index,"shot_id":shot["id"],"references":len(refs)}


def reserve_performance_video(plan, receipt_path):
    ledger_path=Path(plan["video_failure_ledger"]).resolve()
    ledger=read(ledger_path)
    cycle=plan.get("failure_budget_cycle")
    if cycle:
        cycle_path=Path(cycle["path"]).resolve()
        if sha(cycle_path)!=cycle.get("sha256"):
            raise ValueError("failure-budget continuation cycle changed")
        cycle_record=read(cycle_path)
        parent=cycle_record.get("previous_ledger",{})
        if not validate_authorized_failure_cycle(cycle_record,plan,ledger,parent):
            raise ValueError("invalid user-authorized failure-budget continuation")
        failed=0
    else:
        failed=len(ledger["inherited_failed_outputs"])
    for old in ledger["inherited_failed_outputs"]:
        if sha(old["path"])!=old["sha256"]:
            raise ValueError("inherited failure evidence changed")
    for attempt in ledger["attempts"]:
        recpath=Path(attempt["receipt"])
        if not recpath.exists():
            raise ValueError("unresolved prior video reservation")
        rec=read(recpath)
        if rec.get("status")=="rejected_pre_generation" and rec.get("task_created") is False:
            continue
        review_path=recpath.parent/"media_review.json"
        if rec.get("status")!="succeeded" or not review_path.exists():
            raise ValueError("resolve prior video outcome/review before another submission")
        review=read(review_path)
        if review.get("video_sha256")!=rec.get("video_sha256"):
            raise ValueError("prior media review is stale")
        if review.get("decision")=="failed":
            if not cycle or attempt.get("failure_budget_cycle")==cycle_record.get("cycle_id"):
                failed+=1
        elif review.get("decision")!="passed":
            if visual_preview_allowed(plan,review,read(rec["plan"])):
                continue
            # A reviewed visual preview may be retired when the user changes style.
            # This never upgrades its audio review or permits continuation from its tail.
            binding=attempt.get("supersession")
            if not binding or not plan.get("style_revision"):
                raise ValueError("prior video review still pending")
            if sha(binding["path"])!=binding["sha256"]:
                raise ValueError("supersession changed")
            retirement=read(binding["path"])
            visual=("identity","spatial_layout","props_and_hands","action_pace","cut_continuity","visual_storytelling")
            if (retirement.get("reason") not in {"user_requested_style_replacement","user_requested_reference_image_pipeline"}
                or retirement.get("authorization")!="改成写实电影风"
                or retirement.get("receipt_sha256")!=sha(recpath)
                or retirement.get("review_sha256")!=sha(review_path)
                or retirement.get("replacement_style")!=plan["style_revision"]
                or review.get("decision")!="visual_passed_audio_pending"
                or any(review.get("checks",{}).get(k) is not True for k in visual)
                or any(v is False for v in review.get("checks",{}).values())):
                raise ValueError("invalid visual preview supersession")
    limit=cycle_record["authorized_limit"] if cycle else ledger["limit"]
    if failed>=limit:
        raise ValueError("same-script video failure limit reached")
    ledger["attempts"].append({"shot_id":plan["shot_id"],"receipt":str(Path(receipt_path).resolve()),"failed_outputs_before":failed,"failure_budget_cycle":cycle_record.get("cycle_id") if cycle else None})
    ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding="utf-8")

