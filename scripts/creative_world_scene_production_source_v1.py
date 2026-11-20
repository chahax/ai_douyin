"""Explicit provider-native/canonical production source compatibility.

The private legacy checking proof never leaves load_material. It is used only
for an existing pure compiler check, then original proof/raw paths and values
are restored. Neither a native service report nor a ready certificate is made.
"""
from copy import deepcopy
from pathlib import Path
import json

from scripts import creative_world_scene_production_probe_v1 as legacy
from scripts import creative_world_scene_derived_context_script_v1 as derived

VERSION = "creative_world_scene_production_source/v1"


def verify_documents(proof):
    paths = {key: legacy._inside(proof["paths"][key]) for key in ("goal", "setup", "raw_script", "compiled_script")}
    values = {key: legacy.read(path) for key, path in paths.items()}
    identity = proof["identity"]
    for field, key in (("native_goal_sha256", "goal"), ("native_setup_sha256", "setup"),
            ("native_script_sha256", "raw_script"), ("compiled_script_sha256", "compiled_script")):
        if identity.get(field) != legacy.digest(values[key]): raise ValueError("original text source identity differs: " + field)
    is_derived = any(key in proof["paths"] for key in ("derived_script", "source_descriptor")) or "derived_script_sha256" in identity
    if not is_derived:
        legacy.media.world.validate_script(values["raw_script"], values["goal"])
        if legacy.media.world.compile_script(values["raw_script"], values["goal"])["script"] != values["compiled_script"]:
            raise ValueError("legacy native-to-compiled source differs")
        return {"paths": paths, "values": values, "canonical_script": values["raw_script"], "source_descriptor": None}
    for key in ("derived_script", "source_descriptor"):
        paths[key] = legacy._inside(proof["paths"][key]); values[key] = legacy.read(paths[key])
    compiled = derived.compile_document(values["raw_script"], values["goal"])
    if not (compiled["provider_native"] == values["raw_script"] and compiled["derived_script"] == values["derived_script"]
            and compiled["script"] == values["compiled_script"]
            and compiled["source_descriptor"] == values["source_descriptor"] == proof.get("source_descriptor")
            and identity.get("derived_script_sha256") == legacy.digest(values["derived_script"])):
        raise ValueError("provider native / derived / compiled descriptor does not exactly rebuild")
    return {"paths": paths, "values": values, "canonical_script": values["derived_script"],
        "source_descriptor": compiled["source_descriptor"]}


def load_material(proof):
    source = verify_documents(proof)
    if source["source_descriptor"] is None: return legacy.load_material(proof)
    private = deepcopy(proof)
    private["paths"]["raw_script"] = str(source["paths"]["derived_script"])
    material = legacy.load_material(private)
    # No checking path/identity may be exported as original native evidence.
    material["verified"] = deepcopy(proof)
    material["values"]["raw_script"] = deepcopy(source["values"]["raw_script"])
    material["values"]["derived_script"] = deepcopy(source["canonical_script"])
    material["canonical_source_document"] = deepcopy(source["canonical_script"])
    material["script_source_descriptor"] = deepcopy(source["source_descriptor"])
    return material


def bind_request(prepared, material):
    """Bind actual canonical source and true origin identities without recopying raw."""
    descriptor = material.get("script_source_descriptor")
    if descriptor is None: return prepared
    result = deepcopy(prepared); payload = result["payload"]
    binding = {"schema": VERSION + "/actual_source_binding", "source_descriptor": deepcopy(descriptor),
        "actual_full_current_script_sha256": legacy.digest(material["script"]),
        "actual_full_current_script_role": "canonical compiled source; never provider-native v2",
        "source_ref_catalog_role": "indexes canonical compiled steps; creative text unchanged by context-link derivation",
        "provider_native_fulltext_duplicated": False}
    if "review_context" in result:
        # The actual review context/catalog/const all use the newly sent payload.
        context = result["review_context"]; context["script_source_binding"] = deepcopy(binding)
        catalog = legacy.evidence_catalog(context); groups = legacy.required_evidence_groups(catalog, material)
        result.update(context_sha256=legacy.digest(context), evidence_catalog=catalog, required_evidence_groups=groups)
        result["request"]["structured_schema"]["properties"]["context_sha256"] = {"const": result["context_sha256"]}
        def rebind_quote_schema(node):
            if type(node) is dict:
                props = node.get("properties", {})
                if set(props) == {"ref", "path", "quote"}: props["ref"] = {"enum": list(catalog)}
                for child in node.values(): rebind_quote_schema(child)
            elif type(node) is list:
                for child in node: rebind_quote_schema(child)
        rebind_quote_schema(result["request"]["structured_schema"])
        payload["context"] = deepcopy(context)
        payload["evidence_path_index"] = {key: {"path": value["path"]} for key, value in catalog.items()}
        payload["required_evidence_groups"] = groups
    else:
        payload["script_source_binding"] = binding
    if "review_context" not in result and result["request"]["stage"] == "complete_script":
        # The first context is a canonical checking source, including its
        # explicitly derived link; authored ensemble/actions remain identical.
        raw = material["canonical_source_document"]; first = raw["beats"][0]
        payload["scene_context"] = deepcopy(next(c for c in raw["scene_contexts"] if c["id"] == first["scene_context_id"]))
    result["payload_sha256"] = legacy.digest(payload)
    result["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    result["request"]["input_provenance"].update(payload_sha256=result["payload_sha256"],
        provider_native_script_sha256=descriptor["native_script_sha256"], derived_script_sha256=descriptor["derived_script_sha256"],
        compiled_script_sha256=descriptor["compiled_script_sha256"], script_source_binding_sha256=legacy.digest(binding))
    legacy.clients.expected_wire_request(result["request"])
    return result
