"""Explicit synthetic contract fixtures; no production or creative-quality verdict."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_goal_source_contract_v2 as goal


CATALOGS = {"source_ids": ["P1"], "legal_ids": ["LAW1"],
            "user_constraint_ids": ["UC1", "UG1"]}


def native_goal():
    profile = {"gender_presentation": "男性", "age_presentation": "成年",
               "appearance": "合成夹具中的短发", "wardrobe": "合成夹具中的衬衫"}
    return {
        "contract_version": goal.VERSION,
        "claims": [
            {"id": "U1", "kind": "user_constraint", "text": "完整原生新稿。",
             "origin_ids": ["UC1"], "basis_claim_refs": []},
            {"id": "U2", "kind": "user_audience_goal", "text": "让观众理解人物处境。",
             "origin_ids": ["UG1"], "basis_claim_refs": []},
            {"id": "S1", "kind": "platform_metadata", "text": "模拟平台议题标签，不是真实采集。",
             "origin_ids": ["P1"], "basis_claim_refs": []},
            {"id": "L1", "kind": "verified_legal", "text": "模拟已核实条件，非实际法律意见。",
             "origin_ids": ["LAW1"], "basis_claim_refs": []},
            {"id": "C1", "kind": "creative_choice", "text": "虚构员工提出申请，对手明确拒收。",
             "origin_ids": [], "basis_claim_refs": ["U1", "U2", "S1", "L1"]},
            {"id": "I1", "kind": "inference", "text": "推断观众可能关心，但未获得直接观众证据。",
             "origin_ids": [], "basis_claim_refs": ["S1"]},
        ],
        "whole_plan": {
            "premise": "合成场景只用于合同测试，不是本次采用的故事。",
            "audience_path": {"starting_feeling": "疑问", "target_shift": "理解坚持",
                              "emotional_landing": "不再误以为问题已解决", "claim_refs": ["U2"]},
            "characters": [
                {"id": actor, "name": name, "role": role, "profile": deepcopy(profile),
                 "want": want, "pressure": "各自的处境", "initial_state": {
                     "scene_id": "room", "posture": "坐着", "location": position}}
                for actor, name, role, want, position in (
                    ("worker", "员工", "当事人", "拿到明确答复", "桌子左侧"),
                    ("hr", "负责人", "对手", "按自己的口径结束谈话", "桌子右侧"))],
            "scenes": [{"id": "room", "description": "合成小会议室", "appearance": "桌椅"}],
            "props": [
                {"id": "book", "description": "员工的记录本", "initial_state": "合拢，由员工拿着",
                 "holder_character_id": "worker", "owner_character_id": "worker",
                 "support": {"entity_type": "actor", "entity_id": "worker"}, "orientation": None},
                {"id": "paper", "description": "一张空白纸", "initial_state": "桌面上，没有人持有",
                 "holder_character_id": None, "owner_character_id": None,
                 "support": {"entity_type": "scene", "entity_id": "room"}, "orientation": None}],
            "beats": [
                {"id": "B1", "scene_id": "room", "actor_id": "worker", "goal": "得到解释",
                 "resistance": "负责人要求等待系统更新", "stimulus": "对方回避解释",
                 "response": "员工失望后追问", "strategy": {
                     "before": "带着疑问来", "after": "要求当面解释", "effect": "establishes"},
                 "visible_change": "负责人不能再只谈系统", "claim_refs": ["C1"]},
                {"id": "B2", "scene_id": "room", "actor_id": "worker", "goal": "获得明确答复",
                 "resistance": "负责人拒绝当场说明", "stimulus": "对方再次推迟",
                 "response": "员工转为书面申请", "strategy": {
                     "before": "追问口头解释", "after": "提出书面申请", "effect": "changes"},
                 "visible_change": "负责人明确拒收，员工保留申请", "claim_refs": ["C1"]}],
            "ending": {"attempt_result": "申请没有被接收", "visible_consequence": "对方拒收后，员工保留纸张",
                       "emotional_landing": "失望但不再无限等候口头承诺", "open_legal_question": "真实权利义务与争议结果尚未确定",
                       "evidence_beat_ids": ["B2"], "claim_refs": ["C1"]},
        },
    }


def validate(document):
    return goal.validate_goal_document(document, **CATALOGS)


def rejected(document, code):
    with pytest.raises(goal.GoalContractError) as error:
        validate(document)
    assert error.value.code == code
    return error.value


@pytest.mark.parametrize("result", ["对方明确拒收，员工保留申请", "对方接下申请，尚未作法律结论"])
def test_open_legal_result_can_have_a_local_observable_result(result):
    document = native_goal()
    document["whole_plan"]["ending"]["visible_consequence"] = result
    accepted = validate(document)
    assert accepted["whole_plan"]["ending"]["open_legal_question"]
    assert not list(Draft202012Validator(goal.build_goal_request_schema()).iter_errors(accepted))
    # Acceptance only concerns the native contract; the prose is not a gold label.


def test_validation_returns_independent_deep_copy_without_repairing_prose():
    original = native_goal()
    snapshot = deepcopy(original)
    result = validate(original)
    result["whole_plan"]["beats"][0]["response"] = "changed"
    assert original == snapshot


@pytest.mark.parametrize("mutate", [
    lambda doc: doc.update(contract_version="old_brief"),
    lambda doc: doc["whole_plan"]["beats"][0].update(seconds=10),
    lambda doc: doc["whole_plan"]["ending"].update(visible_consequence="   "),
    lambda doc: doc["claims"][0].update(origin_ids=[]),
    lambda doc: doc["claims"][4].update(origin_ids=["LAW1"]),
])
def test_exact_schema_rejects_type_version_incomplete_and_authority_promotion(mutate):
    document = native_goal()
    mutate(document)
    assert list(Draft202012Validator(goal.build_goal_request_schema()).iter_errors(document))
    rejected(document, "GOAL_SCHEMA_INVALID")


def test_wrong_authority_origin_is_rejected_not_reinterpreted_as_a_creative_fact():
    document = native_goal()
    document["claims"][4].update(
        kind="verified_legal", origin_ids=["P1"], basis_claim_refs=[],
        text="合成旧 f1：本故事只展示核对工资与争取书面结算明细的互动过程。")
    # The syntax is valid but metadata cannot supply a verified legal origin.
    assert not list(Draft202012Validator(goal.build_goal_request_schema()).iter_errors(document))
    rejected(document, "GOAL_ORIGIN_CLASS_MISMATCH")


def test_semantically_false_classification_requires_separate_goal_review():
    document = native_goal()
    document["claims"][2]["text"] = (
        "合成旧 f2：仅以负责人看工资条的停滞作为可见留白；故意错标成平台元数据。")
    # P1 is a real catalog ID within this fixture. Natural-language meaning is
    # deliberately NOT inferred by this structural gate or a keyword blacklist.
    assert validate(document)["claims"][2]["text"] == document["claims"][2]["text"]


@pytest.mark.parametrize("catalogs", [
    {**CATALOGS, "source_ids": "P1"},
    {**CATALOGS, "source_ids": ["P1", "P1"]},
    {**CATALOGS, "legal_ids": ["P1"]},
])
def test_source_catalog_integrity_prevents_ambiguous_authority(catalogs):
    with pytest.raises(goal.GoalContractError, match="GOAL_SOURCE_CATALOG_INVALID"):
        goal.validate_goal_document(native_goal(), **catalogs)


def test_omitted_user_requirement_is_not_a_plan_pass():
    document = native_goal()
    document["claims"][0]["origin_ids"] = ["UG1"]
    rejected(document, "GOAL_USER_REQUIREMENT_UNCOVERED")


def test_duplicate_native_ids_cannot_hide_uncovered_rows():
    for section in ("claims", "characters", "beats"):
        document = native_goal()
        rows = document["claims"] if section == "claims" else document["whole_plan"][section]
        rows[1]["id"] = rows[0]["id"]
        rejected(document, "GOAL_DUPLICATE_ID")


def test_real_unicode_external_tag_id_is_preserved_not_rewritten_to_ascii():
    document = native_goal()
    document["claims"][2]["origin_ids"] = ["tag:劳动争议"]
    accepted = goal.validate_goal_document(document, **{**CATALOGS, "source_ids": ["tag:劳动争议"]})
    assert accepted["claims"][2]["origin_ids"] == ["tag:劳动争议"]


def test_inference_and_choice_provenance_cannot_be_circular():
    document = native_goal()
    document["claims"][4]["basis_claim_refs"] = ["I1"]
    document["claims"][5]["basis_claim_refs"] = ["C1"]
    rejected(document, "GOAL_REFERENCE_CYCLE")


def test_unknown_choice_basis_is_not_silently_dropped():
    document = native_goal()
    document["claims"][4]["basis_claim_refs"] = ["unknown"]
    rejected(document, "GOAL_REFERENCE_UNKNOWN")


def test_actor_scene_prop_namespace_collision_is_not_guessable():
    document = native_goal()
    document["whole_plan"]["props"][0]["id"] = "worker"
    rejected(document, "GOAL_ENTITY_ID_COLLISION")


@pytest.mark.parametrize("mutation", ["scene", "holder", "owner", "support"])
def test_initial_entities_must_have_declared_identity(mutation):
    document = native_goal()
    if mutation == "scene":
        document["whole_plan"]["characters"][0]["initial_state"]["scene_id"] = "unknown"
    elif mutation in ("holder", "owner"):
        document["whole_plan"]["props"][0][mutation + "_character_id"] = "unknown"
    else:
        document["whole_plan"]["props"][0]["support"]["entity_id"] = "unknown"
    rejected(document, "GOAL_REFERENCE_UNKNOWN")


def test_known_holder_and_known_table_support_conflict_is_rejected():
    document = native_goal()
    document["whole_plan"]["props"][0]["support"] = {"entity_type": "scene", "entity_id": "room"}
    rejected(document, "GOAL_INITIAL_HOLDER_SUPPORT_CONFLICT")


def test_owner_can_differ_from_actual_holder_and_unknown_support_remains_unknown():
    document = native_goal()
    prop = document["whole_plan"]["props"][0]
    prop.update(owner_character_id="hr", support=None)
    accepted = validate(document)
    assert accepted["whole_plan"]["props"][0]["holder_character_id"] == "worker"
    assert accepted["whole_plan"]["props"][0]["owner_character_id"] == "hr"
    assert accepted["whole_plan"]["props"][0]["support"] is None


def test_prop_containment_cycle_is_rejected():
    document = native_goal()
    props = document["whole_plan"]["props"]
    props[0].update(holder_character_id=None, support={"entity_type": "prop", "entity_id": "paper"})
    props[1]["support"] = {"entity_type": "prop", "entity_id": "book"}
    rejected(document, "GOAL_REFERENCE_CYCLE")


def test_procedural_metadata_cannot_replace_all_declared_dramatic_choices():
    document = native_goal()
    document["whole_plan"]["beats"][0]["claim_refs"] = ["S1", "L1"]
    rejected(document, "GOAL_DRAMATIC_CHOICE_UNTRACED")


def test_repeated_tactic_is_a_contract_diagnostic_not_an_automatic_plot_rewrite():
    document = native_goal()
    document["whole_plan"]["beats"][1]["strategy"]["effect"] = "maintains"
    error = rejected(document, "GOAL_STRATEGY_SHIFT_MISSING")
    assert "strategy change" in error.detail
    assert document["whole_plan"]["beats"][1]["strategy"]["effect"] == "maintains"


def test_ending_must_trace_the_actual_final_beat():
    document = native_goal()
    document["whole_plan"]["ending"]["evidence_beat_ids"] = ["B1"]
    rejected(document, "GOAL_ENDING_UNTRACED")


def test_user_goal_mapping_contains_no_generated_story_or_forced_legal_outcome():
    document = goal.build_user_goal_contract()
    assert len(document["constraints"]) == 4
    assert len(document["audience_goals"]) == 4
    assert all(row["source_quote"] for row in document["constraints"] + document["audience_goals"])
    assert "whole_plan" not in document
    assert "planning_rules" in document
    document["constraints"][0]["text"] = "mutated"
    assert goal.build_user_goal_contract()["constraints"][0]["text"] != "mutated"
