"""New provider-native screenplay with deterministic context links.

Only the explicit contract version and omitted predecessor links differ from
the canonical checking source. No creative field is repaired or normalized.
"""
from copy import deepcopy

from jsonschema import Draft202012Validator

from scripts import creative_world_scene_direct_wire_schema_v1 as direct
from scripts import creative_world_scene_script_contract_v2 as canonical

VERSION = "creative_world_scene_derived_context_script/v1"
NATIVE_VERSION = "creative_world_scene_screenplay/v2"
DESCRIPTOR_VERSION = VERSION + "/source_descriptor"
world = canonical.world
digest = world.digest
LINK_RULE = "scene_contexts[i].previous_context_id = null if i == 0 else scene_contexts[i-1].id; array order is never changed"
RELATION_RULE = (
    "Scene-context IDs are unique and ordered by first use. The provider-native v2 document omits previous_context_id; "
    "the compiler alone derives the first null and subsequent immediately preceding context ID. First story_time.relation is opening; "
    "later relations are not opening. Each beat context resolves to that planned beat's scene; ensemble keys equal its participants; "
    "dialogue speakers participate; ensemble indexes address current action steps, parallel pairs address current action/dialogue steps "
    "and are unique. Returning after another context requires a new occurrence ID. Document order is not elapsed performance time."
)


def prepare_schema(goal):
    prior = direct.prepare_schema(goal)
    schema = deepcopy(prior["schema"])
    schema["properties"]["contract_version"] = {"const": NATIVE_VERSION}
    contexts = schema["properties"]["scene_contexts"]
    item = contexts["items"]
    item["properties"].pop("previous_context_id")
    item["required"].remove("previous_context_id")
    for node in (contexts, schema["properties"]["beats"]):
        node["description"] = RELATION_RULE
    Draft202012Validator.check_schema(schema)
    return {"schema": schema, "manifest": {"schema": VERSION + "/wire_manifest",
        "native_contract_version": NATIVE_VERSION, "canonical_contract_version": world.SCRIPT_VERSION,
        "native_goal_sha256": digest(goal), "provider_schema_sha256": digest(schema),
        "canonical_schema_sha256": digest(canonical.refine_schema(world.build_script_schema(goal))),
        "deterministically_derived_fields": ["scene_contexts/*/previous_context_id"],
        "derivation_rule": LINK_RULE, "provider_wire_alone_is_complete_local_contract": False,
        "canonical_structural_validation_required": True, "creative_fields_modified": False,
        "full_same_source_semantic_and_physical_reviews_required": True}}


def _derive(native):
    result = deepcopy(native)
    result["contract_version"] = world.SCRIPT_VERSION
    for index, context in enumerate(result["scene_contexts"]):
        context["previous_context_id"] = result["scene_contexts"][index-1]["id"] if index else None
    return result


def diagnose(native, goal):
    schema = prepare_schema(goal)["schema"]
    findings = [{"code": "NATIVE_V2_SCHEMA_" + error.validator.upper(),
        "path": canonical._path(error.absolute_path), "rule": error.validator,
        "expected": canonical._observed(error.validator_value), "actual": canonical._observed(error.instance),
        "schema_path": canonical._path(error.absolute_schema_path)}
        for error in Draft202012Validator(schema).iter_errors(native)]
    if not findings:
        findings = deepcopy(canonical.diagnose(_derive(native), goal)["findings"])
    return {"valid": not findings, "findings": findings, "native_script_sha256": digest(native),
        "native_contract_version": NATIVE_VERSION, "native_values_modified": False,
        "semantic_meaning_programmatically_verified": False}


def validate(native, goal):
    result = diagnose(native, goal)
    if not result["valid"]:
        error = ValueError("new native screenplay contract rejected")
        error.detail = result
        raise error
    return result


def derive(native, goal):
    validate(native, goal)
    return _derive(native)


def compile_document(native, goal, brief=None):
    derived = derive(native, goal)
    compiled = world.compile_script(derived, goal, brief)
    descriptor = {"schema": DESCRIPTOR_VERSION, "native_contract_version": NATIVE_VERSION,
        "derived_contract_version": world.SCRIPT_VERSION, "native_goal_sha256": digest(goal),
        "native_script_sha256": digest(native), "derived_script_sha256": digest(derived),
        "compiled_script_sha256": digest(compiled["script"]),
        "derivation_rule": LINK_RULE,
        "generated_paths": [f"/scene_contexts/{i}/previous_context_id" for i in range(len(derived["scene_contexts"]))],
        "contract_version_mapping": {"from": NATIVE_VERSION, "to": world.SCRIPT_VERSION},
        "creative_fields_modified": False,
        "legacy_review_native_script_sha256_role": "derived_script_sha256; canonical review source, not provider-native v2",
        "provider_native_retained_separately": True}
    return {"valid": True, "provider_native": deepcopy(native), "derived_script": derived,
        "script": compiled["script"], "source_descriptor": descriptor,
        "compiler_manifest": {"schema": VERSION + "/compiler_manifest", "source_descriptor": deepcopy(descriptor),
            "canonical_compiler_manifest": deepcopy(compiled["manifest"]), "provider_native_modified": False},
        "diagnostic": {"findings": []}, "necessary_conditions_only": True,
        "creative_quality_passed": False}


def recover_compiled(script, goal, brief=None):
    """Rebuild only the declared origin representation, then exact round-trip.

    This proves deterministic representation compatibility, not actual provider
    authorship. The coordinator separately binds the raw SDK tool object SHA.
    """
    raw = deepcopy(script)
    if raw.get("contract_version") != world.SCRIPT_VERSION or "selected_candidate_id" not in raw:
        raise ValueError("derived canonical compiled source required")
    raw.pop("selected_candidate_id")
    for context in raw.get("scene_contexts", []):
        if "previous_context_id" not in context:
            raise ValueError("canonical context link missing")
        context.pop("previous_context_id")
    raw["contract_version"] = NATIVE_VERSION
    result = compile_document(raw, goal, brief)
    if result["script"] != script:
        raise ValueError("raw-to-canonical-to-compiled round-trip differs; no creative repair allowed")
    return result


def render_script(native, goal):
    text = world.render_script(derive(native, goal), goal)
    return text.replace("原生完整剧本；机器验收、用户审美与视频人工审核分别记录。",
        "原生完整正文；场次前置链接由确定性编译派生。机器验收、用户审美与视频人工审核分别记录。", 1)
