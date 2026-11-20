"""Two synthetic native parts test contracts, not creative quality."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_split_full_review_contract_v1 as split
from tests.test_creative_full_review_contract_v5 import fixture as full_fixture, real_552

CONTEXTS = {"semantic": "1" * 64, "physical": "2" * 64}


def fixture(zero_plan=True):
    case, setup = full_fixture(zero_plan=zero_plan)
    parts = {}
    for part in split.PART_TABLES:
        schema = split.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)
        native = {key: deepcopy(case[-1][key]) for key in schema["properties"] if key in case[-1]}
        native.update(schema=split.VERSION, part=part, context_sha256=CONTEXTS[part], revision_target="none")
        parts[part] = native
    return case, setup, parts


def validate_part(case, setup, parts, part):
    return split.validate_part(parts[part], part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)


def validate_bundle(case, setup, parts):
    return split.validate_bundle(split.build_review_bundle(parts["semantic"], parts["physical"]), *case[:4],
        semantic_context_sha256=CONTEXTS["semantic"], physical_context_sha256=CONTEXTS["physical"], opening_setup=setup)


def test_both_source_complete_native_parts_are_required_for_full_acceptance():
    case, setup, parts = fixture()
    for part in split.PART_TABLES:
        result = validate_part(case, setup, parts, part)
        assert result["valid"] and result["accepted"] and not result["complete_same_source_full_review"]
        assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and result["accepted"]
    assert result["review_origin"] == "two_native_same_source_parts" and not result["native_single_full_review"]


def test_part_schemas_keep_only_reachable_shared_definitions():
    case, setup, parts = fixture()
    full = split.reviews.build_review_schema(*case[:4], opening_setup=setup)
    reachable_counts = []
    for part in split.PART_TABLES:
        schema = split.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)
        Draft202012Validator(schema).validate(parts[part])
        assert set(schema.get("$defs", {})).issubset(full.get("$defs", {}))
        reachable_counts.append(len(schema.get("$defs", {})))
    assert max(reachable_counts) < len(full["$defs"])


@pytest.mark.parametrize("part", ["semantic", "physical"])
@pytest.mark.parametrize("field", [*split.SOURCE_HEADERS, "context_sha256", "part", "schema"])
def test_each_part_identity_is_source_bound(part, field):
    case, setup, parts = fixture()
    parts[part][field] = "0" * 64
    assert not validate_part(case, setup, parts, part)["valid"]
    assert not validate_bundle(case, setup, parts)["accepted"]


@pytest.mark.parametrize("part,table", [("semantic", "fact_checks"), ("semantic", "dialogue_checks"),
    ("semantic", "goal_checks"), ("physical", "initial_checks"), ("physical", "observed_prop_initial"),
    ("physical", "action_checks")])
@pytest.mark.parametrize("mode", ["missing", "empty", "extra_key"])
def test_owned_nonzero_coverage_cannot_be_missing_or_synthetic(part, table, mode):
    case, setup, parts = fixture()
    if mode == "missing":
        parts[part].pop(table)
    elif mode == "empty":
        parts[part][table] = {}
    else:
        parts[part][table]["extra"] = deepcopy(next(iter(parts[part][table].values())))
    assert not validate_bundle(case, setup, parts)["accepted"]


@pytest.mark.parametrize("part,extra", [("semantic", "action_checks"), ("physical", "dialogue_checks"),
    ("physical", "review_limitations"), ("semantic", "plan_support")])
def test_extra_table_or_zero_owned_table_cannot_cross_part_boundary(part, extra):
    case, setup, parts = fixture()
    parts[part][extra] = {}
    assert not validate_part(case, setup, parts, part)["valid"]


@pytest.mark.parametrize("mode", ["missing_semantic", "missing_physical", "extra", "same_part"])
def test_bundle_is_closed_and_has_two_distinct_native_parts(mode):
    case, setup, parts = fixture()
    bundle = split.build_review_bundle(parts["semantic"], parts["physical"])
    if mode.startswith("missing"):
        bundle.pop("native_" + mode.split("_", 1)[1] + "_review")
    elif mode == "extra":
        bundle["native_full_review"] = deepcopy(case[-1])
    else:
        bundle["native_physical_review"] = deepcopy(parts["semantic"])
    assert not split.validate_bundle(bundle, *case[:4], semantic_context_sha256=CONTEXTS["semantic"],
        physical_context_sha256=CONTEXTS["physical"], opening_setup=setup)["accepted"]


@pytest.mark.parametrize("part,table", [("semantic", "fact_checks"), ("semantic", "dialogue_checks"),
    ("semantic", "goal_checks"), ("physical", "action_checks"), ("physical", "initial_checks")])
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_any_actual_failure_or_unknown_blocks_part_and_bundle(part, table, status):
    case, setup, parts = fixture()
    next(iter(parts[part][table].values())).update(status=status, required_revision="整稿修复来源缺口。" if status == "fail" else "")
    parts[part]["revision_target"] = "script" if status == "fail" else "none"
    partial = validate_part(case, setup, parts, part)
    result = validate_bundle(case, setup, parts)
    expected = "needs_whole_revision" if status == "fail" else "halt_review_uncertain"
    assert partial["valid"] and not partial["accepted"] and partial["status"] == expected
    assert result["valid"] and not result["accepted"] and result["status"] == expected


def test_plan_failure_is_not_a_script_only_revision():
    case, setup, parts = fixture(zero_plan=False)
    next(iter(parts["semantic"]["plan_support"].values())).update(status="fail", required_revision="完整新规划修复。")
    parts["semantic"]["revision_target"] = "plan"
    assert validate_part(case, setup, parts, "semantic")["requires_new_goal_plan"]
    assert validate_bundle(case, setup, parts)["requires_new_goal_plan"]


@pytest.mark.parametrize("part,table", [("semantic", "goal_checks"), ("semantic", "criteria"),
    ("physical", "action_checks")])
def test_native_plan_target_remains_reachable_when_plan_support_is_zero(part, table):
    case, setup, parts = fixture()
    assert "plan_support" not in parts["semantic"]
    next(iter(parts[part][table].values())).update(status="fail", required_revision="原生完整规划须解决因果前提。")
    parts[part]["revision_target"] = "plan"
    partial = validate_part(case, setup, parts, part)
    result = validate_bundle(case, setup, parts)
    assert partial["valid"] and partial["requires_new_goal_plan"] and not partial["accepted"]
    assert result["valid"] and not result["accepted"] and result["requires_new_goal_plan"]
    assert result["status"] == "halt_full_review_requires_new_complete_goal"
    assert result["findings"][0]["target"] == "plan"


@pytest.mark.parametrize("target", ["script", "plan"])
def test_pass_or_unknown_without_failure_cannot_request_native_revision(target):
    case, setup, parts = fixture()
    parts["semantic"]["revision_target"] = target
    assert not validate_part(case, setup, parts, "semantic")["valid"]
    next(iter(parts["semantic"]["fact_checks"].values())).update(status="unknown", required_revision="")
    assert not validate_part(case, setup, parts, "semantic")["valid"]


def test_native_definite_failure_cannot_hide_its_target_as_none():
    case, setup, parts = fixture()
    next(iter(parts["semantic"]["goal_checks"].values())).update(status="fail", required_revision="修复完整因果。")
    assert not validate_part(case, setup, parts, "semantic")["valid"]


def test_unknown_has_priority_over_a_known_plan_target_failure():
    case, setup, parts = fixture()
    next(iter(parts["semantic"]["goal_checks"].values())).update(status="fail", required_revision="修复完整规划。")
    parts["semantic"]["revision_target"] = "plan"
    next(iter(parts["physical"]["initial_checks"].values())).update(status="unknown", required_revision="")
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and not result["accepted"] and result["status"] == "halt_review_uncertain"
    assert result["requires_new_goal_plan"] and result["uncertainties"]


@pytest.mark.parametrize("actual", [True, False, None])
def test_physical_part_keeps_v4_explicit_initial_atom_gate(actual):
    case, setup, parts = fixture()
    parts["physical"]["action_checks"]["E0001"]["preconditions"] = [{"entity_id": "slip", "state_key": "open",
        "actual_value": actual, "expected_value": actual, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert not validate_part(case, setup, parts, "physical")["valid"]


def test_unknown_initial_atom_does_not_synthesize_another_part_pass():
    case, setup, parts = fixture()
    row = parts["physical"]["action_checks"]["E0001"]
    row.update(status="unknown", required_revision="")
    row["preconditions"] = [{"entity_id": "slip", "state_key": "open", "actual_value": None,
        "expected_value": True, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert validate_part(case, setup, parts, "physical")["status"] == "halt_review_uncertain"
    assert validate_bundle(case, setup, parts)["status"] == "halt_review_uncertain"


def test_source_quote_is_checked_before_a_part_claims_pass():
    case, setup, parts = fixture()
    next(iter(parts["semantic"]["goal_checks"].values()))["evidence"][0]["quote"] = "不存在的正文"
    assert not validate_part(case, setup, parts, "semantic")["valid"]


def test_independent_context_identities_cannot_be_collapsed():
    case, setup, parts = fixture()
    assert not split.validate_bundle(split.build_review_bundle(**{
        "native_semantic_review": parts["semantic"], "native_physical_review": parts["physical"]}), *case[:4],
        semantic_context_sha256=CONTEXTS["semantic"], physical_context_sha256=CONTEXTS["semantic"], opening_setup=setup)["accepted"]


def test_validation_does_not_rewrite_parts_or_inputs():
    case, setup, parts = fixture()
    digest = split.reviews.base.base.prior.digest
    before = digest([*case, setup, parts])
    assert validate_bundle(case, setup, parts)["accepted"]
    assert before == digest([*case, setup, parts])


@pytest.mark.parametrize("relation,expected", [("new_story", "text_ready_for_director"),
    ("same_story", "halt_same_story_prior_allowance_exhausted"), ("unknown", "halt_prior_story_relation_unknown")])
def test_prior_story_guard_remains_required_in_semantic_part(relation, expected):
    case, setup, parts = fixture()
    old = split.reviews.base.base
    case[1]["prior_story_scope"] = {"full_prior_script": {"premise": "另一旧故事", "beats": []}, "director_remaining": 0}
    entries = old.prior.contract.evidence_catalog(case[0])
    ref = next(iter(entries))
    for part in parts:
        parts[part]["brief_sha256"] = old.prior.digest(case[1])
    parts["semantic"]["prior_story_relation"] = {"prior_scope_sha256": old.prior.digest(case[1]["prior_story_scope"]),
        "relation": relation, "reason": "离线范围判定，只测试不能重领旧额度。",
        "current_evidence": [{"source_ref": ref, "quote": entries[ref]["quote"]}]}
    assert "prior_story_relation" in split.part_table_contract("semantic", *case[:3])["required_tables"]
    assert "prior_story_relation" not in split.part_table_contract("physical", *case[:3])["required_tables"]
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and result["status"] == expected
    if relation != "new_story":
        next(iter(parts["semantic"]["goal_checks"].values())).update(status="fail", required_revision="旧范围失败不能重领额度。")
        parts["semantic"]["revision_target"] = "plan"
        partial = validate_part(case, setup, parts, "semantic")
        assert partial["revision_dispatch_blocked"] and not partial["requires_new_goal_plan"]
        stopped = validate_bundle(case, setup, parts)
        assert stopped["valid"] and stopped["status"] == expected and not stopped["accepted"]
        assert stopped["revision_dispatch_blocked"] and not stopped["requires_new_goal_plan"]
    parts["semantic"].pop("prior_story_relation")
    assert not validate_part(case, setup, parts, "semantic")["valid"]


def test_real_552_cannot_become_accepted_parts_from_a_header_preview():
    path, native, script, views, legal = real_552()
    before = path.read_bytes()
    parts = {}
    for part in split.PART_TABLES:
        schema = split.build_part_schema(part, script, views["brief"], views["plan"], legal,
            context_sha256=CONTEXTS[part], goal_contract=views["goal"], opening_setup=views["opening_setup"])
        # Diagnostic memory projection only; never stored as original native
        # parts or adopted. Preserve all actual nonzero rows and their faults.
        parts[part] = {key: deepcopy(native[key]) for key in schema["properties"] if key in native}
        parts[part].update(schema=split.VERSION, part=part, context_sha256=CONTEXTS[part], revision_target="none")
    semantic = split.validate_part(parts["semantic"], "semantic", script, views["brief"], views["plan"], legal,
        context_sha256=CONTEXTS["semantic"], goal_contract=views["goal"], opening_setup=views["opening_setup"])
    physical = split.validate_part(parts["physical"], "physical", script, views["brief"], views["plan"], legal,
        context_sha256=CONTEXTS["physical"], goal_contract=views["goal"], opening_setup=views["opening_setup"])
    assert not semantic["valid"] and not semantic["accepted"]
    assert "own actual dialogue reference" in semantic["findings"][0]["reason"]
    assert parts["semantic"]["fact_checks"]["CC_CTA"]["status"] == "unknown"
    assert not physical["valid"] and not physical["accepted"]
    assert path.read_bytes() == before
