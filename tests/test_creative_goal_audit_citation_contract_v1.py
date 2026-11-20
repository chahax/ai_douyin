"""Synthetic judgments and unchanged real failed review; no quality gold."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jsonschema import ValidationError
from src.content_factory import creative_goal_audit_citation_contract_v1 as contract

ROOT = Path(__file__).resolve().parents[1] / "data/production_trials/goal_context_text_production_20261013/round_03"
CHECKS = ("source_kind_support", "local_result_without_legal_verdict")


def fixture():
    goal = json.loads((ROOT / "goals/native_03.json").read_text(encoding="utf-8"))
    catalog = contract.build_evidence_catalog(goal)
    row = {"status": "pass", "reason": "合成合同判断，不是质量金标", "required_revision": ""}
    audit = {"schema": contract.VERSION, "goal_sha256": contract.digest(goal), "audit_context_sha256": "0" * 64,
        "claim_checks": {claim["id"]: deepcopy(row) for claim in goal["claims"]},
        "goal_checks": {key: {**deepcopy(row), "evidence_refs": [next(iter(catalog))]} for key in CHECKS}}
    return goal, audit, catalog


def validate(goal, audit):
    return contract.validate(audit, goal, context_sha256="0" * 64, goal_checks=CHECKS)


def test_program_owned_citations_resolve_exact_current_native_without_rewriting_audit():
    goal, audit, catalog = fixture()
    before = deepcopy((goal, audit))
    result = validate(goal, audit)
    assert result["valid"] and result["accepted"]
    assert (goal, audit) == before
    assert not result["semantic_truth_deterministically_proven"] and not result["human_approved"]
    for i, claim in enumerate(goal["claims"]):
        assert result["citations"]["claim:" + claim["id"]] == [{"document_path": f"claims.{i}.text", "quote": claim["text"]}]


@pytest.mark.parametrize("alter", ["empty", "missing", "unknown_ref", "invented_path", "pass_revision", "wrong_goal", "wrong_context", "empty_claims"])
def test_incomplete_or_fabricated_evidence_is_rejected_not_locally_repaired(alter):
    goal, audit, _ = fixture()
    row = audit["goal_checks"][CHECKS[0]]
    if alter == "empty": row["evidence_refs"] = []
    elif alter == "missing": row.pop("evidence_refs")
    elif alter == "unknown_ref": row["evidence_refs"] = ["G9999"]
    elif alter == "invented_path": row["document_path"] = "claims[0]"
    elif alter == "pass_revision": row["required_revision"] = "无需修改"
    elif alter == "wrong_goal": audit["goal_sha256"] = "1" * 64
    elif alter == "wrong_context": audit["audit_context_sha256"] = "1" * 64
    elif alter == "empty_claims": audit["claim_checks"] = {}
    before = deepcopy(audit)
    with pytest.raises(ValidationError): validate(goal, audit)
    assert audit == before


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_known_semantic_failure_and_unknown_remain_distinct(status):
    goal, audit, _ = fixture()
    row = audit["goal_checks"][CHECKS[0]]
    row.update(status=status, required_revision="整版规划重建场内后果" if status == "fail" else "")
    result = validate(goal, audit)
    assert result["valid"] and not result["accepted"]
    assert bool(result["findings"]) == (status == "fail")
    assert bool(result["uncertainties"]) == (status == "unknown")


def test_old_537_paths_and_pass_revision_stay_rejected_with_original_bytes():
    path = ROOT / "call_537_goal_audit_03.json"
    before = path.read_bytes()
    old = json.loads(before)["output"]
    goal, _, _ = fixture()
    with pytest.raises(ValidationError): validate(goal, old)
    assert path.read_bytes() == before


def test_every_compiled_goal_evidence_is_exact_native_string_path():
    goal, _, catalog = fixture()
    for row in catalog.values():
        value = goal
        for part in row["document_path"].split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert row["quote"] == value and isinstance(value, str)
