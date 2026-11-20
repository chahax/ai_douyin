"""Deterministic, source-bound generation groups and natural Seedance prompts.

Story beats, observation shots and paid requests are separate identities.
This module compiles templates only; no provider dispatch or media inspection.
"""
from __future__ import annotations
from copy import deepcopy
import json
import math
import re
from pathlib import Path
import hashlib
import httpx

from .creative_story_emotion import digest, story_media_blockers
from .seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference
from .seedance_models import ark_model

SCHEMA = "emotional_generation_plan/v1"
ARRANGEMENT = "emotional_generation_arrangement/v1"
LEAK = re.compile(r"\b(?:C\d\d|P\d\d(?:_[A-Z])?|E\d\d|SH\d\d|B\d\d)\b"
                  r"|mechanical_check|holder|surface:|程序切点|声明表演窗口|实际操作：")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_bindings(script, assets, view, compiled, brief, review):
    return {k: digest(v) for k, v in {
        "script": script, "assets": assets, "view": view,
        "compiled": compiled, "brief": brief, "review": review}.items()}


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return value


def _prose(value, removed):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("visible prose missing")
    marker = "；程序派生身体朝向："
    if marker in value:
        value, metadata = value.split(marker, 1)
        if not isinstance(json.loads(metadata), list):
            raise ValueError("unknown derived orientation metadata")
        removed.append(metadata)
    if LEAK.search(value) or "{" in value or "}" in value:
        raise ValueError("internal metadata in visible prose; revise the source projection")
    return value


def _time(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _source_steps(script, compiled, shot_ids):
    expected = {f"raw_linear_script.beats.{i}.steps.{j}": step
                for i, beat in enumerate(script["beats"])
                for j, step in enumerate(beat["steps"])}
    rows = compiled.get("source_map", [])
    if len(rows) != len(expected) or {r["source_step_ref"] for r in rows} != set(expected):
        raise ValueError("source map must cover every original step exactly once")
    result = {sid: [] for sid in shot_ids}
    for row in rows:
        if row["shot_id"] not in result:
            raise ValueError("source map refers to an unknown shot")
        step = expected[row["source_step_ref"]]
        mapped = row["source_step"]
        if any(step.get(k, "") != mapped.get(k, "") for k in ("kind", "speaker", "text")):
            raise ValueError("source step was rewritten")
        result[row["shot_id"]].append((row["source_step_ref"], step))
    return result


def _shot_block(shot, scheduled, steps, scale, offset, removed):
    # Source events are context; the timed plan below is performed once.
    lines = ["画面与机位：" + _prose(shot["composition"], removed) + "；"
             + _prose(shot["camera"], removed) + "。",
             "原事件内容（按后文时间安排演出一次，不重复操作）："]
    lines.extend(_prose(step["text"], removed) for _, step in steps if step["kind"] == "action")
    dialogue = [step for _, step in steps if step["kind"] == "dialogue"]
    lock = shot.get("dialogue_lock", [])
    if [(d["speaker"], d["text"]) for d in dialogue] != [(d["speaker"], d["text"]) for d in lock]:
        raise ValueError("dialogue source order or speaker changed")
    events = scheduled["events"]
    shared = [e for e in events if e["dialogue_index"] >= 0]
    common = (len(shared) > 1 and len({e["performance"] for e in shared}) == 1)
    if common:
        lines.append("共用表演描述只演一次：" + _prose(shared[0]["performance"], removed))
    seen = []
    prior_end = 0.0
    for event in events:
        start, end = (_number(event[k], "event time") for k in ("start", "end"))
        if abs(start - prior_end) > 1e-6 or end <= start:
            raise ValueError("event windows must be continuous, ordered and nonempty")
        prior_end = end
        at = f"{_time(offset + start * scale)}—{_time(offset + end * scale)}秒："
        index = event["dialogue_index"]
        if type(index) is not int or index < -1:
            raise ValueError("invalid dialogue index")
        if index >= 0:
            if index >= len(lock):
                raise ValueError("dialogue event outside source")
            seen.append(index)
            line = lock[index]
            lines.append(at + f'{line["speaker"]}用中文普通话说：“{line["text"]}”')
            if not common:
                lines.append(_prose(event["performance"], removed))
        else:
            lines.append(at + _prose(event["performance"], removed))
    if seen != list(range(len(lock))) or abs(prior_end - shot["duration_seconds"]) > 1e-6:
        raise ValueError("timed performance must cover every line once and the whole shot")
    return "\n".join(lines)


def compile_generation_plan(script, assets, view, compiled, brief, full_review, arrangement,
                            *, confirmation=None, revision_feedback_unresolved=False,
                            model="doubao-seedance-2-0-mini-260615"):
    bindings = source_bindings(script, assets, view, compiled, brief, full_review)
    if arrangement.get("schema") != ARRANGEMENT or arrangement.get("bindings") != bindings:
        raise ValueError("generation arrangement source binding changed")
    if compiled.get("source_raw_linear_script") != script or compiled.get("complete") is not True:
        raise ValueError("complete source-bound physical/performance compilation required")
    shots = view["shots"]
    ids = [s["id"] for s in shots]
    groups = arrangement.get("segments")
    if not isinstance(groups, list) or not groups:
        raise ValueError("explicit director generation groups required")
    if len(set(ids)) != len(ids) or len({g["id"] for g in groups}) != len(groups):
        raise ValueError("duplicate shot or segment identity")
    if [sid for group in groups for sid in group["shot_ids"]] != ids:
        raise ValueError("generation groups must cover all shots once in original order")
    membership = {sid: g["id"] for g in groups for sid in g["shot_ids"]}
    for interaction in arrangement.get("interactions", []):
        lock = interaction["shot_ids"]
        if (not lock or any(sid not in membership for sid in lock)
                or len({membership[sid] for sid in lock}) != 1):
            raise ValueError("stimulus and response interaction split across requests")
        indexes = [ids.index(sid) for sid in lock]
        if indexes != list(range(indexes[0], indexes[-1] + 1)) or not interaction.get("reason"):
            raise ValueError("interaction needs contiguous source shots and a reason")
    catalog = ark_model(model)
    schedule = compiled["scheduled_execution"]["beats"]
    if [s["beat_id"] for s in schedule] != ids:
        raise ValueError("performance schedule differs from observation shot order")
    source_steps = _source_steps(script, compiled, ids)
    source_by_id = dict(zip(ids, shots))
    schedule_by_id = dict(zip(ids, schedule))
    story_blockers = story_media_blockers(script, brief, full_review, confirmation,
                        revision_feedback_unresolved=revision_feedback_unresolved)
    style = view["style"]
    removed = []
    header = "9:16竖屏；" + "；".join(_prose(style[k], removed) for k in (
        "visual_medium", "palette", "light_source")) + "。\n"
    for c in assets["characters"]:
        header += _prose("；".join(c[k] for k in (
            "name", "age_group", "hair", "clothing", "body_shape")), removed) + "。\n"
    header += ("声音：所有对白用自然清晰的中文普通话，按指定说话人逐字说出；"
               "不翻译，不新增对白、旁白、字幕或背景音乐。\n")
    result = []
    # Building payloads uses the existing client and catalog through a transport
    # which fails if any code accidentally attempts network access.
    def no_network(request):
        raise AssertionError("offline projection attempted a remote request")
    config = SeedanceConfig(api_key="offline-only", base_url="https://ark.cn-beijing.volces.com/api/v3",
                            model=model, provider="ark_api")
    with httpx.Client(transport=httpx.MockTransport(no_network)) as http:
        with SeedanceClient(config, http_client=http, record_calls=False) as client:
            for position, group in enumerate(groups):
                selected = [source_by_id[sid] for sid in group["shot_ids"]]
                original_duration = sum(_number(s["duration_seconds"], "shot duration") for s in selected)
                duration = group["duration_seconds"]
                if (type(duration) is not int or not catalog["duration_min"] <= duration <= catalog["duration_max"]
                        or duration < original_duration):
                    raise ValueError("generation duration must fit model without compressing performance")
                scale = duration / original_duration
                mode = group["opening_mode"]
                refs = group.get("references", [])
                blockers = list(story_blockers)
                if position == 0 and mode != "background_reference":
                    raise ValueError("bootstrap uses background reference; no invented first frame")
                if mode in {"background_reference", "scene_change_reference"}:
                    if position and mode == "background_reference":
                        raise ValueError("later independent reference generation requires a scene-change contract")
                    if not refs:
                        raise ValueError("background references missing")
                    for ref in refs:
                        if (ref.get("role") != "reference_image"
                                or ref.get("category") != "environment_only"
                                or file_sha(ref["path"]) != ref["sha256"]):
                            raise ValueError("background reference missing, changed or wrong role")
                    placeholders = [SeedanceReference("image", f"https://pending.invalid/reference/{i}",
                                                      "reference_image") for i in range(len(refs))]
                    opening = "\n".join(f"图片{i + 1}只参考{ref['name']}的空间、装修与光线。"
                                         for i, ref in enumerate(refs))
                    blockers.append("actual_reference_uploads_not_bound")
                    if mode == "scene_change_reference":
                        placeholders.append(SeedanceReference("video", "https://pending.invalid/approved-original-video", "reference_video"))
                        opening += "\n视频1仅参考已批准同账号Seedance原视频的人物身份、外貌与服装；新空间按本段图片。"
                        blockers.extend(["preceding_human_approval_missing",
                                         "preceding_trusted_original_video_missing",
                                         "scene_change_identity_and_opening_confirmation_missing"])
                elif mode == "approved_raw_tail":
                    if refs:
                        raise ValueError("strict first frame cannot mix ordinary references")
                    placeholders = [SeedanceReference("image", "https://pending.invalid/original-tail", "first_frame")]
                    opening = "从已批准上段服务原始尾帧继续，人物、服装、站位和道具起态沿用。"
                    blockers.extend(["preceding_human_approval_missing", "preceding_service_original_tail_missing"])
                else:
                    raise ValueError("unsupported opening mode")
                parts = [header, opening, f"生成{duration}秒视频。按顺序完成下面的观察镜头；不要提前换场。"]
                offset = 0.0
                for shot in selected:
                    parts.append(_shot_block(shot, schedule_by_id[shot["id"]], source_steps[shot["id"]],
                                             scale, offset, removed))
                    offset += shot["duration_seconds"] * scale
                if not any(s["dialogue_lock"] for s in selected):
                    parts.append("本段无对白，不增加旁白或内心独白。")
                parts.append("每项动作只执行一次；本段结束后保留当前表演，不演出下一段事件。")
                prompt = "\n".join(parts)
                if LEAK.search(prompt):
                    raise ValueError("internal metadata leaked into service prompt")
                payload = client.build_task_payload(prompt, duration=duration, ratio="9:16", resolution="480p",
                    generate_audio=True, return_last_frame=True, references=placeholders)
                result.append({"segment_id": group["id"], "shot_ids": group["shot_ids"],
                    "source_step_refs": [ref for sid in group["shot_ids"] for ref, _ in source_steps[sid]],
                    "duration_seconds": duration, "source_duration_seconds": original_duration,
                    "time_scale": scale, "time_status": "planned_not_actual_performance",
                    "opening_mode": mode, "references": deepcopy(refs), "prompt": prompt,
                    "prompt_sha256": digest(prompt), "payload_template": payload,
                    "payload_template_sha256": digest(payload),
                    "predecessor_segment_id": groups[position - 1]["id"] if position else None,
                    "blockers_before_submit": blockers + ["offline_template_not_executable"],
                    "submission_ready": False})
    return {"schema": SCHEMA, "bindings": bindings, "arrangement_sha256": digest(arrangement),
            "provider": "ark_api", "model": model, "segments": result,
            "story_blockers": story_blockers, "removed_compiler_metadata": removed,
            "source_beat_count": len(script["beats"]), "observation_shot_count": len(ids),
            "generation_segment_count": len(result), "source_duration_seconds": sum(s["duration_seconds"] for s in shots),
            "planned_duration_seconds": sum(g["duration_seconds"] for g in groups),
            "creative_quality_passed": False, "automatic_submit": False, "remote_request_sent": False}



def _appearance(value, removed):
    """Project static JSON to names/descriptions, never entity IDs."""
    if not isinstance(value, str):
        raise ValueError("character appearance must be text")
    if "[" not in value:
        return _prose(value, removed)
    entries = json.loads(value[value.index("["):])
    if not isinstance(entries, list) or not entries:
        raise ValueError("invalid character appearance array")
    return "；".join("，".join(_prose(c[k], removed) for k in (
        "name", "age_group", "hair", "clothing", "body_shape")) for c in entries)


def natural_shot_prompt(style, shot, dialogue_mode):
    """v4 compatibility projection for an existing single observation shot."""
    removed = []
    performance = shot["visible_performance"]
    shared_marker = "本镜共用表演原文（整镜只执行一遍；下列两个窗口各说其对应原句）："
    common = None
    if performance.startswith(shared_marker):
        common = performance[len(shared_marker):].split("\n全片", 1)[0]
        performance = "全片" + performance.split("\n全片", 1)[1]
    rows = []
    if performance.startswith("全片"):
        if common:
            rows.append("共用表演描述只演一次：" + _prose(common, removed))
        for line in performance.splitlines():
            if line.startswith("声明表演窗口："):
                json.loads(line.split("：", 1)[1])
                continue
            match = re.fullmatch(
                r"全片.+?秒；镜内(.+?)秒；(?:对白：(.+?)；)?实际表演：(.+?)；实际操作：(.+)", line)
            if not match:
                raise ValueError("unsupported compiled performance prose")
            times, dialogue, acting, operations = match.groups()
            if not isinstance(json.loads(operations), list):
                raise ValueError("invalid operation metadata")
            if common and acting.startswith("引用本镜共用表演原文"):
                acting = ""
            row = times + "秒："
            if dialogue:
                row += _prose(dialogue, removed) + "。"
            if acting:
                row += _prose(acting, removed)
            rows.append(row)
    else:
        rows.append(_prose(performance, removed))
    parts = [f"竖屏9:16，{_prose(style['visual_medium'], removed)}。",
             f"色彩与光线：{_prose(style['palette'], removed)}；{_prose(style['light_source'], removed)}。",
             "人物外观：" + _appearance(style["character_lock"], removed) + "。",
             f"本段只拍一个连续镜头，时长{shot['duration_seconds']}秒，片段内部不切镜、不换场。",
             "构图：" + _prose(shot["composition"], removed) + "。",
             "摄影：" + _prose(shot["camera"], removed) + "。",
             "表演和动作（每项只执行一次）：\n" + "\n".join(rows)]
    dialogue = shot["dialogue_lock"]
    if dialogue:
        parts.append("以下" + dialogue_mode + "对白均用自然清晰的中文普通话，"
                     "按指定说话人逐字说出，不翻译为其他语言："
                     + "；".join(f"{d['speaker']}说：{d['text']}" for d in dialogue) + "。")
        if "画外" in dialogue_mode:
            parts.append("画外声音属于指定说话人，画内听者不跟随声音对口型。")
    else:
        parts.append("本段没有对白，不增加旁白、画外解释或内心独白。")
    parts.append("沿用输入画面的空间、人物、服装和道具起态；不提前演出下一段事件。")
    prompt = "\n".join(parts)
    if LEAK.search(prompt):
        raise ValueError("internal metadata leaked into service prompt")
    return prompt

