"""Offline P1 composition of contracts, scene rules, adjudication and routing.

No model client, production claim, media action or final handoff is created.
Native-evidence flags in a diagnostic bundle are caller assertions: production
must obtain them from its own frozen request/response verifier in P2.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json

from . import novel_logic_contracts_v4 as contracts
from .novel_logic_adjudication_v4 import evaluate_gate
from .novel_scene_logic_v4 import analyze_scene_ledger

VERSION = "novel_logic_workflow/v4"


def _candidate_issue(candidate):
    """Compile a rule candidate as unresolved, never a confirmed fact."""
    encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    identity = "scene-rule-" + candidate["candidate_id"]
    return {
        "issue_id": identity, "root_cause_id": candidate["root_cause_id"],
        "origin_candidate_id": candidate["candidate_id"],
        "dimensions": ["causality", "space_gaze_action"],
        "event_ids": list(candidate["event_ids"]),
        "evidence": [encoded],
        "reasonable_explanations": [
            "The extracted states, event identity or continuity annotation may be wrong; verify the full context."],
        "counterevidence": [],
        "impact": "A declared continuous scene has incompatible explicit states; verify before delivery.",
        "severity": "major", "severity_certainty": "unknown",
        "finding_status": "unresolved", "blocking": False,
    }


def evaluate_bundle(bundle):
    """Compose the actual P1 modules for a declared diagnostic bundle.

    Even a domain ``pass`` remains an offline diagnostic, not a persisted
    text_ready_for_director or human approval.  Scene candidates discovered
    after a native pass feed the same issue gate as the review's issues.
    """
    bundle = bundle if isinstance(bundle, dict) else {}
    source, draft = bundle.get("source_binding"), bundle.get("draft_binding")
    ledger = bundle.get("scene_ledger")
    errors = contracts.validate_scene_ledger(
        ledger, expected_source_binding=source, expected_draft_binding=draft)
    if errors:
        analysis = {"status": "contract_invalid", "candidates": [],
                    "retained_ambiguities": [], "contract_errors": errors}
    else:
        analysis = analyze_scene_ledger(ledger)
    candidates = [_candidate_issue(candidate) for candidate in analysis["candidates"]]
    decision = evaluate_gate(
        source_binding=source, draft_binding=draft, review=bundle.get("review"),
        scene_ledger=ledger, adjudication=bundle.get("adjudication"),
        capacity=bundle.get("capacity"), evidence=bundle.get("evidence"),
        require_scene_ledger=True, additional_issues=candidates, scene_analysis=analysis,
    )
    return {
        "schema_version": VERSION, "mode": "offline_diagnostic",
        "scene_analysis": analysis, "scene_candidate_issues": candidates,
        "gate": decision,
        "evidence_trust": "Caller-supplied assertions; no native verifier or production admission in this entry.",
        "production_dispatch_allowed": False, "production_handoff_created": False,
        "new_provider_requests": 0, "new_media_requests": 0,
        "human_approved": False, "semantic_quality_validated": False,
    }


def evaluate_corpus(corpus):
    """Evaluate frozen explicit-state rule fixtures, with split denominators.

    This intentionally does not report free-text semantic recall/precision or
    claim that machine-created narrative labels are independent human gold.
    """
    if not isinstance(corpus, dict) or corpus.get("schema_version") != "novel_logic_rule_corpus/v1":
        raise ValueError("Unsupported frozen corpus")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Corpus must contain labeled cases")
    rows, splits, ids = [], {}, set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Case must be an object")
        identity = case.get("case_id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Case IDs must be nonempty and unique")
        ids.add(identity)
        split = case.get("split")
        if split not in ("development", "holdout"):
            raise ValueError("Every case needs a frozen development/holdout split")
        if type(case.get("expected_candidate")) is not bool or not case.get("label_basis"):
            raise ValueError("Every case needs a predeclared truth label and basis")
        errors = contracts.validate_scene_ledger(case.get("scene_ledger"))
        analysis = (analyze_scene_ledger(case["scene_ledger"]) if not errors
                    else {"candidates": [], "retained_ambiguities": []})
        found = bool(analysis["candidates"])
        analysis_errors = analysis.get("errors", [])
        analysis_complete = analysis.get("status") == "analysis_complete"
        correct = found == case["expected_candidate"] and not errors and analysis_complete and not analysis_errors
        counts = splits.setdefault(split, Counter())
        counts["cases"] += 1
        counts["expected_candidates" if case["expected_candidate"] else "expected_non_candidates"] += 1
        counts["correct"] += int(correct)
        counts["missed_candidates"] += int(case["expected_candidate"] and not found)
        counts["false_candidates"] += int(not case["expected_candidate"] and found)
        counts["contract_failures"] += int(bool(errors))
        counts["analysis_failures"] += int(not analysis_complete or bool(analysis_errors))
        counts["cases_with_retained_ambiguity"] += int(bool(analysis["retained_ambiguities"]))
        rows.append({"case_id": identity, "story_id": case.get("story_id"), "split": split,
                     "expected_candidate": case["expected_candidate"], "found_candidate": found,
                     "correct": correct, "contract_errors": errors,
                     "analysis_errors": analysis_errors,
                     "candidate_count": len(analysis["candidates"]),
                     "retained_ambiguity_count": len(analysis["retained_ambiguities"])})
    story_splits = {}
    pair_groups = {}
    for case in cases:
        story, pair = case.get("story_id"), case.get("pair_id")
        if not isinstance(story, str) or not story or not isinstance(pair, str) or not pair:
            raise ValueError("Each case needs a story and pair ID")
        story_splits.setdefault(story, set()).add(case["split"])
        pair_groups.setdefault(pair, []).append(case)
    if any(len(value) != 1 for value in story_splits.values()):
        raise ValueError("Story leakage across development and holdout")
    if any(len(value) != 2 or {item["expected_candidate"] for item in value} != {True, False}
           for value in pair_groups.values()):
        raise ValueError("Each frozen pair must have one positive and one control")
    corpus_digest = hashlib.sha256(json.dumps(corpus, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return {"schema_version": VERSION, "mode": "explicit_state_rule_benchmark", "corpus_sha256": corpus_digest,
            "status": "fixtures_passed" if all(row["correct"] for row in rows) else "fixture_failures",
            "cases": len(rows), "pairs": len(pair_groups), "stories": len(story_splits),
            "split_counts": {key: dict(value) for key, value in splits.items()}, "results": rows,
            "label_provenance": deepcopy(corpus.get("label_provenance")),
            "semantic_quality_validated": False, "new_provider_requests": 0,
            "retention_note": "Retained diagnostics include unasserted first-event continuity and other unassessed conditions; counts are not a semantic unknown rate.",
            "limitation": "Synthetic explicit-state rule fixtures; story holdout is not unseen natural-language evaluation."}
