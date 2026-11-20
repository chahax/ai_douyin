"""Primary cross-module checks of the P1 composition, not literary quality."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.content_factory import novel_logic_contracts_v4 as contracts
from src.content_factory.novel_logic_workflow_v4 import evaluate_bundle, evaluate_corpus

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/novel_logic_v4/rule_corpus_v1.json"


def corpus():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def bundle(*, conflict=False):
    case = corpus()["cases"][0 if conflict else 1]
    ledger = deepcopy(case["scene_ledger"])
    source, draft = ledger["header"]["source_binding"], ledger["header"]["draft_binding"]
    head = {**ledger["header"], "artifact_id": "R1"}
    review = {"header": head, "provider": "deepseek", "native_response_ref": "offline-native-1",
              "native_verdict": "pass", "whole_text_reviewed": True, "source_complete": True,
              "draft_complete": True, "issues": [],
              "checks": [{"dimension": item, "checked": True, "assessment": "Explicit offline fixture.", "issue_ids": []}
                         for item in contracts.REVIEW_DIMENSIONS]}
    evidence = {"status": "complete", "usage_known": True, "finish_reason": "stop",
                "identity_verified": True, "files_verified": True, "whole_text_verified": True,
                "review_payload_verified": True, "native_provider": "deepseek",
                "source_binding": source, "draft_binding": draft, "review_artifact_id": "R1",
                "native_response_ref": "offline-native-1", "native_verdict": "pass"}
    return {"source_binding": source, "draft_binding": draft, "scene_ledger": ledger,
            "review": review, "evidence": evidence,
            "capacity": {"per_draft_clarification_limit": 1, "per_draft_clarification_used": 0,
                         "run_clarification_limit": 2, "run_clarification_used": 0,
                         "content_revision_limit": 2, "content_revisions_used": 0,
                         "full_review_limit": 5, "full_reviews_used": 1,
                         "call_limit": 10, "calls_used": 2, "token_limit": 10000,
                         "tokens_used": 1000, "request_token_reservation": 100}}


def settle(value, candidate, *, disposition, severity=None):
    result = {"header": {**value["review"]["header"], "artifact_id": "A1"},
              "review_artifact_id": "R1", "new_issues": [deepcopy(candidate)],
              "dispositions": [{"issue_id": candidate["issue_id"], "disposition": disposition,
                                "basis": ["Compared the full source, draft and both event phases."],
                                "new_issue_ids": [], "blocking": False}]}
    if severity:
        result["dispositions"][0].update(effective_severity=severity, effective_severity_certainty="confirmed")
    return result


def test_composition_preserves_inputs_and_does_not_create_production_acceptance():
    value = bundle()
    before = deepcopy(value)
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] == "pass"
    assert result["production_dispatch_allowed"] is False
    assert result["production_handoff_created"] is False
    assert result["human_approved"] is False
    assert result["new_provider_requests"] == 0
    assert value == before


def test_scene_candidate_after_native_pass_enters_same_gate_as_unresolved():
    result = evaluate_bundle(bundle(conflict=True))
    assert len(result["scene_candidate_issues"]) == 1
    issue = result["scene_candidate_issues"][0]
    assert issue["severity_certainty"] == "unknown"
    assert issue["finding_status"] == "unresolved"
    assert result["gate"]["next_action"] == "clarify_same_draft"
    assert issue["issue_id"] in result["gate"]["unresolved_issue_ids"]


@pytest.mark.parametrize("disposition,severity,action", [
    ("confirmed", "major", "revise_full_draft"),
    ("advisory", "minor", "deliver_local"),
    ("rejected", None, "deliver_local"),
])
def test_unmodified_candidate_can_be_explicitly_verified(disposition, severity, action):
    value = bundle(conflict=True)
    candidate = evaluate_bundle(value)["scene_candidate_issues"][0]
    value["adjudication"] = settle(value, candidate, disposition=disposition, severity=severity)
    original = deepcopy(value)
    result = evaluate_bundle(value)
    assert result["gate"]["next_action"] == action
    assert value == original
    assert result["scene_candidate_issues"][0] == candidate


def test_structurally_conflicting_ledger_cannot_pass_even_with_native_pass():
    value = bundle(conflict=True)
    fact = deepcopy(value["scene_ledger"]["events"][0]["after"][0])
    fact["value"] = "sitting"
    value["scene_ledger"]["events"][0]["after"].append(fact)
    result = evaluate_bundle(value)
    assert result["scene_analysis"]["status"] == "needs_attention"
    assert result["gate"]["decision"] == "needs_attention"
    assert result["gate"]["next_action"] == "stop"
    assert result["gate"]["requires_new_request"] is False


def test_checker_error_is_not_an_empty_healthy_ledger():
    value = bundle()
    value["scene_ledger"]["events"][0]["event_id"] = "unknown"
    value["scene_ledger"]["events"][1]["referent_event_id"] = "unknown"
    value["scene_ledger"]["events"][1]["context"]["continuity_from_event_id"] = "unknown"
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] == "needs_attention"
    assert result["gate"]["next_action"] == "stop"


def test_old_draft_ledger_is_rejected_and_evidence_flags_are_never_filled_in():
    value = bundle()
    value["scene_ledger"]["header"]["draft_binding"] = "older-draft"
    assert evaluate_bundle(value)["gate"]["decision"] == "needs_attention"
    value = bundle()
    del value["evidence"]
    assert evaluate_bundle(value)["gate"]["decision"] == "needs_attention"


def test_zero_capacity_only_stops_new_requests_not_local_diagnostics():
    value = bundle()
    value["capacity"]["calls_used"] = value["capacity"]["call_limit"]
    assert evaluate_bundle(value)["gate"]["next_action"] == "deliver_local"
    value["review"]["native_verdict"] = value["evidence"]["native_verdict"] = "revise"
    result = evaluate_bundle(value)
    assert result["gate"]["decision"] != "pass"
    assert "call_budget_exhausted" in result["gate"]["stop_reasons"]


def test_frozen_rules_cover_both_sides_without_claiming_semantic_quality():
    result = evaluate_corpus(corpus())
    assert result["status"] == "fixtures_passed"
    assert (result["cases"], result["pairs"], result["stories"]) == (120, 60, 6)
    assert result["split_counts"]["holdout"]["cases"] == 40
    assert result["semantic_quality_validated"] is False
    assert all(row["correct"] for row in result["results"])


def test_evaluator_rejects_story_leakage_and_missing_controls():
    value = corpus()
    value["cases"][0]["split"] = "holdout"
    with pytest.raises(ValueError, match="Story leakage"):
        evaluate_corpus(value)
    value = corpus()
    value["cases"].pop()
    with pytest.raises(ValueError, match="Each frozen pair"):
        evaluate_corpus(value)


def test_real_cli_connects_modules_and_preserves_existing_output(tmp_path):
    source, output = tmp_path / "bundle.json", tmp_path / "decision.json"
    source.write_text(json.dumps(bundle(conflict=True)), encoding="utf-8")
    args = [sys.executable, str(ROOT / "scripts/run_novel_logic_v4.py"), "diagnose",
            "--input", str(source), "--output", str(output)]
    first = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=30)
    assert first.returncode == 0, first.stderr.decode("utf-8")
    data = output.read_bytes()
    assert json.loads(data)["gate"]["next_action"] == "clarify_same_draft"
    second = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=30)
    assert second.returncode == 1
    assert output.read_bytes() == data


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}'])
def test_cli_rejects_ambiguous_json_without_dispatch(tmp_path, text):
    source = tmp_path / "invalid.json"
    source.write_text(text, encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_novel_logic_v4.py"),
                             "diagnose", "--input", str(source)], cwd=ROOT, capture_output=True, timeout=30)
    assert result.returncode == 1
    assert json.loads(result.stdout)["production_dispatch_allowed"] is False


def test_cli_replay_refuses_output_inside_old_run(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/run_novel_logic_v4.py"),
                             "replay-v3", "--run-dir", str(tmp_path), "--output", str(tmp_path / "new.json")],
                            cwd=ROOT, capture_output=True, timeout=30)
    assert result.returncode == 1
    assert not (tmp_path / "new.json").exists()
