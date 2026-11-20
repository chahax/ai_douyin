"""Focused native creative-commitment relations, with exact current evidence.

The model interprets each C requirement and its actual G usages. This module
checks identity, coverage and reported relation/verdict consistency only; it
does not infer Chinese meaning, convert old reviews, or contact providers.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_drama_audit_contract_v10 as current

VERSION = "creative_goal_commitment_audit/v1"
RELATIONSHIPS = ("compatible", "contradicts", "not_demonstrated", "unknown")
digest = current.digest
build_evidence_catalog = current.build_evidence_catalog
build_commitment_usage_catalog = current.build_commitment_usage_catalog


class CommitmentReportContractError(ValueError):
    """The native report contradicts its own typed relationships."""

    code = "COMMITMENT_RELATION_REPORT_CONTRACT_REJECTED"

    def __init__(self, path, message, **details):
        self.diagnostics = [{"code": self.code, "path": path,
                             "message": message, **details}]
        self.detail = {"diagnostics": deepcopy(self.diagnostics)}
        super().__init__(f"{self.code}: {path}: {message}")


def _object(fields):
    return {"type": "object", "properties": fields,
            "required": list(fields), "additionalProperties": False}


def _context_identity(value):
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise ValueError("actual commitment audit needs a lowercase SHA-256 context")


def _refs(identifiers, *, minimum):
    return {"type": "array", "items": {"enum": list(identifiers)},
            "minItems": minimum, "maxItems": len(identifiers), "uniqueItems": True}


def build_commitment_audit_schema(native_goal, *, context_sha256):
    """Cover each explicit creative_choice usage; never infer a new usage."""
    _context_identity(context_sha256)
    catalog = build_evidence_catalog(native_goal)
    usages = build_commitment_usage_catalog(native_goal)
    if not catalog:
        raise ValueError("current complete goal needs original C/G evidence")
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    rows = {}
    for identifier, usage in usages.items():
        actual_usages = {}
        for key, actual in usage["usages"].items():
            actual_usages[key] = _object({
                "evidence_refs": _refs(actual["evidence_refs"], minimum=1),
                "actual_interpretation": deepcopy(text),
                "relationship": {"enum": list(RELATIONSHIPS)},
            })
        row = _object({
            "claim_ref": {"const": usage["claim_ref"]},
            "literal_requirement": deepcopy(text),
            "actual_usages": _object(actual_usages),
            "status": {"enum": ["pass", "fail", "unknown"]},
            "reason": deepcopy(text),
            "required_revision": {"type": "string"},
            "counterevidence_refs": _refs(catalog, minimum=0),
        })
        row["allOf"] = [
            {"if": {"properties": {"status": {"const": "pass"}}},
             "then": {"properties": {"required_revision": {"const": ""},
                                      "counterevidence_refs": {"maxItems": 0}}}},
            {"if": {"properties": {"status": {"const": "fail"}}},
             "then": {"properties": {"required_revision": deepcopy(text)}}},
        ]
        # Make the relation/verdict restriction visible in the actual tool
        # schema as well as checking it locally. This is not a server guarantee.
        for key in actual_usages:
            for relations, statuses in ((["contradicts", "not_demonstrated"], ["fail"]),
                                        (["unknown"], ["unknown", "fail"])):
                row["allOf"].append({
                    "if": {"properties": {"actual_usages": {"properties": {
                        key: {"properties": {"relationship": {"enum": relations}}}}}}},
                    "then": {"properties": {"status": {"enum": statuses}}},
                })
        rows[identifier] = row
    schema = _object({
        "schema": {"const": VERSION},
        "goal_sha256": {"const": digest(native_goal)},
        "audit_context_sha256": {"const": context_sha256},
        "commitment_checks": _object(rows),
    })
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_report_relationships(document):
    for identifier, row in document["commitment_checks"].items():
        path = "/commitment_checks/" + identifier
        relationships = [value["relationship"] for value in row["actual_usages"].values()]
        definite_failure = any(value in ("contradicts", "not_demonstrated")
                               for value in relationships)
        unknown = "unknown" in relationships
        if definite_failure and row["status"] != "fail":
            raise CommitmentReportContractError(path + "/status",
                "reported contradiction or unmet usage requires fail")
        if unknown and not definite_failure and row["status"] == "pass":
            raise CommitmentReportContractError(path + "/status",
                "reported unknown relationship cannot pass")
        if not definite_failure and row["status"] in ("fail", "unknown"):
            # Compatible own usages may still conflict with another current
            # commitment. Such a wider conclusion needs actual C/G witnesses.
            if (not unknown or row["status"] == "fail") and not row["counterevidence_refs"]:
                raise CommitmentReportContractError(path + "/counterevidence_refs",
                    "wider fail or unknown requires current cross-source counterevidence")


def validate_commitment_audit(document, native_goal, *, context_sha256):
    """Validate one complete native small audit without modifying either input."""
    Draft202012Validator(build_commitment_audit_schema(
        native_goal, context_sha256=context_sha256)).validate(document)
    _validate_report_relationships(document)
    catalog = build_evidence_catalog(native_goal)
    usage_catalog = build_commitment_usage_catalog(native_goal)
    citations, counters, failures, uncertainties = {}, {}, [], []
    for identifier, row in document["commitment_checks"].items():
        usage_evidence = {}
        for key, usage in row["actual_usages"].items():
            usage_evidence[key] = [{"source_ref": ref, **deepcopy(catalog[ref])}
                                   for ref in usage["evidence_refs"]]
        citations[identifier] = {
            "claim": {"source_ref": row["claim_ref"], **deepcopy(catalog[row["claim_ref"]])},
            "actual_usages": usage_evidence,
        }
        counters[identifier] = [{"source_ref": ref, **deepcopy(catalog[ref])}
                                for ref in row["counterevidence_refs"]]
        finding = {"target": "complete_native_goal", "audit_kind": "commitment",
            "table": "commitment_checks", "check": identifier, **deepcopy(row),
            "evidence": deepcopy(citations[identifier]),
            "counterevidence": deepcopy(counters[identifier])}
        if row["status"] == "fail":
            failures.append(finding)
        elif row["status"] == "unknown":
            uncertainties.append(finding)
    return {"valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": citations,
        "counterevidence_citations": counters, "commitment_usage_catalog": usage_catalog,
        "commitment_usage_coverage_complete": True, "reported_relations_self_consistent": True,
        "audit_kind": "commitment", "native_goal_sha256": digest(native_goal),
        "audit_sha256": digest(document), "audit_context_sha256": context_sha256,
        "native_review_modified": False, "citation_metadata_compiled": True,
        "semantic_truth_deterministically_proven": False,
        "commitment_semantic_extraction_proven": False, "human_approved": False}
