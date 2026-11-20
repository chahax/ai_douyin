"""Four real native planning audits around the unchanged native text contracts.

This module prepares and validates only. Scope2, scoped-source2, commitment and
drama remain separate provider documents; no source6 compatibility report is
created, and no frozen module global is replaced.
"""
from __future__ import annotations

from copy import deepcopy
import json

from .creative_goal_context_workflow_v24 import *
from . import creative_goal_context_workflow_v24 as prior
from . import creative_goal_context_workflow_v22 as contracts
from . import creative_legal_speech_scope_v2 as scope_audit
from . import creative_scoped_source_review_v2 as source_audit

VERSION = "creative_goal_context_workflow/v25"
BUNDLE_VERSION = VERSION + "/goal_audit_bundle"
SCOPE_AUDIT_VERSION, SOURCE_AUDIT_VERSION = scope_audit.VERSION, source_audit.VERSION
SCOPE_AUDIT_RULE, SOURCE_AUDIT_RULE = scope_audit.SCOPE_RULE, source_audit.REVIEW_RULE
SOURCE_MAX_COMPLETION_TOKENS = SCOPE_MAX_COMPLETION_TOKENS = 16000
CLARIFICATION_FRAME = "creative_known_native_clarification/v1/request_feedback"
FOUR_AUDIT_RULE = (
    "本流程的新完整规划须由scope2、scoped-source2、commitment、drama四份完整同源原生审查分别验收。"
    "小样例分类、旧三份审查或旧规划报告不能代替当前四审，程序结构通过不证明创作质量。")
_planning_authority_inputs = prior._planning_authority_inputs
_fixed_legal_context, _validate_planning_input = prior._fixed_legal_context, prior._validate_planning_input


def _mark(prepared, inputs):
    prepared = prior._mark(prepared, inputs)
    prepared["manifest"]["workflow_version"] = VERSION
    prepared["manifest"]["reference_occurrences"] = contexts._reference_occurrences(
        json.loads(prepared["request"]["messages"][1]["content"]), inputs["reference_fulltext"])
    prepared["request"]["input_provenance"].update(workflow_version=VERSION,
        context_manifest_sha256=digest(prepared["manifest"]))
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    prepared["wire"] = expected_wire_request(prepared["request"])
    prepared["request_sha256"] = digest(prepared["request"])
    return prepared


def _is_clarification(inputs):
    return type(inputs.get("revision_diagnostics")) is dict and inputs["revision_diagnostics"].get("schema") == CLARIFICATION_FRAME


def prepare_goal_request(inputs, profile):
    if not _is_clarification(inputs):
        result = prior.prepare_goal_request(inputs, profile)
        rule = result["request"]["messages"][0]["content"]
        old = "不能只修改旧文本或以旧审查批准替代新三审。"
        if rule.count(old) != 1: raise ValueError("inherited planning protocol sentence changed; explicit four-audit wording review required")
        result["request"]["messages"][0]["content"] = rule.replace(old,
            "不能只修改旧文本或以旧审查批准替代当前四份同源审查。") + FOUR_AUDIT_RULE
        return _mark(result, inputs)
    # The helper validates original clean-input identities before ownership
    # projection. A valid old plan is never forged into a structural rejection.
    from . import creative_known_native_clarification_v1 as clarification
    validation = clarification.validate_revision_inputs(inputs)
    projected = project_inputs(inputs)
    built = audit_contexts.prior._context("goal_plan", audit_contexts._planning_authority_inputs(projected))
    contracts._add_stage_responsibility(built["payload"], built["manifest"])
    if (contracts.PLANNING_RULE.count("上一完整稿是失败修订证据") != 1
            or contracts.FIXED_LEGAL_SOURCE_RULE.count("previous_complete_document是旧失败原文") != 1):
        raise ValueError("frozen clarification rule wording changed; explicit protocol review required")
    rule = contracts.PLANNING_RULE.replace("上一完整稿是失败修订证据", "上一完整稿是未采用的完整原生修订证据")
    fixed_law_rule = contracts.FIXED_LEGAL_SOURCE_RULE.split("previous_complete_document是旧失败原文", 1)[0]
    rule += (contracts.CAST_SCOPE_RULE + contracts.STAGE_RESPONSIBILITY_RULE + fixed_law_rule
        + prior.OWNERSHIP_RULE + prior.CHOICE_RULE + prior.LAW_SELECTION_RULE + clarification.RULE + FOUR_AUDIT_RULE)
    built["manifest"].update(known_native_clarification=deepcopy(validation),
        fixed_legal_source_rule_version=FIXED_LEGAL_SOURCE_RULE_VERSION,
        structural_feedback_compiler_used=False, previous_native_modified=False)
    result = audit_contexts.prior._request("goal_plan", built["payload"], build_goal_request_schema(inputs),
        "writer", profile, rule, built["manifest"])
    result["request"]["input_provenance"].update(known_native_clarification_sha256=digest(validation),
        fixed_legal_source_rule_version=FIXED_LEGAL_SOURCE_RULE_VERSION,
        structural_feedback_compiler_used=False)
    return _mark(result, inputs)


def _review_manifest(inputs, native_goal, built, kind):
    projected = project_inputs(inputs)
    base = contracts._base_context(projected, native_goal)
    manifest = audit_contexts._manifest(kind, projected, native_goal, base, built["payload"])
    if manifest["reference_occurrences"] != 0:
        raise ValueError("scope/source audit must not duplicate the R01 expression reference")
    manifest.update(built["manifest"], stage="goal_audit", audit_kind=kind,
        payload_identity=contexts._measure(built["payload"]), original_native_goal_sent_separately=False,
        native_goal_audit_parts=4, server_strict_guarantee=False)
    return manifest


def prepare_goal_scope_request(inputs, profile, native_goal):
    _validate_planning_input(inputs, native_goal)
    built = scope_audit.build_scope_context(native_goal)
    context = built["manifest"]["scope_context_sha256"]
    schema = scope_audit.build_scope_schema(native_goal, context_sha256=context)
    manifest = _review_manifest(inputs, native_goal, built, "scope")
    result = audit_contexts._request(built["payload"], schema, profile, SCOPE_AUDIT_RULE, manifest)
    result.update(scope_context_sha256=context, audit_context_sha256=context)
    result["request"]["input_provenance"].update(native_goal_sha256=digest(native_goal), scope_context_sha256=context,
        native_scope_audit_version=SCOPE_AUDIT_VERSION, full_native_goal_scope=True)
    return _mark(result, inputs)


prepare_goal_scope_audit_request = prepare_goal_scope_request
build_goal_scope_audit_schema = scope_audit.build_scope_schema


def validate_goal_scope(document, native_goal, *, context_sha256, inputs=None):
    if inputs is not None: _validate_planning_input(inputs, native_goal)
    result = scope_audit.validate_scope(document, native_goal, context_sha256=context_sha256)
    return {**result, "accepted": result["scope_ready_for_authority_review"], "audit_kind": "scope", "findings": [],
        "uncertainties": [{"source_ref": ref, "kind": "textual_ambiguity", **deepcopy(row)}
            for ref, row in result["textual_ambiguities"].items()], "native_review_modified": False}


validate_goal_scope_audit = validate_goal_scope


def _source_context(inputs, native_goal, native_scope):
    _validate_planning_input(inputs, native_goal)
    base = contracts._base_context(project_inputs(inputs), native_goal)
    current = {key: deepcopy(base["payload"][key]) for key in
        ("source_packet", "verified_legal_context", "user_goal_contract", "origin_catalog")}
    return current, source_audit.build_review_context(native_goal, native_scope, current)


def prepare_goal_scoped_source_request(inputs, profile, native_goal, native_scope):
    source_context, built = _source_context(inputs, native_goal, native_scope)
    context = built["manifest"]["audit_context_sha256"]
    schema = source_audit.build_review_schema(native_goal, native_scope, source_context, context_sha256=context)
    manifest = _review_manifest(inputs, native_goal, built, "source")
    result = audit_contexts._request(built["payload"], schema, profile, SOURCE_AUDIT_RULE, manifest)
    result.update(source_context_sha256=context, audit_context_sha256=context,
        source_authority_context=source_audit._authority(source_context), scoped_source_context=source_context,
        authority_context_sha256=built["manifest"]["authority_context_sha256"])
    result["request"]["input_provenance"].update(native_goal_sha256=digest(native_goal), scope_native_sha256=digest(native_scope),
        source_context_sha256=context, authority_context_sha256=result["authority_context_sha256"],
        native_source_audit_version=SOURCE_AUDIT_VERSION)
    return _mark(result, inputs)


def prepare_goal_source_audit_request(inputs, profile, native_goal, *, native_scope):
    return prepare_goal_scoped_source_request(inputs, profile, native_goal, native_scope)


def build_goal_source_audit_schema(native_goal, *, native_scope, source_context, context_sha256):
    return source_audit.build_review_schema(native_goal, native_scope, source_context, context_sha256=context_sha256)


def validate_goal_scoped_source(document, native_goal, native_scope, *, inputs, context_sha256, authority_context=None):
    source_context, built = _source_context(inputs, native_goal, native_scope)
    if built["manifest"]["audit_context_sha256"] != context_sha256 or authority_context is not None and authority_context != source_audit._authority(source_context):
        raise ValueError("scoped source audit must bind exact current source/user/law and original native scope")
    return source_audit.validate_review(document, native_goal, native_scope, source_context, context_sha256=context_sha256)


def validate_goal_source_audit(document, native_goal, *, native_scope, inputs, context_sha256, authority_context=None):
    return validate_goal_scoped_source(document, native_goal, native_scope, inputs=inputs,
        context_sha256=context_sha256, authority_context=authority_context)


def prepare_goal_drama_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_drama_audit_request(inputs, profile, native_goal), inputs)


def prepare_goal_commitment_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_commitment_audit_request(inputs, profile, native_goal), inputs)


def build_goal_audit_bundle(native_scope_audit, native_source_audit, native_commitment_audit, native_drama_audit):
    return {"schema": BUNDLE_VERSION, "native_scope_audit": deepcopy(native_scope_audit),
        "native_source_audit": deepcopy(native_source_audit), "native_commitment_audit": deepcopy(native_commitment_audit),
        "native_drama_audit": deepcopy(native_drama_audit)}


def validate_goal_audit(bundle, native_goal, *, inputs):
    if type(bundle) is not dict or set(bundle) != {"schema", "native_scope_audit", "native_source_audit", "native_commitment_audit", "native_drama_audit"} or bundle["schema"] != BUNDLE_VERSION:
        raise ValueError("four current native planning audits required; old source6 bundles cannot substitute")
    scope_context = scope_audit.build_scope_context(native_goal)["manifest"]["scope_context_sha256"]
    scoped = validate_goal_scope(bundle["native_scope_audit"], native_goal, inputs=inputs, context_sha256=scope_context)
    if not scoped["accepted"]: raise ValueError("true textual ambiguity stops before source authority and author admission")
    _, source_built = _source_context(inputs, native_goal, bundle["native_scope_audit"])
    projected = project_inputs(inputs)
    drama_payload, _ = contracts._drama_context(projected, native_goal)
    commitment_payload, _ = contracts._commitment_context(projected, native_goal)
    context_ids = {"scope": scope_context, "source": source_built["manifest"]["audit_context_sha256"],
        "drama": digest(drama_payload), "commitment": digest(commitment_payload)}
    if len(set(context_ids.values())) != 4: raise ValueError("four distinct exact planning-audit contexts required")
    source = validate_goal_scoped_source(bundle["native_source_audit"], native_goal, bundle["native_scope_audit"],
        inputs=inputs, context_sha256=context_ids["source"])
    drama = validate_goal_drama_audit(bundle["native_drama_audit"], native_goal, context_sha256=context_ids["drama"])
    commitment = validate_goal_commitment_audit(bundle["native_commitment_audit"], native_goal, context_sha256=context_ids["commitment"])
    decisions = (scoped, source, commitment, drama)
    return {"valid": all(r["valid"] for r in decisions), "accepted": all(r["accepted"] for r in decisions),
        "findings": [f for r in decisions for f in r["findings"]], "uncertainties": [u for r in decisions for u in r["uncertainties"]],
        "scope_challenges": deepcopy(source["scope_challenges"]), "scope_decision": scoped, "source_decision": source,
        "commitment_decision": commitment, "drama_decision": drama, "native_goal_sha256": digest(native_goal),
        "audit_sha256": digest(bundle), **{key + "_context_sha256": value for key, value in context_ids.items()},
        "authority_context_sha256": source["authority_context_sha256"], "four_native_audits_bound": True,
        "native_audit_sha256s": {key: digest(bundle["native_" + key + "_audit"]) for key in ("scope", "source", "commitment", "drama")},
        "combined_decisions_only": True, "native_review_modified": False, "old_source6_report_created": False,
        "semantic_truth_deterministically_proven": False, "human_approved": False, "creative_quality_passed": False}


def prepare_opening_setup_request(inputs, profile, native_goal):
    return _mark(prior.prepare_opening_setup_request(inputs, profile, native_goal), inputs)


def prepare_script_request(inputs, profile, native_goal, native_goal_audit, *, opening_setup,
                           source_ids, legal_ids, user_constraint_ids):
    actual_ids = origin_ids(inputs)
    provided = {"source_ids": source_ids, "legal_ids": legal_ids, "user_constraint_ids": user_constraint_ids}
    if any(set(provided[k]) != set(actual_ids[k]) for k in actual_ids): raise ValueError("origin IDs differ from current supplied source/law/user")
    _validate_planning_input(inputs, native_goal)
    views = compile_native_views(native_goal, opening_setup, **provided)
    audit = validate_goal_audit(native_goal_audit, views["goal"], inputs=inputs)
    if not audit["accepted"]: raise ValueError("all four same-native planning audits must pass before authoring")
    maximum = inputs["production_preferences"].get("max_characters")
    if type(maximum) is not int or maximum < 1 or len(views["brief"]["characters"]) > maximum: raise ValueError("native plan violates cast preference")
    authority = _planning_authority_inputs(inputs)
    if _is_clarification(inputs):
        authority = {k: v for k, v in authority.items() if k not in ("previous_complete_document", "revision_diagnostics")}
    payload_inputs = {**authority, "native_goal_document": views["goal"], "brief": views["brief"], "creative_scene_plan": views["plan"]}
    built = audit_contexts.prior._context("complete_script", payload_inputs)
    built["payload"]["native_opening_setup_document"] = deepcopy(views["opening_setup"])
    audit_contexts._append_native_setup_manifest(built["manifest"], built["payload"], views["opening_setup"])
    built["manifest"].update(fact_projection=deepcopy(views["fact_projection"]), native_goal_audit_bundle_version=BUNDLE_VERSION,
        native_goal_audit_sha256s=deepcopy(audit["native_audit_sha256s"]), native_goal_audit_sha256=digest(native_goal_audit))
    schema = windows.build_script_schema(views["brief"]); beat_ids = [r["id"] for r in views["plan"]["beats"]]
    schema["properties"]["beats"].update(minItems=len(beat_ids), maxItems=len(beat_ids))
    schema["properties"]["beats"]["items"]["properties"]["id"] = {"enum": beat_ids}
    result = audit_contexts.prior._request("complete_script", built["payload"], schema, "writer", profile, AUTHOR_RULE, built["manifest"])
    result.update(views=views, goal_audit_sha256=digest(native_goal_audit), native_opening_setup_sha256=digest(views["opening_setup"]))
    result["request"]["input_provenance"].update(goal_audit_sha256=digest(native_goal_audit),
        **{"native_" + key + "_audit_sha256": value for key, value in audit["native_audit_sha256s"].items()},
        native_goal_audit_bundle_version=BUNDLE_VERSION, native_opening_setup_sha256=digest(views["opening_setup"]), native_goal_sha256=digest(native_goal))
    return _mark(result, inputs)


def prepare_full_review_part_request(inputs, profile, native_script, views, part):
    return _mark(prior.prepare_full_review_part_request(inputs, profile, native_script, views, part), inputs)
