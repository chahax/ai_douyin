"""Native application scope and whole-goal comparisons, preserving frozen v1.

Explicit usage references retain their own G evidence. Background definitions
and other beats can be compared through a separate current-G channel. Scope
and meaning are still model judgments, never inferred by this pure validator.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_commitment_audit_v1 as prior

VERSION = "creative_goal_commitment_audit/v2"
REQUIREMENT_SCOPES = ("background_consistency", "local_event", "cross_beat_relation", "mixed")
RELATIONSHIPS = prior.RELATIONSHIPS
CommitmentReportContractError = prior.CommitmentReportContractError
digest = prior.digest
build_evidence_catalog = prior.build_evidence_catalog
build_commitment_usage_catalog = prior.build_commitment_usage_catalog


def build_commitment_audit_schema(native_goal, *, context_sha256):
    """Add typed application scope without relaxing v1 evidence/verdict gates."""
    schema = deepcopy(prior.build_commitment_audit_schema(
        native_goal, context_sha256=context_sha256))
    schema["properties"]["schema"] = {"const": VERSION}
    catalog = build_evidence_catalog(native_goal)
    global_g = [ref for ref in catalog if ref.startswith("G")]
    for row in schema["properties"]["commitment_checks"]["properties"].values():
        for usage in row["properties"]["actual_usages"]["properties"].values():
            usage["properties"].update(
                requirement_scope={"enum": list(REQUIREMENT_SCOPES)},
                comparison_refs={"type": "array", "items": {"enum": global_g},
                                 "minItems": 0, "maxItems": len(global_g), "uniqueItems": True})
            usage["required"].extend(["requirement_scope", "comparison_refs"])
    Draft202012Validator.check_schema(schema)
    return schema


def validate_commitment_audit(document, native_goal, *, context_sha256):
    """Preserve distinct own-usage and global-comparison citation channels."""
    Draft202012Validator(build_commitment_audit_schema(
        native_goal, context_sha256=context_sha256)).validate(document)
    prior._validate_report_relationships(document)
    catalog = build_evidence_catalog(native_goal)
    usage_catalog = build_commitment_usage_catalog(native_goal)
    citations, comparisons, counters, failures, uncertainties = {}, {}, {}, [], []
    for identifier, row in document["commitment_checks"].items():
        usage_evidence, comparison_evidence = {}, {}
        for key, usage in row["actual_usages"].items():
            usage_evidence[key] = [{"source_ref": ref, **deepcopy(catalog[ref])}
                                   for ref in usage["evidence_refs"]]
            comparison_evidence[key] = [{"source_ref": ref, **deepcopy(catalog[ref])}
                                        for ref in usage["comparison_refs"]]
        citations[identifier] = {
            "claim": {"source_ref": row["claim_ref"], **deepcopy(catalog[row["claim_ref"]])},
            "actual_usages": usage_evidence,
        }
        comparisons[identifier] = comparison_evidence
        counters[identifier] = [{"source_ref": ref, **deepcopy(catalog[ref])}
                                for ref in row["counterevidence_refs"]]
        finding = {"target": "complete_native_goal", "audit_kind": "commitment",
            "table": "commitment_checks", "check": identifier, **deepcopy(row),
            "evidence": deepcopy(citations[identifier]),
            "comparison_evidence": deepcopy(comparisons[identifier]),
            "counterevidence": deepcopy(counters[identifier])}
        if row["status"] == "fail":
            failures.append(finding)
        elif row["status"] == "unknown":
            uncertainties.append(finding)
    return {"valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": citations,
        "comparison_citations": comparisons, "counterevidence_citations": counters,
        "commitment_usage_catalog": usage_catalog, "commitment_usage_coverage_complete": True,
        "reported_relations_self_consistent": True, "citation_channels_kept_distinct": True,
        "audit_kind": "commitment", "native_goal_sha256": digest(native_goal),
        "audit_sha256": digest(document), "audit_context_sha256": context_sha256,
        "native_review_modified": False, "citation_metadata_compiled": True,
        "requirement_scope_semantically_proven": False,
        "semantic_truth_deterministically_proven": False,
        "commitment_semantic_extraction_proven": False, "human_approved": False}
