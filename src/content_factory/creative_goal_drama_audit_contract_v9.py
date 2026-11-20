"""Independent native commitment audit; source v7 and drama v8 stay frozen.

Exact catalogs and reported verdicts are checked here. Interpreting Chinese
claims, extracting operations, and recognizing contradictions remain model
judgments. This module has no provider, request, or dispatch capability.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_drama_audit_contract_v8 as base

VERSION = "creative_goal_drama_audit/v9"
DRAMA_AUDIT_VERSION = VERSION
SOURCE_AUDIT_VERSION = base.SOURCE_AUDIT_VERSION
BUNDLE_VERSION = VERSION + "/audit_bundle"
GOAL_CHECKS = base.GOAL_CHECKS
digest, citations, prior = base.digest, base.citations, base.prior
build_production_scope_catalog = base.build_production_scope_catalog


def build_evidence_catalog(native_goal):
    """Keep every original G number/string and add exact original claim leaves."""
    catalog = deepcopy(citations.build_evidence_catalog(native_goal))
    seen = set()
    for index, claim in enumerate(native_goal["claims"]):
        identifier, text = claim["id"], claim["text"]
        if (type(identifier) is not str or not identifier.strip() or identifier in seen
                or type(text) is not str or not text.strip()):
            raise ValueError("native claims need unique nonempty IDs and original text")
        seen.add(identifier)
        catalog["C:" + identifier] = {"document_path": f"claims.{index}.text", "quote": text}
    return catalog


def build_evidence_manifest(native_goal):
    """A path-only request directory; read quotations from the complete goal."""
    return {ref: {"document_path": row["document_path"]}
            for ref, row in build_evidence_catalog(native_goal).items()}


def build_commitment_usage_catalog(native_goal):
    """Compile only explicit claim_refs; never infer relevance from prose."""
    catalog = build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    whole = native_goal["whole_plan"]
    declared = {claim["id"] for claim in native_goal["claims"]}
    uses = []
    for index, beat in enumerate(whole["beats"]):
        uses.append(("beat:" + beat["id"], f"whole_plan.beats.{index}",
                     beat.get("claim_refs", []), scopes["beat_scopes"][beat["id"]]["evidence_refs"]))
    ending_refs = [ref for ref, row in catalog.items()
                   if row["document_path"].startswith("whole_plan.ending.")]
    uses.append(("ending", "whole_plan.ending", whole["ending"].get("claim_refs", []), ending_refs))
    for _, _, refs, _ in uses:
        if (type(refs) is not list or any(type(ref) is not str or ref not in declared for ref in refs)
                or len(refs) != len(set(refs))):
            raise ValueError("commitment usage needs exact unique declared claim_refs")
    result = {}
    for claim in native_goal["claims"]:
        if claim["kind"] != "creative_choice":
            continue
        actual = {key: {"document_path": path, "evidence_refs": deepcopy(refs)}
                  for key, path, ids, refs in uses if claim["id"] in ids}
        if not actual:
            continue
        if any(not row["evidence_refs"] for row in actual.values()):
            raise ValueError("each actual commitment usage needs original G string evidence")
        claim_ref = "C:" + claim["id"]
        result[claim["id"]] = {"claim_ref": claim_ref,
            "document_path": catalog[claim_ref]["document_path"], "usages": actual}
    return result


def _refs(refs):
    return {"type": "array", "items": {"enum": list(refs)}, "minItems": 1,
            "maxItems": len(refs), "uniqueItems": True}


def build_drama_schema(native_goal, *, context_sha256):
    """Distinct native shape with finite source-derived commitment coverage."""
    schema = base.build_drama_schema(native_goal, context_sha256=context_sha256)
    catalog = build_evidence_catalog(native_goal)
    usages = build_commitment_usage_catalog(native_goal)
    schema["properties"]["schema"] = {"const": DRAMA_AUDIT_VERSION}
    schema["$defs"]["evidence_refs"] = _refs(catalog)
    judgment = schema["$defs"]["goal_judgment"]
    judgment["properties"]["counterevidence_refs"].update(
        items={"enum": list(catalog)}, maxItems=len(catalog))
    # Keep one copy of the shared judgment and reference vocabulary. Per-claim
    # schema rows carry only their exact C identity and source-derived usages.
    common = deepcopy(judgment)
    common["properties"].update(claim_ref={"type": "string"}, checked_usages={"type": "object"})
    common["required"].extend(["claim_ref", "checked_usages"])
    schema["$defs"]["commitment_judgment"] = common
    checks = {}
    for identifier, usage in usages.items():
        checks[identifier] = {"allOf": [{"$ref": "#/$defs/commitment_judgment"},
            {"properties": {"claim_ref": {"const": usage["claim_ref"]},
                "checked_usages": base._object({key: _refs(item["evidence_refs"])
                                                 for key, item in usage["usages"].items()}),
                "evidence_refs": {"contains": {"const": usage["claim_ref"]}}}}]}
    schema["properties"]["commitment_checks"] = base._object(checks)
    schema["required"].append("commitment_checks")
    Draft202012Validator.check_schema(schema)
    return schema


def _scope_evidence(document, native_goal):
    """Preserve v8 own-beat G evidence without adding C to scope enums."""
    catalog = citations.build_evidence_catalog(native_goal)
    scopes = build_production_scope_catalog(native_goal)
    compiled, undeclared = {}, []
    for beat_id, observations in document["scope_observations"].items():
        compiled[beat_id] = {}
        for table, field in (("audible_speakers", "declared_character_id"),
                             ("operated_props", "declared_prop_id")):
            rows = []
            for item in observations[table]:
                ref = item["source_ref"]
                if ref not in scopes["beat_scopes"][beat_id]["evidence_refs"]:
                    raise ValueError("scope observation must use its own actual beat G evidence")
                original = catalog[ref]
                if not item["quote"].strip() or item["quote"] not in original["quote"]:
                    raise ValueError("scope quote must occur verbatim in its exact native G source")
                rows.append({**deepcopy(item), "document_path": original["document_path"],
                             "original_quote": original["quote"]})
                if item[field] is None:
                    undeclared.append({"beat_id": beat_id, "table": table, **deepcopy(item)})
            compiled[beat_id][table] = rows
    if undeclared and document["goal_checks"]["closed_production_scope"]["status"] == "pass":
        raise ValueError("observed undeclared human voice or operated prop cannot coexist with closed scope pass")
    return compiled, undeclared


def validate_drama(document, native_goal, *, context_sha256):
    Draft202012Validator(build_drama_schema(native_goal, context_sha256=context_sha256)).validate(document)
    catalog = build_evidence_catalog(native_goal)
    scope_evidence, undeclared = _scope_evidence(document, native_goal)
    usage_catalog = build_commitment_usage_catalog(native_goal)
    evidence, counterevidence, commitment_evidence = {}, {}, {}
    failures, uncertainties = [], []
    for table in ("goal_checks", "commitment_checks"):
        for key, row in document[table].items():
            if not row["counterexample_analysis"].strip():
                raise ValueError("drama checks need substantive comparison for counterexamples")
            refs = list(dict.fromkeys(row["evidence_refs"] + row["counterevidence_refs"]))
            compiled = [deepcopy(catalog[ref]) for ref in refs]
            counters = [deepcopy(catalog[ref]) for ref in row["counterevidence_refs"]]
            if table == "goal_checks":
                evidence[key], counterevidence[key] = compiled, counters
            else:
                commitment_evidence[key] = {"claim_ref": row["claim_ref"], "evidence": compiled,
                    "counterevidence": counters, "checked_usages": {
                        usage: [deepcopy(catalog[ref]) for ref in checked]
                        for usage, checked in row["checked_usages"].items()}}
            finding = {"target": "complete_native_goal", "audit_kind": "drama", "table": table,
                       "check": key, **deepcopy(row), "evidence": compiled}
            if row["status"] == "fail":
                failures.append(finding)
            elif row["status"] == "unknown":
                uncertainties.append(finding)
    return {"valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": evidence,
        "counterevidence_citations": counterevidence,
        "commitment_check_evidence": commitment_evidence,
        "commitment_usage_catalog": usage_catalog, "commitment_usage_coverage_complete": True,
        "commitment_semantic_extraction_proven": False,
        "scope_observation_evidence": scope_evidence, "undeclared_scope_observations": undeclared,
        "scope_observations_complete_extraction_proven": False, "audit_kind": "drama",
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(document),
        "audit_context_sha256": context_sha256, "native_review_modified": False,
        "citation_metadata_compiled": True, "evidence_catalog_count": len(catalog),
        "semantic_truth_deterministically_proven": False, "human_approved": False}


def build_bundle(native_source_audit, native_drama_audit):
    return {"schema": BUNDLE_VERSION, "native_source_audit": deepcopy(native_source_audit),
            "native_drama_audit": deepcopy(native_drama_audit)}


def validate_bundle(bundle, native_goal, *, source_context_sha256, drama_context_sha256):
    base._context_identity(source_context_sha256)
    base._context_identity(drama_context_sha256)
    if source_context_sha256 == drama_context_sha256:
        raise ValueError("source and drama audits need their distinct actual payload identities")
    if (type(bundle) is not dict or set(bundle) != {"schema", "native_source_audit", "native_drama_audit"}
            or bundle["schema"] != BUNDLE_VERSION):
        raise ValueError("v9 bundle requires two complete native audit documents; no old bundle conversion")
    source = prior.validate_goal_source_audit(bundle["native_source_audit"], native_goal,
                                             context_sha256=source_context_sha256)
    drama = validate_drama(bundle["native_drama_audit"], native_goal, context_sha256=drama_context_sha256)
    return {"valid": True, "accepted": source["accepted"] and drama["accepted"],
        "findings": source["findings"] + drama["findings"],
        "uncertainties": source["uncertainties"] + drama["uncertainties"],
        "source_decision": source, "drama_decision": drama,
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(bundle),
        "source_context_sha256": source_context_sha256, "drama_context_sha256": drama_context_sha256,
        "native_review_modified": False, "combined_decisions_only": True,
        "native_single_combined_audit": False, "human_approved": False,
        "semantic_truth_deterministically_proven": False}
