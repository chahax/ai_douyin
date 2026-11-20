"""Framework-independent contracts for novel logic sidecars, without dispatch.

These validators check declared fields and identity bindings, not the truth of
natural-language content or native service evidence. Native MiniMax text stays
authoritative and is never reformatted here. A malformed auxiliary artifact is
a technical failure, not a request for the writer to rewrite its screenplay.

All artifacts have ``header`` with artifact_id, schema_version, source_binding,
draft_binding, producer_version, parent_artifact_ids, and status. Bindings are
opaque program-assigned strings; a matching string is not proof of file hashes.
Unknown extension fields are preserved (nothing is mutated). No JSON schema or
LLM framework dependency is required.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

VERSION = "novel_logic_contracts/v4"
REVIEW_DIMENSIONS = (
    "mainline_and_motivation", "causality", "character_identity",
    "space_gaze_action", "emotion_windows", "dialogue_naturality",
    "shootability", "completeness", "timing",
)
ARTIFACT_STATUSES = ("complete", "incomplete", "invalidated")
NARRATIVE_LAYERS = ("background", "summary", "performance", "closing_summary")
EVENT_RELATIONS = ("new_event", "same_event", "continuation", "unknown")
INTERPRETATION_STATUSES = ("explicit", "inferred", "ambiguous", "unknown")
SEVERITIES = ("minor", "major", "blocking", "unknown")
SEVERITY_CERTAINTIES = ("confirmed", "possible", "unknown")
FINDING_STATUSES = ("confirmed", "rejected", "unresolved")
DISPOSITIONS = ("confirmed", "rejected", "unresolved", "advisory")

Errors = list[dict[str, str]]


def _error(errors: Errors, code: str, location: str, message: str) -> None:
    errors.append({"code": code, "location": location, "message": message})


def _object(value: Any, path: str, errors: Errors) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error(errors, "SIDECAR_FORMAT", path, "Expected an object; native text is not rewritten.")
        return {}
    return value


def _text(value: Any, path: str, errors: Errors) -> bool:
    valid = isinstance(value, str) and bool(value.strip())
    if not valid:
        _error(errors, "SIDECAR_FORMAT", path, "Expected a nonblank string.")
    return valid


def _enum(value: Any, choices: tuple[str, ...], path: str, errors: Errors) -> None:
    if not isinstance(value, str) or value not in choices:
        _error(errors, "SIDECAR_FORMAT", path, f"Expected one of {choices}.")


def _bool(value: Any, path: str, errors: Errors, *, true_only: bool = False) -> None:
    if type(value) is not bool or (true_only and value is not True):
        _error(errors, "SIDECAR_FORMAT", path, "Expected true." if true_only else "Expected a boolean.")


def _list(value: Any, path: str, errors: Errors, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        _error(errors, "SIDECAR_FORMAT", path, "Expected a nonempty array." if nonempty else "Expected an array.")
        return []
    return value


def _texts(value: Any, path: str, errors: Errors, *, nonempty: bool = False,
           unique: bool = True) -> list[str]:
    values = _list(value, path, errors, nonempty=nonempty)
    valid = []
    for index, item in enumerate(values):
        if _text(item, f"{path}[{index}]", errors):
            valid.append(item)
    if unique and len(valid) != len(set(valid)):
        _error(errors, "SIDECAR_DUPLICATE", path, "References must be unique.")
    return valid


def _json_value(value: Any, path: str, errors: Errors) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_value(item, f"{path}[{index}]", errors)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for key, item in value.items():
            _json_value(item, f"{path}.{key}", errors)
        return
    _error(errors, "SIDECAR_FORMAT", path, "Expected a finite JSON value.")


def validate_header(value: Any, *, expected_source_binding: str | None = None,
                    expected_draft_binding: str | None = None,
                    require_draft: bool = True) -> Errors:
    """Validate a header itself, not its enclosing artifact or native evidence."""
    errors: Errors = []
    header = _object(value, "$.header", errors)
    for field in ("artifact_id", "schema_version", "source_binding", "producer_version"):
        _text(header.get(field), f"$.header.{field}", errors)
    if header.get("schema_version") != VERSION:
        _error(errors, "SCHEMA_VERSION_MISMATCH", "$.header.schema_version", f"Expected {VERSION}.")
    draft = header.get("draft_binding")
    if require_draft or draft is not None:
        _text(draft, "$.header.draft_binding", errors)
    elif "draft_binding" not in header:
        _error(errors, "SIDECAR_FORMAT", "$.header.draft_binding", "Pre-draft artifacts must explicitly use null.")
    parents = _texts(header.get("parent_artifact_ids"), "$.header.parent_artifact_ids", errors)
    if header.get("artifact_id") in parents:
        _error(errors, "ARTIFACT_REFERENCE_INVALID", "$.header.parent_artifact_ids", "An artifact cannot be its own parent.")
    _enum(header.get("status"), ARTIFACT_STATUSES, "$.header.status", errors)
    for field, expected in (("source_binding", expected_source_binding), ("draft_binding", expected_draft_binding)):
        if expected is not None and header.get(field) != expected:
            _error(errors, "ARTIFACT_BINDING_MISMATCH", f"$.header.{field}", "Artifact is not bound to the expected source/draft.")
    return errors


def _artifact(value: Any, errors: Errors, **binding: Any) -> Mapping[str, Any]:
    artifact = _object(value, "$", errors)
    errors.extend(validate_header(artifact.get("header"), **binding))
    return artifact


def _fact(value: Any, path: str, errors: Errors) -> None:
    fact = _object(value, path, errors)
    for field in ("subject_id", "predicate"):
        _text(fact.get(field), f"{path}.{field}", errors)
    if "value" not in fact:
        _error(errors, "SIDECAR_FORMAT", f"{path}.value", "State values must be explicit, including null when unknown.")
    else:
        _json_value(fact["value"], f"{path}.value", errors)
    _enum(fact.get("certainty"), INTERPRETATION_STATUSES, f"{path}.certainty", errors)
    refs = _texts(fact.get("evidence_refs"), f"{path}.evidence_refs", errors)
    if fact.get("certainty") == "explicit" and not refs:
        _error(errors, "EVIDENCE_REFERENCE_MISSING", f"{path}.evidence_refs", "An explicit state needs a location reference, not an exact quote.")
    qualifiers = _object(fact.get("qualifiers"), f"{path}.qualifiers", errors)
    _json_value(qualifiers, f"{path}.qualifiers", errors)


def _facts(value: Any, path: str, errors: Errors) -> None:
    for index, fact in enumerate(_list(value, path, errors)):
        _fact(fact, f"{path}[{index}]", errors)


def validate_scene_ledger(value: Any, *, expected_source_binding: str | None = None,
                          expected_draft_binding: str | None = None) -> Errors:
    """Validate event/state declarations; do not infer physical contradictions."""
    errors: Errors = []
    artifact = _artifact(value, errors, expected_source_binding=expected_source_binding,
                         expected_draft_binding=expected_draft_binding)
    events = _list(artifact.get("events"), "$.events", errors, nonempty=True)
    ids: list[str] = []
    references: list[tuple[str, Any]] = []
    for index, value in enumerate(events):
        path = f"$.events[{index}]"
        event = _object(value, path, errors)
        for field in ("event_id", "timeline_id"):
            _text(event.get(field), f"{path}.{field}", errors)
        if isinstance(event.get("event_id"), str):
            ids.append(event["event_id"])
        _enum(event.get("narrative_layer"), NARRATIVE_LAYERS, f"{path}.narrative_layer", errors)
        _texts(event.get("entities"), f"{path}.entities", errors, nonempty=True)
        _enum(event.get("relation"), EVENT_RELATIONS, f"{path}.relation", errors)
        referent = event.get("referent_event_id")
        if event.get("relation") in ("same_event", "continuation") or referent is not None:
            _text(referent, f"{path}.referent_event_id", errors)
            references.append((f"{path}.referent_event_id", referent))
        elif "referent_event_id" not in event:
            _error(errors, "SIDECAR_FORMAT", f"{path}.referent_event_id", "Use explicit null if there is no referent.")
        if referent is not None and referent == event.get("event_id"):
            _error(errors, "ARTIFACT_REFERENCE_INVALID", f"{path}.referent_event_id", "An event cannot refer to itself.")
        for field in ("before", "after"):
            _facts(event.get(field), f"{path}.{field}", errors)
        _enum(event.get("interpretation_status"), INTERPRETATION_STATUSES, f"{path}.interpretation_status", errors)
        context = _object(event.get("context"), f"{path}.context", errors)
        for field in ("scene_id", "location", "description"):
            _text(context.get(field), f"{path}.context.{field}", errors)
        if "continuity_from_event_id" in context:
            reference = context["continuity_from_event_id"]
            _text(reference, f"{path}.context.continuity_from_event_id", errors)
            references.append((f"{path}.context.continuity_from_event_id", reference))
            if reference == event.get("event_id"):
                _error(errors, "ARTIFACT_REFERENCE_INVALID", f"{path}.context.continuity_from_event_id", "An event cannot continue from itself.")
    if len(ids) != len(set(ids)):
        _error(errors, "SIDECAR_DUPLICATE", "$.events", "Event IDs must be unique.")
    for path, reference in references:
        if isinstance(reference, str) and reference not in ids:
            _error(errors, "ARTIFACT_REFERENCE_MISSING", path, "Referenced event is not in this ledger.")
    return errors


def validate_issue(value: Any, *, location: str = "$", event_ids: set[str] | None = None) -> Errors:
    """Validate a report without deciding whether it is true or blocks release."""
    errors: Errors = []
    issue = _object(value, location, errors)
    for field in ("issue_id", "root_cause_id", "impact"):
        _text(issue.get(field), f"{location}.{field}", errors)
    dimensions = _texts(issue.get("dimensions"), f"{location}.dimensions", errors, nonempty=True)
    if any(dimension not in REVIEW_DIMENSIONS for dimension in dimensions):
        _error(errors, "REVIEW_COVERAGE", f"{location}.dimensions", "Unknown review dimension.")
    refs = _texts(issue.get("event_ids"), f"{location}.event_ids", errors)
    if event_ids is not None and any(reference not in event_ids for reference in refs):
        _error(errors, "ARTIFACT_REFERENCE_MISSING", f"{location}.event_ids", "Issue references a different or missing event.")
    _texts(issue.get("evidence"), f"{location}.evidence", errors, nonempty=True)
    for field in ("reasonable_explanations", "counterevidence"):
        _texts(issue.get(field), f"{location}.{field}", errors)
    _enum(issue.get("severity"), SEVERITIES, f"{location}.severity", errors)
    _enum(issue.get("severity_certainty"), SEVERITY_CERTAINTIES, f"{location}.severity_certainty", errors)
    _enum(issue.get("finding_status"), FINDING_STATUSES, f"{location}.finding_status", errors)
    _bool(issue.get("blocking"), f"{location}.blocking", errors)
    return errors


def _issues(values: Any, path: str, errors: Errors) -> list[str]:
    ids = []
    for index, value in enumerate(_list(values, path, errors)):
        errors.extend(validate_issue(value, location=f"{path}[{index}]"))
        if isinstance(value, Mapping) and isinstance(value.get("issue_id"), str):
            ids.append(value["issue_id"])
    if len(ids) != len(set(ids)):
        _error(errors, "SIDECAR_DUPLICATE", path, "Issue IDs must be unique.")
    return ids


def validate_full_review(value: Any, *, expected_source_binding: str | None = None,
                         expected_draft_binding: str | None = None) -> Errors:
    """Require nine checks and link every issue; content conflicts go to gate.

    ``provider``, complete flags, and native_response_ref are declarations. The
    execution/evidence layer must independently verify them before any release.
    A native pass plus a newly discovered major issue remains valid input to a
    content revision decision; it is not treated as a writer-format failure.
    """
    errors: Errors = []
    artifact = _artifact(value, errors, expected_source_binding=expected_source_binding,
                         expected_draft_binding=expected_draft_binding)
    _enum(artifact.get("provider"), ("deepseek",), "$.provider", errors)
    _text(artifact.get("native_response_ref"), "$.native_response_ref", errors)
    _enum(artifact.get("native_verdict"), ("pass", "revise"), "$.native_verdict", errors)
    for field in ("whole_text_reviewed", "source_complete", "draft_complete"):
        _bool(artifact.get(field), f"$.{field}", errors, true_only=True)
    ids = _issues(artifact.get("issues"), "$.issues", errors)
    checks = _list(artifact.get("checks"), "$.checks", errors)
    dimensions = []
    covered_ids: set[str] = set()
    issue_dimension_map: dict[str, set[str]] = {}
    for index, value in enumerate(checks):
        path = f"$.checks[{index}]"
        check = _object(value, path, errors)
        dimension = check.get("dimension")
        _enum(dimension, REVIEW_DIMENSIONS, f"{path}.dimension", errors)
        dimensions.append(dimension)
        _bool(check.get("checked"), f"{path}.checked", errors, true_only=True)
        _text(check.get("assessment"), f"{path}.assessment", errors)
        check_ids = _texts(check.get("issue_ids"), f"{path}.issue_ids", errors)
        covered_ids.update(check_ids)
        for issue_id in check_ids:
            if issue_id not in ids:
                _error(errors, "ARTIFACT_REFERENCE_MISSING", f"{path}.issue_ids", "Check references an unknown issue.")
            if isinstance(dimension, str):
                issue_dimension_map.setdefault(issue_id, set()).add(dimension)
    if len(dimensions) != len(REVIEW_DIMENSIONS) or any(dimensions.count(item) != 1 for item in REVIEW_DIMENSIONS):
        _error(errors, "REVIEW_COVERAGE", "$.checks", "All nine dimensions must be present exactly once.")
    if set(ids) - covered_ids:
        _error(errors, "REVIEW_ISSUE_COVERAGE", "$.issues", "Every issue must be linked to its checked dimensions.")
    for index, issue in enumerate(artifact.get("issues", []) if isinstance(artifact.get("issues"), list) else []):
        if isinstance(issue, Mapping) and isinstance(issue.get("issue_id"), str):
            declared = issue.get("dimensions")
            if isinstance(declared, list) and all(isinstance(item, str) for item in declared):
                if set(declared) != issue_dimension_map.get(issue["issue_id"], set()):
                    _error(errors, "REVIEW_ISSUE_COVERAGE", f"$.issues[{index}].dimensions", "Issue dimensions and checks must match.")
    return errors


def validate_adjudication(value: Any, *, review: Any = None,
                          expected_source_binding: str | None = None,
                          expected_draft_binding: str | None = None) -> Errors:
    """Require traceable dispositions, including independent newly found issues."""
    errors: Errors = []
    artifact = _artifact(value, errors, expected_source_binding=expected_source_binding,
                         expected_draft_binding=expected_draft_binding)
    _text(artifact.get("review_artifact_id"), "$.review_artifact_id", errors)
    new_ids = _issues(artifact.get("new_issues"), "$.new_issues", errors)
    disposed = []
    dispositions = _list(artifact.get("dispositions"), "$.dispositions", errors)
    for index, value in enumerate(dispositions):
        path = f"$.dispositions[{index}]"
        disposition = _object(value, path, errors)
        if _text(disposition.get("issue_id"), f"{path}.issue_id", errors):
            disposed.append(disposition["issue_id"])
        _enum(disposition.get("disposition"), DISPOSITIONS, f"{path}.disposition", errors)
        _texts(disposition.get("basis"), f"{path}.basis", errors, nonempty=True)
        effective_fields = ("effective_severity", "effective_severity_certainty")
        if any(field in disposition for field in effective_fields):
            if not all(field in disposition for field in effective_fields):
                _error(errors, "ADJUDICATION_EFFECTIVE_SEVERITY_INCOMPLETE", path,
                       "Effective severity and its certainty must be recorded together.")
            _enum(disposition.get("effective_severity"), SEVERITIES,
                  f"{path}.effective_severity", errors)
            _enum(disposition.get("effective_severity_certainty"), SEVERITY_CERTAINTIES,
                  f"{path}.effective_severity_certainty", errors)
        linked = _texts(disposition.get("new_issue_ids"), f"{path}.new_issue_ids", errors)
        if any(issue_id not in new_ids for issue_id in linked):
            _error(errors, "ARTIFACT_REFERENCE_MISSING", f"{path}.new_issue_ids", "Linked new issue is not recorded independently.")
        _bool(disposition.get("blocking"), f"{path}.blocking", errors)
    if len(disposed) != len(set(disposed)):
        _error(errors, "SIDECAR_DUPLICATE", "$.dispositions", "Each issue needs exactly one disposition.")
    if review is not None:
        review_obj = _object(review, "$review", errors)
        review_header = _object(review_obj.get("header"), "$review.header", errors)
        if artifact.get("review_artifact_id") != review_header.get("artifact_id"):
            _error(errors, "ARTIFACT_BINDING_MISMATCH", "$.review_artifact_id", "Disposition targets a different review.")
        this_header = _object(artifact.get("header"), "$.header", errors)
        for field in ("source_binding", "draft_binding"):
            if this_header.get(field) != review_header.get(field):
                _error(errors, "ARTIFACT_BINDING_MISMATCH", f"$.header.{field}", "Review and adjudication must share source and draft.")
        originals = [item.get("issue_id") for item in review_obj.get("issues", [])
                     if isinstance(item, Mapping) and isinstance(item.get("issue_id"), str)] if isinstance(review_obj.get("issues"), list) else []
        if set(originals) & set(new_ids):
            _error(errors, "SIDECAR_DUPLICATE", "$.new_issues", "New issues must not replace original issue IDs.")
        if set(disposed) != set(originals) | set(new_ids):
            _error(errors, "ADJUDICATION_COVERAGE", "$.dispositions", "Dispose every original and newly discovered issue, with no extra IDs.")
    elif not set(new_ids).issubset(disposed):
        _error(errors, "ADJUDICATION_COVERAGE", "$.dispositions", "Every new issue requires a disposition.")
    return errors


def validate_source_episode(value: Any, *, expected_source_binding: str | None = None,
                            expected_draft_binding: str | None = None) -> Errors:
    """Validate acquired source bounds; a pre-draft episode may bind draft=null."""
    errors: Errors = []
    artifact = _artifact(value, errors, expected_source_binding=expected_source_binding,
                         expected_draft_binding=expected_draft_binding, require_draft=False)
    _text(artifact.get("episode_id"), "$.episode_id", errors)
    source_range = _object(artifact.get("source_range"), "$.source_range", errors)
    _texts(source_range.get("chapter_ids"), "$.source_range.chapter_ids", errors, nonempty=True)
    for field in ("start_anchor", "end_anchor"):
        _text(source_range.get(field), f"$.source_range.{field}", errors)
    _texts(artifact.get("selected_event_ids"), "$.selected_event_ids", errors, nonempty=True)
    _facts(artifact.get("prior_end_state"), "$.prior_end_state", errors)
    _texts(artifact.get("unrevealed_facts"), "$.unrevealed_facts", errors)
    boundaries = _object(artifact.get("adaptation_boundaries"), "$.adaptation_boundaries", errors)
    for field in ("preserve", "allowed_changes", "unknown_facts"):
        _texts(boundaries.get(field), f"$.adaptation_boundaries.{field}", errors)
    return errors


def validate_director_consumption(value: Any, *, expected_source_binding: str | None = None,
                                  expected_draft_binding: str | None = None) -> Errors:
    """Minimum director consumer schema only, not a director implementation.

    Asset requirements declare search/candidate state; this contract deliberately
    cannot turn a character name or catalog candidate into an approved binding.
    """
    errors: Errors = []
    artifact = _artifact(value, errors, expected_source_binding=expected_source_binding,
                         expected_draft_binding=expected_draft_binding)
    for field in ("text_gate_artifact_id", "scene_ledger_artifact_id", "episode_artifact_id"):
        _text(artifact.get(field), f"$.{field}", errors)
    segment_ids = []
    performance_refs: set[tuple[str, str]] = set()
    for index, value in enumerate(_list(artifact.get("segments"), "$.segments", errors, nonempty=True)):
        path = f"$.segments[{index}]"
        segment = _object(value, path, errors)
        for field in ("segment_id", "timeline_id", "location", "environment", "emotion_focus", "next_cause"):
            _text(segment.get(field), f"{path}.{field}", errors)
        if isinstance(segment.get("segment_id"), str):
            segment_ids.append(segment["segment_id"])
        _texts(segment.get("present_characters"), f"{path}.present_characters", errors, nonempty=True)
        for field in ("start_state", "end_state"):
            _facts(segment.get(field), f"{path}.{field}", errors)
        for event_index, action in enumerate(_list(segment.get("performance"), f"{path}.performance", errors, nonempty=True)):
            action_path = f"{path}.performance[{event_index}]"
            action = _object(action, action_path, errors)
            for field in ("event_id", "actor_id", "action", "expression", "gaze", "reaction", "reaction_window"):
                _text(action.get(field), f"{action_path}.{field}", errors)
            if isinstance(action.get("event_id"), str) and isinstance(segment.get("segment_id"), str):
                performance_refs.add((action["event_id"], segment["segment_id"]))
            # Empty dialogue is legitimate for a silent action, but omission is not.
            if not isinstance(action.get("dialogue"), str):
                _error(errors, "SIDECAR_FORMAT", f"{action_path}.dialogue", "Use a string, empty for silent action.")
        duration = segment.get("estimated_duration_seconds")
        positive_finite = ((type(duration) is int and duration > 0)
                           or (type(duration) is float and math.isfinite(duration) and duration > 0))
        if not positive_finite:
            _error(errors, "SIDECAR_FORMAT", f"{path}.estimated_duration_seconds", "Expected a positive finite duration estimate.")
        _text(segment.get("duration_basis"), f"{path}.duration_basis", errors)
    if len(segment_ids) != len(set(segment_ids)):
        _error(errors, "SIDECAR_DUPLICATE", "$.segments", "Segment IDs must be unique.")
    coverage = _list(artifact.get("event_coverage"), "$.event_coverage", errors, nonempty=True)
    covered_refs: set[tuple[str, str]] = set()
    covered_event_ids: list[str] = []
    for index, value in enumerate(coverage):
        path = f"$.event_coverage[{index}]"
        covered = _object(value, path, errors)
        _text(covered.get("event_id"), f"{path}.event_id", errors)
        if isinstance(covered.get("event_id"), str):
            covered_event_ids.append(covered["event_id"])
        refs = _texts(covered.get("segment_ids"), f"{path}.segment_ids", errors, nonempty=True)
        _enum(covered.get("relation"), EVENT_RELATIONS, f"{path}.relation", errors)
        if any(reference not in segment_ids for reference in refs):
            _error(errors, "ARTIFACT_REFERENCE_MISSING", f"{path}.segment_ids", "Coverage points to an unknown segment.")
        if isinstance(covered.get("event_id"), str):
            covered_refs.update((covered["event_id"], segment_id) for segment_id in refs)
    if len(covered_event_ids) != len(set(covered_event_ids)):
        _error(errors, "SIDECAR_DUPLICATE", "$.event_coverage", "Each event has one coverage record listing all its segments.")
    if performance_refs - covered_refs:
        _error(errors, "DIRECTOR_COVERAGE_INCOMPLETE", "$.event_coverage", "Every declared performance event needs its matching segment coverage.")
    if covered_refs - performance_refs:
        _error(errors, "ARTIFACT_REFERENCE_MISSING", "$.event_coverage", "Coverage names an event absent from that segment's declared performance.")
    for index, value in enumerate(_list(artifact.get("asset_requirements"), "$.asset_requirements", errors)):
        path = f"$.asset_requirements[{index}]"
        requirement = _object(value, path, errors)
        _enum(requirement.get("asset_type"), ("character", "scene", "prop", "voice"), f"{path}.asset_type", errors)
        _texts(requirement.get("search_tags"), f"{path}.search_tags", errors, nonempty=True)
        _enum(requirement.get("status"), ("pending", "candidate"), f"{path}.status", errors)
        if requirement.get("status") == "candidate":
            for field in ("candidate_id", "candidate_version"):
                _text(requirement.get(field), f"{path}.{field}", errors)
        elif requirement.get("candidate_id") is not None or requirement.get("candidate_version") is not None:
            _error(errors, "ASSET_REQUIREMENT_CONFLICT", path, "Pending requirements cannot claim candidate identity.")
    return errors
