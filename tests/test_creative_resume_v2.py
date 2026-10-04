"""Story-first production controls tested offline; no new root prepare or SDK calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts import run_creative_resume_v2 as resume
from scripts import creative_resume_dispatch_v1 as control
from scripts import creative_review_wire_v9 as review_wire
from scripts import creative_compact_review_transport_v8 as compact
from scripts import creative_joint_source_binding_v9 as joint
from scripts import creative_linear_script_v2 as linear
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_run_creative_resume_v1 import full_physical_case
from tests.test_step_index_physical_adapter_v4 import rebind
from tests.test_creative_joint_source_binding_v9 import review_for
from tests.test_creative_story_direction_contract_v1 import direction as story_fixture


def capture_dispatch(monkeypatch):
    captured = []
    def dispatch(label, wire, validator):
        captured.append({"label": label, "wire": deepcopy(wire), "validator": validator})
        return {"status": "offline_request_captured", "label": label}
    monkeypatch.setattr(resume, "runtime", lambda: SimpleNamespace(dispatch=dispatch))
    return captured


def plan_receipt():
    return {"ordinal": 53, "label": "story_plan_r1", "status": "contract_valid",
            "output": story_fixture()}


def test_story_plan_actual_wire_keeps_complete_R01_and_excludes_failed_templates(monkeypatch):
    original = resume.original()
    before = deepcopy(original)
    captured = capture_dispatch(monkeypatch)
    resume.story_plan(1, feedback=[{"id": "VERIFIED_F01", "evidence": "先明确关系选择与后果", "verified": True}])
    wire = captured[0]["wire"]
    payload = json.loads(wire["messages"][1]["content"])
    assert payload["context"]["creative_brief"] == original["creative_brief"]
    assert payload["context"]["static_visual_manifest"] == original["static_visual_manifest"]
    assert payload["context"]["reference_pack"] == original["reference_pack"]
    assert any(row["id"] == "R01" and row["text"] for row in payload["context"]["reference_pack"])
    assert not {"script", "raw_linear_script", "previous_script"} & set(payload["context"])
    assert wire["input_provenance"]["full_reference_pack_in_messages"] is True
    assert wire["input_provenance"]["old_failed_full_script_used_as_template"] is False
    assert wire["model"] == "MiniMax-M3"
    assert captured[0]["label"] == "story_plan_r1"
    assert resume.original() == before


def test_fresh_draft_uses_adopted_story_plan_not_failed_call51(monkeypatch):
    old = {"title": "FAILED_CALL51_TEMPLATE_SENTINEL",
           "beats": [{"steps": [{"kind": "action", "text": "FAILED_CALL51_ACTION_CHAIN"}]}]}
    sequenced = []
    monkeypatch.setattr(resume, "previous_draft_for_revision", lambda n: sequenced.append(n) or deepcopy(old))
    plan = plan_receipt()
    monkeypatch.setattr(resume, "adopted_story_plan", lambda: deepcopy(plan))
    captured = capture_dispatch(monkeypatch)
    original = resume.original()
    resume.draft(2)
    payload = json.loads(captured[0]["wire"]["messages"][1]["content"])
    assert sequenced == [2]
    assert payload["previous_script"] == {}
    assert "script" not in payload["context"]
    assert payload["context"]["adopted_story_direction"] == plan["output"]
    assert payload["context"]["reference_pack"] == original["reference_pack"]
    assert payload["context"]["static_visual_manifest"] == original["static_visual_manifest"]
    serialized = json.dumps(captured[0]["wire"]["messages"], ensure_ascii=False)
    assert "FAILED_CALL51_TEMPLATE_SENTINEL" not in serialized
    assert "FAILED_CALL51_ACTION_CHAIN" not in serialized
    assert "参考全文与完整旧稿都在输入中" not in serialized
    assert captured[0]["wire"]["input_provenance"]["story_plan_sha256"] == control.digest(plan["output"])
    assert captured[0]["wire"]["input_provenance"]["story_plan_ordinal"] == 53


def test_missing_story_plan_blocks_before_runtime_or_dispatch(monkeypatch):
    monkeypatch.setattr(resume, "previous_draft_for_revision", lambda n: {})
    monkeypatch.setattr(resume, "records", lambda: [])
    constructed = []
    def forbidden_runtime():
        constructed.append(True)
        raise AssertionError("No runtime or SDK should be constructed")
    monkeypatch.setattr(resume, "runtime", forbidden_runtime)
    with pytest.raises(RuntimeError, match="stage missing"):
        resume.draft(2)
    assert constructed == []


def test_stale_story_plan_decision_blocks_before_dispatch(tmp_path, monkeypatch):
    plan = plan_receipt()
    monkeypatch.setattr(resume, "ROOT", tmp_path)
    monkeypatch.setattr(resume, "latest", lambda prefix: deepcopy(plan))
    monkeypatch.setattr(resume, "previous_draft_for_revision", lambda n: {})
    control.write(tmp_path / "STORY_PLAN_DECISION_call53.json",
                  {"approved_for_complete_script": True, "plan_sha256": "stale"})
    constructed = []
    monkeypatch.setattr(resume, "runtime", lambda: constructed.append(True))
    with pytest.raises(RuntimeError, match="stale"):
        resume.draft(2)
    assert constructed == []


def test_story_plan_approval_requires_actual_scalar_leaf_and_keeps_identity(tmp_path, monkeypatch):
    plan = plan_receipt()
    monkeypatch.setattr(resume, "ROOT", tmp_path)
    monkeypatch.setattr(resume, "latest", lambda prefix: deepcopy(plan))
    bad = [{"path": "causal_events", "quote": "[]", "finding": "不能引整个数组"}]
    with pytest.raises(RuntimeError, match="actual leaf"):
        resume.story_plan_decision(bad)
    assert not list(tmp_path.iterdir())
    text = plan["output"]["causal_events"][0]["visible_event"]
    evidence = [{"path": "causal_events.0.visible_event", "quote": text,
                 "finding": "离线门禁测试：引用实际方向事件，不构成真实创作批准"}]
    decision = resume.story_plan_decision(evidence)
    assert decision["plan_sha256"] == control.digest(plan["output"])
    assert decision["media_approval"] is False
    assert resume.adopted_story_plan() == plan


@pytest.fixture
def compiled_case(tmp_path, monkeypatch):
    context, direction, locals_ = full_physical_case()
    context["adopted_story_direction"] = story_fixture()
    rebind(context, direction, locals_)
    monkeypatch.setattr(resume, "ROOT", tmp_path)
    monkeypatch.setattr(resume, "direction_source", lambda n, revision: (deepcopy(context), deepcopy(direction)))
    monkeypatch.setattr(resume, "local_sources", lambda n, revision, count: deepcopy(locals_[:count]))
    monkeypatch.setattr(resume, "derive", lambda raw: linear.accept_linear_script(
        raw, raw, character_names=["甲", "乙"]))
    final_context, compiled = resume.final_context(2, 1)
    return context, direction, locals_, final_context, compiled


def test_actual_final_context_reaches_v9_preflight_with_adopted_plan(compiled_case):
    original, _, _, ctx, compiled = compiled_case
    before = deepcopy(ctx)
    proof = joint.preflight(ctx)
    assert ctx == before
    assert ctx["adopted_story_direction"] == original["adopted_story_direction"]
    assert ctx["raw_linear_script"] == compiled["source_raw_linear_script"]
    assert proof["physical_projection_recomputed"] is True
    assert proof["source_identity_checked"] is True
    assert proof["semantic_approval"] is False
    assert [(m["narrative_beat_id"], m["execution_shot_id"], m["storyboard_id"]) for m in proof["mapping"]] == [
        ("B1", "S1", "SH01"), ("B1", "S2", "SH02")]


def test_joint_tool_messages_keep_full_inputs_and_complete_review_gate(compiled_case):
    ctx = compiled_case[3]
    before = deepcopy(ctx)
    messages = review_wire.joint_messages(ctx, resume.joint_review_messages(ctx))
    assert json.loads(messages[1]["content"]) == ctx == before
    assert json.loads(messages[1]["content"])["reference_pack"] == ctx["reference_pack"]
    for required in ("raw_linear_script", "adopted_story_direction", "execution_bindings", "state_plan"):
        assert required in json.loads(messages[1]["content"])
    assert "coverage每行是七列普通数组" in messages[0]["content"]
    assert "timing_source_leaves" in messages[0]["content"]
    raw = compact.encode_review(review_for(ctx), ctx)
    Draft202012Validator(review_wire.schema(ctx)).validate(raw)
    effective = compact.expand_review(raw, ctx)
    assert joint.validate_joint_review(effective, ctx)["review_source_binding_checked"] is True


def test_render_shows_program_tail_and_multi_group_source_once(compiled_case):
    _, _, _, ctx, compiled = compiled_case
    before = deepcopy((ctx, compiled))
    text = resume.render_production_plan(ctx, compiled)
    assert (ctx, compiled) == before
    tail_count = sum(row["unused_tail_seconds"] > 1e-8 for row in compiled["schedule_report"]["beats"])
    assert tail_count > 0
    assert text.count("程序尾保持：") == tail_count
    assert text.count("不计作声明反应窗口") == tail_count
    source_count = {}
    for row in compiled["source_trace"]:
        source_count[row["source_ref"]] = source_count.get(row["source_ref"], 0) + 1
    assert any(count > 1 for count in source_count.values())
    assert text.count("同一原步骤续行（不重演动作）") == sum(count - 1 for count in source_count.values())
    for beat in ctx["raw_linear_script"]["beats"]:
        for step in beat["steps"]:
            rendered = step["speaker"] + "：" + step["text"] if step["kind"] == "dialogue" else step["text"]
            assert text.count(rendered) == 1
    assert "awaiting_human_review" in text


def test_v9_schema_is_plain_v8_arrays_and_dict_coverage_is_rejected(compiled_case):
    ctx = compiled_case[3]
    schema = review_wire.schema(ctx)
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema"]["enum"] == [compact.VERSION]
    assert schema["properties"]["coverage"]["type"] == "array"
    assert schema["properties"]["coverage"]["items"]["type"] == "array"
    serialized = json.dumps(schema, ensure_ascii=False)
    for forbidden in ('"strict"', '"prefixItems"', '"if"', '"then"'):
        assert forbidden not in serialized
    raw = compact.encode_review(review_for(ctx), ctx)
    raw["coverage"][0] = {"id": raw["coverage"][0][0], "checks": {}}
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(raw)
    with pytest.raises(CreativeContractError, match="COMPACT_ROW_SHAPE_INVALID"):
        compact.expand_review(raw, ctx)


def test_schema_hash_is_stable_across_process_hash_seeds():
    code = (
        "import hashlib,json;"
        "from scripts.creative_review_wire_v9 import schema;"
        "c={'script':{'beats':[{'id':'B1'}]}};"
        "print(hashlib.sha256(json.dumps(schema(c),ensure_ascii=False,sort_keys=True,"
        "separators=(',',':')).encode('utf-8')).hexdigest())"
    )
    hashes = []
    for seed in ("1", "42", "77"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-c", code], cwd=resume.PROJECT,
                                env=env, capture_output=True, text=True, check=True, timeout=30)
        hashes.append(result.stdout.strip())
    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64


def test_v2_runtime_inherits_actual_52_and_531221_without_prepare_or_paid(tmp_path, monkeypatch):
    root = tmp_path / "not_prepared"
    monkeypatch.setattr(resume, "ROOT", root)
    before = control.sha_file(resume.previous_run.ROOT / "CALL_LEDGER.json")
    runtime = resume.runtime()
    assert runtime.inherited["calls_started"] == 52
    assert runtime.inherited["reported_tokens"] == 531221
    assert runtime.inherited["legacy_max_total_tokens"] == 500000
    assert runtime.inherited["prior_aggregate_limit"] is None
    assert not root.exists()
    assert not runtime.ledger.exists()
    runtime.inherited_guard()
    assert control.sha_file(resume.previous_run.ROOT / "CALL_LEDGER.json") == before
    assert not root.exists()


def test_v2_runtime_parent_evidence_hash_guard_blocks_without_sdk_or_new_root(tmp_path, monkeypatch):
    root = tmp_path / "not_prepared"
    monkeypatch.setattr(resume, "ROOT", root)
    runtime = resume.runtime()
    evidence = (resume.previous_run.ROOT / "SOURCE_DIAGNOSTIC_call51.json").resolve()
    original_hash = control.sha_file
    monkeypatch.setattr(control, "sha_file", lambda p: "0" * 64 if Path(p).resolve() == evidence else original_hash(p))
    with pytest.raises(RuntimeError, match="prior frozen evidence changed"):
        runtime.inherited_guard()
    assert not root.exists()


def test_records_merge_parent_history_without_rewriting_it(tmp_path, monkeypatch):
    history = [{"ordinal": 50, "label": "script_review_s1_r1", "status": "contract_rejected"},
               {"ordinal": 51, "label": "draft_s1", "status": "contract_valid"},
               {"ordinal": 52, "label": "script_review_s1_r2", "status": "interface_rejected"}]
    original = deepcopy(history)
    child = {"ordinal": 53, "label": "story_plan_r1", "status": "contract_valid"}
    root = tmp_path / "virtual"
    monkeypatch.setattr(resume, "ROOT", root)
    monkeypatch.setattr(resume.previous_run, "records", lambda: deepcopy(history))
    monkeypatch.setattr(resume, "runtime", lambda: SimpleNamespace(ledger=root / "CALL_LEDGER.json", check=lambda ledger: None))
    monkeypatch.setattr(control, "read", lambda p: {"calls": [{"receipt": "call_053_story_plan_r1.json"}]}
                        if Path(p).name == "CALL_LEDGER.json" else deepcopy(child))
    assert resume.records() == history + [child]
    assert history == original
    assert not root.exists()
