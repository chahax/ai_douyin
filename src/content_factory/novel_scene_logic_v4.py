"""Conservative, offline checks of explicitly extracted scene-state boundaries.

This module does not extract facts from prose or certify their truth. A mismatch
is a candidate for verification against the frozen source and complete draft,
never a confirmed major issue or a text-release decision. Stable IDs and exact
typed states are compared; words are not compared for semantic similarity.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any

VERSION = "novel_scene_logic/v4"
PREDICATES = ("presence", "location", "posture", "holder")
POSTURES = frozenset(("standing", "sitting", "lying", "kneeling", "crouching"))
_UNKNOWN_IDS = frozenset(("unknown", "unspecified", "?"))


def _known_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value not in _UNKNOWN_IDS


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _reason(event_id: Any, reason: str, **extra: Any) -> dict[str, Any]:
    return {"event_id": event_id, "reason": reason, **extra}


def _fact_state(fact: Any) -> tuple[Any, str | None]:
    """Return comparable state, or a reason to retain the fact as unassessed."""
    if not isinstance(fact, Mapping):
        return None, "invalid_fact"
    if not _known_id(fact.get("subject_id")):
        return None, "unknown_subject"
    if fact.get("certainty") != "explicit":
        return None, "fact_not_explicit"
    refs = fact.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(_known_id(ref) for ref in refs):
        return None, "missing_evidence"
    qualifiers = fact.get("qualifiers")
    if not isinstance(qualifiers, Mapping) or qualifiers.get("scope") != "physical":
        return None, "nonphysical_or_unknown_scope"
    predicate, value = fact.get("predicate"), fact.get("value")
    if predicate == "presence":
        return (value, None) if type(value) is bool else (None, "presence_not_boolean")
    if predicate == "posture":
        return (value, None) if isinstance(value, str) and value in POSTURES else (None, "posture_not_normalized")
    if predicate == "location":
        if qualifiers.get("spatial_mode") != "absolute":
            return None, "relative_or_unknown_space"
        if not _known_id(qualifiers.get("reference_frame_id")) or not _known_id(value):
            return None, "unknown_location_or_frame"
        return value, None
    if predicate == "holder":
        if qualifiers.get("holding_mode") != "exclusive" or not _known_id(value):
            return None, "shared_or_unknown_holding"
        return value, None
    return None, "unsupported_predicate"


def _collect(event: Mapping[str, Any], phase: str, retained: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    by_frame: dict[tuple[str, str, Any], dict[str, Any]] = {}
    conflicted: set[tuple[str, str, Any]] = set()
    facts = event.get(phase)
    if not isinstance(facts, list):
        retained.append(_reason(event.get("event_id"), "invalid_state_list", phase=phase))
        return {}
    for fact in facts:
        value, reason = _fact_state(fact)
        if reason:
            retained.append(_reason(event.get("event_id"), reason, phase=phase,
                                    subject_id=fact.get("subject_id") if isinstance(fact, Mapping) else None,
                                    predicate=fact.get("predicate") if isinstance(fact, Mapping) else None))
            continue
        frame = fact["qualifiers"].get("reference_frame_id") if fact["predicate"] == "location" else None
        key = (fact["subject_id"], fact["predicate"], frame)
        if key in conflicted:
            continue
        record = {"value": deepcopy(value), "evidence_refs": list(fact["evidence_refs"]),
                  "reference_frame_id": fact["qualifiers"].get("reference_frame_id")}
        if key not in by_frame:
            by_frame[key] = record
        elif by_frame[key]["value"] != value:
            previous = by_frame.pop(key)
            conflicted.add(key)
            retained.append(_reason(event.get("event_id"), "internally_conflicting_fact_set", phase=phase,
                                    subject_id=key[0], predicate=key[1], reference_frame_id=frame,
                                    evidence_refs=list(dict.fromkeys(previous["evidence_refs"] + record["evidence_refs"]))))
        else:
            by_frame[key]["evidence_refs"] = list(dict.fromkeys(by_frame[key]["evidence_refs"] + record["evidence_refs"]))
    states: dict[tuple[str, str], dict[str, Any]] = {}
    multiple_frames: set[tuple[str, str]] = set()
    for (subject, predicate, _frame), state in by_frame.items():
        key = (subject, predicate)
        if key in states:
            states.pop(key)
            multiple_frames.add(key)
            retained.append(_reason(event.get("event_id"), "different_spatial_frames", phase=phase,
                                    subject_id=subject, predicate=predicate))
        elif key not in multiple_frames:
            states[key] = state
    return states


def analyze_scene_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Check explicit continuous boundaries, returning unverified candidates.

    An eligible event has ``interpretation_status=explicit``,
    ``narrative_layer=performance`` and ``relation=new_event``. Its context must
    explicitly name ``continuity_from_event_id``; an omitted cut or temporal gap
    must not be invented. Both events must have the same known timeline ID.

    Facts require evidence refs, explicit certainty, and physical scope. Location
    additionally requires absolute spatial mode and a matching stable reference
    frame. Holder requires exclusive holding; shared hands are not a conflict.
    Internally contradictory explicit facts make the required auxiliary ledger
    unreliable and return ``needs_attention``; they do not request writer repair.
    Absence of candidates says nothing about overall manuscript correctness.
    """
    result: dict[str, Any] = {
        "schema_version": VERSION, "status": "analysis_complete",
        "requires_semantic_verification": True, "candidates": [],
        "retained_ambiguities": [], "checked_boundaries": [], "errors": [],
    }
    if not isinstance(ledger, Mapping) or not isinstance(ledger.get("events"), list):
        result.update(status="needs_attention", errors=["EVENTS_LIST_REQUIRED"])
        return result
    header = ledger.get("header", {})
    if isinstance(header, Mapping):
        for field in ("source_binding", "draft_binding"):
            result[field] = deepcopy(header.get(field))
    events = ledger["events"]
    index: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for position, event in enumerate(events):
        if not isinstance(event, Mapping) or not _known_id(event.get("event_id")):
            result["errors"].append("KNOWN_EVENT_ID_REQUIRED")
        elif event["event_id"] in index:
            result["errors"].append("DUPLICATE_EVENT_ID")
        else:
            index[event["event_id"]] = (position, event)
    if result["errors"]:
        result["status"] = "needs_attention"
        return result

    retained = result["retained_ambiguities"]
    state_cache: dict[str, dict[str, dict[tuple[str, str], dict[str, Any]]]] = {}
    for event in events:
        context = event.get("context", {})
        context = context if isinstance(context, Mapping) else {}
        if (event.get("narrative_layer") == "performance"
                and event.get("interpretation_status") == "explicit"
                and context.get("channel", "physical") == "physical"):
            state_cache[event["event_id"]] = {
                phase: _collect(event, phase, retained) for phase in ("before", "after")
            }
    if any(item["reason"] == "internally_conflicting_fact_set" for item in retained):
        result.update(status="needs_attention", errors=["INTERNALLY_CONFLICTING_FACT_SET"])
        return result
    latest_performance: dict[str, str] = {}
    for position, event in enumerate(events):
        event_id, timeline = event["event_id"], event.get("timeline_id")
        context = event.get("context")
        context = context if isinstance(context, Mapping) else {}
        predecessor = context.get("continuity_from_event_id")
        prior_id = latest_performance.get(timeline) if isinstance(timeline, str) else None
        if event.get("narrative_layer") == "performance" and isinstance(timeline, str):
            latest_performance[timeline] = event_id
        if event.get("narrative_layer") != "performance":
            retained.append(_reason(event_id, "nonperformance_layer"))
            continue
        if event.get("relation") != "new_event":
            retained.append(_reason(event_id, "same_continuing_or_unknown_event"))
            continue
        if event.get("interpretation_status") != "explicit" or not _known_id(timeline):
            retained.append(_reason(event_id, "event_or_timeline_not_explicit"))
            continue
        if not predecessor:
            retained.append(_reason(event_id, "continuity_not_asserted"))
            continue
        if not isinstance(predecessor, str) or predecessor not in index or index[predecessor][0] >= position:
            retained.append(_reason(event_id, "invalid_continuity_target"))
            continue
        previous = index[predecessor][1]
        if previous.get("timeline_id") != timeline:
            retained.append(_reason(event_id, "different_timelines"))
            continue
        if previous.get("narrative_layer") != "performance" or previous.get("relation") != "new_event":
            retained.append(_reason(event_id, "predecessor_not_independent_performance"))
            continue
        if previous.get("interpretation_status") != "explicit":
            retained.append(_reason(event_id, "predecessor_not_explicit"))
            continue
        if prior_id != predecessor:
            retained.append(_reason(event_id, "intervening_performance_event"))
            continue
        previous_context = previous.get("context", {})
        if not isinstance(previous_context, Mapping):
            previous_context = {}
        if any(c.get("channel", "physical") != "physical" for c in (context, previous_context)):
            retained.append(_reason(event_id, "nonphysical_or_unknown_channel"))
            continue
        before = state_cache[event_id]["before"]
        after = state_cache[predecessor]["after"]
        compared: list[dict[str, str]] = []
        for subject, predicate in sorted(before.keys() & after.keys()):
            left, right = after[(subject, predicate)], before[(subject, predicate)]
            if predicate == "location" and left["reference_frame_id"] != right["reference_frame_id"]:
                retained.append(_reason(event_id, "different_spatial_frames", subject_id=subject, predicate=predicate))
                continue
            compared.append({"subject_id": subject, "predicate": predicate})
            if left["value"] == right["value"]:
                continue
            evidence = list(dict.fromkeys(left["evidence_refs"] + right["evidence_refs"]))
            identity = {"source_binding": result.get("source_binding"), "draft_binding": result.get("draft_binding"),
                        "event_ids": [predecessor, event_id], "subject_id": subject, "predicate": predicate,
                        "previous_value": left["value"], "current_value": right["value"], "evidence_refs": evidence}
            digest = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:20]
            result["candidates"].append({
                "candidate_id": "scene-candidate-" + digest, "status": "candidate", "requires_verification": True,
                "code": "STATE_BOUNDARY_MISMATCH", "root_cause_id": "boundary-" + digest,
                **identity, "possible_severity": "major", "severity_certainty": "unknown",
                "previous_evidence_refs": list(left["evidence_refs"]),
                "current_evidence_refs": list(right["evidence_refs"]),
                "after_evidence": {"event_id": predecessor, "phase": "after", "evidence_refs": list(left["evidence_refs"])},
                "before_evidence": {"event_id": event_id, "phase": "before", "evidence_refs": list(right["evidence_refs"])},
                "reason": "显式连续的独立表演事件，其已抽取前后状态不一致；需对照完整稿与正文核实抽取、连续性、合理解释和实际影响。",
            })
        result["checked_boundaries"].append({"event_ids": [predecessor, event_id], "compared_states": compared})
    return result


def check_scene_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Alias for callers that name their domain operation as a check."""
    return analyze_scene_ledger(ledger)
