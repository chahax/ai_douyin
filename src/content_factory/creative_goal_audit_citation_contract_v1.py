"""Source-bound semantic judgments with compiler-owned citation metadata."""
from copy import deepcopy
import hashlib
import json
from jsonschema import Draft202012Validator

VERSION = "creative_goal_audit_citation/v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def build_evidence_catalog(native_goal):
    """Exact current native strings, without inventing or sanitizing quotations."""
    rows = []
    def visit(value, parts):
        if isinstance(value, str) and value.strip():
            rows.append((".".join(map(str, parts)), value))
        elif isinstance(value, dict):
            for key in sorted(value):
                if key not in ("id", "scene_id", "actor_id", "claim_refs", "evidence_beat_ids"):
                    visit(value[key], [*parts, key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, [*parts, index])
    visit(native_goal["whole_plan"], ["whole_plan"])
    return {"G" + str(i).zfill(3): {"document_path": path, "quote": quote}
            for i, (path, quote) in enumerate(rows, 1)}


def _judgment():
    row = _obj({"status": {"enum": ["pass", "fail", "unknown"]},
        "reason": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "required_revision": {"type": "string"}})
    row["allOf"] = [
        {"if": {"properties": {"status": {"const": "pass"}}},
         "then": {"properties": {"required_revision": {"const": ""}}}},
        {"if": {"properties": {"status": {"const": "fail"}}},
         "then": {"properties": {"required_revision": {"minLength": 1, "pattern": r"\S"}}}}]
    return row


def build_schema(native_goal, *, context_sha256, goal_checks):
    catalog = build_evidence_catalog(native_goal)
    if not catalog:
        raise ValueError("native whole plan needs exact string evidence")
    refs = {"type": "array", "items": {"enum": list(catalog)},
            "minItems": 1, "maxItems": 8, "uniqueItems": True}
    claim_rows = {row["id"]: {"$ref": "#/$defs/judgment"} for row in native_goal["claims"]}
    goal_row = _judgment()
    goal_row["properties"]["evidence_refs"] = {"$ref": "#/$defs/evidence_refs"}
    goal_row["required"].append("evidence_refs")
    schema = _obj({"schema": {"const": VERSION},
        "goal_sha256": {"const": digest(native_goal)},
        "audit_context_sha256": {"const": context_sha256},
        "claim_checks": _obj(claim_rows),
        "goal_checks": _obj({key: {"$ref": "#/$defs/goal_judgment"} for key in goal_checks})})
    schema["$defs"] = {"judgment": _judgment(), "goal_judgment": goal_row, "evidence_refs": refs}
    Draft202012Validator.check_schema(schema)
    return schema


def validate(document, native_goal, *, context_sha256, goal_checks):
    Draft202012Validator(build_schema(native_goal, context_sha256=context_sha256, goal_checks=goal_checks)).validate(document)
    catalog = build_evidence_catalog(native_goal)
    failures, uncertainties, citations = [], [], {}
    for index, claim in enumerate(native_goal["claims"]):
        citations["claim:" + claim["id"]] = [{"document_path": f"claims.{index}.text", "quote": claim["text"]}]
    for key, row in document["goal_checks"].items():
        citations["goal:" + key] = [deepcopy(catalog[ref]) for ref in row["evidence_refs"]]
    for table in ("claim_checks", "goal_checks"):
        for key, row in document[table].items():
            result = {"target": "complete_native_goal", "table": table, "check": key,
                **deepcopy(row), "evidence": deepcopy(citations[("claim:" if table == "claim_checks" else "goal:") + key])}
            if row["status"] == "fail":
                failures.append(result)
            elif row["status"] == "unknown":
                uncertainties.append(result)
    return {"valid": True, "accepted": not failures and not uncertainties,
        "findings": failures, "uncertainties": uncertainties, "citations": citations,
        "native_goal_sha256": digest(native_goal), "audit_sha256": digest(document),
        "audit_context_sha256": context_sha256,
        "citation_metadata_compiled": True, "native_review_modified": False,
        "semantic_truth_deterministically_proven": False, "human_approved": False}
