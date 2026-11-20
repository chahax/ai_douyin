"""Explicit current-brief projection; archived story proposals never enter a writer.

This offline module validates declared IDs and source identity. It does not
infer story facts, inspect prose for forbidden characters, select a proposal,
rewrite old bindings, or prove legal/creative quality.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

VERSION = "creative_current_brief_projection/v1"
BRIEF_FIELDS = {
    "brief_id", "source_identity", "characters", "scenes", "facts",
    "initial_state", "event_chain", "ending", "constraints",
}


class CurrentBriefProjectionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code, message):
    raise CurrentBriefProjectionError(code, message)


def digest(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("INPUT_NOT_CANONICAL_JSON", str(exc))
    return hashlib.sha256(encoded).hexdigest()


def _keys(value, expected, location):
    if not isinstance(value, dict) or set(value) != set(expected):
        _fail("FIELDS_INVALID", location + " requires exactly " + ", ".join(sorted(expected)))
    return value


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        _fail("FIELD_INVALID", location + " must be a nonempty string")
    return value


def _list(value, location, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        _fail("FIELD_INVALID", location + " must be " + ("a nonempty " if nonempty else "a ") + "list")
    return value


def _ids(value, location, *, known=None, nonempty=False):
    _list(value, location, nonempty=nonempty)
    for item in value:
        _text(item, location)
    if len(set(value)) != len(value):
        _fail("REFERENCE_DUPLICATE", location)
    if known is not None and not set(value) <= known:
        _fail("REFERENCE_UNKNOWN", location)
    return value


def _record_ids(records, id_field, fields, location):
    _list(records, location, nonempty=True)
    result = set()
    for record in records:
        _keys(record, fields, location)
        value = _text(record[id_field], location + "." + id_field)
        if value in result:
            _fail("REFERENCE_DUPLICATE", location + "." + value)
        result.add(value)
    return result


def _validate_brief(brief):
    _keys(brief, BRIEF_FIELDS, "current_brief")
    _text(brief["brief_id"], "brief_id")
    source = _keys(brief["source_identity"], {"source_id", "sha256"}, "source_identity")
    _text(source["source_id"], "source_identity.source_id")
    if not isinstance(source["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
        _fail("SOURCE_IDENTITY_INVALID", "sha256 must be 64 lowercase hex characters")

    characters = _record_ids(brief["characters"], "character_id",
                             {"character_id", "name", "role"}, "characters")
    for character in brief["characters"]:
        _text(character["name"], "characters.name")
        _text(character["role"], "characters.role")
    scenes = _record_ids(brief["scenes"], "scene_id", {"scene_id", "description"}, "scenes")
    for scene in brief["scenes"]:
        _text(scene["description"], "scenes.description")
    constraints = _keys(brief["constraints"],
                        {"allowed_character_ids", "allowed_scene_ids", "max_duration_seconds",
                         "dialogue_language", "subtitles"}, "constraints")
    _ids(constraints["allowed_character_ids"], "constraints.allowed_character_ids", nonempty=True)
    _ids(constraints["allowed_scene_ids"], "constraints.allowed_scene_ids", nonempty=True)
    if set(constraints["allowed_character_ids"]) != characters:
        _fail("CHARACTER_SCOPE_MISMATCH", "declared characters differ from explicitly allowed characters")
    if set(constraints["allowed_scene_ids"]) != scenes:
        _fail("SCENE_SCOPE_MISMATCH", "declared scenes differ from explicitly allowed scenes")
    seconds = constraints["max_duration_seconds"]
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        _fail("FIELD_INVALID", "constraints.max_duration_seconds must be positive and finite")
    _text(constraints["dialogue_language"], "constraints.dialogue_language")
    if not isinstance(constraints["subtitles"], bool):
        _fail("FIELD_INVALID", "constraints.subtitles must be boolean")

    facts = _record_ids(brief["facts"], "fact_id", {"fact_id", "text", "participant_ids"}, "facts")
    for fact in brief["facts"]:
        _text(fact["text"], "facts.text")
        _ids(fact["participant_ids"], "facts.participant_ids", known=characters)

    initial = _keys(brief["initial_state"], {"scene_id", "character_states", "prop_states"}, "initial_state")
    if not isinstance(initial["scene_id"], str) or initial["scene_id"] not in scenes:
        _fail("REFERENCE_UNKNOWN", "initial_state.scene_id")
    state_characters = _record_ids(initial["character_states"], "character_id",
                                   {"character_id", "state"}, "initial_state.character_states")
    if state_characters != characters:
        _fail("CHARACTER_STATE_SCOPE_MISMATCH", "each declared character needs one current state")
    for state in initial["character_states"]:
        _text(state["state"], "initial_state.character_states.state")
    _list(initial["prop_states"], "initial_state.prop_states")
    props = set()
    for prop in initial["prop_states"]:
        _keys(prop, {"prop_id", "state", "holder_character_id"}, "initial_state.prop_states")
        prop_id = _text(prop["prop_id"], "prop_id")
        if prop_id in props:
            _fail("REFERENCE_DUPLICATE", "initial_state.prop_states." + prop_id)
        props.add(prop_id)
        _text(prop["state"], "prop.state")
        holder = prop["holder_character_id"]
        if holder is not None and (not isinstance(holder, str) or holder not in characters):
            _fail("REFERENCE_UNKNOWN", "prop.holder_character_id")

    events = _record_ids(brief["event_chain"], "event_id",
                         {"event_id", "summary", "participant_ids", "fact_ids", "scene_id"}, "event_chain")
    for event in brief["event_chain"]:
        _text(event["summary"], "event_chain.summary")
        _ids(event["participant_ids"], "event_chain.participant_ids", known=characters, nonempty=True)
        _ids(event["fact_ids"], "event_chain.fact_ids", known=facts)
        if not isinstance(event["scene_id"], str) or event["scene_id"] not in scenes:
            _fail("REFERENCE_UNKNOWN", "event_chain.scene_id")
    ending = _keys(brief["ending"], {"after_event_id", "summary", "participant_ids", "scene_id"}, "ending")
    if ending["after_event_id"] != brief["event_chain"][-1]["event_id"]:
        _fail("ENDING_EVENT_MISMATCH", "ending must explicitly follow the last current event")
    _text(ending["summary"], "ending.summary")
    _ids(ending["participant_ids"], "ending.participant_ids", known=characters, nonempty=True)
    if not isinstance(ending["scene_id"], str) or ending["scene_id"] not in scenes:
        _fail("REFERENCE_UNKNOWN", "ending.scene_id")


def current_identity(authoritative_current_brief):
    _validate_brief(authoritative_current_brief)
    return {"brief_id": authoritative_current_brief["brief_id"],
            "source_identity": deepcopy(authoritative_current_brief["source_identity"]),
            "brief_sha256": digest(authoritative_current_brief)}


def project_current_brief(authoritative_current_brief, archived_direction, *,
                          expected_current_identity=None, selected_tag_ids=()):
    """Return the exact current writer context plus separate archival identity.

    selected_tag_ids is explicit, defaults to no archived tags, and may contain
    only tag_id values present in archived_direction.tag_choices. No old tag
    story_relevance or creative/emotional/character proposal is projected.
    """
    identity = current_identity(authoritative_current_brief)
    if expected_current_identity is not None and expected_current_identity != identity:
        _fail("CURRENT_IDENTITY_MISMATCH", "current facts or source differ from expected current identity")
    if not isinstance(archived_direction, dict):
        _fail("FIELD_INVALID", "archived_direction must be an object")
    archived_sha = digest(archived_direction)
    if not isinstance(selected_tag_ids, (list, tuple)):
        _fail("FIELD_INVALID", "selected_tag_ids must be a list or tuple")
    tag_ids = list(selected_tag_ids)
    _ids(tag_ids, "selected_tag_ids")
    if tag_ids:
        tag_choices = _list(archived_direction.get("tag_choices"), "archived_direction.tag_choices")
        available = set()
        for tag in tag_choices:
            if not isinstance(tag, dict):
                _fail("FIELD_INVALID", "archived tag choice must be an object")
            available.add(_text(tag.get("tag_id"), "archived tag_id"))
        if not set(tag_ids) <= available:
            _fail("REFERENCE_UNKNOWN", "selected_tag_ids")

    writer = {"current_brief": deepcopy(authoritative_current_brief), "tag_ids": tag_ids}
    archive_source = {field: deepcopy(archived_direction[field])
                      for field in ("schema", "packet_sha256", "source_id", "direction_id")
                      if field in archived_direction and isinstance(archived_direction[field], str)}
    return {"schema": VERSION, "writer_context": writer,
            "identity": {"current_brief": identity, "writer_context_sha256": digest(writer),
                         "archived_direction_sha256": archived_sha},
            "archive": {"direction_sha256": archived_sha, "source_identity": archive_source}}


def verify_writer_request(actual_writer_context, projection):
    """Reject any extra, missing, or changed field in the actual writer projection.

    The caller passes the context actually serialized into the writer request.
    This verifies that context only; it does not claim to inspect an unrelated
    outer prompt, provider transport, or complete production request.
    """
    _keys(projection, {"schema", "writer_context", "identity", "archive"}, "projection")
    if projection["schema"] != VERSION:
        _fail("PROJECTION_VERSION_MISMATCH", str(projection["schema"]))
    writer = _keys(projection["writer_context"], {"current_brief", "tag_ids"}, "writer_context")
    _keys(projection["identity"],
          {"current_brief", "writer_context_sha256", "archived_direction_sha256"}, "projection.identity")
    archive = _keys(projection["archive"], {"direction_sha256", "source_identity"}, "projection.archive")
    archive_identity = archive["source_identity"]
    if (not isinstance(archive_identity, dict)
            or not set(archive_identity) <= {"schema", "packet_sha256", "source_id", "direction_id"}
            or any(not isinstance(value, str) for value in archive_identity.values())):
        _fail("ARCHIVE_IDENTITY_INVALID", "archive contains unselected or invalid identity fields")
    archived_sha = archive["direction_sha256"]
    if (not isinstance(archived_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", archived_sha)
            or archived_sha != projection["identity"]["archived_direction_sha256"]):
        _fail("ARCHIVE_IDENTITY_INVALID", "archive direction digest differs from bound identity")
    identity = current_identity(writer["current_brief"])
    _ids(writer["tag_ids"], "writer_context.tag_ids")
    if projection["identity"].get("current_brief") != identity:
        _fail("CURRENT_IDENTITY_MISMATCH", "projection current identity differs from current brief")
    expected_hash = digest(writer)
    if projection["identity"].get("writer_context_sha256") != expected_hash:
        _fail("WRITER_CONTEXT_IDENTITY_MISMATCH", "projection context digest differs")
    if actual_writer_context != writer or digest(actual_writer_context) != expected_hash:
        _fail("WRITER_REQUEST_PROJECTION_MISMATCH", "actual writer context contains extra, missing, or changed fields")
    return {"schema": "creative_current_brief_request_proof/v1",
            "current_brief_sha256": identity["brief_sha256"],
            "writer_context_sha256": expected_hash,
            "exact_projection_match": True, "unselected_fields_present": False,
            "creative_quality_passed": False}
