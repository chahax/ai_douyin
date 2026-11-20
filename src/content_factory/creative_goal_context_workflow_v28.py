"""Pure world/scene workflow: four native audits and same-source full reviews.

Private legacy projections check unchanged fields only. Actual model payloads,
native reports and identities always retain the complete new native objects.
No runtime, provider, budget, claim or paired-approval snapshot is created.
"""
from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator, ValidationError

from . import creative_goal_context_workflow_v25 as prior
from . import creative_goal_context_workflow_v22 as legacy
from . import creative_world_scene_context_v1 as world

VERSION = "creative_goal_context_workflow/v28"
BUNDLE_VERSION = VERSION + "/goal_audit_bundle"
OPENING_SETUP_VERSION = "creative_world_scene_opening_setup/v1"
AUDITS = ("scope", "source", "commitment", "drama")
digest, contexts = prior.digest, prior.contexts
origin_ids, project_inputs = prior.origin_ids, prior.project_inputs


def _mark(prepared, inputs):
    result = prior._mark(prepared, inputs)
    payload = json.loads(result["request"]["messages"][1]["content"])
    result["manifest"].update(payload_identity=contexts._measure(payload),
        structured_schema_sha256=digest(result["request"]["structured_schema"]),
        reference_occurrences=contexts._reference_occurrences(payload, inputs["reference_fulltext"]))
    result["manifest"].update(workflow_version=VERSION, world_scene_contract_version=world.VERSION,
        paired_snapshot_approval_required=False, production_dispatch_eligible=False)
    result["request"]["input_provenance"].update(workflow_version=VERSION,
        world_scene_contract_version=world.VERSION, context_manifest_sha256=digest(result["manifest"]))
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result.update(wire=expected_wire_request(result["request"]), request_sha256=digest(result["request"]),
        provider_calls=0, production_dispatch_eligible=False, sdk_max_retries=0,
        server_schema_guarantee=False, dispatch_performed=False)
    return result


def _request(stage_name, inputs, profile, payload, response_schema, rule, **metadata):
    result = world._request(stage_name, profile, rule, payload, response_schema, manifest=metadata)
    result.update({key: value for key, value in metadata.items() if key not in ("schema", "stage")})
    return _mark(result, inputs)


def _authority(inputs): return prior._fixed_legal_context(inputs)


def build_goal_request_schema(inputs):
    return world.build_goal_schema(base_schema=prior.build_goal_request_schema(inputs))


def prepare_goal_request(inputs, profile):
    result = world.adapt_goal_request(prior.prepare_goal_request(inputs, profile))
    return _mark(result, inputs)


def diagnose_goal_document(document, *, inputs):
    try:
        world.validate_goal(document)
        projection = world.legacy_goal_checking_projection(document)
        result = prior.diagnose_goal_document(projection, inputs=inputs)
        return {**result, "native_goal_sha256": digest(document), "world_sha256": digest(document["whole_plan"]["world_frame"]),
            "private_checking_projection_sha256": digest(projection), "private_projection_is_not_native": True,
            "native_values_rewritten": False}
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        return {"valid": False, "findings": [{"code": "WORLD_GOAL_CONTRACT_INVALID", "message": str(exc)}],
            "native_values_rewritten": False}


def validate_goal_document(document, *, inputs):
    result = diagnose_goal_document(document, inputs=inputs)
    if not result["valid"]: raise ValueError("complete new world goal rejected: " + str(result["findings"]))
    return deepcopy(document)


def _base(inputs, goal):
    validate_goal_document(goal, inputs=inputs)
    authority = {key: deepcopy(value) for key, value in prior._planning_authority_inputs(inputs).items()
        if key not in ("previous_complete_document", "revision_diagnostics", "revision_requirements",
                       "complete_script_feasibility_diagnostics", "fresh_reconception_context")}
    return legacy.base_requests._context("goal_plan", authority)


def metadata_reference_catalog(goal):
    """Only schema-defined, resolved world foreign keys; no prose inference."""
    actors = {row["id"] for row in goal["whole_plan"]["characters"]}
    scenes = {row["id"] for row in goal["whole_plan"]["scenes"]}
    result = {}
    for ref, row in prior.scope_audit.evidence.build_evidence_catalog(goal).items():
        path = row["document_path"]
        kind = ("character_id" if re.fullmatch(r"whole_plan\.world_frame\.relationship_notes\.\d+\.character_ids\.\d+", path)
            else "scene_id" if re.fullmatch(r"whole_plan\.world_frame\.spatial_connections\.\d+\.(?:from|to)_scene_id", path) else None)
        if kind is None: continue
        value = goal
        for part in path.split("."): value = value[int(part)] if isinstance(value, list) else value[part]
        if value not in (actors if kind == "character_id" else scenes):
            raise ValueError("world metadata reference does not resolve to an existing native ID")
        result[ref] = {"document_path": path, "kind": kind, "registered_id": value, "role": "reference_only_not_proposition"}
    return result


def _scope_schema(goal, context):
    schema = prior.scope_audit.build_scope_schema(goal, context_sha256=context)
    for ref, row in metadata_reference_catalog(goal).items():
        schema["properties"]["records_by_ref"]["properties"][ref] = {
            "const": {"act": "N"}, "description": "reference-only structural foreign key at " + row["document_path"]
                + "; not a natural-language fact, speech act, or dialogue obligation"}
    return schema


def prepare_goal_scope_request(inputs, profile, goal):
    validate_goal_document(goal, inputs=inputs)
    result = world.prepare_scope_request(profile, goal)
    context = result["request"]["structured_schema"]["properties"]["scope_context_sha256"]["const"]
    result["request"]["structured_schema"] = _scope_schema(goal, context)
    result["request"]["messages"][0]["content"] += (
        "Schema标reference-only的键仅为已解析的角色/场景外键，填N表示结构元数据；不是自然语言命题或对白义务。"
        "不得据字符串看起来像ID而豁免其它原文，world的时代/社会/前史/关系和空间description仍逐项审实际含义。")
    result.update(scope_context_sha256=context, audit_context_sha256=context)
    return _mark(result, inputs)


prepare_goal_scope_audit_request = prepare_goal_scope_request


def validate_goal_scope(document, goal, *, context_sha256, inputs):
    validate_goal_document(goal, inputs=inputs)
    Draft202012Validator(_scope_schema(goal, context_sha256)).validate(document)
    result = prior.scope_audit.validate_scope(document, goal, context_sha256=context_sha256)
    return {**result, "accepted": result["scope_ready_for_authority_review"], "audit_kind": "scope", "findings": [],
        "uncertainties": [{"source_ref": ref, "kind": "textual_ambiguity", **deepcopy(row)}
            for ref, row in result["textual_ambiguities"].items()], "native_review_modified": False}


validate_goal_scope_audit = validate_goal_scope


def _source_context(inputs, goal, native_scope):
    base = _base(inputs, goal)
    context = prior.scope_audit.build_scope_context(goal)["manifest"]["scope_context_sha256"]
    validate_goal_scope(native_scope, goal, inputs=inputs, context_sha256=context)
    authority = {key: deepcopy(base["payload"][key]) for key in
        ("source_packet", "verified_legal_context", "user_goal_contract", "origin_catalog")}
    return authority, prior.source_audit.build_review_context(goal, native_scope, authority)


def _source_schema(goal, native_scope, authority, context):
    schema = prior.source_audit.build_review_schema(goal, native_scope, authority, context_sha256=context)
    refs = [ref for ref in prior.scope_audit.evidence.build_evidence_catalog(goal) if ref not in metadata_reference_catalog(goal)]
    schema["properties"]["scope_challenges"]["items"]["properties"]["source_ref"] = {"enum": refs} if refs else False
    return schema


def prepare_goal_scoped_source_request(inputs, profile, goal, native_scope):
    authority, built = _source_context(inputs, goal, native_scope)
    result = world.prepare_source_request(profile, goal, native_scope, authority)
    result["request"]["structured_schema"] = _source_schema(goal, native_scope, authority, built["manifest"]["audit_context_sha256"])
    result["request"]["messages"][0]["content"] += "纯结构角色/场景外键不构成scope_challenge的自然语言命题；其它世界原文不豁免。"
    result.update(source_context_sha256=built["manifest"]["audit_context_sha256"],
        audit_context_sha256=built["manifest"]["audit_context_sha256"],
        source_authority_context=prior.source_audit._authority(authority), scoped_source_context=authority,
        authority_context_sha256=built["manifest"]["authority_context_sha256"])
    return _mark(result, inputs)


def prepare_goal_source_audit_request(inputs, profile, goal, *, native_scope):
    return prepare_goal_scoped_source_request(inputs, profile, goal, native_scope)


def validate_goal_source_audit(document, goal, *, native_scope, inputs, context_sha256, authority_context=None):
    authority, built = _source_context(inputs, goal, native_scope)
    if context_sha256 != built["manifest"]["audit_context_sha256"] or (
        authority_context is not None and authority_context != prior.source_audit._authority(authority)):
        raise ValueError("current complete authority/scope context changed")
    Draft202012Validator(_source_schema(goal, native_scope, authority, context_sha256)).validate(document)
    return prior.source_audit.validate_review(document, goal, native_scope, authority, context_sha256=context_sha256)


def _drama_context(inputs, goal):
    validate_goal_document(goal, inputs=inputs)
    # Only old mechanical context scaffolding is reused. No projected report
    # is made; the actual response schema binds the complete world goal.
    payload, manifest = legacy._drama_context(project_inputs(inputs), world.legacy_goal_checking_projection(goal))
    payload["native_goal_evidence_view"] = legacy.evidence_view.build_lossless_goal_evidence_view(goal)
    payload["production_scope_catalog"] = legacy.drama_contract.build_production_scope_catalog(goal)
    manifest.update(native_goal_sha256=digest(goal), audit_context_sha256=digest(payload),
        payload_identity=contexts._measure(payload), full_new_native_goal_preserved=True,
        old_projection_is_native=False, reference_occurrences=0,
        lossless_goal_view_sha256=digest(payload["native_goal_evidence_view"]))
    for field in manifest.get("field_manifest", []):
        if field.get("path") in payload:
            field["projected"] = contexts._measure(payload[field["path"]])
        if field.get("path") == "native_goal_document": field["native_goal_sha256"] = digest(goal)
    return payload, manifest


def _commitment_context(inputs, goal):
    full, manifest = _drama_context(inputs, goal)
    payload = {key: deepcopy(full[key]) for key in ("native_goal_evidence_view", "stage_responsibility_contract")}
    payload["creative_commitment_usage_catalog"] = legacy.commitment_audit.build_commitment_usage_catalog(goal)
    manifest.update(audit_kind="commitment", audit_context_sha256=digest(payload), payload_identity=contexts._measure(payload))
    return payload, manifest


def prepare_goal_drama_audit_request(inputs, profile, goal):
    payload, manifest = _drama_context(inputs, goal); context = digest(payload)
    result = _request("goal_audit", inputs, profile, payload, legacy.build_goal_drama_audit_schema(goal, context_sha256=context),
        legacy.DRAMA_AUDIT_RULE + world.EXECUTION_RULE, **manifest)
    result["audit_context_sha256"] = context
    return result


def prepare_goal_commitment_audit_request(inputs, profile, goal):
    payload, manifest = _commitment_context(inputs, goal); context = digest(payload)
    result = _request("goal_audit", inputs, profile, payload,
        legacy.commitment_audit.build_commitment_audit_schema(goal, context_sha256=context),
        legacy.COMMITMENT_FOCUS_RULE + world.EXECUTION_RULE, **manifest)
    result["audit_context_sha256"] = context
    return result


def validate_goal_drama_audit(document, goal, *, context_sha256, inputs):
    payload, _ = _drama_context(inputs, goal)
    if digest(payload) != context_sha256: raise ValueError("complete world drama context changed")
    return legacy.drama_contract.validate_drama(document, goal, context_sha256=context_sha256)


def validate_goal_commitment_audit(document, goal, *, context_sha256, inputs):
    payload, _ = _commitment_context(inputs, goal)
    if digest(payload) != context_sha256: raise ValueError("complete world commitment context changed")
    return legacy.commitment_audit.validate_commitment_audit(document, goal, context_sha256=context_sha256)


def build_goal_audit_bundle(native_scope_audit, native_source_audit, native_commitment_audit, native_drama_audit):
    return {"schema": BUNDLE_VERSION, **{"native_" + key + "_audit": deepcopy(value)
        for key, value in zip(AUDITS, (native_scope_audit, native_source_audit, native_commitment_audit, native_drama_audit))}}


def validate_goal_audit(bundle, goal, *, inputs):
    if type(bundle) is not dict or set(bundle) != {"schema", *("native_" + key + "_audit" for key in AUDITS)} or bundle["schema"] != BUNDLE_VERSION:
        raise ValueError("four complete new-world same-source native audits required")
    contexts_by_kind = {"scope": prior.scope_audit.build_scope_context(goal)["manifest"]["scope_context_sha256"],
        "source": _source_context(inputs, goal, bundle["native_scope_audit"])[1]["manifest"]["audit_context_sha256"],
        "commitment": digest(_commitment_context(inputs, goal)[0]), "drama": digest(_drama_context(inputs, goal)[0])}
    decisions = {}
    for kind in AUDITS:
        kwargs = {"inputs": inputs, "context_sha256": contexts_by_kind[kind]}
        if kind == "source": kwargs["native_scope"] = bundle["native_scope_audit"]
        validator = validate_goal_scope if kind == "scope" else globals()["validate_goal_" + kind + "_audit"]
        decisions[kind] = validator(bundle["native_" + kind + "_audit"], goal, **kwargs)
    return {"valid": all(x.get("valid") is True for x in decisions.values()),
        "accepted": all(x.get("accepted") is True for x in decisions.values()),
        "findings": [v for x in decisions.values() for v in x.get("findings", [])],
        "uncertainties": [v for x in decisions.values() for v in x.get("uncertainties", [])],
        "part_decisions": decisions, "native_goal_sha256": digest(goal), "audit_sha256": digest(bundle),
        "scope_challenges": deepcopy(decisions["source"].get("scope_challenges", [])),
        "native_audit_sha256s": {key: digest(bundle["native_" + key + "_audit"]) for key in AUDITS},
        "audit_contexts": contexts_by_kind, "four_native_audits_bound": True,
        "paired_snapshot_approval_required": False, "creative_quality_passed": False}


def build_opening_setup_schema(goal):
    world.validate_goal(goal)
    result = legacy.setups.build_schema(world.legacy_goal_checking_projection(goal))
    result["properties"].update(schema={"const": OPENING_SETUP_VERSION}, goal_sha256={"const": digest(goal)})
    return result


def legacy_opening_setup_checking_projection(setup, goal):
    result = deepcopy(setup)
    result.update(schema=legacy.setups.VERSION, goal_sha256=digest(world.legacy_goal_checking_projection(goal)))
    return result


def validate_opening_setup_document(setup, goal):
    Draft202012Validator(build_opening_setup_schema(goal)).validate(setup)
    legacy.setups.validate(legacy_opening_setup_checking_projection(setup, goal), world.legacy_goal_checking_projection(goal))
    return deepcopy(setup)


def prepare_opening_setup_request(inputs, profile, goal):
    validate_goal_document(goal, inputs=inputs)
    payload = {"native_goal_document": deepcopy(goal), "production_preferences": deepcopy(_authority(inputs)["production_preferences"])}
    previous, diagnostics = (inputs.get(key) for key in ("previous_opening_setup", "opening_setup_diagnostics"))
    if (previous is None) != (diagnostics is None): raise ValueError("complete setup and diagnostics must be paired")
    if previous is not None:
        if previous.get("goal_sha256") != digest(goal): raise ValueError("setup repair changed its original goal")
        payload.update(previous_opening_setup=deepcopy(previous), opening_setup_diagnostics=deepcopy(diagnostics))
    return _request("goal_plan", inputs, profile, payload, build_opening_setup_schema(goal),
        legacy.OPENING_SETUP_RULE + world.EXECUTION_RULE, native_goal_sha256=digest(goal), substage="opening_setup")


def compile_native_views(goal, setup, *, source_ids, legal_ids, user_constraint_ids):
    world.validate_goal(goal); validate_opening_setup_document(setup, goal)
    checking_goal = world.legacy_goal_checking_projection(goal)
    checking_setup = legacy_opening_setup_checking_projection(setup, goal)
    views = legacy.compile_native_views(checking_goal, checking_setup, source_ids=source_ids,
        legal_ids=legal_ids, user_constraint_ids=user_constraint_ids)
    views.update(goal=deepcopy(goal), opening_setup=deepcopy(setup))
    views["brief"].update(selected_candidate_id="native_goal:" + digest(goal), source_identity={
        "native_goal_sha256": digest(goal), "native_opening_setup_sha256": digest(setup), "human_confirmation": None})
    views["plan"].update(native_goal_sha256=digest(goal), native_opening_setup_sha256=digest(setup))
    views["world_scene_compiler_manifest"] = {"native_goal_sha256": digest(goal), "native_setup_sha256": digest(setup),
        "private_goal_checking_projection_sha256": digest(checking_goal), "private_setup_checking_projection_sha256": digest(checking_setup),
        "private_projection_is_native": False, "new_fields_semantically_approved_by_compiler": False}
    return views


def _verify_views(inputs, views):
    validate_goal_document(views["goal"], inputs=inputs)
    expected = compile_native_views(views["goal"], views["opening_setup"], **origin_ids(inputs))
    for key in ("goal", "opening_setup", "brief", "plan", "fact_projection", "world_scene_compiler_manifest"):
        if expected[key] != views.get(key): raise ValueError("new native compiler views changed: " + key)


def prepare_script_request(inputs, profile, goal, audit, *, opening_setup, source_ids, legal_ids, user_constraint_ids):
    validate_goal_document(goal, inputs=inputs)
    supplied = {"source_ids": source_ids, "legal_ids": legal_ids, "user_constraint_ids": user_constraint_ids}
    if any(set(supplied[k]) != set(v) for k, v in origin_ids(inputs).items()): raise ValueError("current origin IDs changed")
    decision = validate_goal_audit(audit, goal, inputs=inputs)
    if decision.get("valid") is not True or decision.get("accepted") is not True:
        raise ValueError("four complete new-world audits must accept before authoring")
    views = compile_native_views(goal, opening_setup, **supplied)
    result = world.prepare_writer_request(inputs, profile, goal, opening_setup=opening_setup)
    # Apply the established writer-stage projection after C has validated the
    # raw ownership contract. Keep complete current native repair documents;
    # old full stories are lineage evidence, not a new authoring template.
    staged = legacy.base_requests._context("complete_script", {**prior._planning_authority_inputs(inputs),
        "native_goal_document": goal, "brief": views["brief"], "creative_scene_plan": views["plan"]})
    payload = json.loads(result["request"]["messages"][1]["content"])
    for key in world.CORE_KEYS: payload[key] = deepcopy(staged["payload"][key])
    if payload["native_goal_document"] != goal or payload["native_opening_setup_document"] != opening_setup:
        raise ValueError("writer stage projection changed current native goal/setup")
    if contexts._reference_occurrences(payload, inputs["reference_fulltext"]) != 1:
        raise ValueError("complete current R01 must occur once in the writer payload")
    result["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    result["request"]["input_provenance"]["context_sha256"] = digest(payload)
    ownership_sha = result["manifest"].pop("projected_inputs_sha256")
    result["manifest"].update(context_sha256=digest(payload), ownership_projected_inputs_sha256=ownership_sha,
        stage_projected_core_sha256=digest({key: payload[key] for key in world.CORE_KEYS}),
        writer_stage_projection_manifest=deepcopy(staged["manifest"]),
        prior_story_fulltext_omission_reason="old full text belongs to same-story allowance review, not a current writing template")
    result.update(views=views, goal_audit_sha256=digest(audit), native_opening_setup_sha256=digest(opening_setup))
    result["request"]["input_provenance"].update(goal_audit_sha256=digest(audit),
        native_goal_audit_bundle_version=BUNDLE_VERSION, native_audit_sha256s=decision["native_audit_sha256s"])
    return _mark(result, inputs)


def validate_script_document(native, views, production_preferences=None):
    result = world.validate_script(native, views["goal"])
    compiled = world.compile_script(native, views["goal"], views["brief"])
    return {**result, "script": compiled["script"], "compiler_manifest": compiled["manifest"],
        "necessary_conditions_only": True,
        "necessary_conditions_scope": "native schema, IDs, ensemble coverage and references; no elapsed-time or semantic proof",
        "diagnostic": {"findings": []}, "creative_quality_passed": False}


def full_reviews():
    from . import creative_full_review_protocol_v6
    return creative_full_review_protocol_v6


def prepare_full_review_part_request(inputs, profile, native, views, part):
    _verify_views(inputs, views)
    compiled = validate_script_document(native, views, inputs["production_preferences"])["script"]
    prepared = full_reviews().prepare_full_review_part_request(inputs, profile, native,
        {**deepcopy(views), "compiled_script": compiled}, part)
    return _mark(prepared, inputs)


def render_script(native, goal): return world.render_script(native, goal)
def build_segment_context(*args, **kwargs): return world.build_segment_context(*args, **kwargs)
