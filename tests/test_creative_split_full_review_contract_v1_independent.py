"""Independent split-audit counterexamples; no clients or accepted production.

Synthetic model judgements exercise contracts only. Real 552 is read-only and
its memory-only diagnostic projections can never become native adopted parts.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_full_review_contract_v5 as full
from src.content_factory import creative_split_full_review_contract_v1 as split
from tests.test_creative_full_review_contract_v4_independent import (
    case_with_native_setup, condition,
)

CONTEXTS = {"semantic": "a" * 64, "physical": "b" * 64}


def fixture(*, zero_facts=False):
    case, setup = case_with_native_setup()
    for key in ("source_obligations", "initial_conditions", "source_order"):
        case[2][key] = []
    if zero_facts:
        case[1]["facts"] = []
    digest = full.base.base.prior.digest
    case[-1].update(schema=full.VERSION, brief_sha256=digest(case[1]), plan_sha256=digest(case[2]))
    coverage = full.review_table_contract(*case[:3])
    for table in coverage["omitted_zero_tables"]:
        case[-1].pop(table)
    parts = {}
    for part in CONTEXTS:
        schema = split.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)
        parts[part] = {field: deepcopy(case[-1][field]) for field in schema["properties"] if field in case[-1]}
        parts[part].update(schema=split.VERSION, part=part, context_sha256=CONTEXTS[part], revision_target="none")
    return case, setup, parts


def validate(case, setup, parts, *, contexts=CONTEXTS):
    return split.validate_bundle(split.build_review_bundle(parts["semantic"], parts["physical"]), *case[:4],
        semantic_context_sha256=contexts["semantic"], physical_context_sha256=contexts["physical"], opening_setup=setup)


def part_result(case, setup, parts, part):
    return split.validate_part(parts[part], part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)


def test_two_owned_coverage_sets_exactly_partition_actual_full_contract():
    case, setup, parts = fixture(zero_facts=True)
    tables = full.review_table_contract(*case[:3])
    expected = set(tables["required_tables"]) | {"legal_claims", "review_limitations"}
    owned = [set(split.part_table_contract(part, *case[:3])["required_tables"]) for part in CONTEXTS]
    assert owned[0].isdisjoint(owned[1]) and owned[0] | owned[1] == expected
    assert set(tables["omitted_zero_tables"]) == {"plan_support", "fact_checks", "obligations", "order_checks"}
    for part in CONTEXTS:
        schema = split.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)
        Draft202012Validator(schema).validate(parts[part])
    result = validate(case, setup, parts)
    assert result["valid"] and result["accepted"]
    assert result["review_origin"] == "two_native_same_source_parts" and result["native_single_full_review"] is False
    assert result["creative_quality_passed"] is False and result["human_quality_approved"] is False


@pytest.mark.parametrize("table", ["plan_support", "fact_checks", "obligations", "order_checks"])
@pytest.mark.parametrize("content", [{}, {"status": "pass", "reason": "generic total review"}])
def test_proven_zero_owned_tables_reject_empty_and_generic_native_rows(table, content):
    case, setup, parts = fixture(zero_facts=True)
    parts["semantic"][table] = deepcopy(content)
    assert not part_result(case, setup, parts, "semantic")["valid"]
    assert not validate(case, setup, parts)["accepted"]


@pytest.mark.parametrize("part,table", [("semantic", "literal_events"), ("semantic", "dialogue_checks"),
    ("semantic", "goal_checks"), ("physical", "initial_checks"), ("physical", "action_checks")])
@pytest.mark.parametrize("mode", ["missing", "foreign_key"])
def test_nonzero_coverage_is_closed_before_partial_acceptance(part, table, mode):
    case, setup, parts = fixture()
    if mode == "missing":
        parts[part][table].pop(next(iter(parts[part][table])))
    else:
        parts[part][table]["other_source_id"] = deepcopy(next(iter(parts[part][table].values())))
    assert not part_result(case, setup, parts, part)["valid"]
    assert not validate(case, setup, parts)["accepted"]


@pytest.mark.parametrize("part,table", [("semantic", "action_checks"), ("physical", "dialogue_checks"),
    ("physical", "review_limitations")])
def test_a_part_cannot_supply_or_claim_the_other_parts_table(part, table):
    case, setup, parts = fixture()
    parts[part][table] = {}
    assert not part_result(case, setup, parts, part)["valid"]


@pytest.mark.parametrize("part", ["semantic", "physical"])
@pytest.mark.parametrize("field", [*split.SOURCE_HEADERS, "context_sha256"])
def test_source_and_actual_part_context_headers_are_exact(part, field):
    case, setup, parts = fixture()
    parts[part][field] = "c" * 64
    assert not part_result(case, setup, parts, part)["valid"]
    assert not validate(case, setup, parts)["accepted"]


def test_two_valid_parts_from_different_script_source_cannot_be_mixed():
    case, setup, parts = fixture()
    other, other_setup, other_parts = fixture()
    other[0]["title"] = "另一份合成全文"
    other_parts["physical"]["script_sha256"] = full.base.base.prior.digest(other[0])
    assert part_result(other, other_setup, other_parts, "physical")["valid"]
    parts["physical"] = other_parts["physical"]
    assert not validate(case, setup, parts)["accepted"]


@pytest.mark.parametrize("mode", ["missing_part", "duplicate_part", "extra_full", "same_context"])
def test_bundle_cannot_collapse_or_replace_the_two_original_parts(mode):
    case, setup, parts = fixture()
    bundle = split.build_review_bundle(parts["semantic"], parts["physical"])
    contexts = deepcopy(CONTEXTS)
    if mode == "missing_part":
        bundle.pop("native_physical_review")
    elif mode == "duplicate_part":
        bundle["native_physical_review"] = deepcopy(parts["semantic"])
    elif mode == "extra_full":
        bundle["native_full_review"] = deepcopy(case[-1])
    else:
        contexts["physical"] = contexts["semantic"]
    assert not split.validate_bundle(bundle, *case[:4], semantic_context_sha256=contexts["semantic"],
        physical_context_sha256=contexts["physical"], opening_setup=setup)["accepted"]


@pytest.mark.parametrize("part,table", [("semantic", "fact_checks"), ("semantic", "goal_checks"),
    ("physical", "action_checks")])
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_content_failure_and_honest_uncertainty_never_gain_acceptance_by_bundling(part, table, status):
    case, setup, parts = fixture()
    next(iter(parts[part][table].values())).update(status=status, required_revision="完整新稿解决问题。" if status == "fail" else "")
    parts[part]["revision_target"] = "script" if status == "fail" else "none"
    result = validate(case, setup, parts)
    expected = "needs_whole_revision" if status == "fail" else "halt_review_uncertain"
    assert result["valid"] and not result["accepted"] and result["status"] == expected
    assert part_result(case, setup, parts, part)["status"] == expected


@pytest.mark.parametrize("key,value", [("location", "另一间屋子"), ("holder_character_id", "hr"), ("open", False)])
def test_real_setup_quote_never_supports_a_forged_physical_atom(key, value):
    case, setup, parts = fixture()
    parts["physical"]["action_checks"]["E0001"]["preconditions"] = [condition(key, value)]
    assert not part_result(case, setup, parts, "physical")["valid"]


@pytest.mark.parametrize("mode", ["missing", "explicit_null"])
def test_unestablished_open_cannot_pass_but_honest_unknown_remains_halt(mode):
    case, setup, parts = fixture()
    if mode == "missing":
        setup["props"]["slip"].pop("open")
    else:
        setup["props"]["slip"]["open"] = None
    prop = next(row for row in case[1]["initial_state"]["prop_states"] if row["id"] == "slip")
    prop["expected_state"] = json.dumps(setup["props"]["slip"], ensure_ascii=False, separators=(",", ":"))
    digest = full.base.base.prior.digest
    for part in parts.values():
        part.update(brief_sha256=digest(case[1]), opening_setup_sha256=digest(setup))
    row = parts["physical"]["action_checks"]["E0001"]
    row["preconditions"] = [condition("open", True)]
    assert not part_result(case, setup, parts, "physical")["valid"]
    row.update(status="unknown")
    row["preconditions"][0]["actual_value"] = None
    result = part_result(case, setup, parts, "physical")
    assert result["valid"] and not result["accepted"] and result["status"] == "halt_review_uncertain"


@pytest.mark.parametrize("source", ["E0001", "E0005"])
def test_current_and_future_event_cannot_establish_current_action_precondition(source):
    case, setup, parts = fixture()
    quote = full.base.base.prior.contract.evidence_catalog(case[0])[source]["quote"]
    parts["physical"]["action_checks"]["E0001"]["preconditions"] = [condition("open", True, quote, source)]
    assert not part_result(case, setup, parts, "physical")["valid"]


def test_both_part_and_bundle_validation_keep_original_native_bytes_semantics():
    case, setup, parts = fixture()
    digest = full.base.base.prior.digest
    before = digest([case, setup, parts])
    for part in parts:
        result = part_result(case, setup, parts, part)
        assert result["valid"] and result["accepted"] and not result["complete_same_source_full_review"]
    assert validate(case, setup, parts)["accepted"]
    assert digest([case, setup, parts]) == before
    assert all("native_full_review" not in part and "review_origin" not in part for part in parts.values())


def test_552_original_stays_rejected_and_its_other_faults_are_not_waived():
    root = Path("data/production_trials/goal_context_text_production_20261013/round_07")
    path = root / "call_552_full_review_01.json"
    original = path.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    native = json.loads(original)["output"]
    prepared = json.loads((root / "requests/full_review_01.json").read_text(encoding="utf-8"))
    views = json.loads((root / "requests/complete_script_01.json").read_text(encoding="utf-8"))["views"]
    script = json.loads((root / "call_551_complete_script_01.json").read_text(encoding="utf-8"))["validation"]["script"]
    args = (script, views["brief"], views["plan"], prepared["review_legal_context"])
    kwargs = {"goal_contract": views["goal"], "opening_setup": views["opening_setup"]}
    assert not full.validate_full_review(native, *args, **kwargs)["valid"]
    parts = {}
    for part in CONTEXTS:
        schema = split.build_part_schema(part, *args, context_sha256=CONTEXTS[part], **kwargs)
        parts[part] = {field: deepcopy(native[field]) for field in schema["properties"] if field in native}
        parts[part].update(schema=split.VERSION, part=part, context_sha256=CONTEXTS[part], revision_target="none")
    semantic = split.validate_part(parts["semantic"], "semantic", *args, context_sha256=CONTEXTS["semantic"], **kwargs)
    physical = split.validate_part(parts["physical"], "physical", *args, context_sha256=CONTEXTS["physical"], **kwargs)
    assert not semantic["valid"] and not semantic["accepted"]
    assert "own actual dialogue reference" in semantic["findings"][0]["reason"]
    assert parts["semantic"]["fact_checks"]["CC_CTA"]["status"] == "unknown"
    assert not physical["valid"] and not physical["accepted"]
    bundle = split.validate_bundle(split.build_review_bundle(parts["semantic"], parts["physical"]), *args,
        semantic_context_sha256=CONTEXTS["semantic"], physical_context_sha256=CONTEXTS["physical"], **kwargs)
    assert not bundle["accepted"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("part,table", [("semantic", "goal_checks"), ("physical", "action_checks")])
def test_zero_plan_support_does_not_make_native_plan_revision_target_unreachable(part, table):
    case, setup, parts = fixture()
    assert "plan_support" not in parts["semantic"]
    row = next(iter(parts[part][table].values()))
    row.update(status="fail", required_revision="原生整片规划起态或因果错误，需要完整新计划。")
    parts[part]["revision_target"] = "plan"
    result = part_result(case, setup, parts, part)
    assert result["valid"] and not result["accepted"] and result["requires_new_goal_plan"]
    assert any(item["target"] == "plan" for item in result["findings"])
    result = validate(case, setup, parts)
    assert result["valid"] and not result["accepted"] and result["requires_new_goal_plan"]


@pytest.mark.parametrize("target", ["script", "plan"])
def test_passing_part_cannot_claim_a_revision_target(target):
    case, setup, parts = fixture()
    parts["semantic"]["revision_target"] = target
    assert not part_result(case, setup, parts, "semantic")["valid"]


@pytest.mark.parametrize("relation,status", [("same_story", "halt_same_story_prior_allowance_exhausted"),
    ("unknown", "halt_prior_story_relation_unknown")])
def test_prior_story_relation_is_not_downgraded_to_ordinary_script_revision(relation, status):
    case, setup, parts = fixture()
    digest = full.base.base.prior.digest
    case[1]["prior_story_scope"] = {"full_prior_script": {"premise": "另一个旧故事", "beats": []}, "director_remaining": 0}
    for part in parts.values():
        part["brief_sha256"] = digest(case[1])
    entries = full.base.base.prior.contract.evidence_catalog(case[0])
    ref = next(iter(entries))
    parts["semantic"]["prior_story_relation"] = {"prior_scope_sha256": digest(case[1]["prior_story_scope"]),
        "relation": relation, "reason": "只测旧额度不能重领，不是审美判断。",
        "current_evidence": [{"source_ref": ref, "quote": entries[ref]["quote"]}]}
    next(iter(parts["semantic"]["goal_checks"].values())).update(status="fail", required_revision="完整新计划修正来源。")
    parts["semantic"]["revision_target"] = "plan"
    result = part_result(case, setup, parts, "semantic")
    assert result["valid"] and not result["accepted"] and result["status"] == status
    assert result["revision_dispatch_blocked"] and not result["requires_new_goal_plan"]
    result = validate(case, setup, parts)
    assert result["status"] == status and result["revision_dispatch_blocked"] and not result["requires_new_goal_plan"]
