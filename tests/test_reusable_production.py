"""Offline tests of reusable routing and actual-evidence gates
    no provider calls."""
from pathlib import Path
import pytest
from src.content_factory.creative_brief import normalize_brief, brief_focus
from src.content_factory.creative_workflow_inputs import load_materials, file_binding
from src.content_factory.reusable_production import (
    SCHEMA, VISUAL_CHECKS, AUDIO_CHECKS, digest, read, write, validate_design,
    route_assets, build_queue, verified_asset, prepare_next_work,
)


def design_for(storyboard):
    return {"schema": SCHEMA, "assets": [
        {"id": "CHAR_A", "kind": "character", "name": "甲", "required_tags": ["photoreal"],
         "reuse_key": "", "prompt": "一个成年人站在柔光的中性背景前，正侧背三个角度保持相同面貌、年龄和服装，完整全身清晰可辨。"},
        {"id": "BG_ROOM", "kind": "background", "name": "室内", "required_tags": ["photoreal"],
         "reuse_key": "", "prompt": "日间室内空场景，桌子位于中部，窗户位于左侧，门口通道保持开阔，真实光影，清楚展示人物可以站立的位置。"},
    ], "shots": [
        {"shot_id": s["id"], "asset_ids": ["CHAR_A", "BG_ROOM"], "new_information": "人物得知消息",
         "reaction_subject": "甲", "cut_reason": "让观众看见反应", "reaction_window": [0, 2], "risks": [],
         "opening_prompt": "甲站在桌子右侧面对窗户，尚未开始说话，双手自然垂下，桌面物品静止，柔和侧光使面部表情清晰可见。"}
        for s in storyboard["shots"]], "issues": []}


@pytest.fixture
def scene(tmp_path):
    story = {"shots": [{"id": "SH01", "duration_seconds": 8, "continuity_mode": "planned_cut_requires_adapter"},
                       {"id": "SH02", "duration_seconds": 8, "continuity_mode": "raw_tail_continuation"}]}
    return tmp_path, design_for(story), story


def asset(tmp_path, kind="character", name="甲", key="A"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    image = tmp_path / "image.png"
    image.write_bytes(b"test original image")
    review = tmp_path / "review.json"
    write(review, {"decision": "passed", "image_sha256": file_binding(image)["sha256"],
                   "checks": {"identity": True}, "observations": ["test fixture only"]})
    receipt = tmp_path / "receipt.json"
    write(receipt, {"status": "downloaded", "image_sha256": file_binding(image)["sha256"]})
    return {"reuse_key": key, "kind": kind, "canonical_name": name, "aliases": [], "tags": ["photoreal"],
            "decision": "passed", "image": file_binding(image), "review": file_binding(review), "receipt": file_binding(receipt)}


def review(path, bindings, checks, evidence):
    write(path, {**bindings, "decision": "passed", "checks": dict.fromkeys(checks, True), "evidence": [file_binding(evidence)], "observations": [{"seconds": [0, 1], "observation": "synthetic fixture"}]})


def ready_scene(scene):
    run, design, story = scene
    library = {"assets": [asset(run / "a"), asset(run / "b", "scene", "室内", "B")]}
    routes = route_assets(design, library)
    bindings = {"design_sha256": digest(design), "storyboard_sha256": digest(story)}
    ev = run / "evidence.txt"
    ev.write_text("synthetic test inspection", encoding="utf-8")
    review(run / "STYLE_REVIEW.json", bindings, ("visual_style", "character_readability", "scene_readability"), ev)
    bindings["assets_sha256"] = digest([{"asset_id": r["asset_id"], "selected": r["selected"]} for r in routes])
    review(run / "STORYBOARD_MEDIA_REVIEW.json", bindings,
           ("actual_asset_layout", "information_progression", "reaction_windows", "cut_motivation"), ev)
    return routes, bindings, ev


def test_brief_is_replaceable_and_missing_preferences_are_delegated(tmp_path):
    p = tmp_path / "brief.json"
    write(p, {"schema": "creative_brief/v1", "theme": "关心", "duration_seconds": [20, 30]})
    bundle = load_materials(source_driver="original", title="原创", brief_path=p)
    assert bundle.source_driver == "original"
    assert "visual_style" in bundle.metadata["creative_brief"]["delegated_fields"]
    assert "20—30秒" in brief_focus(bundle.metadata["creative_brief"])
    with pytest.raises(ValueError):
        load_materials(source_driver="original", title="缺失")


@pytest.mark.parametrize("bad", [[0, 5], [20, 10], [True, 20], "20"])
def test_brief_rejects_invalid_duration(bad):
    with pytest.raises(ValueError):
        normalize_brief({"schema": "creative_brief/v1", "theme": "主题", "duration_seconds": bad})


def test_asset_reuse_recognizes_historical_scene_kind_and_checks_hashes(scene):
    run, design, _ = scene
    a, b = asset(run / "a"), asset(run / "b", "scene", "室内", "B")
    assert [r["status"] for r in route_assets(design, {"assets": [a, b]})] == ["reuse", "reuse"]
    Path(a["image"]["path"]).write_bytes(b"changed image")
    routes = route_assets(design, {"assets": [a, b]})
    assert routes[0]["status"] == "generate" and routes[0]["rejected"]


def test_ambiguous_assets_require_selection_and_similar_names_do_not_match(scene):
    run, design, _ = scene
    a, b = asset(run / "a"), asset(run / "b", key="B")
    assert route_assets(design, {"assets": [a, b]})[0]["status"] == "select_existing"
    b["canonical_name"] = "另一个甲"
    assert route_assets(design, {"assets": [b]})[0]["status"] == "generate"


def test_receipt_must_bind_reviewed_image(tmp_path):
    a = asset(tmp_path)
    write(Path(a["receipt"]["path"]), {"status": "downloaded", "image_sha256": "wrong"})
    a["receipt"] = file_binding(Path(a["receipt"]["path"]))
    with pytest.raises(ValueError, match="回执"):
        verified_asset(a)


def test_invalid_reaction_window_is_rejected(scene):
    _, design, story = scene
    design["shots"][0]["reaction_window"] = [6, 12]
    with pytest.raises(ValueError, match="窗口"):
        validate_design(design, story)


def test_text_and_style_must_be_reviewed_before_assets(scene):
    run, design, story = scene
    routes = route_assets(design, {"assets": []})
    assert build_queue(run, design, story, routes, text_ready=False)["stage"] == "text_review"
    q = build_queue(run, design, story, routes, text_ready=True)
    assert q["sample_asset_ids"] == ["CHAR_A", "BG_ROOM"]
    assert not q["full_workflow_pass"]


def test_changed_style_evidence_cannot_pass(scene):
    run, design, story = scene
    routes, _, ev = ready_scene(scene)
    ev.write_text("changed", encoding="utf-8")
    assert build_queue(run, design, story, routes, text_ready=True)["review_status"] == "stale"


def test_design_issue_returns_to_upstream(scene):
    run, design, story = scene
    design["issues"] = [{"shot_id": "SH01", "owner": "writer", "reason": "动作没有新信息"}]
    assert build_queue(run, design, story, [], text_ready=True)["next_action"] == "repair_design_issues"


def segment(run, sid, bindings, ev, previous=None):
    folder = run / "media" / sid
    folder.mkdir(parents=True)
    video, tail = folder / "video.mp4", folder / "tail.png"
    video.write_bytes((sid + " test video").encode())
    tail.write_bytes((sid + " test original tail").encode())
    rec = {**bindings, "status": "succeeded", "video": file_binding(video), "original_tail": file_binding(tail),
           "first_frame_sha256": previous["sha256"] if previous else "opening"}
    rp = folder / "receipt.json"
    write(rp, rec)
    review(folder / "review.json", {"video_sha256": rec["video"]["sha256"], "receipt_sha256": file_binding(rp)["sha256"]},
           VISUAL_CHECKS + AUDIO_CHECKS, ev)
    return rec


def test_audio_pending_blocks_next_segment_and_complete_requires_full_film(scene):
    run, design, story = scene
    routes, bindings, ev = ready_scene(scene)
    first = segment(run, "SH01", bindings, ev)
    rp = run / "media/SH01/review.json"
    r = read(rp)
    r["checks"]["lip_sync"] = None
    write(rp, r)
    assert build_queue(run, design, story, routes, text_ready=True)["stage"] == "segment_review"
    r["checks"]["lip_sync"] = True
    write(rp, r)
    q = build_queue(run, design, story, routes, text_ready=True)
    assert q["shot_id"] == "SH02" and q["original_tail"] == first["original_tail"]
    segment(run, "SH02", bindings, ev, first["original_tail"])
    q = build_queue(run, design, story, routes, text_ready=True)
    assert q["stage"] == "assembly" and not q["full_workflow_pass"]
    film = run / "film.mp4"
    film.write_bytes(b"assembled test video")
    write(run / "ASSEMBLY_RECEIPT.json", {"segments_sha256": q["segments_sha256"], "video": file_binding(film)})
    assert build_queue(run, design, story, routes, text_ready=True)["stage"] == "full_film_review"
    review(run / "FULL_FILM_REVIEW.json", {"video_sha256": file_binding(film)["sha256"],
           "assembly_receipt_sha256": file_binding(run / "ASSEMBLY_RECEIPT.json")["sha256"]},
           VISUAL_CHECKS + AUDIO_CHECKS + ("emotional_focus", "ending", "all_cut_points"), ev)
    assert build_queue(run, design, story, routes, text_ready=True)["full_workflow_pass"]


def test_wrong_tail_and_failed_generation_cannot_advance(scene):
    run, design, story = scene
    routes, bindings, ev = ready_scene(scene)
    segment(run, "SH01", bindings, ev)
    segment(run, "SH02", bindings, ev, {"sha256": "wrong"})
    assert build_queue(run, design, story, routes, text_ready=True)["stage"] == "continuity_failed"
    p = run / "media/SH01/receipt.json"
    r = read(p)
    r["status"] = "failed"
    write(p, r)
    assert build_queue(run, design, story, routes, text_ready=True)["stage"] == "generation_failed"


def test_cut_requires_existing_continuation_policy(scene):
    run, design, story = scene
    story["shots"][1]["continuity_mode"] = "planned_cut_requires_adapter"
    routes, bindings, ev = ready_scene(scene)
    segment(run, "SH01", bindings, ev)
    assert build_queue(run, design, story, routes, text_ready=True)["stage"] == "continuity_adapter"


def test_original_workflow_adds_budgeted_director_design_and_resumes(tmp_path):
    from test_creative_workflow import _answers, FakeClients
    from src.content_factory.creative_workflow import CreativeWorkflow
    answers = _answers()
    answers[0]["candidates"][0].update(start_quote="", end_quote="")
    answers.append(design_for(answers[3]))
    p = tmp_path / "brief.json"
    write(p, {"schema": "creative_brief/v1", "theme": "和解", "duration_seconds": [20, 30]})
    bundle = load_materials(source_driver="original", title="测试", brief_path=p)
    clients = FakeClients(answers)
    run = tmp_path / "run"
    state = CreativeWorkflow(run, clients=clients).run(bundle)
    assert state["calls_started"] == 6
    assert read(run / "MEDIA_HANDOFF.json")["production_design_sha256"] == digest(read(run / "PRODUCTION_DESIGN.json"))
    result = prepare_next_work(run, tmp_path / "absent.json")
    assert result["queue"]["stage"] == "text_review"
    assert not result["automatic_submit"]
    again = prepare_next_work(run, tmp_path / "absent.json")
    assert again == result
    receipt = read(run / "director_production_design.json")
    assert receipt["status"] == "validated"
    assert receipt["output"] == read(run / "PRODUCTION_DESIGN.json")
    assert receipt["request"]["messages"]
    import json
    request = json.loads(read(run / "director_shots.json")["request"]["messages"][-1]["content"])
    assert request["executor_constraints"]["duration_max"] == 15
    assert "planning_rules" in json.loads(receipt["request"]["messages"][-1]["content"])
    from scripts.revise_creative_from_assistant import bound_workflow
    _, restored = bound_workflow(run)
    assert restored.metadata["creative_brief"] == bundle.metadata["creative_brief"]
    assert restored.manifest == bundle.manifest
    before = len(clients.calls)
    CreativeWorkflow(run, clients=clients).run(bundle)
    assert len(clients.calls) == before


def test_reviewed_original_prepares_valid_small_sample_pack(tmp_path):
    from test_creative_workflow import _answers, FakeClients
    from src.content_factory.creative_workflow import CreativeWorkflow
    from src.content_factory.creative_calibration import record_review
    from scripts.generate_ark_asset_pack import validate_manifest
    answers = _answers()
    answers[0]["candidates"][0].update(start_quote="", end_quote="")
    answers.append(design_for(answers[3]))
    brief = tmp_path / "brief.json"
    write(brief, {"schema": "creative_brief/v1", "theme": "和解"})
    bundle = load_materials(source_driver="original", title="测试", brief_path=brief)
    run = tmp_path / "run"
    CreativeWorkflow(run, clients=FakeClients(answers)).run(bundle)
    evidence = tmp_path / "editorial.md"
    evidence.write_text("隔离测试中的虚构审核记录，不能作为实际视频质量证据。" * 10, encoding="utf-8")
    record_review(run, category="video_original", outcome="passed", evidence_file=evidence)
    result = prepare_next_work(run, tmp_path / "absent.json")
    work = read(Path(result["work_package"]))
    assert result["queue"]["stage"] == "style_review"
    assert len(work["asset_manifest"]["assets"]) == 2
    validate_manifest(work["asset_manifest"])
    assert set(work["review_template"]["checks"].values()) == {None}
    evidence.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="证据"):
        prepare_next_work(run, tmp_path / "absent.json")


def test_reviewed_revision_exports_its_own_design_and_work_package(tmp_path):
    from copy import deepcopy
    from test_creative_workflow import _answers, FakeClients
    from src.content_factory.creative_workflow import CreativeWorkflow
    from src.content_factory.creative_workflow_contract import compile_beat_screenplay
    from src.content_factory.creative_calibration import record_review, record_revision_review
    answers = _answers()
    answers[0]["candidates"][0].update(start_quote="", end_quote="")
    answers.append(design_for(answers[3]))
    brief = tmp_path / "brief.json"
    write(brief, {"schema": "creative_brief/v1", "theme": "和解"})
    bundle = load_materials(source_driver="original", title="测试", brief_path=brief)
    run = tmp_path / "run"
    CreativeWorkflow(run, clients=FakeClients(answers)).run(bundle)
    original_design = read(run / "PRODUCTION_DESIGN.json")
    evidence = tmp_path / "editorial.md"
    evidence.write_text("隔离测试中的虚构审核记录，第一拍需补充道具首次出现以说明动机。" * 8, encoding="utf-8")
    record_review(run, category="video_original", outcome="major_issues", evidence_file=evidence)
    state = read(run / "state.json")
    feedback = tmp_path / "feedback.json"
    write(feedback, {"schema": "creative_assistant_feedback/v1", "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "B01", "evidence": "道具未出现",
                    "impact": "动机不清", "proposal": "建立首次出现", "severity": "major"}]})
    revised = deepcopy(answers[2])
    revised["beats"][0]["before"] = "先建立道具再迟疑"
    revised["screenplay_markdown"] = compile_beat_screenplay(revised)
    design = design_for(answers[3])
    design["shots"][0]["new_information"] = "先看到道具再看到迟疑"
    updated = CreativeWorkflow(run, clients=FakeClients([revised, answers[3], answers[4], design])).revise_from_assistant(bundle, feedback)
    assert updated["calls_started"] == 10
    import json
    request = json.loads(read(run / "director_production_design__assistant_01.json")["request"]["messages"][-1]["content"])
    assert request["issues"] == read(feedback)["issues"]
    assert request["previous_design"] == original_design
    followup = tmp_path / "followup.md"
    followup.write_text("隔离测试中的虚构复审记录，不是实际成片证据，第一拍已给出明确刺激和反应。" * 8, encoding="utf-8")
    record_revision_review(run, outcome="passed", evidence_file=followup)
    CreativeWorkflow(run, clients=FakeClients([])).promote_reviewed_assistant_revision(bundle)
    result = prepare_next_work(run, tmp_path / "absent.json")
    assert result["queue"]["stage"] == "style_review"
    assert read(run / "REUSABLE_PREPRODUCTION.json")["source_variant"] == "assistant_revised"
    assert read(run / "PRODUCTION_DESIGN.json") == original_design
    assert read(run / "ASSISTANT_REVISED_PRODUCTION_DESIGN.json") == design


@pytest.mark.parametrize("failure", ["unknown_key", "tags", "changed_image"])
def test_explicit_reuse_conflict_blocks_before_style_or_generation(scene, failure):
    run, design, story = scene
    a = asset(run / "a")
    design["assets"][0]["reuse_key"] = a["reuse_key"]
    if failure == "unknown_key":
        design["assets"][0]["reuse_key"] = "unknown"
    elif failure == "tags":
        design["assets"][0]["required_tags"].append("unverified_apron")
    else:
        Path(a["image"]["path"]).write_bytes(b"changed")
    routes = route_assets(design, {"assets": [a]})
    assert routes[0]["status"] == "reuse_conflict"
    assert routes[0]["selected"] is None
    assert build_queue(run, design, story, routes, text_ready=True)["next_action"] == "repair_asset_reuse_conflicts"


def test_catalog_conflict_is_a_repairable_workflow_error(scene):
    from src.content_factory.creative_workflow import _validate_production_design
    from src.content_factory.creative_workflow_contract import CreativeContractError
    _, design, story = scene
    design["assets"][0]["reuse_key"] = "absent"
    with pytest.raises(CreativeContractError, match="指定复用键"):
        _validate_production_design(design, story, [])
