"""Single-record blind scope, preserving the v1 semantic task unchanged.

Only the response representation changes. Compiled maps are decision metadata,
never a second native classification or a converted v1 provider document.
"""
from __future__ import annotations

from copy import deepcopy
from jsonschema import Draft202012Validator

from . import creative_legal_speech_scope_v1 as prior

VERSION = "creative_legal_speech_scope/v2"
ACTS, NONLEGAL_ACTS, digest = prior.ACTS, prior.NONLEGAL_ACTS, prior.digest
evidence, views = prior.evidence, prior.views
ScopeContractError = prior.ScopeContractError
_object, _text, _case_catalog = prior._object, prior._text, prior._case_catalog

OLD_RESPONSE_RULE = (
    "speech_act_by_ref完整覆盖当前全部固定键，每键仅填一个短码；scope_observations只为全部L/U各填一条，不为非法律项重复长解释。")
RESPONSE_RULE = (
    "records_by_ref完整覆盖当前全部固定键，每键只提交一个含act的原生记录；F/R/P/M/N记录只有act，"
    "L/U记录在自身detail中填写相应详情。不要另交独立分类表或说明列表，不为非法律项重复长解释。")
if prior.SCOPE_RULE.count(OLD_RESPONSE_RULE) != 1:
    raise RuntimeError("frozen semantic rule no longer has the exact response-protocol sentence")
SCOPE_RULE = prior.SCOPE_RULE.replace(OLD_RESPONSE_RULE, RESPONSE_RULE)


def _current_context(built):
    built = deepcopy(built)
    built["payload"]["scope_task"]["schema"] = VERSION + "/task"
    built["manifest"].update(schema=VERSION + "/context_manifest",
        scope_context_sha256=digest(built["payload"]))
    return built


def build_scope_context(native_goal):
    return _current_context(prior.build_scope_context(native_goal))


def build_case_scope_context(blinded_cases):
    return _current_context(prior.build_case_scope_context(blinded_cases))


def _definitions(catalog):
    contextual = _object({"source_ref": {"enum": list(catalog)}, "quote": _text()})
    assertion = _object({"quote": _text(), "proposition": _text(400),
        "assertion_scope": {"enum": ["general_rule", "case_application"]},
        "expression": {"enum": ["explicit", "presupposed"]}, "reason": _text(300)})
    ambiguity = _object({"quote": _text(), "nonlegal_reading": _text(400), "legal_reading": _text(400),
        "ambiguity_reason": _text(400), "context_evidence": {"type": "array", "items": contextual,
            "minItems": 1, "maxItems": 6}})
    return {"assertion": assertion, "ambiguity": ambiguity,
        "nonlegal_record": _object({"act": {"enum": list(ACTS[:5])}}),
        "legal_record": _object({"act": {"const": "L"}, "detail": {"$ref": "#/$defs/assertion"}}),
        "ambiguous_record": _object({"act": {"const": "U"}, "detail": {"$ref": "#/$defs/ambiguity"}})}


def _schema(built, catalog, verified, *, context_sha256):
    if built["manifest"]["scope_context_sha256"] != context_sha256:
        raise ScopeContractError("scope schema must bind the complete current blind context")
    def record(ref):
        kinds = ("legal_record", "ambiguous_record") if ref in verified else ("nonlegal_record", "legal_record", "ambiguous_record")
        return {"oneOf": [{"$ref": "#/$defs/" + key} for key in kinds]}
    schema = _object({"schema": {"const": VERSION}, "frame_kind": {"const": built["manifest"]["frame_kind"]},
        "input_sha256": {"const": built["manifest"]["input_sha256"]},
        "scope_context_sha256": {"const": context_sha256},
        "records_by_ref": _object({ref: record(ref) for ref in catalog})})
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": _definitions(catalog)})
    Draft202012Validator.check_schema(schema)
    return schema


def build_scope_schema(native_goal, *, context_sha256):
    return _schema(build_scope_context(native_goal), evidence.build_evidence_catalog(native_goal),
        {"C:" + row["id"] for row in native_goal["claims"] if row["kind"] == "verified_legal"},
        context_sha256=context_sha256)


def build_case_scope_schema(blinded_cases, *, context_sha256):
    return _schema(build_case_scope_context(blinded_cases), _case_catalog(blinded_cases), set(), context_sha256=context_sha256)


def compile_act_by_ref(document):
    """Read the single native record, not full source/frame/quote admission.

    Call validate_scope/validate_case_scope first; its decision also carries this
    exact derived map. This accessor never repairs a contradictory native row.
    """
    if type(document) is not dict or document.get("schema") != VERSION or type(document.get("records_by_ref")) is not dict:
        raise ScopeContractError("actual v2 native single-record document required")
    result = {}
    for ref, row in document["records_by_ref"].items():
        if type(ref) is not str or type(row) is not dict or row.get("act") not in ACTS:
            raise ScopeContractError("one valid act per exact native record required")
        expected = {"act"} if row["act"] in NONLEGAL_ACTS else {"act", "detail"}
        if set(row) != expected:
            raise ScopeContractError("single act record cannot carry incompatible or separate detail")
        result[ref] = row["act"]
    return result


def _validate(document, built, catalog, schema):
    Draft202012Validator(schema).validate(document)
    acts = compile_act_by_ref(document)
    assertions, ambiguities = {}, {}
    for ref, row in document["records_by_ref"].items():
        if row["act"] in NONLEGAL_ACTS:
            continue
        content = row["detail"]
        if content["quote"] not in catalog[ref]["quote"]:
            raise ScopeContractError("scope quote must occur in its own native source: " + ref)
        if row["act"] == "L":
            assertions[ref] = deepcopy(content)
        else:
            if content["nonlegal_reading"].strip() == content["legal_reading"].strip():
                raise ScopeContractError("textual ambiguity needs two distinct substantive readings: " + ref)
            used = set()
            for item in content["context_evidence"]:
                identity = (item["source_ref"], item["quote"])
                target = catalog[item["source_ref"]]
                if identity in used or not any(item["quote"] in target.get(key, "") for key in ("quote", "role_context")):
                    raise ScopeContractError("ambiguity context must be exact, current and nonduplicated: " + ref)
                used.add(identity)
            ambiguities[ref] = deepcopy(content)
    return {"schema": VERSION + "/decision", "valid": True, "scope_native_sha256": digest(document),
        "frame_kind": built["manifest"]["frame_kind"], "input_sha256": built["manifest"]["input_sha256"],
        "scope_context_sha256": built["manifest"]["scope_context_sha256"], "source_ref_count": len(catalog),
        "complete_key_coverage_verified": True, "single_native_record_per_ref": True,
        "act_by_ref": acts, "act_map_is_compiled_metadata_not_native_report": True,
        "legal_assertions": assertions, "textual_ambiguities": ambiguities,
        "scope_ready_for_authority_review": not ambiguities,
        "route": "complete_native_author_clarification" if ambiguities else "source_and_authority_review",
        "known_text_content_requires_clarification": bool(ambiguities),
        "external_fact_or_legal_unknown_assessed": False, "scope_report_modified": False,
        "semantic_classification_proven": False, "human_quality_approved": False, "creative_quality_passed": False}


def validate_scope(document, native_goal, *, context_sha256):
    return _validate(document, build_scope_context(native_goal), evidence.build_evidence_catalog(native_goal),
        build_scope_schema(native_goal, context_sha256=context_sha256))


def validate_case_scope(document, blinded_cases, *, context_sha256):
    built = build_case_scope_context(blinded_cases)
    return _validate(document, built, _case_catalog(blinded_cases),
        build_case_scope_schema(blinded_cases, context_sha256=context_sha256))


def authority_projection(document, native_goal):
    context_sha = build_scope_context(native_goal)["manifest"]["scope_context_sha256"]
    decision = validate_scope(document, native_goal, context_sha256=context_sha)
    if not decision["scope_ready_for_authority_review"]:
        raise ScopeContractError("genuine native text ambiguity requires author clarification before authority review")
    return {"schema": VERSION + "/authority_projection", "scope_native_sha256": digest(document),
        "scope_context_sha256": context_sha, "native_goal_sha256": digest(native_goal),
        "act_by_ref": deepcopy(decision["act_by_ref"]), "legal_assertions": deepcopy(decision["legal_assertions"]),
        "original_scope_retained_locally": True, "semantic_classification_proven": False}
