"""Offline validation of explicitly declared, overlapping performance tracks.

This module neither authors nor rearranges events. Adjacent script sources never
imply overlap permission. The speech range is a project experiment in Chinese
characters per planned second, not a professional rule or media measurement.
"""
from copy import deepcopy
from itertools import combinations
import math
import re

VERSION = "creative_interaction_timing/v1"
DEFAULT_PLANNED_SPEECH_RANGE = (2.8, 4.0)
KINDS = frozenset({"speech", "action", "reaction"})
EPSILON = 1e-9


class InteractionTimingError(ValueError):
    """A mechanical timing failure; no attempted automatic repair."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code, message):
    raise InteractionTimingError(code, message)


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        _fail("FIELD_INVALID", field + " must be a nonempty string")
    return value


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("FIELD_INVALID", field + " must be a finite number")
    return value


def _pair(value, known_sources):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _fail("OVERLAP_DECLARATION_INVALID", "each permission must name two source_ref values")
    left, right = value
    if not isinstance(left, str) or not isinstance(right, str):
        _fail("OVERLAP_DECLARATION_INVALID", "permissions name sources, not event indexes")
    if left == right or left not in known_sources or right not in known_sources:
        _fail("OVERLAP_DECLARATION_INVALID", "permission contains duplicate or unknown source_ref")
    return frozenset(value)


def compile_interactions(events, *, declared_allowed_overlap,
                         planned_speech_range=DEFAULT_PLANNED_SPEECH_RANGE,
                         duration_limit_seconds=None):
    """Validate a submitted schedule, preserving all event fields and timings.

    Required fields: event_id, source_ref, kind, actor, start_seconds,
    end_seconds, requires, interaction_id. Speech also needs exact text.
    Optional action prop_ids reserve those props throughout that action.
    A requirement names event_id and its start/end milestone. Reaction events
    need an explicit stimulus. Every actual overlapping source pair needs
    explicit permission, which cannot waive prerequisites, concurrent speech
    by one actor, or two actions reserving the same prop. Dependency cycles
    fail even if their start milestones have identical timestamps.

    No fit-to-duration option exists. An overlong schedule fails rather than
    changing speed or scaling timestamps. This is not creative/media review.
    """
    if not isinstance(events, list) or not events:
        _fail("EVENTS_INVALID", "events must be a nonempty list")
    if not isinstance(declared_allowed_overlap, (list, tuple)):
        _fail("OVERLAP_DECLARATION_INVALID", "permissions must be a list of source pairs")
    if not isinstance(planned_speech_range, (list, tuple)) or len(planned_speech_range) != 2:
        _fail("SPEECH_RANGE_INVALID", "expected lower and upper planned characters per second")
    low, high = (_number(value, "planned_speech_range") for value in planned_speech_range)
    if low <= 0 or high < low:
        _fail("SPEECH_RANGE_INVALID", "range must satisfy 0 < lower <= upper")
    if duration_limit_seconds is not None:
        _number(duration_limit_seconds, "duration_limit_seconds")
        if duration_limit_seconds <= 0:
            _fail("DURATION_LIMIT_INVALID", "duration limit must be positive")

    by_id, sources = {}, set()
    for event in events:
        if not isinstance(event, dict):
            _fail("EVENTS_INVALID", "every event must be an object")
        for field in ("event_id", "source_ref", "actor", "interaction_id"):
            _text(event.get(field), field)
        if event["event_id"] in by_id:
            _fail("EVENT_ID_DUPLICATE", event["event_id"])
        if event["source_ref"] in sources:
            _fail("SOURCE_REF_DUPLICATE", event["source_ref"])
        if not isinstance(event.get("kind"), str) or event["kind"] not in KINDS:
            _fail("EVENT_KIND_INVALID", str(event.get("kind")))
        start = _number(event.get("start_seconds"), "start_seconds")
        end = _number(event.get("end_seconds"), "end_seconds")
        if start < 0 or end <= start:
            _fail("EVENT_INTERVAL_INVALID", event["event_id"])
        if not isinstance(event.get("requires"), list):
            _fail("DEPENDENCY_INVALID", "requires must be an explicit list")
        if event["kind"] == "reaction" and not event["requires"]:
            _fail("REACTION_STIMULUS_MISSING", event["event_id"])
        props = event.get("prop_ids", [])
        if not isinstance(props, list) or any(not isinstance(p, str) or not p.strip() for p in props):
            _fail("PROP_IDS_INVALID", event["event_id"])
        if len(set(props)) != len(props):
            _fail("PROP_IDS_INVALID", "duplicate prop reservation in " + event["event_id"])
        if props and event["kind"] != "action":
            _fail("PROP_IDS_INVALID", "prop_ids reserve props for actions only")
        if event["kind"] == "speech":
            _text(event.get("text"), "speech.text")
        by_id[event["event_id"]] = event
        sources.add(event["source_ref"])

    permissions = set()
    for value in declared_allowed_overlap:
        pair = _pair(value, sources)
        if pair in permissions:
            _fail("OVERLAP_DECLARATION_INVALID", "duplicate source pair")
        permissions.add(pair)

    graph = {event_id: [] for event_id in by_id}
    for event in events:
        dependencies = set()
        for requirement in event["requires"]:
            if not isinstance(requirement, dict) or set(requirement) != {"event_id", "milestone"}:
                _fail("DEPENDENCY_INVALID", "expected event_id and milestone only")
            dependency_id, milestone = requirement["event_id"], requirement["milestone"]
            if not isinstance(dependency_id, str) or dependency_id not in by_id:
                _fail("DEPENDENCY_UNKNOWN", str(dependency_id))
            if dependency_id == event["event_id"]:
                _fail("DEPENDENCY_CYCLE", dependency_id)
            if not isinstance(milestone, str) or milestone not in {"start", "end"}:
                _fail("DEPENDENCY_INVALID", "milestone must be start or end")
            if (dependency_id, milestone) in dependencies:
                _fail("DEPENDENCY_INVALID", "duplicate dependency milestone")
            dependencies.add((dependency_id, milestone))
            graph[event["event_id"]].append(dependency_id)
            reached_at = by_id[dependency_id][milestone + "_seconds"]
            if event["start_seconds"] + EPSILON < reached_at:
                _fail("STIMULUS_NOT_REACHED", f"{event['event_id']} begins before {dependency_id}.{milestone}")

    visiting, visited = set(), set()

    def visit(event_id):
        if event_id in visiting:
            _fail("DEPENDENCY_CYCLE", event_id)
        if event_id in visited:
            return
        visiting.add(event_id)
        for dependency_id in graph[event_id]:
            visit(dependency_id)
        visiting.remove(event_id)
        visited.add(event_id)

    for event_id in by_id:
        visit(event_id)

    overlaps = []
    for left, right in combinations(events, 2):
        start = max(left["start_seconds"], right["start_seconds"])
        end = min(left["end_seconds"], right["end_seconds"])
        if end - start <= EPSILON:
            continue
        if left["kind"] == right["kind"] == "speech" and left["actor"] == right["actor"]:
            _fail("ACTOR_SPEECH_OVERLAP", f"{left['event_id']} and {right['event_id']}")
        if left["kind"] == right["kind"] == "action":
            conflicts = set(left.get("prop_ids", [])) & set(right.get("prop_ids", []))
            if conflicts:
                _fail("PROP_ACTION_OVERLAP", ", ".join(sorted(conflicts)))
        if frozenset((left["source_ref"], right["source_ref"])) not in permissions:
            _fail("OVERLAP_NOT_DECLARED", f"{left['source_ref']} and {right['source_ref']}")
        overlaps.append({"event_ids": [left["event_id"], right["event_id"]],
                         "source_refs": [left["source_ref"], right["source_ref"]],
                         "start_seconds": start, "end_seconds": end})

    speech_estimates, warnings = [], []
    for event in events:
        if event["kind"] != "speech":
            continue
        count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", event["text"]))
        duration = event["end_seconds"] - event["start_seconds"]
        rate = count / duration if count else None
        if rate is None:
            warnings.append({"code": "SPEECH_ESTIMATE_UNAVAILABLE", "event_id": event["event_id"],
                             "reason": "speech has no countable Chinese characters"})
        elif rate > high + EPSILON:
            _fail("PLANNED_SPEECH_TOO_FAST", f"{event['event_id']}: {rate:.3f} > {high}")
        elif rate + EPSILON < low:
            warnings.append({"code": "PLANNED_SPEECH_BELOW_RANGE", "event_id": event["event_id"],
                             "planned_chinese_characters_per_second": rate})
        speech_estimates.append({"event_id": event["event_id"], "source_ref": event["source_ref"],
                                 "chinese_character_count": count, "planned_seconds": duration,
                                 "planned_chinese_characters_per_second": rate})

    total = max(event["end_seconds"] for event in events)
    if duration_limit_seconds is not None and total > duration_limit_seconds + EPSILON:
        _fail("DURATION_LIMIT_EXCEEDED", f"{total} > {duration_limit_seconds}; schedule was not scaled")
    return {"schema": VERSION, "validation_scope": "offline_explicit_timing_contract",
            "events": deepcopy(events), "declared_allowed_overlap": deepcopy(declared_allowed_overlap),
            "total_duration_seconds": total,
            "summed_event_duration_seconds": sum(e["end_seconds"] - e["start_seconds"] for e in events),
            "allowed_actual_overlaps": overlaps, "speech_estimates": speech_estimates,
            "planned_speech_range": [low, high],
            "planned_speech_range_basis": "project_experiment_not_measured_media_rate",
            "warnings": warnings,
            "schedule_reordered": False, "timestamps_scaled": False,
            "actual_media_speech_rate": None, "creative_quality_passed": False}
