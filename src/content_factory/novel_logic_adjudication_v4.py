"""Framework-independent issue adjudication and routing for novel v4.

This module never dispatches, spends, persists a ledger, or grants media rights.
``evidence`` is an admission result supplied by an independent native-evidence
verifier; model-authored sidecars cannot establish those verification facts.
The returned request action is a proposal that still needs transactional
admission by the caller.  Local delivery means machine text, not user approval.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import novel_logic_contracts_v4 as contracts

VERSION = "novel_logic_adjudication/v4"
_SEVERITY_ORDER = {"minor": 0, "unknown": 1, "major": 2, "blocking": 3}


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def deduplicate_issues(issues: list[dict]) -> list[dict]:
    """Group only explicit equal root IDs; retain every member and its identity.

    Groups are presentation aids, never votes or substitutes for dispositions.
    Repeated reports do not increase severity.  In particular, different issue
    IDs of the same root still each require a traceable disposition.
    """
    if not isinstance(issues, list):
        raise ValueError("issues must be a list")
    seen: set[str] = set()
    groups: dict[str, dict] = {}
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("each issue must be an object")
        issue_id, root = issue.get("issue_id"), issue.get("root_cause_id")
        if not isinstance(issue_id, str) or not issue_id.strip() or issue_id in seen:
            raise ValueError("issue IDs must be nonempty and unique")
        if not isinstance(root, str) or not root.strip():
            raise ValueError("root_cause_id is required; semantic guessing is forbidden")
        severity = issue.get("severity")
        if not isinstance(severity, str) or severity not in _SEVERITY_ORDER:
            raise ValueError("unknown severity value")
        seen.add(issue_id)
        group = groups.setdefault(root, {
            "root_cause_id": root, "issue_ids": [], "dimensions": [],
            "event_ids": [], "severity": severity, "members": [],
        })
        group["issue_ids"].append(issue_id)
        group["members"].append(deepcopy(issue))
        for field in ("dimensions", "event_ids"):
            values = issue.get(field, [])
            if not isinstance(values, list):
                raise ValueError(f"{field} must be a list")
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field} must contain nonempty strings")
                if value not in group[field]:
                    group[field].append(value)
        if _SEVERITY_ORDER[severity] > _SEVERITY_ORDER[group["severity"]]:
            group["severity"] = severity
    return list(groups.values())


def _evidence_errors(evidence: Any, source: str, draft: str, review: dict) -> list[str]:
    evidence = _mapping(evidence)
    errors: list[str] = []
    status = evidence.get("status")
    if status != "complete":
        errors.append(status if isinstance(status, str) and status in {
            "transport_unknown", "usage_unknown", "truncated", "evidence_insufficient",
        } else "evidence_insufficient")
    if evidence.get("usage_known") is not True:
        errors.append("usage_unknown")
    if evidence.get("finish_reason") != "stop":
        finish = evidence.get("finish_reason")
        errors.append("truncated" if isinstance(finish, str) and finish in {
            "length", "max_tokens", "truncated",
        } else "end_state_unknown")
    for field in ("identity_verified", "files_verified", "whole_text_verified", "review_payload_verified"):
        if evidence.get(field) is not True:
            errors.append(f"{field}_missing")
    if evidence.get("native_provider") != "deepseek" or review.get("provider") != "deepseek":
        errors.append("native_provider_mismatch")
    expected = {
        "source_binding": source, "draft_binding": draft,
        "review_artifact_id": _mapping(review.get("header")).get("artifact_id"),
        "native_response_ref": review.get("native_response_ref"),
        "native_verdict": review.get("native_verdict"),
    }
    for field, value in expected.items():
        if not value or evidence.get(field) != value:
            errors.append(f"evidence_{field}_mismatch")
    return list(dict.fromkeys(errors))


def validate_capacity(capacity: Any) -> list[str]:
    """Validate explicit frozen capacities without mutating any counter.

    ``full_review`` counts native whole-text review requests, including combined
    clarification/full review.  ``clarification`` is an additional stage cap on
    those clarification requests, not another service charge.  One combined
    request therefore consumes one total call and both applicable stage caps.
    Content revisions are complete new drafts and never exceed two here.
    """
    if not isinstance(capacity, dict):
        return ["capacity_not_frozen"]
    fields = (
        "per_draft_clarification_limit", "per_draft_clarification_used",
        "run_clarification_limit", "run_clarification_used",
        "content_revision_limit", "content_revisions_used",
        "full_review_limit", "full_reviews_used", "call_limit", "calls_used",
        "tokens_used", "request_token_reservation",
    )
    errors = [f"capacity_invalid:{field}" for field in fields
              if not _nonnegative_int(capacity.get(field))]
    if "token_limit" not in capacity or (capacity["token_limit"] is not None
                                               and not _nonnegative_int(capacity["token_limit"])):
        errors.append("capacity_invalid:token_limit")
    if _nonnegative_int(capacity.get("content_revision_limit")) and capacity["content_revision_limit"] > 2:
        errors.append("capacity_invalid:content_revision_limit")
    if capacity.get("request_token_reservation") == 0:
        errors.append("capacity_invalid:request_token_reservation")
    return list(dict.fromkeys(errors))


def request_capacity_errors(capacity: Any, action: str) -> list[str]:
    """Read-only preflight for exactly one proposed external request.

    Atomic claim/counter acquisition and inherited service budget admission stay
    outside this module.  These checks cannot themselves authorize dispatch.
    """
    errors = validate_capacity(capacity)
    if errors:
        return errors
    if not isinstance(action, str) or action not in {"revise_full_draft", "full_review_same_draft", "clarify_same_draft"}:
        return ["request_action_invalid"]
    if capacity["calls_used"] >= capacity["call_limit"]:
        errors.append("call_budget_exhausted")
    limit = capacity["token_limit"]
    if limit is not None and capacity["tokens_used"] + capacity["request_token_reservation"] > limit:
        errors.append("token_budget_exhausted")
    if action == "revise_full_draft":
        if capacity["content_revisions_used"] >= capacity["content_revision_limit"]:
            errors.append("revision_limit")
    else:
        if capacity["per_draft_clarification_used"] >= capacity["per_draft_clarification_limit"]:
            errors.append("per_draft_clarification_limit")
        if capacity["run_clarification_used"] >= capacity["run_clarification_limit"]:
            errors.append("run_clarification_limit")
        if capacity["full_reviews_used"] >= capacity["full_review_limit"]:
            errors.append("full_review_limit")
    return errors


def _effective_issues(issues: list[dict], dispositions: list[dict]) -> tuple[list[str], list[str], list[str]]:
    by_id = {item["issue_id"]: item for item in dispositions}
    confirmed: list[str] = []
    unresolved: list[str] = []
    errors: list[str] = []
    for issue in issues:
        issue_id = issue["issue_id"]
        disposition = by_id[issue_id]
        state = disposition["disposition"]
        if state == "rejected":
            if disposition["blocking"]:
                errors.append(f"rejected_issue_still_blocking:{issue_id}")
            continue
        # Verification may resolve a candidate's impact, but only by explicit
        # paired fields on its traceable disposition. Preserve the raw issue.
        severity = disposition.get("effective_severity", issue["severity"])
        certainty = disposition.get("effective_severity_certainty", issue["severity_certainty"])
        known_minor = severity == "minor" and certainty == "confirmed"
        # Uncertain existence does not imply uncertain impact. If verification
        # has established an issue can only be minor, retaining its unresolved
        # existence must not spend a clarification request or block native pass.
        if known_minor and not issue["blocking"] and not disposition["blocking"]:
            continue
        if state == "confirmed" and certainty == "confirmed":
            if severity in {"major", "blocking"} or issue["blocking"] or disposition["blocking"]:
                confirmed.append(issue_id)
            elif not known_minor:
                unresolved.append(issue_id)
        else:
            # A possibly significant issue cannot become minor by changing the
            # disposition label or leaving the boolean blocking flag false.
            unresolved.append(issue_id)
    return confirmed, unresolved, errors


def _scene_candidate_errors(analysis: dict, issues: list[dict], source: str, draft: str) -> list[str]:
    """Require one traceable issue per independent scene-rule candidate.

    Candidate identity includes source and draft at extraction time. Matching
    an origin ID alone is insufficient when its root/event references changed.
    This prevents an adapter omission, duplicate settlement, or stale candidate
    from erasing an issue merely because the native review originally passed.
    """
    candidates = analysis.get("candidates", [])
    if not isinstance(candidates, list):
        return ["scene_candidates_contract_invalid"]
    index: dict[str, dict] = {}
    errors: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            errors.append("scene_candidates_contract_invalid")
            continue
        identity = candidate.get("candidate_id")
        if not isinstance(identity, str) or not identity.strip() or identity in index:
            errors.append("scene_candidate_identity_invalid")
            continue
        index[identity] = candidate
        if candidate.get("source_binding") != source or candidate.get("draft_binding") != draft:
            errors.append("scene_candidate_binding_invalid")
        root, events = candidate.get("root_cause_id"), candidate.get("event_ids")
        if (not isinstance(root, str) or not root.strip() or not isinstance(events, list)
                or not events or not all(isinstance(item, str) and item.strip() for item in events)):
            errors.append("scene_candidates_contract_invalid")
    mapped: dict[str, list[dict]] = {identity: [] for identity in index}
    for issue in issues:
        identity = issue.get("origin_candidate_id")
        if identity is None:
            continue
        if not isinstance(identity, str) or identity not in index:
            errors.append("scene_candidate_origin_invalid")
            continue
        mapped[identity].append(issue)
    for identity, candidate in index.items():
        matches = mapped[identity]
        if not matches:
            errors.append("scene_candidate_unaccounted")
        elif len(matches) != 1:
            errors.append("scene_candidate_duplicate_mapping")
        else:
            issue = matches[0]
            events = candidate.get("event_ids")
            if (issue["root_cause_id"] != candidate.get("root_cause_id")
                    or not isinstance(events, list)
                    or not all(isinstance(item, str) for item in events)
                    or set(issue["event_ids"]) != set(events)):
                errors.append("scene_candidate_mapping_mismatch")
    return list(dict.fromkeys(errors))


def evaluate_gate(*, source_binding: str, draft_binding: str, review: Any,
                  scene_ledger: Any, adjudication: Any = None, capacity: Any = None,
                  evidence: Any = None, require_scene_ledger: bool = True,
                  additional_issues: Any = None, scene_analysis: Any = None) -> dict:
    """Calculate a machine-text decision and the next bounded action.

    Technical/evidence failures always stop.  A native ``revise`` never becomes
    a local pass, even when every issue is rejected.  Confirmed major content
    routes to a complete new draft; material uncertainty routes to combined
    same-draft clarification and whole-text review.  Existing valid native pass
    is deliverable locally even when all request capacities are exhausted.
    """
    review = _mapping(review)
    result = {
        "schema_version": VERSION, "source_binding": source_binding,
        "draft_binding": draft_binding,
        "review_artifact_id": _mapping(review.get("header")).get("artifact_id"),
        "decision": "needs_attention", "next_action": "stop",
        "stop_reasons": [], "reasons": [], "requires_new_request": False,
        "blocking_issue_ids": [], "unresolved_issue_ids": [], "issue_groups": [],
    }
    bindings = {"expected_source_binding": source_binding, "expected_draft_binding": draft_binding}
    technical: list[str] = []
    if not isinstance(source_binding, str) or not source_binding.strip():
        technical.append("source_binding_invalid")
    if not isinstance(draft_binding, str) or not draft_binding.strip():
        technical.append("draft_binding_invalid")
    review_errors = contracts.validate_full_review(review, **bindings)
    if review_errors:
        technical.append("full_review_contract_invalid")
        result["contract_errors"] = {"full_review": review_errors}
    if _mapping(review.get("header")).get("status") != "complete":
        technical.append("full_review_not_complete")
    if type(require_scene_ledger) is not bool:
        technical.append("scene_ledger_requirement_invalid")
    if require_scene_ledger:
        ledger_errors = contracts.validate_scene_ledger(scene_ledger, **bindings)
        if ledger_errors:
            technical.append("scene_ledger_contract_invalid")
            result.setdefault("contract_errors", {})["scene_ledger"] = ledger_errors
        if _mapping(_mapping(scene_ledger).get("header")).get("status") != "complete":
            technical.append("scene_ledger_not_complete")
    if scene_analysis is not None:
        analysis = _mapping(scene_analysis)
        if analysis.get("status") != "analysis_complete" or analysis.get("errors") != []:
            technical.append("scene_analysis_failed")
        if analysis.get("source_binding") != source_binding or analysis.get("draft_binding") != draft_binding:
            technical.append("scene_analysis_binding_invalid")
    technical.extend(_evidence_errors(evidence, source_binding, draft_binding, review))
    if technical:
        result["stop_reasons"] = list(dict.fromkeys(technical))
        result["reasons"] = ["Required native evidence or current-draft auxiliary artifacts are not verified."]
        return result

    issues = deepcopy(review["issues"])
    if adjudication is not None:
        adjudication_errors = contracts.validate_adjudication(adjudication, review=review, **bindings)
        if adjudication_errors:
            result["stop_reasons"] = ["adjudication_contract_invalid"]
            result["contract_errors"] = {"adjudication": adjudication_errors}
            return result
        if adjudication["header"]["status"] != "complete":
            result["stop_reasons"] = ["adjudication_not_complete"]
            return result
        issues.extend(deepcopy(adjudication["new_issues"]))
        dispositions = deepcopy(adjudication["dispositions"])
    elif issues:
        result["stop_reasons"] = ["adjudication_missing"]
        result["reasons"] = ["Every reported issue needs an individual traceable disposition."]
        return result
    else:
        dispositions = []
    # Independent deterministic checks may discover candidates after the native
    # review.  Preserve them separately and never manufacture a confirmed truth.
    # Missing dispositions for these fresh candidates mean unresolved, not pass.
    additional_issues = [] if additional_issues is None else additional_issues
    if not isinstance(additional_issues, list):
        result["stop_reasons"] = ["additional_issues_contract_invalid"]
        return result
    known = {issue["issue_id"]: issue for issue in issues}
    for index, issue in enumerate(additional_issues):
        issue_errors = contracts.validate_issue(issue, location=f"$.additional_issues[{index}]")
        if issue_errors:
            result["stop_reasons"] = ["additional_issues_contract_invalid"]
            result["contract_errors"] = {"additional_issues": issue_errors}
            return result
        issue_id = issue["issue_id"]
        if issue_id in known:
            if issue != known[issue_id]:
                result["stop_reasons"] = ["additional_issue_identity_conflict"]
                return result
            continue
        issues.append(deepcopy(issue))
        known[issue_id] = issue
        dispositions.append({"issue_id": issue_id, "disposition": "unresolved",
                             "basis": ["Independent candidate requires explicit verification."],
                             "new_issue_ids": [], "blocking": False})
    if require_scene_ledger:
        event_ids = {event["event_id"] for event in scene_ledger["events"]}
        reference_errors = []
        for index, issue in enumerate(issues):
            reference_errors.extend(contracts.validate_issue(issue, location=f"$.issues[{index}]", event_ids=event_ids))
        if reference_errors:
            result["stop_reasons"] = ["issue_event_binding_invalid"]
            result["contract_errors"] = {"issues": reference_errors}
            return result
    if scene_analysis is not None:
        candidate_errors = _scene_candidate_errors(scene_analysis, issues, source_binding, draft_binding)
        if candidate_errors:
            result["stop_reasons"] = candidate_errors
            return result
    try:
        result["issue_groups"] = deduplicate_issues(issues)
    except ValueError as exc:
        result["stop_reasons"] = ["issue_identity_invalid"]
        result["reasons"] = [str(exc)]
        return result
    confirmed, unresolved, errors = _effective_issues(issues, dispositions)
    result["blocking_issue_ids"], result["unresolved_issue_ids"] = confirmed, unresolved
    if errors:
        result["stop_reasons"] = errors
        return result

    if unresolved:
        action = "clarify_same_draft"
        result["reasons"] = ["Potentially material issues remain unresolved; do not downgrade them to minor."]
    elif confirmed:
        result["decision"] = "revise"
        action = "revise_full_draft"
        result["reasons"] = ["Confirmed material content issues require a complete new draft and new full review."]
    elif review["native_verdict"] == "revise":
        action = "full_review_same_draft"
        result["reasons"] = ["Adjudication does not replace DeepSeek native full-text pass; preserve the original revise."]
    else:
        result.update(decision="pass", next_action="deliver_local",
                      reasons=["Current source/draft has verified DeepSeek native pass and no material unresolved issue."])
        return result

    result["proposed_action"] = action
    capacity_errors = request_capacity_errors(capacity, action)
    if capacity_errors:
        result["stop_reasons"] = capacity_errors
        return result
    result["next_action"] = action
    result["requires_new_request"] = True
    return result
