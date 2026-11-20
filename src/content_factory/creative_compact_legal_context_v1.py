"""Pure, source-bound model context projection; no storage or service calls.

The full graph packet remains the authority used by validators and compilers.
This module changes only the evidence shown to a model, never the native theme,
brief, plan, script, ledger or authorization. Hashes below are canonical JSON
hashes unless explicitly named ``utf8_sha256``; they are not file hashes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from . import creative_legal_tag_graph_bridge_v1 as bridge
from .creative_video_trial_contract_v1 import digest

VERSION = "creative_compact_legal_context/v1"
MAX_REPRESENTATIVE_UNIQUE_VIDEOS = 6
CONTEXT_KEYS = ("source_packet", "verified_legal_context", "reference_fulltext",
                "expression_standards", "production_preferences")
METADATA_FIELDS = ("item_id", "video_id", "run_id", "title", "author", "hashtags",
                   "keyword", "metric_kind", "metric_value", "collected_at")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(label + " must be an exact lowercase SHA256")
    return value


def _validate_packet(packet, now):
    # Validate the *original*, including current freshness and the complete
    # same-batch sample gate. A previously projected packet is never authority.
    if not isinstance(packet, dict) or packet.get("schema") != bridge.VERSION:
        raise ValueError("original full legal graph packet required")
    current = bridge.validate_packet(packet, now=now)
    if current.get("blockers") or current.get("sample_gate", {}).get("passed") is not True:
        raise ValueError("complete original source sample gate must pass")
    if packet["graph_source"]["account_profile"]["domain_strategy_id"] != "legal_services":
        raise ValueError("bound legal account required")
    digest(packet)  # Reject non-JSON/nonfinite input without changing it.
    return current


def _validate_components(packet, legal_context, reference_fulltext,
                         expression_standards, production_preferences, binding):
    _sha(binding, "source binding")
    if (not isinstance(reference_fulltext, str) or not reference_fulltext.strip()
            or reference_fulltext != packet["inputs"]["reference_fulltext"]):
        raise ValueError("same complete packet R01 fulltext required")
    if (not isinstance(expression_standards, dict) or not expression_standards.get("criteria")
            or expression_standards != packet["inputs"]["expression_standards"]):
        raise ValueError("same complete packet expression standards required")
    if (not isinstance(legal_context, dict)
            or legal_context.get("schema") != "verified_legal_story_context/v1"
            or not legal_context.get("sources") or not legal_context.get("facts")
            or not legal_context.get("creative_boundaries")):
        raise ValueError("complete separately verified legal context required")
    if not isinstance(production_preferences, dict):
        raise ValueError("complete production preferences object required")
    count = production_preferences.get("max_characters", 4)
    if type(count) is not int or not 1 <= count <= 4:
        raise ValueError("max closed on-screen actors must be 1..4")
    for value in (legal_context, expression_standards, production_preferences):
        digest(value)


def _selected_edges(packet):
    candidate, graph = packet["candidate"], packet["graph"]
    wanted = [row["edge_id"] for row in candidate["related_tags"]]
    indexed = {row["edge_id"]: row for row in graph["edges"]}
    if len(wanted) != len(set(wanted)) or any(edge_id not in indexed for edge_id in wanted):
        raise ValueError("selected original edge identity mismatch")
    anchor = candidate["anchor_tag_id"]
    tags = {row["tag_id"] for row in packet["tag_catalog"]}
    vids = set(candidate["support_video_ids"])
    result = []
    for edge_id in wanted:
        edge = indexed[edge_id]
        if (edge["relation_kind"] != "tag_cooccurrence" or edge["creative_eligible"] is not True
                or anchor not in (edge["source"], edge["target"])
                or not {edge["source"], edge["target"]} <= tags
                or not set(edge["support_video_ids"]) <= vids):
            raise ValueError("selected edge is not exact candidate cooccurrence")
        result.append(deepcopy(edge))  # Complete original selected relation.
    return result


def _representatives(packet):
    candidate_vids = set(packet["candidate"]["support_video_ids"])
    rows = packet["graph_source"]["observations"]
    # Exact known metric values rank examples only. They are never used to
    # recompute a sample gate from this bounded subset or claim platform growth.
    ordered = sorted(rows, key=lambda row: (
        -(row.get("metric_value") if type(row.get("metric_value")) is int else 0),
        row["video_id"], row.get("keyword", ""), row["item_id"], digest(row)))
    result, seen = [], set()
    for row in ordered:
        if row["video_id"] not in candidate_vids or row["video_id"] in seen:
            continue
        seen.add(row["video_id"])
        result.append({**{key: deepcopy(row[key]) for key in METADATA_FIELDS if key in row},
                       "source_observation_sha256": digest(row)})
        if len(result) == MAX_REPRESENTATIVE_UNIQUE_VIDEOS:
            break
    if not result:
        raise ValueError("same-batch selected candidate metadata required")
    return result


def _project_source(packet, binding):
    graph, source = packet["graph"], packet["graph_source"]
    selected_tags = {row["tag_id"] for row in packet["tag_catalog"]}
    selected_families = {family for row in packet["tag_catalog"] for family in row["family_ids"]}
    families = [{key: deepcopy(row[key]) for key in (
        "family_id", "label", "classification_basis", "support_video_count", "visible_author_count")}
        | {"selected_member_tag_ids": sorted(selected_tags & set(row["member_tag_ids"])),
           "support_count_scope": "whole_batch_family_not_selected_candidate"}
        for row in graph["families"] if row["family_id"] in selected_families]
    return {
        "schema": VERSION + "/source_packet",
        "account_profile": deepcopy(source["account_profile"]),
        "collection_run": deepcopy(source["collection_run"]),
        "source_identity": {
            "source_binding_sha256": binding,
            "source_packet_semantic_sha256": digest(packet),
            "source_semantic_sha256": packet["source_sha256"],
            "graph_semantic_sha256": packet["graph_sha256"],
            "collection_run_id": graph["collection_run_id"],
            "complete_evidence_retained_locally": True,
            "metadata_only_not_law_or_real_case": True},
        "candidate": deepcopy(packet["candidate"]),
        "tag_catalog": deepcopy(packet["tag_catalog"]),
        "selected_relations": _selected_edges(packet),
        "selected_tag_families": families,
        "whole_batch_summary": deepcopy(graph["summary"]),
        "sample_gate": deepcopy(packet["sample_gate"]),
        "heat_claim": packet["heat_claim"],
        "source_selection_policy": deepcopy(source["selection_policy"]),
        "candidate_selection_policy": deepcopy(packet["selection_policy"]),
        "representative_metadata": _representatives(packet),
        "limitations": deepcopy(graph["limitations"]),
        "projection_policy": {
            "full_candidate_and_selected_tag_catalog_preserved": True,
            "selected_relations_are_full_original_edges": True,
            "max_representative_unique_videos": MAX_REPRESENTATIVE_UNIQUE_VIDEOS,
            "full_source_packet_graph_observations_not_sent": True,
            "original_complete_sample_gate_validated_before_projection": True,
            "representative_subset_not_sample_gate_or_law": True},
        "human_quality_approved": False,
        "creative_quality_passed": False}


def compact_context(packet, legal_context, reference_fulltext, expression_standards,
                    production_preferences, source_binding_sha256, *, now):
    """Return compatible context after validating the entire original source.

    ``now`` is mandatory so each request rechecks freshness. The caller must
    additionally bind these unchanged inputs to its frozen source manifest;
    this pure function has no access to files or authorization/ledger state.
    """
    _validate_packet(packet, now)
    _validate_components(packet, legal_context, reference_fulltext,
                         expression_standards, production_preferences, source_binding_sha256)
    return {"source_packet": _project_source(packet, source_binding_sha256),
            "verified_legal_context": deepcopy(legal_context),
            "reference_fulltext": reference_fulltext,
            "expression_standards": deepcopy(expression_standards),
            "production_preferences": deepcopy(production_preferences),
            "automatic_creative_choice_not_user_approval": True}


def compact_payload(payload, source_binding_sha256, *, now):
    """Replace only source_packet; preserve all native documents and extras."""
    if not isinstance(payload, dict) or not set(CONTEXT_KEYS) <= set(payload):
        raise ValueError("complete original context payload required")
    context = compact_context(payload["source_packet"], payload["verified_legal_context"],
        payload["reference_fulltext"], payload["expression_standards"],
        payload["production_preferences"], source_binding_sha256, now=now)
    projected = deepcopy(payload)
    projected["source_packet"] = context["source_packet"]
    return projected


def _key_count(value, key):
    if isinstance(value, dict):
        return sum((name == key) + _key_count(child, key) for name, child in value.items())
    if isinstance(value, list):
        return sum(_key_count(child, key) for child in value)
    return 0


def _size(value):
    rendered = _json(value)
    return {"characters": len(rendered), "utf8_bytes": len(rendered.encode("utf-8"))}


def payload_projection_evidence(original, projected, source_binding_sha256, *, now):
    """Validate the exact permitted delta and return deterministic evidence."""
    expected = compact_payload(original, source_binding_sha256, now=now)
    if not isinstance(projected, dict) or digest(expected) != digest(projected):
        raise ValueError("projection must change only the exact source_packet")
    packet, source_context = original["source_packet"], projected["source_packet"]
    original_size, projected_size = _size(original), _size(projected)
    occurrences = {key: _key_count(projected, key) for key in (
        "reference_fulltext", "verified_legal_context", "expression_standards")}
    if any(count != 1 for count in occurrences.values()):
        raise ValueError("complete fixed context must occur once in projected payload")
    return {
        "schema": VERSION + "/projection_evidence",
        "validated_at": now,
        "source_identity": deepcopy(source_context["source_identity"]),
        "original_payload_semantic_sha256": digest(original),
        "projected_payload_semantic_sha256": digest(projected),
        "projected_source_packet_semantic_sha256": digest(source_context),
        "original_source_packet_size": _size(packet),
        "projected_source_packet_size": _size(source_context),
        "original_payload_size": original_size,
        "projected_payload_size": projected_size,
        "character_reduction_ratio": round(1 - projected_size["characters"] / original_size["characters"], 8),
        "full_candidate_sha256": digest(packet["candidate"]),
        "full_selected_tag_catalog_sha256": digest(packet["tag_catalog"]),
        "selected_original_relations": [{"edge_id": row["edge_id"], "semantic_sha256": digest(row)}
                                        for row in source_context["selected_relations"]],
        "representative_metadata_sha256": digest(source_context["representative_metadata"]),
        "representative_unique_videos": len(source_context["representative_metadata"]),
        "full_sample_gate": deepcopy(packet["sample_gate"]),
        "reference_fulltext_utf8_sha256": hashlib.sha256(original["reference_fulltext"].encode("utf-8")).hexdigest(),
        "verified_legal_context_sha256": digest(original["verified_legal_context"]),
        "expression_standards_sha256": digest(original["expression_standards"]),
        "production_preferences_sha256": digest(original["production_preferences"]),
        "fixed_component_key_occurrences": occurrences,
        "unchanged_other_payload_fields": sorted(set(original) - {"source_packet"}),
        "native_documents_preserved_completely": True,
        "complete_original_packet_validated": True,
        "model_calls": 0, "collection_calls": 0, "media_calls": 0,
        "old_records_modified": False, "budget_reset": False,
        "human_quality_approved": False, "creative_quality_passed": False,
        "limitations": ["This verifies deterministic source projection, not actual provider acceptance or creative quality.",
            "Frozen manifest/ledger/worker authorization must be verified separately by the caller."]}


def projection_evidence(packet, context, *, now):
    """Evidence for the compatible initial context, with zero side effects."""
    if not isinstance(context, dict) or not set(CONTEXT_KEYS) <= set(context):
        raise ValueError("complete projected context required")
    if not isinstance(context["source_packet"], dict):
        raise ValueError("projected source packet object required")
    identity = context["source_packet"].get("source_identity", {})
    if not isinstance(identity, dict):
        raise ValueError("projected source identity object required")
    binding = identity.get("source_binding_sha256")
    original = deepcopy(context)
    original["source_packet"] = deepcopy(packet)
    return payload_projection_evidence(original, context, binding, now=now)
