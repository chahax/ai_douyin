"""Offline contract/routing fixtures, never submitted production reviews."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_full_review_contract_v2 as review
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as prior
from tests.test_creative_fresh_legal_text_pipeline_v1 import (
    inputs, theme_for, raw_script, plan_for_fresh, review_for,
)


def fixture(native=None):
    """Explicit model-judgement test input; its verdict is not a quality gold."""
    case = inputs()
    theme = theme_for(case["packet"])
    brief = prior.compile_brief(theme, case["packet"], case["legal_context"],
                                case["production_preferences"], case["source_binding_sha256"])
    script = prior.contract.compile_script(native or raw_script(), brief)
    plan = plan_for_fresh(brief)
    legacy = review_for(script, brief, plan, case["legal_context"])
    value = deepcopy(legacy)
    for table, key in review._COVERAGE_KEYS.items():
        value[table] = {row[key]: {k: deepcopy(v) for k, v in row.items() if k != key}
                        for row in legacy[table]}
    entries = prior.contract.evidence_catalog(script)
    refs = list(entries)
    for ref, row in value["dialogue_checks"].items():
        row["source_refs"] = [ref]
        row.update(turn_function="request", purpose="模拟话轮目的，仅测试合同字段。",
                   stimulus_ref=None, reaction_refs=[], emotional_change=None)
    value["action_checks"] = {}
    first = {}
    for ref, entry in entries.items():
        if entry["kind"] != "action":
            continue
        subjects = ["worker", "hr", "slip"]
        for entity in subjects:
            first.setdefault(entity, ref)
        value["action_checks"][ref] = {
            "status": "pass", "source_refs": [ref], "reason": "模拟逐动作审查，仅验证引用和路由。",
            "required_revision": "", "subjects": subjects, "preconditions": [], "state_changes": [],
        }
    for identifier, row in value["initial_checks"].items():
        entity = identifier.split(":", 1)[1]
        if entity in first:
            row["source_refs"] = [first[entity]]
    for identifier, row in value["observed_prop_initial"].items():
        if identifier in first:
            row["source_refs"] = [first[identifier]]
    value["goal_checks"] = {key: {
        "status": "pass", "source_refs": [refs[0]], "reason": "合成目标判断，仅测试合同，非质量金标。",
        "required_revision": "", "evidence": [{"source_ref": refs[0], "quote": entries[refs[0]]["quote"]}],
    } for key in review.GOAL_FIELDS}
    value["schema"] = review.VERSION
    value["goal_contract_sha256"] = None
    return script, brief, plan, case["legal_context"], value


def validate(case, **kwargs):
    script, brief, plan, legal, value = case
    return review.validate_full_review(value, script, brief, plan, legal, **kwargs)


def physical_fixture():
    native = {"title": "离线状态反例", "premise": "合成动作序列，仅检查状态引用。", "beats": [
        {"id": "B1", "trigger": "准备文件", "event": "文件夹合上", "steps": [
            {"kind": "action", "speaker": "", "text": "阿宁坐在椅子上，把文件夹合上。"},
            {"kind": "dialogue", "speaker": "worker", "text": "请把这笔工资说清楚。"}]},
        {"id": "B2", "trigger": "需要查看文件", "event": "陈姐要合上文件夹", "steps": [
            {"kind": "action", "speaker": "", "text": "陈姐伸手要把文件夹合上。"},
            {"kind": "dialogue", "speaker": "hr", "text": "这份文件先放在桌上。"}]},
        {"id": "B3", "trigger": "交流暂停", "event": "员工起身", "steps": [
            {"kind": "action", "speaker": "", "text": "阿宁从椅子上站起，把文件夹拿到手里。"},
            {"kind": "dialogue", "speaker": "worker", "text": "我会等你的说明。"}]},
    ]}
    case = fixture(native)
    value = case[-1]
    value["action_checks"]["E0001"]["state_changes"] = [{"entity_id": "slip", "state_key": "open",
        "before": True, "after": False, "quote": "把文件夹合上"}]
    return case


def test_keyed_schema_and_validator_share_exact_dialogue_coverage():
    script, brief, plan, legal, value = fixture()
    schema = review.build_review_schema(script, brief, plan, legal)
    expected = review.coverage_specification(script, brief, plan)["dialogue_checks"]
    assert schema["properties"]["dialogue_checks"]["required"] == expected
    assert schema["properties"]["dialogue_checks"]["additionalProperties"] is False
    Draft202012Validator(schema).validate(value)
    result = validate((script, brief, plan, legal, value))
    assert result["valid"] and result["accepted"]
    assert not result["creative_quality_passed"] and not result["human_quality_approved"]


@pytest.mark.parametrize("replacement", [[], {}])
def test_empty_dialogue_rows_rejected_before_semantic_decision(replacement):
    case = fixture()
    case[-1]["dialogue_checks"] = replacement
    result = validate(case)
    assert not result["valid"] and result["findings"][0]["code"] == "DIALOGUE_COVERAGE_EMPTY"


def test_real_530_empty_dialogue_response_is_rejected_without_repairing_evidence():
    root = Path("data/production_trials/m31_flash_script_test_20261013/round_01/call_evidence/call_530")
    request = json.loads((root / "request_body.raw").read_text(encoding="utf-8"))
    payload = json.loads(request["messages"][1]["content"])
    raw = json.loads((root / "response_body.raw").read_text(encoding="utf-8"))
    document = json.loads(raw["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    before = prior.digest(document)
    result = review.validate_full_review(document, payload["full_current_script"], payload["brief"],
                                         payload["full_scene_plan"], payload["verified_legal_context"])
    assert result["findings"][0]["code"] == "DIALOGUE_COVERAGE_EMPTY"
    assert prior.digest(document) == before and len(payload["evidence_catalog"]) == 33


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_dialogue_coverage_missing_or_extra_key_fails_outbound_and_local(change):
    case = fixture()
    rows = case[-1]["dialogue_checks"]
    if change == "missing":
        rows.pop(next(iter(rows)))
    else:
        rows["E9999"] = deepcopy(next(iter(rows.values())))
    with pytest.raises(ValidationError):
        Draft202012Validator(review.build_review_schema(*case[:4])).validate(case[-1])
    assert not validate(case)["valid"]


@pytest.mark.parametrize("field,value", [("kind", "action"), ("speaker", "hr")])
def test_literal_kind_and_speaker_bound_per_reference(field, value):
    case = fixture()
    case[-1]["literal_events"]["E0001"][field] = value
    assert not validate(case)["valid"]


@pytest.mark.parametrize("field", ["script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256"])
def test_each_source_hash_is_bound(field):
    case = fixture()
    case[-1][field] = "0" * 64
    assert not validate(case)["valid"]


def test_goal_contract_is_opaque_but_source_bound():
    case = fixture()
    goal = {"user_goal": {"feeling": "被理解后看见选择"}, "native_plan": {"text": "完整原生创作选择"}}
    assert not validate(case, goal_contract=goal)["valid"]
    case[-1]["goal_contract_sha256"] = prior.digest(goal)
    assert validate(case, goal_contract=goal)["valid"]


@pytest.mark.parametrize("field,value", [("stimulus_ref", "E0004"), ("reaction_refs", ["E0001"])])
def test_dialogue_stimulus_and_reaction_follow_source_order(field, value):
    case = fixture()
    case[-1]["dialogue_checks"]["E0002"][field] = value
    assert not validate(case)["valid"]


def test_dialogue_cannot_pass_without_checking_its_own_step():
    case = fixture()
    case[-1]["dialogue_checks"]["E0002"]["source_refs"] = ["E0001"]
    assert "own actual dialogue" in validate(case)["findings"][0]["reason"]


def test_blank_dialogue_purpose_is_not_meaningful():
    case = fixture()
    case[-1]["dialogue_checks"]["E0002"]["purpose"] = "   "
    assert not validate(case)["valid"]


def test_goal_pass_needs_actual_unchanged_quote():
    case = fixture()
    case[-1]["goal_checks"]["local_consequence"]["evidence"][0]["quote"] = "模型补写的结尾"
    assert "unchanged" in validate(case)["findings"][0]["reason"]


def test_goal_pass_cannot_be_an_empty_count():
    case = fixture()
    case[-1]["goal_checks"]["local_consequence"]["evidence"] = []
    assert not validate(case)["valid"]


def test_explicit_local_consequence_failure_enters_whole_revision():
    case = fixture()
    row = case[-1]["goal_checks"]["local_consequence"]
    row.update(status="fail", required_revision="完整新稿须兑现本次交锋的选择或回应，不替争议下结论。")
    result = validate(case)
    assert result["valid"] and not result["accepted"] and result["status"] == "needs_whole_revision"
    assert result["findings"][0]["table"] == "goal_checks"


def test_unknown_goal_halts_instead_of_authorizing_content_revision():
    case = fixture()
    case[-1]["goal_checks"]["emotional_change"]["status"] = "unknown"
    result = validate(case)
    assert result["valid"] and result["status"] == "halt_review_uncertain"
    assert not result["findings"] and result["uncertainties"]


def test_closed_notebook_cannot_pass_a_later_open_precondition():
    case = physical_fixture()
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "expected_value": True, "actual_value": False, "established_by": "E0001", "quote": "把文件夹合上"}]
    assert "unsatisfied" in validate(case)["findings"][0]["reason"]


def test_closed_notebook_cannot_be_reported_open_without_restoration():
    case = physical_fixture()
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "expected_value": True, "actual_value": True, "established_by": "E0001", "quote": "把文件夹合上"}]
    assert "reported earlier action state" in validate(case)["findings"][0]["reason"]


def test_latest_state_cannot_be_bypassed_by_initial_witness():
    case = physical_fixture()
    case[-1]["action_checks"]["E0001"]["state_changes"] = [{"entity_id": "slip", "state_key": "holder_character_id",
        "before": None, "after": "hr", "quote": "把文件夹合上"}]
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{"entity_id": "slip", "state_key": "holder_character_id",
        "expected_value": None, "actual_value": None, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert "latest reported state" in validate(case)["findings"][0]["reason"]


def test_standing_character_cannot_have_a_seated_before_state_without_sit():
    case = physical_fixture()
    case[1]["initial_state"]["character_states"][0]["posture"] = "站着"
    case[-1]["brief_sha256"] = prior.digest(case[1])
    case[-1]["action_checks"]["E0005"]["state_changes"] = [{"entity_id": "worker", "state_key": "posture",
        "before": "坐着", "after": "站着", "quote": "从椅子上站起"}]
    assert "last established before state" in validate(case)["findings"][0]["reason"]


def test_table_object_cannot_be_in_actor_hand_without_take_transition():
    case = physical_fixture()
    case[-1]["action_checks"]["E0005"]["preconditions"] = [{"entity_id": "slip", "state_key": "holder_character_id",
        "expected_value": "worker", "actual_value": None, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert "unsatisfied" in validate(case)["findings"][0]["reason"]


def test_future_action_cannot_establish_earlier_precondition():
    case = physical_fixture()
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "expected_value": True, "actual_value": True, "established_by": "E0005", "quote": "拿到手里"}]
    assert not validate(case)["valid"]


def test_later_action_cannot_repair_passing_initial_state():
    case = physical_fixture()
    case[-1]["initial_checks"]["character:worker"]["source_refs"] = ["E0001", "E0005"]
    assert "later actions cannot repair" in validate(case)["findings"][0]["reason"]


def test_state_trace_order_comes_from_script_not_model_object_order():
    case = physical_fixture()
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "expected_value": False, "actual_value": False, "established_by": "E0001", "quote": "把文件夹合上"}]
    before = validate(case)
    case[-1]["action_checks"] = dict(reversed(list(case[-1]["action_checks"].items())))
    assert validate(case) == before and before["valid"]


def test_rejected_action_assertion_does_not_establish_later_state():
    case = physical_fixture()
    case[-1]["action_checks"]["E0001"].update(status="unknown")
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "expected_value": False, "actual_value": False, "established_by": "E0001", "quote": "把文件夹合上"}]
    assert not validate(case)["valid"]


def test_validation_never_changes_native_documents():
    case = fixture()
    snapshots = [prior.digest(value) for value in case]
    assert validate(case)["valid"]
    assert [prior.digest(value) for value in case] == snapshots


def test_routine_workplace_word_is_not_a_banned_token_rule():
    case = fixture()
    case[-1]["dialogue_checks"]["E0001"]["purpose"] = "核对工资并索取具体说明，不按词表判错。"
    assert validate(case)["valid"]


def test_unknown_action_stops_without_becoming_a_revision_failure():
    case = fixture()
    case[-1]["action_checks"]["E0004"]["status"] = "unknown"
    result = validate(case)
    assert result["valid"] and result["status"] == "halt_review_uncertain"
    assert not result["findings"] and result["uncertainties"][0]["table"] == "action_checks"


@pytest.mark.parametrize("key,value", [("holder_character_id", "third_person"), ("open", 1), ("posture", True)])
def test_state_values_are_typed_and_actor_identity_is_closed(key, value):
    case = physical_fixture()
    entity = "worker" if key == "posture" else "slip"
    case[-1]["action_checks"]["E0005"]["state_changes"] = [{"entity_id": entity, "state_key": key,
        "before": value, "after": value, "quote": "拿到手里"}]
    assert not validate(case)["valid"]


def test_later_prop_observation_cannot_patch_first_state():
    case = physical_fixture()
    case[-1]["observed_prop_initial"]["slip"]["source_refs"] = ["E0001", "E0005"]
    assert "later actions cannot repair" in validate(case)["findings"][0]["reason"]


def test_compact_schema_preserves_coverage_and_shares_standard_definitions():
    case = fixture()
    schema = review.build_review_schema(*case[:4])
    assert "$defs" in schema
    assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))) < 20000
    assert set(schema["properties"]["literal_events"]["required"]) == set(case[-1]["literal_events"])
    Draft202012Validator(schema).validate(case[-1])
