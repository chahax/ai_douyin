"""Offline v4 workflow gates; no production prepare, provider, media or quota calls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts import run_creative_resume_v4 as resume
from scripts import creative_resume_dispatch_v2 as control
from scripts import creative_linear_script_v3 as linear
from scripts import creative_review_wire_v10 as review_wire
from scripts import creative_joint_source_binding_v10 as joint
from scripts import creative_compact_review_transport_v8 as compact
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_review_v3 import CHECKS
from tests.test_run_creative_resume_v1 import complete_joint_review, first_ref


def capture_dispatch(monkeypatch):
    captured = []
    def dispatch(label, wire, validator):
        captured.append({"label": label, "wire": deepcopy(wire), "validator": validator})
        return {"status": "offline_request_captured", "label": label}
    monkeypatch.setattr(resume, "runtime", lambda: SimpleNamespace(dispatch=dispatch))
    return captured


def actual_plan():
    path = resume.previous_run.ROOT / "call_060_story_plan_r8.json"
    return resume.stage_record_view(control.read(path))


def rebind(context, direction, locals_):
    direction["context_sha256"] = control.digest(context)
    direction["raw_linear_script_sha256"] = control.digest(context["raw_linear_script"])
    for index, local in enumerate(locals_):
        local["input_sha256"] = control.digest(resume.physical.build_local_input(context, direction, locals_[:index]))


def source_case():
    context, direction, locals_ = resume.physical.make_surface_offline_case(untimed=True)
    original = resume.original()
    for key in ("creative_brief", "material_ref", "reference_pack", "reference_expression_rule"):
        context[key] = deepcopy(original[key])
    context["adopted_story_direction"] = deepcopy(actual_plan()["output"])
    context["linear_script_protocol"] = linear.VERSION
    context["script_timing_status"] = linear.TIMING_STATUS
    context["script_preliminary_timing"] = linear.preliminary_timing_estimates(context["raw_linear_script"])
    rebind(context, direction, locals_)
    return context, direction, locals_


def derive_case(raw):
    return linear.accept_linear_script(raw, raw, character_names=["甲", "乙"])


@pytest.fixture
def compiled_case(tmp_path, monkeypatch):
    context, direction, locals_ = source_case()
    before = deepcopy(context["raw_linear_script"])
    monkeypatch.setattr(resume, "ROOT", tmp_path)
    monkeypatch.setattr(resume, "direction_source", lambda n, revision: (deepcopy(context), deepcopy(direction)))
    monkeypatch.setattr(resume, "local_sources", lambda n, revision, count: deepcopy(locals_[:count]))
    monkeypatch.setattr(resume, "derive", derive_case)
    final_context, compiled = resume.final_context(5, 1)
    assert context["raw_linear_script"] == before
    return context, direction, locals_, final_context, compiled


def leaf(ctx, path):
    value = ctx
    for item in path.split("."):
        value = value[int(item)] if isinstance(value, list) else value[item]
    assert isinstance(value, (str, int, float)) and not isinstance(value, bool)
    return {"path": path, "quote": value if isinstance(value, str) else json.dumps(value)}


def joint_review_for(ctx):
    review = complete_joint_review(ctx)
    for row, mapped in zip(review["coverage"], joint.preflight(ctx)["mapping"]):
        row["checks"]["timing"]["evidence_refs"] += [
            leaf(ctx, mapped["timing_source_leaves"][-1]),
            leaf(ctx, mapped["execution_timing_leaves"][0])]
        row["checks"]["continuity"]["evidence_refs"] += [
            leaf(ctx, path) for path in mapped["continuity_source_leaves"]]
        if mapped["dialogue_text_leaves"]:
            row["checks"]["dialogue_timing"]["evidence_refs"] += [
                leaf(ctx, mapped["dialogue_text_leaves"][0]),
                leaf(ctx, mapped["dialogue_window_leaves"][0])]
        else:
            row["checks"]["dialogue_timing"] = {
                "status": "not_applicable", "reason": "离线夹具本镜无对白",
                "evidence_refs": [], "issue_ids": []}
    return review


def script_review_for(ctx):
    coverage = []
    for index, beat in enumerate(ctx["script"]["beats"]):
        own = f"script.beats.{index}."
        checks = {}
        for name in CHECKS:
            status = "not_applicable" if name in ("dialogue_timing", "first_frame", "assets") else "pass"
            refs = [] if status == "not_applicable" else [first_ref(ctx, own)]
            if name == "timing":
                refs = [leaf(ctx, own + "before")]
            if name == "continuity" and index:
                refs.append(first_ref(ctx, f"script.beats.{index-1}."))
            checks[name] = {"status": status,
                "reason": "离线协议测试；正文先后可审，实际对白/反应窗口尚未编排",
                "evidence_refs": refs, "issue_ids": []}
        coverage.append({"id": beat["id"], "checks": checks})
    return {"story_preserved": True, "issues": [], "suggestions": [],
        "calibration_focus": [], "coverage": coverage}


def preliminary_script_context():
    c, _, _ = source_case()
    raw = deepcopy(c["raw_linear_script"])
    c.pop("raw_linear_script")
    c.pop("component_registry")
    c["script"] = derive_case(raw)
    c["script"].pop("screenplay_markdown")
    c["script_revision_source"] = {"raw_sha256": control.digest(raw), "protocol": linear.VERSION}
    return c


def test_runtime_inherits_actual_62_and_620826_without_prepare_or_provider(tmp_path, monkeypatch):
    root = tmp_path / "unprepared"
    monkeypatch.setattr(resume, "ROOT", root)
    old = resume.previous_run.ROOT / "CALL_LEDGER.json"
    before = control.sha_file(old)
    runtime = resume.runtime()
    assert runtime.inherited["calls_started"] == 62
    assert runtime.inherited["reported_tokens"] == 620826
    assert runtime.inherited["legacy_max_total_tokens"] == 500000
    assert runtime.inherited["historical_legacy_calls"] == 49
    assert runtime.inherited["historical_legacy_reported_tokens"] == 490913
    assert runtime.inherited["prior_aggregate_limit"] is None
    assert runtime.inherited["last_rejection"]["ordinal"] == 62
    assert runtime.quota_state is None
    runtime.inherited_guard()
    assert control.sha_file(old) == before
    assert not root.exists() and not runtime.ledger.exists()
    assert "get_usage_limits" not in Path(resume.__file__).read_text(encoding="utf-8")


def test_runtime_parent_hash_change_blocks_without_new_root_or_sdk(tmp_path, monkeypatch):
    root = tmp_path / "unprepared"
    monkeypatch.setattr(resume, "ROOT", root)
    runtime = resume.runtime()
    evidence = (resume.previous_run.ROOT / "STORY_PLAN_DECISION_call60.json").resolve()
    original_hash = control.sha_file
    monkeypatch.setattr(control, "sha_file",
        lambda path: "0" * 64 if Path(path).resolve() == evidence else original_hash(path))
    with pytest.raises(RuntimeError, match="prior frozen evidence changed"):
        runtime.inherited_guard()
    assert not root.exists()


def test_parent60_approved_direction_is_read_only_fallback(tmp_path, monkeypatch):
    plan = actual_plan()
    before = control.sha_file(resume.previous_run.ROOT / "STORY_PLAN_DECISION_call60.json")
    monkeypatch.setattr(resume, "ROOT", tmp_path / "new")
    monkeypatch.setattr(resume, "latest", lambda prefix: deepcopy(plan))
    adopted = resume.adopted_story_plan()
    assert adopted["ordinal"] == 60 and adopted["label"] == "story_plan_r8"
    assert adopted["output"] == plan["output"]
    assert not (tmp_path / "new").exists()
    assert control.sha_file(resume.previous_run.ROOT / "STORY_PLAN_DECISION_call60.json") == before


@pytest.mark.parametrize("ordinal", [53, 61, 62])
def test_fallback_cannot_adopt_a_non60_parent_direction_even_if_a_file_exists(tmp_path, monkeypatch, ordinal):
    parent = tmp_path / "parent"; parent.mkdir()
    plan = actual_plan()
    plan.update(ordinal=ordinal, label="story_plan_r_unapproved")
    control.write(parent / f"STORY_PLAN_DECISION_call{ordinal}.json",
        {"approved_for_complete_script": True, "plan_sha256": control.digest(plan["output"])})
    monkeypatch.setattr(resume, "ROOT", tmp_path / "new")
    monkeypatch.setattr(resume.previous_run, "ROOT", parent)
    monkeypatch.setattr(resume, "latest", lambda prefix: deepcopy(plan))
    with pytest.raises((RuntimeError, FileNotFoundError)):
        resume.adopted_story_plan()
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("status", ["contract_rejected", "interface_rejected", "pending_response", "outcome_unknown"])
def test_latest_failed_plan_blocks_without_falling_back_to_parent60(monkeypatch, status):
    good = actual_plan()
    bad = deepcopy(good)
    bad.update(ordinal=64, label="story_plan_r9", status=status)
    monkeypatch.setattr(resume, "records", lambda: [deepcopy(good), deepcopy(bad)])
    with pytest.raises(RuntimeError, match="no fallback"):
        resume.adopted_story_plan()


def test_stale_or_unapproved_parent60_decision_blocks(tmp_path, monkeypatch):
    parent = tmp_path / "parent"; parent.mkdir()
    plan = actual_plan()
    monkeypatch.setattr(resume, "ROOT", tmp_path / "new")
    monkeypatch.setattr(resume.previous_run, "ROOT", parent)
    monkeypatch.setattr(resume, "latest", lambda prefix: deepcopy(plan))
    path = parent / "STORY_PLAN_DECISION_call60.json"
    control.write(path, {"approved_for_complete_script": True, "plan_sha256": "stale"})
    with pytest.raises(RuntimeError, match="stale"):
        resume.adopted_story_plan()
    control.write(path, {"approved_for_complete_script": False, "plan_sha256": control.digest(plan["output"])})
    with pytest.raises(RuntimeError, match="not adopted"):
        resume.adopted_story_plan()


def test_fresh_writer_wire_preserves_full_R01_brief_original_assets_without_failed_action_template(monkeypatch):
    original = resume.original()
    plan = actual_plan()
    previous = {"title": "FAILED_62_SENTINEL", "beats": [{"steps": [{"text": "FAILED_62_MICRO_CHAIN"}]}]}
    sequenced = []
    monkeypatch.setattr(resume, "previous_draft_for_revision", lambda n: sequenced.append(n) or deepcopy(previous))
    monkeypatch.setattr(resume, "adopted_story_plan", lambda: deepcopy(plan))
    captured = capture_dispatch(monkeypatch)
    resume.draft(5, feedback={"verified": "对白排时由局部阶段负责"})
    wire = captured[0]["wire"]
    payload = json.loads(wire["messages"][1]["content"])
    assert sequenced == [5]
    assert payload["context"]["creative_brief"] == original["creative_brief"]
    assert payload["context"]["static_visual_manifest"] == original["static_visual_manifest"]
    assert payload["context"]["reference_pack"] == original["reference_pack"]
    assert any(row["id"] == "R01" and row["text"] for row in payload["context"]["reference_pack"])
    assert payload["context"]["adopted_story_direction"] == plan["output"]
    assert payload["previous_script"] == {} and "script" not in payload["context"]
    text = json.dumps(wire["messages"], ensure_ascii=False)
    assert "FAILED_62_SENTINEL" not in text and "FAILED_62_MICRO_CHAIN" not in text
    beat_schema = wire["inner_document_schema"]["properties"]["beats"]["items"]
    assert "duration_seconds" not in beat_schema["properties"]
    assert "duration_seconds" not in beat_schema["required"]
    assert wire["input_provenance"]["story_plan_ordinal"] == 60
    assert wire["model"] == "MiniMax-M3"
    assert wire["parameters"]["max_completion_tokens"] == 6500


def test_director_context_keeps_complete_original_registry_and_untimed_raw_source(monkeypatch):
    context, _, _ = source_case()
    original = resume.original()
    original["static_visual_manifest"] = deepcopy(context["component_registry"]["original_manifest"])
    source = {"ordinal": 63, "output": deepcopy(context["raw_linear_script"])}
    before = deepcopy((original, source))
    monkeypatch.setattr(resume, "original", lambda: deepcopy(original))
    monkeypatch.setattr(resume, "require_script_decision", lambda n: {"approved_for_direction": True})
    monkeypatch.setattr(resume, "ensure_latest_draft", lambda n: deepcopy(source))
    monkeypatch.setattr(resume, "adopted_story_plan", actual_plan)
    result = resume.director_context(5)
    assert (original, source) == before
    assert result["raw_linear_script"] == source["output"]
    assert all("duration_seconds" not in b for b in result["raw_linear_script"]["beats"])
    bundle = result["component_registry"]
    assert bundle["original_manifest"] == original["static_visual_manifest"]
    assert bundle["original_manifest_sha256"] == control.digest(original["static_visual_manifest"])
    assert bundle["effective_manifest"] == result["static_visual_manifest"]
    assert "P03" not in {p["id"] for p in result["static_visual_manifest"]["props"]}
    assert set(bundle["member_source_map"]) == {"P03_Y", "P03_P", "P03_B"}
    assert result["reference_pack"] == original["reference_pack"]
    assert result["script_timing_status"] == "preliminary_budget_not_actual"
    assert result["script_preliminary_timing"]["raw_sha256"] == control.digest(source["output"])
    assert result["script_preliminary_timing"]["actual_windows_verified"] is False


def test_direction_wire_carries_registry_and_canonical_component_location_contract(monkeypatch):
    context, _, _ = source_case()
    monkeypatch.setattr(resume, "director_context", lambda n: deepcopy(context))
    monkeypatch.setattr(resume, "require_script_decision", lambda n: {"approved_for_direction": True})
    captured = capture_dispatch(monkeypatch)
    resume.direction(5)
    wire = captured[0]["wire"]
    payload = json.loads(wire["messages"][1]["content"])
    assert payload["context"] == context
    assert payload["context"]["component_registry"]["original_manifest"] == context["component_registry"]["original_manifest"]
    description = wire["inner_document_schema"]["properties"]["initial_state"]["properties"]["P03_Y"]["properties"]["location"]["description"]
    assert "surface:" in description
    assert "slide" in wire["messages"][0]["content"]
    assert wire["input_provenance"]["actual_selected_images"] == []
    assert wire["input_provenance"]["images_returned_to_director"] is False


def test_local_actual_wire_uses_compiled_prefix_yellow_changed_pink_blue_unchanged(monkeypatch):
    context, direction, locals_ = source_case()
    monkeypatch.setattr(resume, "direction_source", lambda n, revision: (deepcopy(context), deepcopy(direction)))
    monkeypatch.setattr(resume, "local_sources", lambda n, revision, count: deepcopy(locals_[:count]))
    captured = capture_dispatch(monkeypatch)
    resume.local(5, 1, 2)
    wire = captured[0]["wire"]
    inp = json.loads(wire["messages"][1]["content"])["local_input"]
    assert inp["start_state"]["P03_Y"] == {"holder": "none", "location": "surface:E02:near_fang"}
    assert inp["start_state"]["P03_P"] == direction["initial_state"]["P03_P"]
    assert inp["start_state"]["P03_B"] == direction["initial_state"]["P03_B"]
    assert inp["previous_local_sha256"] == [control.digest(locals_[0])]
    assert inp["context"]["reference_pack"] == context["reference_pack"]
    assert wire["input_provenance"]["local_input_sha256"] == control.digest(inp)


def test_final_context_untimed_source_and_real_compile_reach_joint10_preflight(compiled_case):
    original, _, _, ctx, compiled = compiled_case
    before = deepcopy(ctx)
    proof = joint.preflight(ctx)
    assert ctx == before
    assert ctx["raw_linear_script"] == original["raw_linear_script"] == compiled["source_raw_linear_script"]
    assert all("duration_seconds" not in b for b in ctx["raw_linear_script"]["beats"])
    assert ctx["script_timing_status"] == "preliminary_budget_not_actual"
    assert ctx["script_preliminary_timing"]["actual_windows_verified"] is False
    assert compiled["execution_timing_source"] == "local_duration_and_actual_schedule_only"
    assert compiled["semantic_approval"] is False and compiled["production_ready"] is False
    assert proof["physical_projection_recomputed"] is True and proof["semantic_approval"] is False
    assert [(m["narrative_beat_id"], m["execution_shot_id"], m["storyboard_id"]) for m in proof["mapping"]] == [
        ("B1", "S1", "SH01"), ("B1", "S2", "SH02")]
    assert not any(path.startswith("raw_linear_script.") and path.endswith(".duration_seconds")
        for m in proof["mapping"] for path in m["timing_source_leaves"])


def test_joint_wire_and_complete_review_require_actual_evidence_not_program_budget_alone(compiled_case):
    ctx = compiled_case[3]
    before = deepcopy(ctx)
    messages = review_wire.joint_messages(ctx, resume.joint_review_messages(ctx))
    assert json.loads(messages[1]["content"]) == ctx == before
    assert "execution_timing_leaves" in messages[0]["content"]
    assert "不拿上游估时替代实调" in messages[0]["content"]
    review = joint_review_for(ctx)
    raw = compact.encode_review(review, ctx)
    Draft202012Validator(review_wire.schema(ctx)).validate(raw)
    assert joint.validate_joint_review(compact.expand_review(raw, ctx), ctx)["semantic_approval"] is False
    invalid = deepcopy(review)
    invalid["coverage"][0]["checks"]["timing"]["evidence_refs"] = [
        leaf(ctx, "shots.shots.0.id"), leaf(ctx, "script.beats.0.duration_seconds")]
    with pytest.raises(CreativeContractError, match="JOINT_TIMING_EXECUTION_MISSING"):
        joint.validate_joint_review(invalid, ctx)


def test_joint_actual_dialogue_cannot_be_not_applicable(compiled_case):
    ctx = compiled_case[3]
    review = joint_review_for(ctx)
    review["coverage"][0]["checks"]["dialogue_timing"] = {
        "status": "not_applicable", "reason": "错误套用脚本预估阶段的N/A规则", "evidence_refs": [], "issue_ids": []}
    with pytest.raises(CreativeContractError, match="JOINT_DIALOGUE_SOURCE_MISSING"):
        joint.validate_joint_review(review, ctx)


def test_script_wire_checks_source_order_and_marks_delivery_window_unavailable():
    ctx = preliminary_script_context()
    before = deepcopy(ctx)
    messages = review_wire.script_messages(ctx)
    assert json.loads(messages[1]["content"]) == ctx == before
    assert "timing检查继续逐拍审刺激→对白→反应的源顺序，不能not_applicable" in messages[0]["content"]
    assert "dialogue_timing应not_applicable" in messages[0]["content"]
    assert "本次只批准正文进入导演安排" in messages[0]["content"]
    review = script_review_for(ctx)
    raw = compact.encode_review(review, ctx)
    assert review_wire.validate_script_review(raw, ctx) == review


def test_preliminary_program_budget_cannot_approve_actual_dialogue_timing():
    ctx = preliminary_script_context()
    review = script_review_for(ctx)
    review["coverage"][0]["checks"]["dialogue_timing"] = {
        "status": "pass", "reason": "把程序预算误称实际对白和表演窗口已通过",
        "evidence_refs": [leaf(ctx, "script.beats.0.duration_seconds")], "issue_ids": []}
    raw = compact.encode_review(review, ctx)
    before = deepcopy(raw)
    with pytest.raises(CreativeContractError, match="SCRIPT_ACTUAL_TIMING_UNAVAILABLE"):
        review_wire.validate_script_review(raw, ctx)
    assert raw == before


def test_preliminary_script_timing_cannot_skip_stimulus_dialogue_reaction_source_order():
    ctx = preliminary_script_context()
    review = script_review_for(ctx)
    review["coverage"][0]["checks"]["timing"] = {
        "status": "not_applicable", "reason": "错误认为无实际秒数可以不审源先后", "evidence_refs": [], "issue_ids": []}
    # encode enforces the unchanged full business validator, so rejection can occur here.
    with pytest.raises(CreativeContractError, match="不能跳过"):
        compact.encode_review(review, ctx)


def test_script_review_actual_dispatch_validator_and_effective_reader_both_reject_delivery_pass(monkeypatch):
    ctx = preliminary_script_context()
    monkeypatch.setattr(resume, "script_context", lambda n: deepcopy(ctx))
    monkeypatch.setattr(resume, "ensure_latest_draft", lambda n: {"output": {"raw_fixture": True}})
    captured = capture_dispatch(monkeypatch)
    resume.script_review(5)
    review = script_review_for(ctx)
    good = compact.encode_review(review, ctx)
    assert captured[0]["validator"](good)["semantic_approval"] is False
    review["coverage"][0]["checks"]["dialogue_timing"] = {
        "status": "pass", "reason": "错误把预算当真实表演时间",
        "evidence_refs": [leaf(ctx, "script.beats.0.duration_seconds")], "issue_ids": []}
    bad = compact.encode_review(review, ctx)
    with pytest.raises(CreativeContractError, match="SCRIPT_ACTUAL_TIMING_UNAVAILABLE"):
        captured[0]["validator"](bad)
    monkeypatch.setattr(resume, "latest", lambda prefix: {"output": deepcopy(bad)})
    with pytest.raises(CreativeContractError, match="SCRIPT_ACTUAL_TIMING_UNAVAILABLE"):
        resume.effective_script_review(5)


def test_readable_plan_keeps_raw_steps_once_and_original_slide_not_take_place_hold(compiled_case):
    _, _, _, ctx, compiled = compiled_case
    before = deepcopy((ctx, compiled))
    text = resume.render_production_plan(ctx, compiled)
    assert (ctx, compiled) == before
    assert '"kind": "slide"' in text and '"target": "P03_Y"' in text
    for beat in ctx["raw_linear_script"]["beats"]:
        for step in beat["steps"]:
            rendered = step["speaker"] + "：" + step["text"] if step["kind"] == "dialogue" else step["text"]
            assert text.count(rendered) == 1
    assert "同一原步骤续行（不重演动作）" in text
    assert "不计作声明反应窗口" in text
    assert "awaiting_human_review" in text


def test_finalize_delivers_full_untimed_script_and_plan_without_claiming_media_or_quality(compiled_case, monkeypatch):
    _, _, _, ctx, compiled = compiled_case
    review = joint_review_for(ctx)
    raw = ctx["raw_linear_script"]
    source = {"ordinal": 63, "output": deepcopy(raw)}
    receipt = {"ordinal": 68, "output": compact.encode_review(review, ctx)}
    monkeypatch.setattr(resume, "get_effective_final_review",
        lambda n, revision: (deepcopy(ctx), deepcopy(compiled), deepcopy(receipt), deepcopy(review)))
    monkeypatch.setattr(resume, "ensure_latest_draft", lambda n: deepcopy(source))
    monkeypatch.setattr(resume, "runtime", lambda: SimpleNamespace(summary=lambda: {
        "effective_calls_started": 62, "effective_reported_tokens": 620826}))
    evidence = [{"path": "raw_linear_script.beats.0.steps.0.text",
        "quote": raw["beats"][0]["steps"][0]["text"],
        "finding": "离线交接门禁夹具，不能计为真实模型审查或创作质量批准"}]
    handoff = resume.finalize(5, 1, evidence)
    folder = resume.ROOT / "DELIVERABLE_s5_d1"
    assert control.read(folder / "FULL_SCRIPT.json") == raw
    assert "duration_seconds" not in json.dumps(control.read(folder / "FULL_SCRIPT.json"))
    assert (folder / "FULL_SCRIPT.md").read_text(encoding="utf-8").startswith("# " + raw["title"])
    assert '"kind": "slide"' in (folder / "DIRECTOR_PERFORMANCE_PLAN.md").read_text(encoding="utf-8")
    assert handoff["text_production_handoff_complete"] is True
    assert handoff["status"] == "text_reviewed_awaiting_aesthetic_samples"
    assert handoff["actual_selected_images"] == []
    assert handoff["actual_images_returned_to_director"] is False
    assert handoff["asset_sample_selection_status"] == "awaiting_human_aesthetic_approval"
    assert handoff["component_registry"] == ctx["component_registry"]
    assert handoff["original_asset_manifest_preserved"] is True
    assert handoff["preliminary_script_budget_was_not_actual"] is True
    assert handoff["media_calls"] == 0 and handoff["video_content_status"] is None
    assert handoff["video_human_review_required"] is True and handoff["automatic_media_submit"] is False
    assert handoff["old_task_or_budget_reset"] is False
    assert not any("quality" in key and value is True for key, value in handoff.items())


@pytest.mark.parametrize("problem", ["issues", "story_not_preserved"])
def test_finalize_rejects_unresolved_review_before_writing_delivery(compiled_case, monkeypatch, problem):
    _, _, _, ctx, compiled = compiled_case
    review = joint_review_for(ctx)
    if problem == "issues":
        review["issues"] = [{"id": "OFFLINE_UNRESOLVED"}]
    else:
        review["story_preserved"] = False
    monkeypatch.setattr(resume, "get_effective_final_review",
        lambda n, revision: (deepcopy(ctx), deepcopy(compiled), {"ordinal": 68}, deepcopy(review)))
    with pytest.raises(RuntimeError, match="unresolved"):
        resume.finalize(5, 1, [])
    assert not (resume.ROOT / "DELIVERABLE_s5_d1").exists()

def test_parent60_with_wrong_label_is_not_a_valid_fallback(tmp_path, monkeypatch):
    parent = tmp_path / "parent"; parent.mkdir()
    plan = actual_plan()
    plan["label"] = "story_plan_r_other"
    control.write(parent / "STORY_PLAN_DECISION_call60.json",
        {"approved_for_complete_script": True, "plan_sha256": control.digest(plan["output"])})
    monkeypatch.setattr(resume, "ROOT", tmp_path / "new")
    monkeypatch.setattr(resume.previous_run, "ROOT", parent)
    monkeypatch.setattr(resume, "latest", lambda prefix: deepcopy(plan))
    with pytest.raises((RuntimeError, FileNotFoundError)):
        resume.adopted_story_plan()


def test_joint10_tool_schema_remains_plain_arrays_and_dict_row_is_rejected(compiled_case):
    ctx = compiled_case[3]
    schema = review_wire.schema(ctx)
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["coverage"]["type"] == "array"
    assert schema["properties"]["coverage"]["items"]["type"] == "array"
    text = json.dumps(schema)
    assert '"strict"' not in text and '"prefixItems"' not in text
    review = compact.encode_review(joint_review_for(ctx), ctx)
    review["coverage"][0] = {"id": review["coverage"][0][0], "checks": {}}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(review)
    with pytest.raises(CreativeContractError, match="COMPACT_ROW_SHAPE_INVALID"):
        compact.expand_review(review, ctx)


def test_script_decision_only_approves_direction_and_binds_receipt_not_media(tmp_path, monkeypatch):
    ctx = preliminary_script_context()
    review = script_review_for(ctx)
    source = {"ordinal": 63, "output": {"untimed_source_fixture": True}}
    receipt = {"ordinal": 64, "label": "script_review_s5_r1",
        "status": "contract_valid", "output": compact.encode_review(review, ctx)}
    name = "call_064_script_review_s5_r1.json"
    control.write(tmp_path / name, receipt)
    control.write(tmp_path / "CALL_LEDGER.json", {"calls": [{"ordinal": 64, "receipt": name}]})
    monkeypatch.setattr(resume, "ROOT", tmp_path)
    monkeypatch.setattr(resume, "effective_script_review",
        lambda n: (deepcopy(ctx), deepcopy(receipt), deepcopy(review)))
    monkeypatch.setattr(resume, "ensure_latest_draft", lambda n: deepcopy(source))
    ref = leaf(ctx, "script.beats.0.before")
    evidence = [{**ref, "finding": "离线审查决策门禁，不是实际作品批准"}]
    decision = resume.script_decision(5, True, evidence)
    assert decision["approved_for_direction"] is True
    assert decision["media_approval"] is False
    assert decision["review_receipt_sha256"] == control.sha_file(tmp_path / name)
    assert decision["script_source_sha256"] == control.digest(source["output"])
    assert "production_ready" not in decision and "quality_passed" not in decision


def test_untimed_source_with_eleven_actions_does_not_inherit_six_second_quality_gate(monkeypatch):
    from tests.test_creative_linear_script_v3 import raw as untimed_fixture
    from tests.test_creative_linear_script_v2 import context as source_context, action
    from src.content_factory.creative_workflow_contract import validate_script, _physical_step_count

    c = source_context()
    raw = untimed_fixture()
    raw["beats"][0]["steps"] = [action(
        "方澄起身，走到柜旁，打开柜门，拿起纸袋，关上柜门，转身，走到桌边，"
        "放下纸袋，拿起清单，拨齐清单，压平边角。")]
    before = deepcopy((c, raw))
    monkeypatch.setattr(resume, "original", lambda: deepcopy(c))
    derived = resume.derive(raw)
    proof = linear.preliminary_timing_estimates(raw)
    assert (c, raw) == before
    assert derived["beats"][0]["before"] == raw["beats"][0]["steps"][0]["text"]
    assert _physical_step_count(derived["beats"][0]["before"]) == 11
    assert derived["beats"][0]["duration_seconds"] == 6
    assert proof["actual_windows_verified"] is False
    assert proof["action_timing_verified"] is False
    assert proof["semantic_approval"] is False and proof["production_ready"] is False
    assert proof["by_beat_id"][raw["beats"][0]["id"]]["action_duration_seconds"] is None
    assert proof["required_next_stage"] == (
        "local_model_actual_schedule_then_deterministic_compile_and_full_joint_review")
    # This demonstrates the removed false rejection, rather than approving the
    # action density or claiming the eleven operations can play in six seconds.
    with pytest.raises(CreativeContractError, match="11 个连续物理步骤"):
        validate_script(deepcopy(derived), c["script"]["selected_candidate_id"], "", "original")
    assert (c, raw) == before
