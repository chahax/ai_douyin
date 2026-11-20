"""Pure stage projections for an independent goal-first text workflow.

The complete source packet and historical ledgers stay outside the model
context as local authorities. Projection manifests describe omissions; they
do not establish freshness, a new-story allowance or creative acceptance.
Nothing in this module constructs a client, reads credentials, or writes files.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

VERSION = "creative_stage_context/v2"
STAGES = ("goal_plan", "complete_script", "full_review")
INPUT_KEYS = {
    "source_packet", "verified_legal_context", "reference_fulltext",
    "expression_standards", "production_preferences", "user_goal_contract",
    "native_goal_document", "brief", "creative_scene_plan", "full_current_script",
    "evidence_catalog", "review_criteria", "previous_complete_document",
    "revision_diagnostics", "context_policy",
    # Explicit compatibility names from the immutable 529 request. No caller
    # should mistake these historical fields for a fresh validated goal.
    "automatic_creative_choice_not_user_approval", "revision_requirements",
    "complete_script_feasibility_diagnostics",
}
COMMON = ("source_packet", "verified_legal_context", "reference_fulltext",
          "expression_standards", "production_preferences", "user_goal_contract")
REQUIRED = {
    "goal_plan": COMMON,
    "complete_script": COMMON + ("native_goal_document", "brief", "creative_scene_plan"),
    "full_review": COMMON + ("native_goal_document", "brief", "creative_scene_plan",
                              "full_current_script", "evidence_catalog", "review_criteria"),
}
# These explicit local safety bounds are not model token/context-window claims.
# Exceeding one raises an error; no source or current full text is truncated.
DEFAULT_POLICY = {
    "goal_plan": {"max_payload_characters": 100_000, "max_payload_utf8_bytes": 300_000},
    "complete_script": {"max_payload_characters": 140_000, "max_payload_utf8_bytes": 420_000},
    "full_review": {"max_payload_characters": 180_000, "max_payload_utf8_bytes": 540_000},
}
SOURCE_KEYS = {
    "schema", "account_profile", "collection_run", "source_identity", "candidate",
    "tag_catalog", "selected_relations", "selected_tag_families", "whole_batch_summary",
    "sample_gate", "heat_claim", "source_selection_policy", "candidate_selection_policy",
    "representative_metadata", "limitations", "projection_policy", "human_quality_approved",
    "creative_quality_passed",
}
CANDIDATE_KEYS = {
    "anchor_tag_id", "candidate_id", "family_id", "quality_claim", "related_tags",
    "score_basis", "selected_item_ids", "selection_score", "support_video_count",
    "support_video_ids", "title", "visible_author_count",
}
TAG_KEYS = {
    "classification_basis", "family_ids", "item_ids", "kind", "label", "raw_labels",
    "role", "support_video_ids", "supporting_unique_videos", "tag_id",
}
RELATION_KEYS = {
    "creative_eligible", "edge_id", "jaccard", "lift", "npmi", "relation_basis",
    "relation_kind", "source", "support_item_ids", "support_video_count",
    "support_video_ids", "target", "visible_author_count",
}
FAMILY_KEYS = {
    "family_id", "label", "classification_basis", "support_video_count",
    "visible_author_count", "selected_member_tag_ids", "support_count_scope",
}
METADATA_KEYS = {
    "item_id", "video_id", "run_id", "title", "author", "hashtags", "keyword",
    "metric_kind", "metric_value", "collected_at", "source_observation_sha256",
}


class ContextError(ValueError):
    """A local preflight error; no dispatch has happened."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _measure(value):
    encoded = _json(value)
    return {"characters": len(encoded), "utf8_bytes": len(encoded.encode("utf-8")),
            "semantic_sha256": _digest(value)}


def _object(value, path, *, nonempty=True):
    if type(value) is not dict or (nonempty and not value):
        raise ContextError(path + " must be a nonempty JSON object")
    return value


def _unknown(value, allowed, path):
    unknown = set(value) - allowed
    if unknown:
        raise ContextError(path + " has unmapped fields: " + ", ".join(sorted(unknown)))


def _sha(value, path):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ContextError(path + " must be a lowercase SHA256")
    return value


def _record(rows, path, value, disposition, reason, *, projected=None):
    row = {"path": path, "disposition": disposition, "reason": reason,
           "original": _measure(value)}
    if disposition != "omitted":
        row["projected"] = _measure(value if projected is None else projected)
    rows.append(row)


def _source_projection(source, rows):
    _object(source, "source_packet")
    _unknown(source, SOURCE_KEYS, "source_packet")
    if source.get("schema") != "creative_compact_legal_context/v1/source_packet":
        raise ContextError("source_packet must be the explicitly bound compact legal packet; "
                           "validate its complete authority separately")
    for key in ("source_identity", "candidate", "collection_run"):
        _object(source.get(key), "source_packet." + key)
    identity = source["source_identity"]
    _sha(identity.get("source_binding_sha256"), "source_packet.source_identity.source_binding_sha256")
    _sha(identity.get("source_packet_semantic_sha256"), "source_packet.source_identity.source_packet_semantic_sha256")
    if identity.get("metadata_only_not_law_or_real_case") is not True:
        raise ContextError("metadata-only source limitation required")
    candidate = source["candidate"]
    _unknown(candidate, CANDIDATE_KEYS, "source_packet.candidate")
    for key in ("candidate_id", "anchor_tag_id", "family_id"):
        if not isinstance(candidate.get(key), str) or not candidate[key]:
            raise ContextError("source_packet.candidate." + key + " required")
    selected = candidate.get("selected_item_ids")
    if (type(selected) is not list or not selected or any(not isinstance(x, str) or not x for x in selected)
            or len(selected) != len(set(selected))):
        raise ContextError("candidate selected_item_ids must be unique nonempty identities")
    result = {"schema": VERSION + "/selected_source",
              "source_identity": deepcopy(identity),
              "candidate": {}, "representative_metadata": [],
              "tag_observations": [], "selected_relations": [], "selected_tag_families": []}
    for key, value in source.items():
        path = "source_packet." + key
        if key in ("source_identity",):
            _record(rows, path, value, "included", "exact original source identities retained")
        elif key == "candidate":
            for ckey, cvalue in value.items():
                cpath = path + "." + ckey
                if ckey == "support_video_ids":
                    _record(rows, cpath, cvalue, "omitted", "duplicate support identity list; selected_item_ids retained")
                else:
                    result["candidate"][ckey] = deepcopy(cvalue)
                    _record(rows, cpath, cvalue, "included", "selected candidate identity, observations and counts retained")
        elif key == "representative_metadata":
            if type(value) is not list or not value:
                raise ContextError(path + " must contain same-batch representative metadata")
            seen, seen_videos = set(), set()
            for index, item in enumerate(value):
                ipath = path + "/" + str(index)
                _object(item, ipath)
                _unknown(item, METADATA_KEYS, ipath)
                if item.get("item_id") not in selected or item.get("item_id") in seen:
                    raise ContextError("representative metadata identity must be unique and selected")
                if (not isinstance(item.get("video_id"), str)
                        or item["item_id"] != "douyin:" + item["video_id"]
                        or item.get("video_id") in seen_videos
                        or item.get("run_id") != source["collection_run"].get("run_id")):
                    raise ContextError("representative metadata must map to its exact video and collection run")
                seen.add(item["item_id"])
                seen_videos.add(item["video_id"])
                result[key].append(deepcopy(item))
                _record(rows, ipath, item, "included", "complete selected metadata observation, not inferred video content")
        elif key == "tag_catalog":
            if type(value) is not list or not value:
                raise ContextError(path + " requires selected tag observations")
            for index, item in enumerate(value):
                ipath = path + "/" + str(index)
                _object(item, ipath)
                _unknown(item, TAG_KEYS, ipath)
                projected = {k: deepcopy(v) for k, v in item.items() if k not in ("item_ids", "support_video_ids")}
                projected["source_row_sha256"] = _digest(item)
                result["tag_observations"].append(projected)
                _record(rows, ipath, item, "projected", "retain exact tag identity, classification and support count; repeated support lists stay local", projected=projected)
                for omitted in ("item_ids", "support_video_ids"):
                    if omitted in item:
                        _record(rows, ipath + "." + omitted, item[omitted], "omitted", "support lists retained in local original packet, not repeated per tag")
        elif key == "selected_relations":
            if type(value) is not list:
                raise ContextError(path + " must be an array")
            for index, item in enumerate(value):
                ipath = path + "/" + str(index)
                _object(item, ipath)
                _unknown(item, RELATION_KEYS, ipath)
                projected = {k: deepcopy(v) for k, v in item.items() if k not in ("support_item_ids", "support_video_ids")}
                projected["source_row_sha256"] = _digest(item)
                result[key].append(projected)
                _record(rows, ipath, item, "projected", "cooccurrence relation and counts retained; relation does not prove legal equivalence", projected=projected)
                for omitted in ("support_item_ids", "support_video_ids"):
                    if omitted in item:
                        _record(rows, ipath + "." + omitted, item[omitted], "omitted", "repeated relation support identities retained in local source authority")
        elif key == "selected_tag_families":
            if type(value) is not list:
                raise ContextError(path + " must be an array")
            for index, item in enumerate(value):
                ipath = path + "/" + str(index)
                _object(item, ipath)
                _unknown(item, FAMILY_KEYS, ipath)
                result[key].append(deepcopy(item))
                _record(rows, ipath, item, "included", "exact selected tag family membership and whole-batch count scope")
        elif key in ("account_profile", "collection_run", "heat_claim", "limitations"):
            result[key] = deepcopy(value)
            _record(rows, path, value, "included", "account boundaries, collection identity or observation limitations retained")
        else:
            _record(rows, path, value, "omitted", "local collection/sample policy, redundant projection metadata or whole-batch summary; not reinterpreted by the creative model")
    if not result["representative_metadata"] or not result["tag_observations"]:
        raise ContextError("selected-source observations required")
    tag_ids = [row.get("tag_id") for row in result["tag_observations"]]
    if (any(not isinstance(tag_id, str) or not tag_id for tag_id in tag_ids)
            or len(tag_ids) != len(set(tag_ids)) or candidate["anchor_tag_id"] not in tag_ids):
        raise ContextError("selected tag identities must be unique and include the candidate anchor")
    edge_ids = [row.get("edge_id") for row in result["selected_relations"]]
    if any(not isinstance(edge_id, str) or not edge_id for edge_id in edge_ids) or len(edge_ids) != len(set(edge_ids)):
        raise ContextError("selected relation identities must be unique")
    for relation in result["selected_relations"]:
        if not {relation.get("source"), relation.get("target")} <= set(tag_ids):
            raise ContextError("selected relation endpoints must map to selected tag identities")
    return result


def _preferences_projection(preferences, rows):
    result = deepcopy(_object(preferences, "production_preferences"))
    scope = result.get("prior_story_scope")
    if scope is not None:
        _object(scope, "production_preferences.prior_story_scope")
        if "full_prior_script" in scope:
            prior = scope.pop("full_prior_script")
            expected = _sha(scope.get("prior_script_sha256"), "prior_story_scope.prior_script_sha256")
            if _digest(prior) != expected:
                raise ContextError("prior full script and retained identity differ")
            _record(rows, "production_preferences.prior_story_scope.full_prior_script", prior, "omitted",
                    "old full story belongs in a separate lineage gate; exact identity and spent allowance stay in scope")
        if not isinstance(scope.get("prior_script_sha256"), str):
            raise ContextError("prior scope requires retained prior_script_sha256")
        _sha(scope["prior_script_sha256"], "prior_story_scope.prior_script_sha256")
    return result


def _reference_occurrences(value, reference):
    if isinstance(value, str):
        return value.count(reference)
    if isinstance(value, dict):
        return sum(_reference_occurrences(v, reference) for v in value.values())
    if isinstance(value, list):
        return sum(_reference_occurrences(v, reference) for v in value)
    return 0


def _policy(stage, inputs):
    policy = deepcopy(DEFAULT_POLICY[stage])
    override = inputs.get("context_policy")
    if override is not None:
        _object(override, "context_policy")
        _unknown(override, set(policy), "context_policy")
        policy.update(override)
    if any(type(value) is not int or value <= 0 for value in policy.values()):
        raise ContextError("context safety budgets must be positive integer characters/bytes")
    return policy


def build_stage_context(stage, inputs):
    """Return complete stage payload and auditable, non-authorizing manifest.

    Full current script, law conditions, standards and R01 are copied exactly.
    A complete previous native document is present only during content revision.
    Upstream goal validity and source freshness remain coordinator gates.
    """
    if stage not in STAGES:
        raise ContextError("unsupported stage; director/performance are separate contracts")
    _object(inputs, "inputs")
    _unknown(inputs, INPUT_KEYS, "inputs")
    for key in REQUIRED[stage]:
        if key not in inputs or inputs[key] is None:
            raise ContextError(stage + " requires " + key)
    reference = inputs["reference_fulltext"]
    if not isinstance(reference, str) or not reference.strip():
        raise ContextError("reference_fulltext must be complete nonempty text")
    for key in ("verified_legal_context", "expression_standards", "user_goal_contract"):
        _object(inputs[key], key)
    for key in ("native_goal_document", "brief", "creative_scene_plan", "full_current_script", "evidence_catalog"):
        if key in REQUIRED[stage]:
            _object(inputs[key], key)
    if stage == "full_review" and (type(inputs["review_criteria"]) not in (dict, list) or not inputs["review_criteria"]):
        raise ContextError("full_review requires complete nonempty review criteria")
    # Check serialization before a projection can hide invalid JSON fields.
    original_measure = _measure(inputs)
    rows, payload = [], {}
    for key in REQUIRED[stage]:
        value = inputs[key]
        if key == "source_packet":
            payload[key] = _source_projection(value, rows)
            _record(rows, key, value, "projected", "selected source observations with explicit original identity mapping", projected=payload[key])
        elif key == "production_preferences":
            payload[key] = _preferences_projection(value, rows)
            _record(rows, key, value, "projected", "retain hard production and exhausted historical scope; prior full text evaluated separately", projected=payload[key])
        else:
            payload[key] = deepcopy(value)
            _record(rows, key, value, "included", "complete stage-required value retained without prose edits")
    previous = inputs.get("previous_complete_document")
    diagnostics = inputs.get("revision_diagnostics")
    legacy_diagnostics = inputs.get("complete_script_feasibility_diagnostics")
    if diagnostics is not None and legacy_diagnostics is not None:
        raise ContextError("revision diagnostics have two competing source fields")
    diagnostics = diagnostics if diagnostics is not None else legacy_diagnostics
    revision_stage = stage in ("goal_plan", "complete_script")
    revision_mode = revision_stage and previous is not None
    if revision_mode:
        _object(previous, "previous_complete_document")
        if type(diagnostics) not in (dict, list) or not diagnostics:
            raise ContextError("complete native revision requires explicit nonempty diagnostics")
        payload["previous_complete_document"] = deepcopy(previous)
        payload["revision_diagnostics"] = deepcopy(diagnostics)
        _record(rows, "previous_complete_document", previous, "included", "complete native previous version supplied only for bounded content revision")
        dkey = "revision_diagnostics" if "revision_diagnostics" in inputs else "complete_script_feasibility_diagnostics"
        _record(rows, dkey, inputs[dkey], "included", "explicit full revision diagnostics; compatibility field mapped to revision_diagnostics")
        if "revision_requirements" in inputs:
            payload["revision_requirements"] = deepcopy(inputs["revision_requirements"])
            _record(rows, "revision_requirements", inputs["revision_requirements"], "included", "specific content repair requirements; not permission to resend unknown requests")
    elif revision_stage and diagnostics is not None:
        raise ContextError("revision diagnostics require the complete native previous version")
    handled = set(REQUIRED[stage])
    if revision_mode:
        handled |= {"previous_complete_document", "revision_diagnostics", "complete_script_feasibility_diagnostics", "revision_requirements"}
    for key, value in inputs.items():
        if key not in handled:
            if key == "context_policy":
                reason = "local context safety configuration; no invented provider request field"
            elif key == "automatic_creative_choice_not_user_approval":
                reason = "legacy authority flag stays in manifest; model output never establishes human approval"
            elif key in ("previous_complete_document", "revision_diagnostics", "complete_script_feasibility_diagnostics", "revision_requirements"):
                reason = "initial generation/full review needs the current full version, not repeated failed versions or old diagnostics"
            else:
                reason = "not required by this stage; kept in local coordinator authority without silently changing its contents"
            _record(rows, key, value, "omitted", reason)
    occurrence_count = _reference_occurrences(payload, reference)
    if occurrence_count != 1:
        raise ContextError("complete reference must occur exactly once in projected request payload")
    policy = _policy(stage, inputs)
    measure = _measure(payload)
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ContextError("stage context exceeds explicit safety budget; no content truncated")
    script = payload.get("full_current_script")
    manifest = {
        "schema": VERSION + "/manifest", "stage": stage,
        "generation_mode": "bounded_content_revision" if revision_mode else ("full_current_review" if stage == "full_review" else "initial_generation"),
        "input_identity": original_measure, "payload_identity": measure,
        "source_projection_input_sha256": _digest(inputs["source_packet"]),
        "source_projection_output_sha256": _digest(payload["source_packet"]),
        "original_source_identity": deepcopy(inputs["source_packet"]["source_identity"]),
        "reference_proof": {"characters": len(reference), "utf8_bytes": len(reference.encode("utf-8")),
                            "utf8_sha256": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
                            "payload_occurrences": occurrence_count, "full_text_unchanged": payload["reference_fulltext"] == reference},
        "full_current_script_sha256": _digest(script) if script is not None else None,
        "full_current_script_unchanged": script == inputs.get("full_current_script") if script is not None else None,
        "field_manifest": rows, "context_policy": policy,
        "actual_provider_tokens": None, "token_estimate_performed": False,
        "source_freshness_or_sample_gate_revalidated": False,
        "upstream_goal_semantically_validated": False,
        "lineage_gate_status": "separate_gate_required_before_any_candidate_dispatch",
        "authorization_changed": False, "allowance_reset": False,
        "human_quality_approved": False, "creative_quality_passed": False,
        "client_constructed": False, "dispatch_performed": False,
    }
    return {"payload": payload, "manifest": manifest}
