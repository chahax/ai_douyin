"""Offline state/evidence tests; synthetic pass labels are not quality gold."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_full_review_contract_v3 as old
from src.content_factory import creative_full_review_contract_v4 as review
from tests.test_creative_full_review_contract_v3 import fixture as old_fixture, physical_fixture as old_physical


def fixture(physical=False, *, with_setup=False):
    case = old_physical() if physical else old_fixture()
    case[-1]["schema"] = review.VERSION
    case[-1]["opening_setup_sha256"] = None
    if not with_setup:
        return case, None
    brief = case[1]
    setup = {"schema": "offline_native_setup", "characters": {}, "props": {}}
    for kind, field in (("characters", "character_states"), ("props", "prop_states")):
        for row in brief["initial_state"][field]:
            if kind == "characters":
                native = {"posture": row.get("posture"), "location": row.get("location")}
            else:
                native = {key: deepcopy(row.get(key)) for key in
                          ("holder_character_id", "location", "orientation", "presence_at_start")}
                native["location"] = "长桌上，没人持有"
            setup[kind][row["id"]] = native
            row["expected_state"] = json.dumps(native, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = old.prior.digest(brief)
    case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    return case, setup


def validate(case, setup=None, **kwargs):
    return review.validate_full_review(case[-1], *case[:4], opening_setup=setup, **kwargs)


@pytest.mark.parametrize("label", ["statement", "inform", "陈述并告知自己开始书写", "告知 / 拒绝补偿性让步"])
def test_open_descriptive_label_is_not_filtered_by_old_enum(label):
    case, setup = fixture(with_setup=True)
    next(iter(case[-1]["dialogue_checks"].values()))["turn_function"] = label
    Draft202012Validator(review.build_review_schema(*case[:4], opening_setup=setup)).validate(case[-1])
    result = validate(case, setup)
    assert result["valid"] and result["accepted"]
    assert not result["creative_quality_passed"] and not result["human_quality_approved"]
    assert result["native_initial_projection_verified"]


@pytest.mark.parametrize("label", ["", " \t\n", None, 3, [], {"tag": "statement"}])
def test_descriptive_label_requires_substantive_string(label):
    case, setup = fixture()
    next(iter(case[-1]["dialogue_checks"].values()))["turn_function"] = label
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("mode", ["missing", "extra", "empty"])
def test_all_dialogue_coverage_remains_closed(mode):
    case, setup = fixture()
    rows = case[-1]["dialogue_checks"]
    if mode == "missing":
        rows.pop(next(iter(rows)))
    elif mode == "extra":
        rows["E9999"] = deepcopy(next(iter(rows.values())))
    else:
        rows.clear()
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("field", ["script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256", "opening_setup_sha256"])
def test_every_native_source_identity_remains_exact(field):
    case, setup = fixture(with_setup=True)
    case[-1][field] = "0" * 64
    assert not validate(case, setup)["valid"]


def test_program_catalog_is_native_setup_values_and_paths_without_action_fill():
    case, setup = fixture(with_setup=True)
    before = old.prior.digest(setup)
    catalog = review.initial_evidence_catalog(case[1], setup)
    assert catalog["initial:prop:slip"]["value"] == setup["props"]["slip"]
    assert catalog["initial:prop:slip"]["path"] == "/props/slip"
    assert catalog["initial:prop:slip"]["origin"] == "native_opening_setup_document"
    catalog["initial:prop:slip"]["value"]["location"] = "fake location"
    assert old.prior.digest(setup) == before


@pytest.mark.parametrize("mutation", ["coverage_missing", "coverage_extra", "projected_text", "projected_boolean_type"])
def test_native_setup_projection_cannot_be_hand_rebound(mutation):
    case, setup = fixture(with_setup=True)
    if mutation == "coverage_missing":
        setup["props"].pop("slip")
    elif mutation == "coverage_extra":
        setup["props"]["extra"] = deepcopy(setup["props"]["slip"])
    elif mutation == "projected_text":
        setup["props"]["slip"]["location"] = "另一张桌子上"
    else:
        setup["props"]["slip"]["holder_character_id"] = False
    # Even recomputing the caller's advertised setup SHA cannot change the
    # original compiler projection into this different native setup.
    case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    assert not validate(case, setup)["valid"]


def test_initial_witness_accepts_exact_same_native_state_prose():
    case, setup = fixture(physical=True, with_setup=True)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "holder_character_id", "expected_value": None,
        "actual_value": None, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert validate(case, setup)["accepted"]


@pytest.mark.parametrize("quote", ["把文件夹合上", "角色已经拿着文件夹", "不在任何原生字段中的措辞"])
def test_current_action_or_invented_text_cannot_prove_native_initial_state(quote):
    case, setup = fixture(physical=True, with_setup=True)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "holder_character_id", "expected_value": None,
        "actual_value": None, "established_by": "initial:prop:slip", "quote": quote}]
    result = validate(case, setup)
    assert not result["valid"] and "same native setup" in result["findings"][0]["reason"]


@pytest.mark.parametrize("origin,quote", [("E0003", "陈姐伸手"), ("E0005", "拿到手里"), ("E0001", "陈姐伸手")])
def test_state_witness_requires_strictly_earlier_source_and_unchanged_quote(origin, quote):
    case, setup = fixture(physical=True)
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "open", "expected_value": False,
        "actual_value": False, "established_by": origin, "quote": quote}]
    assert not validate(case, setup)["valid"]


def test_valid_earlier_witness_keeps_existing_state_trace():
    case, setup = fixture(physical=True)
    case[-1]["action_checks"]["E0003"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "open", "expected_value": False,
        "actual_value": False, "established_by": "E0001", "quote": "把文件夹合上"}]
    assert validate(case, setup)["accepted"]


def test_same_meaning_different_reported_state_text_is_not_normalized():
    case, setup = fixture(physical=True, with_setup=True)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "location", "expected_value": "长桌上，没人持有",
        "actual_value": "在桌上无人拿着", "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert not validate(case, setup)["valid"]


def test_true_quote_cannot_certify_a_forged_explicit_initial_location():
    case, setup = fixture(physical=True, with_setup=True)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "location", "expected_value": "另一柜子里",
        "actual_value": "另一柜子里", "established_by": "initial:prop:slip", "quote": "没人持有"}]
    result = validate(case, setup)
    assert not result["valid"] and "explicit native setup atom" in result["findings"][0]["reason"]


@pytest.mark.parametrize("actual", [True, False, None])
def test_undeclared_open_cannot_pass_with_a_true_location_quote(actual):
    case, setup = fixture(physical=True, with_setup=True)
    assert "open" not in setup["props"]["slip"]
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": "open", "expected_value": actual,
        "actual_value": actual, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    result = validate(case, setup)
    assert not result["valid"] and "does not explicitly establish" in result["findings"][0]["reason"]


@pytest.mark.parametrize("atom,value", [("open", None), ("presence", "unknown")])
def test_explicit_unknown_initial_atom_does_not_satisfy_a_passing_precondition(atom, value):
    case, setup = fixture(physical=True, with_setup=True)
    source = setup["props"]["slip"]
    source[atom] = value
    if atom == "presence":
        source["presence_at_start"] = "unknown"
    prop = next(row for row in case[1]["initial_state"]["prop_states"] if row["id"] == "slip")
    prop["expected_state"] = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = old.prior.digest(case[1])
    case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": atom, "expected_value": value,
        "actual_value": value, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    result = validate(case, setup)
    assert not result["valid"] and "unknown native setup atom" in result["findings"][0]["reason"]


@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("status", ["unknown", "fail"])
def test_unverified_initial_open_keeps_honest_nonpassing_route(declared, status):
    case, setup = fixture(physical=True, with_setup=True)
    if declared:
        source = setup["props"]["slip"]
        source["open"] = None
        prop = next(row for row in case[1]["initial_state"]["prop_states"] if row["id"] == "slip")
        prop["expected_state"] = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
        case[-1]["brief_sha256"] = old.prior.digest(case[1])
        case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    row = case[-1]["action_checks"]["E0001"]
    row.update(status=status, required_revision="完整新稿须解决未证实的开合前提。" if status == "fail" else "")
    row["preconditions"] = [{"entity_id": "slip", "state_key": "open", "expected_value": True,
        "actual_value": None, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    result = validate(case, setup)
    assert result["valid"] and not result["accepted"]
    assert result["status"] == ("halt_review_uncertain" if status == "unknown" else "needs_whole_revision")


def test_explicit_known_initial_open_can_support_matching_precondition():
    case, setup = fixture(physical=True, with_setup=True)
    source = setup["props"]["slip"]
    source["open"] = True
    prop = next(row for row in case[1]["initial_state"]["prop_states"] if row["id"] == "slip")
    prop["expected_state"] = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = old.prior.digest(case[1])
    case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "expected_value": True, "actual_value": True, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert validate(case, setup)["accepted"]


@pytest.mark.parametrize("kind,field,value,atom,wrong", [
    ("scene", "scene_id", "office", "holder_character_id", "worker"),
    ("prop", "container_prop_id", "worker", "support_entity_id", "hr"),
    ("actor", "actor_id", "worker", "holder_character_id", "hr"),
    ("absent", None, None, "location", "长桌上"),
])
def test_typed_placement_initial_atoms_are_not_reinvented(kind, field, value, atom, wrong):
    case, setup = fixture(physical=True, with_setup=True)
    source = {"kind": kind, "orientation": None}
    if field:
        source.update({field: value, "location": "本轮原生位置"})
    setup["props"]["slip"] = source
    prop = next(row for row in case[1]["initial_state"]["prop_states"] if row["id"] == "slip")
    prop["expected_state"] = json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    case[-1]["brief_sha256"] = old.prior.digest(case[1])
    case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{
        "entity_id": "slip", "state_key": atom, "expected_value": wrong,
        "actual_value": wrong, "established_by": "initial:prop:slip", "quote": kind}]
    result = validate(case, setup)
    assert not result["valid"] and "explicit native setup atom" in result["findings"][0]["reason"]


@pytest.mark.parametrize("table,key", [("dialogue_checks", "E0002"), ("action_checks", "E0001"),
                                     ("goal_checks", "local_consequence"), ("criteria", "factual_physical"),
                                     ("ending_checks", "visible_consequence")])
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_every_content_failure_or_uncertainty_still_blocks_handoff(table, key, status):
    case, setup = fixture(physical=True)
    row = case[-1][table][key]
    row.update(status=status, required_revision="完整新稿须解决已明确的因果缺口。" if status == "fail" else "")
    result = validate(case, setup)
    assert result["valid"] and not result["accepted"]
    assert result["status"] == ("needs_whole_revision" if status == "fail" else "halt_review_uncertain")


def test_goal_and_setup_identity_must_match_without_rewriting_either():
    case, setup = fixture(with_setup=True)
    goal = {"complete_native_plan": "original"}
    setup["goal_sha256"] = "0" * 64
    case[-1]["opening_setup_sha256"] = old.prior.digest(setup)
    case[-1]["goal_contract_sha256"] = old.prior.digest(goal)
    assert not validate(case, setup, goal_contract=goal)["valid"]


def test_schema_is_a_new_contract_not_old_review_acceptance():
    case, setup = fixture()
    schema = review.build_review_schema(*case[:4])
    assert schema["properties"]["schema"] == {"const": review.VERSION}
    case[-1]["schema"] = old.VERSION
    assert not validate(case, setup)["valid"]


def test_real_546_open_label_preview_still_fails_original_witnesses_read_only():
    root = Path("data/production_trials/goal_context_text_production_20261013/round_06")
    receipt_path = root / "call_546_full_review_01.json"
    before = receipt_path.read_bytes()
    receipt = json.loads(before)
    doc = deepcopy(receipt["output"])
    script = json.loads((root / "call_545_complete_script_01.json").read_text(encoding="utf-8"))["validation"]["script"]
    views = json.loads((root / "requests/complete_script_01.json").read_text(encoding="utf-8"))["views"]
    prepared = json.loads((root / "requests/full_review_01.json").read_text(encoding="utf-8"))
    assert doc["dialogue_checks"]["E0029"]["turn_function"] == "statement"
    # Offline only: the preview header identifies a hypothetical new contract.
    # The provider-native old response/receipt remains unmodified and unusable.
    doc["schema"] = review.VERSION
    doc["opening_setup_sha256"] = old.prior.digest(views["opening_setup"])
    Draft202012Validator(review.build_review_schema(script, views["brief"], views["plan"],
        prepared["review_legal_context"], goal_contract=views["goal"], opening_setup=views["opening_setup"])).validate(doc)
    result = review.validate_full_review(doc, script, views["brief"], views["plan"],
        prepared["review_legal_context"], goal_contract=views["goal"], opening_setup=views["opening_setup"])
    assert not result["valid"] and not result["accepted"]
    assert result["findings"][0]["code"] == "REVIEW_EVIDENCE_INVALID"
    assert "frozen native declarations" in result["findings"][0]["reason"]
    # The preserved observed-initial gate rejects first. Independently inspect
    # the unchanged original witnesses to prove that the more specific source
    # gate also rejects, without skipping either gate to accept this response.
    with pytest.raises(ValueError, match="same native setup"):
        review._validate_extra(doc, script, views["brief"], opening_setup=views["opening_setup"])
    assert receipt_path.read_bytes() == before


def test_validation_does_not_change_setup_brief_script_or_native_response():
    case, setup = fixture(physical=True, with_setup=True)
    snapshots = [old.prior.digest(value) for value in (*case, setup)]
    assert validate(case, setup)["valid"]
    assert [old.prior.digest(value) for value in (*case, setup)] == snapshots
