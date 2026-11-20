"""Local spatial declarations and actual reference-compiler projections.

Public API: ``validate_scene(scene, manifest)``, ``build_previs_bundle(scene,
manifest)``, and ``compile_reference_projection(binding_contract,
selected_asset_ids, *, mode, payload=None, messages=None, now, ...)``.

The scene is our own creative_studio_scene/v1, NOT a DirectorDesk .director
file. Coordinates are meters in a right-handed Z-up space; rotations are Euler
XYZ degrees. A complete, explicit geometry snapshot must be present in a
hash-bound JSON provenance record. Assistant examples live in a separate
geometry_provenance_catalog, never become user declarations, native frames,
approved portraits, physics simulation, or production authorization.

Only source reference_compiler_v4 determines original material qualification.
This module performs no network, model call, media inspection, Blender launch,
file writes, approval recording, or mutation of caller-owned objects.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any

from . import creative_reference_compiler_v4 as reference_compiler


SCENE_SCHEMA = "creative_studio_scene/v1"
PROJECTION_SCHEMA = "creative_studio_reference_projection/v1"
MANIFEST_SCHEMA = "creative_shared_production_contract/v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SNAPSHOT_KEYS = {"units", "coordinate_system", "scene_id", "segment_id", "time_seconds",
                  "bounds", "structures", "entities", "camera"}


class StudioReferencePrevisError(ValueError):
    """Known local declaration failure; never a service/transport failure."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str):
    raise StudioReferencePrevisError(code, detail)


def _digest(value: Any) -> str:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError):
        _fail("SCENE_VALUE_INVALID", "JSON must contain finite serializable values")
    return hashlib.sha256(data).hexdigest()


def _object(value: Any, keys: set[str], label: str):
    if not isinstance(value, dict) or set(value) != keys:
        _fail("SCENE_CONTRACT_INVALID", label + " missing/unknown fields")


def _id(value: Any, label: str):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail("SCENE_ID_INVALID", label)


def _sha(value: Any, label: str):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        _fail("SCENE_SOURCE_BINDING_INVALID", label)


def _number(value: Any, label: str, *, positive=False):
    if type(value) not in {int, float} or not math.isfinite(value) or (positive and value <= 0):
        _fail("SCENE_NUMBER_INVALID", label)


def _vector(value: Any, label: str, *, positive=False):
    if not isinstance(value, list) or len(value) != 3:
        _fail("SCENE_VECTOR_INVALID", label + " requires three explicit values")
    for item in value:
        _number(item, label, positive=positive)


def _rows(rows: Any, key: str, label: str, *, nonempty=False) -> dict:
    if not isinstance(rows, list) or (nonempty and not rows):
        _fail("SCENE_CONTRACT_INVALID", label)
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            _fail("SCENE_CONTRACT_INVALID", label)
        _id(row.get(key), label)
        if row[key] in result:
            _fail("SCENE_DUPLICATE_ID", label + ": " + row[key])
        result[row[key]] = row
    return result


def _json_pointer(value: Any, pointer: Any) -> Any:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        _fail("SCENE_SOURCE_POINTER_INVALID", "RFC6901 pointer required")
    current = value
    for token in pointer.split("/")[1:] if pointer else []:
        if re.search(r"~(?![01])", token):
            _fail("SCENE_SOURCE_POINTER_INVALID", pointer)
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(current):
            current = current[int(token)]
        else:
            _fail("SCENE_SOURCE_POINTER_INVALID", pointer)
    return current


def _provenance(scene: dict, manifest: dict, snapshot: dict) -> dict:
    state = scene["source_state"]
    _object(state, {"status", "source_id", "source_pointer", "source_sha256"}, "source_state")
    if state["status"] not in {"known", "offline_fixture"}:
        _fail("SCENE_SOURCE_UNKNOWN", "unknown geometry is not completed from text")
    _id(state["source_id"], "geometry source id")
    _sha(state["source_sha256"], "geometry source hash")
    sources = _rows(scene["geometry_provenance_catalog"], "source_id", "geometry provenance", nonempty=True)
    for record in sources.values():
        _object(record, {"source_id", "origin", "author", "text", "sha256"}, "geometry source")
        _sha(record["sha256"], "geometry source hash")
        if not isinstance(record["text"], str) or not record["text"].strip():
            _fail("SCENE_SOURCE_BINDING_INVALID", "nonempty explicit JSON source required")
        if hashlib.sha256(record["text"].encode("utf-8")).hexdigest() != record["sha256"]:
            _fail("SCENE_SOURCE_CHANGED", record["source_id"])
        if (record["origin"], record["author"]) not in {
            ("offline_fixture", "assistant"), ("explicit_geometry_declaration", "human")
        }:
            _fail("SCENE_SOURCE_ORIGIN_INVALID", "assistant geometry is only an offline fixture")
    record = sources.get(state["source_id"])
    if record is None or record["sha256"] != state["source_sha256"]:
        _fail("SCENE_SOURCE_BINDING_INVALID", "selected source/hash mismatch")
    expected = ("offline_fixture", "assistant") if state["status"] == "offline_fixture" else (
        "explicit_geometry_declaration", "human")
    if (record["origin"], record["author"]) != expected:
        _fail("SCENE_SOURCE_ORIGIN_INVALID", "source state cannot promote a fixture")
    if state["status"] == "known":
        bank = _rows(manifest.get("provenance_catalog"), "source_id", "manifest provenance")
        original = bank.get(record["source_id"])
        if (original is None or original.get("kind") != "user_declaration"
                or original.get("text") != record["text"] or original.get("sha256") != record["sha256"]):
            _fail("SCENE_INDEPENDENT_SOURCE_MISSING", "known geometry needs an independently bound user declaration")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail("SCENE_SOURCE_JSON_INVALID", "ambiguous duplicate JSON key: " + key)
            value[key] = item
        return value
    try:
        parsed = json.loads(record["text"], object_pairs_hook=unique_object,
                            parse_constant=lambda value: _fail("SCENE_NUMBER_INVALID", value))
    except (json.JSONDecodeError, TypeError):
        _fail("SCENE_SOURCE_JSON_INVALID", record["source_id"])
    actual = _json_pointer(parsed, state["source_pointer"])
    if _digest(actual) != _digest(snapshot):
        _fail("SCENE_GEOMETRY_SOURCE_MISMATCH", "every coordinate/state must equal the explicit source snapshot")
    return {"source_status": state["status"], "source_sha256": record["sha256"],
            "source_pointer": state["source_pointer"], "origin": record["origin"], "author": record["author"]}


def validate_scene(scene: dict, manifest: dict) -> dict:
    """Validate one explicit space snapshot; do not infer production geometry.

    A full existing shared manifest is passed unchanged. This gate verifies ID
    correspondence and its hash, not the manifest's full creative/production
    qualification. ``known`` geometry requires a same-ID exact original JSON
    user declaration in manifest.provenance_catalog; assistant fixtures use
    their separate scene geometry_provenance_catalog and remain provisional.
    """
    _object(scene, {"schema", "manifest_sha256", "script_sha256", "source_state",
                    "geometry_provenance_catalog", *_SNAPSHOT_KEYS}, "scene")
    if scene["schema"] != SCENE_SCHEMA:
        _fail("SCENE_CONTRACT_INVALID", "unsupported scene schema")
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        _fail("SCENE_MANIFEST_INVALID", "original shared manifest required")
    _sha(manifest.get("script_sha256"), "manifest script hash")
    if scene["manifest_sha256"] != _digest(manifest) or scene["script_sha256"] != manifest["script_sha256"]:
        _fail("SCENE_MANIFEST_MISMATCH", "manifest/script identity changed")
    if scene["units"] != "meters" or scene["coordinate_system"] != "Z_UP_RIGHT_HANDED":
        _fail("SCENE_SPACE_UNSUPPORTED", "explicit meters/Z_UP_RIGHT_HANDED required")
    actors = _rows(manifest.get("actors"), "id", "manifest actors", nonempty=True)
    props = _rows(manifest.get("props"), "id", "manifest props")
    scenes = _rows(manifest.get("scenes"), "id", "manifest scenes", nonempty=True)
    if set(actors) & set(props) or set(actors) & set(scenes) or set(props) & set(scenes):
        _fail("SCENE_DUPLICATE_ID", "stable IDs cannot overlap entity types")
    if scene["scene_id"] not in scenes:
        _fail("SCENE_ENTITY_UNBOUND", "scene is absent from original manifest")
    _id(scene["segment_id"], "segment id")
    _number(scene["time_seconds"], "time_seconds")
    if scene["time_seconds"] < 0:
        _fail("SCENE_NUMBER_INVALID", "time_seconds must be nonnegative")
    bounds = scene["bounds"]
    _object(bounds, {"min_m", "max_m"}, "bounds")
    _vector(bounds["min_m"], "bounds.min_m")
    _vector(bounds["max_m"], "bounds.max_m")
    if any(low >= high for low, high in zip(bounds["min_m"], bounds["max_m"])):
        _fail("SCENE_BOUNDS_INVALID", "nonempty bounds required")
    structures = _rows(scene["structures"], "structure_id", "space structures", nonempty=True)
    for sid, structure in structures.items():
        _object(structure, {"structure_id", "role", "scene_id", "pose", "proxy"}, "structure")
        if sid in actors or sid in props or sid in scenes:
            _fail("SCENE_DUPLICATE_ID", "environment structure cannot impersonate a cast/prop/scene id")
        if structure["scene_id"] != scene["scene_id"]:
            _fail("SCENE_SPACE_MIXED", sid)
        if structure["role"] not in {"table", "chair", "wall", "door", "floor", "other"}:
            _fail("SCENE_PROXY_INVALID", "explicit closed environment role required")
        _object(structure["pose"], {"position_m", "rotation_deg"}, "structure pose")
        _vector(structure["pose"]["position_m"], "structure.position_m")
        _vector(structure["pose"]["rotation_deg"], "structure.rotation_deg")
        _object(structure["proxy"], {"shape", "size_m"}, "structure proxy")
        if structure["proxy"]["shape"] != "box":
            _fail("SCENE_PROXY_INVALID", "environment uses explicit box proxies")
        _vector(structure["proxy"]["size_m"], "structure.size_m", positive=True)
        if any(pos < low or pos > high for pos, low, high in zip(
                structure["pose"]["position_m"], bounds["min_m"], bounds["max_m"])):
            _fail("SCENE_ENTITY_OUTSIDE_BOUNDS", sid)
    entities = _rows(scene["entities"], "entity_id", "scene entities", nonempty=True)
    if {eid for eid, row in entities.items() if row.get("entity_type") == "actor"} != set(actors) or {
        eid for eid, row in entities.items() if row.get("entity_type") == "prop"} != set(props):
        _fail("SCENE_CAST_NOT_CLOSED", "declare every manifest actor/prop present or explicitly absent")
    for eid, entity in entities.items():
        _object(entity, {"entity_id", "entity_type", "scene_id", "presence", "pose", "proxy", "state"}, "entity")
        kind = entity["entity_type"]
        if kind not in {"actor", "prop"} or eid not in (actors if kind == "actor" else props):
            _fail("SCENE_ENTITY_UNBOUND", eid)
        if entity["scene_id"] != scene["scene_id"]:
            _fail("SCENE_SPACE_MIXED", "one snapshot cannot merge unrelated spaces")
        if entity["presence"] not in {"present", "absent"}:
            _fail("SCENE_POSE_UNKNOWN", "presence must be explicit")
        if entity["presence"] == "absent":
            expected_state = {"posture": None} if kind == "actor" else {"holder_actor_id": None, "support": None}
            if entity["pose"] is not None or entity["proxy"] is not None or entity["state"] != expected_state:
                _fail("SCENE_ABSENT_STATE_INVALID", "absent entity cannot assert a present pose or action")
            continue
        _object(entity["pose"], {"position_m", "rotation_deg"}, "pose")
        _vector(entity["pose"]["position_m"], "pose.position_m")
        _vector(entity["pose"]["rotation_deg"], "pose.rotation_deg")
        _object(entity["proxy"], {"shape", "size_m"}, "proxy")
        if entity["proxy"]["shape"] != ("capsule" if kind == "actor" else "box"):
            _fail("SCENE_PROXY_INVALID", "only explicit white actor capsules/prop boxes supported")
        _vector(entity["proxy"]["size_m"], "proxy.size_m", positive=True)
        if any(position < low or position > high for position, low, high in zip(
                entity["pose"]["position_m"], bounds["min_m"], bounds["max_m"])):
            _fail("SCENE_ENTITY_OUTSIDE_BOUNDS", eid)
        if kind == "actor":
            _object(entity["state"], {"posture"}, "actor state")
            if entity["state"]["posture"] not in {"seated", "standing", "walking"}:
                _fail("SCENE_POSE_UNKNOWN", eid)
        else:
            _object(entity["state"], {"holder_actor_id", "support"}, "prop state")
            holder = entity["state"]["holder_actor_id"]
            if holder is not None:
                _id(holder, "prop holder id")
            if holder is not None and (holder not in entities or entities[holder]["entity_type"] != "actor"
                                       or entities[holder].get("presence") != "present"):
                _fail("SCENE_PROP_HOLDER_INVALID", eid)
            support = entity["state"]["support"]
            if support is not None:
                _object(support, {"entity_type", "entity_id"}, "support")
                _id(support["entity_id"], "prop support id")
                if support["entity_type"] == "scene":
                    valid = support["entity_id"] == scene["scene_id"]
                elif support["entity_type"] == "structure":
                    valid = support["entity_id"] in structures
                else:
                    other = entities.get(support["entity_id"])
                    valid = (support["entity_type"] in {"actor", "prop"} and other is not None
                             and other["entity_type"] == support["entity_type"] and support["entity_id"] != eid
                             and other.get("presence") == "present")
                if not valid:
                    _fail("SCENE_PROP_SUPPORT_INVALID", eid)
    # Supporting prop cycles do not define a usable physical arrangement.
    for eid, entity in entities.items():
        seen, current = set(), entity
        while current["entity_type"] == "prop" and current["state"]["support"] is not None:
            if current["entity_id"] in seen:
                _fail("SCENE_PROP_SUPPORT_CYCLE", eid)
            seen.add(current["entity_id"])
            support = current["state"]["support"]
            if support["entity_type"] != "prop":
                break
            current = entities[support["entity_id"]]
    camera = scene["camera"]
    _object(camera, {"camera_id", "position_m", "target_m", "focal_length_mm", "sensor_width_mm", "render_size_px"}, "camera")
    _id(camera["camera_id"], "camera id")
    if camera["camera_id"] in entities or camera["camera_id"] in scenes or camera["camera_id"] in structures:
        _fail("SCENE_DUPLICATE_ID", "camera id")
    _vector(camera["position_m"], "camera.position_m")
    _vector(camera["target_m"], "camera.target_m")
    if camera["position_m"] == camera["target_m"]:
        _fail("SCENE_CAMERA_INVALID", "camera needs a distinct target")
    for field in ("focal_length_mm", "sensor_width_mm"):
        _number(camera[field], "camera." + field, positive=True)
    size = camera["render_size_px"]
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or not 16 <= v <= 4096 for v in size):
        _fail("SCENE_CAMERA_INVALID", "explicit render size from 16 to 4096 pixels required")
    snapshot = {key: deepcopy(scene[key]) for key in _SNAPSHOT_KEYS}
    source = _provenance(scene, manifest, snapshot)
    provisional = source["origin"] == "offline_fixture"
    return {"schema": SCENE_SCHEMA + "/validation", "status": "scene_valid",
            "scene_sha256": _digest(scene), "manifest_sha256": _digest(manifest),
            "script_sha256": manifest["script_sha256"], "scene_id": scene["scene_id"],
            "entity_ids": list(entities), "structure_ids": list(structures), "segment_id": scene["segment_id"],
            "geometry_source": source, "provisional": provisional,
            "geometry_not_native_source": True, "assistant_pixel_identity_verified": False,
            "physics_simulated": False, "director_desk_format_compatible": False,
            "production_adopted": False, "calls_authorized": False, "new_paid_calls": 0}


def build_previs_bundle(scene: dict, manifest: dict) -> dict:
    """Return deterministic JSON + Blender Python white-model text, without IO.

    The script creates a NEW Blender scene, leaving preexisting scenes intact.
    It does not render, save, spawn a process, load assets or execute source text.
    The caller may separately choose to render this local proxy preview; it is
    not frame extraction or verification of generated video.
    """
    validation = validate_scene(scene, manifest)
    text = json.dumps(scene, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    snapshot = {key: deepcopy(scene[key]) for key in _SNAPSHOT_KEYS}
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    script = '''# creative_studio_scene/v1 — local provisional white models, no physics.
# Own format; not DirectorDesk .director and not a generated-video review.
import bpy
import json
import math
from mathutils import Vector

DATA = json.loads(SNAPSHOT_LITERAL)

def bind_snapshot(obj):
    # Blender names are display labels: repeated exports may append .001.
    # Stable contract IDs live in properties, qualified by this snapshot.
    obj["scene_id"] = DATA["scene_id"]
    obj["segment_id"] = DATA["segment_id"]
    return obj

scene = bind_snapshot(bpy.data.scenes.new("creative_studio_previs"))
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
collection = bpy.data.collections.new("creative_studio_proxies")
scene.collection.children.link(collection)
white = bpy.data.materials.new("creative_studio_white")
white.diffuse_color = (0.8, 0.8, 0.8, 1.0)
world = bpy.data.worlds.new("creative_studio_preview_world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.15, 0.15, 0.15, 1.0)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
scene.world = world
sun_data = bpy.data.lights.new("creative_studio_display_sun", "SUN")
sun_data.energy = 2.5
sun = bind_snapshot(bpy.data.objects.new("creative_studio_display_sun", sun_data))
collection.objects.link(sun)
sun.rotation_euler = (0.5, -0.5, -0.4)

def attach(obj):
    for previous in list(obj.users_collection):
        previous.objects.unlink(obj)
    collection.objects.link(obj)
    if getattr(obj.data, "materials", None) is not None:
        obj.data.materials.append(white)
    return bind_snapshot(obj)

def capsule(size):
    sx, sy, sz = size
    rz = min(sx, sy, sz) / 2
    middle = max(0, sz / 2 - rz)
    rings = [(-middle + rz * math.sin(-math.pi / 2 + j * math.pi / 16),
              math.cos(-math.pi / 2 + j * math.pi / 16)) for j in range(9)]
    rings += [(middle + rz * math.sin(j * math.pi / 16), math.cos(j * math.pi / 16)) for j in range(9)]
    verts = [(sx / 2 * radius * math.cos(i * math.pi / 8),
              sy / 2 * radius * math.sin(i * math.pi / 8), z)
             for z, radius in rings for i in range(16)]
    faces = [(j * 16 + i, j * 16 + (i + 1) % 16,
              (j + 1) * 16 + (i + 1) % 16, (j + 1) * 16 + i)
             for j in range(len(rings) - 1) for i in range(16)]
    mesh = bpy.data.meshes.new("creative_studio_capsule")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return bpy.data.objects.new("creative_studio_actor_proxy", mesh)

for entity in DATA["entities"]:
    if entity["presence"] == "absent":
        continue
    # Capsules are generic geometry proxies, never actor portraits or rigged performances.
    if entity["proxy"]["shape"] == "capsule":
        obj = attach(capsule(entity["proxy"]["size_m"]))
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        obj = attach(bpy.context.object)
    obj.name = entity["entity_id"]
    obj.location = entity["pose"]["position_m"]
    obj.rotation_euler = tuple(math.radians(v) for v in entity["pose"]["rotation_deg"])
    obj.dimensions = entity["proxy"]["size_m"]
    obj["entity_id"] = entity["entity_id"]
    obj["entity_type"] = entity["entity_type"]
    obj["declared_state_json"] = json.dumps(entity["state"], ensure_ascii=False, sort_keys=True)

for structure in DATA["structures"]:
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = attach(bpy.context.object)
    obj.name = structure["structure_id"]
    obj.location = structure["pose"]["position_m"]
    obj.rotation_euler = tuple(math.radians(v) for v in structure["pose"]["rotation_deg"])
    obj.dimensions = structure["proxy"]["size_m"]
    obj["structure_id"] = structure["structure_id"]
    obj["environment_role"] = structure["role"]

lo, hi = DATA["bounds"]["min_m"], DATA["bounds"]["max_m"]
bpy.ops.mesh.primitive_cube_add(size=1.0)
floor = attach(bpy.context.object)
floor.name = "creative_studio_floor_proxy"
floor.location = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] - 0.025)
floor.dimensions = (hi[0] - lo[0], hi[1] - lo[1], 0.05)

camera_data = bpy.data.cameras.new(DATA["camera"]["camera_id"])
camera = bind_snapshot(bpy.data.objects.new(DATA["camera"]["camera_id"], camera_data))
camera["camera_id"] = DATA["camera"]["camera_id"]
collection.objects.link(camera)
camera.location = DATA["camera"]["position_m"]
direction = Vector(DATA["camera"]["target_m"]) - camera.location
camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
camera_data.lens = DATA["camera"]["focal_length_mm"]
camera_data.sensor_width = DATA["camera"]["sensor_width_mm"]
scene.camera = camera
scene.render.resolution_x, scene.render.resolution_y = DATA["camera"]["render_size_px"]
scene.render.resolution_percentage = 100
scene["creative_studio_geometry_provisional"] = PROVISIONAL_LITERAL
scene["creative_studio_source_sha256"] = SOURCE_HASH_LITERAL
if bpy.context.window is not None:
    bpy.context.window.scene = scene
'''.replace("PROVISIONAL_LITERAL", repr(validation["provisional"]), 1).replace(
        "SOURCE_HASH_LITERAL", repr(validation["geometry_source"]["source_sha256"]), 1).replace(
        "SNAPSHOT_LITERAL", repr(snapshot_json), 1)
    return {"schema": SCENE_SCHEMA + "/previs_bundle", "validation": validation,
            "scene": deepcopy(scene), "scene_json": text,
            "scene_json_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "blender_python": script, "blender_python_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
            "export_format": SCENE_SCHEMA, "renders_executed": 0, "new_paid_calls": 0,
            "calls_authorized": False, "production_adopted": False, "human_review_status": "not_applicable_local_proxy"}


def compile_reference_projection(binding_contract: dict, selected_asset_ids: list[str], *, mode: str,
        payload: dict | None = None, messages: list | None = None, now,
        expected_account_binding_sha256=None, provider_get_evidence=None,
        expected_continuation=None, required_entities=None) -> dict:
    """Select explicit actual order and delegate qualification to v4.

    Exactly one of payload (media request) or messages (director image inputs)
    is required. This projection can select/reorder original assets, but cannot
    change their roles/mode, invent subjects/qualification, weaken required
    identities, or replace a formal first frame with a general reference.
    Existing v4 ReferenceCompilerError is propagated unchanged.
    """
    if not isinstance(binding_contract, dict) or binding_contract.get("mode") != mode or mode not in {
        "first_frame", "multimodal_reference"
    }:
        _fail("STUDIO_REFERENCE_MODE_MISMATCH", "mode must equal its original explicit binding")
    if (payload is None) == (messages is None):
        _fail("STUDIO_REFERENCE_CHANNEL_INVALID", "provide exactly one original payload/messages")
    assets = _rows(binding_contract.get("assets"), "asset_id", "bound reference assets", nonempty=True)
    if (not isinstance(selected_asset_ids, list) or not selected_asset_ids
            or any(not isinstance(aid, str) or aid not in assets for aid in selected_asset_ids)
            or len(set(selected_asset_ids)) != len(selected_asset_ids)):
        _fail("STUDIO_REFERENCE_SELECTION_INVALID", "explicit unique existing asset IDs required")
    original_roles = [asset.get("role") for asset in assets.values()]
    if (mode == "first_frame" and (len(original_roles) != 1 or original_roles != ["first_frame"])) or (
        mode == "multimodal_reference" and any(role in {"first_frame", "last_frame"} for role in original_roles)
    ):
        _fail("STUDIO_REFERENCE_MODE_MIXED", "original frame/reference modes cannot be filtered into compliance")
    selected = deepcopy(binding_contract)
    selected["assets"] = [deepcopy(assets[aid]) for aid in selected_asset_ids]
    if not isinstance(selected.get("entity_bindings"), list) or any(
            not isinstance(row, dict) for row in selected["entity_bindings"]):
        _fail("STUDIO_REFERENCE_SELECTION_INVALID", "original entity bindings required")
    selected["entity_bindings"] = [row for row in selected["entity_bindings"] if row.get("asset_id") in selected_asset_ids]
    expected_required = deepcopy(binding_contract.get("required_entities"))
    if not isinstance(expected_required, list) or any(not isinstance(row, dict) for row in expected_required):
        _fail("STUDIO_REQUIRED_ENTITY_SCOPE_CHANGED", "original required entities must be explicit")
    if messages is not None:
        expected_required = [row for row in expected_required if row.get("entity_type") in {"actor", "scene"}]
    if required_entities is not None and required_entities != expected_required:
        _fail("STUDIO_REQUIRED_ENTITY_SCOPE_CHANGED", "selected references cannot weaken original required entities")
    kwargs = {"now": now, "expected_account_binding_sha256": expected_account_binding_sha256,
              "provider_get_evidence": provider_get_evidence, "expected_continuation": expected_continuation}
    if messages is not None:
        result = reference_compiler.build_director_visual_messages(messages, selected,
            selected_asset_ids, required_entities=expected_required, **kwargs)
        ordered = result["coverage"]["ordered_images"]
        channel = "director_messages"
    else:
        result = reference_compiler.compile_reference_request(payload, selected, **kwargs)
        ordered = result["coverage"]["ordered_references"]
        channel = "media_payload"
    mapping = result["coverage"]["entity_asset_mapping"]
    ordered_roles = [{**deepcopy(row), "kind": assets[row["asset_id"]]["kind"],
                      "role": assets[row["asset_id"]]["role"],
                      "subjects": [deepcopy(subject) for subject in mapping if subject["asset_id"] == row["asset_id"]]}
                     for row in ordered]
    return {"schema": PROJECTION_SCHEMA, "channel": channel, "input_mode": mode,
            "selected_asset_ids": deepcopy(selected_asset_ids), "selected_binding_contract": selected,
            "compiler_result": result, "ordered_roles": ordered_roles,
            "geometry_used_as_identity_material": False, "calls_authorized": False,
            "new_paid_calls": 0, "production_adopted": False,
            "media_status_after_save": "awaiting_human_review"}


def validate_scene_sequence(scenes: list[dict], manifest: dict) -> dict:
    """Validate static snapshots sharing a closed space; no motion inference.

    Segment IDs and start times are explicit and unique/increasing. Bounds and
    structural ID/pose/size/role sets must stay identical. Cast/prop IDs remain
    closed to the shared manifest; absent actors keep IDs and explicit absence.
    Camera and present entity poses may vary only in their individually bound
    geometry declarations. This does not certify the causal transition itself.
    """
    if not isinstance(scenes, list) or not scenes:
        _fail("SCENE_SEQUENCE_INVALID", "nonempty explicit snapshots required")
    validated = [validate_scene(scene, manifest) for scene in scenes]
    first, seen, previous = scenes[0], set(), None
    layout = {row["structure_id"]: row for row in first["structures"]}
    proxies = {}
    for scene in scenes:
        segment = scene["segment_id"]
        if segment in seen or (previous is not None and scene["time_seconds"] <= previous):
            _fail("SCENE_SEQUENCE_ORDER_INVALID", "unique segment ids and strictly increasing explicit times required")
        seen.add(segment)
        previous = scene["time_seconds"]
        if (scene["scene_id"] != first["scene_id"] or scene["units"] != first["units"]
                or scene["coordinate_system"] != first["coordinate_system"] or scene["bounds"] != first["bounds"]
                or {row["structure_id"]: row for row in scene["structures"]} != layout):
            _fail("SCENE_SEQUENCE_LAYOUT_CHANGED", "shared space/bounds/structures cannot silently change")
        for entity in scene["entities"]:
            if entity["presence"] == "absent":
                continue
            eid = entity["entity_id"]
            if eid in proxies and entity["proxy"] != proxies[eid]:
                _fail("SCENE_SEQUENCE_PROXY_CHANGED", eid)
            proxies[eid] = deepcopy(entity["proxy"])
    return {"schema": SCENE_SCHEMA + "/sequence_validation", "status": "scene_sequence_valid",
            "sequence_sha256": _digest(scenes), "manifest_sha256": _digest(manifest),
            "scene_id": first["scene_id"], "segment_ids": [scene["segment_id"] for scene in scenes],
            "snapshot_validations": validated, "shared_layout_sha256": _digest(layout),
            "provisional": any(row["provisional"] for row in validated),
            "geometry_not_native_source": True, "motion_validated": False, "physics_simulated": False,
            "production_adopted": False, "new_paid_calls": 0, "calls_authorized": False}


def build_previs_sequence(scenes: list[dict], manifest: dict) -> dict:
    """Export independent static white-model bundles after shared-space checks."""
    validation = validate_scene_sequence(scenes, manifest)
    return {"schema": SCENE_SCHEMA + "/previs_sequence", "validation": validation,
            "bundles": [build_previs_bundle(scene, manifest) for scene in scenes],
            "renders_executed": 0, "new_paid_calls": 0, "production_adopted": False}


def build_offline_previs_example(manifest: dict, *, scene_id: str | None = None) -> dict:
    """An ASSISTANT fixture, not reconstruction of the original room/people.

    This helper reuses IDs only. Every dimension, placement, pose, furniture and
    camera is an explicit synthetic example, independently labeled and never
    inserted into the shared manifest. It demonstrates two static cameras in
    one shared room; no actor face/voice, original frame or performance claimed.
    """
    if not isinstance(manifest, dict):
        _fail("SCENE_MANIFEST_INVALID", "manifest required")
    room_ids = list(_rows(manifest.get("scenes"), "id", "manifest scenes", nonempty=True))
    if scene_id is None:
        if len(room_ids) != 1:
            _fail("SCENE_SPACE_UNKNOWN", "choose an explicit scene ID for a multi-space manifest")
        scene_id = room_ids[0]
    if scene_id not in room_ids:
        _fail("SCENE_ENTITY_UNBOUND", "chosen example scene ID is not in manifest")
    actor_ids = list(_rows(manifest.get("actors"), "id", "manifest actors", nonempty=True))
    prop_ids = list(_rows(manifest.get("props"), "id", "manifest props"))
    if len(actor_ids) > 4 or len(prop_ids) > 20:
        _fail("SCENE_EXAMPLE_LIMIT", "small explicit example supports up to 4 actors/20 props")
    def box(sid, role, position, size):
        return {"structure_id": sid, "role": role, "scene_id": scene_id,
                "pose": {"position_m": position, "rotation_deg": [0, 0, 0]},
                "proxy": {"shape": "box", "size_m": size}}
    structures = [box("env_tabletop", "table", [0, 0, 0.75], [1.5, 1.1, 0.08]),
                  box("env_wall_back", "wall", [-0.7, 1.95, 1.5], [4.4, 0.1, 3]),
                  box("env_wall_right", "wall", [2.95, 0, 1.5], [0.1, 4, 3]),
                  box("env_door", "door", [2.1, 1.95, 1.1], [1, 0.1, 2.2])]
    for index, (x, y) in enumerate(((-0.65, -0.45), (-0.65, 0.45), (0.65, -0.45), (0.65, 0.45))):
        structures.append(box("env_table_leg_" + str(index), "table", [x, y, 0.35], [0.06, 0.06, 0.7]))
    entities = []
    for index, aid in enumerate(actor_ids):
        position = [-1.1 if index % 2 == 0 else 1.1, -0.3 + (index // 2) * 0.7, 1]
        entities.append({"entity_id": aid, "entity_type": "actor", "scene_id": scene_id, "presence": "present",
            "pose": {"position_m": position, "rotation_deg": [0, 0, -90 if index % 2 == 0 else 90]},
            "proxy": {"shape": "capsule", "size_m": [0.5, 0.4, 1.5]}, "state": {"posture": "seated"}})
        structures.append(box("env_chair_seat_" + str(index), "chair", [position[0], position[1], 0.45], [0.6, 0.6, 0.08]))
        structures.append(box("env_chair_back_" + str(index), "chair",
            [position[0] + (-0.3 if index % 2 == 0 else 0.3), position[1], 0.8], [0.08, 0.6, 0.7]))
        for leg, (dx, dy) in enumerate(((-0.24, -0.24), (-0.24, 0.24), (0.24, -0.24), (0.24, 0.24))):
            structures.append(box("env_chair_leg_" + str(index) + "_" + str(leg), "chair",
                [position[0] + dx, position[1] + dy, 0.2], [0.04, 0.04, 0.4]))
    for index, pid in enumerate(prop_ids):
        entities.append({"entity_id": pid, "entity_type": "prop", "scene_id": scene_id, "presence": "present",
            "pose": {"position_m": [-0.5 + (index % 5) * 0.23, -0.35 + (index // 5) * 0.23, 0.82], "rotation_deg": [0, 0, 0]},
            "proxy": {"shape": "box", "size_m": [0.12, 0.12, 0.05]},
            "state": {"holder_actor_id": None, "support": {"entity_type": "structure", "entity_id": "env_tabletop"}}})
    examples = []
    for index, camera_position in enumerate(([0, -1.9, 1.7], [-2.3, -1.5, 1.8])):
        snapshot = {"units": "meters", "coordinate_system": "Z_UP_RIGHT_HANDED", "scene_id": scene_id,
            "segment_id": "OFFLINE_M00" + str(index + 1), "time_seconds": index * 4,
            "bounds": {"min_m": [-3, -2, 0], "max_m": [3, 2, 3]},
            "structures": deepcopy(structures), "entities": deepcopy(entities),
            "camera": {"camera_id": "offline_camera_" + str(index + 1), "position_m": camera_position,
                       "target_m": [0, 0, 1], "focal_length_mm": 24, "sensor_width_mm": 36,
                       "render_size_px": [640, 360]}}
        text = json.dumps({"snapshot": snapshot}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        sid = "offline_geometry_" + str(index + 1)
        examples.append({"schema": SCENE_SCHEMA, "manifest_sha256": _digest(manifest),
            "script_sha256": manifest.get("script_sha256"), **snapshot,
            "source_state": {"status": "offline_fixture", "source_id": sid, "source_pointer": "/snapshot", "source_sha256": sha},
            "geometry_provenance_catalog": [{"source_id": sid, "origin": "offline_fixture", "author": "assistant", "text": text, "sha256": sha}]})
    validate_scene_sequence(examples, manifest)
    return {"scenes": examples, "provisional": True, "geometry_not_native_source": True,
            "manifest_sha256": _digest(manifest), "new_paid_calls": 0, "production_adopted": False}
