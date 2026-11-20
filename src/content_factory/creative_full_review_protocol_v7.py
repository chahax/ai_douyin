"""Thin native v7 world-counterproof contract over frozen full v6 checks.

Only a private, labelled checking projection removes the new world field after
the native v7 schema has validated it. Nonempty counterproof forbids pass and
native findings/identities always retain the actual unmodified v7 response.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError

from . import creative_full_review_protocol_v6 as prior

VERSION = "creative_full_review_part/v7"
BUNDLE_VERSION = "creative_full_review_bundle/v7"
ADAPTER_VERSION = "creative_full_review_protocol/v7"
PART_TABLES = prior.PART_TABLES
digest = prior.digest
WORLD_RULE = (
    "本次响应合同为creative_full_review_part/v7，所有world_scene_checks原生行须明确提交counterevidence引用数组。"
    "该数组只填source_directory合法ref的未解反证；没有则[]。非空反证只能fail/unknown，不能pass或省略。"
    "反证不因兼容旧检查而消失；revision_target和unresolved_issues照完整原生失败/未知填写。"
)


def _resolved(schema, node):
    value = node
    while "$ref" in value:
        value = schema["$defs"][value["$ref"].split("/")[-1]]
    return deepcopy(value)


def build_part_schema(part, script, brief, plan, legal_context, **options):
    schema = prior.build_part_schema(part, script, brief, plan, legal_context, **options)
    schema["properties"]["schema"] = {"const": VERSION}
    if part == "semantic":
        raw = deepcopy(script); raw.pop("selected_candidate_id")
        catalog = prior.world.build_evidence_catalog(options["goal_contract"], raw)
        schema["$defs"]["v7_world_counterevidence"] = {"type": "array", "items": {"enum": list(catalog)}, "uniqueItems": True}
        table = _resolved(schema, schema["properties"]["world_scene_checks"])
        for identifier, original in table["properties"].items():
            row = _resolved(schema, original)
            row["properties"]["counterevidence"] = {"$ref": "#/$defs/v7_world_counterevidence"}
            row["required"].append("counterevidence")
            row.setdefault("allOf", []).append({"if": {"properties": {"status": {"const": "pass"}}},
                "then": {"properties": {"counterevidence": {"maxItems": 0}}}})
            table["properties"][identifier] = row
        schema["properties"]["world_scene_checks"] = table
    Draft202012Validator.check_schema(schema)
    return schema


def _projection(native, part):
    value = deepcopy(native); value["schema"] = prior.VERSION
    if part == "semantic":
        for row in value["world_scene_checks"].values(): row.pop("counterevidence")
    return value


def _lift(result, native, part=None):
    value = deepcopy(result)
    if "underlying_v6_decision" in value:
        value["compiler_underlying_v6_decision"] = value.pop("underlying_v6_decision")
    for field in ("findings", "uncertainties"):
        for item in value.get(field, []):
            if item.get("table") == "world_scene_checks":
                doc = native if part else native["native_" + item["part"] + "_review"]
                item["finding"] = deepcopy(doc["world_scene_checks"][item["item_id"]])
    value.update(full_review_protocol_version=ADAPTER_VERSION, native_version=VERSION,
        native_response_rewritten=False, compiler_projection_is_native_review=False,
        compiler_v6_checking_only=True)
    if part:
        value.update(native_part_sha256=digest(native), split_review_contract_version=VERSION,
            compiler_v6_checking_projection_sha256=digest(_projection(native, part)))
    else:
        value.update(native_bundle_sha256=digest(native), split_review_bundle_version=BUNDLE_VERSION,
            native_part_sha256={key: digest(native["native_" + key + "_review"]) for key in PART_TABLES},
            review_origin="two_native_same_source_v7_parts")
    return value


def _invalid(exc):
    return {"valid": False, "accepted": False, "status": "halt_full_review_v7_contract",
        "findings": [{"code": "FULL_REVIEW_V7_CONTRACT_INVALID", "reason": exc.message if isinstance(exc, ValidationError) else str(exc),
            "path": "/" + "/".join(map(str, exc.absolute_path)) if isinstance(exc, ValidationError) else ""}],
        "uncertainties": [], "new_scope_admitted": False, "new_scope_revision_admitted": False,
        "content_checks_satisfied": False, "full_review_protocol_version": ADAPTER_VERSION}


def validate_part(native, part, script, brief, plan, legal_context, *, checking_adapter=None, **options):
    try:
        Draft202012Validator(build_part_schema(part, script, brief, plan, legal_context, **options)).validate(native)
        checker = prior if checking_adapter is None else checking_adapter
        result = checker.validate_part(_projection(native, part), part, script, brief, plan, legal_context, **options)
        return _lift(result, native, part)
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc)


def build_review_bundle(native_semantic_review, native_physical_review):
    return {"schema": BUNDLE_VERSION, "native_semantic_review": deepcopy(native_semantic_review),
        "native_physical_review": deepcopy(native_physical_review)}


def validate_bundle(bundle, script, brief, plan, legal_context, *, checking_adapter=None,
                    semantic_context_sha256, physical_context_sha256, **options):
    try:
        if (type(bundle) is not dict or set(bundle) != {"schema", "native_semantic_review", "native_physical_review"}
                or bundle["schema"] != BUNDLE_VERSION): raise ValueError("two original native v7 parts required")
        contexts = {"semantic": semantic_context_sha256, "physical": physical_context_sha256}
        for part in PART_TABLES:
            Draft202012Validator(build_part_schema(part, script, brief, plan, legal_context,
                context_sha256=contexts[part], **options)).validate(bundle["native_" + part + "_review"])
        projected = prior.build_review_bundle(*(_projection(bundle["native_" + part + "_review"], part) for part in PART_TABLES))
        checker = prior if checking_adapter is None else checking_adapter
        result = checker.validate_bundle(projected, script, brief, plan, legal_context,
            semantic_context_sha256=semantic_context_sha256, physical_context_sha256=physical_context_sha256, **options)
        lifted = _lift(result, bundle)
        # Each native row status survives projection; restore original world
        # counterproofs and true report SHAs in the nested original-part views.
        if "part_results" in lifted:
            lifted["part_results"] = {part: _lift(result["part_results"][part], bundle["native_" + part + "_review"], part) for part in PART_TABLES}
        return lifted
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc)


def upgrade_prepared(prepared, inputs, views, part):
    """New actual request identity; never upgrades an old response object."""
    from scripts import creative_world_scene_replanned_workflow_v3 as workflow
    result = deepcopy(prepared); payload = json.loads(result["request"]["messages"][1]["content"])
    payload["native_review_protocol"] = ADAPTER_VERSION
    context = digest(payload)
    schema = build_part_schema(part, views["compiled_script"], views["brief"], views["plan"], result["review_legal_context"],
        context_sha256=context, goal_contract=views["goal"], opening_setup=views["opening_setup"],
        prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
    rule = result["request"]["messages"][0]["content"]
    if rule.count(workflow.REVIEW_SOURCE_RULE) != 1: raise ValueError("exact inherited canonical source rule required")
    result["request"]["messages"][0]["content"] = rule.replace(workflow.REVIEW_SOURCE_RULE,
        workflow.REVIEW_SOURCE_RULE.replace("v6响应", "v7响应")) + "\n" + WORLD_RULE
    result["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    result["request"]["structured_schema"] = schema
    result["request"]["input_provenance"].update(context_sha256=context, part_context_sha256=context,
        native_review_part_version=VERSION, full_review_protocol_version=ADAPTER_VERSION)
    result.update(context_sha256=context, part_context_sha256=context, full_review_protocol_version=ADAPTER_VERSION)
    measure = workflow.base.workflow.contexts._measure(payload); policy = result["manifest"]["context_policy"]
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ValueError("new review protocol exceeds existing context budget; no text truncated")
    result["manifest"].update(context_sha256=context, part_context_sha256=context, full_review_protocol_version=ADAPTER_VERSION,
        payload_identity=measure, payload_characters=len(result["request"]["messages"][1]["content"]),
        schema_characters=len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))))
    return workflow.base.workflow._mark(result, inputs)
