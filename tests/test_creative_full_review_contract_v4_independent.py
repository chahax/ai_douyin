"""Independent v4 contract counterexamples; no model or historical runtime."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_full_review_contract_v4 as review
from src.content_factory import creative_full_review_contract_v3 as frozen
from tests.test_creative_full_review_contract_v3 import fixture as prior_fixture, physical_fixture


def case_with_native_setup():
    case = physical_fixture()
    script, brief, plan, legal, document = case
    scene = brief["scenes"][0]["id"]
    setup = {"schema": "independent_synthetic_native_setup", "characters": {}, "props": {}}
    for row in brief["initial_state"]["character_states"]:
        value = {key: deepcopy(row.get(key)) for key in ("posture", "location")}
        value["scene_id"] = scene
        setup["characters"][row["id"]] = value
        row["expected_state"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for row in brief["initial_state"]["prop_states"]:
        value = {"presence": row.get("presence_at_start", "unknown"),
                 "holder_character_id": row["holder_character_id"],
                 "location": "长桌上，没人持有", "orientation": "纸面朝上", "open": True}
        setup["props"][row["id"]] = value
        row["expected_state"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    document["schema"] = review.VERSION
    document["brief_sha256"] = frozen.prior.digest(brief)
    document["opening_setup_sha256"] = frozen.prior.digest(setup)
    return case, setup


def validate(case, setup, **kwargs):
    return review.validate_full_review(case[-1], *case[:4], opening_setup=setup, **kwargs)


def condition(state_key, value, quote="没人持有", origin="initial:prop:slip"):
    return {"entity_id": "slip", "state_key": state_key, "expected_value": value,
            "actual_value": value, "established_by": origin, "quote": quote}


@pytest.mark.parametrize("label", ["statement", "告知事实并保留异议", "确认收到但拒绝承诺结果"])
def test_descriptive_turn_label_changes_no_acceptance_authority(label):
    case, setup = case_with_native_setup()
    baseline = validate(case, setup)
    next(iter(case[-1]["dialogue_checks"].values()))["turn_function"] = label
    changed = validate(case, setup)
    assert baseline["valid"] and baseline["accepted"]
    assert changed["valid"] and changed["accepted"] and changed["status"] == baseline["status"]
    assert changed["human_quality_approved"] is False and changed["creative_quality_passed"] is False


@pytest.mark.parametrize("label", ["", " \n\t", False, None, {"purpose": "statement"}])
def test_descriptive_turn_label_cannot_be_empty_or_another_type(label):
    case, setup = case_with_native_setup()
    next(iter(case[-1]["dialogue_checks"].values()))["turn_function"] = label
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("hash_field", ["script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256", "opening_setup_sha256"])
def test_all_native_and_law_identity_hashes_remain_closed(hash_field):
    case, setup = case_with_native_setup()
    case[-1][hash_field] = "f" * 64
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_actual_dialogue_identity_coverage_is_not_relaxed(mode):
    case, setup = case_with_native_setup()
    rows = case[-1]["dialogue_checks"]
    if mode == "missing":
        rows.pop(next(iter(rows)))
    else:
        rows["E9999"] = deepcopy(next(iter(rows.values())))
    assert not validate(case, setup)["valid"]


def test_native_initial_catalog_preserves_original_values_and_entity_path():
    case, setup = case_with_native_setup()
    before = frozen.prior.digest(setup)
    catalog = review.initial_evidence_catalog(case[1], setup)
    assert catalog["initial:prop:slip"]["path"] == "/props/slip"
    assert catalog["initial:prop:slip"]["origin"] == "native_opening_setup_document"
    assert catalog["initial:prop:slip"]["value"] == setup["props"]["slip"]
    catalog["initial:prop:slip"]["value"]["location"] = "测试复制对象"
    assert frozen.prior.digest(setup) == before


@pytest.mark.parametrize("mutation", ["missing_prop", "forged_projection", "different_goal"])
def test_native_projection_and_goal_cannot_be_rebound_by_recomputing_only_header(mutation):
    case, setup = case_with_native_setup()
    kwargs = {}
    if mutation == "missing_prop":
        setup["props"].pop("slip")
    elif mutation == "forged_projection":
        setup["props"]["slip"]["location"] = "另一间办公室"
    else:
        goal = {"complete_original_goal": "independent fixture"}
        setup["goal_sha256"] = "0" * 64
        case[-1]["goal_contract_sha256"] = frozen.prior.digest(goal)
        kwargs["goal_contract"] = goal
    case[-1]["opening_setup_sha256"] = frozen.prior.digest(setup)
    assert not validate(case, setup, **kwargs)["valid"]


@pytest.mark.parametrize("quote", ["把文件夹合上", "从未出现的柜中", ""])
def test_current_action_or_fabricated_quote_never_establishes_initial_state(quote):
    case, setup = case_with_native_setup()
    case[-1]["action_checks"]["E0001"]["preconditions"] = [condition("holder_character_id", None, quote)]
    result = validate(case, setup)
    assert not result["valid"] and result["accepted"] is False


def test_true_quote_cannot_support_fabricated_native_location_value():
    case, setup = case_with_native_setup()
    case[-1]["action_checks"]["E0001"]["preconditions"] = [condition("location", "另一柜子里")]
    result = validate(case, setup)
    assert not result["valid"] and "explicit native setup atom" in result["findings"][0]["reason"]


@pytest.mark.parametrize("key,value", [("holder_character_id", "hr"), ("open", False), ("presence", "absent")])
def test_same_entity_true_quote_cannot_forge_other_explicit_initial_atom(key, value):
    case, setup = case_with_native_setup()
    case[-1]["action_checks"]["E0001"]["preconditions"] = [condition(key, value)]
    result = validate(case, setup)
    assert not result["valid"] and "explicit native setup atom" in result["findings"][0]["reason"]


def test_exact_native_location_and_same_entity_quote_is_a_valid_declared_witness():
    case, setup = case_with_native_setup()
    case[-1]["action_checks"]["E0001"]["preconditions"] = [condition("location", "长桌上，没人持有")]
    assert validate(case, setup)["accepted"]


@pytest.mark.parametrize("value", [True, False])
def test_native_location_quote_cannot_certify_an_undeclared_container_open_value(value):
    case, setup = case_with_native_setup()
    setup["props"]["slip"].pop("open")
    native = setup["props"]["slip"]
    row = next(item for item in case[1]["initial_state"]["prop_states"] if item["id"] == "slip")
    row["expected_state"] = json.dumps(native, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = frozen.prior.digest(case[1])
    case[-1]["opening_setup_sha256"] = frozen.prior.digest(setup)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [
        condition("open", value, "长桌上，没人持有")]
    result = validate(case, setup)
    assert not result["valid"] and not result["accepted"]


@pytest.mark.parametrize("origin", ["E0003", "E0005"])
def test_current_or_future_action_cannot_prove_its_own_prior_state(origin):
    case, setup = case_with_native_setup()
    entries = frozen.prior.contract.evidence_catalog(case[0])
    case[-1]["action_checks"]["E0003"]["preconditions"] = [condition("open", False, entries[origin]["quote"], origin)]
    result = validate(case, setup)
    assert not result["valid"] and "earlier actual action" in result["findings"][0]["reason"]


@pytest.mark.parametrize("key,value", [("open", None), ("presence", "unknown")])
def test_unknown_native_value_cannot_support_a_passing_precondition(key, value):
    case, setup = case_with_native_setup()
    setup["props"]["slip"][key] = value
    native = setup["props"]["slip"]
    row = next(item for item in case[1]["initial_state"]["prop_states"] if item["id"] == "slip")
    row["expected_state"] = json.dumps(native, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = frozen.prior.digest(case[1])
    case[-1]["opening_setup_sha256"] = frozen.prior.digest(setup)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [
        condition(key, value, "长桌上，没人持有")]
    result = validate(case, setup)
    assert not result["valid"] and not result["accepted"]


@pytest.mark.parametrize("missing", [True, False])
def test_honestly_unknown_open_state_remains_an_uncertainty_halt(missing):
    case, setup = case_with_native_setup()
    if missing:
        setup["props"]["slip"].pop("open")
    else:
        setup["props"]["slip"]["open"] = None
    native = setup["props"]["slip"]
    row = next(item for item in case[1]["initial_state"]["prop_states"] if item["id"] == "slip")
    row["expected_state"] = json.dumps(native, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = frozen.prior.digest(case[1])
    case[-1]["opening_setup_sha256"] = frozen.prior.digest(setup)
    action = case[-1]["action_checks"]["E0001"]
    action["status"] = "unknown"
    witness = condition("open", True, "长桌上，没人持有")
    witness["actual_value"] = None
    action["preconditions"] = [witness]
    result = validate(case, setup)
    assert result["valid"] and result["status"] == "halt_review_uncertain"
    assert not result["accepted"]


def test_earlier_action_must_prove_exact_last_reported_value_and_original_quote():
    case, setup = case_with_native_setup()
    case[-1]["action_checks"]["E0003"]["preconditions"] = [condition("open", False, "把文件夹合上", "E0001")]
    assert validate(case, setup)["accepted"]
    case[-1]["action_checks"]["E0003"]["preconditions"][0]["quote"] = "把文件夹打开"
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("status,expected", [("fail", "needs_whole_revision"), ("unknown", "halt_review_uncertain")])
def test_open_turn_function_cannot_override_negative_content_routing(status, expected):
    case, setup = case_with_native_setup()
    next(iter(case[-1]["dialogue_checks"].values()))["turn_function"] = "statement"
    row = case[-1]["goal_checks"]["local_consequence"]
    row.update(status=status, required_revision="模型须提交完整新稿修正因果。" if status == "fail" else "")
    result = validate(case, setup)
    assert result["valid"] and result["status"] == expected and not result["accepted"]


def test_true_quote_with_wrong_entity_id_remains_invalid():
    case, setup = case_with_native_setup()
    row = condition("holder_character_id", None)
    row["established_by"] = "initial:character:worker"
    case[-1]["action_checks"]["E0001"]["preconditions"] = [row]
    assert not validate(case, setup)["valid"]


def test_real_546_remains_rejected_after_offline_new_schema_preview_only():
    root = Path("data/production_trials/goal_context_text_production_20261013/round_06")
    paths = [root / "call_541_goal_plan_09.json", root / "call_544_opening_setup_01.json",
             root / "call_545_complete_script_01.json", root / "call_546_full_review_01.json"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    native_receipt = json.loads(paths[-1].read_bytes())
    assert native_receipt["status"] == "contract_rejected"
    document = deepcopy(native_receipt["output"])
    script = json.loads(paths[-2].read_bytes())["validation"]["script"]
    views = json.loads((root / "requests/complete_script_01.json").read_bytes())["views"]
    legal = json.loads((root / "requests/full_review_01.json").read_bytes())["review_legal_context"]
    document["schema"] = review.VERSION
    document["opening_setup_sha256"] = frozen.prior.digest(views["opening_setup"])
    assert document["dialogue_checks"]["E0029"]["turn_function"] == "statement"
    Draft202012Validator(review.build_review_schema(script, views["brief"], views["plan"], legal,
        goal_contract=views["goal"], opening_setup=views["opening_setup"])).validate(document)
    result = review.validate_full_review(document, script, views["brief"], views["plan"], legal,
        goal_contract=views["goal"], opening_setup=views["opening_setup"])
    assert not result["valid"] and not result["accepted"]
    assert result["findings"][0]["code"] == "REVIEW_EVIDENCE_INVALID"
    with pytest.raises(ValueError):
        review._validate_extra(document, script, views["brief"], opening_setup=views["opening_setup"])
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_validation_never_mutates_the_native_setup_or_review_input():
    case, setup = case_with_native_setup()
    before = [frozen.prior.digest(value) for value in (*case, setup)]
    assert validate(case, setup)["accepted"]
    assert [frozen.prior.digest(value) for value in (*case, setup)] == before
