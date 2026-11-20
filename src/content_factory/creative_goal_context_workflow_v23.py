"""Independent speech-act source6 admission around the frozen native text chain.

Fixed legal quotations, setup4, drama11, focused commitments and same-source full
reviews reuse pure workflow22 functions. Source6 and the three-native bundle are
validated here without making an old-version report or bypassing source gates.
"""
from __future__ import annotations
from copy import deepcopy
import json
from .creative_goal_context_workflow_v22 import *
from . import creative_goal_context_workflow_v22 as frozen
from . import creative_goal_legal_usage_source_audit_v6 as source_audit

VERSION = "creative_goal_context_workflow/v23"
SOURCE_AUDIT_VERSION = source_audit.VERSION
SOURCE_AUDIT_RULE = source_audit.SOURCE_REVIEW_RULE
BUNDLE_VERSION = VERSION + "/goal_audit_bundle"
_planning_authority_inputs = frozen._planning_authority_inputs
_validate_planning_input = frozen._validate_planning_input
_base_context = frozen._base_context
_source_authority = frozen._source_authority
_drama_context = frozen._drama_context
_commitment_context = frozen._commitment_context
_verify_views = frozen._verify_views
_fixed_legal_context = frozen._fixed_legal_context


def _mark_workflow(result):
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result["request"]["input_provenance"]["workflow_version"] = VERSION
    result["manifest"]["workflow_version"] = VERSION
    result["request"]["input_provenance"]["context_manifest_sha256"] = digest(result["manifest"])
    result["wire"] = expected_wire_request(result["request"])
    result["request_sha256"] = digest(result["request"])
    return result


def prepare_goal_request(inputs, profile):
    # The old projector leaves unrecognized native v6 findings intact. Do not
    # manufacture v5 decisions just to externalize tables or satisfy its gate.
    return _mark_workflow(frozen.prepare_goal_request(inputs, profile))


def _source_context(inputs, native_goal):
    built = _base_context(inputs, native_goal)
    payload = {key: deepcopy(built["payload"][key]) for key in
        ("source_packet", "verified_legal_context", "user_goal_contract", "origin_catalog")}
    view = evidence_view.build_lossless_goal_evidence_view(native_goal)
    if evidence_view.reconstruct_goal(view, expected_native_goal_sha256=digest(native_goal)) != native_goal:
        raise ValueError("source lossless goal view changed the complete current native goal")
    payload.update(native_goal_evidence_view=view, native_goal_sha256=digest(native_goal),
        legal_evidence_role_catalog=source_audit.build_evidence_role_catalog(native_goal))
    manifest = audit_contexts._manifest("source", inputs, native_goal, built, payload)
    if manifest["reference_occurrences"] != 0:
        raise ValueError("source audit must not carry R01 expression reference")
    authority = _source_authority(payload)
    manifest.update(schema=VERSION + "/source_context_manifest", audit_context_sha256=digest(payload),
        authority_context_sha256=digest(authority), lossless_goal_view_sha256=digest(view),
        native_goal_reconstruction_verified=True, original_native_goal_sent_separately=False,
        legal_evidence_role_catalog_sha256=digest(payload["legal_evidence_role_catalog"]),
        role_catalog_contains_duplicate_quotations=False, speech_act_semantic_classification_proven=False)
    return payload, manifest


def build_goal_source_audit_schema(native_goal, *, context_sha256, authority_context):
    return source_audit.build_source_schema(native_goal, authority_context, context_sha256=context_sha256)


def prepare_goal_source_audit_request(inputs, profile, native_goal):
    allowance = profile.get("source_strict", {}).get("max_completion_tokens", SOURCE_MAX_COMPLETION_TOKENS)
    if type(allowance) is not int or allowance != SOURCE_MAX_COMPLETION_TOKENS:
        raise ValueError("source6 requires the explicit independent 24000 output allowance")
    payload, manifest = _source_context(inputs, native_goal)
    authority = _source_authority(payload)
    context_sha = digest(payload)
    schema = build_goal_source_audit_schema(native_goal, context_sha256=context_sha, authority_context=authority)
    result = audit_contexts._request(payload, schema, profile, SOURCE_AUDIT_RULE, manifest)
    result["request"]["parameters"]["max_completion_tokens"] = allowance
    manifest.update(native_source_observations_version=SOURCE_AUDIT_VERSION,
        source_output_allowance=SOURCE_MAX_COMPLETION_TOKENS,
        source_output_allowance_basis="unmeasured headroom; complete native speech-act v6 report only",
        speech_act_fixed_key_coverage=True, speech_act_semantic_classification_proven=False)
    result.update(source_authority_context=authority, source_context_sha256=context_sha,
        authority_context_sha256=digest(authority))
    result["request"]["input_provenance"].update(native_goal_sha256=digest(native_goal),
        source_context_sha256=context_sha, authority_context_sha256=digest(authority),
        native_source_audit_version=SOURCE_AUDIT_VERSION)
    return _mark_workflow(result)


def validate_goal_source_audit(document, native_goal, *, context_sha256, authority_context=None, inputs=None):
    if inputs is not None:
        payload, _ = _source_context(inputs, native_goal)
        expected = _source_authority(payload)
        if digest(payload) != context_sha256 or authority_context is not None and authority_context != expected:
            raise ValueError("source audit must bind the complete current authority and actual source payload")
        authority_context = expected
    if authority_context is None:
        raise ValueError("source6 requires complete authority_context or current inputs")
    return source_audit.validate_source(document, native_goal, authority_context, context_sha256=context_sha256)


def prepare_goal_drama_audit_request(inputs, profile, native_goal):
    return _mark_workflow(frozen.prepare_goal_drama_audit_request(inputs, profile, native_goal))


def prepare_goal_commitment_audit_request(inputs, profile, native_goal):
    return _mark_workflow(frozen.prepare_goal_commitment_audit_request(inputs, profile, native_goal))


def prepare_opening_setup_request(inputs, profile, native_goal):
    return _mark_workflow(frozen.prepare_opening_setup_request(inputs, profile, native_goal))


def prepare_full_review_part_request(inputs, profile, native_script, views, part):
    return _mark_workflow(frozen.prepare_full_review_part_request(inputs, profile, native_script, views, part))


def build_goal_audit_bundle(native_source_audit,native_drama_audit,native_commitment_audit):
    return {"schema":BUNDLE_VERSION,"native_source_audit":deepcopy(native_source_audit),
        "native_drama_audit":deepcopy(native_drama_audit),"native_commitment_audit":deepcopy(native_commitment_audit)}


def validate_goal_audit(bundle,native_goal,*,inputs):
    if (type(bundle) is not dict or set(bundle) !=
            {"schema","native_source_audit","native_drama_audit","native_commitment_audit"}
            or bundle["schema"] != BUNDLE_VERSION):
        raise ValueError("three current complete native planning audits required")
    source_payload,_ = _source_context(inputs,native_goal)
    drama_payload,_ = _drama_context(inputs,native_goal)
    focused_payload,_ = _commitment_context(inputs,native_goal)
    contexts_by_kind = {"source":digest(source_payload), "drama":digest(drama_payload),
                        "commitment":digest(focused_payload)}
    if len(set(contexts_by_kind.values())) != 3:
        raise ValueError("three distinct current native planning audit contexts required")
    source = validate_goal_source_audit(bundle["native_source_audit"], native_goal,
        context_sha256=contexts_by_kind["source"], authority_context=_source_authority(source_payload))
    drama = validate_goal_drama_audit(bundle["native_drama_audit"], native_goal,
        context_sha256=contexts_by_kind["drama"])
    focus = validate_goal_commitment_audit(bundle["native_commitment_audit"],native_goal,
        context_sha256=contexts_by_kind["commitment"])
    decisions = (source, drama, focus)
    return {"valid":all(row["valid"] for row in decisions),
        "accepted":all(row["accepted"] for row in decisions),
        "findings":[item for row in decisions for item in row["findings"]],
        "uncertainties":[item for row in decisions for item in row["uncertainties"]],
        "source_decision":source,"drama_decision":drama,"commitment_decision":focus,
        "native_goal_sha256":digest(native_goal),"audit_sha256":digest(bundle),
        "source_context_sha256":contexts_by_kind["source"],"drama_context_sha256":contexts_by_kind["drama"],
        "commitment_context_sha256":contexts_by_kind["commitment"],
        "authority_context_sha256":digest(_source_authority(source_payload)),
        "three_native_audits_bound":True,"combined_decisions_only":True,"native_single_combined_audit":False,
        "native_review_modified":False,"semantic_truth_deterministically_proven":False,"human_approved":False}


def prepare_script_request(inputs, profile, native_goal, native_goal_audit, *, opening_setup,
                           source_ids, legal_ids, user_constraint_ids):
    """Only three complete current same-goal native audits admit the author."""
    actual_ids = origin_ids(audit_contexts._planning_authority_inputs(inputs))
    provided = {"source_ids": source_ids, "legal_ids": legal_ids, "user_constraint_ids": user_constraint_ids}
    if any(set(provided[key]) != set(actual_ids[key]) for key in actual_ids):
        raise ValueError("origin IDs differ from actual supplied source/legal/user context")
    _validate_planning_input(inputs, native_goal)
    views = compile_native_views(native_goal, opening_setup, **provided)
    audit = validate_goal_audit(native_goal_audit, views["goal"], inputs=inputs)
    if not audit["accepted"]:
        raise ValueError("all three current native planning audits must pass; no author request prepared")
    maximum = inputs["production_preferences"].get("max_characters")
    if type(maximum) is not int or maximum < 1 or len(views["brief"]["characters"]) > maximum:
        raise ValueError("native whole plan violates explicit on-screen cast preference")
    payload_inputs = {**audit_contexts._planning_authority_inputs(inputs), "native_goal_document": views["goal"],
        "brief": views["brief"], "creative_scene_plan": views["plan"]}
    built = audit_contexts.prior._context("complete_script", payload_inputs)
    built["payload"]["native_opening_setup_document"] = deepcopy(views["opening_setup"])
    audit_contexts._append_native_setup_manifest(built["manifest"], built["payload"], views["opening_setup"])
    built["manifest"]["fact_projection"] = deepcopy(views["fact_projection"])
    built["manifest"]["native_goal_audit_bundle_version"] = BUNDLE_VERSION
    schema = windows.build_script_schema(views["brief"])
    beat_ids = [row["id"] for row in views["plan"]["beats"]]
    schema["properties"]["beats"]["minItems"] = len(beat_ids)
    schema["properties"]["beats"]["maxItems"] = len(beat_ids)
    schema["properties"]["beats"]["items"]["properties"]["id"] = {"enum": beat_ids}
    result = audit_contexts.prior._request("complete_script", built["payload"], schema,
        "writer", profile, AUTHOR_RULE, built["manifest"])
    result["views"] = views
    result["goal_audit_sha256"] = digest(native_goal_audit)
    result["request"]["input_provenance"].update(goal_audit_sha256=digest(native_goal_audit),
        native_source_audit_sha256=digest(native_goal_audit["native_source_audit"]),
        native_drama_audit_sha256=digest(native_goal_audit["native_drama_audit"]),
        native_commitment_audit_sha256=digest(native_goal_audit["native_commitment_audit"]),
        native_goal_audit_bundle_version=BUNDLE_VERSION,
        native_opening_setup_sha256=digest(views["opening_setup"]), native_goal_sha256=digest(native_goal))
    result["native_opening_setup_sha256"] = digest(views["opening_setup"])
    return _mark_workflow(result)

