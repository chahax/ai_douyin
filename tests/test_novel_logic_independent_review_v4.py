"""Independent adversarial P1 acceptance; no service dispatch or production edits."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import novel_logic_contracts_v4 as contracts
from src.content_factory.novel_logic_workflow_v4 import evaluate_bundle


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/novel_logic_v4/rule_corpus_v1.json"


def example():
    ledger = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"][0]["scene_ledger"]
    source, draft = ledger["header"]["source_binding"], ledger["header"]["draft_binding"]
    review = {"header": {**ledger["header"], "artifact_id": "independent-review"},
              "provider": "deepseek", "native_response_ref": "offline:independent-review",
              "native_verdict": "pass", "whole_text_reviewed": True,
              "source_complete": True, "draft_complete": True, "issues": [],
              "checks": [{"dimension": dimension, "checked": True,
                          "assessment": "Offline declared scope only.", "issue_ids": []}
                         for dimension in contracts.REVIEW_DIMENSIONS]}
    evidence = {"status": "complete", "usage_known": True, "finish_reason": "stop",
                "identity_verified": True, "files_verified": True, "whole_text_verified": True,
                "review_payload_verified": True, "native_provider": "deepseek",
                "source_binding": source, "draft_binding": draft,
                "review_artifact_id": review["header"]["artifact_id"],
                "native_response_ref": review["native_response_ref"], "native_verdict": "pass"}
    return {"source_binding": source, "draft_binding": draft, "scene_ledger": ledger,
            "review": review, "evidence": evidence,
            "capacity": {"per_draft_clarification_limit": 1, "per_draft_clarification_used": 0,
                         "run_clarification_limit": 2, "run_clarification_used": 0,
                         "content_revision_limit": 2, "content_revisions_used": 0,
                         "full_review_limit": 5, "full_reviews_used": 1,
                         "call_limit": 10, "calls_used": 2, "token_limit": None,
                         "tokens_used": 1000, "request_token_reservation": 100}}


def reject_current_candidate(value):
    issue = evaluate_bundle(value)["scene_candidate_issues"][0]
    value["adjudication"] = {
        "header": {**value["review"]["header"], "artifact_id": "independent-adjudication"},
        "review_artifact_id": value["review"]["header"]["artifact_id"],
        "new_issues": [deepcopy(issue)],
        "dispositions": [{"issue_id": issue["issue_id"], "disposition": "rejected",
                          "basis": ["Offline explicit dismissal fixture, not model evidence."],
                          "new_issue_ids": [], "blocking": False}],
    }
    return issue


def test_changed_boundary_cannot_reuse_rejected_candidate_under_same_artifact_headers():
    value = example()
    old_candidate = reject_current_candidate(value)
    assert evaluate_bundle(value)["gate"]["decision"] == "pass"
    # Even if a caller accidentally preserves the declared draft binding, the
    # actual rule candidate changes and its old disposition cannot consume it.
    value["scene_ledger"]["events"][1]["before"][0]["value"] = "sitting"
    result = evaluate_bundle(value)
    assert result["scene_candidate_issues"][0]["issue_id"] != old_candidate["issue_id"]
    assert result["gate"]["next_action"] == "stop"
    assert "scene_candidate_origin_invalid" in result["gate"]["stop_reasons"]


def minor_existence_dispute(*, certainty="confirmed", blocking=False):
    value = example()
    # Remove the independent physical conflict so the only question is whether
    # an already minor wording observation actually exists.
    ledger = value["scene_ledger"]
    ledger["events"][1]["before"][0]["value"] = ledger["events"][0]["after"][0]["value"]
    issue = {"issue_id": "wording-minor", "root_cause_id": "wording-style",
             "dimensions": ["dialogue_naturality"], "event_ids": ["E2"],
             "evidence": ["E2: wording observation, existence disputed"],
             "reasonable_explanations": ["May be intentional characterization."],
             "counterevidence": [], "impact": "Only phrasing; no narrative or staging impact.",
             "severity": "minor", "severity_certainty": certainty,
             "finding_status": "unresolved", "blocking": blocking}
    value["review"]["issues"] = [issue]
    for check in value["review"]["checks"]:
        check["issue_ids"] = [issue["issue_id"]] if check["dimension"] in issue["dimensions"] else []
    value["adjudication"] = {
        "header": {**value["review"]["header"], "artifact_id": "minor-adjudication"},
        "review_artifact_id": value["review"]["header"]["artifact_id"],
        "new_issues": [],
        "dispositions": [{"issue_id": issue["issue_id"], "disposition": "unresolved",
                          "basis": ["Existence disputed; impact independently confirmed minor."],
                          "new_issue_ids": [], "blocking": False}],
    }
    return value


@pytest.mark.parametrize("exhausted", [False, True])
def test_confirmed_minor_impact_with_disputed_existence_needs_no_external_clarification(exhausted):
    value = minor_existence_dispute()
    if exhausted:
        value["capacity"]["calls_used"] = value["capacity"]["call_limit"]
        value["capacity"]["run_clarification_used"] = value["capacity"]["run_clarification_limit"]
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] == "pass"
    assert result["gate"]["next_action"] == "deliver_local"
    assert result["gate"]["requires_new_request"] is False
    assert result["gate"]["issue_groups"][0]["members"][0]["finding_status"] == "unresolved"


@pytest.mark.parametrize("certainty,blocking", [("unknown", False), ("possible", False), ("confirmed", True)])
def test_only_confirmed_nonblocking_minor_impact_can_survive_existence_dispute(certainty, blocking):
    value = minor_existence_dispute(certainty=certainty, blocking=blocking)
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] != "pass"
    assert result["gate"]["next_action"] == "clarify_same_draft"


def test_confirmed_minor_dispute_cannot_replace_native_revise_with_pass():
    value = minor_existence_dispute()
    value["review"]["native_verdict"] = value["evidence"]["native_verdict"] = "revise"
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] != "pass"
    assert result["gate"]["next_action"] == "full_review_same_draft"


def test_dismissal_and_zero_capacity_cannot_turn_native_revise_into_pass():
    value = example()
    reject_current_candidate(value)
    value["review"]["native_verdict"] = value["evidence"]["native_verdict"] = "revise"
    value["capacity"]["calls_used"] = value["capacity"]["call_limit"]
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] != "pass"
    assert result["gate"]["next_action"] == "stop"
    assert result["gate"]["proposed_action"] == "full_review_same_draft"
    assert "call_budget_exhausted" in result["gate"]["stop_reasons"]


@pytest.mark.parametrize("artifact", ["scene_ledger", "review", "adjudication"])
@pytest.mark.parametrize("binding", ["source_binding", "draft_binding"])
def test_one_stale_artifact_cannot_use_current_review_and_candidate_dismissal(artifact, binding):
    value = example()
    reject_current_candidate(value)
    value[artifact]["header"][binding] = "stale:independent-counterexample"
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] != "pass"
    assert result["gate"]["next_action"] == "stop"


def test_third_repeated_fact_does_not_hide_internally_conflicting_sidecar():
    value = example()
    first = value["scene_ledger"]["events"][0]["after"][0]
    conflict = {**deepcopy(first), "value": "kneeling"}
    value["scene_ledger"]["events"][0]["after"].extend([conflict, deepcopy(first)])
    result = evaluate_bundle(value)
    assert result["scene_analysis"]["errors"] == ["INTERNALLY_CONFLICTING_FACT_SET"]
    assert result["gate"]["next_action"] == "stop"
    assert result["gate"]["requires_new_request"] is False


@pytest.mark.parametrize("field", ["status", "usage_known", "finish_reason",
                                  "review_payload_verified", "whole_text_verified"])
def test_unknown_native_evidence_overrides_a_complete_candidate_dismissal(field):
    value = example()
    reject_current_candidate(value)
    value["evidence"][field] = None
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] != "pass"
    assert result["gate"]["next_action"] == "stop"
    assert result["new_provider_requests"] == 0
    assert result["production_dispatch_allowed"] is False


def test_fixture_holdout_is_story_disjoint_but_shares_rule_families():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = corpus["cases"]
    development = {case["story_id"] for case in cases if case["split"] == "development"}
    holdout = {case["story_id"] for case in cases if case["split"] == "holdout"}
    assert development.isdisjoint(holdout)
    assert {case["family"] for case in cases if case["split"] == "development"} == {
        case["family"] for case in cases if case["split"] == "holdout"}
    assert "share rule templates" in corpus["holdout_limitation"]
    assert "no model agreement or human literary gold claim" in corpus["label_provenance"]


def test_existing_v3_replay_reads_without_changing_any_run_file():
    from src.content_factory.novel_logic_replay_v4 import replay_saved_v3

    run = ROOT / "data/novel_adaptation_production/20261017_plaintext_v3/run"
    assert run.is_dir(), "Independent acceptance requires the preserved research run."

    def snapshot():
        return {str(path.relative_to(run)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in run.rglob("*") if path.is_file()}

    before = snapshot()
    result = replay_saved_v3(run)
    assert result["status"] == "saved_evidence_verified"
    assert len(result["pairs"]) == 3
    assert {pair["native_verdict"] for pair in result["pairs"]} == {"revise"}
    assert result["original_calls"] == 20
    assert result["original_reported_tokens"] == 310301
    assert result["original_pending_call"] is None
    assert result["v4_acceptance"] is False
    assert result["new_provider_requests"] == 0
    assert before == snapshot()
