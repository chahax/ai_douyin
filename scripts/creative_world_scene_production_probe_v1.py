"""Independent bounded whole direction / first-segment acting / production review.

Preview is pure. Only an explicitly prepared single-use Session can dispatch.
No video submission, pixel inspection, playback, ASR, publication or old tail.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from jsonschema import Draft202012Validator

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_goal_context_dispatch_v7 as runtime7
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_text_handoff_verifier_v1 as text_proof
from scripts import creative_world_scene_multimodal_clients_v1 as clients
from scripts import creative_world_scene_media_probe_v1 as media
from scripts.creative_fresh_source_session_v1 import Session as NativeSession, Halt
from src.content_factory import creative_goal_context_workflow_v28 as workflow
from src.content_factory import creative_world_scene_context_v1 as world
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from src.content_factory import creative_complete_production_pipeline_v3 as acting
from src.content_factory import creative_director_endpoint_contract_v4 as endpoint
from src.content_factory import creative_shared_production_contract_v1 as shared
from src.content_factory import creative_video_trial_contract_v1 as source
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "creative_world_scene_production_probe/v1"
LIMITS = {"goal_plan": 3, "goal_audit": 0, "complete_script": 3, "full_review": 3}
CHECKS = ("identity_asset_mapping", "source_dialogue_fidelity", "opening_causal_action",
    "ensemble_emotional_action", "stimulus_reaction", "normal_speech_and_overlap", "props_state_continuity",
    "world_scene_continuity", "current_prompt_isolation", "spoken_language_and_unspoken_metadata", "encoding_hold_not_new_action")
RULE = ("本轮只制作完整导演与首段，不代表整片局部表演已通过。原生world/scene/ensemble与完整R01是创作依据。"
    "素材按实际image1环境/image2成年女性/image3成年男性；选择与原生人物吻合的映射，不据C编号猜人物。"
    "不得改正文、原初态、对白或新增人物、道具、未来动作。开场行为必须遵循已验收正文及用户执行要求。"
    "图片中三视图仅为同一人的档案，画面每个角色只出现一个。资料与规则不朗读。"
    "人物及场景素材尚无本片用户审美批准，当前只是受委托选用；不伪称人工通过。")
REVIEW_RULE = ("你审查同源首段制作，不是视频像素或人工审美审核。逐项反例检查原生正文、整片导演、"
    "首段连续表演、正常语速排时、起终态与真实来源、原生世界/场次/在场者，及实际H3 prompt。"
    "每项quote必须是evidence目录指定真实字段路径的非空逐字片段，勿为引用复制整段长prompt/R01；引用真实性不代表语义成立。"
    "尤其审动作与当下对白重叠是否合理、听者神情、开场是否被空镜拖延、身份与三张原始素材描述能否相容。"
    "identity须分别对照每个goal profile、实际picture角色映射与原asset请求描述，不仅引用一个标题。"
    "spoken_language_and_unspoken_metadata须明确核普通话、正常速度、资料不朗读、无字幕无旁白，不能拿中文提示存在当声学质量已验证。"
    "encoding_hold只是帧格点余量，应维持既有终态，不能新增实质反应/动作、补剧情、提速或删句。"
    "只有证据充分且反例已解决才pass；明确失败fail给具体返修；未能判明unknown，不能把unknown变为明确失败。"
    "不以测试/数字/接口成功当表演质量通过；后续段未演出不算当前首段失败。")
read, write, digest, sha, now = io.read, io.write, io.digest, io.sha_file, io.now
obj = source._obj


def _inside(path):
    p = Path(path).resolve()
    if p == PROJECT or not p.is_relative_to(PROJECT): raise ValueError("independent project path required")
    return p


def _hashes(paths): return {str(_inside(p)): sha(p) for p in paths}


def load_material(verified):
    if not (verified.get("valid") is True and verified.get("accepted") is True
            and verified.get("status") == "text_ready_for_director"):
        raise ValueError("actual text-ready proof required")
    values = {k: read(_inside(v)) for k, v in verified["paths"].items()}
    inputs, goal, setup, script = (values[k] for k in ("inputs", "goal", "setup", "compiled_script"))
    views = workflow.compile_native_views(goal, setup, **workflow.origin_ids(inputs))
    if digest(workflow.validate_script_document(values["raw_script"], views, inputs["production_preferences"])["script"]) != digest(script):
        raise ValueError("actual native body compilation differs")
    context = {k: deepcopy(views["brief"][k]) for k in ("characters", "scenes", "initial_state")}
    context["initial_state"]["scene_id"] = goal["whole_plan"]["beats"][0]["scene_id"]
    manifest = shared.build_pending_manifest(script, context, {"status": "unknown", "provider_id": "local-comfy-h3",
        "model": "minimax_h3_ref2va_pruned_int8_convrot", "identity_reference_mode": "unverified",
        "allows_actor_asset_mapping": None, "sources": [], "reason": "delegated selected stills are not human appearance approval"})
    provenance = next(r for r in manifest["provenance_catalog"] if r["source_id"] == "frozen_source_context")
    actor_bank = {a["id"]: a for a in goal["whole_plan"]["characters"]}
    profile_text = json.dumps({k: v["profile"] for k, v in actor_bank.items()}, ensure_ascii=False, sort_keys=True)
    manifest["provenance_catalog"].append({"source_id": "native_goal_actor_profiles", "kind": "source_brief",
        "text": profile_text, "sha256": shared.text_sha256(profile_text)})
    for actor in manifest["actors"]:
        actor["profile"] = {k: shared.known(actor_bank[actor["id"]]["profile"][k],
            [{"source_id": "native_goal_actor_profiles", "quote": profile_text}]) for k in shared.PROFILE_FIELDS}
    shared.validate_shared_manifest(manifest, script)
    initial = pipeline.build_initial_state(context, manifest)
    assets = read(media.CATALOG)
    selected = []
    for picture, key in enumerate(media.FIXED_ASSETS, 1):
        rows = [r for r in assets["assets"] if (r["asset_id"], r["version"]) == key]
        if len(rows) != 1: raise ValueError("one exact selected still catalog row required")
        a = rows[0]; image = _inside(a["image"]["path"])
        if sha(image) != a["image"]["expected_sha256"]: raise ValueError("actual selected still changed")
        entry = {"picture": picture, "asset_id": key[0], "version": key[1], "path": str(image), "file_sha256": sha(image)}
        if picture > 1:
            p = _inside(Path(a["evidence_paths"][0]).parent / "IMAGEGEN_REQUEST.json")
            quote = "成年中国职场女性" if picture == 2 else "成年中国职场男性"
            if quote not in read(p)["prompt"]: raise ValueError("original selected gender descriptor changed")
            entry["asset_gender_evidence"] = {"path": str(p), "file_sha256": sha(p), "quote": quote}
        selected.append(entry)
    return {"verified": deepcopy(verified), "values": values, "views": views, "script": script,
        "manifest": manifest, "initial": initial, "selected_stills": selected}


def _request(stage, profile, rule, payload, schema, stills=()):
    role = "writer" if stage in ("goal_plan", "complete_script") else "director"
    params = deepcopy(profile[role]["parameters"]); params.update(profile.get("stage_parameters", {}).get(stage, {}))
    messages = [{"role": "system", "content": rule + "\n" + RULE},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
    if stills:
        parts = [{"type": "text", "text": "以下独立静态图按image1/2/3与selected_stills清单一致。"}]
        parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," +
            base64.b64encode(Path(row["path"]).read_bytes()).decode(), "detail": "default"}} for row in stills]
        messages.append({"role": "user", "content": parts})
    request = {"role": role, "model": profile[role]["model"], "stage": stage, "parameters": params,
        "messages": messages, "structured_schema": schema, "input_provenance": {"production_version": VERSION,
            "payload_sha256": digest(payload), "selected_stills_sha256": digest(stills)}}
    clients.expected_wire_request(request)
    return {"request": request, "payload": payload, "payload_sha256": digest(payload)}


def direction_schema(material):
    script, manifest = material["script"], material["manifest"]
    actors = [r["id"] for r in manifest["actors"]]
    return obj({"direction": pipeline.whole_direction_schema(script, manifest),
        "cast_by_picture": obj({"image2": {"enum": actors}, "image3": {"enum": actors}})})


def direction_request(material, profile, diagnostics=()):
    script, manifest, initial = (material[k] for k in ("script", "manifest", "initial"))
    inputs = material["values"]["inputs"]
    payload = pipeline.build_director_input(script, manifest, initial, inputs["reference_fulltext"], inputs["production_preferences"], diagnostics)
    payload.update(native_goal=deepcopy(material["values"]["goal"]), selected_stills=deepcopy(material["selected_stills"]))
    schema = direction_schema(material)
    return _request("goal_plan", profile, endpoint.DIRECTOR_RULE + "\n提交direction与cast_by_picture两个原生对象；不要替换旧原生协议。", payload, schema, material["selected_stills"])


def compile_direction(native, material):
    Draft202012Validator(direction_schema(material)).validate(native)
    if len(set(native["cast_by_picture"].values())) != 2: raise ValueError("two selected stills must map distinct closed actors")
    result = pipeline.compile_direction(native["direction"], material["script"], material["manifest"])
    first_refs = result["segments"][0]["source_refs"]
    bank = source.catalog(material["script"]); first_beat = material["script"]["beats"][0]["id"]
    if not first_refs or any(bank[r]["beat_id"] != first_beat for r in first_refs):
        raise ValueError("minimal first segment must stay inside the first native beat; revise complete direction")
    return {"valid": True, "compiled_direction": result, "native_document_sha256": digest(native)}


def performance_request(material, profile, direction_native, diagnostics=()):
    compiled = compile_direction(direction_native, material)["compiled_direction"]
    inputs = material["values"]["inputs"]; segment = compiled["segments"][0]
    payload = pipeline.build_performance_input(material["script"], material["manifest"], segment,
        material["initial"], [], inputs["reference_fulltext"], inputs["production_preferences"])
    goal, script = material["values"]["goal"], material["values"]["raw_script"]
    first = script["beats"][0]; context = next(c for c in script["scene_contexts"] if c["id"] == first["scene_context_id"])
    payload.update(world_frame=deepcopy(goal["whole_plan"]["world_frame"]), canonical_characters=deepcopy(goal["whole_plan"]["characters"]),
        scene_context=deepcopy(context), current_ensemble=deepcopy(first["ensemble"]), parallel_with=deepcopy(first["parallel_with"]),
        ensemble_is_authored_context_not_executed=True, selected_stills=deepcopy(material["selected_stills"]),
        cast_by_picture=deepcopy(direction_native["cast_by_picture"]), known_complete_diagnostics=deepcopy(list(diagnostics)))
    schema = pipeline.performance_schema(material["script"], material["manifest"], segment, material["initial"], [])
    return _request("complete_script", profile, acting.PERFORMANCE_RULE, payload, schema, material["selected_stills"])


def compile_performance(native, material, direction_native):
    direction = compile_direction(direction_native, material)["compiled_direction"]
    perf = pipeline.compile_performance(native, material["script"], material["manifest"], direction["segments"][0], material["initial"], [])
    return {"valid": True, "compiled_performance": perf, "native_document_sha256": digest(native)}


def reference_map(material, direction_native, *, reviewed=False):
    actors = {r["id"]: r for r in material["values"]["goal"]["whole_plan"]["characters"]}
    scene = material["values"]["goal"]["whole_plan"]["beats"][0]["scene_id"]
    result = []
    for row in material["selected_stills"]:
        item = {k: deepcopy(row[k]) for k in ("picture", "asset_id", "version")}
        if row["picture"] == 1: item.update(role="environment", scene_ids=[scene])
        else:
            actor = actors[direction_native["cast_by_picture"]["image" + str(row["picture"])]]
            item.update(role="character", character_id=actor["id"], name=actor["name"],
                gender_presentation=actor["profile"]["gender_presentation"], asset_presentation="female" if row["picture"] == 2 else "male",
                gender_mapping_reviewed=reviewed, asset_gender_evidence=deepcopy(row["asset_gender_evidence"]))
        result.append(item)
    return result


def render_prompt(material, direction_native, performance_native):
    perf = compile_performance(performance_native, material, direction_native)["compiled_performance"]
    frames = max(5, math.ceil(perf["total_seconds"] * 24 - 1e-8)); frames += (5 - frames) % 17
    if frames > 362: raise ValueError("native performance exceeds H3 first-segment encoding grid")
    encoded = frames / 24; hold = encoded - perf["total_seconds"]
    if not 0 <= hold <= 17/24 + 1e-8: raise ValueError("encoding hold must be bounded H3 grid remainder")
    mapping = reference_map(material, direction_native); names = {r["id"]: r["name"] for r in material["manifest"]["actors"]}
    script = material["values"]["raw_script"]; first = script["beats"][0]
    ctx = next(c for c in script["scene_contexts"] if c["id"] == first["scene_context_id"])
    scene = next(s for s in material["values"]["goal"]["whole_plan"]["scenes"] if s["id"] == ctx["scene_id"])
    lines = [f"横屏1280×704，24fps，共{frames}帧（{encoded:g}秒）。写实连续剧情首段。",
        "自然中文普通话，正常谈话速度；只说当前列出的原对白各一次，无旁白、字幕或新增人物。",
        "三张参考分别为image1环境、image2同一女性角色档案、image3同一男性角色档案；每角色仅一人，不生成三视图分身。",
        "实际人物映射：" + json.dumps(mapping, ensure_ascii=False),
        "当前故事时间：" + json.dumps(ctx["story_time"], ensure_ascii=False) + "；场地：" + scene["description"],
        "本段计划起态（不是已生成画面）：" + json.dumps(perf["planned_initial_state"], ensure_ascii=False),
        "连续表演：" + performance_native["continuous_performance"]]
    for actor in material["values"]["goal"]["whole_plan"]["characters"]:
        lines.append("人物固定资料：" + actor["name"] + "；" + json.dumps(actor["profile"], ensure_ascii=False))
    for g in performance_native["actor_goals"]:
        lines.append(names[g["actor_id"]] + "当下目的：" + g["immediate_objective"] + "；接收回应：" + g["source_reception"]["response"])
    deliveries = {r["source_ref"]: r for r in performance_native["dialogue_delivery"]}
    for row in perf["schedule"]:
        timing = f"{row['start_seconds']:g}–{row['end_seconds']:g}秒"
        if row["kind"] == "dialogue":
            cue = deliveries[row["source_ref"]]
            lines.append(timing + " " + names[row["speaker"]] + "原对白：「" + row["original_text"] + "」；语气：" + cue["speech_tone"] + "；听者：" + cue["listener_behavior"])
        else: lines.append(timing + " 当前原动作：" + row["original_text"] + ("；与" + row["overlap_with"] + "当前谈话自然重叠" if row["overlap_with"] else ""))
    lines += [f"原生末句接收窗口{performance_native['post_reaction_seconds']:g}秒已计入实际表演，不另补新戏。",
        "计划终态：" + json.dumps(perf["planned_ending_state"], ensure_ascii=False),
        f"实际表演总时长{perf['total_seconds']:g}秒；其后仅{hold:g}秒编码网格余量维持既有终态，不新增实质动作/反应，不加速/删句。"]
    current = set(perf["source_refs"]); prompt = "\n".join(lines)
    for ref, row in source.catalog(material["script"]).items():
        if row["kind"] == "dialogue" and len(row["text"]) >= 4:
            expected = sum(r["kind"] == "dialogue" and r["original_text"] == row["text"] for r in perf["schedule"])
            if prompt.count(row["text"]) != expected: raise ValueError("native current dialogue duplication or future speech leakage")
    return {"prompt": prompt, "prompt_sha256": shared.text_sha256(prompt), "performance": perf,
        "native_source_duration_seconds": perf["total_seconds"], "native_integer_duration_seconds": perf["duration_seconds"],
        "encoded_duration_seconds": encoded, "frame_length": frames, "encoding_hold_seconds": hold}


def evidence_catalog(payload):
    result = {}
    def visit(value, path):
        if isinstance(value, str) and value.strip(): result["Q" + str(len(result)+1).zfill(4)] = {"path": path, "quote": value}
        elif type(value) is dict:
            for k, v in value.items(): visit(v, path + "." + k if path else k)
        elif type(value) is list:
            for i, v in enumerate(value): visit(v, path + "." + str(i))
    visit(payload, "")
    return result


def required_evidence_groups(catalog, material):
    """Structural source families, not a deterministic semantic verdict."""
    def family(*prefixes):
        refs = [ref for ref, row in catalog.items() if any(row["path"].startswith(p) for p in prefixes)]
        if not refs: raise ValueError("required production source family absent: " + repr(prefixes))
        return refs
    prompt = family("actual_video_prompt")
    originals = family("full_current_script.beats.0.steps.")
    schedule = family("first_compiled_performance.schedule.")
    initial = family("first_compiled_performance.planned_initial_state.")
    end = family("first_compiled_performance.planned_ending_state.")
    acting_source = family("first_native_performance.continuous_performance", "first_native_performance.actor_goals.")
    casts = []
    for index, _ in enumerate(material["values"]["goal"]["whole_plan"]["characters"]):
        casts.append(family(f"whole_native_goal.whole_plan.characters.{index}.profile."))
    for index in (1, 2):
        casts.extend([family(f"reference_map.{index}.character_id"),
            family(f"reference_map.{index}.gender_presentation"), family(f"selected_still_sources.{index}.asset_gender_evidence.quote")])
    return {"identity_asset_mapping": casts, "source_dialogue_fidelity": [originals, prompt],
        "opening_causal_action": [initial, originals, prompt],
        "ensemble_emotional_action": [family("full_current_script.beats.0.ensemble."), acting_source, prompt],
        "stimulus_reaction": [originals, acting_source], "normal_speech_and_overlap": [schedule, prompt],
        "props_state_continuity": [initial, end, originals],
        "world_scene_continuity": [family("whole_native_goal.whole_plan.world_frame."), family("full_current_script.scene_contexts."), initial],
        "current_prompt_isolation": [originals, prompt],
        "spoken_language_and_unspoken_metadata": [prompt, family("first_native_performance.dialogue_delivery.", "first_native_performance.actor_goals.")],
        "encoding_hold_not_new_action": [prompt, end]}


def review_request(material, profile, direction_native, performance_native):
    rendered = render_prompt(material, direction_native, performance_native)
    payload = {"full_current_script": deepcopy(material["script"]), "whole_native_goal": deepcopy(material["values"]["goal"]),
        "whole_direction": deepcopy(direction_native), "first_native_performance": deepcopy(performance_native),
        "first_compiled_performance": deepcopy(rendered["performance"]), "reference_map": reference_map(material, direction_native),
        "selected_still_sources": deepcopy(material["selected_stills"]), "reference_fulltext": material["values"]["inputs"]["reference_fulltext"],
        "production_preferences": deepcopy(material["values"]["inputs"]["production_preferences"]),
        "actual_video_prompt": rendered["prompt"], "encoding": {k: v for k, v in rendered.items() if k not in ("prompt", "performance")},
        "first_segment_only": True, "later_segments_acting_not_reviewed": True}
    catalog = evidence_catalog(payload); context = digest(payload)
    groups = required_evidence_groups(catalog, material)
    quote = obj({"ref": {"enum": list(catalog)}, "path": {"type": "string"}, "quote": {"type": "string", "minLength": 1}})
    check = obj({"status": {"enum": ["pass", "fail", "unknown"]}, "reason": {"type": "string", "minLength": 1},
        "evidence": source._array(quote, 1), "counterevidence": source._array(quote), "required_revision": {"type": "string"}})
    checks = {}
    for key in CHECKS:
        row = deepcopy(check)
        row["properties"]["evidence"]["allOf"] = [{"contains": {"type": "object", "properties": {"ref": {"enum": refs}},
            "required": ["ref"]}, "minContains": 1} for refs in groups[key]]
        checks[key] = row
    schema = obj({"schema": {"const": VERSION + "/production_review"}, "context_sha256": {"const": context}, "checks": obj(checks)})
    # The complete source text occurs in the context only. The model receives
    # one shared path index; exact quote snapshots remain local for validation.
    result = _request("full_review", profile, REVIEW_RULE,
        {"context": payload, "evidence_path_index": {k: {"path": v["path"]} for k, v in catalog.items()},
            "required_evidence_groups": groups}, schema)
    result.update(context_sha256=context, review_context=payload, evidence_catalog=catalog, rendered=rendered, required_evidence_groups=groups)
    return result


def validate_review(native, prepared):
    Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
    findings, unknown = [], []
    for key, row in native["checks"].items():
        for ev in row["evidence"] + row["counterevidence"]:
            declared = prepared["evidence_catalog"].get(ev["ref"])
            if not declared or declared["path"] != ev["path"] or not ev["quote"].strip() or ev["quote"] not in declared["quote"]:
                raise ValueError("production review must quote an exact original source field path")
        if row["status"] == "pass" and row["required_revision"]: raise ValueError("pass cannot require revision")
        if row["status"] == "fail" and not row["required_revision"].strip(): raise ValueError("fail needs exact required revision")
        if row["status"] == "fail": findings.append({"check": key, **deepcopy(row)})
        if row["status"] == "unknown": unknown.append({"check": key, **deepcopy(row)})
    return {"valid": True, "accepted": not findings and not unknown, "findings": findings, "uncertainties": unknown,
        "first_segment_only": True, "later_segments_acting_approved": False, "human_quality_approved": False}


@dataclass(frozen=True)
class Config:
    root: str
    text_root: str
    grant_id: str
    authorization_path: str
    counter_root: str
    round_key: str
    story_ledger_path: str = str(media.DEFAULT_LEDGER)
    extra_source_files: tuple = ()
    dispatch_lock_path: str = str(PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")


class Runtime(runtime7.GoalContextRuntime):
    def _request_gate(self, request):
        projected, _ = clients._projection(request)
        super()._request_gate(projected)
        clients.expected_wire_request(request)
    def _policy(self):
        value = super()._policy(); value.update(schema=VERSION + "/runtime_policy", first_segment_only=True,
            total_new_calls_limit=9, old_director_capacity={"used": 7, "limit": 7, "remaining": 0})
        return value


class Session:
    def __init__(self, config, *, text_verifier=text_proof.verify_text_handoff, client_factory_builder=None):
        self.config = config if isinstance(config, Config) else Config(**config)
        self.root = _inside(self.config.root); self.clock = now
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", self.config.grant_id): raise ValueError("safe independent grant required")
        self.text_verifier = text_verifier; self.client_factory_builder = client_factory_builder
        self.pending_intent = None
    @classmethod
    def open(cls, root, **kwargs): return cls(read(Path(root) / "PRODUCTION_CONFIG.json"), **kwargs)
    def parent(self):
        v = self.text_verifier(_inside(self.config.text_root))
        if not all(v.get(k) is True for k in ("valid", "accepted")) or not v.get("source_files") or not v.get("parent_identity"):
            raise ValueError("verified actual text source/inherited identity required")
        for p, h in v["source_files"].items():
            if sha(_inside(p)) != h: raise ValueError("verified original text source changed")
        return v
    def preview(self):
        parent = self.parent(); material = load_material(parent); profile = material["values"]["profile"]
        first = direction_request(material, profile)
        code = {Path(__file__).resolve()}
        for module in tuple(sys.modules.values()):
            raw = getattr(module, "__file__", None)
            if raw:
                path = Path(raw).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / d) for d in ("src", "scripts")): code.add(path)
        files = {**parent["source_files"], **_hashes([*sorted(code), self.config.story_ledger_path,
            media.CATALOG, *(r["path"] for r in material["selected_stills"]),
            *(r["asset_gender_evidence"]["path"] for r in material["selected_stills"] if "asset_gender_evidence" in r), *self.config.extra_source_files])}
        return {"schema": VERSION + "/preview", "config": asdict(self.config), "parent": parent,
            "parent_identity_sha256": digest(parent["parent_identity"]), "source_files": files,
            "stage_limits": LIMITS, "first_request": first, "first_request_sha256": digest(first["request"]),
            "provider_calls": 0, "media_submissions": 0, "first_segment_only": True}
    def authorization_template(self, preview):
        return {"schema": VERSION + "/authorization", "grant_id": self.config.grant_id, "root": str(self.root),
            "preview_sha256": digest(preview), "parent_identity_sha256": preview["parent_identity_sha256"],
            "starting_spend": preview["parent"]["inherited"], "stage_limits": LIMITS, "total_new_calls_limit": 9,
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0}, "first_segment_only": True,
            "automatic_retry": False, "media_authorized": False, "old_budget_reset": False}
    def prepare(self):
        p = self.preview(); auth = read(self.config.authorization_path)
        for key, value in self.authorization_template(p).items():
            if auth.get(key) != value: raise ValueError("exact separate production authorization differs: " + key)
        CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        parent = p["parent"]; successors = policy.successor_paths(PROJECT, parent, digest(parent["parent_identity"]))
        if self.root.exists() or any(x.exists() for x in successors): raise FileExistsError("existing root or unique parent successor; do not restart/regrant")
        self.root.mkdir(parents=True)
        write(self.root / "PRODUCTION_CONFIG.json", asdict(self.config), True); write(self.root / "PREVIEW.json", p, True)
        write(self.root / "PARENT_TEXT_VERIFIED.json", parent, True)
        write(self.root / "PROFILE.json", read(parent["paths"]["profile"]), True)
        scope = {"schema": VERSION + "/scope", "grant_id": self.config.grant_id, "inherited": parent["inherited"],
            "stage_limits": LIMITS, "first_segment_only": True, "media_authorized": False,
            "publish_authorized": False, "automatic_retry": False, "old_budget_reset": False}
        write(self.root / "USER_SCOPE.json", scope, True)
        binding = {"schema": VERSION + "/successor_claim", "root": str(self.root), "grant_id": self.config.grant_id,
            "parent_identity": parent["parent_identity"], "parent_identity_sha256": digest(parent["parent_identity"]),
            "parent_session_root": parent["root"], "authorization_sha256": sha(self.config.authorization_path)}
        for path in successors: policy.new_claim(path, binding)
        files = {**p["source_files"], **_hashes([self.config.authorization_path, self.root / "PRODUCTION_CONFIG.json",
            self.root / "PROFILE.json", self.root / "USER_SCOPE.json", self.root / "PREVIEW.json", self.root / "PARENT_TEXT_VERIFIED.json", *successors])}
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "binding": binding, "successor_claim_paths": [str(x) for x in successors], "stage_limits": LIMITS,
            "inherited": parent["inherited"], "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0}}, True)
        rt = self.runtime(); rt.prepare(); return self.state(rt, "prepared")
    def _guard(self):
        f = read(self.root / "PRODUCTION_FREEZE.json")
        if f.get("schema") != VERSION + "/freeze" or f["stage_limits"] != LIMITS or read(self.root / "PRODUCTION_CONFIG.json") != json.loads(json.dumps(asdict(self.config))):
            raise ValueError("exact frozen production configuration/policy differs")
        for p, h in f["files"].items():
            if sha(_inside(p)) != h: raise ValueError("frozen original source changed: " + p)
        for p in f["successor_claim_paths"]:
            if read(p) != f["binding"]: raise ValueError("parent unique successor changed")
        run = self.root / "RUN_CLAIM.json"
        if run.exists():
            claim = read(run)
            if not (claim.get("schema") == VERSION + "/run_claim" and claim.get("root") == str(self.root)
                    and type(claim.get("pid")) is int and claim["pid"] > 0 and claim.get("automatic_restart") is False
                    and claim.get("freeze_sha256") == sha(self.root / "PRODUCTION_FREEZE.json")):
                raise ValueError("original single-use RUN identity differs")
        return True
    def runtime(self):
        f = read(self.root / "PRODUCTION_FREEZE.json"); profile = read(self.root / "PROFILE.json")
        builder = self.client_factory_builder or (lambda r: clients.make_client_factory(r, writer_base_url=profile["writer"]["base_url"]))
        return Runtime(PROJECT, self.root, list(f["files"]), f["inherited"], profile=profile, stage_limits=LIMITS,
            inherited_guard=self._guard, admission=self._admit, shared_lock=_inside(self.config.dispatch_lock_path),
            quota_state=None, client_factory_builder=builder)
    def _admit(self, label, request, ledger):
        self._guard(); CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"]) >= 9 or not re.fullmatch(r"(?:whole_direction|first_performance|first_production_review)_0[123]", label): raise ValueError("production scope exhausted/unregistered label")
        expected_stage = "goal_plan" if label.startswith("whole_direction") else "complete_script" if label.startswith("first_performance") else "full_review"
        if request["stage"] != expected_stage: raise ValueError("production stage mapping differs")
        intent = self.pending_intent
        if not intent or intent["label"] != label or sha(intent["path"]) != intent["sha256"]: raise ValueError("original trusted call intent required")
        row = read(intent["path"])
        if row["request"] != request or row["ledger_prefix_sha256"] != digest(ledger["calls"]): raise ValueError("exact request/native predecessor sequence differs")
        if digest(self._rebuild(label, ledger)["request"]) != digest(request): raise ValueError("request differs from actual source/native builder")
        return True
    @staticmethod
    def _decision(receipt):
        return receipt.get("validation") or {"valid": False, "findings": [deepcopy(receipt.get("validation_error", receipt.get("failure")))]}
    def _rebuild(self, label, ledger):
        """Reconstruct only from the original ordered accepted/rejected natives."""
        material = load_material(read(self.root / "PARENT_TEXT_VERIFIED.json")); profile = read(self.root / "PROFILE.json")
        receipts = [read(self.root / r["receipt"]) for r in ledger["calls"]]
        directions, perfs, reviews = [], [], []; direction_diagnostics, perf_diagnostics = [], []
        latest_direction = None; latest_perf = None
        for r in receipts:
            value = NativeSession.known(r, r["label"], require_valid=False); decision = self._decision(r)
            if r["label"].startswith("whole_direction"):
                directions.append(r); latest_direction = value
                if value.get("direction", {}).get("availability") == "unknown": raise ValueError("uncertain native whole direction cannot continue")
                if not decision["valid"]: direction_diagnostics.append({"previous_complete_document": value, "diagnostics": decision})
            elif r["label"].startswith("first_performance"):
                perfs.append(r); latest_perf = value
                if value.get("availability") == "unknown": raise ValueError("uncertain native performance cannot continue")
                if not decision["valid"]:
                    diag = {"previous_complete_document": value, "diagnostics": decision}; perf_diagnostics.append(diag)
                    direction_diagnostics.append({"previous_complete_direction": latest_direction, "failed_local_performance": diag})
            else:
                reviews.append(r)
                if not decision.get("valid") or decision.get("uncertainties") or decision.get("accepted"):
                    raise ValueError("terminal production review cannot continue")
                perf_diagnostics.append({"previous_complete_document": latest_perf, "native_production_review": value, "diagnostics": decision})
        if label.startswith("whole_direction"):
            if label != f"whole_direction_{len(directions)+1:02}": raise ValueError("direction ordinal differs")
            if receipts and not ((receipts[-1]["label"].startswith("whole_direction") or receipts[-1]["label"].startswith("first_performance")) and not self._decision(receipts[-1])["valid"]):
                raise ValueError("no known complete direction-revision predecessor")
            return direction_request(material, profile, direction_diagnostics)
        if not directions or not self._decision(directions[-1])["valid"]: raise ValueError("valid actual whole direction required")
        if label.startswith("first_performance"):
            if label != f"first_performance_{len(perfs)+1:02}" or not receipts[-1]["label"].startswith(("whole_direction", "first_production_review")):
                raise ValueError("valid actual acting predecessor and ordinal required")
            return performance_request(material, profile, latest_direction, perf_diagnostics)
        if label != f"first_production_review_{len(reviews)+1:02}" or not perfs or not receipts[-1]["label"].startswith("first_performance") or not self._decision(perfs[-1])["valid"]:
            raise ValueError("valid actual performance required before production review")
        return review_request(material, profile, latest_direction, latest_perf)
    def state(self, rt, status, **details):
        value = NativeSession.state(self, rt, status, **details); value.update(schema=VERSION + "/state", first_segment_only=True)
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha(self.root / "RUN_CLAIM.json")
        write(self.root / "STATE.json", value); return value
    def invoke(self, rt, label, prepared, validator):
        path = self.root / "call_intents" / (label + ".json")
        write(path, {"label": label, "request": prepared["request"], "ledger_prefix_sha256": digest(read(rt.ledger)["calls"])}, True)
        self.pending_intent = {"label": label, "path": str(path), "sha256": sha(path)}
        receipt = policy.dispatch_claimed(rt, label, prepared, validator, root=self.root, grant_id=self.config.grant_id,
            stage_limits=LIMITS, current_round_root=self.config.counter_root, current_round_key=self.config.round_key, guard=self._guard)
        native = NativeSession.known(receipt, label, require_valid=False)
        decision = self._decision(receipt)
        return native, decision, receipt
    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file(): raise ValueError("separate prepare required")
        policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "pid": os.getpid(), "started_at": now(), "automatic_restart": False, "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json")})
        rt = None
        try:
            rt = self.runtime(); self._guard(); CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]: raise ValueError("nonempty original RUN cannot restart")
            parent = read(self.root / "PARENT_TEXT_VERIFIED.json"); material = load_material(parent); profile = read(self.root / "PROFILE.json")
            direction_diagnostics, perf_diagnostics = [], []; perf_count = review_count = 0
            for d in (1, 2, 3):
                dr = direction_request(material, profile, direction_diagnostics)
                dn, dc, _ = self.invoke(rt, f"whole_direction_{d:02}", dr, lambda v: compile_direction(v, material))
                if dn.get("direction", {}).get("availability") == "unknown": return self.state(rt, "halt_whole_direction_uncertain")
                if not dc["valid"]: direction_diagnostics.append({"previous_complete_document": dn, "diagnostics": dc}); continue
                while perf_count < 3:
                    perf_count += 1; pr = performance_request(material, profile, dn, perf_diagnostics)
                    pn, pc, _ = self.invoke(rt, f"first_performance_{perf_count:02}", pr, lambda v: compile_performance(v, material, dn))
                    if pn.get("availability") == "unknown": return self.state(rt, "halt_first_performance_uncertain")
                    if not pc["valid"]:
                        diag = {"previous_complete_document": pn, "diagnostics": pc}; perf_diagnostics.append(diag)
                        # Real over-window state must be fed to complete direction;
                        # not compressed or edited by the coordinator.
                        direction_diagnostics.append({"previous_complete_direction": dn, "failed_local_performance": diag}); break
                    qr = review_request(material, profile, dn, pn)
                    review_count += 1
                    qn, qc, _ = self.invoke(rt, f"first_production_review_{review_count:02}", qr, lambda v: validate_review(v, qr))
                    if not qc["valid"]: return self.state(rt, "halt_production_review_contract", native_review_ordinal=read(rt.ledger)["calls"][-1]["ordinal"])
                    if qc["uncertainties"]: return self.state(rt, "halt_production_review_uncertain", decision=qc)
                    if qc["accepted"]: return self._save(rt, material, dn, pn, qn, qr, qc)
                    perf_diagnostics.append({"previous_complete_document": pn, "native_production_review": qn, "diagnostics": qc})
                if perf_count >= 3: break
            return self.state(rt, "halt_first_production_capacity_exhausted")
        except Halt as e: return self.state(rt, e.status, **e.details)
        except Exception as e:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(e).__name__, "message": str(e), "automatic_restart": False}, True)
            return self.state(rt, "halt_execution_reconciliation", error=str(e))
    def _save(self, rt, material, dn, pn, qn, qr, qc):
        records = {"NATIVE_DIRECTION": dn, "COMPILED_DIRECTION": compile_direction(dn, material)["compiled_direction"],
            "NATIVE_FIRST_PERFORMANCE": pn, "COMPILED_FIRST_PERFORMANCE": qr["rendered"]["performance"],
            "NATIVE_FIRST_PRODUCTION_REVIEW": qn, "FIRST_PRODUCTION_DECISION": qc, "RENDERED_FIRST_SEGMENT": qr["rendered"]}
        for key, value in records.items(): write(self.root / (key + ".json"), value, True)
        proof = {"schema": VERSION + "/first_segment_handoff", "first_segment_only": True,
            "text_handoff_sha256": material["verified"]["handoff_sha256"], "native_identity": material["verified"]["identity"],
            "artifact_files": _hashes(self.root / (key + ".json") for key in records), "review_context_sha256": qr["context_sha256"],
            "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json"), "run_claim_sha256": sha(self.root / "RUN_CLAIM.json"),
            "decision": qc, "media_submitted": False, "human_quality_approved": False, "later_segments_acting_approved": False}
        write(self.root / "FIRST_SEGMENT_HANDOFF.json", proof, True)
        return self.state(rt, "first_segment_ready_for_media", production_handoff_sha256=sha(self.root / "FIRST_SEGMENT_HANDOFF.json"))


def _verify_receipt(root, row, manifest, reader):
    p = evidence._inside(root / row["receipt"], root); reader.verify(p, row["receipt_sha256"]); receipt = reader.json(p)
    req = receipt["request"]
    if not (receipt["ordinal"] == row["ordinal"] and receipt["label"] == row["label"] and receipt["request_sha256"] == digest(req)
            and receipt["source_binding_sha256"] == digest(manifest) and receipt["token_reservation"] == row["token_reservation"]): raise ValueError("original production receipt identity differs")
    directory = evidence._inside(root / receipt["call_evidence"]["directory"], root / "call_evidence")
    identity = {"ordinal": receipt["ordinal"], "label": receipt["label"], "request_sha256": digest(req),
        "source_binding_sha256": digest(manifest), "role": req["role"], "model": req["model"]}; ih = digest(identity)
    if reader.json(directory / "IDENTITY.json") != {"schema": "creative_call_evidence/v1", "identity": identity, "identity_sha256": ih}: raise ValueError("SDK identity differs")
    actual, raw, _ = evidence._body(reader, directory, "request", ih); expected = clients.expected_wire_request(req)
    pre = reader.json(directory / "M31_WIRE_PREFLIGHT.json"); host = "api.minimax.cn" if req["role"] == "writer" else "api.deepseek.com"
    if not (digest(actual) == digest(expected) and pre["logical_request_sha256"] == digest(req) and pre["actual_request_body_sha256"] == hashlib.sha256(raw).hexdigest()
            and pre["expected_wire_sha256"] == pre["actual_wire_sha256"] == digest(expected) and pre["identity_sha256"] == ih
            and type(pre["SDK_max_retries"]) is int and pre["SDK_max_retries"] == 0
            and pre["schema"] == clients.text.VERSION + "/outbound_proof" and pre["body_bytes"] == len(raw)
            and pre["mapped_fields"] == sorted(expected) and pre["full_wire_equals_mapped_logical_request"] is True
            and pre["messages_sha256"] == digest(req["messages"]) and pre["structured_schema_sha256"] == digest(req["structured_schema"])
            and pre["endpoint_method"] == "POST" and pre["endpoint_path"] == "/v1/chat/completions"
            and pre["verified_endpoint_sha256"] == digest(["POST", "https://" + host + "/v1/chat/completions"])
            and pre["writer_reasoning_effort"] == ("medium" if req["role"] == "writer" else None)
            and all(pre[k] is False for k in ("HTTP_follow_redirects", "server_stream_requested", "server_schema_guarantee",
                "new_provider_acceptance_verified", "calls_authorized_by_proof", "automatic_retry"))
            and pre["provider_received_request"] is None
            and pre["status"] == "wire_verified_before_send" and pre["provider_endpoint_host"] == host):
        raise ValueError("actual original multimodal SDK wire differs")
    response, body, bm = evidence._body(reader, directory, "response", ih); meta = receipt["response_metadata"]
    known, _, _ = NativeSession.classify_native(receipt)
    if not (known and meta["response_body_complete"] is True and meta["finish_reason"] in ("stop", "tool_calls")
            and type(meta.get("total_tokens")) is int and meta["total_tokens"] >= 0 and meta["raw_body_sha256"] == hashlib.sha256(body).hexdigest()
            and response == receipt["response_payload"] and meta["response_model"] == meta["requested_model"] == req["model"] == response["model"]
            and bm["http_metadata"]["http_status_code"] == meta["http_status_code"]
            and 200 <= meta["http_status_code"] < 300 and meta["total_tokens"] == response.get("usage", {}).get("total_tokens")
            and meta["response_id"] == response["id"] and len(response["choices"]) == 1
            and meta["finish_reason"] == response["choices"][0]["finish_reason"]): raise ValueError("unknown/incomplete production response or usage")
    choice = response["choices"][0]; calls = choice.get("message", {}).get("tool_calls", [])
    if type(calls) is not list or len(calls) != 1 or calls[0].get("type") != "function" or calls[0]["function"]["name"] != expected["tools"][0]["function"]["name"]: raise ValueError("production tool identity differs")
    if not (calls[0]["function"]["arguments"] == receipt["response_text"] and digest(io.strict_json(receipt["response_text"])) == digest(receipt["output"])): raise ValueError("original native tool differs")
    phases = []
    for i, path in enumerate(sorted(directory.glob("event_*.json")), 1):
        event = reader.json(path)
        if event["sequence"] != i or event["identity_sha256"] != ih: raise ValueError("SDK journal differs")
        phases.append(event["phase"])
    if any(phases.count(k) != 1 for k in ("dispatch_attempt_started", "request_body_saved", "response_body_saved", "result_ready")):
        raise ValueError("single complete production SDK dispatch evidence required")
    return receipt


def verify_first_segment_handoff(root, *, text_verified=None):
    session = Session.open(root); session._guard(); actual_parent = session.parent()
    if text_verified is not None and digest(actual_parent) != digest(text_verified): raise ValueError("provided text proof differs from actual original verifier")
    rt = session.runtime(); state = read(session.root / "STATE.json"); proofpath = session.root / "FIRST_SEGMENT_HANDOFF.json"; proof = read(proofpath)
    if not (state["status"] == "first_segment_ready_for_media" and state["spend_verification_pending"] is False
            and proof.get("schema") == VERSION + "/first_segment_handoff" and proof.get("first_segment_only") is True
            and proof.get("text_handoff_sha256") == actual_parent["handoff_sha256"] and proof.get("native_identity") == actual_parent["identity"]
            and proof.get("media_submitted") is False and proof.get("human_quality_approved") is False and proof.get("later_segments_acting_approved") is False
            and state["production_handoff_sha256"] == sha(proofpath) and proof["freeze_sha256"] == sha(session.root / "PRODUCTION_FREEZE.json")
            and proof["run_claim_sha256"] == state["run_claim_sha256"] == sha(session.root / "RUN_CLAIM.json")):
        raise ValueError("original complete first-segment production state required")
    summary = rt.summary(); ledger = read(rt.ledger)
    if summary != state["spend"] or summary["new_unknown_token_reservations"] != 0: raise ValueError("original settled production usage differs")
    reader = evidence.Reader(); receipts = [_verify_receipt(session.root, r, ledger["source_manifest"], reader) for r in ledger["calls"]]
    evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = reader.json(session.root / "call_intents" / (row["label"] + ".json"))
        prefix = {**ledger, "calls": ledger["calls"][:index]}
        if digest(intent) != digest({"label": row["label"], "request": receipt["request"], "ledger_prefix_sha256": digest(prefix["calls"])}) or digest(session._rebuild(row["label"], prefix)["request"]) != digest(receipt["request"]):
            raise ValueError("original request/native predecessor reconstruction differs")
    required_artifacts = {str((session.root / (key + ".json")).resolve()) for key in ("NATIVE_DIRECTION", "COMPILED_DIRECTION",
        "NATIVE_FIRST_PERFORMANCE", "COMPILED_FIRST_PERFORMANCE", "NATIVE_FIRST_PRODUCTION_REVIEW", "FIRST_PRODUCTION_DECISION", "RENDERED_FIRST_SEGMENT")}
    if set(proof["artifact_files"]) != required_artifacts: raise ValueError("exact first-segment native and derived artifact set required")
    for p, h in proof["artifact_files"].items(): reader.verify(_inside(p), h)
    records = {key: read(session.root / (key + ".json")) for key in ("NATIVE_DIRECTION", "NATIVE_FIRST_PERFORMANCE", "NATIVE_FIRST_PRODUCTION_REVIEW")}
    for value in records.values():
        if not any(digest(r.get("output")) == digest(value) and r["status"] == "contract_valid" for r in receipts): raise ValueError("production artifact is not actual valid native receipt")
    material = load_material(actual_parent); dn, pn, qn = records.values(); prepared = review_request(material, read(session.root / "PROFILE.json"), dn, pn)
    checked = validate_review(qn, prepared)
    if not (checked["accepted"] and digest(checked) == digest(proof["decision"]) and prepared["context_sha256"] == proof["review_context_sha256"]): raise ValueError("same-native production review does not pass")
    rendered = prepared["rendered"]
    if digest(read(session.root / "RENDERED_FIRST_SEGMENT.json")) != digest(rendered): raise ValueError("actual deterministic render changed")
    for name, expected in {"COMPILED_DIRECTION": compile_direction(dn, material)["compiled_direction"],
        "COMPILED_FIRST_PERFORMANCE": rendered["performance"], "FIRST_PRODUCTION_DECISION": checked}.items():
        if digest(read(session.root / (name + ".json"))) != digest(expected): raise ValueError("derived production artifact differs from original native: " + name)
    ledger_source = read(session.config.story_ledger_path)
    for name in ("STATE.json", "CALL_LEDGER.json", "PRODUCTION_FREEZE.json", "RUN_CLAIM.json", "FIRST_SEGMENT_HANDOFF.json"):
        reader.bytes(session.root / name)
    result = {"schema": VERSION + "/verified_first_segment", "valid": True, "accepted": True, "status": "first_segment_ready_for_media",
        "text_handoff_sha256": actual_parent["handoff_sha256"], **{k: v for k, v in actual_parent["identity"].items() if k in ("native_goal_sha256", "native_script_sha256", "native_setup_sha256")},
        "segment_ordinal": 1, "beat_id": material["script"]["beats"][0]["id"], "story_id": ledger_source["story_id"],
        "source_refs": rendered["performance"]["source_refs"], "duration_seconds": rendered["encoded_duration_seconds"],
        "native_source_duration_seconds": rendered["native_source_duration_seconds"], "native_integer_duration_seconds": rendered["native_integer_duration_seconds"],
        "encoded_duration_seconds": rendered["encoded_duration_seconds"], "encoding_hold_seconds": rendered["encoding_hold_seconds"], "frame_length": rendered["frame_length"],
        "production_review_context_sha256": prepared["context_sha256"], "encoding_hold_reviewed": checked["accepted"],
        "actual_video_prompt": rendered["prompt"], "video_prompt_sha256": rendered["prompt_sha256"],
        "reference_map": reference_map(material, dn, reviewed=True), "production_handoff_path": str(proofpath), "production_handoff_sha256": sha(proofpath),
        "proof_files": [{"path": p, "file_sha256": h} for p, h in {**proof["artifact_files"], **{p: r["sha256"] for p, r in reader.files.items()}}.items()],
        "spend": summary, "first_segment_only": True, "later_segments_acting_approved": False, "authorizes_media_dispatch": False, "human_quality_approved": False}
    result["encoding_certificate_sha256"] = digest({k: result[k] for k in ('native_source_duration_seconds','native_integer_duration_seconds',
        'encoded_duration_seconds','encoding_hold_seconds','frame_length','video_prompt_sha256','production_review_context_sha256')})
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("action", choices=("preview", "prepare", "run", "verify")); parser.add_argument("path")
    args = parser.parse_args(argv)
    if args.action == "verify": result = verify_first_segment_handoff(args.path)
    else:
        s = Session(read(args.path)) if args.action in ("preview", "prepare") else Session.open(args.path)
        result = getattr(s, args.action)()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
