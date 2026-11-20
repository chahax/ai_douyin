"""Zero-coverage source contracts, synthetic verdicts are not quality gold."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_full_review_contract_v5 as review
from tests.test_creative_full_review_contract_v4 import fixture as prior_fixture
from tests.test_creative_full_review_contract_v3 import fixture as native_fixture


def fixture(*, zero_plan=True, with_setup=True):
    case, setup = prior_fixture(physical=True, with_setup=with_setup)
    if zero_plan:
        for key in ("source_obligations", "initial_conditions", "source_order"):
            case[2][key] = []
        case[-1]["plan_sha256"] = review.base.base.prior.digest(case[2])
    case[-1]["schema"] = review.VERSION
    for table in review.review_table_contract(*case[:3])["omitted_zero_tables"]:
        case[-1].pop(table)
    return case, setup


def validate(case, setup=None):
    return review.validate_full_review(case[-1], *case[:4], opening_setup=setup)


def test_actual_zero_tables_are_absent_from_native_schema_and_metadata():
    case, setup = fixture()
    contract = review.review_table_contract(*case[:3])
    assert contract["omitted_zero_tables"] == ["plan_support", "obligations", "order_checks"]
    schema = review.build_review_schema(*case[:4], opening_setup=setup)
    for table in contract["omitted_zero_tables"]:
        assert table not in schema["properties"] and table not in schema["required"]
    Draft202012Validator(schema).validate(case[-1])
    assert validate(case, setup)["accepted"]


@pytest.mark.parametrize("table", ["plan_support", "obligations", "order_checks"])
@pytest.mark.parametrize("value", [{}, {"status": "pass", "reason": "summary", "source_refs": [], "required_revision": ""}])
def test_even_empty_native_zero_table_is_an_extra_field(table, value):
    case, setup = fixture()
    case[-1][table] = deepcopy(value)
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("table", ["fact_checks", "initial_checks", "observed_prop_initial", "literal_events",
    "dialogue_checks", "criteria", "ending_checks", "action_checks", "goal_checks"])
@pytest.mark.parametrize("mode", ["missing", "empty", "extra_key"])
def test_nonzero_tables_cannot_be_removed_or_pretend_empty(table, mode):
    case, setup = fixture()
    if mode == "missing":
        case[-1].pop(table)
    elif mode == "empty":
        case[-1][table] = {}
    else:
        case[-1][table]["invented"] = deepcopy(next(iter(case[-1][table].values())))
    assert not validate(case, setup)["valid"]


def test_nonzero_plan_tables_keep_exact_coverage():
    case, setup = fixture(zero_plan=False)
    assert "plan_support" in review.review_table_contract(*case[:3])["required_tables"]
    assert validate(case, setup)["accepted"]
    case[-1].pop("plan_support")
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("field", ["script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256",
    "goal_contract_sha256", "opening_setup_sha256"])
def test_all_source_identity_headers_remain_closed(field):
    case, setup = fixture()
    case[-1][field] = "0" * 64
    assert not validate(case, setup)["valid"]


@pytest.mark.parametrize("status", ["fail", "unknown"])
@pytest.mark.parametrize("table", ["fact_checks", "dialogue_checks", "action_checks", "goal_checks", "criteria"])
def test_zero_table_change_does_not_relax_content_routing(status, table):
    case, setup = fixture()
    row = next(iter(case[-1][table].values()))
    row.update(status=status, required_revision="整稿须解决明确缺口。" if status == "fail" else "")
    result = validate(case, setup)
    assert result["valid"] and not result["accepted"]
    assert result["status"] == ("needs_whole_revision" if status == "fail" else "halt_review_uncertain")


def test_nonzero_plan_failure_requires_new_goal_plan():
    case, setup = fixture(zero_plan=False)
    next(iter(case[-1]["plan_support"].values())).update(status="fail", required_revision="完整新规划须修复源因果。")
    result = validate(case, setup)
    assert result["valid"] and not result["accepted"] and result["requires_new_goal_plan"]


@pytest.mark.parametrize("actual", [True, False, None])
def test_v4_undeclared_initial_atom_gate_remains_active(actual):
    case, setup = fixture()
    case[-1]["action_checks"]["E0001"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "actual_value": actual, "expected_value": actual, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert not validate(case, setup)["valid"]


def test_descriptive_labels_and_honest_unknown_still_work():
    case, setup = fixture()
    next(iter(case[-1]["dialogue_checks"].values()))["turn_function"] = "statement"
    row = case[-1]["action_checks"]["E0001"]
    row.update(status="unknown", required_revision="")
    row["preconditions"] = [{"entity_id": "slip", "state_key": "open", "actual_value": None,
        "expected_value": True, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    result = validate(case, setup)
    assert result["valid"] and result["status"] == "halt_review_uncertain"


def test_internal_zero_projection_does_not_mutate_native_inputs():
    case, setup = fixture()
    digest = review.base.base.prior.digest
    before = digest([*case, setup])
    assert validate(case, setup)["accepted"]
    assert digest([*case, setup]) == before
    projected = review._compiled_view(case[-1], *case[:3])
    assert projected["plan_support"] == {} and "plan_support" not in case[-1]


@pytest.mark.parametrize("kind", ["action", "dialogue"])
def test_actual_no_dialogue_or_no_action_table_is_omitted_by_catalog(kind):
    native = {"title": "离线零项合同", "premise": "仅检验真实事件目录，不是可采用剧情。", "beats": [
        {"id": "B" + str(i), "trigger": "原生触发", "event": "原生事件", "steps": [
            {"kind": kind, "speaker": "worker" if kind == "dialogue" else "", "text": "请说明工资。" if kind == "dialogue" else "阿宁看着纸。"}]}
        for i in range(1, 4)]}
    case = native_fixture(native)
    case[-1].update(schema=review.VERSION, opening_setup_sha256=None)
    for key in ("source_obligations", "initial_conditions", "source_order"):
        case[2][key] = []
    case[-1]["plan_sha256"] = review.base.base.prior.digest(case[2])
    for table in review.review_table_contract(*case[:3])["omitted_zero_tables"]:
        case[-1].pop(table)
    missing = "dialogue_checks" if kind == "action" else "action_checks"
    assert missing not in review.build_review_schema(*case[:4])["properties"]
    assert validate(case)["accepted"]


def real_552():
    root = Path("data/production_trials/goal_context_text_production_20261013/round_07")
    receipt_path = root / "call_552_full_review_01.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    prepared = json.loads((root / "requests/full_review_01.json").read_text(encoding="utf-8"))
    views = json.loads((root / "requests/complete_script_01.json").read_text(encoding="utf-8"))["views"]
    script = json.loads((root / "call_551_complete_script_01.json").read_text(encoding="utf-8"))["validation"]["script"]
    return receipt_path, receipt["output"], script, views, prepared["review_legal_context"]


def test_real_552_is_never_adopted_by_removing_zero_tables_read_only():
    path, native, script, views, legal = real_552()
    before = path.read_bytes()
    kwargs = {"goal_contract": views["goal"], "opening_setup": views["opening_setup"]}
    assert not review.validate_full_review(native, script, views["brief"], views["plan"], legal, **kwargs)["valid"]
    preview = deepcopy(native)
    preview["schema"] = review.VERSION
    for table in review.review_table_contract(script, views["brief"], views["plan"])["omitted_zero_tables"]:
        preview.pop(table)
    result = review.validate_full_review(preview, script, views["brief"], views["plan"], legal, **kwargs)
    assert not result["valid"] and not result["accepted"]
    assert "own actual action reference" in result["findings"][0]["reason"]
    assert preview["fact_checks"]["CC_CTA"]["status"] == "unknown"
    assert path.read_bytes() == before
