"""Finite native-goal evidence, without arbitrary per-judgment reference limits.

Source audit remains the frozen v7 contract. A new drama response and a distinct
bundle retain their own native identities; old responses are never transformed.
This module validates/compiles only and does not prepare or dispatch requests.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_context_workflow_v7 as prior

VERSION = "creative_goal_drama_audit/v8"
DRAMA_AUDIT_VERSION = VERSION
SOURCE_AUDIT_VERSION = prior.SOURCE_AUDIT_VERSION
BUNDLE_VERSION = VERSION + "/audit_bundle"
GOAL_CHECKS = tuple(prior.GOAL_CHECKS)
digest = prior.digest
citations = prior.citations


def _object(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def build_production_scope_catalog(native_goal):
    """Declared IDs and exact beat-path evidence; no prose-based classification."""
    whole = native_goal["whole_plan"]
    actor_ids = [row["id"] for row in whole["characters"]]
    prop_ids = [row["id"] for row in whole["props"]]
    beats = whole["beats"]
    beat_ids = [row["id"] for row in beats]
    for label, values in (("characters", actor_ids), ("props", prop_ids), ("beats", beat_ids)):
        if (any(type(value) is not str or not value.strip() for value in values)
                or len(values) != len(set(values))):
            raise ValueError("actual native " + label + " need unique nonempty IDs")
    if not beat_ids:
        raise ValueError("native production scope needs complete beats")
    catalog = citations.build_evidence_catalog(native_goal)
    scopes = {}
    for index, beat_id in enumerate(beat_ids):
        path = f"whole_plan.beats.{index}"
        refs = [ref for ref, row in catalog.items() if row["document_path"].startswith(path + ".")]
        if not refs:
            raise ValueError("each actual beat needs native original string evidence")
        scopes[beat_id] = {"document_path": path, "evidence_refs": refs}
    return {"declared_actor_ids": actor_ids, "declared_prop_ids": prop_ids, "beat_scopes": scopes}


def _scope_schema(native_goal):
    catalog = build_production_scope_catalog(native_goal)
    beat_rows = {}
    for beat_id, scope in catalog["beat_scopes"].items():
        common = {
            "source_ref": {"enum": scope["evidence_refs"]},
            "quote": {"type": "string", "minLength": 1, "pattern": r"\S"},
        }
        speaker = _object({**deepcopy(common),
            "declared_character_id": {"enum": [*catalog["declared_actor_ids"], None]}})
        prop = _object({**deepcopy(common),
            "declared_prop_id": {"enum": [*catalog["declared_prop_ids"], None]}})
        beat_rows[beat_id] = _object({
            "audible_speakers": {"type": "array", "items": speaker, "uniqueItems": True},
            "operated_props": {"type": "array", "items": prop, "uniqueItems": True},
        })
    return _object(beat_rows)


def _context_identity(context_sha256):
    if (type(context_sha256) is not str or len(context_sha256) != 64
            or any(char not in "0123456789abcdef" for char in context_sha256)):
        raise ValueError("actual audit context needs a lowercase SHA-256 identity")


def build_drama_schema(native_goal, *, context_sha256):
    _context_identity(context_sha256)
    catalog = citations.build_evidence_catalog(native_goal)
    if not catalog:
        raise ValueError("complete native plan needs exact string evidence")
    limit = len(catalog)
    judgment = citations._judgment()
    judgment["properties"].update({
        "evidence_refs": {"$ref": "#/$defs/evidence_refs"},
        "counterexample_analysis": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "counterevidence_refs": {"type": "array", "items": {"enum": list(catalog)},
                                 "maxItems": limit, "uniqueItems": True},
    })
    judgment["required"].extend(["evidence_refs", "counterexample_analysis", "counterevidence_refs"])
    # Preserve pass/fail revision conditions from the base judgment; append,
    # rather than replace them when enforcing unresolved counterevidence.
    judgment["allOf"].append({
        "if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
        "then": {"properties": {"counterevidence_refs": {"maxItems": 0}}},
    })
    schema = _object({
        "schema": {"const": DRAMA_AUDIT_VERSION},
        "goal_sha256": {"const": digest(native_goal)},
        "audit_context_sha256": {"const": context_sha256},
        "goal_checks": _object({key: {"$ref": "#/$defs/goal_judgment"} for key in GOAL_CHECKS}),
        "scope_observations": _scope_schema(native_goal),
    })
    schema["$defs"] = {
        "goal_judgment": judgment,
        "evidence_refs": {"type": "array", "items": {"enum": list(catalog)},
                          "minItems": 1, "maxItems": limit, "uniqueItems": True},
    }
    Draft202012Validator.check_schema(schema)
    return schema


def validate_drama(document, native_goal, *, context_sha256):
    Draft202012Validator(build_drama_schema(native_goal, context_sha256=context_sha256)).validate(document)
    catalog = citations.build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    scope_evidence = {}
    undeclared = []
    for beat_id, observations in document["scope_observations"].items():
        scope_evidence[beat_id] = {}
        for table, field in (("audible_speakers", "declared_character_id"), ("operated_props", "declared_prop_id")):
            compiled = []
            for item in observations[table]:
                ref = item["source_ref"]
                if ref not in scopes["beat_scopes"][beat_id]["evidence_refs"]:
                    raise ValueError("scope observation must use its own actual beat evidence")
                original = catalog[ref]
                if not item["quote"].strip() or item["quote"] not in original["quote"]:
                    raise ValueError("scope observation quote must occur verbatim in its exact native G source")
                compiled.append({**deepcopy(item), "document_path": original["document_path"],
                                 "original_quote": original["quote"]})
                if item[field] is None:
                    undeclared.append({"beat_id": beat_id, "table": table, **deepcopy(item)})
            scope_evidence[beat_id][table] = compiled
    if undeclared and document["goal_checks"]["closed_production_scope"]["status"] == "pass":
        raise ValueError("observed undeclared human voice or operated prop cannot coexist with closed scope pass")
    citations_by_key, countercitations_by_key, failures, uncertainties = {}, {}, [], []
    for key, row in document["goal_checks"].items():
        if not row["counterexample_analysis"].strip():
            raise ValueError("drama checks need substantive comparison for counterexamples")
        evidence = [deepcopy(catalog[ref]) for ref in dict.fromkeys(
            row["evidence_refs"] + row["counterevidence_refs"])]
        counterevidence = [deepcopy(catalog[ref]) for ref in row["counterevidence_refs"]]
        citations_by_key[key] = evidence
        countercitations_by_key[key] = counterevidence
        finding = {"target": "complete_native_goal", "audit_kind": "drama", "table": "goal_checks",
                   "check": key, **deepcopy(row), "evidence": evidence}
        if row["status"] == "fail":
            failures.append(finding)
        elif row["status"] == "unknown":
            uncertainties.append(finding)
    return {
        "valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": citations_by_key,
        "counterevidence_citations": countercitations_by_key,
        "scope_observation_evidence": scope_evidence,
        "undeclared_scope_observations": undeclared,
        "scope_observations_complete_extraction_proven": False,
        "audit_kind": "drama", "native_goal_sha256": digest(native_goal),
        "audit_sha256": digest(document), "audit_context_sha256": context_sha256,
        "native_review_modified": False, "citation_metadata_compiled": True,
        "evidence_catalog_count": len(catalog),
        "semantic_truth_deterministically_proven": False, "human_approved": False,
    }


def build_bundle(native_source_audit, native_drama_audit):
    return {"schema": BUNDLE_VERSION,
            "native_source_audit": deepcopy(native_source_audit),
            "native_drama_audit": deepcopy(native_drama_audit)}


def validate_bundle(bundle, native_goal, *, source_context_sha256, drama_context_sha256):
    """The caller recomputes both SHA values from its actual request payloads.

    Contract validity is separate from native transport/receipt provenance. Both
    source and drama documents must match the unchanged goal and current context.
    """
    _context_identity(source_context_sha256)
    _context_identity(drama_context_sha256)
    if source_context_sha256 == drama_context_sha256:
        raise ValueError("source and drama audits need their distinct actual payload identities")
    if (type(bundle) is not dict or set(bundle) != {"schema", "native_source_audit", "native_drama_audit"}
            or bundle["schema"] != BUNDLE_VERSION):
        raise ValueError("new bundle requires two complete native audit documents; no old combined audit")
    source = prior.validate_goal_source_audit(bundle["native_source_audit"], native_goal,
                                             context_sha256=source_context_sha256)
    drama = validate_drama(bundle["native_drama_audit"], native_goal,
                           context_sha256=drama_context_sha256)
    return {
        "valid": True, "accepted": source["accepted"] and drama["accepted"],
        "findings": source["findings"] + drama["findings"],
        "uncertainties": source["uncertainties"] + drama["uncertainties"],
        "source_decision": source, "drama_decision": drama,
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(bundle),
        "source_context_sha256": source_context_sha256,
        "drama_context_sha256": drama_context_sha256,
        "native_review_modified": False, "combined_decisions_only": True,
        "native_single_combined_audit": False, "human_approved": False,
        "semantic_truth_deterministically_proven": False,
    }
