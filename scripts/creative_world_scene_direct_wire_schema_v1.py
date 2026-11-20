"""Pure provider-facing representation of the complete screenplay contract.

This module changes only a copied request Schema. It never transforms model
output. Canonical script_contract_v2 validation and same-source full review
remain mandatory: the direct wire alone has fewer cross-field constraints.
"""
from copy import deepcopy

from jsonschema import Draft202012Validator

from scripts import creative_world_scene_script_contract_v2 as canonical

VERSION = "creative_world_scene_direct_wire_schema/v1"
FORBIDDEN_KEYWORDS = {"allOf", "anyOf", "oneOf", "not", "prefixItems", "if", "then", "else", "propertyNames", "$ref", "$defs"}
LOCAL_RULES = [
    {"id": "beat_order", "rule": "Exact complete native-goal beat IDs and order; no duplicate, omitted or shuffled beat."},
    {"id": "scene_occurrences", "rule": "First predecessor is null/opening; later predecessor is nonempty and exact, relation is not opening; occurrence IDs unique and used in first-use order."},
    {"id": "beat_scene_mapping", "rule": "Each beat context resolves to the scene in its same native goal; returning after another context requires a new occurrence."},
    {"id": "ensemble_coverage", "rule": "Ensemble actor keys equal the current context participants, including silent actors; allowed actors are not all required in every scene."},
    {"id": "step_speaker", "rule": "Action speaker is empty; dialogue speaker is an actual present actor."},
    {"id": "local_indices", "rule": "Performance indices are strict native integers addressing actual action steps in this beat; parallel pairs address this beat's actual action/dialogue steps without duplicates."},
    {"id": "performance_time", "rule": "Document position is not a proof of elapsed time or completed-before state; original full physical review still requires supported temporal evidence."},
]


def _keyword_paths(value, prefix=()):
    if type(value) is dict:
        for key, child in value.items():
            if key in FORBIDDEN_KEYWORDS: yield (*prefix, key)
            yield from _keyword_paths(child, (*prefix, key))
    elif type(value) is list:
        for index, child in enumerate(value): yield from _keyword_paths(child, (*prefix, index))


def prepare_schema(goal, canonical_schema=None):
    """Build direct wire plus explicit canonical/provider identity manifest.

    A supplied canonical schema must equal the actual full canonical builder
    for this exact goal. Unknown schema shapes are rejected, not stripped.
    """
    expected = canonical.refine_schema(canonical.world.build_script_schema(goal))
    if canonical_schema is not None and canonical_schema != expected:
        raise ValueError("supplied canonical schema differs from the exact native-goal contract")
    source = expected if canonical_schema is None else canonical_schema
    result = deepcopy(source)
    actors = [row["id"] for row in goal["whole_plan"]["characters"]]
    beats = result["properties"]["beats"]
    beat_parts = beats.pop("allOf")
    if len(beat_parts) != 2 or set(beat_parts[0]) != {"items"} or set(beat_parts[1]) != {"prefixItems"}:
        raise ValueError("expected canonical complete-beat and positional constraints")
    beat = beat_parts[0]["items"]
    beats["items"] = beat

    # Preserve the full step object; only its conditional speaker relation
    # moves to the unchanged canonical validator, explicitly listed above.
    step = beat["properties"]["steps"]["items"]
    speaker_conditions = step.pop("allOf")
    if len(speaker_conditions) != 2:
        raise ValueError("expected canonical action/dialogue speaker conditions")
    step["properties"]["speaker"] = {"type": "string", "enum": ["", *actors]}

    # An explicit optional property for every allowed actor preserves the
    # original subset semantics; no extra actor is forced onto a scene.
    ensemble = beat["properties"]["ensemble"]
    if ensemble.get("propertyNames") != {"enum": actors} or type(ensemble.get("additionalProperties")) is not dict:
        raise ValueError("expected canonical allowed-actor performance-array map")
    performances = ensemble.pop("additionalProperties")
    if performances.get("type") != "array": raise ValueError("canonical actor values must remain arrays")
    ensemble.pop("propertyNames")
    ensemble["properties"] = {actor: deepcopy(performances) for actor in actors}
    ensemble["additionalProperties"] = False

    contexts = result["properties"]["scene_contexts"]
    context_parts = contexts.pop("allOf")
    if len(context_parts) != 2 or set(context_parts[0]) != {"items"} or "prefixItems" not in context_parts[1]:
        raise ValueError("expected canonical full-scene and first/later constraints")
    contexts["items"] = context_parts[0]["items"]
    result.pop("$comment", None)
    remaining = list(_keyword_paths(result))
    if remaining:
        raise ValueError("unhandled compound schema keyword at " + "/".join(map(str, remaining[0])))
    Draft202012Validator.check_schema(result)
    manifest = {"schema": VERSION + "/manifest", "native_goal_sha256": canonical.world.digest(goal),
        "canonical_schema_sha256": canonical.world.digest(source), "provider_schema_sha256": canonical.world.digest(result),
        "canonical_validation_module": canonical.VERSION, "canonical_validation_call": "diagnose(native, exact_goal) with default canonical schema",
        "provider_wire_alone_equivalent_to_canonical": False, "canonical_validation_required": True,
        "full_same_source_semantic_and_physical_reviews_required": True,
        "constraints_retained_locally": deepcopy(LOCAL_RULES), "full_beat_schema_copies": 1,
        "actor_ids": actors, "all_actors_required_in_every_scene": False,
        "native_output_transformed": False, "source_goal_modified": False,
        "creative_quality_passed": False, "provider_calls": 0}
    return {"schema": result, "manifest": manifest}


def build_schema(goal, canonical_schema=None):
    return prepare_schema(goal, canonical_schema)["schema"]
