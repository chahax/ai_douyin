"""Story-independent asset routing and evidence-gated production queue.

This layer prepares work, never supplies semantic review results or clears a
provider/campaign lock. Paid execution remains in the existing gated executors.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .creative_workflow_inputs import file_binding, verify_binding

SCHEMA = "reusable_production_design/v1"
VISUAL_CHECKS = ("identity", "spatial_layout", "props_and_hands", "action_pace", "cut_continuity", "visual_storytelling")
AUDIO_CHECKS = ("voice", "speech_pace", "lip_sync")
DESIGN_PROMPT = """你是本项目现有导演，负责将已定分镜编排为可复用资产与审片计划，不是第三审核模型。
不改变事件、对白、时长和镜序，不宣称图像或视频通过。只写当前故事，不引用历史镜号或目录。
每镜明确新增信息、观看反应的人、切走理由、情绪可读窗口；无新信息的操作列入问题，禁止擅自删除。
每个角色与场景用稳定ID；同一角色不同服装或场景不同时间光线需不同资产ID。人物母版用清楚柔光和中性背景；场景图容纳实际动线。
复用仅按已给资产目录选择；没有确切匹配则reuse_key为空。只输出需要的资产；不能凭同姓、相似衣服或画风认定同一人物。
输出JSON：{"schema":"reusable_production_design/v1","assets":[{"id":"CHAR_A","kind":"character|background","name":"角色或场景名","required_tags":["明确的画风、服装或光线标签"],"reuse_key":"或空串","prompt":"可直接用于角色多角度设定或无人场景的具体提示，至少40字"}],"shots":[{"shot_id":"分镜原ID","asset_ids":["CHAR_A"],"new_information":"新增信息","reaction_subject":"反应主体，无人则明确无","cut_reason":"切镜理由","reaction_window":[0,2],"risks":["identity|dialogue|interaction|camera_change中相关项"],"opening_prompt":"首帧静态构图，不提前完成动作，至少40字"}],"issues":[{"shot_id":"原ID","owner":"writer或director","reason":"上游需要处理的实际问题"}]}。
镜序逐字保留，每镜至少一个资产，全部资产必须被引用；风险允许空数组。reaction_window是本镜内真实非零时窗，仅说明计划，不证明表演通过。没有问题时issues为空数组。
"""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(key + " 不能为空")
    return value.strip()


def validate_design(value: dict, storyboard: dict, asset_catalog: list | None = None) -> None:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("资产设计版本无效")
    assets = value.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("缺少资产需求")
    ids = []
    for a in assets:
        aid = _text(a.get("id"), "asset id")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", aid) or aid in ids:
            raise ValueError("资产ID重复或不安全")
        ids.append(aid)
        if a.get("kind") not in {"character", "background"}:
            raise ValueError("资产类型无效")
        _text(a.get("name"), "asset name")
        if len(_text(a.get("prompt"), "asset prompt")) < 40:
            raise ValueError("资产提示不足40字")
        if not isinstance(a.get("reuse_key"), str):
            raise ValueError("reuse_key 应是文本")
        tags = a.get("required_tags")
        if not isinstance(tags, list) or not tags:
            raise ValueError("复用需要明确兼容标签")
        for tag in tags:
            _text(tag, "tag")
    if asset_catalog is not None:
        for req in assets:
            if not req["reuse_key"]:
                continue
            matches = [a for a in asset_catalog if a.get("reuse_key") == req["reuse_key"]]
            if len(matches) != 1:
                raise ValueError(f"{req['id']} 指定复用键不存在或不唯一: {req['reuse_key']}")
            candidate = matches[0]
            kind = {"scene": "background"}.get(candidate.get("kind"), candidate.get("kind"))
            missing = sorted(set(req["required_tags"]) - set(candidate.get("tags", [])))
            if kind != req["kind"] or missing:
                raise ValueError(f"{req['id']} 指定资产复用不兼容，缺少标签: {missing}；保留真实要求，修正复用选择或明确新建")
    shots = value.get("shots")
    expected = storyboard["shots"]
    if not isinstance(shots, list) or [s.get("shot_id") for s in shots] != [s["id"] for s in expected]:
        raise ValueError("资产设计改变了镜序")
    used = set()
    for row, shot in zip(shots, expected):
        refs = row.get("asset_ids")
        if (not isinstance(refs, list) or not refs or any(not isinstance(x, str) for x in refs)
                or len(refs) != len(set(refs)) or not set(refs) <= set(ids)):
            raise ValueError("镜头引用了未知或重复资产")
        used.update(refs)
        for key in ("new_information", "reaction_subject", "cut_reason", "opening_prompt"):
            _text(row.get(key), key)
        if len(row["opening_prompt"]) < 40:
            raise ValueError("首帧提示不足40字")
        window = row.get("reaction_window")
        if (not isinstance(window, list) or len(window) != 2
                or any(type(x) not in (int, float) for x in window)
                or not 0 <= window[0] < window[1] <= shot["duration_seconds"]):
            raise ValueError("反应窗口超出镜头")
        risks = row.get("risks")
        if not isinstance(risks, list) or any(x not in {"identity", "dialogue", "interaction", "camera_change"} for x in risks):
            raise ValueError("风险类别无效")
    if used != set(ids):
        raise ValueError("资产需求包含未使用资产")
    if not isinstance(value.get("issues"), list):
        raise ValueError("issues 必须为列表")
    for issue in value["issues"]:
        if issue.get("shot_id") not in {s["id"] for s in expected} or issue.get("owner") not in {"writer", "director"}:
            raise ValueError("问题无法定位上游")
        _text(issue.get("reason"), "issue reason")


def verified_asset(asset: dict) -> dict:
    if asset.get("decision") != "passed":
        raise ValueError("历史资产未通过")
    for key in ("image", "review", "receipt"):
        verify_binding(asset[key])
    review = read(Path(asset["review"]["path"]))
    checks = review.get("checks")
    if (review.get("decision") != "passed" or review.get("image_sha256") != asset["image"]["sha256"]
            or not isinstance(checks, dict) or not checks or any(v is not True for v in checks.values())
            or not (review.get("observations") or review.get("evidence"))):
        raise ValueError("资产实际审核不完整或版本已变")
    receipt = read(Path(asset["receipt"]["path"]))
    if receipt.get("status") != "downloaded" or receipt.get("image_sha256") != asset["image"]["sha256"]:
        raise ValueError("资产生成回执与原图不一致")
    return asset


def route_assets(design: dict, library: dict) -> list[dict]:
    rows = library.get("assets", [])
    result = []
    for req in design["assets"]:
        matches, rejected = [], []
        for candidate in rows:
            key = candidate.get("reuse_key")
            if req["reuse_key"]:
                match = key == req["reuse_key"]
            else:
                match = req["name"] in [candidate.get("canonical_name"), *candidate.get("aliases", [])]
            if not match:
                continue
            try:
                if ({"scene": "background"}.get(candidate.get("kind"), candidate.get("kind"))) != req["kind"] or not set(req["required_tags"]) <= set(candidate.get("tags", [])):
                    raise ValueError("身份、画风、服装或场景标签不匹配")
                matches.append(verified_asset(candidate))
            except (KeyError, OSError, ValueError, TypeError) as exc:
                rejected.append({"reuse_key": key, "reason": str(exc)})
        # Ambiguity is a selection task, never an arbitrary first hit.
        status = "reuse" if len(matches) == 1 else "select_existing" if matches else "generate"
        if req["reuse_key"] and not matches:
            status = "reuse_conflict"
            if not rejected:
                rejected.append({"reuse_key": req["reuse_key"], "reason": "指定复用键不存在"})
        result.append({"asset_id": req["id"], "status": status, "requirement": req,
                       "selected": matches[0] if len(matches) == 1 else None,
                       "candidates": [x["reuse_key"] for x in matches], "rejected": rejected})
    return result


def _review(path: Path, expected: dict, checks: tuple[str, ...]) -> str:
    if not path.exists():
        return "pending"
    value = read(path)
    if any(value.get(k) != v for k, v in expected.items()):
        return "stale"
    actual = value.get("checks", {})
    if not isinstance(actual, dict):
        return "pending"
    if value.get("decision") == "failed" or any(v is False for v in actual.values()):
        return "failed"
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list) or not evidence or not value.get("observations"):
        return "pending"
    try:
        for item in evidence:
            verify_binding(item)
    except (OSError, ValueError, KeyError, TypeError):
        return "stale"
    return "passed" if value.get("decision") == "passed" and all(actual.get(k) is True for k in checks) else "pending"


def build_queue(run: Path, design: dict, storyboard: dict, routes: list, *, text_ready: bool) -> dict:
    """Recompute from actual evidence each time; never trust saved queue status."""
    validate_design(design, storyboard)
    dh, sh = digest(design), digest(storyboard)
    base = {"schema": "reusable_production_queue/v1", "design_sha256": dh,
            "storyboard_sha256": sh, "automatic_submit": False, "full_workflow_pass": False}
    def stop(stage, action, **kw):
        return {**base, "stage": stage, "next_action": action, **kw}
    if not text_ready:
        return stop("text_review", "review_current_text")
    if design["issues"]:
        return stop("upstream_revision", "repair_design_issues", issues=design["issues"])
    conflicts = [r for r in routes if r["status"] == "reuse_conflict"]
    if conflicts:
        return stop("upstream_revision", "repair_asset_reuse_conflicts", assets=conflicts)
    # First validate a few selected sample images against the intended style.
    style = _review(run / "STYLE_REVIEW.json", {"design_sha256": dh, "storyboard_sha256": sh},
                    ("visual_style", "character_readability", "scene_readability"))
    if style != "passed":
        return stop("style_review", "prepare_style_samples" if style == "pending" else "repair_style",
                    review_status=style, sample_asset_ids=[next(a["id"] for a in design["assets"] if a["kind"] == kind)
                                                     for kind in ("character", "background")
                                                     if any(a["kind"] == kind for a in design["assets"])])
    needed = [r for r in routes if r["status"] != "reuse"]
    if needed:
        return stop("assets", "resolve_assets", assets=needed)
    # A new composition still needs review even when all master assets are reusable.
    asset_binding = digest([{ "asset_id": r["asset_id"], "selected": r["selected"]} for r in routes])
    composition = _review(run / "STORYBOARD_MEDIA_REVIEW.json",
                          {"design_sha256": dh, "storyboard_sha256": sh, "assets_sha256": asset_binding},
                          ("actual_asset_layout", "information_progression", "reaction_windows", "cut_motivation"))
    if composition != "passed":
        return stop("storyboard_media_review", "review_compositions_and_rhythm", review_status=composition,
                    assets_sha256=asset_binding)
    risk_shots, covered = [], set()
    for row in sorted(design["shots"], key=lambda r: -len(r["risks"])):
        if set(row["risks"]) - covered:
            risk_shots.append(row["shot_id"])
            covered.update(row["risks"])
    probes = _review(run / "CAPABILITY_REVIEW.json",
                     {"design_sha256": dh, "storyboard_sha256": sh, "assets_sha256": asset_binding},
                     ("identity", "reaction", "interaction", "audio"))
    if risk_shots and probes != "passed":
        return stop("capability_review", "verify_representative_shots", shot_ids=risk_shots,
                    review_status=probes, assets_sha256=asset_binding)
    previous_tail = None
    segment_bindings = []
    for index, shot in enumerate(storyboard["shots"]):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", shot["id"]):
            raise ValueError("镜头ID不能作为安全目录")
        folder = run / "media" / shot["id"]
        receipt_path = folder / "receipt.json"
        if not receipt_path.exists():
            if index and shot["continuity_mode"] != "raw_tail_continuation":
                return stop("continuity_adapter", "resolve_cut_under_current_continuation_policy", shot_id=shot["id"])
            return stop("segment", "prepare_existing_executor", shot_id=shot["id"], original_tail=previous_tail,
                        assets_sha256=asset_binding,
                        requirements=["current_campaign_reservation", "paid_scope_authorization", "reviewed_first_frame"])
        rec = read(receipt_path)
        if rec.get("design_sha256") != dh or rec.get("storyboard_sha256") != sh or rec.get("assets_sha256") != asset_binding:
            return stop("source_changed", "reconcile_media_version", shot_id=shot["id"])
        if rec.get("status") in {"failed", "cancelled", "expired", "rejected_pre_generation"}:
            return stop("generation_failed", "repair_and_record_campaign_failure", shot_id=shot["id"], receipt=str(receipt_path))
        if rec.get("status") != "succeeded":
            return stop("submission", "query_existing_task" if rec.get("task_id") else "resolve_existing_submission",
                        shot_id=shot["id"], receipt=str(receipt_path))
        if index and rec.get("first_frame_sha256") != previous_tail["sha256"]:
            return stop("continuity_failed", "repair_from_earliest_changed_segment", shot_id=shot["id"])
        try:
            verify_binding(rec["video"])
            verify_binding(rec["original_tail"])
        except (OSError, ValueError, KeyError):
            return stop("source_changed", "reconcile_media_version", shot_id=shot["id"])
        review = _review(folder / "review.json", {"video_sha256": rec["video"]["sha256"],
                         "receipt_sha256": file_binding(receipt_path)["sha256"]}, VISUAL_CHECKS + AUDIO_CHECKS)
        if review != "passed":
            return stop("segment_review", "repair_current_segment" if review == "failed" else "review_current_segment",
                        shot_id=shot["id"], review_status=review)
        previous_tail = rec["original_tail"]
        segment_bindings.append({"receipt": file_binding(receipt_path), "review": file_binding(folder / "review.json")})
    assembly_path = run / "ASSEMBLY_RECEIPT.json"
    segments_hash = digest(segment_bindings)
    if assembly_path.exists():
        assembly = read(assembly_path)
        if assembly.get("segments_sha256") != segments_hash:
            return stop("assembly", "rebuild_assembly_for_current_segments", segments_sha256=segments_hash)
        try:
            verify_binding(assembly["video"])
        except (KeyError, OSError, ValueError, TypeError):
            return stop("assembly", "reconcile_assembly_version", segments_sha256=segments_hash)
        status = _review(run / "FULL_FILM_REVIEW.json", {"video_sha256": assembly["video"]["sha256"],
                         "assembly_receipt_sha256": file_binding(assembly_path)["sha256"]},
                         VISUAL_CHECKS + AUDIO_CHECKS + ("emotional_focus", "ending", "all_cut_points"))
        if status == "passed":
            return {**base, "stage": "complete", "next_action": "none", "full_workflow_pass": True,
                    "video": assembly["video"]}
        return stop("full_film_review", "review_whole_film" if status != "failed" else "repair_film",
                    review_status=status, video=assembly["video"])
    return stop("assembly", "assemble_and_review_whole_film", assets_sha256=asset_binding, segments_sha256=segments_hash)


def prepare_run(run_dir: Path, library_path: Path) -> dict:
    """Bind a generic creative output to reusable assets; no historical series edits."""
    from scripts.compile_creative_seedance_segments import compile_run
    run = Path(run_dir).resolve()
    state = read(run / "state.json")
    revised = state.get("status") == "reviewed_revision_media_handoff_pending_capability"
    prefix = "ASSISTANT_REVISED_" if revised else ""
    plan, receipt = compile_run(run, revised=revised)
    design = read(run / (prefix + "PRODUCTION_DESIGN.json"))
    storyboard = read(run / (prefix + "STORYBOARD.json"))
    handoff = read(run / (prefix + "MEDIA_HANDOFF.json"))
    if handoff.get("production_design_sha256") != digest(design):
        raise ValueError("媒体交接未绑定当前资产设计")
    validate_design(design, storyboard)
    state = read(run / "state.json")
    manifest = read(run / (prefix + "CREATIVE_OUTPUT_MANIFEST.json"))
    if digest(manifest) != state.get("revised_output_manifest_sha256" if revised else "output_manifest_sha256") or manifest.get("handoff_sha256") != digest(handoff):
        raise ValueError("创作输出总清单不匹配")
    required = {prefix + name for name in ("PRODUCTION_DESIGN.json", "STORYBOARD.json", "SCREENPLAY.json", "MEDIA_HANDOFF.json")}
    for item in manifest.get("artifacts", []):
        name = item["path"]
        if Path(name).name != name or file_binding(run / name)["sha256"] != item["sha256"]:
            raise ValueError("创作输出产物已更改")
        required.discard(name)
    if required:
        raise ValueError("创作输出总清单缺少必要产物")
    library = read(library_path) if library_path.is_file() else {"assets": []}
    local_path = run / "RUN_ASSET_LIBRARY.json"
    if local_path.is_file():
        local = read(local_path)
        library = {"assets": [*library.get("assets", []), *local.get("assets", [])]}
    keys = [a["reuse_key"] for a in library.get("assets", [])]
    if len(set(keys)) != len(keys):
        raise ValueError("素材库存在重复reuse_key，需明确版本后再复用")
    routes = route_assets(design, library)
    text_ready = ((revised or receipt["text_gate_status"] == "text_review_gate_satisfied")
                  and receipt["workflow_status"] in {"media_handoff_pending_capability", "reviewed_revision_media_handoff_pending_capability"})
    if revised or state.get("assistant_review_required") is not False:
        from .creative_calibration import validated_assistant_review, validated_revision_review
        actual = (validated_revision_review if revised else validated_assistant_review)(run, state)
        text_ready = text_ready and actual is not None and actual.get("outcome") == "passed"
    queue = build_queue(run, design, storyboard, routes, text_ready=text_ready)
    if text_ready and plan["blocked_shots"]:
        queue.update(stage="upstream_revision", next_action="repair_unmapped_shots", shot_ids=plan["blocked_shots"])
    requests = []
    for row in routes:
        if row["status"] == "generate":
            r = row["requirement"]
            requests.append({"id": r["id"], "type": "character_turnaround" if r["kind"] == "character" else "background",
                             "prompt": r["prompt"], "review_checks": ["identity", "visual_style", "composition"],
                             "status": "pending_text_and_style_gates", "automatic_submit": False})
    output = {"schema": "reusable_preproduction/v1", "source_run": str(run),
              "source_variant": "assistant_revised" if revised else "initial",
              "design": design,
              "source_bindings": {prefix + name: file_binding(run / (prefix + name)) for name in
                                  ("PRODUCTION_DESIGN.json", "STORYBOARD.json", "MEDIA_HANDOFF.json")},
              "asset_routes": routes, "asset_requests": requests, "queue": queue,
              "automatic_submit": False}
    output["shot_assets"] = [
        {**shot, "references": [next(r for r in routes if r["asset_id"] == aid)["selected"] for aid in shot["asset_ids"]]}
        for shot in design["shots"]
    ]
    output["segment_templates"] = plan
    write(run / "REUSABLE_PREPRODUCTION.json", output)
    write(run / "PRODUCTION_QUEUE.json", queue)
    return output

def asset_catalog(path: Path) -> list[dict]:
    """Only expose verified, reusable metadata to the director, without credentials."""
    result = []
    for asset in read(path).get("assets", []):
        try:
            verified_asset(asset)
        except (KeyError, ValueError, OSError, TypeError):
            continue
        result.append({k: asset.get(k) for k in ("reuse_key", "kind", "canonical_name", "aliases", "tags", "reuse_conditions")})
    return result


def prepare_next_work(run_dir: Path, library_path: Path) -> dict:
    """Materialize the next local work package, idempotently, with null checks.

    Packages contain existing-generator manifests or shot templates, never a
    provider call. A changed source produces a separate package; old evidence
    is not overwritten. An agent performs the actual image/audio inspection.
    """
    output = prepare_run(run_dir, library_path)
    run = Path(run_dir).resolve()
    queue = output["queue"]
    binding = {k: queue[k] for k in ("design_sha256", "storyboard_sha256", "assets_sha256") if k in queue}
    job = {"schema": "reusable_production_work/v1", "queue": queue,
           "automatic_submit": False, "remote_request_sent": False,
           "source_bindings": output["source_bindings"], "review_template": None}
    stage = queue["stage"]
    review_checks, review_name = (), None
    if stage == "style_review":
        wanted = set(queue["sample_asset_ids"])
        candidates = [r for r in output["asset_routes"] if r["asset_id"] in wanted]
        job["existing_samples"] = [r["selected"] for r in candidates if r["status"] == "reuse"]
        job["sample_requirements"] = [r["requirement"] for r in candidates if r["status"] != "reuse"]
        assets = [a for a in output["asset_requests"] if a["id"] in wanted]
        review_name, review_checks = "STYLE_REVIEW.json", ("visual_style", "character_readability", "scene_readability")
    elif stage == "assets":
        assets = output["asset_requests"]
        job["selection_tasks"] = [r for r in output["asset_routes"] if r["status"] == "select_existing"]
    else:
        assets = []
    if stage in {"style_review", "assets"} and assets:
        job["asset_manifest"] = {"schema": "ark_visual_asset_pack/v1", "model": "doubao-seedream-5-0-pro-260628",
            "size": "2560x1440", "assets": [{k: a[k] for k in ("id", "type", "prompt", "review_checks")} for a in assets]}
    if stage == "storyboard_media_review":
        job["opening_frame_jobs"] = output["shot_assets"]
        review_name, review_checks = "STORYBOARD_MEDIA_REVIEW.json", ("actual_asset_layout", "information_progression", "reaction_windows", "cut_motivation")
    if stage == "capability_review":
        job["probe_jobs"] = [s for s in output["segment_templates"]["segments"] if s["shot_id"] in queue["shot_ids"]]
        review_name, review_checks = "CAPABILITY_REVIEW.json", ("identity", "reaction", "interaction", "audio")
    if stage in {"segment", "segment_review", "generation_failed", "submission", "continuity_adapter"}:
        sid = queue["shot_id"]
        job["shot"] = next(s for s in output["shot_assets"] if s["shot_id"] == sid)
        job["segment_template"] = next(s for s in output["segment_templates"]["segments"] if s["shot_id"] == sid)
        if stage == "segment_review":
            rp = run / "media" / sid / "receipt.json"
            rec = read(rp)
            binding = {"video_sha256": rec["video"]["sha256"], "receipt_sha256": file_binding(rp)["sha256"]}
            review_name, review_checks = f"media/{sid}/review.json", VISUAL_CHECKS + AUDIO_CHECKS
    if stage == "full_film_review":
        binding = {"video_sha256": queue["video"]["sha256"],
                   "assembly_receipt_sha256": file_binding(run / "ASSEMBLY_RECEIPT.json")["sha256"]}
        review_name, review_checks = "FULL_FILM_REVIEW.json", VISUAL_CHECKS + AUDIO_CHECKS + ("emotional_focus", "ending", "all_cut_points")
    if review_name:
        job["review_destination"] = str(run / review_name)
        job["review_template"] = {"schema": "reusable_production_review/v1", **binding,
            "decision": "pending", "checks": dict.fromkeys(review_checks), "evidence": [], "observations": [],
            "instruction": "实际看图或同步听看视频后逐项记录；填写具体秒数、观察、证据文件绑定及未解决问题。未经检查保留null。"}
    job_id = digest(job)
    folder = run / "prepared_work" / job_id[:16]
    job_path = folder / "work.json"
    if not job_path.exists():
        write(job_path, job)
        if job.get("asset_manifest"):
            write(folder / "asset_manifest.json", job["asset_manifest"])
        if job["review_template"]:
            write(folder / "review.pending.json", job["review_template"])
    return {"queue": queue, "work_package": str(job_path), "automatic_submit": False}


def register_asset(run_dir: Path, asset_path: Path) -> None:
    """Register an actually reviewed generated asset locally; preserve history."""
    asset = verified_asset(read(asset_path))
    if not isinstance(asset.get("reuse_key"), str) or not asset["reuse_key"].strip():
        raise ValueError("素材缺少reuse_key")
    library_path = Path(run_dir) / "RUN_ASSET_LIBRARY.json"
    library = read(library_path) if library_path.exists() else {"schema": "reusable_visual_asset_library/v1", "assets": []}
    for existing in library["assets"]:
        if existing.get("reuse_key") == asset["reuse_key"]:
            if existing == asset:
                return
            raise ValueError("已有同名素材，禁止覆盖历史版本")
    library["assets"].append(asset)
    write(library_path, library)
