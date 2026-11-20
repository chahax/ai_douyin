"""Actual474 source provenance protocol properties; no new writer/API calls."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.content_factory import creative_autonomous_text_contract_v13 as contract
from tests.test_creative_autonomous_text_pipeline_v12 import read, codes
from tests.test_creative_autonomous_text_pipeline_v10 import adjudication_for, subset

PROJECT = Path(__file__).resolve().parents[1]
ROOT12 = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_12"


def actual_474():
    brief = read(ROOT12 / "INPUT.json")["brief"]
    plan = read(ROOT12 / "SCENE_PLAN.json")
    script = contract.compile_script(read(ROOT12 / "call_471_whole_draft_05.json")["output"], brief)
    review = read(ROOT12 / "call_472_whole_review_05.json")["output"]
    audit = read(ROOT12 / "call_473_literal_audit_05.json")["output"]
    extract = read(ROOT12 / "call_474_factual_scope_extract_05.json")["output"]
    scope = read(ROOT12 / "SOURCE_FACT_SCOPE.json")
    temporal = read(ROOT12 / "SOURCE_TEMPORAL_SCOPE.json")
    return brief, script, plan, review, audit, extract, scope, temporal


def claim(extract, id_):
    return next(row for table in extract["category_extracts"] for row in table["claims"] if row["id"] == id_)


def test_actual474_public_wire_and_local_source_acceptance_match_without_changing_native_result():
    brief, script, _, _, _, extract, scope, _ = actual_474()
    before = deepcopy((script, extract, scope))
    contract.base._validate_schema(contract.build_fact_scope_schema(script, brief, scope), extract, "actual474")
    result = contract.validate_fact_scope_extract(extract, script, brief, scope)
    assert result["complete"] is True
    assert (script, extract, scope) == before
    assert read(ROOT12 / "call_474_factual_scope_extract_05.json")["status"] == "contract_rejected"


@pytest.mark.parametrize("source_kind", ["allowance_value", "source_quotes", "source_fact"])
def test_same_allowance_id_can_provenance_cite_frozen_value_quote_or_related_source_fact(source_kind):
    brief, script, _, _, _, extract, scope, _ = actual_474()
    allowance_id = "A8" if source_kind == "source_fact" else "A6"
    allowance = next(row for row in scope["allowed_claims"] if row["id"] == allowance_id)
    quote = allowance["value"] if source_kind == "allowance_value" else allowance["source_quotes"][0]["quote"]
    if source_kind == "source_fact":
        quote = next(row["text"] for row in brief["facts"] if row["id"] == allowance["source_fact_ids"][0])
    row = claim(extract, "C-BP-04" if source_kind == "source_fact" else "C-FU-02")
    row["source_alignment"]["source_attribute_quote"] = quote
    semantic_before = deepcopy(row)
    assert contract.validate_fact_scope_extract(extract, script, brief, scope)["complete"]
    assert row == semantic_before


@pytest.mark.parametrize("change", ["wrong_category", "cross_fact", "unregistered_same_fact", "paraphrase", "wrong_script_sha", "wrong_scope_sha"])
def test_provenance_widening_never_accepts_another_category_fact_paraphrase_or_binding(change):
    brief, script, _, _, _, extract, scope, _ = actual_474()
    row = claim(extract, "C-FU-02")
    if change == "wrong_category": row["source_alignment"]["allowance_id"] = "A8"
    elif change == "cross_fact": row["source_alignment"]["source_attribute_quote"] = brief["facts"][0]["text"]
    elif change == "unregistered_same_fact": row["source_alignment"]["source_attribute_quote"] = "先公司办理立场劝签；小林发现原因与真实决定冲突、质问后拒绝。"
    elif change == "paraphrase": row["source_alignment"]["source_attribute_quote"] = "周姐私下请求小林帮忙签完好交差。"
    elif change == "wrong_script_sha": extract["script_sha256"] = "0" * 64
    else: extract["scope_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        contract.validate_fact_scope_extract(extract, script, brief, scope)


def test_new_quote_acceptance_does_not_override_actual_literal_paper_transfer_failure():
    brief, script, plan, review, audit, extract, scope, temporal = actual_474()
    assert all(row["status"] == "pass" for row in review["criteria"])
    verdict = adjudication_for(extract, script, brief, scope)
    before = deepcopy((extract, verdict, audit, script))
    result = contract.combine_temporal_decisions(review, audit, extract, verdict, script, brief, plan, scope, temporal)
    assert result["status"] == "needs_whole_revision"
    assert {"FACT_F4", "SOURCE_EVENT_SO9", "INITIAL_PROP_pen"}.issubset(codes(result))
    assert (extract, verdict, audit, script) == before
    # Pen reference-frame mismatch stays documented/pending; this test does not
    # certify it as a true visual error. F4's extra physical transfer is explicit.
    assert read(ROOT12 / "STATE.json")["status"] == "halt_contract_rejected"


def test_only_unknown_adjudication_cannot_become_ready_after_source_quote_acceptance():
    brief, script, _, _, _, extract, scope, _ = actual_474()
    extract = subset(extract, "C-FU-01")
    verdict = adjudication_for(extract, script, brief, scope)
    verdict["findings"][0].update(disposition="unknown", basis_kind="uncertain", source_attribute_type="unknown")
    result = contract.decide_adjudication(verdict, extract, script, brief, scope)
    assert result["status"] == "halt_review_uncertain" and result["uncertainties"]
